# PyroScan — Free Provider Layer Design

**Date:** 2026-11-16
**Status:** Proposed — awaiting review. No provider code exists yet.
**Scope:** Phase 0 of the free provider layer: architecture, contracts, cache,
refresh, keys, API/UI states, phases, tests. All five phases are specified; after
review, only Phase 1 proceeds to an implementation plan.
**Related:** `Docs/HANDOFF.md` §8, `Docs/dashboard_design.md`,
`server/README.md`, `server/pipeline/weather.py`, `server/api.py`

---

## 1. Purpose

PyroScan currently runs on a closed loop: drone photos → ODM → SQLite →
FastAPI → dashboard. Everything outside the mission patch is either a fixture
(heat, wind, prediction, severity, weather, advisory) or a cached Esri basemap.
The dashboard makes zero runtime network requests, which is correct for the
field but leaves the console blind to what is actually happening around the
mission.

This spec adds a **read-only free provider layer** inside FastAPI. It fetches
regional weather/wind, active fire detections, terrain, imagery, and place
names from keyless or free-tier public sources; caches them on disk per mission;
and surfaces every value with its **source, observation time, age, and staleness**
so a mixed-age payload can never be mistaken for a single synced snapshot.

The layer is additive. It does not touch the ODM pipeline, does not change the
Context → Reconstruction flow, and does not make the dashboard depend on the
network: when providers are unreachable the console serves cache, and when there
is no cache it falls back to today's fixtures with `simulated: true`.

---

## 2. Decisions

### 2.1 Locked before this spec

| Decision | Choice |
|---|---|
| Deployment focus | Indonesia-first; Brighton remains the demo |
| Refresh model | Hybrid: fetch when online, always serve cache, show source/age/stale |
| Cost | No paid APIs, no paid keys |
| Cache footprint | Mission bbox + 10–25 km regional ring |
| BMKG `adm4` | Auto-resolve from a bundled level-4 index; manual override; Open-Meteo fallback |
| Runtime location | Provider gateway inside the existing FastAPI process |

### 2.2 Decided in this spec

| Decision | Choice | Why |
|---|---|---|
| `adm4` resolution | **Bundle a derived index** (`adm4_index.json`), built by a committed script from a user-supplied open dataset | Avoids a runtime dependency on an unversioned BMKG endpoint and unclear terms; the index is a small, reviewable artifact |
| BMKG without an index | BMKG reports `unavailable` (`adm4_unresolved`); the `weather` key is answered by Open-Meteo | Phase 1 must ship even if the boundary dataset is not cleared yet |
| Refresh trigger | **Lazy**: serve cache synchronously, enqueue one `BackgroundTask` per stale key; plus `python -m server.providers.prefetch` | No scheduler loop, no Redis/Celery, no request blocked on a provider timeout |
| FIRMS in Phase 1 | Provider + `/providers` status + Live-data card + compact inset | Ships user-visible value without coupling the framework to a new regional map view |
| Regional map view | Deferred to after Phase 1 (not scheduled here) | Keeps Phase 1 small; the inset proves the data first |
| COG reading | Decided in Phase 2 behind a measured gate (§7.5) | `rasterio` is not installed on Python 3.14; the reader choice must be evidence-based, not assumed |
| Cache status | **Never stored**; derived at read time from timestamps | A cached `status` goes wrong the moment the file ages |
| Provider keys | Env-only, loaded from `.env` by a ~15-line loader; no new dependency | Consistent with the repo's stdlib-first server |
| Fixtures | Committed under `server/providers/fixtures/`, not `server/cache/` | `server/cache/` is gitignored; replay fixtures must be versioned |
| Cold-cache behaviour | Inline fetch for light adapters (≤6 s), queued warm-up for DEM/imagery | Avoids both an empty first render and a 45 s blocking request |
| Fixture fallback | Committed `fallback.json` per key, marked `simulated: true`, never cached | Keeps the dashboard alive offline without ever passing a fixture off as real data |

---

## 3. Architecture

```
                    ┌──────────────────────────────────────────────┐
  dashboard  ──────►│ FastAPI                                      │
  (local only)      │                                              │
                    │  /api/v1/missions/{id}/providers  ──┐        │
                    │  /providers/{key}                   │        │
                    │  /context/dem, /context/imagery     ▼        │
                    │                          ┌──────────────────┐│
                    │                          │ ProviderGateway  ││
                    │                          │  resolve chain   ││
                    │                          │  cache read/write││
                    │                          │  status derive   ││
                    │                          └────────┬─────────┘│
                    └───────────────────────────────────┼──────────┘
                                                        │
                    ┌───────────────────────────────────▼──────────┐
                    │ adapters (one module per source)             │
                    │  bmkg · open_meteo · firms · copernicus_dem  │
                    │  sentinel2 · places                          │
                    └───────────────────────────────────┬──────────┘
                                                        │ HTTPS (server only)
              ┌────────────┬────────────┬───────────────┼────────────┬──────────────┐
              ▼            ▼            ▼               ▼            ▼              ▼
            BMKG      Open-Meteo    NASA FIRMS     Copernicus DEM  Earth Search   Photon /
          (adm4)                                  (AWS Open Data)  (Sentinel-2)   Overpass

                    ┌──────────────────────────────────────────────┐
                    │ server/cache/providers/<mission_id>/         │
                    │  envelope.json + binary assets per key       │
                    └──────────────────────────────────────────────┘
```

### 3.1 Layers

1. **Adapters** (`server/providers/<name>.py`) — pure translation. Take an
   `Extent` and a provider-specific config, return a `ProviderPayload` or raise
   `ProviderError`. No cache access, no FastAPI, no UI knowledge. Each adapter
   is independently unit-testable against a recorded fixture.
2. **Gateway** (`server/providers/gateway.py`) — the only thing the API calls.
   Owns cache read/write, TTL evaluation, status derivation, fallback chains,
   single-flight locking, and background refresh dispatch.
3. **Registry / chains** (`server/providers/registry.py`) — declares which
   adapters answer which payload key, in priority order, with their TTLs.
4. **API** (`server/api.py`) — thin. Resolves mission → `Extent`, calls the
   gateway, returns envelopes. Adds a `providers` summary to the mission payload.
5. **Prefetch CLI** (`server/providers/prefetch.py`) — fills a whole mission's
   keys for offline use before deployment.

### 3.2 Why not the alternatives

- **Browser → provider directly.** Rejected. FIRMS requires a `MAP_KEY` that
  must not ship to the browser; several sources omit or restrict CORS; each
  provider's terms differ; there is no shared cache, so every client refetches;
  and offline behaviour collapses. The gateway also lets us normalise six
  different schemas into one contract.
- **A separate data-pipeline service.** Not a second runtime. Heavy payloads
  (DEM, Sentinel-2, OSM labels) are fetched by the same adapters, invoked either
  lazily or from the prefetch CLI. If they later outgrow the API process, the
  CLI becomes the seam — no client change.

---

## 4. Provider interface

### 4.1 Types

```python
# server/providers/base.py

@dataclass(frozen=True)
class Extent:
    west: float; south: float; east: float; north: float
    ring_km: float = 15.0            # 10–25, clamped

    @property
    def centre(self) -> tuple[float, float]: ...

@dataclass
class ProviderPayload:
    data: dict                        # adapter-shaped, see §5
    observed_at: str | None           # provider-reported observation/validity, UTC ISO
    extra: dict = field(default_factory=dict)   # adapter diagnostics, never shown raw

class ProviderError(Exception):
    kind: str                         # "network" | "http" | "parse" | "config" | "missing"
    detail: str

class Provider(Protocol):
    id: str                           # "bmkg", "firms", ...
    key: str                          # payload key it answers: "weather", "regional_fires", ...
    source_label: str                 # "BMKG", "NASA FIRMS"
    licence: str
    attribution: str
    ttl_s: int
    fetch_timeout_s: int              # 6 for light adapters, 45 for DEM/imagery
    allow_inline: bool                # may a cold GET fetch synchronously?
    requires: tuple[str, ...]         # config keys that must be present, e.g. ("firms_map_key",)

    def fetch(self, extent: Extent, cfg: ProviderConfig) -> ProviderPayload: ...
```

Adapters never see the mission id, the database, or the cache. They receive an
`Extent` and resolved config. Everything else is the gateway's job.

### 4.2 Result envelope (the shared contract)

Every key the gateway returns has this shape, and only this shape:

```python
@dataclass
class ProviderResult:
    key: str                 # "weather" | "regional_fires" | "context_dem" | ...
    data: dict | None
    source: str              # adapter id actually used, e.g. "open-meteo"
    source_label: str        # "Open-Meteo"
    observed_at: str | None  # UTC ISO, provider-reported
    fetched_at: str | None   # UTC ISO, when bytes were last successfully stored
    age_s: int | None        # now - observed_at, computed at read time
    ttl_s: int
    status: str              # see §7.3
    reason: str | None       # latest fetch-outcome code (independent of status)
    error: str | None        # human string, only when status in {error, offline}
    licence: str
    attribution: str
    simulated: bool          # True only for fixture fallback
    configured: bool         # adapter's requires[] satisfied
    fallback_from: str | None  # adapter id that failed, when a chain fell through
```

`simulated` exists so the dashboard can keep its existing `SIMULASI` marking
rule and never mislabel real data. A real provider result is **always**
`simulated: false`, even when served `stale` from cache.

### 4.3 Dispatch

```python
Gateway.get(mission_id: str, key: str, extent: Extent, *,
            allow_fetch: bool = True, force: bool = False) -> ProviderResult
Gateway.refresh_async(background, mission_id: str, key: str, extent: Extent) -> None
Gateway.status_all(mission_id: str, extent: Extent) -> list[ProviderResult]
```

`get` never blocks longer than the adapter's inline budget. It reads cache and
derives status; if the result is stale **and** `allow_fetch` is true, it
schedules exactly one background refresh for that key (single-flight,
per-process) and returns the cache immediately.

On a **cold cache** the behaviour depends on the adapter's cost class:

- `allow_inline = True` (weather, regional_fires, places — 6 s timeout): fetch
  synchronously and return `fresh`/`empty`. This is the first-load path; one
  bounded request per key beats rendering an empty card.
- `allow_inline = False` (context_dem, context_imagery — 45 s timeout): enqueue a
  background refresh and immediately return `status: "unavailable"`,
  `reason: "warming"`, `data: null`. The UI renders "fetching terrain…" and the
  next request picks up the cache. A 45 s blocking GET is never acceptable.

`force=True` (from `POST .../providers/refresh`) skips the TTL check and always
enqueues, rather than blocking, so the endpoint returns 202 with the queued keys.

---

## 5. Data contracts

All coordinates WGS84 decimal degrees, all times UTC ISO-8601 with `Z`.
All payloads are JSON-serialisable and stable-additive: fields may be added,
never removed or renamed without a `schema` bump.

### 5.1 `weather` — BMKG → Open-Meteo

```json
{
  "wind_speed_kmh": 12.4,
  "wind_dir_deg": 145,
  "temp_c": 31.2,
  "humidity_pct": 68,
  "precip_mm": 0.0,
  "cloud_pct": 40,
  "condition": "Berawan",
  "adm4": "32.73.15.2001",
  "adm4_name": "Kel. Sukajadi",
  "adm4_resolved_by": "index",
  "forecast_hours": 3
}
```

- `wind_dir_deg` is the meteorological direction the wind comes **from**,
  0–359. This matches the existing `pipeline/weather.py` and `_prediction()`
  contract, which adds 180° to get the spread bearing. The spec does not change
  that convention.
- `adm4*` fields are `null` for the Open-Meteo adapter.
- `forecast_hours` = hours between the chosen BMKG forecast entry and now, so
  the UI can say "BMKG forecast, 2 h old" rather than implying a measurement.
  `null` for Open-Meteo, whose `current` block is an observation/near-term value.
- BMKG field names above are the intended mapping; they are confirmed against a
  captured fixture before the parser is written (§14.1), and the fixture wins if
  the live response differs.
- Backward compatibility: `pipeline/weather.py:get_weather()` becomes a thin
  wrapper over the gateway and keeps returning the legacy keys
  (`wind_speed_kmh`, `wind_dir_deg`, `humidity_pct`, `temperature_c`, `source`,
  `observed_at`, `simulated`, `age_min`). No caller changes in Phase 1.

### 5.2 `regional_fires` — NASA FIRMS NRT

```json
{
  "count": 37,
  "bbox": {"west": 106.1, "south": -7.4, "east": 108.2, "north": -5.6},
  "window_days": 1,
  "sensors": ["VIIRS_SNPP_NRT"],
  "detections": [
    {"lat": -6.91, "lon": 107.61, "confidence": 0.9, "confidence_raw": "h",
     "frp": 4.21, "brightness_k": 331.4, "sensor": "VIIRS",
     "acq_at": "2026-11-16T05:42:00Z", "daynight": "D"}
  ],
  "nearest_km": 3.4,
  "nearest_bearing_deg": 118,
  "newest_age_s": 2100,
  "truncated": false
}
```

- `confidence` normalised 0–1: VIIRS `l/n/h` → `0.3/0.6/0.9`; MODIS 0–100 → /100.
  `confidence_raw` keeps the provider value so we never lose information.
- `detections` sorted newest first, capped at 500; `truncated` says so.
  Deduplicated on `(round(lat,3), round(lon,3), acq_at, sensor)`.
- `nearest_km` / `nearest_bearing_deg` are measured from the mission centre to
  the nearest detection; bearing is compass degrees.
- `count` is the total returned before any UI cap, so "37 detections" stays true
  even when the inset lists five.
- `window_days` is fixed at `1` in Phase 1. FIRMS supports up to 10; widening it
  is a one-line config change once the inset needs history.

### 5.3 `context_dem` — Copernicus DEM 30 m

```json
{
  "bbox": {"west": 106.1, "south": -7.4, "east": 108.2, "north": -5.6},
  "width": 256, "height": 256,
  "h_min": 12.4, "h_max": 1840.6,
  "asset": "context_dem.json",
  "source_resolution_m": 30
}
```

- `asset` names a sibling file next to the envelope: a heightmap in the
  **exact shape of `spike/missions/<id>/heightmap.json`**, which is
  `mission_id`, `width`, `height`, `west`, `south`, `east`, `north`,
  `height_scale_m` (1.0), `geoid_offset_m` (0.0), `base_height_m` (0.0),
  `h_min`, `h_max`, and `heights_m` as a flat row-major list of
  `width × height` floats. Reusing that format means the dashboard's mesh
  builder works unchanged.
- `mission_id` in the context asset is the literal string `context` so it is
  never mistaken for a reconstructed mission.
- Heights are orthometric metres from Copernicus DEM; `geoid_offset_m` stays
  0.0 because the source is already EGM2008-referenced. The UI must not imply
  that context elevations are comparable to the drone DSM to centimetres.
- The returned grid covers the ring extent, so `width × height` is a downsample
  of the source tiles, not a crop of one tile.
- The mission patch keeps its own high-resolution heightmap. The context DEM is
  labelled 30 m in the UI and never merged into the patch.

### 5.4 `context_imagery` — Sentinel-2 L2A

```json
{
  "bbox": {"west": 106.1, "south": -7.4, "east": 108.2, "north": -5.6},
  "asset": "context_imagery.webp",
  "scene_id": "S2B_48MYT_20261112_0_L2A",
  "acquired_at": "2026-11-12T03:12:41Z",
  "cloud_pct": 11.3,
  "resolution_m": 10,
  "bands": ["B04", "B03", "B02"]
}
```

- `acquired_at` is the scene acquisition time and is what the UI shows as the
  imagery age. This is frequently days old; that is correct and must be visible.
- `cloud_pct` is the scene-level value from STAC, not a per-pixel mask.

### 5.5 `places`

```json
{
  "place_card": {
    "lat": -6.9175, "lon": 107.6191,
    "name": "Sukajadi", "admin": "Kota Bandung, Jawa Barat",
    "country": "Indonesia", "osm_type": "district", "osm_id": 12345
  },
  "ring_labels": [
    {"name": "Lembang", "kind": "town", "lat": -6.81, "lon": 107.61, "population": 183000}
  ],
  "label_count": 14
}
```

- `place_card` is a reverse geocode of the mission centre. `ring_labels` are
  named OSM places inside the ring, capped at 40, largest population first.
- Place names are **context, not survey truth**. The card is never presented as
  a measured coordinate; see §11.4.

---

## 6. Extent and the regional ring

```python
def mission_extent(heightmap: dict, ring_km: float) -> Extent:
    ring_km = min(25.0, max(10.0, ring_km))
    ...
```

- Base bbox is the mission heightmap extent.
- `ring_km` defaults to 15, clamped to 10–25, configured by
  `PYROSCAN_REGIONAL_RING_KM`.
- Longitude padding is divided by `cos(lat)` so the ring is kilometre-correct at
  any latitude; latitude padding is direct (`km / 111.32`).
- The extent is computed once per request from the heightmap already loaded by
  `_payload()`, so no extra I/O.
- FIRMS and places use the full ring. Weather uses the **mission centre point**
  (BMKG forecast is per `adm4`; Open-Meteo is per point). DEM and imagery use the
  full ring, rounded outward to the provider's native tile grid.

---

## 7. Cache, TTL, and status

### 7.1 Layout

```
server/cache/providers/<mission_id>/
  weather.envelope.json
  regional_fires.envelope.json
  context_dem.envelope.json
  context_dem.json              # heightmap payload (§5.3)
  context_imagery.envelope.json
  context_imagery.webp
  places.envelope.json
```

`server/cache/` is already gitignored, so nothing here can be committed by
accident. `mission_id` is sanitised to `[A-Za-z0-9_-]` before use as a path
segment; anything else is rejected with `ValueError` (no path traversal).

### 7.2 Envelope on disk

```json
{
  "schema": 1,
  "key": "weather",
  "provider": "bmkg",
  "source_label": "BMKG",
  "licence": "BMKG public data — attribution required",
  "attribution": "Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)",
  "fetched_at": "2026-11-16T06:12:03Z",
  "observed_at": "2026-11-16T05:00:00Z",
  "last_attempt_at": "2026-11-16T06:12:03Z",
  "last_error": null,
  "fail_count": 0,
  "data": { }
}
```

Writes are atomic: serialise to `*.tmp` in the same directory, `os.replace()`
onto the target. A crashed write leaves either the old envelope or the new one,
never a truncated file.

`age_s`, `status`, and `reason` are **not stored**. They are derived on read
(§7.3), so an on-disk file can never claim to be fresher than it is.

### 7.3 Status derivation

Read `age = now - observed_at` (falling back to `fetched_at` when a provider
reports no observation time). Priority order, first match wins:

| Status | Condition |
|---|---|
| `unconfigured` | adapter `requires` are missing (e.g. no FIRMS `MAP_KEY`); no cache is written |
| `unavailable` | a prerequisite is missing at runtime **and** there is no usable cache (`adm4_unresolved`, `no_usable_scene`, `warming`) |
| `empty` | fetch succeeded inside TTL and returned zero features (`count == 0`) |
| `fresh` | cache exists, non-empty, and `age ≤ ttl_s` |
| `stale` | cache exists and `age > ttl_s`, with no recorded failure since last success |
| `offline` | cache exists and the latest attempt failed with `network`/`http` |
| `error` | no cache, and the latest attempt failed |

`empty` is checked before `fresh` because a successful zero-detection fetch is
both recent and empty; "no active fires in the ring" is the useful answer and
must not render as a failure.

An existing cache is never hidden by `unavailable`. If imagery is cached but the
latest search found no usable scene, the status stays `stale` (that is what the
user is actually looking at) while `reason` carries `no_usable_scene` so the UI
can explain why it has not refreshed. **`reason` describes the latest fetch
outcome and is independent of `status`**; `status` describes the cache the client
received.

### 7.4 TTLs

| Key | TTL | Reasoning |
|---|---|---|
| `weather` | 1200 s (20 min) | Inside the 15–30 min locked range; BMKG issues 3-hourly forecasts, Open-Meteo updates ~15 min |
| `regional_fires` | 7200 s (2 h) | VIIRS NRT latency is ~3 h; refetching faster adds load without new data |
| `context_dem` | 2 592 000 s (30 d) | Static product |
| `context_imagery` | 259 200 s (3 d) | Inside the 1–5 d locked range; revisit is ~5 d at the equator |
| `places` | 2 592 000 s (30 d) | OSM changes slowly; reverse geocode is stable |

TTLs live on the adapter class, not in the gateway, and are overridable per
deployment via `PYROSCAN_TTL_<KEY>_S` for testing, where `<KEY>` is the payload
key uppercased — e.g. `PYROSCAN_TTL_WEATHER_S`,
`PYROSCAN_TTL_CONTEXT_DEM_S`.

### 7.5 COG reader gate (Phase 2 first task) — **ANSWERED 2026-11-16**

Measured on the Brighton cell
(`Copernicus_DSM_COG_10_N46_00_W092_00_DEM`, 34.1 MB, 3600², 30 m, EPSG:4326,
1024² deflate tiles, overviews `[2,4,8]`, S3 with `Accept-Ranges: bytes`):

| Probe | Result |
|---|---|
| `rasterio` wheel for CPython 3.14 / win_amd64 | **exists** (`rasterio-1.5.2-cp314-cp314-win_amd64.whl`); installed and imported |
| 25 km window read (814×429 px) | 4.4 s, **33.3 MB transferred** across 3 GETs, one 32.5 MB |
| Single-pixel read | **35 MB transferred** |
| Plain full download of the same object | 34.1 MB in 7.7 s |
| S3 `Range: bytes=0-1023` | `206` with `Content-Range`, no `Content-Encoding` |

**Decision:** use **rasterio**. Do **not** claim windowed reads for Copernicus
DEM — every read currently transfers the whole tile, including a one-pixel read.
The cause is unresolved and is *not* a missing range capability: S3 honours
ranges and the tile is tiled. Treat the tile as an all-or-nothing object and
budget accordingly.

**Budget, restated from the measurement:** ~34 MB per Copernicus tile. A ring
inside one 1° cell needs one tile (34 MB, inside the 60 MB DEM budget). A ring
crossing a cell boundary needs two (~68 MB), so the ring crop must stay inside
one cell wherever possible and record `source_tiles` when it cannot.

The tile is downloaded once, cropped to a 256² ring heightmap, written to the
cache, and discarded. No remote raster is kept.

**Sentinel-2 re-check (Phase 3).** The same probe must be repeated against a
`visual` COG before assuming 10 m windowed reads; the Sentinel-2 tiles are much
larger (~700 MB), so a full-tile transfer would not fit any budget. If that
probe also shows whole-object transfer, Phase 3 falls back to a STAC-resolved
scene thumbnail and states its real resolution in the payload.

Still true and unchanged: downloading a full Sentinel-2 tile is unacceptable, so
Phase 3 does not begin until its own measurement says otherwise.

---

## 8. Refresh, fallback, failure

### 8.1 Read path

```
get(key)
  ├─ envelope on disk, non-empty?
  │     ├─ fresh    → return, no network
  │     ├─ stale    → return this cache + enqueue refresh
  │     └─ offline  → return this cache + enqueue refresh (no fallthrough)
  │
  └─ no usable cache (missing, unreadable, or zero-length)
        ├─ chain over adapters in priority order
        │     ├─ first success → write envelope, return fresh/empty
        │     └─ all failed    → fixture exists? → error + simulated (§8.5)
        │                        else           → error / unconfigured / unavailable
        └─ no adapter available → error with reason
```

On a cold cache the chain is walked either inline (light adapters) or in the
background (heavy adapters), per §4.3. A heavy key returns `unavailable` /
`warming` on the first request and `fresh` on the next one.

A usable cache is always preferred over a chain fallthrough, including when it
is `stale` or `offline`. That is the point of the hybrid model: BMKG's
40-minute-old cached wind is more relevant to an Indonesian mission than a fresh
global model, and the UI states its age instead of silently swapping sources.
Fallthrough only happens when there is nothing usable to serve.

`allow_fetch=False` (`?allow_fetch=0`, or `PYROSCAN_PROVIDER_OFFLINE=1`) never
touches the network and never enqueues. It returns whatever cache exists as
`stale`/`offline`, or `error`.

### 8.2 Chains

| Key | Chain |
|---|---|
| `weather` | BMKG → Open-Meteo |
| everything else | single adapter |

Chain semantics: if BMKG is `unconfigured`/`unavailable` (no `adm4`), the
gateway moves to Open-Meteo **before** attempting a request and sets
`fallback_from: "bmkg"` with `reason: "adm4_unresolved"`. If BMKG is attempted
and fails on network/HTTP/parse, the same fallthrough happens and the BMKG
failure is recorded in its own envelope so its `offline` state is not lost.

A cached BMKG result that is `stale` or `offline` does **not** trigger
fallthrough — the cache is served and a refresh is queued. Stale BMKG beats
fresh Open-Meteo for Indonesian wind, and the UI says so.

### 8.3 Background refresh

```python
@app.get("/api/v1/missions/{mission_id}/providers")
def providers(mission_id: str, background: BackgroundTasks, allow_fetch: bool = True):
    ...
    for stale_key in stale:
        gateway.refresh_async(background, mission_id, stale_key, extent)
```

- Single-flight per `(mission_id, key)` via an in-process `threading.Lock` and a
  small `_inflight` set. Two concurrent requests produce one fetch.
- Adapter timeout: 6 s connect+read for weather/FIRMS/places, 45 s for DEM and
  imagery (they are large).
- Retries: none in Phase 1. A failed attempt is recorded (`fail_count`,
  `last_error`) and the next request retries naturally. No exponential backoff
  state to corrupt.
- The gateway never raises to the API for provider problems. Adapter failures
  are data, not exceptions, at the boundary.

### 8.4 Missing key is not an error

`FIRMS` without `MAP_KEY` returns `status: unconfigured`,
`reason: "firms_map_key_missing"`, `data: null`, and the UI shows a one-line
"Add MAP_KEY to enable NASA FIRMS" in the Live-data card. It must not log a
traceback, retry, or show a red banner. Same for CDSE credentials if ever used.

### 8.5 Fixture fallback (the offline guarantee)

When a key has **no usable cache and every adapter in its chain fails**, the
gateway returns a committed fixture if one exists:

```
status: "error"
reason: "fixture_fallback"
simulated: true
source: "fixture"
data: { ...fixture payload... }
```

- Fixtures live at `server/providers/fixtures/<key>/fallback.json` and are
  committed. They are distinct from the `<adapter>/live.json` response captures
  in §14.1: captures prove parsing, `fallback.json` keeps the dashboard alive.
- If no fixture exists, the result is plain `error` with `data: null` and the UI
  renders the empty state. Fixtures are a safety net for keys that already had
  one, not a promise that every key has demo data.
- `weather` has a fallback in Phase 1 because the current
  `pipeline/weather.py` already depends on the weather block of
  `spike/web/data/fixtures.json`. To avoid a second copy that can drift, the
  weather fallback **reads that file directly** rather than adding
  `fixtures/weather/fallback.json`; the selftest asserts the mapping still
  matches the block's keys. `regional_fires` ships
  `fixtures/regional_fires/fallback.json` with `count: 0` so the inset has a
  defined shape.
- **UI precedence:** `simulated: true` wins over `status: error` for styling.
  A fixture renders as a muted `SIMULASI` row, never as a red failure banner —
  degraded-but-labelled is not the same as broken. The legend and the Live-data
  card both show the badge.
- A fixture never writes an envelope. It is a response value, not a cache
  entry; otherwise the next request would mistake it for real provider data.

This is what keeps the locked requirement true: the dashboard fallback works
offline, and the static `spike/web` shell (no API at all) is untouched by any of
it.

---

## 9. Configuration and keys

### 9.1 Loader

`server/providers/config.py` reads `os.environ`, after a stdlib loader reads
`ROOT/.env` (already gitignored) line by line: `KEY=VALUE`, `#` comments,
optional surrounding quotes. No `python-dotenv` dependency. Real environment
variables always win over `.env`.

### 9.2 Variables

| Variable | Required for | Default |
|---|---|---|
| `PYROSCAN_FIRMS_MAP_KEY` | `regional_fires` | none → `unconfigured` |
| `PYROSCAN_BMKG_ADM4` | manual BMKG override | none → auto-resolve |
| `PYROSCAN_REGIONAL_RING_KM` | all | `15` (clamped 10–25) |
| `PYROSCAN_PROVIDER_OFFLINE` | all | `0` |
| `PYROSCAN_TTL_<KEY>_S` | tests | adapter default |
| `PYROSCAN_EARTHDATA_TOKEN` | not used in Phase 1–5 | none |
| `PYROSCAN_CDSE_CLIENT_ID` / `_SECRET` | not used in Phase 1–5 | none |

Earthdata/CDSE are listed only because the provider table mentions free
accounts; no phase in this spec uses them. AWS Open Data and Earth Search are
keyless. They are documented so nobody adds an account "just in case".

### 9.3 Secret rules

- Keys are read only inside `server/providers/config.py` and passed to adapters
  as values. No adapter reads `os.environ` directly.
- The API never returns a key. `/providers` reports `configured: true|false`.
- No key appears in cache envelopes, logs, error strings, or the dashboard. A
  URL containing a key (FIRMS embeds it in the path) is redacted before any
  error is recorded or logged: `_redact(url)` replaces the key segment with
  `***`.
- `.env.example` is committed with empty values; `.env` stays gitignored.

---

## 10. API

All endpoints are additive. Nothing in the current surface changes shape.

### 10.1 New endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/missions/{id}/providers` | `{mission_id, ring_km, offline, items: {key: ProviderResult}}` |
| GET | `/api/v1/missions/{id}/providers/{key}` | one `ProviderResult`; 404 for unknown key |
| POST | `/api/v1/missions/{id}/providers/refresh` | `202 {queued: [keys]}`; body `{"keys": ["weather"]}`, omitted `keys` = all registered keys |
| GET | `/api/v1/missions/{id}/regional_fires` | `regional_fires` result (Phase 1 convenience) |
| GET | `/api/v1/missions/{id}/context/dem` | 30 m context heightmap JSON (Phase 2) |
| GET | `/api/v1/missions/{id}/context/imagery.webp` | context mosaic (Phase 3) |

Query params on all GETs: `allow_fetch=0|1` (default 1), `refresh=0|1`
(default 0; `1` forces an enqueue and returns current cache immediately).

### 10.2 Mission payload additions

`_payload()` gains one key, `providers`, and the existing `weather` keeps its
shape:

```json
{
  "providers": {
    "ring_km": 15,
    "offline": false,
    "items": {
      "weather":        {"status": "fresh", "source": "bmkg", "source_label": "BMKG",
                         "age_s": 480, "ttl_s": 1200, "simulated": false,
                         "reason": null, "configured": true},
      "regional_fires": {"status": "fresh", "source": "firms", "source_label": "NASA FIRMS",
                         "age_s": 2100, "ttl_s": 7200, "simulated": false,
                         "reason": null, "configured": true}
    }
  },
  "regional_fires": { "...": "full §5.2 payload, or null" },
  "places": { "...": "full §5.5 payload, or null" }
}
```

The summary is deliberately compact: the dashboard needs status chips on every
page, and shipping full DEM/fire payloads in the mission payload would bloat the
initial load. Full payloads come from the dedicated endpoints; `regional_fires`
and `places` are small enough to inline because the Context view needs them
immediately.

The existing `weather` object is built from the gateway result so there is one
source of truth, and it keeps `source`, `age_min`, and `simulated` for the
current Weather tab.

**One integration change is required in `api.py`.** `_prediction()` currently
reads wind from the DB bundle (`bundle["weather"]`). Once weather comes from the
gateway, that would let the prediction fronts and the Weather tab disagree.
`_prediction(bundle, weather)` takes the resolved weather as a parameter and the
DB row is no longer consulted for wind in the payload path. The DB weather row
stays as the historical record of what the pipeline used at mission time; it is
not the dashboard's live value.

### 10.3 Errors

- Unknown mission → 404 (existing behaviour).
- Unknown provider key → 404.
- Provider failure → **200** with a non-fresh `status`. A provider being down is
  not an API error; the payload says so.
- Only infrastructure faults (unreadable DB, bad mission id) are 5xx.

---

## 11. UI

### 11.1 Live data card (Layers tab, Context)

A new card below the photogrammetry card. Rows appear **only for keys that are
registered in the current phase** — Phase 1 renders two rows (weather, fires);
DEM, imagery, and places join as their phases land, so the card never advertises
a provider the server cannot answer.

```
LIVE DATA                              15 km ring
● BMKG            fresh · 8 min    forecast
● NASA FIRMS      fresh · 35 min   37 detections
```

- One row per provider: status dot, source label, age or reason, and a short
  fact. Row order is fixed so it does not jump between refreshes.
- Status dot colours reuse existing tokens: `fresh` → green, `stale` →
  amber, `offline`/`error` → red, `unconfigured`/`unavailable` → muted,
  `empty` → green outline (a valid zero).
- The card footers a single attribution line for every provider currently
  shown, and the full licence text in the Mission tab.

### 11.2 Weather tab

Keep the four values. Add:

- a source line: `BMKG · forecast 2 h ahead` or `Open-Meteo · observed 6 min ago`;
- `stale` → amber banner `Wind data 41 min old` (existing `Stale` state, now
  driven by the gateway TTL instead of a hardcoded 30 min);
- `offline` → existing offline pill;
- `reason: "adm4_unresolved"` → `BMKG code unresolved for this location — using
  Open-Meteo`. This is keyed on `reason`/`fallback_from: "bmkg"`, **not** on
  `status`, because a successful fallthrough returns Open-Meteo's `fresh` status
  and would otherwise silently hide the downgrade.

### 11.3 Regional fires inset (Phase 1)

A compact panel anchored bottom-left of the **Context** view only:

```
NASA FIRMS · NRT                 37
nearest 3.4 km · ESE · 35 min
[5 rows: distance, bearing, confidence, age]
```

- Header shows `NASA FIRMS · NRT` — never `SIMULASI`. The `SIMULASI` badge
  stays on heat/wind/prediction/severity fixtures and is now proven by
  `simulated: true` on those layers rather than by page-level assumption.
- Empty payload → `No detections in the last 24 h` with the same header, not an
  error state. The window text is derived from `window_days × 24`, not
  hardcoded.
- `unconfigured` → `NASA FIRMS · add MAP_KEY to enable`, muted.
- Clicking a row centres the camera on that detection at Context altitude; it
  does not enter Reconstruction (there is no reconstruction there).
- Collapsible; collapsed by default at widths under 900 px.

### 11.4 Place card (Phase 4)

Replaces the static coordinate readout with `Sukajadi · Kota Bandung, Jawa
Barat` plus the coordinates. Must include the qualifier `± drone GPS` and must
not show more than 5 decimal places (~1 m), because the underlying accuracy is
metres-to-tens-of-metres, not centimetres. No "survey-grade" wording.

### 11.5 States

Existing `Boot / No mission / Processing / Failed / Done / Stale / Offline`
remain. Provider layer adds no new page-level state; it adds **per-provider**
state inside the Live-data card and inset. A single failed provider never blocks
the dashboard.

---

## 12. Storage

| Key | Typical | Worst case |
|---|---|---|
| `weather` | 3 KB | 40 KB (72 h forecast) |
| `regional_fires` | 20 KB | 120 KB (500 detections) |
| `context_dem` | 0.7 MB (256² JSON) | 1.2 MB |
| `context_imagery` | 3 MB | 10 MB |
| `places` | 8 KB | 30 KB |
| envelopes | 2 KB each | — |
| **total per mission ring** | **~30 MB** | **~100 MB** |

This matches the 30–100 MB budget in `Docs/HANDOFF.md`. Cache is disposable:
deleting `server/cache/providers/<id>/` is always safe and is documented as the
reset procedure. No cleanup job in Phase 1; a `prefetch --prune` flag lands in
Phase 5 if disk pressure appears.

---

## 13. Phases

Each phase is independently shippable and leaves the dashboard working offline.

### Phase 1 — Framework, weather, FIRMS, source/age

1. `providers/base.py`, `config.py`, `cache.py`, `gateway.py`, `registry.py`.
2. Capture one live response per Phase 1 adapter into `fixtures/` (§14.1) and
   confirm field names before writing any parser.
3. `open_meteo.py`; `pipeline/weather.py` re-implemented as a gateway wrapper;
   `_prediction()` takes the resolved weather instead of reading the DB row
   (§10.2).
4. `bmkg.py`, `adm4.py`, `tools/build_adm4_index.py`, bundled
   `data/adm4_index.json`.
5. `firms.py`.
6. API: `/providers`, `/providers/{key}`, `/providers/refresh`,
   `/regional_fires`; `providers` + `regional_fires` in the payload.
7. UI: Live-data card, Weather tab source line, regional fires inset.
8. `providers/prefetch.py`, `providers/selftest.py`, `fixtures/`.

**Exit:** with `MAP_KEY` set, the dashboard shows a real BMKG or Open-Meteo
reading with an age under 20 min and a FIRMS count with a nearest distance;
with the key absent it shows `unconfigured` and still renders; with the network
cut and a warm cache it serves `offline`; from a cold cache with no network it
falls back to fixtures with `simulated: true`. Zero requests from the browser to
any provider domain.

### Phase 1a — `adm4` index content

Depends on clearing the boundary dataset (§15.1). `adm4_index.json` may ship
empty: the resolver then reports `adm4_unresolved`, BMKG is
`unavailable`, and Open-Meteo carries the Weather tab. Filling the index is a
data task, not a code change: run the build script, review the diff, commit the
index. **No Phase 1 code depends on the dataset being available.**

### Phase 2 — Copernicus DEM

`cog.py` (§7.5 gate), `copernicus_dem.py`, `GET /context/dem`, Context terrain
from a 30 m ring DEM, Live-data row, storage check. The Esri basemap becomes a
tint/underlay only; the context surface is now real terrain.

### Phase 3 — Sentinel-2 imagery

`sentinel2.py` via Earth Search STAC, least-cloudy scene within 90 days, windowed
`visual` read, `GET /context/imagery.webp`. Replaces the Esri context mosaic.
Esri attribution is removed from `README.md`, `Docs/dashboard_design.md`, and
`config.CONTEXT` in the same commit.

### Phase 4 — OSM / Photon

`places.py`: Photon reverse geocode for the mission centre, Overpass names
within the ring, both cached 30 days and rate-limited client-side. Place card +
optional ring labels. Production note: self-host Photon/Overpass; the public
instances are demo-only.

### Phase 5 — Hardening

Stale/offline matrix in the UI, fixture coverage for every adapter, failure
injection tests, attribution review per provider, storage reporting,
`prefetch --prune`, and a `Docs/HANDOFF.md` section rewrite.

---

## 14. Tests

The repo uses a script pattern (`python -m server.selftest`), not pytest. Follow
it: `python -m server.providers.selftest`. pytest is optional and, if used,
imports the same functions.

### 14.1 Fixture replay (no network)

`server/providers/fixtures/<adapter>/<case>.json` holds a recorded response.
Each adapter test parses a fixture and asserts the normalised payload:

- BMKG: 3-hourly entries, local-time→UTC conversion for WIB/WITA/WIT, nearest
  entry to now, `wind_dir_deg` unchanged from source.
- Open-Meteo: `current` mapping, `observed_at` from `current.time`.
- FIRMS: CSV with VIIRS `l/n/h` and MODIS `0–100`, `acq_time` `HHMM`→UTC,
  dedupe, sort, cap, `nearest_km`/`bearing` against a known centre.

Adapters added in Phase 2+ extend this list in their own phase: DEM asset naming
and bbox rounding to the tile grid (Phase 2), Sentinel-2 scene selection and
`acquired_at` (Phase 3), reverse-geocode mapping and ring-label cap/sort
(Phase 4). Phase 1 tests do not stub adapters that do not exist.

**Fixture capture is part of each phase's first task.** Before a parser is
written, one real response per adapter is captured once and committed as the
`<adapter>/live.json` fixture. The fixture, not this document's prose, is the
authoritative field list; if a field name here disagrees with the capture, the
capture wins and this spec is corrected in the same commit. No parser is written
against an unverified schema.

### 14.2 Gateway behaviour (no network)

- `fresh` cache → zero adapter calls (inject a spy adapter).
- `stale` cache → returns cached data **and** enqueues exactly one refresh.
- Two concurrent `get`s on a stale key → one fetch.
- Chain: BMKG `unavailable` (no `adm4`) → Open-Meteo used, `fallback_from: bmkg`.
- Chain: BMKG network failure → Open-Meteo used, BMKG envelope records
  `fail_count=1`.
- Chain: BMKG `stale` → **no** fallthrough, `stale` returned.
- Missing `MAP_KEY` → `unconfigured`, no exception, no retry.
- `allow_fetch=False` → no adapter call, cache returned as `stale`.
- Corrupt envelope (truncated JSON) → treated as missing, refetched, old file
  replaced.
- Cold cache, all adapters fail, fixture present → `status: error`,
  `simulated: true`, `reason: fixture_fallback`, and **no envelope written**.
- Cold cache, all adapters fail, no fixture → `status: error`, `data: null`.
- Fixture fallback result is not cached: a second `get` retries the adapter
  rather than serving the fixture from disk.
- Heavy key (DEM) on a cold cache → `unavailable`/`warming`, one queued refresh,
  and the next `get` after the refresh returns `fresh`.
- `mission_id` containing `../` → rejected.
- Key redaction: a FIRMS URL error strings the key.

### 14.3 Failure injection

Adapters are exercised with a stub transport returning: connection reset,
HTTP 429, HTTP 500, 200 with HTML, 200 with empty CSV, and a 12 MB response.
Each must produce a typed `ProviderError` or a valid `empty` payload, never an
unhandled exception, and never a partially written cache file.

### 14.4 Live smoke (opt-in)

`python -m server.providers.selftest --live` hits the real endpoints once per
adapter and prints the resolved status and age. Skipped unless `--live` is
passed, so CI and offline runs stay deterministic. Requires a network and, for
FIRMS, `MAP_KEY`; the test reports `skipped` rather than `failed` when the key
is absent.

### 14.5 Acceptance checks that are not automated

Dashboard states are verified in a browser at 1600×900 and 1180×900 with
screenshots saved to `Docs/references/`: fresh, stale, offline, unconfigured,
empty, and the inset collapsed.

---

## 15. Risks

### 15.1 BMKG `adm4` index (highest)

BMKG keys forecasts by `adm4` (village-level) but publishes no clean
machine-readable code→boundary index. The plan bundles a derived index, which
needs a **verified open source** with a licence that permits redistribution of a
derived index.

Mitigations, in order: (a) ship an empty index and lean on Open-Meteo — Phase 1
is unaffected; (b) allow `PYROSCAN_BMKG_ADM4` per deployment; (c) accept
district-level (`adm3`, kecamatan) resolution if only that is licensed, and
record the coarser granularity in the payload's `adm4_resolved_by`. The index
build script must fail loudly and leave the existing index untouched if the
source is missing or unlicensed — never emit a partial index.

`adm4_resolved_by` values: `manual` | `index` | `adm3_fallback`. The UI shows
the resolved name so a coarser match is visible, not silent.

### 15.2 Sentinel-2 clouds and revisit

Equatorial cloud cover frequently leaves the newest usable scene days or weeks
old. `cloud_pct` and `acquired_at` are surfaced as-is; a 12-day-old scene with
11 % cloud is a correct answer, not a bug. If no scene under 40 % cloud exists
in 90 days, the previous cached imagery is still served as `stale` with
`reason: "no_usable_scene"` — never a blank imagery slot and never a silently
re-dated scene.

### 15.3 COG reading without rasterio

Covered by the Phase 2 gate (§7.5). The failure mode is real: a naive
implementation downloads hundreds of megabytes per mission. The byte budget is
an acceptance criterion, not a nice-to-have.

### 15.4 Public API politeness

Photon, Overpass, and OSM tile servers have published usage policies and will
rate-limit or block aggressive clients. Mitigations: cache TTLs in days,
client-side minimum interval per host, a descriptive `User-Agent` with a contact
string, no retries in Phase 1, and self-hosting documented before any public
deployment. Phase 4 is demo-grade on public instances by design.

### 15.5 Esri remains until Phase 3

The Esri context mosaic is prototype-only. The spec removes it in Phase 3, not
earlier, because Phase 2 (DEM) ships before imagery and the Context view would
otherwise regress to no imagery at all. `README.md` continues to state the
prototype-only status until that commit.

### 15.6 Mixed-age payload

The dashboard will show a 6-minute-old wind reading beside 12-day-old imagery.
Source/age/stale is therefore mandatory on every provider surface, not
optional polish. A provider row without an age is a bug.

### 15.7 No GPU, no new bottleneck

Providers are network- and disk-bound. ODM remains the hardware bottleneck. The
only added CPU cost is DEM resampling and imagery reprojection during refresh,
which runs in a background task and must stay under the 45 s adapter timeout;
`selftest --live` reports the duration.

---

## 16. Acceptance criteria

Phase 1 is done when all of these hold.

1. `GET /api/v1/missions/{id}/providers` returns one entry per **registered** key
   with `status`, `source_label`, `age_s`, `ttl_s`, `simulated`, `configured`.
2. The Weather tab shows real BMKG data when `adm4` resolves, Open-Meteo
   otherwise, with a source line and an age in minutes; the amber stale banner
   is driven by the gateway TTL.
3. The Context view shows the regional-fires inset with `NASA FIRMS · NRT`, a
   count, nearest distance/bearing, and detection rows. `SIMULASI` appears on
   that surface **only** when `simulated: true` (fixture fallback); a real FIRMS
   result is never labelled simulated.
4. With `PYROSCAN_FIRMS_MAP_KEY` unset the inset reads "add MAP_KEY to enable"
   and the rest of the dashboard is unaffected.
5. With the network unreachable and a warm cache, each key that has a cache
   reports `offline` with data still rendered; with a cold cache, committed
   fixtures render with `simulated: true`. The static `spike/web` dashboard is
   unchanged in both cases.
6. No browser request targets a provider domain: the network panel shows only
   `127.0.0.1`. (Verified with the DevTools network log filtered to external
   origins: zero.)
7. `python -m server.providers.selftest` passes offline with fixtures;
   `--live` passes or reports `skipped` for missing keys.
8. Refreshing twice within one TTL performs one upstream fetch (asserted by
   `fail_count`/request spy in the selftest, and by server logs during a manual
   check).
9. Cache files are written atomically; killing the process mid-refresh leaves a
   readable cache or none, never a truncated envelope.
10. No key appears in any API response, log line, cache file, or committed file;
    `git grep` for the key value returns nothing.
11. Per-mission ring storage for a full Phase 5 mission is ≤ 100 MB.
12. `Docs/HANDOFF.md`, `server/README.md`, and `README.md` are updated in the
    same commit that lands the phase, including attribution and the provider
    table's real status.

---

## 17. Out of scope

- Any paid API, paid tier, or paid key.
- Browser-side provider calls.
- A regional map view (deferred past Phase 1; the inset is the Phase 1 surface).
- Fire spread modelling changes; providers feed the existing model, they do not
  replace it.
- YOLO detections, SSE mission progress, React/Vite port, auth, PWA.
- Historical/archival retrieval beyond the cache; no time-series database.
- Multi-user or multi-tenant provider quotas.
- Cursor coordinate readout beyond the Phase 4 place card.
