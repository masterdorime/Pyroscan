"""Runnable self-check for the provider layer. No frameworks, no network."""
from __future__ import annotations

import sys
import traceback

from .base import (Extent, ProviderConfig, ProviderError, ProviderPayload,
                   ProviderResult)
from .cache import mission_dir, read_envelope, write_envelope
from .config import load, redact
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


@case
def config_env_beats_file():
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text("PYROSCAN_FIRMS_MAP_KEY=fromfile\n", encoding="utf-8")
    cfg = load(env_path=d / ".env", environ={"PYROSCAN_FIRMS_MAP_KEY": "fromenv"})
    assert cfg.firms_map_key == "fromenv"


@case
def config_file_and_quotes():
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text(
        '# comment\nPYROSCAN_FIRMS_MAP_KEY="quoted"\nPYROSCAN_REGIONAL_RING_KM=22\n',
        encoding="utf-8",
    )
    cfg = load(env_path=d / ".env", environ={})
    assert cfg.firms_map_key == "quoted"
    assert cfg.ring_km == 22.0


@case
def config_redacts_secret():
    out = redact("GET https://firms.example/api/csv/SECRET123/VIIRS/1,2,3,4/1", "SECRET123")
    assert "SECRET123" not in out
    assert "***" in out


@case
def cache_roundtrip_and_atomic():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    write_envelope("M1", "weather", {"schema": 1, "key": "weather", "data": {"a": 1}}, root=root)
    env = read_envelope("M1", "weather", root=root)
    assert env["data"] == {"a": 1}
    assert list((root / "M1").glob("*.tmp")) == []


@case
def cache_corrupt_returns_none():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    p = write_envelope("M1", "weather", {"schema": 1}, root=root)
    p.write_text("{not json", encoding="utf-8")
    assert read_envelope("M1", "weather", root=root) is None


@case
def cache_rejects_path_traversal():
    for bad in ("../evil", "a/b", "", "..", "a b"):
        try:
            mission_dir(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


@case
def cache_preserves_non_ascii():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    data = {"condition": "Cerah Berawan", "note": "Hujan Ringan - pantau", "name": "Kel. Sukajadi"}
    write_envelope("M1", "weather", {"schema": 1, "data": data}, root=root)
    back = read_envelope("M1", "weather", root=root)
    assert back["data"] == data
    raw = (root / "M1" / "weather.envelope.json").read_text(encoding="utf-8")
    assert "Cerah Berawan" in raw


if __name__ == "__main__":
    raise SystemExit(main())
