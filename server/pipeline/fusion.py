"""DEM fusion: elevation, slope and aspect at each hotspot."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def load_heightmap(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _grid(hm: dict):
    w, h = int(hm["width"]), int(hm["height"])
    z = np.array(hm["heights_m"], dtype=float).reshape(h, w)
    if np.isnan(z).any():
        z = np.where(np.isnan(z), np.nanmedian(z), z)
    lat = (hm["south"] + hm["north"]) / 2.0
    width_m = (hm["east"] - hm["west"]) * 111320.0 * math.cos(math.radians(lat))
    height_m = (hm["north"] - hm["south"]) * 111320.0
    dx = width_m / max(w - 1, 1)
    dy = height_m / max(h - 1, 1)
    drow, dcol = np.gradient(z)
    d_east = dcol / dx
    d_north = -drow / dy
    slope = np.degrees(np.arctan(np.hypot(d_east, d_north)))
    aspect = (np.degrees(np.arctan2(-d_east, -d_north)) + 360.0) % 360.0
    return z, slope, aspect, width_m, height_m


def coverage_m2(hm: dict) -> float:
    lat = (hm["south"] + hm["north"]) / 2.0
    width_m = (hm["east"] - hm["west"]) * 111320.0 * math.cos(math.radians(lat))
    height_m = (hm["north"] - hm["south"]) * 111320.0
    return round(width_m * height_m, 1)


def sample(hm: dict, lat: float, lon: float) -> dict:
    z, slope, aspect, _, _ = _grid(hm)
    h, w = z.shape
    u = (lon - hm["west"]) / max(hm["east"] - hm["west"], 1e-12)
    v = (lat - hm["south"]) / max(hm["north"] - hm["south"], 1e-12)
    i = int(round(np.clip(u, 0, 1) * (w - 1)))
    j = int(round((1 - np.clip(v, 0, 1)) * (h - 1)))
    return {
        "elevation_m": round(float(z[j, i]), 2),
        "slope_deg": round(float(slope[j, i]), 1),
        "aspect_deg": round(float(aspect[j, i]), 1),
    }


def build_fusion(
    mission: dict,
    hm: dict,
    hotspots: list[dict],
    weather: dict,
    predictions: list[dict],
    photogrammetry: dict | None = None,
    burn_scar: dict | None = None,
) -> dict:
    enriched = []
    for s in hotspots:
        enriched.append({**s, **sample(hm, s["lat"], s["lon"])})

    primary = enriched[0] if enriched else None
    pred60 = next(
        (p for p in predictions if p["horizon_min"] == 60 and primary and p["hotspot_id"] == primary["id"]),
        None,
    )
    alt = [p for p in predictions if p["horizon_min"] != 60]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    fusion = {
        "schema_version": "1.1.0",
        "session_id": mission["id"],
        "mission_mode": mission.get("mission_mode", "PRE_FIRE"),
        "timestamp": now,
        "area_coverage_m2": coverage_m2(hm),
        "photogrammetry": photogrammetry or {
            "images_submitted": mission.get("photos"),
            "images_aligned": mission.get("aligned"),
            "align_ratio": mission.get("align_ratio"),
            "odm_task_id": mission.get("odm_task_id"),
        },
        "hotspots": [
            {
                "id": s["id"], "lat": s["lat"], "lon": s["lon"],
                "elevation_m": s.get("elevation_m"), "slope_deg": s.get("slope_deg"),
                "aspect_deg": s.get("aspect_deg"),
                "fire_confidence": s.get("fire_confidence"),
                "smoke_confidence": s.get("smoke_confidence"),
            }
            for s in enriched
        ],
        "environmental_data": {
            "wind_speed_kmh": weather.get("wind_speed_kmh"),
            "wind_direction_deg": weather.get("wind_dir_deg"),
            "humidity_pct": weather.get("humidity_pct"),
            "temperature_c": weather.get("temperature_c"),
            "source": weather.get("source"),
            "observed_at": weather.get("observed_at"),
            "age_minutes": weather.get("age_min"),
        },
        "wind_direction_convention": "FROM",
    }
    if pred60:
        fusion["spread_prediction"] = {
            "predicted_lat": pred60["predicted_lat"],
            "predicted_lon": pred60["predicted_lon"],
            "estimated_arrival_minutes": pred60["horizon_min"],
            "risk_level": pred60["risk_level"],
            "slope_weight": pred60.get("slope_weight"),
            "wind_weight": pred60.get("wind_weight"),
            "rate_m_min": pred60.get("rate_m_min"),
            "bearing_deg": pred60.get("bearing_deg"),
        }
    if alt:
        fusion["spread_prediction_alt"] = [
            {
                "predicted_lat": p["predicted_lat"],
                "predicted_lon": p["predicted_lon"],
                "estimated_arrival_minutes": p["horizon_min"],
                "risk_level": p["risk_level"],
            }
            for p in alt
        ]
    if burn_scar:
        fusion["burn_scar"] = burn_scar
    return fusion


def write_json(path: Path | str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
