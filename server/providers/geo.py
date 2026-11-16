"""Geodesy helpers: ring extent, great-circle distance, compass bearing."""
from __future__ import annotations

import math

from .base import Extent

KM_PER_DEG_LAT = 111.32
EARTH_RADIUS_KM = 6371.0088


def _padded(west: float, south: float, east: float, north: float,
            ring_km: float) -> Extent:
    ring_km = min(25.0, max(10.0, float(ring_km)))
    lat = (south + north) / 2
    lat_pad = ring_km / KM_PER_DEG_LAT
    lon_pad = ring_km / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return Extent(
        west=west - lon_pad,
        south=south - lat_pad,
        east=east + lon_pad,
        north=north + lat_pad,
        ring_km=ring_km,
    )


def mission_extent(bbox: dict, ring_km: float) -> Extent:
    """Mission bbox grown by a kilometre-correct regional ring."""
    return _padded(bbox["west"], bbox["south"], bbox["east"], bbox["north"], ring_km)


def extent_from_point(lat: float, lon: float, radius_km: float = 0.5) -> Extent:
    """A small box around one point, for point-based providers."""
    return _padded(lon, lat, lon, lat, radius_km * 2)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
