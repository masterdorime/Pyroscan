"""Copernicus DEM 30 m: cell naming, tile fetch, ring crop, adapter.

Measured behaviour (spec 7.5): every remote read of a tile transfers the whole
~34 MB object, including a single-pixel read. So this module downloads the tile
once, crops locally, and deletes it. A ring is covered by the single cell
containing its centre; crossing a cell boundary clips and is flagged.
"""
from __future__ import annotations

import math
from pathlib import Path

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
               max_bytes: int = TILE_MAX_BYTES, getter=None) -> Path:
    """Stream one tile to `dest`, refusing short reads and oversized objects."""
    caller = getter or requests.get
    try:
        resp = caller(tile_url(name), stream=True, timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError("network", f"{type(exc).__name__}: {exc}") from None
    if resp.status_code >= 400:
        raise ProviderError("http", f"HTTP {resp.status_code} for {name}")

    expected = resp.headers.get("Content-Length")
    written = 0
    dest = Path(dest)
    try:
        with open(dest, "wb") as handle:
            for chunk in resp.iter_content(1 << 20):
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


def crop_dem(tile_path: Path, extent: Extent, size: int = 256) -> dict:
    """Crop the tile to the ring and resample to a mission-format heightmap."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(tile_path) as ds:
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
