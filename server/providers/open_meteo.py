"""Open-Meteo adapter: the global fallback for weather and wind."""
from __future__ import annotations

from . import http
from .base import Extent, ProviderConfig, ProviderError, ProviderPayload

URL = "https://api.open-meteo.com/v1/forecast"


def _observe(raw: dict) -> str:
    current = raw.get("current")
    if not isinstance(current, dict):
        raise ProviderError("parse", "missing 'current' block")
    moment = str(current.get("time") or "")
    if not moment:
        raise ProviderError("parse", "missing 'current.time'")
    return moment if moment.endswith("Z") else moment + "Z"


def parse(raw: dict) -> ProviderPayload:
    """Map Open-Meteo's `current` block onto the shared weather contract."""
    current = raw.get("current")
    if not isinstance(current, dict):
        raise ProviderError("parse", "missing 'current' block")
    try:
        data = {
            "wind_speed_kmh": float(current["wind_speed_10m"]),
            "wind_dir_deg": int(round(float(current["wind_direction_10m"]))) % 360,
            "temp_c": float(current["temperature_2m"]),
            "humidity_pct": int(round(float(current["relative_humidity_2m"]))),
            "precip_mm": current.get("precipitation"),
            "cloud_pct": current.get("cloud_cover"),
            "condition": None,
            "adm4": None,
            "adm4_name": None,
            "adm4_resolved_by": None,
            "forecast_hours": None,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("parse", f"unexpected current block: {exc}") from None
    return ProviderPayload(data, _observe(raw))


class OpenMeteoProvider:
    id = "open-meteo"
    key = "weather"
    source_label = "Open-Meteo"
    licence = "Open-Meteo free tier: non-commercial use, CC BY 4.0"
    attribution = "Weather data by Open-Meteo.com (CC BY 4.0)"
    ttl_s = 1200
    fetch_timeout_s = 6
    allow_inline = True
    requires: tuple[str, ...] = ()

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        lat, lon = extent.centre
        raw = http.get_json(
            URL,
            {
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "current": ("temperature_2m,relative_humidity_2m,"
                            "wind_speed_10m,wind_direction_10m"),
                "wind_speed_unit": "kmh",
                "timezone": "UTC",
            },
            timeout=self.fetch_timeout_s,
        )
        return parse(raw)
