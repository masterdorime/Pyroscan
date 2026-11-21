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


def _synthetic_dem(path, value=200.0, nodata=None, size=120,
                   bounds=(-92.0, 46.0, -91.0, 47.0)):
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    data = np.full((size, size), value, dtype="float32")
    if nodata is not None:
        data[size // 2, size // 2] = nodata
    profile = {"driver": "GTiff", "height": size, "width": size, "count": 1,
               "dtype": "float32", "crs": "EPSG:4326", "tiled": True,
               "blockxsize": 64, "blockysize": 64,
               "transform": from_bounds(*bounds, size, size)}
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(data, 1)


@case
def dem_crop_returns_ring_heightmap():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path, value=250.0)
    e = mission_extent({"west": -91.50, "south": 46.50, "east": -91.495, "north": 46.505}, 5)
    out = crop_dem(path, e, size=64)
    hm = out["heightmap"]
    assert hm["width"] == 64 and hm["height"] == 64 and hm["mission_id"] == "context"
    assert len(hm["heights_m"]) == 64 * 64
    assert hm["h_min"] == hm["h_max"] == 250.0
    assert out["clipped"] is False


@case
def dem_crop_reports_clipping_at_a_cell_edge():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path)
    e = mission_extent({"west": -92.01, "south": 46.84, "east": -91.99, "north": 46.86}, 5)
    out = crop_dem(path, e, size=64)
    assert out["clipped"] is True
    assert out["bbox"]["west"] >= -92.0


@case
def dem_crop_excludes_nodata_from_the_range():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path, value=250.0, nodata=-32767.0)
    e = mission_extent({"west": -91.9, "south": 46.1, "east": -91.1, "north": 46.9}, 5)
    out = crop_dem(path, e, size=64)
    assert out["heightmap"]["h_min"] >= 0
    assert out["nodata_px"] >= 1


@case
def dem_adapter_writes_asset_and_payload():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import (CopernicusDemProvider, cell_bounds,
                                                 tile_name)

    e = mission_extent({"west": 107.595, "south": -6.505,
                        "east": 107.605, "north": -6.495}, 5)
    tile = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(tile, value=310.0, bounds=cell_bounds(tile_name(*e.centre)))

    def fake_fetch(name, dest):
        dest.write_bytes(tile.read_bytes())
        return dest

    prov = CopernicusDemProvider(tile_fetcher=fake_fetch)

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_dem": (prov,)}, root)
    result = gw.refresh_now("M1", "context_dem", e)

    assert result.status == "fresh"
    asset = mission_dir("M1", root) / "context_dem.json"
    assert asset.exists()
    env = read_envelope("M1", "context_dem", root=root)
    assert env["data"]["asset"] == "context_dem.json"
    assert env["data"]["source_resolution_m"] == 30
    assert env["data"]["width"] == 256
    assert env["data"]["clipped"] is False


@case
def payload_exposes_context_dem_only_when_cached():
    import tempfile
    from pathlib import Path
    import server.api as api_mod
    from server import db
    from server.providers.cache import write_asset

    mission = db.get_mission(db.init_db(), "SPIKE_BRIGHTON_ODM")
    assert mission
    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"weather": (_Spy(),)}, root)
    original = api_mod.default_gateway
    api_mod.default_gateway = lambda: gw
    try:
        payload = api_mod._payload(mission, None)
        assert payload["assets"].get("context_dem") in (None, "")
        write_asset(mission["id"], "context_dem.json", b'{"width":1}', root=root)
        payload = api_mod._payload(mission, None)
        assert payload["assets"]["context_dem"].endswith("/context/dem")
    finally:
        api_mod.default_gateway = original


@case
def dem_fetch_enforces_a_total_deadline():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    chunks = [b"x" * 64] * 1000
    try:
        fetch_tile("X", dest, deadline_s=0,
                   getter=lambda *a, **k: _StreamResp(chunks))
    except ProviderError as e:
        assert e.kind == "network"
        assert not dest.exists()
        return
    raise AssertionError("a trickling stream ran forever")


@case
def dem_module_requires_rasterio_at_import():
    import sys
    import server.providers as pkg

    saved_module = sys.modules.pop("server.providers.copernicus_dem", None)
    had_attr = hasattr(pkg, "copernicus_dem")
    if had_attr:
        delattr(pkg, "copernicus_dem")
    saved_rasterio = sys.modules.get("rasterio")
    sys.modules["rasterio"] = None
    try:
        try:
            import importlib
            importlib.import_module("server.providers.copernicus_dem")
        except ImportError:
            return
        raise AssertionError("module imported without rasterio")
    finally:
        if saved_rasterio is None:
            sys.modules.pop("rasterio", None)
        else:
            sys.modules["rasterio"] = saved_rasterio
        sys.modules.pop("server.providers.copernicus_dem", None)
        if saved_module is not None:
            sys.modules["server.providers.copernicus_dem"] = saved_module
            setattr(pkg, "copernicus_dem", saved_module)


@case
def firms_falls_back_when_the_first_sensor_is_empty():
    from server.providers import firms
    empty = _FIRMS_HEADER + "\n"
    real = _firms_csv([_row(-6.9, 107.6, "2026-11-16", "0420")])
    seen = []

    def fetch_text(url, **kwargs):
        seen.append(url)
        return empty if "VIIRS_SNPP_NRT" in url else real

    prov = FirmsProvider(fetch_text=fetch_text)
    payload = prov.fetch(_extent(), _cfg_with_key())
    assert payload.data["count"] == 1
    assert len(seen) == 2
    assert any("MODIS_NRT" in s for s in seen)


@case
def firms_stops_at_the_first_sensor_with_rows():
    from server.providers import firms
    real = _firms_csv([_row(-6.9, 107.6, "2026-11-16", "0420")])
    seen = []

    def fetch_text(url, **kwargs):
        seen.append(url)
        return real

    prov = FirmsProvider(fetch_text=fetch_text)
    payload = prov.fetch(_extent(), _cfg_with_key())
    assert payload.data["count"] == 1
    assert len(seen) == 1


def _cfg_with_key():
    return ProviderConfig(firms_map_key="test-key", bmkg_adm4=None,
                          ring_km=15.0, offline=False, ttl_overrides={})


@case
def dem_reads_the_remote_cog_by_default():
    import server.providers.copernicus_dem as cd
    seen = {}
    real = cd.crop_dem_mosaic

    def spy(extent, size=256, *, source_for=None):
        seen["extent"] = extent
        seen["source_for"] = source_for
        hm = {"mission_id": "context", "width": size, "height": size,
              "west": extent.west, "south": extent.south,
              "east": extent.east, "north": extent.north,
              "height_scale_m": 1.0, "geoid_offset_m": 0.0, "base_height_m": 0.0,
              "h_min": 100.0, "h_max": 200.0,
              "heights_m": [150.0] * (size * size)}
        return {"heightmap": hm, "clipped": False, "nodata_px": 0, "tiles": [],
                "coverage": 1.0,
                "bbox": {"west": extent.west, "south": extent.south,
                         "east": extent.east, "north": extent.north}}

    cd.crop_dem_mosaic = spy
    try:
        cd.CopernicusDemProvider().fetch(_extent(), _cfg())
    finally:
        cd.crop_dem_mosaic = real
    # No tile_fetcher means the remote COG path: no local source resolver.
    assert seen["source_for"] is None
    assert abs(seen["extent"].centre[1] - _extent().centre[1]) < 1e-9


@case
def s2_picks_the_least_cloudy_scene():
    import json
    from pathlib import Path
    from server.providers import sentinel2
    raw = json.loads(
        (Path(__file__).parent / "fixtures/sentinel2/search.json").read_text(encoding="utf-8"))
    scene = sentinel2.pick_scene(raw["features"])
    assert scene is not None
    assert scene["href"].endswith(".tif")
    assert scene["acquired_at"].endswith("Z")
    assert scene["cloud_pct"] <= 40.0
    clouds = [float(f["properties"]["eo:cloud_cover"]) for f in raw["features"]]
    assert scene["cloud_pct"] == min(clouds)


@case
def s2_returns_none_when_all_scenes_are_cloudy():
    from server.providers import sentinel2
    features = [{"id": "X", "properties": {"eo:cloud_cover": 91.0},
                 "assets": {"visual": {"href": "https://x/TCI.tif"}}}]
    assert sentinel2.pick_scene(features) is None


@case
def s2_adapter_writes_webp_asset_and_payload():
    import tempfile
    from pathlib import Path
    import numpy as np
    from server.providers.sentinel2 import Sentinel2Provider

    def searcher(extent, **kwargs):
        return [{"id": "S2B_TEST", "properties": {"eo:cloud_cover": 3.5,
                                                  "datetime": "2026-10-02T16:31:00Z"},
                 "assets": {"visual": {"href": "https://x/TCI.tif"}}}]

    def reader(href, extent, size=1024):
        return np.full((size, size, 3), 90, dtype="uint8")

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_imagery": (Sentinel2Provider(searcher=searcher,
                                                         reader=reader),)}, root)
    result = gw.refresh_now("M1", "context_imagery", _extent())

    assert result.status == "fresh"
    asset = mission_dir("M1", root) / "context_imagery.webp"
    assert asset.exists() and asset.read_bytes()[:4] == b"RIFF"
    env = read_envelope("M1", "context_imagery", root=root)
    assert env["data"]["resolution_m"] == 10
    assert env["data"]["scene_id"] == "S2B_TEST"
    assert env["data"]["cloud_pct"] == 3.5
    assert env["data"]["acquired_at"] == "2026-10-02T16:31:00Z"


@case
def s2_no_usable_scene_reports_unavailable():
    import tempfile
    from pathlib import Path
    from server.providers.sentinel2 import Sentinel2Provider

    def searcher(extent, **kwargs):
        return []

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_imagery": (Sentinel2Provider(searcher=searcher),)}, root)
    r = gw.refresh_now("M1", "context_imagery", _extent())
    assert r.status == "error"
    assert r.reason == "no_usable_scene"


@case
def s2_window_read_reprojects_into_the_tile_crs():
    import tempfile
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import transform

    from server.providers.sentinel2 import read_scene_window

    lat, lon = _extent().centre
    xs, ys = transform("EPSG:4326", "EPSG:32615", [lon], [lat])
    x, y = xs[0], ys[0]
    size_px = 600
    path = Path(tempfile.mkdtemp()) / "tci.tif"
    profile = {"driver": "GTiff", "height": size_px, "width": size_px, "count": 3,
               "dtype": "uint8", "crs": "EPSG:32615",
               "transform": from_origin(x - size_px * 15, y + size_px * 15, 30, 30)}
    data = np.full((3, size_px, size_px), 120, dtype="uint8")
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(data)

    out = read_scene_window(str(path), _extent(), size=32)
    assert out.shape == (32, 32, 3)
    assert out.mean() > 0


@case
def s2_skips_a_scene_that_does_not_cover_the_window():
    import tempfile
    from pathlib import Path
    import numpy as np
    from server.providers.sentinel2 import Sentinel2Provider

    def searcher(extent, **kwargs):
        return [
            {"id": "S2B_WRONG_TILE", "properties": {"eo:cloud_cover": 0.1,
                                                    "datetime": "2026-10-02T16:31:00Z"},
             "assets": {"visual": {"href": "https://x/15TWM/TCI.tif"}}},
            {"id": "S2B_RIGHT_TILE", "properties": {"eo:cloud_cover": 0.2,
                                                    "datetime": "2026-10-02T16:31:00Z"},
             "assets": {"visual": {"href": "https://x/15TWN/TCI.tif"}}},
        ]

    tried = []

    def reader(href, extent, size=1024):
        tried.append(href)
        if "/15TWM/" in href:
            raise ProviderError("parse", "ring lies outside the imagery tile")
        return np.full((size, size, 3), 80, dtype="uint8")

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_imagery": (Sentinel2Provider(searcher=searcher,
                                                         reader=reader),)}, root)
    result = gw.refresh_now("M1", "context_imagery", _extent())
    assert result.status == "fresh"
    assert len(tried) == 2
    assert result.data["scene_id"] == "S2B_RIGHT_TILE"


def _brighton_window():
    """The 4 km mosaic window the adapter actually reads at Brighton.

    Taken from spike/missions/SPIKE_BRIGHTON_ODM/heightmap.json grown by the
    15 km ring, then reduced to the imagery window. Fixed here because the
    failure it guards (a neighbouring MGRS tile winning on cloud cover) is
    positional, not random.
    """
    from server.providers.sentinel2 import imagery_extent
    return imagery_extent(mission_extent(
        {"west": -91.99491934, "south": 46.84206609,
         "east": -91.99303442, "north": 46.84329274}, 15))


def _scene(scene_id: str, cloud: float, bbox, href: str | None = None) -> dict:
    return {
        "id": scene_id,
        "bbox": bbox,
        "properties": {"eo:cloud_cover": cloud, "datetime": "2026-10-02T17:10:51Z"},
        "assets": {"visual": {"href": href or f"https://x/{scene_id}/TCI.tif"}},
    }


# Footprints as returned by Earth Search on 2026-11-18 for the Brighton window.
_NEIGHBOUR_15TWN = [-92.939197, 46.856649, -91.532736, 47.852932]
_COVERING_15TWM = [-93.000249, 45.956779, -91.557505, 46.953671]


@case
def s2_window_is_centred_on_the_mission_not_the_clipped_ring():
    window = _brighton_window()
    assert abs(window.centre[0] - 46.842679415) < 1e-6
    assert abs(window.centre[1] - (-91.99397688)) < 1e-6
    # 4 km across in both axes at this latitude
    assert abs((window.north - window.south) * 111.32 - 4.0) < 0.05


@case
def s2_ranks_a_covering_scene_above_a_less_cloudy_neighbour():
    from server.providers.sentinel2 import pick_scenes
    window = _brighton_window()
    features = [
        _scene("S2C_15TWN_20261116_0_L2A", 0.00010, _NEIGHBOUR_15TWN),
        _scene("S2B_15TWM_20261002_0_L2A", 0.00013, _COVERING_15TWM),
    ]
    order = pick_scenes(features, window=window)
    # Cloud alone would put the northern neighbour first; it does not contain
    # the window centre, so it must not be the first read.
    assert [c["scene_id"] for c in order] == [
        "S2B_15TWM_20261002_0_L2A", "S2C_15TWN_20261116_0_L2A"]


@case
def s2_keeps_unscored_scenes_in_cloud_order():
    """A feature without a bbox cannot be scored, so it keeps its cloud rank."""
    from server.providers.sentinel2 import pick_scenes
    features = [
        {"id": "A", "properties": {"eo:cloud_cover": 5.0},
         "assets": {"visual": {"href": "https://x/A/TCI.tif"}}},
        {"id": "B", "properties": {"eo:cloud_cover": 1.0},
         "assets": {"visual": {"href": "https://x/B/TCI.tif"}}},
    ]
    order = pick_scenes(features, window=_brighton_window())
    assert [c["scene_id"] for c in order] == ["B", "A"]


@case
def s2_provider_never_reads_the_neighbour_first():
    import tempfile
    from pathlib import Path
    import numpy as np
    from server.providers.sentinel2 import Sentinel2Provider
    from server.providers.base import ProviderError

    features = [
        _scene("S2C_15TWN_20261116_0_L2A", 0.00010, _NEIGHBOUR_15TWN),
        _scene("S2B_15TWM_20261002_0_L2A", 0.00013, _COVERING_15TWM),
    ]
    tried: list[str] = []

    def searcher(extent, **kwargs):
        return features

    def reader(href, extent, size=1024):
        tried.append(href)
        if "15TWN" in href:
            raise ProviderError("parse", "ring lies outside the imagery tile")
        return np.full((size, size, 3), 80, dtype="uint8")

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_imagery": (Sentinel2Provider(searcher=searcher,
                                                         reader=reader),)}, root)
    # Brighton ring, not the default Indonesian extent: the footprints above are
    # Brighton's, and the ranking is a positional test.
    brighton_ring = mission_extent(
        {"west": -91.99491934, "south": 46.84206609,
         "east": -91.99303442, "north": 46.84329274}, 15)
    result = gw.refresh_now("M1", "context_imagery", brighton_ring)
    assert result.status == "fresh"
    assert tried and "15TWM" in tried[0]
    assert result.data["scene_id"] == "S2B_15TWM_20261002_0_L2A"


@case
def s2_window_read_keeps_the_utm_axis_order():
    """The 4 km window must land on the right pixels, not a transposed crop.

    A synthetic tile in the real UTM zone 15N grid: rows run north to south and
    columns west to east. The read is painted so any axis flip or offset error
    shows up as the wrong half of the image.
    """
    import tempfile
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from server.providers.sentinel2 import read_scene_window

    size_px = 420
    res = 10.0
    # Origin chosen so the Brighton window sits inside the tile.
    west, north = 574600.0, 5190300.0
    path = Path(tempfile.mkdtemp()) / "tci.tif"
    profile = {"driver": "GTiff", "height": size_px, "width": size_px, "count": 3,
               "dtype": "uint8", "crs": "EPSG:32615",
               "transform": from_origin(west, north, res, res)}
    data = np.zeros((3, size_px, size_px), dtype="uint8")
    data[0, :, size_px // 2:] = 255   # east half bright in red
    data[1, size_px // 2:, :] = 255   # south half bright in green
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(data)

    pixels = read_scene_window(str(path), _brighton_window(), size=64)
    assert pixels.shape == (64, 64, 3)
    red, green = pixels[..., 0].astype(float), pixels[..., 1].astype(float)
    # Left of the image is west: red must be dimmer there. Row 0 is north, so
    # green (painted in the southern half) must be brighter at the bottom.
    assert red[:, :28].mean() < red[:, 36:].mean()
    assert green[:28, :].mean() < green[36:, :].mean()
    # The window is inside the tile, so nothing should be empty.
    assert pixels.mean() > 5


@case
def geo_square_extent_is_centred_and_unclamped():
    import math
    from server.providers.geo import square_extent
    e = square_extent(46.8427, -91.9940, 30)
    assert abs((e.north - e.south) * 111.32 - 60.0) < 0.05
    assert abs((e.east - e.west) * 111.32 * math.cos(math.radians(46.8427)) - 60.0) < 0.05
    assert abs(e.centre[0] - 46.8427) < 1e-9
    assert abs(e.centre[1] + 91.9940) < 1e-9


def _synthetic_tile(path, *, bounds, value, px=12):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    west, south, east, north = bounds
    profile = {"driver": "GTiff", "height": px, "width": px, "count": 1,
               "dtype": "float32", "crs": "EPSG:4326",
               "transform": from_origin(west, north,
                                        (east - west) / px, (north - south) / px)}
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(np.full((px, px), value, dtype="float32"), 1)
    return path


@case
def dem_mosaic_stitches_four_tiles_in_place():
    import tempfile
    from pathlib import Path
    from server.providers.base import Extent
    from server.providers.copernicus_dem import (cell_bounds, crop_dem_mosaic,
                                                 tile_name, tiles_for)

    root = Path(tempfile.mkdtemp())
    # A 0.6-degree box that straddles four cells around (46.8, -91.9).
    e = Extent(west=-92.2, south=46.5, east=-91.6, north=47.1, ring_km=60)
    cells = tiles_for(e)
    assert len(cells) == 4, cells
    heights = {(-93, 46): 100.0, (-92, 46): 200.0, (-93, 47): 300.0, (-92, 47): 400.0}
    paths = {}
    for name in cells:
        b = cell_bounds(name)
        west, south, east, north = b
        # key by the cell's SW corner as integers
        key = (int(round(west)), int(round(south)))
        paths[name] = _synthetic_tile(root / f"{name}.tif", bounds=b,
                                      value=heights[key])

    def source_for(name):
        return paths[name]

    out = crop_dem_mosaic(e, size=64, source_for=source_for)
    hm = out["heightmap"]
    assert out["coverage"] > 0.99
    assert out["clipped"] is False
    # NW quadrant carries the north-west tile (300), SE carries 400.
    def at(lon, lat):
        x = int((lon - hm["west"]) / (hm["east"] - hm["west"]) * 63)
        y = int((hm["north"] - lat) / (hm["north"] - hm["south"]) * 63)
        return hm["heights_m"][y * hm["width"] + x]

    assert at(-92.15, 47.05) == 300.0   # N46? no: north of 47 -> N47W093
    assert at(-91.65, 47.05) == 400.0   # N47W092
    assert at(-92.15, 46.55) == 100.0   # N46W093
    assert at(-91.65, 46.55) == 200.0   # N46W092


@case
def dem_mosaic_flags_a_missing_tile():
    import tempfile
    from pathlib import Path
    from server.providers.base import Extent
    from server.providers.copernicus_dem import (cell_bounds, crop_dem_mosaic,
                                                 tile_name)

    root = Path(tempfile.mkdtemp())
    e = Extent(west=-92.2, south=46.5, east=-91.6, north=47.1, ring_km=60)
    present = {}
    # Provide only the southern row; the northern row fails to open.
    for lon in (-93, -92):
        name = tile_name(46.0, float(lon))
        present[name] = _synthetic_tile(root / f"{name}.tif",
                                        bounds=cell_bounds(name), value=150.0)

    def source_for(name):
        if name not in present:
            raise OSError("no such tile")
        return present[name]

    out = crop_dem_mosaic(e, size=32, source_for=source_for)
    assert out["clipped"] is True
    assert out["missing_tiles"]
    assert out["coverage"] < 0.9
    assert all(isinstance(v, float) and v == v for v in out["heightmap"]["heights_m"])


@case
def dem_mosaic_reads_decimated():
    """A 12-px-wide tile must still fill a 64-px output band (out_shape used)."""
    import tempfile
    from pathlib import Path
    from server.providers.base import Extent
    from server.providers.copernicus_dem import cell_bounds, crop_dem_mosaic, tile_name

    root = Path(tempfile.mkdtemp())
    name = tile_name(46.0, -92.0)
    path = _synthetic_tile(root / "tile.tif", bounds=cell_bounds(name),
                           value=222.0, px=12)
    e = Extent(west=-92.4, south=46.2, east=-91.8, north=46.8, ring_km=60)
    out = crop_dem_mosaic(e, size=64, source_for=lambda n: path)
    hm = out["heightmap"]
    assert hm["width"] == 64 and len(hm["heights_m"]) == 64 * 64
    assert set(hm["heights_m"]) == {222.0}


@case
def dem_wide_provider_expands_and_names_its_asset():
    import tempfile
    from pathlib import Path
    from server.providers.base import Extent
    from server.providers.copernicus_dem import (CopernicusDemProvider,
                                                 cell_bounds, tile_name)

    root = Path(tempfile.mkdtemp())
    e = Extent(west=-92.02, south=46.82, east=-91.97, north=46.86, ring_km=15)
    cells = {}
    # The provider's 60 km box needs this one tile; the rest will be missing.
    for lat in (46, 47):
        for lon in (-93, -92):
            name = tile_name(float(lat), float(lon))
            cells[name] = _synthetic_tile(root / f"{name}.tif",
                                          bounds=cell_bounds(name),
                                          value=180.0 + lat, px=10)

    def fake_fetch(name, dest):
        dest.write_bytes(cells[name].read_bytes())
        return dest

    prov = CopernicusDemProvider(tile_fetcher=fake_fetch, window_km=60,
                                 size=64, key="context_dem_wide",
                                 asset="context_dem_wide.json")
    payload = prov.fetch(e, _cfg())
    assert payload.data["asset"] == "context_dem_wide.json"
    assert payload.data["window_km"] == 60
    assert payload.data["width"] == 64
    # 60 km across, centred on the mission
    span_km = (payload.data["bbox"]["north"] - payload.data["bbox"]["south"]) * 111.32
    assert abs(span_km - 60) < 0.5
    assert len(payload.data["tiles"]) == 4


def _wide_window():
    from server.providers.geo import square_extent
    return square_extent(46.842679, -91.993977, 30)


_SOUTH_BBOX = [-92.45, 46.57, -91.55, 46.86]
_NORTH_BBOX = [-92.94, 46.856, -91.53, 47.85]


@case
def s2_mosaic_prefers_a_near_date_over_a_clearer_far_one():
    from server.providers.sentinel2 import pick_scene_mosaic
    feats = [
        _scene("SOUTH", 0.0001, _SOUTH_BBOX),
        _scene("NORTH_NEAR", 0.02, _NORTH_BBOX,
               href="https://x/15/T/WN/near/TCI.tif"),
        _scene("NORTH_FAR", 0.00005, _NORTH_BBOX,
               href="https://x/15/T/WN/far/TCI.tif"),
    ]
    feats[2]["properties"]["datetime"] = "2027-03-01T17:10:51Z"
    feats[1]["properties"]["datetime"] = "2026-10-10T17:10:51Z"
    picked = pick_scene_mosaic(feats, window=_wide_window())
    ids = [s["scene_id"] for s in picked["scenes"]]
    assert ids == ["SOUTH", "NORTH_NEAR"], ids
    assert picked["multi_date"] is False
    assert picked["date_range"] == ["2026-10-02", "2026-10-10"]
    assert picked["coverage"] == 1.0


@case
def s2_mosaic_flags_a_multi_date_pair():
    from server.providers.sentinel2 import pick_scene_mosaic
    feats = [
        _scene("SOUTH", 0.0001, _SOUTH_BBOX),
        _scene("NORTH_FAR", 0.00005, _NORTH_BBOX,
               href="https://x/15/T/WN/far/TCI.tif"),
    ]
    feats[1]["properties"]["datetime"] = "2027-03-01T17:10:51Z"
    picked = pick_scene_mosaic(feats, window=_wide_window())
    assert [s["scene_id"] for s in picked["scenes"]] == ["SOUTH", "NORTH_FAR"]
    assert picked["multi_date"] is True
    assert picked["span_days"] > 14


@case
def s2_mosaic_stitches_two_utm_tiles_side_by_side():
    import tempfile
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from server.providers.sentinel2 import read_scene_mosaic

    root = Path(tempfile.mkdtemp())
    window = _wide_window()

    def tile(name, west, east, rgb):
        path = root / f"{name}.tif"
        px = 40
        profile = {"driver": "GTiff", "height": px, "width": px, "count": 3,
                   "dtype": "uint8", "crs": "EPSG:32615",
                   "transform": from_origin(west, 5225000, (east - west) / px,
                                             (75000 / px))}
        data = np.zeros((3, px, px), dtype="uint8")
        for band, value in enumerate(rgb, start=1):
            data[band - 1] = value
        with rasterio.open(path, "w", **profile) as ds:
            ds.write(data)
        return str(path)

    # Two 30 km-wide tiles, west and east, both fully covering the window's rows.
    west_src = tile("west", 540000, 576000, (220, 20, 20))
    east_src = tile("east", 576000, 612000, (20, 20, 220))
    scenes = [{"scene_id": "W", "href": west_src, "bbox": None,
               "acquired_at": "2026-10-02T00:00:00Z", "cloud_pct": 0.1},
              {"scene_id": "E", "href": east_src, "bbox": None,
               "acquired_at": "2026-10-02T00:00:00Z", "cloud_pct": 0.1}]

    pixels = read_scene_mosaic(scenes, window, size=64)
    assert pixels.shape == (64, 64, 3)
    left, right = pixels[:, :20], pixels[:, -20:]
    assert left[..., 0].mean() > left[..., 2].mean(), "west tile is red"
    assert right[..., 2].mean() > right[..., 0].mean(), "east tile is blue"


@case
def s2_wide_adapter_reports_a_mosaic_payload():
    import tempfile
    from pathlib import Path
    import numpy as np
    from server.providers.sentinel2 import Sentinel2WideProvider

    feats = [
        _scene("SOUTH", 0.0001, _SOUTH_BBOX),
        _scene("NORTH", 0.02, _NORTH_BBOX, href="https://x/15/T/WN/n/TCI.tif"),
    ]
    feats[1]["properties"]["datetime"] = "2026-10-10T17:10:51Z"

    prov = Sentinel2WideProvider(
        searcher=lambda extent, **kw: feats,
        reader=lambda scenes, extent, size=1024: np.full((size, size, 3), 70, "uint8"),
        size=128, window_km=60)
    brighton_ring = mission_extent(
        {"west": -91.99491934, "south": 46.84206609,
         "east": -91.99303442, "north": 46.84329274}, 15)
    payload = prov.fetch(brighton_ring, _cfg())

    d = payload.data
    assert d["asset"] == "context_imagery_wide.webp"
    assert d["window_km"] == 60
    assert d["scene_count"] == 2
    assert d["date_range"] == ["2026-10-02", "2026-10-10"]
    assert d["multi_date"] is False
    assert d["resolution_m"] == round(60000 / 128)
    span = (d["bbox"]["north"] - d["bbox"]["south"]) * 111.32
    assert abs(span - 60) < 0.5


@case
def provinces_route_serves_the_bundled_file():
    from fastapi.testclient import TestClient
    from server.api import app

    client = TestClient(app)
    r = client.get("/api/v1/provinces.geojson")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/geo+json")
    assert len(r.json()["features"]) == 38


@case
def globe_base_images_are_bundled_and_the_right_size():
    from pathlib import Path
    from PIL import Image

    p = Path(__file__).resolve().parents[2] / "spike" / "web" / "data" / "world_blue_marble.jpg"
    assert p.exists(), "run python tools/fetch_world_image.py"
    assert p.stat().st_size < 6_000_000
    with Image.open(p) as im:
        assert im.size == (5400, 2700)

    # The Indonesia crop is data at the zoom level (LOD), not a tile server.
    crop = p.parent / "indonesia_blue_marble.jpg"
    assert crop.exists(), "run python tools/fetch_indonesia_base.py"
    assert crop.stat().st_size < 5_000_000
    with Image.open(crop) as im:
        assert im.size == (4096, 1700)


@case
def provinces_catalogue_is_the_38_land_clipped_provinces():
    import json
    from pathlib import Path

    p = Path(__file__).parent / "data" / "provinces.geojson"
    fc = json.loads(p.read_text(encoding="utf-8"))
    feats = fc["features"]
    assert len(feats) == 38
    isos = [f["properties"]["iso"] for f in feats]
    assert len(set(isos)) == 38
    assert all(i.startswith("ID-") for i in isos)

    kt = next(f for f in feats if f["properties"]["iso"] == "ID-KT")
    assert 145_000 <= kt["properties"]["area_km2"] <= 165_000

    for name in ("Papua Selatan", "Papua Tengah", "Papua Pegunungan",
                 "Papua Barat Daya"):
        assert any(f["properties"]["name"] == name for f in feats), name

    for f in feats:
        props = f["properties"]
        west, south, east, north = props["bbox"]
        assert 93 <= west < east <= 143, props
        assert -13 <= south < north <= 9, props
        assert props["area_km2"] > 100
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for ring in poly:
                assert len(ring) >= 4
                assert ring[0] == ring[-1], (props["iso"], "ring not closed")


@case
def firms_parse_respects_the_cap():
    from .firms import parse

    text = (
        "latitude,longitude,acq_date,acq_time,satellite,frp,confidence\n"
        "0.0,114.0,2026-11-19,0300,MODIS,10,80\n"
        "0.1,114.1,2026-11-19,0600,MODIS,20,90\n"
    )
    payload = parse(text, (0.0, 114.0), cap=1)
    assert payload.data["count"] == 2
    assert len(payload.data["detections"]) == 1


@case
def provinces_pip_is_bbox_prefiltered_and_exact():
    from .provinces import load, province_at

    feats = load()
    assert province_at(feats, 114.0, 0.0)["properties"]["iso"] == "ID-KT"
    assert province_at(feats, 96.0, 4.5)["properties"]["iso"] == "ID-AC"
    assert province_at(feats, 118.0, 1.0) is None
    assert province_at(feats, 0.0, 0.0) is None


@case
def overview_fires_aggregate_once_and_cap():
    from datetime import datetime, timezone
    from .provinces import aggregate, load

    feats = load()
    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    dots = [
        {"lat": 0.0, "lon": 114.0, "frp": 10.0, "confidence": 0.8,
         "acq_at": "2026-11-19T03:00:00Z", "sensor": "MODIS"},
        {"lat": 0.2, "lon": 114.2, "frp": 30.0, "confidence": 0.9,
         "acq_at": "2026-11-19T06:00:00Z", "sensor": "MODIS"},
        {"lat": 1.0, "lon": 118.0, "frp": 99.0, "confidence": 1.0,
         "acq_at": "2026-11-19T07:00:00Z", "sensor": "VIIRS"},
    ]
    out = aggregate(feats, dots, now=now, cap=1)
    kt = out["ID-KT"]
    assert kt["count"] == 2
    assert kt["max_frp"] == 30.0
    assert kt["newest_age_s"] == 6 * 3600
    assert len(kt["dots"]) == 1
    assert kt["dots"][0]["frp"] == 30.0
    assert sum(v["count"] for v in out.values()) == 2


@case
def overview_days_are_clamped_to_the_api_maximum():
    from .provinces import clamp_days

    assert clamp_days(9) == 5
    assert clamp_days(0) == 1
    assert clamp_days(5) == 5


@case
def stac_search_can_order_by_datetime_for_tile_coverage():
    from .base import Extent
    from .sentinel2 import search_scenes

    seen: dict = {}

    class Response:
        status_code = 200

        def json(self):
            return {"features": []}

    def poster(url, json=None, timeout=None):
        seen.update(json or {})
        return Response()

    search_scenes(Extent(100, -2, 102, 0), order="datetime", poster=poster)
    assert seen["sortby"][0]["field"] == "properties.datetime"


@case
def mosaic_reads_local_tiles_with_coverage():
    import tempfile
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from .base import Extent
    from .sentinel2 import read_scene_mosaic

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "tile.tif"
        data = np.full((3, 8, 8), 120, dtype="uint8")
        data[:, :4, :4] = 0  # NoData corner the mask must not call covered
        transform = from_bounds(100, -2, 102, 0, 8, 8)
        with rasterio.open(path, "w", driver="GTiff", width=8, height=8,
                           count=3, dtype="uint8", crs="EPSG:4326",
                           transform=transform) as ds:
            ds.write(data)
        image, coverage, covered = read_scene_mosaic(
            [{"href": str(path)}], Extent(100, -2, 103, 0), size=16,
            with_stats=True, min_coverage=0)
        zero = Path(td) / "zero.tif"
        with rasterio.open(zero, "w", driver="GTiff", width=8, height=8,
                           count=3, dtype="uint8", crs="EPSG:4326",
                           transform=transform) as ds:
            ds.write(np.zeros((3, 8, 8), dtype="uint8"))
        stacked, _, _ = read_scene_mosaic(
            [{"href": str(path)}, {"href": str(zero)}],
            Extent(100, -2, 103, 0), size=16, with_stats=True, min_coverage=0)
        survived, _, _ = read_scene_mosaic(
            [{"href": str(Path(td) / "missing.tif")}, {"href": str(path)}],
            Extent(100, -2, 103, 0), size=16, with_stats=True, min_coverage=0)
    assert np.asarray(image).max() > 0
    assert np.asarray(stacked).max() > 0, "a NoData scene erased valid pixels"
    assert np.asarray(survived).max() > 0, "one bad scene killed the mosaic"
    assert image.size == (16, 16)
    assert 0.4 <= coverage <= 0.62, coverage
    assert not covered[1, 1]      # zero NoData corner
    assert covered[1, 5]          # inside the tile and non-zero


@case
def province_mask_zero_outside_and_keeps_holes():
    import numpy as np
    from .province_plate import mask_rgba

    square = {"type": "Polygon", "coordinates": [[
        [0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]]]}
    covered = np.zeros((10, 10), dtype=bool)
    covered[:, :6] = True
    alpha = mask_rgba(10, square, (0, 0, 1, 1), covered)
    assert alpha[5, 5] == 255
    assert alpha[0, 0] == 0
    assert alpha[5, 8] == 0       # polygon hole (right of 0.8)
    assert alpha[5, 7] == 0       # uncovered within the polygon


@case
def mosaic_masks_clouds_and_fills_from_the_next_scene():
    import tempfile
    from pathlib import Path
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from .base import Extent
    from .sentinel2 import read_scene_mosaic

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        transform = from_bounds(100, -2, 102, 0, 8, 8)

        def write(name, count, data):
            path = root / name
            with rasterio.open(path, "w", driver="GTiff", width=8, height=8,
                               count=count, dtype="uint8", crs="EPSG:4326",
                               transform=transform) as ds:
                ds.write(data)
            return str(path)

        tci1 = write("t1.tif", 3, np.full((3, 8, 8), 120, dtype="uint8"))
        tci2 = write("t2.tif", 3, np.full((3, 8, 8), 200, dtype="uint8"))
        clear = np.full((1, 8, 8), 4, dtype="uint8")
        cloudy = clear.copy()
        cloudy[:, :, :4] = 9  # left half cloud in the first date
        scl1 = write("s1.tif", 1, cloudy)
        scl2 = write("s2.tif", 1, clear)
        scenes = [{"href": tci1, "mask_href": scl1},
                  {"href": tci2, "mask_href": scl2}]
        image, coverage, _ = read_scene_mosaic(
            scenes, Extent(100, -2, 102, 0), size=16, fill_once=True,
            with_stats=True, min_coverage=0)
        arr = np.asarray(image).astype(int)
        left = arr[:, :8].mean()
        right = arr[:, 8:].mean()
    assert coverage > 0.99, coverage
    assert left > right + 20, (left, right)  # cloud-filled left comes from date 2


@case
def province_plate_keeps_two_dates_per_tile_for_cloud_fill():
    from .province_plate import pick_tile_scenes

    def feature(day, cloud, href):
        return {
            "assets": {"visual": {"href": href},
                       "scl": {"href": href.replace("TCI", "SCL")}},
            "properties": {"datetime": f"2026-11-{day}T00:00:00Z",
                           "eo:cloud_cover": cloud},
        }

    features = [
        feature("01", 30, "https://x/50/M/KC/01/TCI.tif"),
        feature("05", 10, "https://x/50/M/KC/05/TCI.tif"),
        feature("03", 20, "https://x/50/M/KD/03/TCI.tif"),
    ]
    picked = pick_tile_scenes(features, per_tile=2)
    assert len(picked["scenes"]) == 3
    assert all(s.get("mask_href") for s in picked["scenes"])
    kc = [s for s in picked["scenes"] if s["tile"] == "50MKC"]
    assert [s["cloud_pct"] for s in kc] == [10, 30]


@case
def province_plate_picks_one_least_cloudy_scene_per_tile():
    from .province_plate import pick_tile_scenes

    def feature(tile, cloud, day):
        zone = tile[:2]
        band = tile[2]
        square = tile[3:]
        return {"assets": {"visual": {
                    "href": f"https://x/{zone}/{band}/{square}/{day}/TCI.tif"}},
                "properties": {"datetime": f"2026-11-{day}T00:00:00Z",
                               "eo:cloud_cover": cloud}}

    features = [feature("50MKC", 40, "02"), feature("50MKC", 10, "05"),
                feature("50MKD", 20, "03")]
    picked = pick_tile_scenes(features)
    by_tile = {s["tile"]: s for s in picked["scenes"]}
    assert len(picked["scenes"]) == 2
    assert by_tile["50MKC"]["cloud_pct"] == 10
    assert by_tile["50MKD"]["cloud_pct"] == 20
    assert picked["date_range"][0].startswith("2026-11-03")


@case
def province_plate_builds_a_masked_webp():
    import io
    from pathlib import Path
    import tempfile
    import numpy as np
    from PIL import Image
    from .province_plate import build_plate

    feature = {"properties": {"iso": "ID-TEST", "name": "Test",
                              "bbox": [100, -2, 102, 0]},
               "geometry": {"type": "Polygon", "coordinates": [[
                   [100, -2], [102, -2], [102, 0], [100, 0], [100, -2]]]}}

    def reader(scenes, extent, *, size, with_stats=False, min_coverage=0, fill_once=False):
        rgb = np.full((size, size, 3), 140, dtype="uint8")
        cov = np.zeros((size, size), dtype=bool)
        cov[:, : size // 2] = True
        return rgb, 0.5, cov

    def searcher(extent):
        return [{"id": "fake-1", "bbox": [100, -2, 102, 0],
                 "properties": {"datetime": "2026-11-01T00:00:00Z",
                                "eo:cloud_cover": 10},
                 "assets": {"visual": {"href": "https://x/50/M/KC/01/TCI.tif"}}}]

    with tempfile.TemporaryDirectory() as td:
        out = build_plate("ID-TEST", size=32, feature=feature,
                          reader=reader, searcher=searcher,
                          cache_dir=Path(td), force=True)
        image = Image.open(io.BytesIO(out["image"])).convert("RGBA")
        alpha = np.asarray(image)[..., 3]
    assert out["meta"]["tier"] == "preview"
    assert 0.3 <= out["meta"]["coverage"] <= 0.6
    assert alpha[16, 4] == 255
    assert alpha[16, 28] == 0


@case
def province_detail_window_centres_on_the_given_point():
    from .province_plate import detail_extent

    extent = detail_extent((95, -11, 141, 6), centre=(118, -2))
    assert extent.west < 118 < extent.east
    assert extent.south < -2 < extent.north
    width_km = (extent.east - extent.west) * 111
    assert 115 <= width_km <= 125, width_km


@case
def province_detail_window_is_about_121_km():
    from .province_plate import detail_extent

    extent = detail_extent((95, -11, 141, 6))
    width_km = (extent.east - extent.west) * 111
    assert 115 <= width_km <= 125, width_km


@case
def every_province_has_a_land_centre():
    from .provinces import land_centre, load, province_at

    for feature in load():
        lon, lat = land_centre(feature)
        assert province_at([feature], lon, lat) is not None, \
            feature["properties"]["iso"]


@case
def country_fires_do_not_report_a_silent_zero():
    from .base import ProviderConfig, ProviderError
    from . import provinces

    def fake(url, timeout=None, secret=None):
        if "VIIRS" in url:
            return ("latitude,longitude,acq_date,acq_time,satellite,frp,"
                    "confidence\n")
        raise ProviderError("network", "MODIS down")

    original = provinces.http.get_text
    provinces.http.get_text = fake
    try:
        try:
            provinces.fetch_country(ProviderConfig(firms_map_key="k"), days=5)
            raise AssertionError("a half-failed query reported a silent zero")
        except ProviderError as exc:
            assert "MODIS" in exc.detail
    finally:
        provinces.http.get_text = original


@case
def province_plate_refuses_a_fully_empty_window():
    from pathlib import Path
    import tempfile
    import numpy as np
    from .province_plate import PlateUnavailable, build_plate

    feature = {"properties": {"iso": "ID-TEST", "name": "Test",
                              "bbox": [100, -2, 102, 0]},
               "geometry": {"type": "Polygon", "coordinates": [[
                   [100, -2], [102, -2], [102, 0], [100, 0], [100, -2]]]}}

    def reader(scenes, extent, *, size, with_stats=False, min_coverage=0, fill_once=False):
        return (np.zeros((size, size, 3), dtype="uint8"), 0.0,
                np.zeros((size, size), dtype=bool))

    def searcher(extent):
        return [{"id": "f", "bbox": [100, -2, 102, 0],
                 "properties": {"datetime": "2026-11-01T00:00:00Z",
                                "eo:cloud_cover": 10},
                 "assets": {"visual": {"href": "https://x/50/M/KC/01/TCI.tif"}}}]

    with tempfile.TemporaryDirectory() as td:
        try:
            build_plate("ID-TEST", size=16, feature=feature, reader=reader,
                        searcher=searcher, cache_dir=Path(td), force=True)
            raise AssertionError("empty plate was reported as available")
        except PlateUnavailable:
            pass


@case
def site_builds_a_dem_context_and_caches():
    import tempfile
    from pathlib import Path
    from .site import SiteUnavailable, build_site

    with tempfile.TemporaryDirectory() as td:
        calls = []

        def dem(extent, size):
            calls.append(size)
            return {"heightmap": {"width": size, "height": size,
                                  "heights_m": [42.0] * (size * size)}}

        def searcher(extent, **kw):
            return []

        out = build_site(114, 0, cache_dir=Path(td), dem_reader=dem,
                         searcher=searcher, weather_reader=lambda e: None,
                         hourly_reader=False, force=True)
        assert out["name"] == "Kalimantan Tengah"
        assert out["heightmap"]["width"] == 257
        assert out["imagery_url"] is None
        assert out["spread"]["frames"][-1]["t_min"] == 360
        assert out["spread"]["model"].startswith("rothermel")
        again = build_site(114, 0, cache_dir=Path(td), dem_reader=dem,
                           searcher=searcher, weather_reader=lambda e: None,
                           hourly_reader=False)
        assert again["id"] == out["id"]
        assert len(calls) == 1
    try:
        build_site(0, 0, cache_dir=Path(td), dem_reader=dem, searcher=searcher)
        raise AssertionError("a site outside Indonesia was accepted")
    except SiteUnavailable:
        pass


@case
def rothermel_responds_to_wind_moisture_and_slope():
    from ..pipeline.rothermel import rate_of_spread

    dry = rate_of_spread("short_grass", 0.06, 8, 0, 0)["rate_m_min"]
    wet = rate_of_spread("short_grass", 0.20, 8, 0, 0)["rate_m_min"]
    windy = rate_of_spread("short_grass", 0.06, 25, 0, 0)["rate_m_min"]
    sloped = rate_of_spread("short_grass", 0.06, 8, 0, 25)["rate_m_min"]
    assert 5 <= dry <= 60, dry
    assert dry > wet, (dry, wet)
    assert windy > dry, (windy, dry)
    assert sloped > dry, (sloped, dry)


@case
def rothermel_ellipse_has_a_head_and_back():
    from ..pipeline.rothermel import ellipse_frames, rate_of_spread

    model = rate_of_spread("tropical_forest", 0.08, 12, 270, 5,
                           aspect_deg=180)
    frames = ellipse_frames(0, 114, model, horizon_min=360, step_min=30)
    assert len(frames) == 13
    last = frames[-1]
    assert len(last["ring"]) == 24
    head = last["head"]
    # the head lies east of the ignition for a wind from the west
    assert head["lon"] > 114
    assert last["rate_m_min"] > 0


if __name__ == "__main__":
    raise SystemExit(main())
