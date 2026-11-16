"""Deterministic fire-spread vector model.

This is a transparent heuristic, not Rothermel. Wind and upslope are summed as
vectors with configurable weights; the result is a rate and a bearing. Risk is
a fixed threshold on the rate, owned by the engine (never the LLM).
"""
from __future__ import annotations

import math

SLOPE_WEIGHT = 0.6
WIND_WEIGHT = 0.4
BASE_RATE = 3.0
MODEL_VERSION = "pyroscan-spread-0.1"

# Risk thresholds in m/min. Documented so the dashboard and advisory agree.
LOW_MAX = 10.0
MEDIUM_MAX = 20.0
HIGH_MAX = 32.0


def risk_from_rate(rate_m_min: float) -> str:
    if rate_m_min >= HIGH_MAX:
        return "CRITICAL"
    if rate_m_min >= MEDIUM_MAX:
        return "HIGH"
    if rate_m_min >= LOW_MAX:
        return "MEDIUM"
    return "LOW"


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def predict(hotspot: dict, weather: dict, horizons=(30, 60)) -> list[dict]:
    wind_from = float(weather.get("wind_dir_deg") or 0.0)
    wind_to = (wind_from + 180.0) % 360.0
    slope = _clamp(float(hotspot.get("slope_deg") or 0.0), 0.0, 60.0)
    upslope = (float(hotspot.get("aspect_deg") or 0.0) + 180.0) % 360.0

    wind_a = 12.0 * (float(weather.get("wind_speed_kmh") or 0.0) / 10.0)
    slope_a = 20.0 * math.tan(math.radians(slope))
    ve = WIND_WEIGHT * wind_a * math.sin(math.radians(wind_to)) + \
        SLOPE_WEIGHT * slope_a * math.sin(math.radians(upslope))
    vn = WIND_WEIGHT * wind_a * math.cos(math.radians(wind_to)) + \
        SLOPE_WEIGHT * slope_a * math.cos(math.radians(upslope))
    rate = BASE_RATE + math.hypot(ve, vn)
    bearing = math.degrees(math.atan2(ve, vn)) % 360.0 if (ve or vn) else wind_to

    lat0 = float(hotspot["lat"])
    lon0 = float(hotspot["lon"])
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))
    out = []
    for h in horizons:
        dist = rate * h
        out.append({
            "hotspot_id": hotspot["id"],
            "horizon_min": h,
            "predicted_lat": lat0 + (dist * math.cos(math.radians(bearing))) / m_lat,
            "predicted_lon": lon0 + (dist * math.sin(math.radians(bearing))) / m_lon,
            "risk_level": risk_from_rate(rate),
            "slope_weight": SLOPE_WEIGHT,
            "wind_weight": WIND_WEIGHT,
            "rate_m_min": round(rate, 2),
            "bearing_deg": round(bearing, 1),
            "model_version": MODEL_VERSION,
        })
    return out
