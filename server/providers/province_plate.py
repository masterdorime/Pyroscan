"""Province imagery plates: a polygon-masked Sentinel-2 composite.

Preview: the province bbox at 2048 px (~250–350 m). Detail: a 2048 px / 59 m
window around the bbox centre. Both are RGBA WebP: alpha is 0 outside the
boundary *and* where no scene covers, so the globe base shows through instead
of a flat colour that would read as land.
"""
from __future__ import annotations

import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np

from .. import config as server_config
from .base import Extent
from .provinces import land_centre, load
from .sentinel2 import (read_scene_mosaic, search_scenes,
                        _iso, _parse_date, _scl_href, _tci_href, _tile_of)

PLATE_VERSION = 2
PREVIEW_SIZE = 2048
DETAIL_MPP = 59
DETAIL_SIZE = 2048
TIERS = {"preview", "detail"}


class PlateUnavailable(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def plate_dir() -> Path:
    return Path(server_config.PROVIDERS_CACHE) / "provinces"


def plate_path(iso: str, tier: str, cache_dir: Path | None = None) -> Path:
    return Path(cache_dir or plate_dir()) / f"{iso}_{tier}.webp"


def meta_path(iso: str, tier: str, cache_dir: Path | None = None) -> Path:
    return Path(cache_dir or plate_dir()) / f"{iso}_{tier}.json"


def feature_for(iso: str, features: list[dict] | None = None) -> dict:
    for feature in features or load():
        if feature["properties"]["iso"] == iso:
            return feature
    raise PlateUnavailable(f"unknown province {iso}")


def _pad(bbox: tuple, fraction: float = 0.02) -> tuple:
    west, south, east, north = bbox
    dx = max((east - west) * fraction, 0.02)
    dy = max((north - south) * fraction, 0.02)
    return west - dx, south - dy, east + dx, north + dy


def detail_extent(bbox: tuple, *, size: int = DETAIL_SIZE,
                  m_per_px: float = DETAIL_MPP,
                  centre: tuple[float, float] | None = None) -> Extent:
    """A 59 m window near the province centre; the full bbox would exceed
    Cesium's texture cap and would not be 59 m anyway."""
    west, south, east, north = bbox
    lon, lat = centre or ((west + east) / 2, (south + north) / 2)
    span_km = size * m_per_px / 1000
    dlat = span_km / 111 / 2
    dlon = span_km / (111 * max(0.2, math.cos(math.radians(lat)))) / 2
    return Extent(lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _ring_points(ring, bbox, size) -> list[tuple[float, float]]:
    west, south, east, north = bbox
    span_lon = (east - west) or 1e-12
    span_lat = (north - south) or 1e-12
    return [((lon - west) / span_lon * (size - 1),
             (north - lat) / span_lat * (size - 1)) for lon, lat in ring]


def mask_rgba(size: int, geometry: dict, bbox: tuple, covered) -> np.ndarray:
    """255 inside the polygon and covered by a scene; 0 elsewhere."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    polygons = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
                else geometry["coordinates"])
    for poly in polygons:
        draw.polygon(_ring_points(poly[0], bbox, size), fill=255)
        for hole in poly[1:]:
            draw.polygon(_ring_points(hole, bbox, size), fill=0)
    alpha = np.asarray(mask, dtype=np.uint8)
    if covered is not None:
        alpha = np.where(np.asarray(covered, dtype=bool), alpha, 0).astype(np.uint8)
    return alpha


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _overlap(scene: dict, bbox: tuple) -> float:
    west, south, east, north = bbox
    try:
        sw, ss, se, sn = scene["bbox"]
    except (TypeError, ValueError):
        return 0.0
    return (max(0.0, min(east, se) - max(west, sw))
            * max(0.0, min(north, sn) - max(south, ss)))


def _search_province(window: Extent) -> list[dict]:
    """Two STAC pages: recent dates cover every tile; the clearest page gives
    each tile a better scene where one exists. One page alone either leaves
    tile-sized holes (cloud-sorted) or shows the rainiest week (date-sorted)."""
    recent = search_scenes(window, days=180, limit=200, order="datetime")
    clearest = search_scenes(window, days=180, limit=200)
    return recent + clearest


def pick_tile_scenes(features: list[dict], *, limit: int = 28,
                     bbox: tuple | None = None, per_tile: int = 1) -> dict:
    """Up to `per_tile` clearest scenes per MGRS tile, for `limit` tiles.

    A province spans ~25 tiles; the ±14-day pairing used for 60 km mosaics is
    too few scenes here, so tiles are chosen independently and the date range
    is reported instead of pretending it is one date. Two dates per tile let
    the SCL mask fill one date's cloud from the next.
    """
    buckets: dict[str, list[dict]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        href = _tci_href(feature)
        tile = _tile_of(href or "")
        try:
            cloud = float(props.get("eo:cloud_cover"))
        except (TypeError, ValueError):
            continue
        if not href or not tile:
            continue
        buckets.setdefault(tile, []).append({
            "href": href, "tile": tile, "cloud_pct": cloud,
            "acquired_at": _iso(props.get("datetime")),
            "bbox": feature.get("bbox"),
            "mask_href": _scl_href(feature),
        })
    for bucket in buckets.values():
        bucket.sort(key=lambda s: (s["cloud_pct"], s.get("acquired_at") or ""))

    tiles = list(buckets.values())
    if bbox is not None:
        tiles.sort(key=lambda bb: -(_overlap(bb[0], bbox)
                                    * (1 - bb[0]["cloud_pct"] / 100)))
    else:
        tiles.sort(key=lambda bb: bb[0]["tile"])
    chosen = [scene for bucket in tiles[:limit]
              for scene in bucket[:per_tile]]
    dates = sorted(d for d in (_parse_date(s["acquired_at"]) for s in chosen) if d)
    span = (dates[-1] - dates[0]).days if len(dates) > 1 else 0
    return {
        "scenes": chosen,
        "date_range": [dates[0].strftime("%Y-%m-%d"),
                       dates[-1].strftime("%Y-%m-%d")] if dates else [],
        "multi_date": span > 14,
        "span_days": span,
    }


def build_plate(iso: str, tier: str = "preview", *, size: int | None = None,
                feature: dict | None = None, reader=None, searcher=None,
                cache_dir: Path | None = None, force: bool = False) -> dict:
    if tier not in TIERS:
        raise PlateUnavailable(f"unknown tier {tier}")
    size = size or (PREVIEW_SIZE if tier == "preview" else DETAIL_SIZE)
    image_path = plate_path(iso, tier, cache_dir)
    info_path = meta_path(iso, tier, cache_dir)
    if not force and image_path.exists() and info_path.exists():
        meta = json.loads(info_path.read_text(encoding="utf-8"))
        if meta.get("version") == PLATE_VERSION:
            return {"image": image_path.read_bytes(), "meta": meta}

    feature = feature or feature_for(iso)
    bbox = tuple(feature["properties"]["bbox"])
    if tier == "preview":
        extent = Extent(*_pad(bbox))
    else:
        lon, lat = land_centre(feature)
        extent = detail_extent(bbox, size=size, centre=(lon, lat))
    reader = reader or read_scene_mosaic
    searcher = searcher or _search_province

    scenes = searcher(extent)
    window_bbox = (extent.west, extent.south, extent.east, extent.north)
    picked = pick_tile_scenes(scenes, limit=32 if tier == "preview" else 8,
                              per_tile=2, bbox=window_bbox)
    if not picked["scenes"]:
        raise PlateUnavailable("no cloud-free Sentinel-2 scenes in the window")

    rgb, _, covered = reader(picked["scenes"], extent, size=size,
                             with_stats=True, min_coverage=0, fill_once=True)
    alpha = mask_rgba(size, feature["geometry"], (extent.west, extent.south, extent.east, extent.north), covered)
    rgba = np.dstack([np.asarray(rgb)[..., :3], alpha])
    buffer = io.BytesIO()
    Image.fromarray(rgba.astype("uint8"), "RGBA").save(
        buffer, "WEBP", quality=82, method=4)
    payload = buffer.getvalue()

    polygon = mask_rgba(size, feature["geometry"], (extent.west, extent.south,
                                                    extent.east, extent.north),
                        None) > 0
    covered_px = int((alpha > 0).sum())
    coverage = covered_px / max(1, int(polygon.sum()))
    if coverage <= 0:
        raise PlateUnavailable(f"{tier} window has no imagery on land")
    span_m = max((extent.east - extent.west) * 111_000,
                 (extent.north - extent.south) * 111_000)
    meta = {
        "version": PLATE_VERSION,
        "iso": iso,
        "name": feature["properties"].get("name"),
        "tier": tier,
        "size": size,
        "resolution_m": round(span_m / size),
        "coverage": round(coverage, 3),
        "scenes": len(picked["scenes"]),
        "date_range": picked["date_range"],
        "multi_date": bool(picked["multi_date"]),
        "rectangle": [extent.west, extent.south, extent.east, extent.north],
        "attribution": "Contains modified Copernicus Sentinel data",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write(image_path, payload)
    _write(info_path, json.dumps(meta).encode("utf-8"))
    return {"image": payload, "meta": meta}
