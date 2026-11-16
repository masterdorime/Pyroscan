"""Per-mission provider cache. Atomic writes, derived status, disposable.

Layout: <root>/<mission_id>/<key>.envelope.json
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import config as server_config

KEY_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
ASSET_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_NETWORK_WORDS = ("network", "connection", "timeout", "timed out", "reset",
                  "unreachable", "dns", "refused", "http")


@dataclass(frozen=True)
class Derived:
    """A status computed at read time. Never persisted."""
    status: str
    reason: str | None
    age_s: int | None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_networkish(env: dict) -> bool:
    if env.get("last_error_kind") in ("network", "http"):
        return True
    message = str(env.get("last_error") or "").lower()
    return any(word in message for word in _NETWORK_WORDS)


def derive(env: dict | None, ttl_s: int, *, configured: bool = True,
           now: datetime | None = None) -> Derived:
    """Spec §7.3: status describes the cache the client received.

    `reason` describes the latest fetch outcome and is independent of `status`.
    An unknown age is never reported as fresh, and a future timestamp is
    clamped to age 0 rather than producing a negative age.
    """
    if not configured:
        return Derived("unconfigured", "not_configured", None)
    if env is None:
        return Derived("error", "never_fetched", None)

    moment = now or datetime.now(timezone.utc)
    reference = _parse_ts(env.get("observed_at")) or _parse_ts(env.get("fetched_at"))
    if reference is None:
        return Derived("stale", "unknown_age", None)

    age_s = max(0, int((moment - reference).total_seconds()))
    reason = env.get("last_error") or None
    data = env.get("data")

    # A recorded network failure outranks a fresh-looking age: the cache is the
    # last good copy and we have not been able to confirm it since.
    if _is_networkish(env):
        return Derived("offline", reason, age_s)
    if age_s <= ttl_s:
        if isinstance(data, dict) and "count" in data and data.get("count") == 0:
            return Derived("empty", reason, age_s)
        return Derived("fresh", reason, age_s)
    return Derived("stale", reason, age_s)


def _safe(value: str, label: str) -> str:
    if not isinstance(value, str) or not KEY_SAFE.match(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _safe_asset(name: str) -> str:
    """Assets carry an extension (context_dem.json), so dots are allowed."""
    if (not isinstance(name, str) or not ASSET_SAFE.match(name)
            or name in (".", "..") or ".." in name):
        raise ValueError(f"unsafe asset name: {name!r}")
    return name


def mission_dir(mission_id: str, root: Path | None = None) -> Path:
    """Cache directory for one mission. Rejects path traversal."""
    return Path(root or server_config.PROVIDERS_CACHE) / _safe(mission_id, "mission id")


def _envelope_path(mission_id: str, key: str, root: Path | None) -> Path:
    return mission_dir(mission_id, root) / f"{_safe(key, 'provider key')}.envelope.json"


def _atomic_write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def write_envelope(mission_id: str, key: str, envelope: dict,
                   root: Path | None = None) -> Path:
    """Serialise an envelope atomically; a crash leaves old or new, never half."""
    payload = json.dumps(envelope, ensure_ascii=False, indent=2)
    return _atomic_write(_envelope_path(mission_id, key, root),
                         payload.encode("utf-8"))


def read_envelope(mission_id: str, key: str,
                  root: Path | None = None) -> dict | None:
    """Read an envelope, or None when missing, unreadable, or malformed."""
    path = _envelope_path(mission_id, key, root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_asset(mission_id: str, name: str, data: bytes,
                root: Path | None = None) -> Path:
    """Store a binary sidecar (imagery, DEM) next to the envelopes."""
    target = mission_dir(mission_id, root) / _safe_asset(name)
    return _atomic_write(target, data)
