# Free Provider Layer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the provider gateway, BMKG + Open-Meteo weather, NASA FIRMS regional detections, and per-provider source/age throughout the API and dashboard.

**Architecture:** A pure-translation adapter per source, wrapped by one `Gateway` that owns a per-mission file cache, read-time status derivation, fallback chains, and single-flight background refresh. The API calls only the gateway; the browser calls only the API. Cache is always served before the network, and a committed fixture is the last resort so the console never goes blank.

**Tech Stack:** Python 3.14, FastAPI, `requests`, stdlib `zoneinfo`/`csv`/`json`. No new dependencies. Dashboard is plain JS + CSS in `spike/web/`. Tests are a homegrown script runner (`python -m server.providers.selftest <case>`), matching the existing `server/selftest.py` pattern — pytest is not installed.

**Spec:** `Docs/specs/2026-11-16-free-provider-layer-design.md`

## Global Constraints

- No paid API, paid tier, or paid key. Free/keyless sources only.
- No secret in the browser, in git, or in any cache envelope. Keys come from `os.environ` / `.env` and are redacted from every error string and log line.
- `.env` stays gitignored; only `.env.example` is committed, with empty values.
- `server/cache/` is gitignored — never commit anything under it.
- No new runtime dependencies. `requests` and `numpy` are present; everything else is stdlib.
- Every test runs with **no network access** and no API key. Live calls exist only behind `--live` and are never part of the default run.
- Provider failure is data, not an exception: endpoints return HTTP 200 with a non-fresh `status`.
- The dashboard must keep working with no network, and the static `spike/web` shell (no API) must keep working untouched.
- Real provider data is `simulated: false`. `SIMULASI` appears only when `simulated: true`.
- Cache `status` is never persisted — it is derived on read.
- All times are UTC ISO-8601 with `Z`. All coordinates are WGS84 decimal degrees.
- `wind_dir_deg` is the direction wind comes **from** (meteorological), 0–359. Do not invert it anywhere.

## Review Focus

These are the five ways this software will most likely mislead a user, none of
which the spec's own tests pin down. Each gets a test in the task that owns the
code.

1. **Provider answers for a different place than asked.** BMKG resolves a
   forecast by `adm4`; if we echo whatever the response contains without
   checking it against the requested code, a wrong village's wind renders as
   fact. Expected: reject the payload, mark `unavailable`. → Task 10.
2. **`observed_at` missing or in the future.** A provider that omits the
   timestamp, or whose clock leads ours, makes `age_s` negative or `None`; a
   naive implementation then reports `fresh` forever. Expected: clamp negative
   to 0, and treat an unknown age as `stale`, never `fresh`. → Task 4.
3. **FIRMS CSV much larger than the 500-row output cap.** Bad fire season in a
   25 km ring can return tens of thousands of rows. Expected: bounded parse,
   cap at 500, `truncated: true`, no hang. → Task 11.
4. **`acq_time` with 3 digits or a leading zero.** NASA emits `"420"`,
   `"0420"`, and `"2359"`. `"420"` parsed as `HHMM` gives 42:00 and a wrong
   age. Expected: right-pad to 4 digits before parsing. → Task 11.
5. **Non-ASCII provider text through cache and JSON.** BMKG returns
   `"Cerah Berawan"`, `"Hujan Ringan di Wilayah …"`; place names carry
   accents. A `write_text` without `encoding="utf-8"` (or a `json.dumps`
   without `ensure_ascii=False`) mangles it silently. Expected: exact
   round-trip through the envelope and the HTTP response. → Task 3.

---

## File Structure

**Create**

| Path | Responsibility |
|---|---|
| `server/providers/__init__.py` | Package marker, exports |
| `server/providers/base.py` | `Extent`, `ProviderPayload`, `ProviderError`, `Provider` protocol, `ProviderResult`, `ProviderConfig` |
| `server/providers/geo.py` | Ring extent, haversine, bearing |
| `server/providers/config.py` | `.env` loader, `load()`, `redact()` |
| `server/providers/cache.py` | Envelope read/write (atomic), path sanitising, `derive()` status |
| `server/providers/http.py` | One shared GET with timeout, typed errors, redaction |
| `server/providers/registry.py` | `build_registry(cfg)` → key → ordered adapters |
| `server/providers/gateway.py` | `Gateway`, `default_gateway()` |
| `server/providers/adm4.py` | `Adm4Match`, `resolve()` |
| `server/providers/open_meteo.py` | Open-Meteo adapter |
| `server/providers/bmkg.py` | BMKG adapter |
| `server/providers/firms.py` | FIRMS adapter |
| `server/providers/prefetch.py` | CLI |
| `server/providers/selftest.py` | Case runner + all Phase 1 cases |
| `server/providers/data/adm4_index.json` | Committed index (ships empty) |
| `server/providers/tools/build_adm4_index.py` | Index builder |
| `server/providers/fixtures/` | Recorded captures + `fallback.json` + `README.md` |
| `.env.example` | Empty-value key template |

**Modify**

| Path | Change |
|---|---|
| `server/config.py` | Add `PROVIDERS_CACHE = CACHE / "providers"`; include in `ensure_dirs()` |
| `server/pipeline/weather.py` | `get_weather()` delegates to the gateway when given a `mission_id`; legacy behaviour otherwise |
| `server/pipeline/runner.py:82` | Pass `mission_id=` |
| `server/api.py` | `/providers*`, `/regional_fires`; `providers` summary; weather from gateway; `_prediction(bundle, weather)` |
| `spike/web/dashboard.html` | Live-data card, Fire inset container, weather reason line |
| `spike/web/dashboard.css` | Styles for both |
| `spike/web/dashboard.js` | Render both from the payload |
| `README.md`, `server/README.md`, `Docs/HANDOFF.md` | Status, endpoints, attribution |

---

### Task 1: Types, geo math, and the test runner

**Files:**
- Create: `server/providers/__init__.py`, `server/providers/base.py`, `server/providers/geo.py`, `server/providers/selftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Extent(west, south, east, north, ring_km=15.0)` with `.centre -> (lat, lon)`; `ProviderPayload(data, observed_at, extra)`; `ProviderError(kind, detail)`; `ProviderResult` (13 fields, see spec §4.2); `ProviderConfig(firms_map_key, bmkg_adm4, ring_km, offline, ttl_overrides)`; `geo.mission_extent(bbox, ring_km) -> Extent`; `geo.extent_from_point(lat, lon, radius_km=0.5) -> Extent`; `geo.haversine_km(lat1, lon1, lat2, lon2) -> float`; `geo.bearing_deg(lat1, lon1, lat2, lon2) -> float`; `selftest.case` decorator and `selftest.main(argv)`.

- [ ] **Step 1: Write the failing tests**

Create `server/providers/selftest.py` with the runner (no cases yet), then add the geo cases:

```python
"""Runnable self-check for the provider layer. No frameworks, no network."""
from __future__ import annotations

import sys
import traceback

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


if __name__ == "__main__":
    raise SystemExit(main())


@case
def geo_extent_ring_km():
    bbox = {"west": 107.600, "south": -6.920, "east": 107.610, "north": -6.919}
    e = mission_extent(bbox, 15)
    assert e.ring_km == 15.0
    lat_span = e.north - e.south
    lon_span = e.east - e.west
    assert round(lat_span, 4) == round(0.001 + 30 / 111.32, 4)
    assert lon_span > lat_span          # longitude padding widens by 1/cos(lat)
    assert e.centre[0] > -6.9201 and e.centre[0] < -6.9189


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest geo_extent_ring_km`
Expected: `NameError: name 'mission_extent' is not defined` (or `ModuleNotFoundError: No module named 'server.providers'`).

- [ ] **Step 3: Implement `base.py` and `geo.py`**

`base.py` — dataclasses exactly as spec §4.1–4.2, plus `ProviderConfig`. `Extent.centre` returns `((south + north) / 2, (west + east) / 2)`.

`geo.py`:

```python
def mission_extent(bbox: dict, ring_km: float) -> Extent
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float
def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float
```

`mission_extent` clamps `ring_km` to `[10, 25]`, pads latitude by `ring_km / 111.32` and longitude by `ring_km / (111.32 * cos(radians(centre_lat)))`, and returns the padded extent. `extent_from_point(lat, lon, radius_km=0.5)` returns the same shape for a point, used by the point-based weather path. `haversine_km` is the standard great-circle formula with R = 6371.0088. `bearing_deg` is the initial bearing normalised to `[0, 360)`.

Add these imports directly below `import traceback` (later tasks extend this block, because the modules they need do not exist yet):

```python
from datetime import datetime, timezone

from .base import Extent, ProviderConfig, ProviderError, ProviderPayload, ProviderResult
from .geo import bearing_deg, haversine_km, mission_extent
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest geo_extent_ring_km geo_extent_clamps geo_distance_and_bearing`
Expected: three `PASS` lines and `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/
git commit -m "feat(providers): add core types, geo helpers, and test runner"
```

---

### Task 2: Config loader and secret redaction

**Files:**
- Create: `server/providers/config.py`, `.env.example`
- Test: `server/providers/selftest.py` (append cases)

**Interfaces:**
- Consumes: `ProviderConfig` from `base.py`.
- Produces: `load(*, env_path: Path | None = None, environ: dict[str, str] | None = None) -> ProviderConfig`; `redact(text: str, secret: str | None) -> str`; module constant `ENV_KEYS` listing every recognised variable.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest config_env_beats_file`
Expected: `NameError: name 'load' is not defined`.

- [ ] **Step 3: Implement `config.py` and `.env.example`**

`_read_env_file(path)` parses `KEY=VALUE`, skips blank lines and `#` comments, strips one layer of matching single or double quotes. `load()` merges: real `environ` wins over file values, file wins over defaults. `ring_km` defaults to `15.0`; `offline` is true when `PYROSCAN_PROVIDER_OFFLINE` is `1`/`true`. `ttl_overrides` is built from any `PYROSCAN_TTL_<KEY>_S` environment variable, uppercased key → int.

`.env.example` contains every key from spec §9.2 with an empty or default value and no real secrets.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest config_env_beats_file config_file_and_quotes config_redacts_secret`
Expected: `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/config.py .env.example
git commit -m "feat(providers): load config from env and .env, redact secrets"
```

---

### Task 3: Cache envelope IO

**Files:**
- Create: `server/providers/cache.py`
- Modify: `server/config.py` (add `PROVIDERS_CACHE`, extend `ensure_dirs`)
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `config.CACHE`.
- Produces: `mission_dir(mission_id: str, root: Path | None = None) -> Path`; `read_envelope(mission_id: str, key: str, root: Path | None = None) -> dict | None`; `write_envelope(mission_id: str, key: str, envelope: dict, root: Path | None = None) -> Path`; `write_asset(mission_id: str, name: str, data: bytes, root: Path | None = None) -> Path`; `KEY_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")`.

- [ ] **Step 1: Write the failing tests**

```python
@case
def cache_roundtrip_and_atomic():
    import tempfile
    from pathlib import Path
    root = Path(tempfile.mkdtemp())
    write_envelope("M1", "weather", {"schema": 1, "key": "weather", "data": {"a": 1}}, root=root)
    env = read_envelope("M1", "weather", root=root)
    assert env["data"] == {"a": 1}
    leftovers = list((root / "M1").glob("*.tmp"))
    assert leftovers == []


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
    data = {"condition": "Cerah Berawan", "note": "Hujan Ringan — pantau", "name": "Kel. Sukajadi"}
    write_envelope("M1", "weather", {"schema": 1, "data": data}, root=root)
    back = read_envelope("M1", "weather", root=root)
    assert back["data"] == data
    raw = (root / "M1" / "weather.envelope.json").read_text(encoding="utf-8")
    assert "Cerah Berawan" in raw
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest cache_roundtrip_and_atomic`
Expected: `NameError: name 'write_envelope' is not defined`.

- [ ] **Step 3: Implement `cache.py`**

`mission_dir` validates the id against `KEY_SAFE` and raises `ValueError` otherwise. `write_envelope`/`write_asset` write to `<target>.tmp` in the same directory then `os.replace`. `read_envelope` returns `None` on any `OSError`/`JSONDecodeError`/non-dict payload. Use `encoding="utf-8"` and `json.dumps(..., ensure_ascii=False)` on write, `encoding="utf-8"` on read.

Add `PROVIDERS_CACHE = CACHE / "providers"` to `server/config.py` and include it in `ensure_dirs()`.

Add the cache imports to the selftest import block:

```python
from .cache import mission_dir, read_envelope, write_envelope
```

- [ ] **Step 4: Run all cache cases**

Run: `python -m server.providers.selftest cache_roundtrip_and_atomic cache_corrupt_returns_none cache_rejects_path_traversal cache_preserves_non_ascii`
Expected: `4/4 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/cache.py server/config.py
git commit -m "feat(providers): atomic per-mission envelope cache"
```

---

### Task 4: Status derivation

**Files:**
- Modify: `server/providers/cache.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: envelope dict shape from Task 3 (`fetched_at`, `observed_at`, `last_attempt_at`, `last_error`, `fail_count`, `data`).
- Produces: `Derived(status: str, reason: str | None, age_s: int | None)` dataclass; `derive(env: dict | None, ttl_s: int, *, configured: bool = True, now: datetime | None = None) -> Derived`.

Priority order is spec §7.3. `reason` describes the latest fetch outcome and is **independent** of `status`.

- [ ] **Step 1: Write the failing tests**

```python
def _env(**kw):
    base = {"observed_at": "2026-11-16T06:00:00Z", "fetched_at": "2026-11-16T06:00:05Z",
            "last_error": None, "fail_count": 0, "data": {"count": 3}}
    base.update(kw)
    return base


def _now():
    from datetime import datetime, timezone
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
    from datetime import datetime, timezone
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest status_matrix`
Expected: `NameError: name 'derive' is not defined`.

- [ ] **Step 3: Implement `derive`**

Parse timestamps with `datetime.fromisoformat` after normalising a trailing `Z` to `+00:00`; assume UTC when naive. Compute `age_s = max(0, int((now - observed).total_seconds()))`. `reason` = `"never_fetched"` when there is no envelope; `"unknown_age"` when neither timestamp parses; otherwise the envelope's `last_error` trimmed to a short code, else `None`. Apply the spec §7.3 priority exactly, with `empty` checked before `fresh` (`data.get("count") == 0` only applies when the key's payload carries `count`).

Add `derive` to the selftest import block: `from .cache import derive, mission_dir, read_envelope, write_envelope`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest status_matrix status_future_timestamp_is_not_fresh_forever status_unknown_age_is_stale status_reason_independent_of_status`
Expected: `4/4 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/cache.py
git commit -m "feat(providers): derive provider status on read"
```

---

### Task 5: HTTP helper

**Files:**
- Create: `server/providers/http.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `ProviderError` from `base.py`, `redact` from `config.py`.
- Produces: `get_text(url: str, params: dict | None = None, *, timeout: int, secret: str | None = None, fetcher=None) -> str`; `get_json(url, params=None, *, timeout, secret=None, fetcher=None) -> dict`.

`fetcher` defaults to `requests.get` and exists so tests never touch the network.

- [ ] **Step 1: Write the failing tests**

```python
class _Resp:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} for url")


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest http_network_error_is_typed`
Expected: `NameError: name 'get_text' is not defined`.

- [ ] **Step 3: Implement `http.py`**

Wrap the call in `try/except requests.RequestException` → `ProviderError("network", redact(...))`; non-2xx → `ProviderError("http", ...)`; JSON decode failure → `ProviderError("parse", ...)`. Set a `User-Agent` of `PyroScan/0.1 (+local research console)`. No retries.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest http_network_error_is_typed http_status_error_is_typed_and_redacted http_json_parse_error_is_typed`
Expected: `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/http.py
git commit -m "feat(providers): shared HTTP helper with typed errors and redaction"
```

---

### Task 6: Registry and gateway read path

**Files:**
- Create: `server/providers/registry.py`, `server/providers/gateway.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `build_registry(cfg: ProviderConfig) -> dict[str, tuple[Provider, ...]]`; `Gateway(registry, cfg, *, root=None, now_fn=None)` with `.get(mission_id, key, extent, *, allow_fetch=True, force=False, background=None) -> ProviderResult`, `.refresh_async(background, mission_id, key, extent) -> None`, `.refresh_now(mission_id, key, extent) -> ProviderResult`, `.status_all(mission_id, extent, *, allow_fetch=True) -> dict[str, ProviderResult]`; `default_gateway() -> Gateway`; `reset_default_gateway() -> None`.

`background` is FastAPI's `BackgroundTasks` (or any object with `add_task`). When it is `None`, `get` performs no enqueue — it still returns the cache or the `warming` state. The API route always passes one.

`refresh_now` is the synchronous body a background task calls. Tests use it directly — no FastAPI needed.

- [ ] **Step 1: Write the failing tests**

```python
class _Spy:
    """Minimal adapter answering one key."""
    def __init__(self, key="weather", data=None, observed="2026-11-16T06:00:00Z",
                 allow_inline=True, ttl_s=1200, boom=None):
        self.id = "spy"; self.key = key; self.source_label = "Spy"
        self.licence = "test"; self.attribution = "test"
        self.ttl_s = ttl_s; self.fetch_timeout_s = 6; self.allow_inline = allow_inline
        self.requires = ()
        self.data = data if data is not None else {"count": 1}
        self.observed = observed; self.boom = boom; self.calls = 0
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
    from server.providers.base import ProviderConfig
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest gateway_fresh_cache_skips_adapter`
Expected: `NameError: name 'Gateway' is not defined`.

- [ ] **Step 3: Implement `registry.py` and `gateway.py`**

`build_registry` imports the adapters lazily (they arrive in Tasks 8–11) and returns `{"weather": (bmkg, open_meteo), "regional_fires": (firms,)}` for whatever keys exist. Until those modules exist, return `{}` — the import must be inside the function and guarded so Task 6 runs before Task 8.

`Gateway.get` follows spec §8.1: read envelope → `derive` → `fresh`/`empty`/`stale`/`offline` return the cache (`stale`/`offline` also enqueue when `allow_fetch`), otherwise walk the chain, inline when `adapter.allow_inline` else return `unavailable`/`warming` and enqueue. `refresh_now` executes the chain, writes the envelope on success, and on failure writes an envelope preserving prior `data` with `last_error` and `fail_count + 1`.

Single-flight: an in-process `set` of `(mission_id, key)` guarded by a `threading.Lock`; `refresh_async` adds the task only if the pair is not already in flight, and `refresh_now` removes it in a `finally`.

Add `from .gateway import Gateway` to the selftest import block.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest gateway_fresh_cache_skips_adapter gateway_stale_serves_cache_and_queues_once gateway_cold_light_fetches_inline gateway_cold_heavy_returns_warming`
Expected: `4/4 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/registry.py server/providers/gateway.py
git commit -m "feat(providers): gateway with cache-first reads and single-flight refresh"
```

---

### Task 7: Chains, failure recording, and fixture fallback

**Files:**
- Modify: `server/providers/gateway.py`
- Create: `server/providers/fixtures/regional_fires/fallback.json`, `server/providers/fixtures/README.md`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `Gateway` from Task 6.
- Produces: `fallback_path(key: str) -> Path | None` in `gateway.py` (or `cache.py`); `Gateway.get` gains chain fallthrough and `fallback_from`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest chain_falls_through_when_primary_unavailable`
Expected: `AssertionError` — `fallback_from` is `None` because fallthrough is not implemented.

- [ ] **Step 3: Implement fallthrough and fixture fallback**

Walk the chain in order. Skip an adapter whose `requires` are unmet and mark that adapter `configured=False`. On `ProviderError`, write a failure envelope for that adapter and continue. On the first success, write the success envelope and return. If **every** adapter was skipped as unconfigured, return `status: "unconfigured"` with `configured: false`, `data: null`, and **no** fixture fallback — a missing key is a configuration state, not a failure, and the UI must be able to say "add MAP_KEY to enable". Only when at least one adapter was attempted and all attempts failed does the fixture fallback apply: load `fixtures/<key>/fallback.json` and return the `error`/`fixture_fallback`/`simulated: true` shape from spec §8.5 without writing an envelope.

Create `fixtures/regional_fires/fallback.json` with `{"count": 0, "bbox": null, "window_days": 1, "sensors": [], "detections": [], "nearest_km": null, "nearest_bearing_deg": null, "newest_age_s": null, "truncated": false}` and `fixtures/README.md` documenting the `live.*` vs `fallback.json` distinction and the provenance rule.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest chain_falls_through_when_primary_unavailable chain_records_failed_attempt chain_stale_primary_does_not_fall_through fixture_fallback_is_simulated_and_not_cached unconfigured_beats_fixture_fallback`
Expected: `5/5 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/gateway.py server/providers/fixtures/
git commit -m "feat(providers): chain fallthrough, failure recording, fixture fallback"
```

---

### Task 8: Open-Meteo adapter and legacy weather wrapper

**Files:**
- Create: `server/providers/open_meteo.py`, `server/providers/fixtures/open_meteo/live.json`
- Modify: `server/pipeline/weather.py`, `server/pipeline/runner.py:82`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `http.get_json`, `ProviderPayload`, `Extent`.
- Produces: `OpenMeteoProvider` (`id="open-meteo"`, `key="weather"`, `ttl_s=1200`, `fetch_timeout_s=6`, `allow_inline=True`, `requires=()`); `pipeline.weather.get_weather(lat, lon, online=False, cache_path=None, *, mission_id=None) -> dict`.

- [ ] **Step 1: Capture the fixture**

Call the live endpoint once and save the raw JSON to `server/providers/fixtures/open_meteo/live.json`:

```
https://api.open-meteo.com/v1/forecast?latitude=-6.9&longitude=107.6&current=temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m&wind_speed_unit=kmh&timezone=UTC
```

If the network is unavailable, hand-write a fixture with the same key structure and record in `fixtures/README.md` that it is synthetic. The parser is written against the fixture, not against this plan's prose.

- [ ] **Step 2: Write the failing tests**

```python
@case
def open_meteo_parses_fixture():
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / "fixtures/open_meteo/live.json")
                     .read_text(encoding="utf-8"))
    from server.providers import open_meteo
    payload = open_meteo.parse(raw)
    assert set(payload.data) >= {"wind_speed_kmh", "wind_dir_deg", "temp_c", "humidity_pct"}
    assert payload.data["adm4"] is None
    assert payload.data["forecast_hours"] is None
    assert payload.observed_at.endswith("Z")
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m server.providers.selftest open_meteo_parses_fixture`
Expected: `AttributeError: module 'server.providers.open_meteo' has no attribute 'parse'` (or `ModuleNotFoundError`).

- [ ] **Step 4: Implement the adapter and wrapper**

`open_meteo.parse(raw: dict) -> ProviderPayload` maps the `current` block to spec §5.1, sets `observed_at` from `current["time"]` (Open-Meteo returns naive UTC when `timezone=UTC`; append `Z`), and sets `adm4`/`adm4_name`/`adm4_resolved_by`/`forecast_hours`/`condition`/`precip_mm`/`cloud_pct` to `None`. `OpenMeteoProvider.fetch` calls `http.get_json` with the params above and returns `parse(...)`.

In `pipeline/weather.py`, add the keyword `mission_id`. When it is provided, call `default_gateway().get(mission_id, "weather", extent_from_point(lat, lon))` and return the legacy dict (`temperature_c` from `temp_c`); when it is omitted, keep today's cache-file + fixture behaviour unchanged. Add a tiny `providers.geo.extent_from_point(lat, lon) -> Extent` (a 1 km box) for this path.

`runner.py:82` becomes `weather = weather_mod.get_weather(center["lat"], center["lon"], online=online, mission_id=mission_id)`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m server.providers.selftest open_meteo_parses_fixture`
Expected: `PASS`.

Then run the existing pipeline check to prove nothing regressed: `python -m server.selftest`
Expected: `PASS selftest: fusion, spread, advisory, db`.

- [ ] **Step 6: Commit**

```bash
git add server/providers/open_meteo.py server/providers/fixtures/open_meteo/ server/pipeline/weather.py server/pipeline/runner.py
git commit -m "feat(providers): Open-Meteo adapter and gateway-backed weather"
```

---

### Task 9: `adm4` resolver, bundled index, and builder

**Files:**
- Create: `server/providers/adm4.py`, `server/providers/data/adm4_index.json`, `server/providers/tools/build_adm4_index.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `Extent`, `config`.
- Produces: `Adm4Match(code: str, name: str, tz: str, resolved_by: str)`; `resolve(extent: Extent, *, override: str | None = None, index_path: Path | None = None) -> Adm4Match | None`; `load_index(path) -> list[dict]`.

Index entry: `{"code": "32.73.15.2001", "name": "Kel. Sukajadi", "level": "adm4", "bbox": [w, s, e, n], "tz": "Asia/Jakarta"}`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest adm4_picks_smallest_containing_bbox`
Expected: `NameError: name 'resolve' is not defined`.

- [ ] **Step 3: Implement the resolver and commit an empty index**

`resolve` returns the manual override first if given. Otherwise load the index, keep entries whose `bbox` contains the extent centre, prefer `level == "adm4"` over `"adm3"`, and among the preferred level choose the smallest bbox area. Return `None` when the list is empty or unreadable. Never raise on a malformed index — treat it as empty and let the caller report `adm4_unresolved`.

Commit `data/adm4_index.json` as `{"schema": 1, "generated_at": null, "source": null, "entries": []}`.

`tools/build_adm4_index.py` reads a user-supplied CSV/GeoJSON path from `--source`, validates that it has code/name/bbox/tz columns, and writes the index. It must exit non-zero and leave the existing index untouched when `--source` is missing or has no rows.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest adm4_empty_index_resolves_nothing adm4_picks_smallest_containing_bbox adm4_manual_override_wins adm4_adm3_fallback_only_without_adm4`
Expected: `4/4 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/adm4.py server/providers/data/ server/providers/tools/
git commit -m "feat(providers): resolve BMKG adm4 from a bundled boundary index"
```

---

### Task 10: BMKG adapter

**Files:**
- Create: `server/providers/bmkg.py`, `server/providers/fixtures/bmkg/live.json`
- Modify: `server/providers/registry.py` (register BMKG ahead of Open-Meteo)
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `adm4.resolve`, `http.get_json`, `ProviderPayload`, `ProviderError`.
- Produces: `BmkgProvider(*, index_path: Path | None = None)` (`id="bmkg"`, `key="weather"`, `ttl_s=1200`, `allow_inline=True`, `requires=()`); `parse(raw: dict, adm4: str, tz: str, now: datetime) -> ProviderPayload`.

`index_path` defaults to `data/adm4_index.json` and exists so tests can point at a temp index without touching the committed file.

- [ ] **Step 1: Capture the fixture**

Fetch one real response and save it to `fixtures/bmkg/live.json`:

```
https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=<any valid adm4 code from BMKG's published list>
```

Use a code from BMKG's own site, not from our index — the index may be empty. Record the code and the capture date in `fixtures/README.md`. The parser is written against this file.

- [ ] **Step 2: Write the failing tests**

```python
@case
def bmkg_parses_fixture_and_picks_nearest_entry():
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / "fixtures/bmkg/live.json")
                     .read_text(encoding="utf-8"))
    from server.providers import bmkg
    adm4 = raw["lokasi"]["adm4"] if "lokasi" in raw else "32.73.15.2001"
    now = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
    p = bmkg.parse(raw, adm4, "Asia/Jakarta", now)
    assert p.data["adm4"] == adm4
    assert 0 <= p.data["wind_dir_deg"] <= 359
    assert p.observed_at.endswith("Z")
    assert p.data["forecast_hours"] >= 0


@case
def bmkg_rejects_mismatched_adm4():
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / "fixtures/bmkg/live.json")
                     .read_text(encoding="utf-8"))
    from server.providers import bmkg
    now = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
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
    from server.providers.base import ProviderConfig
    cfg = ProviderConfig(None, None, 15.0, False, {})
    prov = BmkgProvider(index_path=Path(tempfile.mkdtemp()) / "empty.json")
    try:
        prov.fetch(_extent(), cfg)
    except ProviderError as e:
        assert e.kind == "missing" and e.detail == "adm4_unresolved"
        return
    raise AssertionError("no ProviderError")
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m server.providers.selftest bmkg_parses_fixture_and_picks_nearest_entry`
Expected: `ModuleNotFoundError: No module named 'server.providers.bmkg'`.

- [ ] **Step 4: Implement the adapter**

`parse` flattens the 3-hourly `cuaca` lists, parses each `local_datetime` as naive local time in the given IANA zone via `zoneinfo.ZoneInfo`, converts to UTC, picks the entry nearest `now`, and maps `t→temp_c`, `hu→humidity_pct`, `ws→wind_speed_kmh`, `wd→wind_dir_deg`, `tp→precip_mm`, `tcc→cloud_pct`, `weather_desc→condition`. Set `forecast_hours` to the absolute hour distance. **Verify the response's own adm4 equals the requested `adm4` and raise `ProviderError("parse", "adm4_mismatch")` when it does not.** `fetch` resolves `adm4` via `adm4.resolve`; when that returns `None`, raise `ProviderError("missing", "adm4_unresolved")`.

Register BMKG before Open-Meteo in `registry.build_registry`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m server.providers.selftest bmkg_parses_fixture_and_picks_nearest_entry bmkg_rejects_mismatched_adm4 bmkg_unresolved_adm4_is_missing_not_error`
Expected: `3/3 passed`.

- [ ] **Step 6: Commit**

```bash
git add server/providers/bmkg.py server/providers/fixtures/bmkg/ server/providers/registry.py
git commit -m "feat(providers): BMKG adapter with adm4 verification"
```

---

### Task 11: FIRMS adapter

**Files:**
- Create: `server/providers/firms.py`, `server/providers/fixtures/firms/live.csv`
- Modify: `server/providers/registry.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `http.get_text`, `geo.haversine_km`, `geo.bearing_deg`, `ProviderError`.
- Produces: `FirmsProvider` (`id="firms"`, `key="regional_fires"`, `ttl_s=7200`, `fetch_timeout_s=6`, `allow_inline=True`, `requires=("firms_map_key",)`); `parse(csv_text: str, centre: tuple[float, float]) -> ProviderPayload`; `parse_acq(acq_date: str, acq_time: str) -> str`.

- [ ] **Step 1: Capture the fixture**

With a free `MAP_KEY`, fetch the current VIIRS NRT CSV for a small box and save it as `fixtures/firms/live.csv` (header row included, no comments). Record the box, date, and source in `fixtures/README.md`. Without a key, hand-author a header-valid CSV with a handful of rows and mark it synthetic in the README.

- [ ] **Step 2: Write the failing tests**

```python
_FIRMS_HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
                 "satellite,instrument,confidence,version,bright_ti5,frp,daynight")


def _firms_csv(rows):
    return "\n".join([_FIRMS_HEADER] + rows) + "\n"


def _row(lat, lon, date, time, conf="n", sensor="VIIRS"):
    return f"{lat},{lon},330.1,0.4,0.4,{date},{time},N,VIIRS,{conf},2.0NRT,290.2,4.2,D"


@case
def firms_parses_fixture():
    from pathlib import Path
    text = (Path(__file__).parent / "fixtures/firms/live.csv").read_text(encoding="utf-8")
    from server.providers import firms
    p = firms.parse(text, (-6.9, 107.6))
    assert p.data["count"] == len(p.data["detections"])
    assert p.observed_at.endswith("Z")
    assert all(0 <= d["confidence"] <= 1 for d in p.data["detections"])


@case
def firms_handles_three_digit_acq_time():
    from server.providers import firms
    text = _firms_csv([_row(-6.9, 107.6, "2026-11-16", "420")])
    p = firms.parse(text, (-6.9, 107.6))
    assert p.data["detections"][0]["acq_at"] == "2026-11-16T04:20:00Z"


@case
def firms_caps_at_500_and_flags_truncation():
    from server.providers import firms
    rows = [_row(-6.9 + i * 0.0001, 107.6, "2026-11-16", f"{i % 2400:04d}") for i in range(5000)]
    p = firms.parse(_firms_csv(rows), (-6.9, 107.6))
    assert len(p.data["detections"]) == 500
    assert p.data["truncated"] is True


@case
def firms_missing_key_is_unconfigured():
    import tempfile
    from pathlib import Path
    from server.providers.base import ProviderConfig
    cfg = ProviderConfig(None, None, 15.0, False, {})
    root = Path(tempfile.mkdtemp())
    gw = Gateway({"regional_fires": (FirmsProvider(),)}, cfg, root=root)
    r = gw.get("M1", "regional_fires", _extent())
    assert r.status == "unconfigured"
    assert r.configured is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m server.providers.selftest firms_handles_three_digit_acq_time`
Expected: `ModuleNotFoundError: No module named 'server.providers.firms'`.

- [ ] **Step 4: Implement the adapter**

`parse_acq` right-pads `acq_time` with leading zeros to 4 characters, then formats `HH:MM`. `parse` reads with `csv.DictReader` over `io.StringIO`, normalises confidence (VIIRS `l/n/h → 0.3/0.6/0.9`; numeric `0–100 → /100`), dedupes on `(round(lat, 3), round(lon, 3), acq_at, sensor)`, sorts newest first, caps at 500 setting `truncated`, computes `count` before the cap, and computes `nearest_km`/`nearest_bearing_deg` from `centre`. `observed_at` is the newest `acq_at`. Rows with unparseable coordinates are skipped rather than aborting the whole payload.

`FirmsProvider.fetch` builds `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{w},{s},{e},{n}/1` and calls `http.get_text(..., secret=key)`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m server.providers.selftest firms_parses_fixture firms_handles_three_digit_acq_time firms_caps_at_500_and_flags_truncation firms_missing_key_is_unconfigured`
Expected: `4/4 passed`.

- [ ] **Step 6: Commit**

```bash
git add server/providers/firms.py server/providers/fixtures/firms/ server/providers/registry.py
git commit -m "feat(providers): NASA FIRMS NRT adapter with confidence normalisation"
```

---

### Task 12: Prefetch CLI

**Files:**
- Create: `server/providers/prefetch.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `default_gateway()`, `build_registry`, `config.load()`, `db`.
- Produces: `main(argv) -> int` supporting `--mission <id>` (repeatable, default: latest), `--only <key>` (repeatable), `--offline` (refuse network), `--json`.

- [ ] **Step 1: Write the failing test**

```python
@case
def prefetch_runs_refresh_for_requested_keys():
    import tempfile
    from pathlib import Path
    from server.providers.base import ProviderConfig
    root = Path(tempfile.mkdtemp())
    spy = _Spy()
    cfg = ProviderConfig(None, None, 15.0, False, {})
    gw = Gateway({"weather": (spy,)}, cfg, root=root)
    events = run_prefetch(gw, "M1", _extent(), keys=["weather"])
    assert spy.calls == 1
    assert events[0]["key"] == "weather"
    assert events[0]["status"] in ("fresh", "empty", "stale")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest prefetch_runs_refresh_for_requested_keys`
Expected: `NameError: name 'run_prefetch' is not defined`.

- [ ] **Step 3: Implement `prefetch`**

`run_prefetch(gw, mission_id, extent, *, keys=None) -> list[dict]` calls `gw.refresh_now` per key and returns `[{"key", "status", "reason", "age_s"}]`. `main` resolves missions (explicit ids or the latest) and their extents from the heightmap via the existing `fusion.load_heightmap`, builds `default_gateway()`, and prints a line per key or the JSON list.

Add `from .prefetch import run_prefetch` to the selftest import block.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest prefetch_runs_refresh_for_requested_keys`
Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/prefetch.py
git commit -m "feat(providers): prefetch CLI for offline mission prep"
```

---

### Task 13: API endpoints and providers summary

**Files:**
- Modify: `server/api.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `Gateway`, `build_registry`, `config.load()`.
- Produces: `GET /api/v1/missions/{id}/providers`, `GET /api/v1/missions/{id}/providers/{key}`, `POST /api/v1/missions/{id}/providers/refresh`, `GET /api/v1/missions/{id}/regional_fires`; helper `providers_summary(results: dict[str, ProviderResult], ring_km: float, offline: bool) -> dict`.

The summary item carries `status`, `source`, `source_label`, `age_s`, `ttl_s`, `simulated`, `reason`, `configured`, `attribution`, and `licence`. `attribution`/`licence` are present because the Live-data card must footer them (spec §11.1) and the Mission tab must show full licence text — neither can be reached from `data` alone. `data` is never included.

- [ ] **Step 1: Write the failing test**

```python
@case
def providers_summary_is_compact_and_key_free():
    from server.providers.base import ProviderResult
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest providers_summary_is_compact_and_key_free`
Expected: `ImportError: cannot import name 'providers_summary' from 'server.api'`.

- [ ] **Step 3: Implement the endpoints**

`providers_summary` emits exactly the spec §10.2 item keys plus `attribution` and `licence` (`status`, `source`, `source_label`, `age_s`, `ttl_s`, `simulated`, `reason`, `configured`, `attribution`, `licence`) and never `data` or any config value. Wire the four routes; all provider failures return 200. `POST /providers/refresh` returns `202` with `{"queued": [...]}` and enqueues via `BackgroundTasks`.

- [ ] **Step 4: Run the test, then a live manual check**

Run: `python -m server.providers.selftest providers_summary_is_compact_and_key_free`
Expected: `PASS`.

Start `python -m uvicorn server.api:app --host 127.0.0.1 --port 8000`, then:
`curl.exe -s http://127.0.0.1:8000/api/v1/missions/latest/providers`
Expected: JSON containing `"items"` with a `weather` entry carrying a `status`; no `data` field, no key value.

- [ ] **Step 5: Commit**

```bash
git add server/api.py
git commit -m "feat(api): provider status endpoints and summary"
```

---

### Task 14: Mission payload weather source and prediction fix

**Files:**
- Modify: `server/api.py` (`_payload`, `_weather`, `_prediction`)
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `default_gateway()`.
- Produces: `_prediction(bundle: dict, weather: dict) -> dict`; `_weather(bundle, hm, result) -> dict`; `_payload` gains `providers`, `regional_fires`, `places`.

- [ ] **Step 1: Write the failing tests**

```python
@case
def prediction_uses_passed_weather_not_db_row():
    from server.api import _prediction
    bundle = {"weather": {"wind_dir_deg": 0}, "predictions": []}
    out = _prediction(bundle, {"wind_dir_deg": 90.0})
    assert abs(out["wind_to_deg"] - 270.0) < 0.01


@case
def weather_payload_maps_gateway_result():
    from server.providers.base import ProviderResult
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest prediction_uses_passed_weather_not_db_row`
Expected: `TypeError: _prediction() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement the payload changes**

Change `_prediction` to accept `weather` and read `wind_dir_deg` from it. Change `_weather` to build from the gateway result, keeping `temperature_c` and `age_min` for the current tab. In `_payload`, resolve `weather` once via `default_gateway().get(...)`, pass it to both `_weather` and `_prediction`, and add `providers`, `regional_fires` (inline result data or `null`), and `places` (`null` in Phase 1).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest prediction_uses_passed_weather_not_db_row weather_payload_maps_gateway_result`
Expected: `2/2 passed`.

Then confirm the payload still loads: `curl.exe -s http://127.0.0.1:8000/api/v1/missions/latest` returns JSON with `mission`, `weather`, `providers`, `regional_fires`.

- [ ] **Step 5: Commit**

```bash
git add server/api.py
git commit -m "feat(api): source weather from providers and align prediction fronts"
```

---

### Task 15: Dashboard live-data card

**Files:**
- Modify: `spike/web/dashboard.html` (after the `#recon-card` element), `spike/web/dashboard.css`, `spike/web/dashboard.js`
- Test: browser check (no unit test — this is presentation)

**Interfaces:**
- Consumes: `state.f.providers.items.<key>` and `state.f.providers.ring_km` from Task 14.
- Produces: `renderProviders()` called from `init()` after `state.f` is set.

- [ ] **Step 1: Add the markup**

Immediately after the closing `</div>` of `#recon-card` in `#tab-layers`:

```html
<div class="card" id="live-data-card">
  <div class="card-head"><h3>Live data</h3><span class="tag" id="ld-ring">—</span></div>
  <ul class="ld-list" id="ld-list"></ul>
  <p class="small ld-attrib" id="ld-attrib"></p>
</div>
```

- [ ] **Step 2: Add the styles**

Append a `.ld-list`/`.ld-row`/`.ld-dot` block to `dashboard.css` using existing tokens only (`--muted`, `--green`, `--amber`, `--red`, `--line`, `--silver`). Status dot colours: `fresh`/`empty` green (`empty` outlined), `stale` amber, `offline`/`error` red, `unconfigured`/`unavailable` muted.

- [ ] **Step 3: Render from the payload**

`renderProviders()` iterates `Object.entries(f.providers.items)` in **fixed order** `["weather", "regional_fires", "context_dem", "context_imagery", "places"]`, skipping keys the payload does not contain, and writes one row per key: dot, `source_label`, and either `age` (`${Math.round(age_s / 60)} min`) or a short reason label. Set `#ld-ring` to `${ring_km} km ring`. Set `#ld-attrib` to the joined `attribution` values of visible rows. When a row has `simulated: true`, append `· SIMULASI`.

- [ ] **Step 4: Verify in the browser**

Start the API, run `node spike/web/shot.mjs "http://127.0.0.1:8000/dashboard.html" "spike/shots/phase1-live-data.png" --headed`, and confirm: two rows visible, ages in minutes, no `undefined`, ring label present, attribution line present.

- [ ] **Step 5: Commit**

```bash
git add spike/web/dashboard.html spike/web/dashboard.css spike/web/dashboard.js
git commit -m "feat(dashboard): live data source/age card"
```

---

### Task 16: Weather tab source line and regional fires inset

**Files:**
- Modify: `spike/web/dashboard.html`, `spike/web/dashboard.css`, `spike/web/dashboard.js`
- Test: browser check

**Interfaces:**
- Consumes: `state.f.weather`, `state.f.providers.items.weather`, `state.f.regional_fires`.
- Produces: `renderFiresInset()`.

- [ ] **Step 1: Make the weather card honest**

In `#tab-weather`, give the `SIMULASI` tag an id (`id="w-flag"`) and add `<p class="small" id="w-note"></p>` after the stats list. In JS, set `#w-flag` hidden when `providers.items.weather.simulated` is false; set `#w-note` to `BMKG · forecast ${forecast_hours} h ahead` or `Open-Meteo · observed ${Math.round(age_s/60)} min ago`; set `#w-source` to `source_label`. When `reason === "adm4_unresolved"` or `fallback_from === "bmkg"`, set `#w-note` to `BMKG code unresolved for this location — using Open-Meteo`. When `status` is `stale`, add the existing amber banner style to `#w-note`.

- [ ] **Step 2: Add the inset markup**

After the `#legend` element:

```html
<div id="fires-inset" hidden>
  <div class="fi-head"><span id="fi-title">NASA FIRMS · NRT</span><span class="fi-count" id="fi-count"></span></div>
  <div class="fi-sub" id="fi-sub"></div>
  <ol class="fi-rows" id="fi-rows"></ol>
</div>
```

- [ ] **Step 3: Render it from the payload**

Show the inset only in Context state. Header is always `NASA FIRMS · NRT`. `#fi-count` = `regional_fires.count`. `#fi-sub` = `nearest ${nearest_km} km · ${compass(nearest_bearing_deg)} · ${Math.round(newest_age_s/60)} min`, or `No detections in the last ${window_days * 24} h` when `count === 0`, or `add MAP_KEY to enable` when `providers.items.regional_fires.status === "unconfigured"`. Render at most 5 rows: distance, compass bearing, confidence, age. Append `· SIMULASI` to the header only when `simulated` is true. Clicking a row flies the camera to that detection's lat/lon using the existing camera helper; it must not enter Reconstruction.

- [ ] **Step 4: Verify in the browser**

Screenshot with and without `PYROSCAN_FIRMS_MAP_KEY` set. Confirm the header never reads `SIMULASI` for real data, the empty state reads as a result not an error, and the inset is absent in Reconstruction.

- [ ] **Step 5: Commit**

```bash
git add spike/web/
git commit -m "feat(dashboard): regional fires inset and weather source line"
```

---

### Task 17: Offline proof, live smoke, and docs

**Files:**
- Modify: `server/providers/selftest.py` (`live_smoke`, `--live` wiring), `README.md`, `server/README.md`, `Docs/HANDOFF.md`
- Test: full selftest run

**Interfaces:**
- Consumes: everything.
- Produces: `live_smoke() -> int`; documentation matching shipped behaviour.

- [ ] **Step 1: Add the live smoke, wired to `--live`**

`main` calls `live_smoke()` instead of the case list when `--live` is passed. `live_smoke` calls each adapter once via `refresh_now` into a temp cache root and prints `key status age_s` per provider. A missing `MAP_KEY` or an unresolved `adm4` prints `skipped <key>: <reason>` and does not count as a failure.

- [ ] **Step 2: Run the full offline suite**

Run: `python -m server.providers.selftest`
Expected: every case `PASS`, `N/N passed`, no network access required. Then `python -m server.selftest` → `PASS selftest: fusion, spread, advisory, db`.

- [ ] **Step 3: Prove the offline matrix**

With the API running and a warm cache: stop the network adapter (disconnect Wi-Fi or set `PYROSCAN_PROVIDER_OFFLINE=1`), reload the dashboard, and confirm each provider row reads `offline` with its data still rendered. Delete `server/cache/providers/<id>/`, reload with no network, and confirm fixtures render with `SIMULASI` and no red banner. Screenshot both to `spike/shots/`.

- [ ] **Step 4: Prove zero external browser requests**

Open DevTools → Network, reload the dashboard, filter to external origins. Expected: zero requests to any host other than `127.0.0.1`.

- [ ] **Step 5: Update the docs**

`server/README.md`: add the four endpoints and the cache path. `README.md`: move the provider layer from "Next" to "Shipped (Phase 1)", state that weather is now BMKG/Open-Meteo with source and age, that fires are `NASA FIRMS · NRT`, and keep the Esri prototype-only note (Phase 3 removes it). `Docs/HANDOFF.md`: rewrite §8 to describe what shipped, list the four new endpoints, keep the `adm4` dataset risk with its current status, and record that the regional map view is still not built.

- [ ] **Step 6: Commit and push**

```bash
git add README.md server/README.md Docs/HANDOFF.md server/providers/selftest.py
git commit -m "docs: record Phase 1 provider layer and offline behaviour"
git push origin main
```

---

## Self-Review

**Spec coverage.** Every Phase 1 item in spec §13 maps to a task: framework (§3.1) → Tasks 1–7; Open-Meteo (§5.1) → Task 8; `adm4` (§15.1) → Task 9; BMKG (§5.1) → Task 10; FIRMS (§5.2) → Task 11; prefetch (§3.1) → Task 12; API (§10) → Tasks 13–14; Live-data card (§11.1) → Task 15; inset (§11.3) → Task 16; acceptance criteria (§16) → Task 17. Phase 2–5 sections are intentionally out of scope; they get their own plan.

**Deviation from the spec worth noting for the implementer:** spec §5.1 says `pipeline/weather.py:get_weather()` "becomes a thin wrapper over the gateway". The pipeline calls it without a mission id (`runner.py:82`, and any future caller), so Task 8 adds an optional `mission_id` keyword and preserves the old path when it is absent. `runner.py` passes it. This keeps the signature backward compatible and avoids inventing a pseudo-mission cache directory.

**Known sequencing constraint.** Task 6's `build_registry` must import adapters lazily, because `open_meteo`/`bmkg`/`firms` do not exist until Tasks 8–11. Task 8 is also where the legacy pipeline wrapper changes, so Tasks 6–7 stay testable in isolation with spy adapters.
