"""Runnable self-check for the provider layer. No frameworks, no network."""
from __future__ import annotations

import sys
import traceback

from .base import (Extent, ProviderConfig, ProviderError, ProviderPayload,
                   ProviderResult)
from .geo import bearing_deg, haversine_km, mission_extent

CASES: dict[str, object] = {}


def case(fn):
    CASES[fn.__name__] = fn
    return fn


def main(argv: list[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    if "--live" in names:
        names.remove("--live")
    selected = names or list(CASES)
    failed = 0
    for name in selected:
        fn = CASES.get(name)
        if fn is None:
            print(f"UNKNOWN {name}")
            failed += 1
            continue
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{len(selected) - failed}/{len(selected)} passed")
    return 1 if failed else 0


@case
def geo_extent_ring_km():
    bbox = {"west": 107.600, "south": -6.920, "east": 107.610, "north": -6.919}
    e = mission_extent(bbox, 15)
    assert e.ring_km == 15.0
    lat_span = e.north - e.south
    lon_span = e.east - e.west
    assert round(lat_span, 4) == round(0.001 + 30 / 111.32, 4)
    assert lon_span > lat_span
    assert -6.9201 < e.centre[0] < -6.9189


@case
def geo_extent_clamps():
    bbox = {"west": 107.6, "south": -6.92, "east": 107.61, "north": -6.919}
    assert mission_extent(bbox, 99).ring_km == 25.0
    assert mission_extent(bbox, 1).ring_km == 10.0


@case
def geo_distance_and_bearing():
    assert abs(haversine_km(-6.9, 107.6, -6.9, 107.61) - 1.108) < 0.01
    assert abs(bearing_deg(-6.9, 107.6, -6.9, 107.61) - 90.0) < 0.5
    assert abs(bearing_deg(-6.9, 107.6, -6.89, 107.6) - 0.0) < 0.5


if __name__ == "__main__":
    raise SystemExit(main())
