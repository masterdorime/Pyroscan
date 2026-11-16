"""Which adapters answer which payload key, in priority order."""
from __future__ import annotations

from .base import Provider, ProviderConfig


def build_registry(cfg: ProviderConfig) -> dict[str, tuple[Provider, ...]]:
    """Build the chain table. Adapters are imported lazily: each phase adds its own.

    A missing adapter module is skipped, so this works while the layer is being
    built one task at a time.
    """
    chains: dict[str, tuple[Provider, ...]] = {}

    try:
        from . import open_meteo
        weather: list[Provider] = [open_meteo.OpenMeteoProvider()]
    except ImportError:
        weather = []

    try:
        from . import bmkg
        weather.insert(0, bmkg.BmkgProvider())
    except ImportError:
        pass

    if weather:
        chains["weather"] = tuple(weather)

    try:
        from . import firms
        chains["regional_fires"] = (firms.FirmsProvider(),)
    except ImportError:
        pass

    try:
        from . import copernicus_dem
        chains["context_dem"] = (copernicus_dem.CopernicusDemProvider(),)
    except ImportError:
        pass

    return chains
