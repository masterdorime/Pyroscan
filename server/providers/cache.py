"""Per-mission provider cache. Atomic writes, derived status, disposable.

Layout: <root>/<mission_id>/<key>.envelope.json
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .. import config as server_config

KEY_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def _safe(value: str, label: str) -> str:
    if not isinstance(value, str) or not KEY_SAFE.match(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


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
    target = mission_dir(mission_id, root) / _safe(name, "asset name")
    return _atomic_write(target, data)
