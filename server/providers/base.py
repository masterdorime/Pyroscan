"""Shared types for the provider layer. No I/O, no provider specifics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Extent:
    """A geographic box, plus the size of the regional ring around it."""
    west: float
    south: float
    east: float
    north: float
    ring_km: float = 15.0

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.south + self.north) / 2, (self.west + self.east) / 2)


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved provider settings. Keys stay server-side; never serialise this."""
    firms_map_key: str | None = None
    bmkg_adm4: str | None = None
    ring_km: float = 15.0
    offline: bool = False
    ttl_overrides: dict[str, int] = field(default_factory=dict)


@dataclass
class ProviderPayload:
    """What an adapter returns: normalised data plus the provider's own timestamp."""
    data: dict
    observed_at: str | None
    extra: dict = field(default_factory=dict)


class ProviderError(Exception):
    """A typed adapter failure. `kind` decides the resulting status."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class Provider(Protocol):
    """An adapter. Pure translation: extent + config in, payload or error out."""
    id: str
    key: str
    source_label: str
    licence: str
    attribution: str
    ttl_s: int
    fetch_timeout_s: int
    allow_inline: bool
    requires: tuple[str, ...]

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload:
        ...


@dataclass
class ProviderResult:
    """The single envelope every payload key resolves to."""
    key: str
    data: dict | None
    source: str
    source_label: str
    observed_at: str | None
    fetched_at: str | None
    age_s: int | None
    ttl_s: int
    status: str
    reason: str | None
    error: str | None
    licence: str
    attribution: str
    simulated: bool
    configured: bool
    fallback_from: str | None
