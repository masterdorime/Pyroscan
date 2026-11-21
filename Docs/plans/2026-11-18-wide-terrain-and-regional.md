# Wide Terrain and Regional View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Terrain show the full 4 km imagery it already caches, and make Regional a real 60 km landscape with mosaicked Sentinel-2 imagery and Copernicus DEM.

**Architecture:** Slice A re-registers the existing local surfaces (no new downloads). Slice B adds two wide provider instances (multi-tile DEM mosaic, two-tile imagery mosaic), a second ring mesh, and new mode presets. Every new surface has a cached-asset fallback to the previous look.

**Tech Stack:** Python 3.14 (rasterio, FastAPI, numpy, Pillow), static JS + Cesium 1.147, node for pure-maths tests.

**Spec:** `Docs/specs/2026-11-18-wide-terrain-and-regional.md`

## Global Constraints

- No paid APIs or keys; Sentinel-2 and Copernicus remain keyless.
- Offline behaviour and fixture fallback must keep working.
- Never claim 10 m where the layer is ~60 m; the badge and legend carry resolution and age.
- Drone mode must render exactly as it does today.
- Provider reads request `out_shape`, so GDAL serves overviews.
- New tests run offline with synthetic rasters.
- Python tests: `python -m server.providers.selftest`. JS: `node spike/web/test-terrain-math.mjs`.

## Review Focus

- A 60 km box whose imagery tiles cannot be paired within 14 days must show a date range, not a single date.
- A missing wide asset must leave the previous surface visible, not blank.
- A box crossing a DEM tile boundary must not leave a seam or a hole.
- Terrain must never show 10 m imagery past its 4 km box.
- The 143 m mission at 60 km is ~2 px; the site marker must still be findable.

---

## Slice A — free local detail

### Task A1: Draw the full 4 km imagery

**Files:**
- Modify: `spike/web/terrain-math.js` (add `textureRect`)
- Modify: `spike/web/dashboard.js:388-520` (landscape), `:720-810` (context terrain), `:840-905` (ring hole)
- Test: `spike/web/test-terrain-math.mjs`

**Interfaces:**
- Produces: `TerrainMath.textureRect(box, imageBox) -> [u0, v0, u1, v1]` (clamped 0..1; `[0,1,0,0]` when either box is missing)
- Produces: `detailBox() -> {west,south,east,north}` in `dashboard.js` — the imagery bbox when cached, else `state.f.context`

- [ ] **Step 1: Write the failing test** — in `test-terrain-math.mjs`, assert `textureRect(same, same)` is `[0,0,1,1]`, a 1.35 km box inside a 4 km image returns the central sub-rect with `u1-u0 ≈ 0.337`, and a box larger than the image clamps to `[0,0,1,1]`.
- [ ] **Step 2: Run it and see it fail** — `node spike/web/test-terrain-math.mjs` → `textureRect is not a function`.
- [ ] **Step 3: Implement `textureRect`** — derive `u`/`v` from the box's fractions of `imageBox`, clamp each to 0..1, return `[u0, v0, u1, v1]` where `v` grows southwards.
- [ ] **Step 4: Use it in `dashboard.js`** — add `detailBox()`; build the imagery quad and the context terrain mesh over `detailBox()` with `textureRect(detailBox(), state.contextImageryBbox)`; raise the context mesh to 128² (31 m cells at 4 km); make the ring's hole use `detailBox()` so the ring cannot poke through the larger mesh.
- [ ] **Step 5: Run tests** — node test passes; `python -m server.providers.selftest` still 82/82.
- [ ] **Step 6: Browser check** — Terrain deep link: the photo now reaches 2 km from centre instead of 0.7 km; the patch and legend unchanged.

### Task A2: Terrain preset, badge, scale bar

**Files:**
- Modify: `spike/web/terrain-math.js` (add `scaleBar`)
- Modify: `spike/web/dashboard.js` (`MODES.terrain`, `modeBadge`, `applyCamera`, viewport resize)
- Modify: `spike/web/dashboard.html`, `spike/web/dashboard.css` (`#scalebar`)
- Test: `spike/web/test-terrain-math.mjs`

**Interfaces:**
- Produces: `TerrainMath.scaleBar(metresPerPixel, maxPx) -> {metres, px, label}` using 1/2/5 × 10ⁿ steps.
- Consumes: `state.contextImageryMeta.window_km`, `resolution_m` for the badge.

- [ ] **Step 1: Write the failing test** — `scaleBar(12, 140)` returns a round metre value ≤ 140 px with a label like `2 km`; `scaleBar(0.4, 140)` stays in metres.
- [ ] **Step 2: Run and see it fail.**
- [ ] **Step 3: Implement `scaleBar`** — pick the largest 1/2/5 step whose pixel width fits `maxPx`; format km above 1000 m.
- [ ] **Step 4: Preset + clamp + badge** — `terrain: { camera: { heading: 45, pitch: -30, range: 2000 }, limits: { min: 400, max: 8000 } }`; badge `${dem}m DEM · ${window_km} km image · ${age}`, falling back to `mosaic` when the imagery meta is absent.
- [ ] **Step 5: Scale bar element** — bottom-left above the fires inset, visible only in Regional; update in `applyCamera()` and on resize from `camera.frustum.fovy` and `canvas.clientHeight`.
- [ ] **Step 6: Verify** — node test passes; Terrain and Regional screenshots show the new framing; Drone unchanged.

---

## Slice B — 60 km Regional

### Task B1: `square_extent`

**Files:** Modify `server/providers/geo.py`; Test `server/providers/selftest.py`.

**Interfaces:** Produces `square_extent(lat, lon, half_km) -> Extent` (centred, `ring_km = 2*half_km`, no 10–25 km clamp).

- [ ] **Step 1: Test** — `square_extent(46.8427, -91.9940, 30)` spans 30 km north and south within 0.05 km and is centred on the point.
- [ ] **Step 2: Run** — fails with `AttributeError`.
- [ ] **Step 3: Implement** using `KM_PER_DEG_LAT` and `cos(lat)`.
- [ ] **Step 4: Run** — passes.

### Task B2: DEM mosaic provider

**Files:** Modify `server/providers/copernicus_dem.py`; Test `server/providers/selftest.py`.

**Interfaces:**
- Produces `tiles_for(extent) -> list[str]` (every 1° cell the box touches).
- Produces `crop_dem_mosaic(extent, size, *, source_for=None) -> dict` with the same keys as `crop_dem` plus `tiles` and `coverage`.
- Produces `CopernicusDemProvider(window_km=None, size=256, key="context_dem", asset=ASSET_NAME)`; when `window_km` is set the provider expands the given extent to `square_extent(centre, window_km/2)`.

- [ ] **Step 1: Test** — four synthetic 1° tiles (10×10 px each, distinct constant heights) produce a 64² heightmap whose quadrants carry those heights; a missing tile sets `clipped=True` and still returns a finite grid.
- [ ] **Step 2: Run** — fails with `ImportError`.
- [ ] **Step 3: Implement** — enumerate cells; for each, open, intersect the box with the raster bounds, compute the destination rect by proportion, `read(1, window=..., out_shape=(dh, dw))`, place; fill holes with the median.
- [ ] **Step 4: Test decimation** — assert the output shape equals `size` even when the window is larger than the source pixels, proving `out_shape` is used.
- [ ] **Step 5: Run** — passes; existing local DEM tests unchanged.

### Task B3: Wide Sentinel-2 mosaic

**Files:** Modify `server/providers/sentinel2.py`; Test `server/providers/selftest.py`.

**Interfaces:**
- Produces `pick_scene_mosaic(features, *, window, max_cloud=MAX_CLOUD, tolerance_days=14) -> dict` → `{scenes: [...], date_range: [iso, iso], multi_date: bool}`, choosing a greedy cover of a 5×5 probe grid over `window`.
- Produces `read_scene_mosaic(scenes, window, *, size) -> np.ndarray` and `Sentinel2WideProvider`.

- [ ] **Step 1: Test pairing** — two features on adjacent footprints, the low-cloud one 60 days away and a cloudier one 3 days away; the chosen mosaic uses the near-date scene and `multi_date` is false. With no near-date candidate, it uses the far one and sets `multi_date=true`.
- [ ] **Step 2: Test stitching** — two synthetic UTM tiles side by side, each a constant colour; the mosaic's left half matches tile A and the right half tile B.
- [ ] **Step 3: Implement** — greedy cover over probe points; for reads, transform the window to the scene CRS, clip per raster, map to a destination rect by raster bounds, `out_shape`, place; uncovered pixels stay black and are counted.
- [ ] **Step 4: Adapter test** — `window_km=60`, `size=1024`, asset `context_imagery_wide.webp`, payload carries `scenes`, `date_range`, `resolution_m=59`.
- [ ] **Step 5: Run** — 82/82 plus the new cases.

### Task B4: Registry, API, prefetch

**Files:** Modify `server/providers/registry.py`, `server/providers/prefetch.py`, `server/api.py`; Test `server/providers/selftest.py`.

**Interfaces:**
- New keys `context_dem_wide` and `context_imagery_wide`; routes `/context/dem_wide` and `/context/imagery_wide.webp`; payload `imagery_wide`.
- `_provider_detail` gains `context_dem_wide` (`"4 tiles"`/`"clipped"`) and `context_imagery_wide` (`"2 tiles · 2–10 Oct"`).

- [ ] **Step 1: Test** — payload exposes `imagery_wide` only when its asset exists; providers list both wide rows; `_provider_detail` strings.
- [ ] **Step 2: Implement** registry + routes + payload.
- [ ] **Step 3: Prefetch** — `--only` accepts both new keys.
- [ ] **Step 4: Run.**

### Task B5: Wide ring and Regional mode

**Files:** Modify `spike/web/dashboard.js`, `spike/web/dashboard.html`, `spike/web/dashboard.css`; Test `spike/web/test-terrain-math.mjs`.

**Interfaces:**
- `loadWideContext(live)` fetches `/context/dem_wide` and reads `state.contextDemWide`, `state.contextImageryWide`.
- `buildRingTerrainWide()` builds a 128² mesh over the wide DEM bbox, textured by `textureRect(wideDemBox, wideImageBox)`; hillshade when the image is absent.
- `MODES.regional` = `{ camera: { heading: 45, pitch: -35, range: 25000 }, limits: { min: 8000, max: 80000 } }`.
- `setMode` shows the local ring in Terrain and the wide ring in Regional.

- [ ] **Step 1: Test texture registration** — `textureRect(wideDemBox, wideImageBox)` for offset boxes returns the expected u/v span.
- [ ] **Step 2: Implement loads + ring + presets + badge** (`60 km · 60 m image · 2 tiles`, reading `imagery_wide`).
- [ ] **Step 3: Fallback** — no wide image → hillshade; no wide DEM → hide the wide ring, show the local ring, badge `wide fetch failed`.
- [ ] **Step 4: Browser** — Regional at 60 km, then with the wide assets removed from a temporary cache root, then Drone.

### Task B6: Evidence and docs

**Files:** `Docs/HANDOFF.md` §8–9, §11; `Docs/dashboard_design.md`; `README.md`; `spike/shots/*`.

- [ ] **Step 1: Screenshots** — `phase6-terrain-4km.png`, `phase6-regional-60km.png`, `phase6-regional-fallback.png`.
- [ ] **Step 2: Docs** — coverage, resolutions, scene pairing, fallbacks, measured download sizes, and the remaining "not a landscape yet" (no lighting/atmosphere) note.
- [ ] **Step 3: Tests** — full offline suite + node; record counts.
- [ ] **Step 4: Diff review** — no unintended files.

---

## Self-review notes

- Spec §2–§6 map to tasks A1–A2 and B1–B5; §7 fallbacks to B2/B3/B5; §8 honesty to A2/B4/B5; §9 performance asserted in B5 step 4; §10 tests distributed to their owning tasks.
- Names used consistently: `detailBox`, `textureRect`, `scaleBar`, `square_extent`, `tiles_for`, `crop_dem_mosaic`, `pick_scene_mosaic`, `read_scene_mosaic`, `context_dem_wide`, `context_imagery_wide`.
- Uncovered risk folded in: date pairing (B3), missing tile (B2), missing asset (B5), scale honesty (A2).
