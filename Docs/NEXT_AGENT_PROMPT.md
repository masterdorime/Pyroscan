# Next Agent Prompt — PyroScan providers, modes, and the two blockers

You are the next agent on **PyroScan**. Do not rely on prior chat context. Read,
in order:

1. `Docs/HANDOFF.md` — engineering state; §9 gaps are authoritative
2. `Docs/dashboard_design.md` — the visual system
3. This prompt
4. `README.md` and `server/README.md`
5. `Docs/specs/2026-11-17-mission-modes-and-spread-visualization.md` — the current design intent

**Repo:** https://github.com/masterdorime/Pyroscan (public, `main`). Check
`git log -1`. Working tree should be clean apart from an untracked `benchmarks/`.

---

## 1. Where the product actually is

The provider layer works. The dashboard shows almost none of it. Hold those two
facts together — most of the work left is the gap between them.

**Shipped and tested (77/77 offline, `python -m server.providers.selftest`):**

- Gateway with per-mission file cache, read-time status (7 states), fallback
  chains, single-flight refresh, fixture fallback, secrets server-side only.
- Weather: BMKG → Open-Meteo. BMKG reports `unavailable` because
  `server/providers/data/adm4_index.json` ships **empty**; Open-Meteo answers.
- NASA FIRMS with a real key in `.env`. **Sensor fallback matters:**
  `VIIRS_SNPP_NRT` returned zero rows for every box tested while `MODIS_NRT`
  returned 36 for the same area, so the adapter tries VIIRS then MODIS.
- Copernicus DEM 30 m, read as a **windowed** COG (0.85 MB for 25 km), cropped to
  a 256² ring heightmap (~712 KB cached), `/context/dem`, Context relief.
- Sentinel-2 **data layer**: STAC search, windowed `TCI.tif` read with CRS
  reprojection, graded WebP (40–115 KB), `/context/imagery.webp`.
- **View modes (Phase 1 of the modes spec):** `Drone · Terrain · Regional` tabs
  with per-mode camera presets and clamps, resolution+age badges,
  disabled-with-reason states, and `#/<mission>/<mode>` deep links. Zoom no longer
  switches mode.

**Two blockers.** Both are "the data arrives and the pixels don't" problems:

1. **Sentinel-2 never reaches the scene.** The asset is fetched, graded and
   served; the render is disabled in `spike/web/dashboard.js`. The read picks a
   neighbouring UTM tile for the 4 km window (`ring lies outside the imagery
   tile`), and the tile that previously worked returned a rasterio IO error.
2. **Regional has no ring terrain.** A 128×128 tinted mesh over the DEM bbox was
   built, added, and never appeared (no console error). It was reverted rather
   than left as dead code. `phase4-regional.png` shows the symptom: a 1.35 km
   mosaic diamond floating on empty background.

---

## 2. What to do first, and how

**Do not fix either blocker by editing and screenshotting.** That was tried
repeatedly last session and cost a lot of tokens for no progress. Instrument
first.

For the Sentinel-2 blocker, one standalone probe:

```python
# prints crs, bounds, transformed window, and whether the window is inside
ds.crs, ds.bounds, ds.width, ds.height
transform_bounds("EPSG:4326", ds.crs, w, s, e, n)
```

Run it against one known-good scene, compare with what
`server/providers/sentinel2.py:read_scene_window` computes, and only then change
code. The adapter already tries three candidates (`pick_scenes`), so the open
question is *which tile contains the window centre*, not how many to try.

For the ring terrain, instrument the primitive: log whether it is in
`viewer.scene.primitives`, whether `show` is true, its `boundingSphere`, and
whether the material renders at all with a known-good `Image` material swapped
in. Candidates: `Color` + `flat: true`, bounding-sphere culling at 30 km ECEF
scale, depth ordering against the mosaic quad.

---

## 3. Then, in order

1. **Modes spec Phase 3** — per-bearing spread model (36 bearings) fed by real
   wind and real terrain, with `reality: real|fixture` per input. This is the
   capability change: the prediction stops being a fixture.
2. **Modes spec Phase 4** — growing front with a trail, driven by that model, with
   the input strip that lets you toggle wind/terrain/fuel and watch the front
   change shape.
3. **Modes spec Phase 5** — per-source surfaces: FIRMS dots sized by FRP and
   coloured by age (blueprint: `Docs/references/ref-modis-fire-map.png`), a
   coverage ring when zero; BMKG wind rose + 3-hourly forecast strip + the `adm4`
   polygon; DEM slope/aspect/LOS; Sentinel-2 two-date swipe.
4. **DEM chain** — DEMNAS ~8 m (Indonesia) → USGS 3DEP 10 m/1 m (USA demo) →
   Copernicus 30 m. **Licences and access are unverified.** Check before writing
   them into a spec as fact.
5. **OSM / Photon** (provider spec Phase 4), then hardening.

---

## 4. Rules that must not be broken

- **No paid APIs or paid keys.** Free/keyless only.
- **No secret in the browser, the repo, or a log.** `MAP_KEY` lives in `.env`
  (gitignored); images/errors are redacted. `git grep <key>` must stay empty.
- **Never present fixture data as real.** Heat, wind vectors, severity, prediction
  geometry and the ignition point are fixtures and say `SIMULASI`. Real provider
  data is `simulated: false` and must never be badged SIMULASI.
- **Resolution honesty.** 30 m context is never shown as reconstruction; the
  camera clamp and the badge carry the cell size. A ring that crosses a 1° cell
  is `clipped` and says so.
- **Brighton has no fires.** Zero detections must render as coverage
  ("N ha monitored · no detections"), never as an error and never as an empty box.
- **The offline path must keep working** in every mode; the static `spike/web`
  shell must keep working with no API.
- **Do not rebuild the ODM pipeline** or replace the Drone mode.

## 5. Traps already paid for

- GDAL curl logs report the object size as `Content-Length` on **HEAD** responses.
  Summing it inflates a windowed read to the whole file. Count `Content-Range` on
  `206` bodies. This mistake produced two wrong "gate failed" conclusions.
- Remote `rasterio.open` has **no Python timeout**. Without
  `GDAL_HTTP_TIMEOUT`/`GDAL_HTTP_CONNECTTIMEOUT` a stalled read pins the gateway's
  single-flight claim forever.
- The gateway must never let a raw exception escape. `_do_refresh` catches
  `Exception` as a last resort; keep it that way.
- A failing refresh can still look healthy for a 3-day TTL. `fail_count` and
  `last_error` carry the truth; the card does not show it yet.
- The demo mission ring crosses a cell edge, so `clipped: true` is normal here and
  several test fixtures had to be moved off the boundary to avoid confusing
  clipping with breakage.
- Browser screenshots are the expensive part of a session. Prefer one instrumented
  probe over three screenshot-and-guess loops.

## 6. Environment

Python 3.14, FastAPI, uvicorn, requests, numpy, pillow, tifffile, **rasterio
1.5.2 (cp314 wheel)**. Node 24, Cesium 1.147 bundled locally, Playwright Edge.

```powershell
python -m server.providers.selftest          # 77/77, no network
python -m server.selftest                    # pipeline checks
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/terrain

python -m server.providers.prefetch --mission SPIKE_BRIGHTON_ODM --only context_dem
node spike\web\shot.mjs "http://127.0.0.1:8000/dashboard.html" "spike/shots/x.png"
```

`PYROSCAN_PROVIDER_OFFLINE=1` forces cache-only. Watch for it lingering in a shell
— it silently makes `prefetch` a no-op and looks like a broken provider.

## 7. Definition of done for the next slice

- Sentinel-2 imagery visible in Terrain/Regional, dated and cloud-labelled, with
  the mosaic as fallback.
- Regional showing ring terrain instead of a floating diamond.
- The front growing from a fixture ignition under real wind and real terrain, with
  the input strip proving that toggling wind changes its shape.
- 77+ offline tests green, docs and screenshots updated in the same commit as the
  code, `Docs/HANDOFF.md` §9 gaps closed or re-scoped honestly.
