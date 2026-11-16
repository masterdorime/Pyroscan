"""Resolve a BMKG adm4 code from a bundled Indonesian boundary index.

BMKG keys forecasts by adm4 (village-level) but publishes no machine-readable
code-to-boundary index. We ship a derived one; when it is empty the resolver
returns None and the weather key falls back to Open-Meteo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .base import Extent

DEFAULT_INDEX = Path(__file__).resolve().parent / "data" / "adm4_index.json"
DEFAULT_TZ = "Asia/Jakarta"


@dataclass(frozen=True)
class Adm4Match:
    code: str
    name: str | None
    tz: str
    resolved_by: str  # manual | index | adm3_fallback


def _bbox(entry: dict) -> tuple[float, float, float, float] | None:
    box = entry.get("bbox")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        return tuple(float(v) for v in box)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def load_index(path: Path | None = None) -> list[dict]:
    """Read the index, tolerating a missing or malformed file by returning []."""
    try:
        raw = json.loads(Path(path or DEFAULT_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("entries") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and _bbox(e) is not None]


def _contains(entry: dict, lat: float, lon: float) -> bool:
    box = _bbox(entry)
    if box is None:
        return False
    west, south, east, north = box
    return west <= lon <= east and south <= lat <= north


def _area(entry: dict) -> float:
    west, south, east, north = _bbox(entry)  # type: ignore[misc]
    return max(0.0, east - west) * max(0.0, north - south)


def resolve(extent: Extent, *, override: str | None = None,
            index_path: Path | None = None) -> Adm4Match | None:
    """Explicit override wins; otherwise the smallest containing box does."""
    if override:
        return Adm4Match(override, None, DEFAULT_TZ, "manual")

    lat, lon = extent.centre
    hits = [e for e in load_index(index_path) if _contains(e, lat, lon)]
    if not hits:
        return None

    adm4 = [e for e in hits if e.get("level") == "adm4"]
    chosen_level = "index" if adm4 else "adm3_fallback"
    candidates = adm4 or hits
    best = min(candidates, key=_area)
    return Adm4Match(
        code=str(best.get("code") or ""),
        name=best.get("name"),
        tz=str(best.get("tz") or DEFAULT_TZ),
        resolved_by=chosen_level,
    )
