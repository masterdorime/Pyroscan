"""BMKG adapter: Indonesia's own forecast, keyed by adm4.

Field names come from a real capture (`fixtures/bmkg/live.json`), not from the
spec's guess: BMKG supplies `datetime` already in UTC plus `wd_deg`, `ws`, `hu`,
`t`, `tp`, `tcc`. `local_datetime` is only a fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import http
from .adm4 import resolve
from .base import Extent, ProviderConfig, ProviderError, ProviderPayload

URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"


def _moment(entry: dict, tz: str) -> datetime | None:
    stamp = entry.get("datetime")
    if stamp:
        try:
            parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    local = entry.get("local_datetime")
    if not local:
        return None
    try:
        naive = datetime.fromisoformat(str(local))
    except ValueError:
        return None
    try:
        return naive.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)
    except Exception:
        return None


def _block(raw: dict) -> dict:
    data = raw.get("data")
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    raise ProviderError("parse", "missing 'data' block")


def parse(raw: dict, adm4: str, tz: str,
          now: datetime | None = None) -> ProviderPayload:
    """Flatten the 3-hourly forecast and pick the entry closest to `now`."""
    block = _block(raw)
    lokasi = block.get("lokasi") or {}
    served = str(lokasi.get("adm4") or "")
    if served and served != str(adm4):
        raise ProviderError("parse", f"adm4_mismatch: asked {adm4}, got {served}")

    days = block.get("cuaca")
    if not isinstance(days, list):
        raise ProviderError("parse", "missing 'cuaca'")
    entries = [e for day in days if isinstance(day, list)
               for e in day if isinstance(e, dict)]
    if not entries:
        raise ProviderError("parse", "empty forecast")

    moment = now or datetime.now(timezone.utc)
    timed = [(e, _moment(e, tz)) for e in entries]
    timed = [(e, m) for e, m in timed if m is not None]
    if not timed:
        raise ProviderError("parse", "no usable timestamps")
    chosen, chosen_at = min(timed, key=lambda pair: abs((pair[1] - moment).total_seconds()))

    try:
        data = {
            "wind_speed_kmh": float(chosen["ws"]),
            "wind_dir_deg": int(round(float(chosen["wd_deg"]))) % 360,
            "temp_c": float(chosen["t"]),
            "humidity_pct": int(round(float(chosen["hu"]))),
            "precip_mm": chosen.get("tp"),
            "cloud_pct": chosen.get("tcc"),
            "condition": chosen.get("weather_desc"),
            "adm4": adm4,
            "adm4_name": lokasi.get("desa") or None,
            "adm4_resolved_by": None,
            "forecast_hours": int(round(abs((chosen_at - moment).total_seconds()) / 3600)),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("parse", f"unexpected forecast entry: {exc}") from None

    return ProviderPayload(
        data, chosen_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


class BmkgProvider:
    id = "bmkg"
    key = "weather"
    source_label = "BMKG"
    licence = "BMKG public data - attribution required"
    attribution = "Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)"
    ttl_s = 1200
    fetch_timeout_s = 6
    allow_inline = True
    requires: tuple[str, ...] = ()

    def __init__(self, *, index_path: Path | None = None) -> None:
        self.index_path = index_path

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        match = resolve(extent, override=cfg.bmkg_adm4, index_path=self.index_path)
        if match is None:
            raise ProviderError("missing", "adm4_unresolved")
        raw = http.get_json(URL, {"adm4": match.code}, timeout=self.fetch_timeout_s)
        payload = parse(raw, match.code, match.tz)
        payload.data["adm4_resolved_by"] = match.resolved_by
        if match.name:
            payload.data["adm4_name"] = match.name
        return payload
