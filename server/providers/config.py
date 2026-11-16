"""Provider configuration: stdlib .env loader, no new dependencies.

Real environment variables win over .env, which wins over defaults. Keys are
read here and only here; nothing in this module is ever serialised.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import config as server_config
from .base import ProviderConfig

ENV_KEYS = (
    "PYROSCAN_FIRMS_MAP_KEY",
    "PYROSCAN_BMKG_ADM4",
    "PYROSCAN_REGIONAL_RING_KM",
    "PYROSCAN_PROVIDER_OFFLINE",
    "PYROSCAN_EARTHDATA_TOKEN",
    "PYROSCAN_CDSE_CLIENT_ID",
    "PYROSCAN_CDSE_SECRET",
)

_TRUTHY = {"1", "true", "yes", "on"}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load(*, env_path: Path | None = None,
         environ: dict[str, str] | None = None) -> ProviderConfig:
    """Merge defaults, .env, then the real environment."""
    merged = _read_env_file(env_path or (server_config.ROOT / ".env"))
    merged.update(os.environ if environ is None else environ)

    ring_raw = merged.get("PYROSCAN_REGIONAL_RING_KM")
    try:
        ring_km = float(ring_raw) if ring_raw else 15.0
    except ValueError:
        ring_km = 15.0

    overrides: dict[str, int] = {}
    for key, value in merged.items():
        if key.startswith("PYROSCAN_TTL_") and key.endswith("_S"):
            try:
                overrides[key[len("PYROSCAN_TTL_"):-2].lower()] = int(value)
            except ValueError:
                continue

    return ProviderConfig(
        firms_map_key=merged.get("PYROSCAN_FIRMS_MAP_KEY") or None,
        bmkg_adm4=merged.get("PYROSCAN_BMKG_ADM4") or None,
        ring_km=ring_km,
        offline=str(merged.get("PYROSCAN_PROVIDER_OFFLINE", "")).lower() in _TRUTHY,
        ttl_overrides=overrides,
    )


def redact(text: str, secret: str | None) -> str:
    """Strip a credential out of any string that could be logged or returned."""
    if secret:
        text = text.replace(secret, "***")
    return text
