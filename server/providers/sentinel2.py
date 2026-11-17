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
                  poster=None) -> list[dict]:
    """Earth Search is keyless. Returns raw STAC features, least cloudy first."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    body = {
        "collections": [COLLECTION],
        "intersects": _ring_polygon(extent),
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": limit,
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
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


def pick_scene(features: list[dict], *, max_cloud: float = MAX_CLOUD) -> dict | None:
    """Least-cloudy usable scene, or None. Cloud is scene-level, not site-level."""
    for feature in features:
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
        return {
            "scene_id": feature.get("id"),
            "acquired_at": _iso(props.get("datetime")),
            "cloud_pct": cloud_pct,
            "href": href,
        }
    return None


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

    def __init__(self, *, searcher=None, reader=None, size: int = SIZE) -> None:
        self.searcher = searcher or search_scenes
        self.reader = reader or read_scene_window
        self.size = size

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        # Search by the window we will read, not the whole ring: a scene that
        # clips the ring edge need not contain the mosaic centre at all.
        window = imagery_extent(extent)
        scene = pick_scene(self.searcher(window))
        if scene is None:
            raise ProviderError("missing", "no_usable_scene")
        pixels = self.reader(scene["href"], window, size=self.size)
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
