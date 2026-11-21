"""Copernicus DEM 30 m: cell naming, tile fetch, ring crop, adapter.

Measured behaviour (spec 7.5): every remote read of a tile transfers the whole
~34 MB object, including a single-pixel read. So this module downloads the tile
once, crops locally, and deletes it. A ring is covered by the single cell
containing its centre; crossing a cell boundary clips and is flagged.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
import rasterio
import requests

from .base import Extent, ProviderError

BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
SOURCE_RESOLUTION_M = 30
TILE_MAX_BYTES = 80_000_000


def tile_name(lat: float, lon: float) -> str:
    """Name of the 1-degree cell containing the point, by its SW corner."""
    south = math.floor(lat)
    west = math.floor(lon)
    ns = "N" if south >= 0 else "S"
    ew = "E" if west >= 0 else "W"
    return (f"Copernicus_DSM_COG_10_{ns}{abs(south):02d}_00_"
            f"{ew}{abs(west):03d}_00_DEM")


def tile_url(name: str) -> str:
    return f"{BASE_URL}/{name}/{name}.tif"


def cell_bounds(name: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) parsed back out of a tile name."""
    parts = name.split("_")
    try:
        lat_part, lon_part = parts[4], parts[6]
        south = int(lat_part[1:]) * (1 if lat_part[0] == "N" else -1)
        west = int(lon_part[1:]) * (1 if lon_part[0] == "E" else -1)
    except (IndexError, ValueError):
        raise ValueError(f"not a Copernicus tile name: {name!r}") from None
    return float(west), float(south), float(west + 1), float(south + 1)


def fetch_tile(name: str, dest: Path, *, timeout: int = 45,
               deadline_s: float = 120.0, max_bytes: int = TILE_MAX_BYTES,
               getter=None) -> Path:
    """Stream one tile to `dest`, refusing short reads, overruns and stalls.

    `timeout` is the per-read socket timeout; `deadline_s` is the total wall
    clock budget, because a trickling connection can satisfy the former forever
    while holding the gateway's single-flight claim.
    """
    caller = getter or requests.get
    try:
        resp = caller(tile_url(name), stream=True, timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError("network", f"{type(exc).__name__}: {exc}") from None
    if resp.status_code >= 400:
        raise ProviderError("http", f"HTTP {resp.status_code} for {name}")

    expected = resp.headers.get("Content-Length")
    written = 0
    started = time.monotonic()
    dest = Path(dest)
    try:
        with open(dest, "wb") as handle:
            for chunk in resp.iter_content(1 << 20):
                if time.monotonic() - started > deadline_s:
                    raise ProviderError("network",
                                        f"tile fetch exceeded {deadline_s}s")
                written += len(chunk)
                if written > max_bytes:
                    raise ProviderError("http", f"tile exceeds {max_bytes} bytes")
                handle.write(chunk)
        if expected is not None and int(expected) != written:
            raise ProviderError("network",
                                f"short read: {written} of {expected} bytes")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def crop_dem(source, extent: Extent, size: int = 256) -> dict:
    """Crop the source (local path or remote COG URL) to the ring."""
    from rasterio.windows import from_bounds

    # Remote opens have no Python-level timeout; without these a stalled
    # request hangs the refresh forever. Same guard as the imagery path.
    with rasterio.Env(GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_CONNECTTIMEOUT="10",
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        try:
            with rasterio.open(source) as ds:
                bounds = ds.bounds
                west = max(extent.west, bounds.left)
                south = max(extent.south, bounds.bottom)
                east = min(extent.east, bounds.right)
                north = min(extent.north, bounds.top)
                clipped = (west > extent.west or south > extent.south
                           or east < extent.east or north < extent.north)
                if west >= east or south >= north:
                    raise ProviderError("parse", "ring lies outside the DEM tile")
                window = from_bounds(west, south, east, north, transform=ds.transform)
                window = window.round_offsets().round_lengths()
                array = ds.read(1, window=window, boundless=False)
                nodata = ds.nodata
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("network", f"DEM read failed: {type(exc).__name__}") from None

    data = array.astype("float64")
    if nodata is not None:
        data[data == nodata] = np.nan
    data[~np.isfinite(data)] = np.nan
    nodata_px = int(np.isnan(data).sum())

    finite = data[np.isfinite(data)]
    fill = float(np.median(finite)) if finite.size else 0.0
    data = np.where(np.isfinite(data), data, fill)

    height, width = data.shape
    rows = (np.arange(size) * (height / size)).astype(int).clip(0, height - 1)
    cols = (np.arange(size) * (width / size)).astype(int).clip(0, width - 1)
    small = data[rows][:, cols]

    heightmap = {
        "mission_id": "context",
        "width": int(size),
        "height": int(size),
        "west": float(west),
        "south": float(south),
        "east": float(east),
        "north": float(north),
        "height_scale_m": 1.0,
        "geoid_offset_m": 0.0,
        "base_height_m": 0.0,
        "h_min": float(small.min()),
        "h_max": float(small.max()),
        "heights_m": [float(v) for v in small.ravel()],
    }
    return {
        "heightmap": heightmap,
        "clipped": bool(clipped),
        "nodata_px": nodata_px,
        "bbox": {"west": float(west), "south": float(south),
                 "east": float(east), "north": float(north)},
    }


ASSET_NAME = "context_dem.json"


def tiles_for(extent: Extent) -> list[str]:
    """Every 1-degree cell the box touches, by SW corner (no duplicates)."""
    south, north = math.floor(extent.south), math.floor(extent.north)
    west, east = math.floor(extent.west), math.floor(extent.east)
    names: list[str] = []
    for lat in range(south, north + 1):
        for lon in range(west, east + 1):
            name = tile_name(float(lat), float(lon))
            if name not in names:
                names.append(name)
    return names


def crop_dem_mosaic(extent: Extent, size: int = 256, *, source_for=None) -> dict:
    """Stitch every tile the box touches into one heightmap.

    Tiles are EPSG:4326, so no reprojection is involved: each tile's intersection
    with the box maps proportionally to a destination rectangle in the output
    grid. Reads pass `out_shape` so GDAL serves an overview instead of full
    resolution — that is what makes a 60 km box affordable.
    """
    from rasterio.windows import from_bounds

    resolve = source_for or tile_url
    grid = np.full((size, size), np.nan, dtype="float64")
    used: list[str] = []
    missing: list[str] = []
    covered = 0

    span_lon = (extent.east - extent.west) or 1e-12
    span_lat = (extent.north - extent.south) or 1e-12

    with rasterio.Env(GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_CONNECTTIMEOUT="10",
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for name in tiles_for(extent):
            try:
                source = resolve(name)
                with rasterio.open(source) as ds:
                    b = ds.bounds
                    west = max(extent.west, b.left)
                    south = max(extent.south, b.bottom)
                    east = min(extent.east, b.right)
                    north = min(extent.north, b.top)
                    if west >= east or south >= north:
                        continue     # touches a corner only
                    x0 = int(round((west - extent.west) / span_lon * size))
                    x1 = int(round((east - extent.west) / span_lon * size))
                    y0 = int(round((extent.north - north) / span_lat * size))
                    y1 = int(round((extent.north - south) / span_lat * size))
                    x1 = min(size, max(x1, x0 + 1))
                    y1 = min(size, max(y1, y0 + 1))
                    window = from_bounds(west, south, east, north,
                                         transform=ds.transform)
                    block = ds.read(1, window=window, boundless=False,
                                    out_shape=(y1 - y0, x1 - x0)).astype("float64")
                    if ds.nodata is not None:
                        block[block == ds.nodata] = np.nan
                    grid[y0:y1, x0:x1] = block
                    used.append(name)
                    covered += (x1 - x0) * (y1 - y0)
            except Exception:
                missing.append(name)
                continue

    finite = grid[np.isfinite(grid)]
    if not finite.size:
        raise ProviderError("parse", "no DEM tile covered the ring")
    fill = float(np.median(finite))
    holes = int((~np.isfinite(grid)).sum())
    grid = np.where(np.isfinite(grid), grid, fill)

    heightmap = {
        "mission_id": "context",
        "width": int(size),
        "height": int(size),
        "west": float(extent.west),
        "south": float(extent.south),
        "east": float(extent.east),
        "north": float(extent.north),
        "height_scale_m": 1.0,
        "geoid_offset_m": 0.0,
        "base_height_m": 0.0,
        "h_min": float(grid.min()),
        "h_max": float(grid.max()),
        "heights_m": [float(v) for v in grid.ravel()],
    }
    return {
        "heightmap": heightmap,
        "clipped": bool(missing) or (covered / (size * size)) < 0.995,
        "nodata_px": holes,
        "tiles": used,
        "missing_tiles": missing,
        "coverage": round(covered / (size * size), 4),
        "bbox": {"west": float(extent.west), "south": float(extent.south),
                 "east": float(extent.east), "north": float(extent.north)},
    }


class CopernicusDemProvider:
    """30 m context terrain. One full tile per ring; see spec 7.5."""

    id = "copernicus-dem"
    key = "context_dem"
    source_label = "Copernicus DEM"
    licence = "Copernicus DEM (c) ESA, DLR - free, attribution required"
    attribution = "Copernicus DEM 30 m, ESA/DLR, via AWS Open Data"
    ttl_s = 2_592_000
    fetch_timeout_s = 45
    allow_inline = False
    requires: tuple[str, ...] = ()

    def __init__(self, *, tile_fetcher=None, size: int = 256,
                 window_km: float | None = None, key: str = "context_dem",
                 asset: str = ASSET_NAME,
                 source_label: str | None = None) -> None:
        # None means "read the remote COG window directly". A callable is a test
        # seam that yields a local file, which is how the parser tests run offline.
        self.tile_fetcher = tile_fetcher
        self.size = size
        # window_km expands the mission ring to a fixed box around its centre:
        # the wide Regional DEM. None keeps the caller's ring (15 km).
        self.window_km = window_km
        self.key = key
        self.asset = asset
        if source_label:
            self.source_label = source_label

    def fetch(self, extent: Extent, cfg) -> "ProviderPayload":
        import json
        import shutil
        import tempfile

        from .base import ProviderPayload
        from .geo import square_extent

        if self.window_km:
            lat, lon = extent.centre
            extent = square_extent(lat, lon, self.window_km / 2)

        name = tile_name(*extent.centre)
        try:
            if self.tile_fetcher is None:
                # Windowed read straight from the COGs, stitched across tiles.
                cropped = crop_dem_mosaic(extent, size=self.size)
            else:
                workdir = Path(tempfile.mkdtemp(prefix="pyroscan-dem-"))
                try:
                    def local(name_: str) -> Path:
                        return self.tile_fetcher(name_, workdir / f"{name_}.tif")
                    cropped = crop_dem_mosaic(extent, size=self.size,
                                              source_for=local)
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("parse", f"DEM crop failed: {exc}") from None

        blob = json.dumps(cropped["heightmap"], ensure_ascii=False).encode("utf-8")
        heightmap = cropped["heightmap"]
        data = {
            "bbox": cropped["bbox"],
            "width": heightmap["width"],
            "height": heightmap["height"],
            "h_min": heightmap["h_min"],
            "h_max": heightmap["h_max"],
            "asset": self.asset,
            "source_resolution_m": SOURCE_RESOLUTION_M,
            "clipped": cropped["clipped"],
            "nodata_px": cropped["nodata_px"],
            "source_tile": name,
            "tiles": cropped.get("tiles", [name]),
            "coverage": cropped.get("coverage", 1.0),
            "window_km": self.window_km,
        }
        return ProviderPayload(data, None,
                               extra={"asset_name": self.asset, "asset_bytes": blob})
