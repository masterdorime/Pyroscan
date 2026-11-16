"""Copernicus DEM 30 m: cell naming, tile fetch, ring crop, adapter.

Measured behaviour (spec 7.5): every remote read of a tile transfers the whole
~34 MB object, including a single-pixel read. So this module downloads the tile
once, crops locally, and deletes it. A ring is covered by the single cell
containing its centre; crossing a cell boundary clips and is flagged.
"""
from __future__ import annotations

import math
from pathlib import Path

from .base import Extent

BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
SOURCE_RESOLUTION_M = 30
TILE_MAX_BYTES = 80_000_000


def tile_name(lat: float, lon: float) -> str:
    """Name of the 1-degree cell containing the point, by its SW corner."""
    south = math.floor(lat)
    west = math.floor(lon)
    ns = "N" if south >= 0 else "S"
    ew = "E" if west >= 0 else "W"
    return (f"Copernicus_DSM_COG_10_{ns}{abs(south):02d}_00_"
            f"{ew}{abs(west):03d}_00_DEM")


def tile_url(name: str) -> str:
    return f"{BASE_URL}/{name}/{name}.tif"


def cell_bounds(name: str) -> tuple[float, float, float, float]:
    """(west, south, east, north) parsed back out of a tile name."""
    parts = name.split("_")
    try:
        lat_part, lon_part = parts[4], parts[6]
        south = int(lat_part[1:]) * (1 if lat_part[0] == "N" else -1)
        west = int(lon_part[1:]) * (1 if lon_part[0] == "E" else -1)
    except (IndexError, ValueError):
        raise ValueError(f"not a Copernicus tile name: {name!r}") from None
    return float(west), float(south), float(west + 1), float(south + 1)
