"""Sentinel-2 L2A context imagery via Earth Search STAC and windowed COG reads.

Measured (spec 7.5): a 1.2 km window costs 1.46 MB and a 25 km window 15.95 MB,
so the true-colour asset is read directly and never downloaded whole (290 MB).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import requests

from .base import Extent, ProviderConfig, ProviderError, ProviderPayload

STAC = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
MAX_CLOUD = 40.0
DAYS = 90
SIZE = 1024
ASSET_NAME = "context_imagery.webp"
SOURCE_RESOLUTION_M = 10
# The Context view only ever shows the ~1.35 km mosaic, so imagery is fetched for
# a mosaic-scale window rather than the 30 km ring: 1024 px over 4 km is ~4 m/px,
# while the same 1024 px over the ring would be ~30 m/px draped over 1.35 km.
IMAGERY_KM = 4.0


def imagery_extent(extent: Extent) -> Extent:
    """Small box centred on the ring, sized for the Context mosaic."""
    import math

    lat, lon = extent.centre
    half_lat = (IMAGERY_KM / 2) / 111.32
    half_lon = (IMAGERY_KM / 2) / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
    return Extent(west=lon - half_lon, south=lat - half_lat,
                  east=lon + half_lon, north=lat + half_lat, ring_km=extent.ring_km)


def _iso(value) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        return text
    return text + "Z" if "T" in text and "+" not in text else text


def _ring_polygon(extent: Extent) -> dict:
    w, s, e, n = extent.west, extent.south, extent.east, extent.north
    return {"type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def search_scenes(extent: Extent, *, days: int = DAYS, limit: int = 10,
                  poster=None, order: str = "cloud") -> list[dict]:
    """Earth Search is keyless. Returns raw STAC features, least cloudy first."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    sortby = ([{"field": "properties.datetime", "direction": "desc"}]
              if order == "datetime" else
              [{"field": "properties.eo:cloud_cover", "direction": "asc"}])
    body = {
        "collections": [COLLECTION],
        "intersects": _ring_polygon(extent),
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": limit,
        "sortby": sortby,
    }
    post = poster or requests.post
    try:
        resp = post(STAC, json=body, timeout=30)
    except requests.RequestException as exc:
        raise ProviderError("network", f"{type(exc).__name__}: {exc}") from None
    if resp.status_code >= 400:
        raise ProviderError("http", f"STAC HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        raise ProviderError("parse", "STAC response is not JSON") from None
    features = data.get("features")
    return features if isinstance(features, list) else []


def _tci_href(feature: dict) -> str | None:
    assets = feature.get("assets") or {}
    for name in ("visual", "TCI", "tci"):
        asset = assets.get(name) or {}
        href = asset.get("href")
        if href:
            return href
    return None


def _scl_href(feature: dict) -> str | None:
    """Scene Classification Layer: per-pixel cloud/shadow mask, 20 m."""
    assets = feature.get("assets") or {}
    for name in ("scl", "SCL"):
        asset = assets.get(name) or {}
        href = asset.get("href")
        if href:
            return href
    return None


def pick_scene(features: list[dict], *, max_cloud: float = MAX_CLOUD) -> dict | None:
    """Least-cloudy usable scene, or None. Cloud is scene-level, not site-level."""
    candidates = pick_scenes(features, max_cloud=max_cloud)
    return candidates[0] if candidates else None


def _bbox_contains(bbox, lat: float, lon: float) -> bool | None:
    """True/False when the STAC bbox is usable, None when it is absent."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        west, south, east, north = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    # STAC bbox is WGS84 lon/lat with south < north. Be tolerant of a swapped
    # pair rather than silently declaring "not covered".
    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west
    return west <= lon <= east and south <= lat <= north


def _coverage_rank(feature: dict, window: Extent | None) -> int:
    """How much to trust this scene for the window we are about to read.

    0 = the scene footprint contains the window centre (read it first)
    1 = cannot tell, e.g. a fixture without a bbox (keep the old cloud order)
    2 = the footprint demonstrably excludes the centre (try only as a last resort)

    Why this exists: `intersects` is a footprint test, not a raster-grid test.
    At Brighton the 4 km mosaic window is centred at 46.8427 N while the
    neighbouring MGRS tile 15TWN starts at 46.8566 N; 15TWN still intersects the
    search polygon and is often the *least cloudy* scene, so ranking by cloud
    alone read a sliver and failed ("ring lies outside the imagery tile").
    """
    if window is None:
        return 1
    lat, lon = window.centre
    inside = _bbox_contains(feature.get("bbox"), lat, lon)
    return 1 if inside is None else (0 if inside else 2)


def pick_scenes(features: list[dict], *, max_cloud: float = MAX_CLOUD,
                window: Extent | None = None) -> list[dict]:
    """All usable scenes, best first: covered centre, then least cloudy.

    A scene can intersect the search area while its own raster does not contain
    the window we read, so the adapter tries these in order rather than trusting
    the first one. `window` lets the ordering respect the *raster* coverage we
    can see in the scene bbox; without it the order stays pure cloud.
    """
    ranked: list[tuple[int, int, dict]] = []
    for position, feature in enumerate(features):
        props = feature.get("properties") or {}
        href = _tci_href(feature)
        cloud = props.get("eo:cloud_cover")
        if href is None or cloud is None:
            continue
        try:
            cloud_pct = float(cloud)
        except (TypeError, ValueError):
            continue
        if cloud_pct > max_cloud:
            continue
        ranked.append((
            _coverage_rank(feature, window), position,
            {
                "scene_id": feature.get("id"),
                "acquired_at": _iso(props.get("datetime")),
                "cloud_pct": cloud_pct,
                "href": href,
                "bbox": feature.get("bbox"),
            },
        ))
    ranked.sort(key=lambda item: (item[0], item[2]["cloud_pct"], item[1]))
    return [scene for _, _, scene in ranked]


def grade_like_context(pixels, *, size: int = 512):
    """The same look the cached Esri context was graded with.

    Copied from `spike/tools/make_dashboard_assets.py` so Sentinel-2 reads as
    part of the same paper landscape: lift shadows, gentle contrast, +18 %
    saturation, a warm channel bias, exposure, then unsharp.
    """
    import numpy as np
    from PIL import Image, ImageFilter

    image = Image.fromarray(pixels.astype("uint8"), "RGB").resize(
        (size, size), Image.BILINEAR)
    arr = np.asarray(image).astype(np.float32) / 255.0
    arr = np.power(arr, 0.86)                       # lift the shadows
    arr = np.clip((arr - 0.5) * 1.08 + 0.5, 0, 1)   # gentle contrast
    gray = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    arr = np.clip(gray[..., None] + (arr - gray[..., None]) * 1.18, 0, 1)
    arr[..., 0] *= 1.07
    arr[..., 1] *= 1.02
    arr[..., 2] *= 0.94
    arr = np.clip(arr * 1.12, 0, 1)
    return Image.fromarray((arr * 255).astype("uint8"), "RGB").filter(
        ImageFilter.UnsharpMask(radius=1, percent=60, threshold=6))


def read_scene_window(source: str, extent: Extent, *, size: int = SIZE):
    """Windowed RGB read, reprojecting the ring into the tile's own CRS.

    Passing degrees to `from_bounds` on a UTM tile silently yields a 0x0 window;
    that mistake was made once during the gate and is now impossible by construction.
    """
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    # Remote opens have no Python-level timeout: without these a stalled HTTPS
    # request pins the gateway's single-flight claim indefinitely.
    with rasterio.Env(GDAL_HTTP_TIMEOUT="30", GDAL_HTTP_CONNECTTIMEOUT="10",
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        try:
            with rasterio.open(source) as ds:
                left, bottom, right, top = transform_bounds(
                    "EPSG:4326", ds.crs,
                    extent.west, extent.south, extent.east, extent.north)
                bounds = ds.bounds
                left = max(left, bounds.left)
                bottom = max(bottom, bounds.bottom)
                right = min(right, bounds.right)
                top = min(top, bounds.top)
                if left >= right or bottom >= top:
                    raise ProviderError("parse", "ring lies outside the imagery tile")
                window = from_bounds(left, bottom, right, top,
                                     transform=ds.transform).round_offsets().round_lengths()
                if window.width < 1 or window.height < 1:
                    raise ProviderError("parse", "empty imagery window")
                bands = ds.count
                picked = [1, 2, 3] if bands >= 3 else [1]
                array = ds.read(picked, window=window)
        except ProviderError:
            raise
        except Exception as exc:
            # rasterio raises RasterioIOError for remote read failures; the
            # gateway must only ever see typed provider errors.
            raise ProviderError("network", f"imagery read failed: {type(exc).__name__}") from None

    if array.size == 0:
        raise ProviderError("parse", "empty imagery window")
    if array.shape[0] >= 3:
        pixels = np.transpose(array[:3], (1, 2, 0)).astype("uint8")
    else:
        pixels = np.repeat(np.transpose(array[:1], (1, 2, 0)), 3, axis=2).astype("uint8")

    return np.asarray(grade_like_context(pixels, size=size))


def encode_webp(pixels, *, quality: int = 82) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(pixels.astype("uint8"), "RGB").save(
        buffer, format="WEBP", quality=quality, method=4)
    return buffer.getvalue()


# --- wide Regional mosaic ---------------------------------------------------
WIDE_KM = 60.0
WIDE_SIZE = 1024
WIDE_ASSET = "context_imagery_wide.webp"
PAIR_TOLERANCE_DAYS = 14
PROBE_GRID = 5


def _tile_of(href: str) -> str | None:
    """MGRS tile from a Sentinel COG path: .../15/T/WM/... -> 15TWM."""
    parts = str(href).split("/")
    for i, part in enumerate(parts):
        if (len(part) == 2 and part.isdigit() and i + 2 < len(parts)
                and len(parts[i + 1]) == 1 and len(parts[i + 2]) == 2):
            return f"{part}{parts[i + 1]}{parts[i + 2]}"
    return None


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _probe_points(extent: Extent, n: int = PROBE_GRID) -> list[tuple[float, float]]:
    """An n x n lat/lon grid over the window, used as coverage probes."""
    out = []
    for j in range(n):
        for i in range(n):
            lat = extent.south + (extent.north - extent.south) * (j / (n - 1))
            lon = extent.west + (extent.east - extent.west) * (i / (n - 1))
            out.append((lat, lon))
    return out


def pick_scene_mosaic(features: list[dict], *, window: Extent,
                      max_cloud: float = MAX_CLOUD,
                      tolerance_days: int = PAIR_TOLERANCE_DAYS) -> dict | None:
    """Choose the fewest scenes that cover `window`, preferring one date.

    A 60 km box crosses Sentinel-2 tile edges, so one scene cannot cover it.
    Picking the least cloudy scene per tile independently can pair October with
    November and leave a visible seam. Instead: probe the window on a grid,
    greedily take the scene that covers the most uncovered probes, and among
    equals prefer a date close to the least-cloudy scene's date.
    """
    candidates = pick_scenes(features, max_cloud=max_cloud, window=window)
    if not candidates:
        return None

    # The target date is the clearest scene over the window *centre*: the tile
    # that actually holds the mission. A clearer neighbour must not drag the
    # whole mosaic to a different season.
    lat, lon = window.centre
    centred = [c for c in candidates if _bbox_contains(c.get("bbox"), lat, lon)]
    target = min(centred or candidates, key=lambda c: c["cloud_pct"])
    target_date = _parse_date(target["acquired_at"])
    probes = _probe_points(window)

    def gap_days(scene: dict) -> int:
        when = _parse_date(scene["acquired_at"])
        if not when or not target_date:
            return 9999
        return abs((when - target_date).days)

    uncovered = set(range(len(probes)))
    remaining = list(candidates)
    chosen: list[dict] = []
    while uncovered and remaining:
        scored = []
        for scene in remaining:
            covers = {i for i in uncovered
                      if _bbox_contains(scene.get("bbox"), *probes[i])}
            if not covers:
                continue
            scored.append(((-len(covers), gap_days(scene) > tolerance_days,
                            gap_days(scene), scene["cloud_pct"]), scene, covers))
        if not scored:
            break
        scored.sort(key=lambda item: item[0])
        _, scene, covers = scored[0]
        chosen.append(scene)
        uncovered -= covers
        remaining.remove(scene)

    if not chosen:
        return None

    dates = sorted(d for d in (_parse_date(c["acquired_at"]) for c in chosen) if d)
    span = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    covered = 1 - len(uncovered) / len(probes)
    return {
        "scenes": chosen,
        "target_scene": target,
        "date_range": [dates[0].strftime("%Y-%m-%d"),
                       dates[-1].strftime("%Y-%m-%d")] if dates else [],
        "multi_date": span > tolerance_days,
        "span_days": span,
        "coverage": round(covered, 3),
    }


def read_scene_mosaic(scenes: list[dict], extent: Extent, *, size: int = WIDE_SIZE,
                      with_stats: bool = False, min_coverage: float = 0.9,
                      fill_once: bool = False):
    """Stitch the chosen scenes into one georeferenced RGB array.

    Works in 4326 for placement (each scene's raster bounds are transformed back)
    so a mosaic is still correct if the scenes use different CRSs.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    span_lon = (extent.east - extent.west) or 1e-12
    span_lat = (extent.north - extent.south) or 1e-12
    mosaic = np.zeros((size, size, 3), dtype="uint8")
    covered = np.zeros((size, size), dtype=bool)

    env = {"GDAL_HTTP_TIMEOUT": "30", "GDAL_HTTP_CONNECTTIMEOUT": "10",
           "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
    errors: list[str] = []
    with rasterio.Env(**env):
        for scene in scenes:
            try:
                with rasterio.open(scene["href"]) as ds:
                    b4326 = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
                    west = max(extent.west, b4326[0])
                    south = max(extent.south, b4326[1])
                    east = min(extent.east, b4326[2])
                    north = min(extent.north, b4326[3])
                    if west >= east or south >= north:
                        continue
                    x0 = int(round((west - extent.west) / span_lon * size))
                    x1 = int(round((east - extent.west) / span_lon * size))
                    y0 = int(round((extent.north - north) / span_lat * size))
                    y1 = int(round((extent.north - south) / span_lat * size))
                    x1 = min(size, max(x1, x0 + 1))
                    y1 = min(size, max(y1, y0 + 1))
                    win_bounds = transform_bounds("EPSG:4326", ds.crs,
                                                  west, south, east, north)
                    window = from_bounds(*win_bounds, transform=ds.transform)
                    bands = ds.count
                    picked = [1, 2, 3] if bands >= 3 else [1]
                    block = ds.read(picked, window=window,
                                    out_shape=(y1 - y0, x1 - x0))
            except Exception as exc:
                # One dead COG must not make a whole province unbuildable.
                errors.append(type(exc).__name__)
                continue
            rgb = (np.transpose(block[:3], (1, 2, 0)) if block.shape[0] >= 3
                   else np.repeat(np.transpose(block[:1], (1, 2, 0)), 3, axis=2))
            # A scene's rectangular bounds can include NoData corners. Write
            # only pixels with signal and mark only those as covered, or a
            # later NoData tile erases an earlier valid one.
            valid = block.max(axis=0) > 4
            if scene.get("mask_href"):
                try:
                    with rasterio.open(scene["mask_href"]) as ms:
                        mwin = transform_bounds("EPSG:4326", ms.crs,
                                                west, south, east, north)
                        window = from_bounds(*mwin, transform=ms.transform)
                        mask = ms.read(1, window=window,
                                       out_shape=(y1 - y0, x1 - x0),
                                       boundless=True, fill_value=0)
                    # 0/1 no-data, 3 shadow, 8/9 cloud, 10 cirrus, 11 snow.
                    valid &= ~np.isin(mask, (0, 1, 3, 8, 9, 10, 11))
                except Exception:
                    pass  # masking is optional; the TCI validity still holds
            target = ((valid & ~covered[y0:y1, x0:x1]) if fill_once
                      else valid)
            region = mosaic[y0:y1, x0:x1]
            region[target] = rgb.astype("uint8")[target]
            covered[y0:y1, x0:x1] |= valid

    if not covered.any() and errors:
        raise ProviderError("network", f"mosaic read failed: {errors[0]}")
    fraction = float(covered.mean())
    if fraction < min_coverage:
        raise ProviderError("parse", f"mosaic incomplete ({fraction:.0%} covered)")
    image = grade_like_context(mosaic, size=size)
    if with_stats:
        return image, fraction, covered
    return np.asarray(image)


class Sentinel2Provider:
    id = "sentinel-2"
    key = "context_imagery"
    source_label = "Sentinel-2"
    licence = "Sentinel-2 L2A, Copernicus - free, attribution required"
    attribution = "Contains modified Copernicus Sentinel data"
    ttl_s = 259_200
    fetch_timeout_s = 45
    allow_inline = False
    requires: tuple[str, ...] = ()

    def __init__(self, *, searcher=None, reader=None, size: int = SIZE,
                 source_label: str | None = None) -> None:
        self.searcher = searcher or search_scenes
        self.reader = reader or read_scene_window
        self.size = size
        if source_label:
            self.source_label = source_label

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        # Search by the window we will read, not the whole ring: a scene that
        # clips the ring edge need not contain the mosaic centre at all.
        window = imagery_extent(extent)
        candidates = pick_scenes(self.searcher(window), window=window)
        if not candidates:
            raise ProviderError("missing", "no_usable_scene")

        pixels = None
        scene = None
        last_error: ProviderError | None = None
        for candidate in candidates[:3]:
            try:
                pixels = self.reader(candidate["href"], window, size=self.size)
                scene = candidate
                break
            except ProviderError as exc:
                last_error = exc
                continue
        if scene is None or pixels is None:
            raise last_error or ProviderError("missing", "no_usable_scene")
        data = {
            "bbox": {"west": window.west, "south": window.south,
                     "east": window.east, "north": window.north},
            "asset": ASSET_NAME,
            "scene_id": scene["scene_id"],
            "acquired_at": scene["acquired_at"],
            "cloud_pct": scene["cloud_pct"],
            "resolution_m": SOURCE_RESOLUTION_M,
            "window_km": IMAGERY_KM,
            "bands": ["B04", "B03", "B02"],
        }
        # observed_at stays None on purpose: cache freshness is not scene freshness.
        # The scene date travels in data["acquired_at"] and is what the UI shows.
        return ProviderPayload(data, None,
                               extra={"asset_name": ASSET_NAME,
                                      "asset_bytes": encode_webp(pixels)})


class Sentinel2WideProvider(Sentinel2Provider):
    """60 km Regional mosaic: several scenes, one graded asset."""

    key = "context_imagery_wide"

    def __init__(self, *, searcher=None, reader=None, size: int = WIDE_SIZE,
                 window_km: float = WIDE_KM,
                 source_label: str | None = None) -> None:
        super().__init__(searcher=searcher,
                         reader=reader or read_scene_mosaic, size=size,
                         source_label=source_label)
        self.window_km = window_km

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        from .geo import square_extent

        lat, lon = extent.centre
        window = square_extent(lat, lon, self.window_km / 2)
        picked = pick_scene_mosaic(self.searcher(window), window=window)
        if not picked:
            raise ProviderError("missing", "no_usable_scene")

        pixels = self.reader(picked["scenes"], window, size=self.size)
        scenes = [
            {
                "scene_id": s["scene_id"],
                "tile": _tile_of(s["href"]),
                "acquired_at": s["acquired_at"],
                "cloud_pct": s["cloud_pct"],
            }
            for s in picked["scenes"]
        ]
        data = {
            "bbox": {"west": window.west, "south": window.south,
                     "east": window.east, "north": window.north},
            "asset": WIDE_ASSET,
            "scenes": scenes,
            "date_range": picked["date_range"],
            "multi_date": picked["multi_date"],
            "scene_count": len(scenes),
            "coverage": picked["coverage"],
            "cloud_pct": max((s["cloud_pct"] for s in scenes), default=None),
            "resolution_m": round(self.window_km * 1000 / self.size),
            "source_resolution_m": SOURCE_RESOLUTION_M,
            "window_km": self.window_km,
            "bands": ["B04", "B03", "B02"],
        }
        # observed_at stays None: cache freshness is not scene freshness. The
        # mosaic's dates travel in date_range and are what the UI shows.
        return ProviderPayload(data, None,
                               extra={"asset_name": WIDE_ASSET,
                                      "asset_bytes": encode_webp(pixels)})
