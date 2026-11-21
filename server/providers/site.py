"""Fire-site context: an 18 km real DEM + Sentinel-2 window at a detection.

This is a site *context*, not drone photogrammetry: there are no photos at a
FIRMS dot. Cached per rounded coordinate so a click is a one-off build.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
import io

from .. import config as server_config
from .base import Extent, ProviderConfig, ProviderError
from .copernicus_dem import crop_dem_mosaic
from .open_meteo import OpenMeteoProvider
from .provinces import load, province_at
from .province_plate import pick_tile_scenes
from .sentinel2 import (pick_scene_mosaic, read_scene_mosaic, search_scenes)
from ..pipeline import spread as spread_model

SITE_KM = 18.0
SITE_SIZE = 257
IMAGE_SIZE = 2048
SITE_VERSION = 8
CACHE_TTL_S = 7 * 86400

_CACHE: dict[tuple, tuple[float, dict]] = {}


class SiteUnavailable(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def site_dir(cache_dir: Path | None = None) -> Path:
    return Path(cache_dir or (Path(server_config.PROVIDERS_CACHE) / "sites"))


def _extent(lon: float, lat: float, window_km: float = SITE_KM) -> Extent:
    dlat = window_km / 111 / 2
    dlon = window_km / (111 * max(0.2, math.cos(math.radians(lat)))) / 2
    return Extent(lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _slope_aspect(heightmap: dict, extent: Extent) -> tuple[float, float]:
    grid = np.array(heightmap["heights_m"], dtype="float32").reshape(
        heightmap["height"], heightmap["width"])
    lat0 = math.radians((extent.south + extent.north) / 2)
    dx = (extent.east - extent.west) * 111_000 * math.cos(lat0) / grid.shape[1]
    dy = (extent.north - extent.south) * 111_000 / grid.shape[0]
    cy, cx = grid.shape[0] // 2, grid.shape[1] // 2
    sub = grid[max(0, cy - 2):cy + 3, max(0, cx - 2):cx + 3]
    gy, gx = np.gradient(sub, dy, dx)
    slope = math.degrees(math.atan(math.hypot(gx.mean(), gy.mean())))
    aspect = math.degrees(math.atan2(-gx.mean(), -gy.mean())) % 360
    return round(slope, 1), round(aspect, 1)


def _spread_frames(lat: float, lon: float, rate: float, bearing: float,
                   step: int = 30, horizon: int = 360) -> list[dict]:
    """Elliptical isochrones: ignition at one focus, wind along the bearing."""
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    b = math.radians(bearing)
    frames = []
    for t in range(0, horizon + 1, step):
        head = rate * t
        a = head * 0.6           # semi-major
        off = head * 0.4         # centre ahead of the ignition
        width = head * 0.32      # semi-minor
        ring = []
        for deg in range(0, 360, 15):
            th = math.radians(deg)
            x = off + a * math.cos(th)
            y = width * math.sin(th)
            east = x * math.sin(b) + y * math.cos(b)
            north = x * math.cos(b) - y * math.sin(b)
            ring.append([round(lon + east / m_lon, 6),
                         round(lat + north / m_lat, 6)])
        frames.append({
            "t_min": t,
            "head": {"lon": round(lon + head * math.sin(b) / m_lon, 6),
                     "lat": round(lat + head * math.cos(b) / m_lat, 6)},
            "ring": ring,
        })
    return frames


def build_site(lon: float, lat: float, *, window_km: float = SITE_KM,
               cache_dir: Path | None = None,
               dem_reader=None, searcher=None, scene_reader=None,
               weather_reader=None, force: bool = False) -> dict:
    features = load()
    province = province_at(features, float(lon), float(lat))
    if province is None:
        raise SiteUnavailable("outside the 38 Indonesian provinces")
    window_km = float(window_km)
    if not 2 <= window_km <= 80:
        raise SiteUnavailable("site window must be 2-80 km")
    image_size = 2048 if round(window_km) == 18 else 1024
    site_id = f"site-{lat:.3f}-{lon:.3f}-{round(window_km)}km"
    directory = site_dir(cache_dir)
    meta_path = directory / f"{site_id}.json"
    image_path = directory / f"{site_id}.webp"
    if not force and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta.get("version") == SITE_VERSION
                and time.time() - meta.get("built_ts", 0) < CACHE_TTL_S):
            return meta

    extent = _extent(float(lon), float(lat), window_km)
    dem_reader = dem_reader or crop_dem_mosaic
    searcher = searcher or (lambda window: search_scenes(window, days=90,
                                                        limit=20))
    scene_reader = scene_reader or read_scene_mosaic
    dem = dem_reader(extent, size=SITE_SIZE)
    heightmap = dem["heightmap"]

    imagery = None
    coverage = 0.0
    date_range: list[str] = []
    scenes = 0
    try:
        features = searcher(extent)
        if window_km <= 25:
            picked = pick_tile_scenes(features, limit=4, per_tile=2, bbox=(
                extent.west, extent.south, extent.east, extent.north))
        else:
            picked = pick_scene_mosaic(features, window=extent)
        if picked and picked.get("scenes"):
            pixels, coverage, covered = scene_reader(
                picked["scenes"], extent, size=image_size,
                with_stats=True, min_coverage=0, fill_once=True)
            rgb = np.asarray(pixels).astype("float32")
            # Bake a DEM hillshade into the texture: Sentinel haze hides relief
            # that the terrain geometry alone only shows at the silhouette.
            grid = np.array(heightmap["heights_m"], dtype="float32").reshape(
                SITE_SIZE, SITE_SIZE)
            lat0 = math.radians((extent.south + extent.north) / 2)
            dx = (extent.east - extent.west) * 111_000 * math.cos(lat0) / SITE_SIZE
            dy = (extent.north - extent.south) * 111_000 / SITE_SIZE
            gy, gx = np.gradient(grid, dy, dx)
            normal = np.dstack([-gx, -gy, np.ones_like(grid)])
            normal /= np.linalg.norm(normal, axis=2, keepdims=True)
            light = np.array([-0.55, -0.55, 0.63])
            light /= np.linalg.norm(light)
            shade = 0.55 + 0.55 * np.clip(
                (normal * light).sum(axis=2), 0, 1)
            shade = np.asarray(Image.fromarray(
                (shade * 255).astype("uint8")).resize(
                    (image_size, image_size), Image.BILINEAR),
                dtype="float32") / 255
            rgb = np.clip(rgb * shade[..., None], 0, 255)
            # Fill cloud/NoData holes with the bundled wide base, not black or
            # transparency; the site remains a texture, never a cutout.
            try:
                base = Image.open(Path(server_config.WEB) / "data"
                                  / "skin_satellite.jpg").convert("RGB")
                bw, bs, be, bn = 88, -20, 150, 10
                box = (int((extent.west - bw) / (be - bw) * base.width),
                       int((bn - extent.north) / (bn - bs) * base.height),
                       int((extent.east - bw) / (be - bw) * base.width),
                       int((bn - extent.south) / (bn - bs) * base.height))
                base = base.crop(box).resize((image_size, image_size),
                                             Image.LANCZOS)
                base_rgb = np.asarray(base).astype("float32")
                covered_mask = np.asarray(covered, dtype=bool)
                under = base_rgb.copy()
                under[covered_mask] = rgb[covered_mask]
                # Cloud shadows survive SCL as near-black pixels; the base is
                # better than a black hole.
                dark = under.max(axis=2) < 14
                under[dark] = base_rgb[dark]
                rgb = under
            except (OSError, ValueError):
                pass
            buffer = io.BytesIO()
            Image.fromarray(rgb.astype("uint8"), "RGB").save(
                buffer, "WEBP", quality=82, method=4)
            imagery = buffer.getvalue()
            date_range = picked["date_range"]
            scenes = len(picked["scenes"])
    except ProviderError:
        imagery = None  # the terrain still opens without a scene

    weather = None
    try:
        read_weather = weather_reader or (lambda ext: OpenMeteoProvider().fetch(
            ext, ProviderConfig()).data)
        weather = read_weather(extent)
    except Exception:
        weather = None

    terrain = None
    slope = aspect = 0.0
    try:
        grid = np.array(heightmap["heights_m"], dtype="float32").reshape(
            heightmap["height"], heightmap["width"])
        slope, aspect = _slope_aspect(heightmap, extent)
        terrain = {
            "min_m": round(float(grid.min())),
            "max_m": round(float(grid.max())),
            "mean_m": round(float(grid.mean())),
            "relief_m": round(float(grid.max() - grid.min())),
            "slope_deg": slope,
            "aspect_deg": aspect,
            "grid_m": round(window_km * 1000 / SITE_SIZE, 1),
        }
    except Exception:
        terrain = None

    spread = None
    try:
        hotspot = {"id": "site", "lat": float(lat), "lon": float(lon),
                   "slope_deg": slope, "aspect_deg": aspect}
        prediction = spread_model.predict(hotspot, weather or {}, horizons=(360,))
        if prediction:
            p = prediction[0]
            spread = {
                "rate_m_min": p["rate_m_min"],
                "bearing_deg": p["bearing_deg"],
                "risk": p["risk_level"],
                "model": p["model_version"],
                "frames": _spread_frames(float(lat), float(lon),
                                         p["rate_m_min"], p["bearing_deg"]),
            }
    except Exception:
        spread = None

    meta = {
        "version": SITE_VERSION,
        "id": site_id,
        "name": province["properties"]["name"],
        "iso": province["properties"]["iso"],
        "centre": {"lon": float(lon), "lat": float(lat)},
        "bbox": {"west": extent.west, "south": extent.south,
                 "east": extent.east, "north": extent.north},
        "window_km": window_km,
        "terrain": terrain,
        "heightmap": heightmap,
        "imagery_url": f"/api/v1/sites/{site_id}/imagery.webp" if imagery else None,
        "imagery_coverage": round(float(coverage), 3),
        "imagery_scenes": scenes,
        "imagery_date_range": date_range,
        "imagery_mpp": round(window_km * 1000 / image_size, 1),
        "weather": weather,
        "spread": spread,
        "attribution": "Copernicus DEM 30 m · Sentinel-2 L2A",
        "built_ts": time.time(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    directory.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if imagery:
        image_path.write_bytes(imagery)
    _CACHE[(site_id,)] = (time.time(), meta)
    return meta


def site_paths(site_id: str, cache_dir: Path | None = None) -> tuple[Path, Path]:
    if not site_id.startswith("site-") or "/" in site_id or ".." in site_id:
        raise SiteUnavailable("bad site id")
    directory = site_dir(cache_dir)
    return directory / f"{site_id}.json", directory / f"{site_id}.webp"
