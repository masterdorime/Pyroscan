"""Runnable self-check for the provider layer. No frameworks, no network."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from .adm4 import resolve
from .base import (Extent, ProviderConfig, ProviderError, ProviderPayload,
                   ProviderResult)
from .cache import derive, mission_dir, read_envelope, write_envelope
from .config import load, redact
from .geo import bearing_deg, haversine_km, mission_extent
from .gateway import Gateway
from .http import get_json, get_text

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


def _env(**kw):
    base = {"observed_at": "2026-11-16T06:00:00Z", "fetched_at": "2026-11-16T06:00:05Z",
            "last_error": None, "fail_count": 0, "data": {"count": 3}}
    base.update(kw)
    return base


def _now():
    return datetime(2026, 11, 16, 6, 10, tzinfo=timezone.utc)


@case
def status_matrix():
    now = _now()
    assert derive(None, 1200, now=now).status == "error"
    assert derive(None, 1200, now=now).reason == "never_fetched"
    assert derive(None, 1200, configured=False, now=now).status == "unconfigured"
    assert derive(_env(), 1200, now=now).status == "fresh"
    assert derive(_env(observed_at="2026-11-16T05:20:00Z"), 1200, now=now).status == "stale"
    assert derive(_env(data={"count": 0}), 1200, now=now).status == "empty"
    assert derive(_env(last_error="connection reset"), 1200, now=now).status == "offline"
    assert derive(None, 1200, now=now).status == "error"


@case
def status_future_timestamp_is_not_fresh_forever():
    now = datetime(2026, 11, 16, 6, 10, tzinfo=timezone.utc)
    d = derive(_env(observed_at="2026-11-16T09:00:00Z"), 1200, now=now)
    assert d.age_s == 0
    assert d.status == "fresh"


@case
def status_unknown_age_is_stale():
    now = _now()
    d = derive(_env(observed_at=None, fetched_at=None), 1200, now=now)
    assert d.age_s is None
    assert d.status == "stale"
    assert d.reason == "unknown_age"


@case
def status_reason_independent_of_status():
    now = _now()
    d = derive(_env(observed_at="2026-11-16T05:20:00Z", last_error="no_usable_scene"),
               1200, now=now)
    assert d.status == "stale"
    assert d.reason == "no_usable_scene"


class _Resp:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text


@case
def http_network_error_is_typed():
    def boom(*a, **k):
        import requests
        raise requests.ConnectionError("reset")
    try:
        get_text("https://x/y", timeout=6, fetcher=boom)
    except ProviderError as e:
        assert e.kind == "network"
        return
    raise AssertionError("no ProviderError")


@case
def http_status_error_is_typed_and_redacted():
    def bad(*a, **k):
        return _Resp(status=500)
    try:
        get_text("https://x/csv/SECRET123/VIIRS", timeout=6, secret="SECRET123", fetcher=bad)
    except ProviderError as e:
        assert e.kind == "http"
        assert "SECRET123" not in str(e)
        return
    raise AssertionError("no ProviderError")


@case
def http_json_parse_error_is_typed():
    def html(*a, **k):
        return _Resp(text="<html>nope</html>")
    try:
        get_json("https://x/y", timeout=6, fetcher=html)
    except ProviderError as e:
        assert e.kind == "parse"
        return
    raise AssertionError("no ProviderError")


class _Spy:
    """Minimal adapter answering one key."""

    def __init__(self, key="weather", data=None, observed="2026-11-16T06:00:00Z",
                 allow_inline=True, ttl_s=1200, boom=None):
        self.id = "spy"
        self.key = key
        self.source_label = "Spy"
        self.licence = "test"
        self.attribution = "test"
        self.ttl_s = ttl_s
        self.fetch_timeout_s = 6
        self.allow_inline = allow_inline
        self.requires = ()
        self.data = data if data is not None else {"count": 1}
        self.observed = observed
        self.boom = boom
        self.calls = 0

    def fetch(self, extent, cfg):
        self.calls += 1
        if self.boom:
            raise self.boom
        return ProviderPayload(self.data, self.observed)


class _Tasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **k):
        self.tasks.append((fn, a, k))


_FIXED_NOW = datetime(2026, 11, 16, 6, 10, tzinfo=timezone.utc)


def _cfg():
    return ProviderConfig(firms_map_key=None, bmkg_adm4=None, ring_km=15.0,
                          offline=False, ttl_overrides={})


def _gw_from(registry, root):
    """Gateway with a frozen clock so status assertions never depend on wall time."""
    return Gateway(registry, _cfg(), root=root, now_fn=lambda: _FIXED_NOW)


def _gw(adapter, root):
    return _gw_from({adapter.key: (adapter,)}, root)


def _extent():
    return mission_extent({"west": 107.6, "south": -6.92,
                           "east": 107.61, "north": -6.919}, 15)


@case
def gateway_fresh_cache_skips_adapter():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy()
    gw = _gw(spy, root)
    gw.refresh_now("M1", "weather", _extent())
    assert spy.calls == 1
    r = gw.get("M1", "weather", _extent())
    assert r.status == "fresh" and spy.calls == 1


@case
def gateway_stale_serves_cache_and_queues_once():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(observed="2026-11-16T05:00:00Z")
    gw = _gw(spy, root)
    gw.refresh_now("M1", "weather", _extent())
    tasks = _Tasks()
    r1 = gw.get("M1", "weather", _extent())
    gw.refresh_async(tasks, "M1", "weather", _extent())
    gw.refresh_async(tasks, "M1", "weather", _extent())
    assert r1.data is not None
    assert len(tasks.tasks) == 1


@case
def gateway_cold_light_fetches_inline():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(allow_inline=True)
    gw = _gw(spy, root)
    r = gw.get("M1", "weather", _extent())
    assert r.status in ("fresh", "empty") and spy.calls == 1


@case
def gateway_cold_heavy_returns_warming():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(key="context_dem", allow_inline=False, ttl_s=2592000)
    gw = _gw(spy, root)
    tasks = _Tasks()
    r = gw.get("M1", "context_dem", _extent(), background=tasks)
    assert r.status == "unavailable"
    assert r.reason == "warming"
    assert spy.calls == 0
    assert len(tasks.tasks) == 1


@case
def chain_falls_through_when_primary_unavailable():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    bmkg = _Spy(boom=ProviderError("missing", "adm4_unresolved"))
    om = _Spy(data={"wind_speed_kmh": 12})
    gw = _gw_from({"weather": (bmkg, om)}, root)
    r = gw.get("M1", "weather", _extent())
    assert r.source == "spy" and r.data["wind_speed_kmh"] == 12
    assert r.fallback_from == bmkg.id


@case
def chain_records_failed_attempt():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    bmkg = _Spy(boom=ProviderError("network", "reset"))
    om = _Spy(data={"wind_speed_kmh": 9})
    gw = _gw_from({"weather": (bmkg, om)}, root)
    gw.get("M1", "weather", _extent())
    env = read_envelope("M1", "weather", root=root)
    assert env["fail_count"] == 1


@case
def chain_stale_primary_does_not_fall_through():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    bmkg = _Spy(observed="2026-11-16T05:00:00Z", data={"wind_speed_kmh": 3})
    om = _Spy(data={"wind_speed_kmh": 99})
    gw = _gw_from({"weather": (bmkg, om)}, root)
    gw.refresh_now("M1", "weather", _extent())
    r = gw.get("M1", "weather", _extent())
    assert r.status == "stale" and r.data["wind_speed_kmh"] == 3 and om.calls == 0


@case
def fixture_fallback_is_simulated_and_not_cached():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(key="regional_fires", boom=ProviderError("network", "reset"))
    gw = _gw(spy, root)
    r = gw.get("M1", "regional_fires", _extent())
    assert r.status == "error" and r.simulated is True
    assert r.reason == "fixture_fallback"
    assert read_envelope("M1", "regional_fires", root=root) is None
    gw.get("M1", "regional_fires", _extent())
    assert spy.calls == 2


@case
def unconfigured_beats_fixture_fallback():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(key="regional_fires")
    spy.requires = ("firms_map_key",)
    gw = _gw(spy, root)
    r = gw.get("M1", "regional_fires", _extent())
    assert r.status == "unconfigured"
    assert r.configured is False and r.simulated is False
    assert spy.calls == 0
    assert read_envelope("M1", "regional_fires", root=root) is None


@case
def open_meteo_parses_fixture():
    import json
    from pathlib import Path
    from server.providers import open_meteo
    raw = json.loads(
        (Path(__file__).parent / "fixtures/open_meteo/live.json").read_text(encoding="utf-8")
    )
    payload = open_meteo.parse(raw)
    assert set(payload.data) >= {
        "wind_speed_kmh", "wind_dir_deg", "temp_c", "humidity_pct", "precip_mm",
        "cloud_pct", "condition", "adm4", "adm4_name", "adm4_resolved_by",
        "forecast_hours",
    }
    assert payload.data["adm4"] is None
    assert payload.data["forecast_hours"] is None
    assert payload.observed_at.endswith("Z")
    assert 0 <= payload.data["wind_dir_deg"] <= 359


_ADM4_INDEX = {"schema": 1, "entries": [
    {"code": "32.73.15.2001", "name": "Kel. Sukajadi", "level": "adm4",
     "bbox": [107.58, -6.93, 107.62, -6.90], "tz": "Asia/Jakarta"},
    {"code": "32.73.15.2002", "name": "Kel. Pasteur", "level": "adm4",
     "bbox": [107.59, -6.92, 107.61, -6.91], "tz": "Asia/Jakarta"},
    {"code": "32.73.15", "name": "Kec. Sukajadi", "level": "adm3",
     "bbox": [107.57, -6.94, 107.63, -6.89], "tz": "Asia/Jakarta"},
]}


def _index(tmpdir):
    import json
    from pathlib import Path
    p = Path(tmpdir) / "adm4.json"
    p.write_text(json.dumps(_ADM4_INDEX), encoding="utf-8")
    return p


@case
def adm4_empty_index_resolves_nothing():
    import json, tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "i.json"
    p.write_text(json.dumps({"schema": 1, "entries": []}), encoding="utf-8")
    assert resolve(_extent(), index_path=p) is None


@case
def adm4_missing_index_resolves_nothing():
    import tempfile
    from pathlib import Path
    assert resolve(_extent(), index_path=Path(tempfile.mkdtemp()) / "nope.json") is None


@case
def adm4_picks_smallest_containing_bbox():
    import tempfile
    m = resolve(_extent(), index_path=_index(tempfile.mkdtemp()))
    assert m.code == "32.73.15.2002" and m.resolved_by == "index"


@case
def adm4_manual_override_wins():
    import tempfile
    m = resolve(_extent(), override="99.99.99.9999", index_path=_index(tempfile.mkdtemp()))
    assert m.code == "99.99.99.9999" and m.resolved_by == "manual"


@case
def adm4_adm3_fallback_only_without_adm4():
    import json, tempfile
    from pathlib import Path
    p = Path(tempfile.mkdtemp()) / "i.json"
    only3 = {"schema": 1, "entries": [_ADM4_INDEX["entries"][2]]}
    p.write_text(json.dumps(only3), encoding="utf-8")
    m = resolve(_extent(), index_path=p)
    assert m.code == "32.73.15" and m.resolved_by == "adm3_fallback"


if __name__ == "__main__":
    raise SystemExit(main())
