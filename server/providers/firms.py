"""NASA FIRMS adapter: near-real-time active fire detections in the ring.

CSV column names follow the published FIRMS area-CSV header. Confidence is
normalised to 0-1 while `confidence_raw` keeps the provider's own value.
"""
from __future__ import annotations

import csv
import io

from . import http
from .base import Extent, ProviderConfig, ProviderError, ProviderPayload

URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{box}/{days}"
SOURCE = "VIIRS_SNPP_NRT"
SOURCES = ("VIIRS_SNPP_NRT", "MODIS_NRT")
WINDOW_DAYS = 1
CAP = 500

_VIIRS_CONFIDENCE = {"l": 0.3, "n": 0.6, "h": 0.9}


def parse_acq(acq_date: str, acq_time: str) -> str:
    """`HHMM` from FIRMS, tolerant of 3-digit and zero-padded values."""
    digits = str(acq_time).strip().zfill(4)
    if len(digits) != 4 or not digits.isdigit():
        raise ValueError(f"bad acq_time {acq_time!r}")
    hour, minute = int(digits[:2]), int(digits[2:])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"bad acq_time {acq_time!r}")
    return f"{str(acq_date).strip()}T{hour:02d}:{minute:02d}:00Z"


def _confidence(raw: str | None) -> float:
    text = str(raw or "").strip().lower()
    if text in _VIIRS_CONFIDENCE:
        return _VIIRS_CONFIDENCE[text]
    try:
        return max(0.0, min(1.0, float(text) / 100.0))
    except ValueError:
        return 0.0


def parse(csv_text: str, centre: tuple[float, float],
          cap: int = CAP) -> ProviderPayload:
    from .geo import bearing_deg, haversine_km

    seen: set[tuple] = set()
    rows: list[dict] = []

    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            acq_at = parse_acq(row.get("acq_date"), row.get("acq_time"))
        except (KeyError, TypeError, ValueError):
            continue
        sensor = (row.get("satellite") or row.get("instrument") or "unknown").strip()
        fingerprint = (round(lat, 3), round(lon, 3), acq_at, sensor)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        try:
            frp = float(row["frp"]) if row.get("frp") not in (None, "") else None
        except ValueError:
            frp = None
        try:
            brightness = float(row["bright_ti4"] or row["brightness"])
        except (KeyError, TypeError, ValueError):
            brightness = None
        rows.append({
            "lat": lat,
            "lon": lon,
            "confidence": _confidence(row.get("confidence")),
            "confidence_raw": row.get("confidence"),
            "frp": frp,
            "brightness_k": brightness,
            "sensor": sensor,
            "acq_at": acq_at,
            "daynight": row.get("daynight"),
        })

    total = len(rows)
    if not rows:
        return ProviderPayload(
            {"count": 0, "bbox": None, "window_days": WINDOW_DAYS,
             "sensors": [SOURCE], "detections": [], "nearest_km": None,
             "nearest_bearing_deg": None, "newest_age_s": None,
             "truncated": False},
            None,
        )

    rows.sort(key=lambda d: d["acq_at"], reverse=True)
    nearest = min(rows, key=lambda d: haversine_km(centre[0], centre[1], d["lat"], d["lon"]))
    east, west = max(r["lon"] for r in rows), min(r["lon"] for r in rows)
    north, south = max(r["lat"] for r in rows), min(r["lat"] for r in rows)

    data = {
        "count": total,
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "window_days": WINDOW_DAYS,
        "sensors": sorted({r["sensor"] for r in rows if r["sensor"]}),
        "detections": rows[:cap],
        "nearest_km": round(
            haversine_km(centre[0], centre[1], nearest["lat"], nearest["lon"]), 2
        ),
        "nearest_bearing_deg": round(
            bearing_deg(centre[0], centre[1], nearest["lat"], nearest["lon"])
        ),
        "newest_age_s": None,
        "truncated": total > CAP,
    }
    return ProviderPayload(data, rows[0]["acq_at"])


class FirmsProvider:
    id = "firms"
    key = "regional_fires"
    source_label = "NASA FIRMS"
    licence = "NASA FIRMS NRT - NASA Earthdata open data"
    attribution = "NASA FIRMS (Fire Information for Resource Management System)"
    ttl_s = 7200
    fetch_timeout_s = 6
    allow_inline = True
    requires: tuple[str, ...] = ("firms_map_key",)

    def __init__(self, *, fetch_text=None) -> None:
        self.fetch_text = fetch_text or http.get_text

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        if not cfg.firms_map_key:
            raise ProviderError("config", "firms_map_key_missing")
        box = f"{extent.west:.4f},{extent.south:.4f},{extent.east:.4f},{extent.north:.4f}"
        first_empty = None
        for source in SOURCES:
            url = URL.format(key=cfg.firms_map_key, source=source, box=box,
                             days=WINDOW_DAYS)
            text = self.fetch_text(url, timeout=self.fetch_timeout_s,
                                   secret=cfg.firms_map_key)
            payload = parse(text, extent.centre)
            payload.data["sensors"] = [source]
            if payload.data["count"]:
                return payload
            if first_empty is None:
                first_empty = payload
        if first_empty is not None:
            first_empty.data["sensors"] = list(SOURCES)
        return first_empty or ProviderPayload({"count": 0}, None)