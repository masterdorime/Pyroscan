# Indonesia First — Slice 1 (Globe Shell and Boundaries) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Indonesia entry mode: a globe over Indonesia with bundled base imagery, the 38 province borders, a coverage label, and the existing Drone/Terrain/Regional modes unchanged.

**Architecture:** One new client mode (`indonesia`) toggles Cesium's globe, sky atmosphere and a single-tile world image on; the local mission primitives are hidden. A build-time script produces a 38-province GeoJSON (OSM, land-clipped) served read-only by the API; the client loads it as a `GeoJsonDataSource` overlay.

**Tech Stack:** Python 3.14 (shapely = build-time only), FastAPI, Cesium 1.147, static JS, Playwright for browser checks.

**Spec:** `Docs/specs/2026-11-19-indonesia-first-province-splice.md`

**Status:** Tasks 1–5 implemented 2026-11-19. Task 6 (docs/evidence) in the same
change. Slices 2–4 remain.

## Global Constraints

- No paid APIs or keys; OSM/Overpass and Natural Earth are free.
- The app must work offline once assets are bundled; no runtime geometry downloads.
- ODbL attribution `© OpenStreetMap contributors` and Natural Earth are shown wherever the boundaries/base appear.
- Drone/Terrain/Regional must render exactly as before when Indonesia is not active.
- 38 provinces, including the four 2022 Papua splits.
- Existing tests stay green: provider 91/91, pipeline, terrain-math.

## Review Focus

- Switching to Indonesia and back must not leave the mission patch, ring or studio visible.
- A missing/corrupt `provinces.geojson` must leave a usable globe with the coverage label, not a blank scene.
- Enabling the globe must not change Terrain/Regional lighting, background or depth.
- Zoom clamps must keep the Indonesia camera on the archipelago (no accidental zoom to 0 m or past 6,000 km).
- The static (no-API) shell must not break when the province route 404s.

---

### Task 1: Build the 38-province GeoJSON

**Files:**
- Create: `tools/build_provinces.py`
- Create: `server/providers/data/provinces.geojson`
- Create: `server/providers/data/PROVINCES.md` (licence + regeneration note)
- Test: `server/providers/selftest.py`

**Interfaces:**
- Produces `FeatureCollection` with 38 features; each `properties =
  {name: str, iso: str ("ID-KT"), bbox: [w,s,e,n], area_km2: int}`; geometry
  `Polygon | MultiPolygon`, WGS84, land-clipped, simplified 0.002°.
- Consumes: Overpass `rel(area)["admin_level"="4"]; out ids tags;` then
  `rel(<id>); out geom;`; Natural Earth `ne_10m_land.geojson`.

- [ ] **Step 1: Write the failing test** in `server/providers/selftest.py`:

```python
@case
def provinces_catalogue_is_the_38_land_clipped_provinces():
    import json
    from pathlib import Path
    from shapely.geometry import shape
    p = Path(__file__).parent / "data" / "provinces.geojson"
    fc = json.loads(p.read_text(encoding="utf-8"))
    feats = fc["features"]
    assert len(feats) == 38
    isos = [f["properties"]["iso"] for f in feats]
    assert len(set(isos)) == 38 and all(i.startswith("ID-") for i in isos)
    kt = next(f for f in feats if f["properties"]["iso"] == "ID-KT")
    assert 145_000 <= kt["properties"]["area_km2"] <= 165_000
    assert all(shape(f["geometry"]).is_valid for f in feats)
    for name in ("Papua Selatan", "Papua Tengah", "Papua Pegunungan", "Papua Barat Daya"):
        assert any(f["properties"]["name"] == name for f in feats)
```

- [ ] **Step 2: Run it and see it fail** — `python -m server.providers.selftest provinces_catalogue_is_the_38_land_clipped_provinces` → `FileNotFoundError`.

- [ ] **Step 3: Implement `tools/build_provinces.py`** — fetch relation ids + tags,
  then per relation `out geom`; assemble outer ways with `shapely.ops.polygonize`
  and subtract inner polygons; clip with the union of NE land polygons that
  intersect the province bbox; simplify `0.002`; compute `area_km2` with a
  latitude-weighted shoelace; write sorted by `iso`. Download NE land to
  `tools/.cache/` if absent (gitignored). `shapely` is build-time only.

- [ ] **Step 4: Run the builder** — `python tools/build_provinces.py` → prints
  `38 provinces, <size> KB`; file is ~1 MB or less.

- [ ] **Step 5: Run the test** — passes.

- [ ] **Step 6: Write `PROVINCES.md`** — ODbL 1.0 text/attribution, NE public
  domain, the build command, and the note that regeneration drifts with OSM.

- [ ] **Step 7: Commit** — `git add tools/build_provinces.py
  server/providers/data/provinces.geojson server/providers/data/PROVINCES.md
  server/providers/selftest.py && git commit -m "feat(data): 38 land-clipped province boundaries"`

### Task 2: Bundle the world base image

**Files:**
- Create: `tools/fetch_world_image.py`
- Create: `spike/web/data/world_blue_marble.jpg`
- Test: `server/providers/selftest.py`

**Interfaces:** 5400×2700 equirectangular JPEG, `≤ 6 MB`, NASA Blue Marble
(public domain). Served as `/data/world_blue_marble.jpg`.

- [ ] **Step 1: Failing test** — assert the file exists, PIL size is
  `(5400, 2700)`, bytes `< 6_000_000`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement the fetch script** — download
  `https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/world.topo.bathy.200412.3x5400x2700.jpg`
  to the asset path, refuse if the size differs by more than 2×.
- [ ] **Step 4: Run the script, then the test** — pass.
- [ ] **Step 5: Commit.**

### Task 3: Serve the province file

**Files:** Modify `server/api.py`; Test `server/providers/selftest.py`.

**Interfaces:** `GET /api/v1/provinces.geojson` → the committed file,
`application/geo+json`, 404 with a typed message if absent.

- [ ] **Step 1: Failing test** — `TestClient` GET returns 200,
  `content-type` starts with `application/geo+json`, 38 features.
- [ ] **Step 2: Run → fail (404).**
- [ ] **Step 3: Implement the route.**
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit.**

### Task 4: Indonesia mode shell

**Files:** Modify `spike/web/dashboard.html`, `spike/web/dashboard.js`;
Test `spike/web/check-indonesia.mjs` (new, Playwright).

**Interfaces:**
- `MODES.indonesia = { scene: 'indonesia', camera: { heading: 0, pitch: -60,
  range: 4_500_000 }, limits: { min: 800_000, max: 6_000_000 } }`
- `INDONESIA = { lat: -2.0, lon: 118.0 }`; `applyCamera()` targets it when
  `state.viewMode === 'indonesia'`.
- `state.globeReady` true after the viewer has a globe and one imagery layer.
- `setMode('indonesia')` hides every local primitive/group and shows the globe.

- [ ] **Step 1: Failing browser check** — `node spike/web/check-indonesia.mjs`:
  loads `#/SPIKE_BRIGHTON_ODM/indonesia`, expects `state.viewMode === 'indonesia'`,
  `scene.globe.show === true`, `imageryLayers.length === 1`,
  `scene.skyAtmosphere.show === true`, and that `state.prims.contextTerrain.show`
  and `state.prims.landscapeImagery.show` are false. Fails: mode not found.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — viewer `globe: true, baseLayer: false`; add
  `SingleTileImageryProvider` for `/data/world_blue_marble.jpg` over
  `Rectangle.MAX_VALUE`; `globe.baseColor` dark; tab button + `MODE_ORDER`
  prepend `indonesia`; default mode `indonesia`; `applyModeVisibility()` hides
  `prims` and `groups` outside Indonesia; gate `showBase`/`setLayer`/
  `applySceneTheme` for Indonesia; badge `COVERAGE · INDONESIA`; camera target
  and clamps from the interfaces above.
- [ ] **Step 4: Run the check → pass.**
- [ ] **Step 5: Regression screenshots** — Drone, Terrain, Regional; compare
  visually to `phase6-*` and assert no console errors.
- [ ] **Step 6: Commit.**

### Task 5: Province borders overlay

**Files:** Modify `spike/web/dashboard.js`; Test `spike/web/check-indonesia.mjs`.

**Interfaces:** `state.provinces` = `GeoJsonDataSource` added once;
`state.provinces.entities.values.length === 38`; stroke
`#9fc2b0` alpha 0.55, fill alpha 0.06; visible only in Indonesia mode.

- [ ] **Step 1: Extend the check** — after load, 38 entities, datasource show
  true in Indonesia; switch to Terrain, expect show false; reload with the
  route stubbed to 500 and expect the globe plus `COVERAGE · INDONESIA`, no
  page error.
- [ ] **Step 2: Run → fail (no datasource).**
- [ ] **Step 3: Implement** — `GeoJsonDataSource.load('api/v1/provinces.geojson',
  {stroke, fill, strokeWidth: 1})`, `clampToGround: true`; add on init;
  hide/show in `applyModeVisibility`; catch load failure and set
  `state.provincesFailed = true` (badge still shows coverage).
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Screenshot** `spike/shots/phase7-indonesia.png`.
- [ ] **Step 6: Commit.**

### Task 6: Docs and evidence

**Files:** `Docs/HANDOFF.md` (§6, §9, §11), `README.md`, `.gitignore`.

- [ ] **Step 1:** Add the Indonesia level, the boundary source/licence, the
  bundle sizes, and the fact that counts/dots are Slice 2.
- [ ] **Step 2:** Allow-list `phase7-*.png`; screenshot names.
- [ ] **Step 3:** Run the full offline suite and record counts.
- [ ] **Step 4:** Review `git diff` for unintended changes.
- [ ] **Step 5:** Commit.

---

## Later slices (not in this plan)

- **Slice 2:** FIRMS country query, per-province counts, labels.
- **Slice 3:** province imagery preview + card + fallback.
- **Slice 4:** detail tier + recon handoff.

## Self-review notes

- Spec §3 Indonesia level → Tasks 4–5; §4.1 boundaries → Task 1; §6 Indonesia
  → Tasks 4–5; §7 honesty → Task 4 badge + Task 5 failure; §8 performance →
  Task 4 check; §9 tests → Tasks 1–5.
- Names consistent: `MODES.indonesia`, `INDONESIA`, `state.provinces`,
  `setMode('indonesia')`, `applyModeVisibility`.
- The five review-focus items each have an assertion in Task 4 or 5.
