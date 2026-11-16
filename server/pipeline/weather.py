"""Weather with an offline cache. The critical path never requires internet."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .. import config

MAX_AGE_MIN = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fixture() -> dict:
    path = config.WEB / "data" / "fixtures.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    w = data["weather"]
    observed = _now() - timedelta(minutes=int(w.get("age_min", 12)))
    return {
        "wind_speed_kmh": w["wind_speed_kmh"],
        "wind_dir_deg": w["wind_dir_deg"],
        "humidity_pct": w["humidity_pct"],
        "temperature_c": w["temp_c"],
        "source": "fixture (Open-Meteo shape)",
        "observed_at": observed.isoformat(),
        "is_cached": 1,
        "simulated": True,
        "age_min": int(w.get("age_min", 12)),
    }


def _from_gateway(mission_id: str, lat: float, lon: float,
                  online: bool) -> dict | None:
    """Resolve weather through the provider gateway, or None when it has nothing."""
    try:
        from ..providers.gateway import default_gateway
        from ..providers.geo import extent_from_point
    except Exception:
        return None

    try:
        res = default_gateway().get(mission_id, "weather",
                                    extent_from_point(lat, lon),
                                    allow_fetch=online)
    except Exception:
        return None
    if not res.data or res.data.get("wind_speed_kmh") is None:
        return None

    data = res.data
    return {
        "wind_speed_kmh": data.get("wind_speed_kmh"),
        "wind_dir_deg": data.get("wind_dir_deg"),
        "humidity_pct": data.get("humidity_pct"),
        "temperature_c": data.get("temp_c"),
        "source": res.source,
        "observed_at": res.observed_at,
        "is_cached": 0 if res.status == "fresh" else 1,
        "simulated": res.simulated,
        "age_min": int((res.age_s or 0) / 60),
    }


def _age_min(observed_at: str) -> int:
    try:
        dt = datetime.fromisoformat(observed_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((_now() - dt).total_seconds() / 60))
    except Exception:
        return 999


def get_weather(lat: float, lon: float, online: bool = False,
                cache_path: Path | None = None,
                *, mission_id: str | None = None) -> dict:
    """Weather for the pipeline.

    With a `mission_id` the provider gateway answers (BMKG, then Open-Meteo) and
    the result is cached per mission. Without one — or when the gateway has
    nothing usable — the original cache-file + fixture path runs unchanged, so
    the pipeline keeps working offline.
    """
    if mission_id:
        resolved = _from_gateway(mission_id, lat, lon, online)
        if resolved is not None:
            return resolved

    cache_path = cache_path or (config.CACHE / "weather.json")
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            age = _age_min(cached.get("observed_at", ""))
            if age <= MAX_AGE_MIN:
                cached["age_min"] = age
                return cached
        except Exception:
            pass

    if online:
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
                    "wind_speed_unit": "kmh", "timezone": "UTC",
                },
                timeout=6,
            )
            r.raise_for_status()
            cur = r.json()["current"]
            w = {
                "wind_speed_kmh": cur["wind_speed_10m"],
                "wind_dir_deg": cur["wind_direction_10m"],
                "humidity_pct": cur["relative_humidity_2m"],
                "temperature_c": cur["temperature_2m"],
                "source": "open-meteo",
                "observed_at": _now().replace(microsecond=0).isoformat(),
                "is_cached": 0,
                "simulated": False,
                "age_min": 0,
            }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(w, indent=2), encoding="utf-8")
            return w
        except Exception:
            pass

    w = _fixture()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(w, indent=2), encoding="utf-8")
    return w
