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
        chains["context_dem_wide"] = (
            copernicus_dem.CopernicusDemProvider(
                window_km=60.0, size=256, key="context_dem_wide",
                asset="context_dem_wide.json",
                source_label="Copernicus DEM (60 km)"),)
    except ImportError:
        pass

    try:
        from . import sentinel2
        chains["context_imagery"] = (sentinel2.Sentinel2Provider(),)
        chains["context_imagery_wide"] = (
            sentinel2.Sentinel2WideProvider(
                source_label="Sentinel-2 (60 km)"),)
    except ImportError:
        pass

    return chains
