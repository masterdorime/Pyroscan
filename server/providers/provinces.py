"""Province catalogue, point-in-polygon, and country-wide FIRMS aggregation.

The boundaries are bundled (ODbL, see data/PROVINCES.md), so this module never
fetches at runtime. FIRMS is queried once over Indonesia's box and cached for
two hours; dots are assigned to exactly one province.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import http
from .base import ProviderConfig, ProviderError
from .firms import SOURCES, URL, parse

DATA = Path(__file__).resolve().parent / "data" / "provinces.geojson"
BOX = "95,-11,141,6"  # Indonesia, including the sea between the islands
DOT_CAP_PER_PROVINCE = 80
CACHE_TTL_S = 7200

_LOADED: list[dict] | None = None
_CACHE: dict[tuple, tuple[float, dict]] = {}


def load(path: Path | None = None) -> list[dict]:
    global _LOADED
    if path is None and _LOADED is not None:
        return _LOADED
    features = json.loads(Path(path or DATA).read_text(encoding="utf-8"))["features"]
    if path is None:
        _LOADED = features
    return features


def clamp_days(value: int) -> int:
    """FIRMS accepts 1..5 days; 7 returns `Invalid day range`."""
    return max(1, min(5, int(value or 1)))


def _ring_contains(ring: list[list[float]], lon: float, lat: float) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _geometry_contains(geometry: dict, lon: float, lat: float) -> bool:
    polygons = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
                else geometry["coordinates"])
    for poly in polygons:
        if _ring_contains(poly[0], lon, lat):
            # Holes are not expected after the land clip; the outer ring decides.
            return True
    return False


def province_at(features: list[dict], lon: float, lat: float) -> dict | None:
    for feature in features:
        west, south, east, north = feature["properties"]["bbox"]
        if not (west <= lon <= east and south <= lat <= north):
            continue
        if _geometry_contains(feature["geometry"], lon, lat):
            return feature
    return None


def _ring_area(ring: list[list[float]]) -> float:
    twice = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        twice += x1 * y2 - x2 * y1
    return abs(twice) / 2


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float]:
    twice = cx = cy = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        cross = x1 * y2 - x2 * y1
        twice += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(twice) < 1e-12:
        n = max(1, len(ring) - 1)
        return (sum(p[0] for p in ring[:-1]) / n,
                sum(p[1] for p in ring[:-1]) / n)
    return cx / (3 * twice), cy / (3 * twice)


def land_centre(feature: dict) -> tuple[float, float]:
    """A point on the province's largest polygon, not the bbox centre.

    Island provinces (Maluku, Kepulauan Riau, NTT) have a bbox centre at sea;
    a detail plate centred there is fully transparent."""
    geometry = feature["geometry"]
    polygons = ([geometry["coordinates"]] if geometry["type"] == "Polygon"
                else geometry["coordinates"])
    ring = max((poly[0] for poly in polygons), key=_ring_area)
    west = min(p[0] for p in ring)
    east = max(p[0] for p in ring)
    south = min(p[1] for p in ring)
    north = max(p[1] for p in ring)
    candidates = [_ring_centroid(ring)]
    for j in range(1, 8):
        for i in range(1, 8):
            candidates.append((west + (east - west) * i / 8,
                               south + (north - south) * j / 8))
    for lon, lat in candidates:
        if _ring_contains(ring, lon, lat):
            return lon, lat
    raise ValueError(f"no land centre for {feature['properties'].get('iso')}")


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def aggregate(features: list[dict], dots: list[dict], *,
              now: datetime | None = None,
              cap: int = DOT_CAP_PER_PROVINCE) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for dot in dots:
        try:
            lat, lon = float(dot["lat"]), float(dot["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        feature = province_at(features, lon, lat)
        if feature is None:
            continue  # a dot over open sea is not invented into a province
        props = feature["properties"]
        row = out.setdefault(props["iso"], {
            "iso": props["iso"], "name": props["name"], "count": 0,
            "max_frp": None, "newest_age_s": None, "dots": [],
        })
        row["count"] += 1
        frp = dot.get("frp")
        if frp is not None and (row["max_frp"] is None or frp > row["max_frp"]):
            row["max_frp"] = round(float(frp), 1)
        when = _when(dot.get("acq_at"))
        if when is not None:
            age = max(0, int((now - when).total_seconds()))
            if row["newest_age_s"] is None or age < row["newest_age_s"]:
                row["newest_age_s"] = age
        row["dots"].append(dot)
    for row in out.values():
        row["dots"].sort(key=lambda d: d.get("acq_at") or "", reverse=True)
        row["dots"] = row["dots"][:cap]
    return out


def fetch_country(cfg: ProviderConfig, days: int = 5) -> list[dict]:
    if not cfg.firms_map_key:
        raise ProviderError("config", "firms_map_key_missing")
    days = clamp_days(days)
    rows: list[dict] = []
    failures: list[str] = []
    for source in SOURCES:
        url = URL.format(key=cfg.firms_map_key, source=source, box=BOX, days=days)
        try:
            text = http.get_text(url, timeout=20, secret=cfg.firms_map_key)
        except ProviderError as exc:
            failures.append(f"{source}:{exc.kind}")
            continue
        payload = parse(text, (0.0, 118.0), cap=5000)
        rows.extend(payload.data["detections"])
    if not rows and failures:
        raise ProviderError("network", "; ".join(failures))
    return rows


def overview(cfg: ProviderConfig, days: int = 5) -> dict:
    days = clamp_days(days)
    cache_key = (cfg.firms_map_key, days)
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]

    rows = fetch_country(cfg, days)
    provinces = aggregate(load(), rows)
    dots = [{**dot, "iso": iso} for iso, row in provinces.items()
            for dot in row["dots"]]
    data = {
        "window_days": days,
        "bbox": {"west": 95, "south": -11, "east": 141, "north": 6},
        "sensors": sorted({d.get("sensor") for d in rows if d.get("sensor")}),
        "count": len(rows),
        "provinces": provinces,
        "dots": dots,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "NASA FIRMS NRT",
    }
    _CACHE[cache_key] = (time.time(), data)
    return data
