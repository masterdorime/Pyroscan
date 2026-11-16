"""Runnable self-check for the provider layer. No frameworks, no network."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from .adm4 import resolve
from .base import (Extent, ProviderConfig, ProviderError, ProviderPayload,
                   ProviderResult)
from .bmkg import BmkgProvider
from .cache import (derive, mission_dir, read_envelope, write_asset,
                    write_envelope)
from .config import load, redact
from .firms import FirmsProvider
from .geo import bearing_deg, haversine_km, mission_extent
from .gateway import Gateway
from .http import get_json, get_text
from .prefetch import run_prefetch

CASES: dict[str, object] = {}


def case(fn):
    CASES[fn.__name__] = fn
    return fn


def main(argv: list[str] | None = None) -> int:
    names = list(sys.argv[1:] if argv is None else argv)
    live = "--live" in names
    if live:
        names.remove("--live")
    if live:
        return live_smoke()
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
                 allow_inline=True, ttl_s=1200, boom=None,
                 attribution="test", licence="test"):
        self.id = "spy"
        self.key = key
        self.source_label = "Spy"
        self.licence = licence
        self.attribution = attribution
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


def _bmkg_raw():
    import json
    from pathlib import Path
    return json.loads(
        (Path(__file__).parent / "fixtures/bmkg/live.json").read_text(encoding="utf-8")
    )


@case
def bmkg_parses_fixture_and_picks_nearest_entry():
    from server.providers import bmkg
    raw = _bmkg_raw()
    adm4 = raw["data"][0]["lokasi"]["adm4"]
    now = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)
    p = bmkg.parse(raw, adm4, "Asia/Jakarta", now)
    assert p.data["adm4"] == adm4
    assert 0 <= p.data["wind_dir_deg"] <= 359
    assert p.observed_at.endswith("Z")
    assert p.data["forecast_hours"] >= 0
    assert p.data["condition"]


@case
def bmkg_rejects_mismatched_adm4():
    from server.providers import bmkg
    raw = _bmkg_raw()
    now = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)
    try:
        bmkg.parse(raw, "00.00.00.0000", "Asia/Jakarta", now)
    except ProviderError as e:
        assert e.kind == "parse"
        return
    raise AssertionError("accepted a response for a different adm4")


@case
def bmkg_unresolved_adm4_is_missing_not_error():
    import tempfile
    from pathlib import Path
    prov = BmkgProvider(index_path=Path(tempfile.mkdtemp()) / "empty.json")
    try:
        prov.fetch(_extent(), _cfg())
    except ProviderError as e:
        assert e.kind == "missing" and e.detail == "adm4_unresolved"
        return
    raise AssertionError("no ProviderError")


_FIRMS_HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
                 "satellite,instrument,confidence,version,bright_ti5,frp,daynight")


def _firms_csv(rows):
    return "\n".join([_FIRMS_HEADER] + rows) + "\n"


def _row(lat, lon, date, t, conf="n", sensor="VIIRS"):
    return f"{lat},{lon},330.1,0.4,0.4,{date},{t},{sensor},VIIRS,{conf},2.0NRT,290.2,4.2,D"


@case
def firms_parses_fixture():
    from pathlib import Path
    from server.providers import firms
    text = (Path(__file__).parent / "fixtures/firms/live.csv").read_text(encoding="utf-8")
    p = firms.parse(text, (-6.9, 107.6))
    assert p.data["count"] == len(p.data["detections"])
    assert p.observed_at.endswith("Z")
    assert all(0 <= d["confidence"] <= 1 for d in p.data["detections"])
    assert p.data["nearest_km"] is not None and p.data["nearest_km"] > 0


@case
def firms_handles_three_digit_acq_time():
    from server.providers import firms
    text = _firms_csv([_row(-6.9, 107.6, "2026-11-16", "420")])
    p = firms.parse(text, (-6.9, 107.6))
    assert p.data["detections"][0]["acq_at"] == "2026-11-16T04:20:00Z"


@case
def firms_caps_at_500_and_flags_truncation():
    from server.providers import firms
    rows = [_row(-6.9 + i * 0.0001, 107.6, "2026-11-16",
                 f"{(i % 1440) // 60:02d}{i % 60:02d}") for i in range(5000)]
    p = firms.parse(_firms_csv(rows), (-6.9, 107.6))
    assert len(p.data["detections"]) == 500
    assert p.data["truncated"] is True
    assert p.data["count"] == 5000


@case
def firms_empty_csv_is_empty_not_error():
    from server.providers import firms
    p = firms.parse(_FIRMS_HEADER + "\n", (-6.9, 107.6))
    assert p.data["count"] == 0 and p.data["detections"] == []
    assert p.observed_at is None


@case
def firms_missing_key_is_unconfigured():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"regional_fires": (FirmsProvider(),)}, root)
    r = gw.get("M1", "regional_fires", _extent())
    assert r.status == "unconfigured"
    assert r.configured is False


@case
def prefetch_runs_refresh_for_requested_keys():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy()
    gw = _gw(spy, root)
    events = run_prefetch(gw, "M1", _extent(), keys=["weather"])
    assert spy.calls == 1
    assert events[0]["key"] == "weather"
    assert events[0]["status"] in ("fresh", "empty", "stale")


@case
def providers_summary_is_compact_and_key_free():
    from server.api import providers_summary
    res = {"weather": ProviderResult(
        key="weather", data={"wind_speed_kmh": 12}, source="bmkg",
        source_label="BMKG", observed_at="2026-11-16T06:00:00Z",
        fetched_at="2026-11-16T06:00:05Z", age_s=120, ttl_s=1200,
        status="fresh", reason=None, error=None,
        licence="BMKG public", attribution="BMKG", simulated=False,
        configured=True, fallback_from=None)}
    out = providers_summary(res, 15.0, False)
    assert out["ring_km"] == 15.0 and out["offline"] is False
    assert out["items"]["weather"]["status"] == "fresh"
    assert out["items"]["weather"]["age_s"] == 120
    assert out["items"]["weather"]["attribution"] == "BMKG"
    assert out["items"]["weather"]["licence"] == "BMKG public"
    assert "data" not in out["items"]["weather"]


@case
def attribution_follows_the_winning_adapter():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    primary = _Spy(boom=ProviderError("network", "reset"),
                   attribution="Primary", licence="Licence A")
    secondary = _Spy(data={"wind_speed_kmh": 5},
                     attribution="Secondary", licence="Licence B")
    gw = _gw_from({"weather": (primary, secondary)}, root)
    gw.get("M1", "weather", _extent())
    r = gw.get("M1", "weather", _extent())  # cache hit: the real path for the UI
    assert r.source == "spy"
    assert r.attribution == "Secondary" and r.licence == "Licence B"


@case
def unconfigured_reported_even_when_fetch_disallowed():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(key="regional_fires")
    spy.requires = ("firms_map_key",)
    gw = _gw(spy, root)
    r = gw.get("M1", "regional_fires", _extent(), allow_fetch=False)
    assert r.status == "unconfigured"


@case
def prediction_uses_passed_weather_not_db_row():
    from server.api import _prediction
    bundle = {"weather": {"wind_dir_deg": 0}, "predictions": [],
              "mission": {"id": "T1", "started_at": "2026-11-16T08:00:00Z",
                          "ended_at": "2026-11-16T08:30:00Z"}}
    out = _prediction(bundle, {"wind_dir_deg": 90.0})
    assert abs(out["wind_to_deg"] - 270.0) < 0.01


@case
def weather_payload_maps_gateway_result():
    from server.api import _weather
    res = ProviderResult(
        key="weather", data={"wind_speed_kmh": 11.5, "wind_dir_deg": 145,
                             "temp_c": 31.0, "humidity_pct": 68},
        source="bmkg", source_label="BMKG",
        observed_at="2026-11-16T06:00:00Z", fetched_at="2026-11-16T06:00:05Z",
        age_s=300, ttl_s=1200, status="fresh", reason=None, error=None,
        licence="BMKG public", attribution="BMKG", simulated=False,
        configured=True, fallback_from=None)
    out = _weather({}, None, res)
    assert out["temp_c"] == 31.0 and out["wind_dir_deg"] == 145
    assert out["source"] == "bmkg" and out["simulated"] is False
    assert out["age_min"] == 5


def live_smoke() -> int:
    """One real call per adapter. Opt-in only: `--live`. Missing keys skip."""
    import tempfile
    from pathlib import Path

    from .gateway import Gateway
    from .geo import extent_from_point
    from .registry import build_registry

    cfg = load()
    registry = build_registry(cfg)
    if not registry:
        print("no adapters registered")
        return 0

    gw = Gateway(registry, cfg, root=Path(tempfile.mkdtemp()))
    extent = extent_from_point(-6.9, 107.6, 5.0)
    failures = 0
    for key in registry:
        result = gw.refresh_now("live-smoke", key, extent)
        if result.status in ("unconfigured", "unavailable"):
            print(f"skipped {key}: {result.status} ({result.reason})")
        elif result.status in ("error", "offline"):
            print(f"FAIL {key}: {result.reason}")
            failures += 1
        else:
            print(f"ok {key}: {result.status} source={result.source} age={result.age_s}s")
    return 1 if failures else 0


@case
def warm_cache_survives_a_failed_refresh_as_offline():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(data={"wind_speed_kmh": 7})
    gw = _gw(spy, root)
    gw.refresh_now("M1", "weather", _extent())
    spy.boom = ProviderError("network", "reset")
    r = gw.refresh_now("M1", "weather", _extent())
    assert r.status == "offline"
    assert r.data and r.data["wind_speed_kmh"] == 7


@case
def offline_with_no_cache_falls_back_to_fixture():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    spy = _Spy(key="regional_fires")
    spy.requires = ()
    gw = _gw(spy, root)
    r = gw.get("M1", "regional_fires", _extent(), allow_fetch=False)
    assert r.simulated is True and r.reason == "fixture_fallback"
    assert r.data and r.data["count"] == 0


@case
def offline_weather_uses_the_committed_fixture():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    gw = _gw(_Spy(), root)
    r = gw.get("M1", "weather", _extent(), allow_fetch=False)
    assert r.simulated is True and r.reason == "fixture_fallback"
    assert r.data and r.data.get("wind_speed_kmh") is not None


@case
def empty_past_ttl_with_a_failed_refresh_is_offline():
    env = _env(data={"count": 0}, observed_at="2026-11-16T05:00:00Z",
               last_error="connection reset", last_error_kind="network")
    d = derive(env, 1200, now=_now())
    assert d.status == "offline"


@case
def empty_inside_ttl_is_still_empty():
    d = derive(_env(data={"count": 0}), 1200, now=_now())
    assert d.status == "empty"


@case
def fallback_from_survives_a_warm_read():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    primary = _Spy(boom=ProviderError("missing", "adm4_unresolved"))
    secondary = _Spy(data={"wind_speed_kmh": 12})
    gw = _gw_from({"weather": (primary, secondary)}, root)
    cold = gw.get("M1", "weather", _extent())
    warm = gw.get("M1", "weather", _extent())
    assert cold.fallback_from == "spy"
    assert warm.fallback_from == "spy"


@case
def fixture_weather_reports_no_age():
    from server.api import _weather
    res = ProviderResult(
        key="weather", data={"wind_speed_kmh": 10, "wind_dir_deg": 90,
                             "temp_c": 20, "humidity_pct": 50},
        source="fixture", source_label="Sample data", observed_at=None,
        fetched_at=None, age_s=None, ttl_s=1200, status="error",
        reason="fixture_fallback", error=None, licence="n/a",
        attribution="Offline sample", simulated=True, configured=True,
        fallback_from=None)
    assert _weather({}, None, res)["age_min"] is None


@case
def payload_enqueues_refresh_for_a_stale_weather_cache():
    import tempfile
    from pathlib import Path
    import server.api as api_mod
    from server import db

    root = Path(tempfile.mkdtemp())
    mission = db.get_mission(db.init_db(), "SPIKE_BRIGHTON_ODM")
    assert mission, "demo mission missing"

    write_envelope(mission["id"], "weather", {
        "schema": 1, "key": "weather", "provider": "open-meteo",
        "source_label": "Open-Meteo", "licence": "x", "attribution": "y",
        "fetched_at": "2026-01-01T00:00:00Z", "observed_at": "2026-01-01T00:00:00Z",
        "last_attempt_at": "2026-01-01T00:00:00Z", "last_error": None,
        "last_error_kind": None, "fail_count": 0,
        "data": {"wind_speed_kmh": 1, "wind_dir_deg": 90,
                 "temp_c": 20, "humidity_pct": 50},
    }, root=root)

    tasks = _Tasks()
    original = api_mod.default_gateway
    api_mod.default_gateway = lambda: _gw_from({"weather": (_Spy(),)}, root)
    try:
        api_mod._payload(mission, tasks)
    finally:
        api_mod.default_gateway = original
    assert len(tasks.tasks) == 1


@case
def cache_accepts_dotted_asset_names():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    p = write_asset("M1", "context_dem.json", b"{}", root=root)
    assert p.name == "context_dem.json" and p.exists()
    for bad in ("../x", "a/b", "..", "."):
        try:
            write_asset("M1", bad, b"{}", root=root)
        except ValueError:
            continue
        raise AssertionError(f"accepted asset name {bad!r}")


@case
def dem_tile_name_hemispheres():
    from server.providers.copernicus_dem import tile_name
    assert tile_name(46.84, -91.99) == "Copernicus_DSM_COG_10_N46_00_W092_00_DEM"
    assert tile_name(-6.91, 107.60) == "Copernicus_DSM_COG_10_S07_00_E107_00_DEM"
    assert tile_name(0.4, 0.4) == "Copernicus_DSM_COG_10_N00_00_E000_00_DEM"
    assert tile_name(-0.4, -0.4) == "Copernicus_DSM_COG_10_S01_00_W001_00_DEM"


@case
def dem_cell_bounds_round_trip():
    from server.providers.copernicus_dem import cell_bounds, tile_name
    west, south, east, north = cell_bounds("Copernicus_DSM_COG_10_N46_00_W092_00_DEM")
    assert (west, south) == (-92.0, 46.0)
    assert (east, north) == (-91.0, 47.0)
    assert tile_name(46.5, -91.5) == "Copernicus_DSM_COG_10_N46_00_W092_00_DEM"


@case
def dem_tile_url_is_keyless():
    from server.providers.copernicus_dem import tile_name, tile_url
    name = tile_name(46.84, -91.99)
    url = tile_url(name)
    assert url.startswith("https://copernicus-dem-30m.s3.amazonaws.com/")
    assert url.endswith(f"/{name}/{name}.tif")
    assert "?" not in url and "key" not in url.lower()


class _StreamResp:
    def __init__(self, chunks, length=None, status=200):
        self._chunks = chunks
        self.status_code = status
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def iter_content(self, size):
        yield from self._chunks


@case
def dem_fetch_rejects_truncated_tile():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    try:
        fetch_tile("X", dest, getter=lambda *a, **k: _StreamResp([b"abc"], length=100))
    except ProviderError as e:
        assert e.kind == "network"
        assert not dest.exists()
        return
    raise AssertionError("accepted a short read")


@case
def dem_fetch_enforces_byte_cap():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    big = [b"x" * 1024] * 100
    try:
        fetch_tile("X", dest, max_bytes=4096, getter=lambda *a, **k: _StreamResp(big))
    except ProviderError as e:
        assert e.kind == "http"
        assert not dest.exists()
        return
    raise AssertionError("exceeded the cap without raising")


@case
def dem_fetch_writes_complete_tile():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    out = fetch_tile("X", dest, getter=lambda *a, **k: _StreamResp([b"ab", b"cd"], length=4))
    assert out.exists() and out.read_bytes() == b"abcd"


if __name__ == "__main__":
    raise SystemExit(main())
