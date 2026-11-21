# PyroScan — Handoff

**Date:** 2026-11-18
**Repo:** https://github.com/masterdorime/Pyroscan (public, `main`). Raw drone data and the reference video are not committed; the demo DB, mission assets, Cesium bundle, and screenshots are.
**Status: provider layer Phase 1-2 shipped; Phase 3 data layer shipped, both render blockers fixed; wide Terrain/Regional ships; Indonesia is a 2D map with four skins (slices 1-4 plus the 2D renderer); view modes Phase 1 shipped.** Weather (BMKG → Open-Meteo), NASA FIRMS detections, Copernicus 30 m terrain and Sentinel-2 imagery are fetched, cached and surfaced with source/age. The dashboard opens on **Indonesia** (globe + 38 province borders), then Drone / Terrain / Regional. Since 2026-11-18 the Sentinel-2 crop is drawn in Terrain/Regional, Regional draws a 60 km landscape from a 4-tile DEM and 2-scene imagery mosaic, and the wide layer falls back to the 15 km ring when its cache is missing. §9.24–26 state what the Indonesia shell does not do yet.

Specs and plans:
`Docs/specs/2026-11-16-free-provider-layer-design.md`,
`Docs/specs/2026-11-17-mission-modes-and-spread-visualization.md`,
`Docs/plans/2026-11-16-free-provider-layer-phase-1.md`,
`Docs/plans/2026-11-16-free-provider-layer-phase-2.md`,
`Docs/plans/2026-11-17-free-provider-layer-phase-3.md`.

**Test state.** `python -m server.providers.selftest` → **91/91**, no network.
`python -m server.selftest` → PASS. `node spike/web/test-terrain-math.mjs` → PASS
(the DEM grid/datum/scale maths used by every context surface).
`--live` reaches all three providers when the FIRMS key is present. `MAP_KEY`
lives in `.env` (gitignored, never committed).

**Render-blocker probe.** `python tools/probe_sentinel2_window.py` prints the
scene CRS, bounds, transform, the mission window in 4326 and in the raster CRS,
the pixel window, clipping, ring coverage and the actual read for every STAC
candidate, then compares that with `read_scene_window`. It is read-only; no
cache, DB or dashboard state is touched. Run it before changing scene selection
again.

**Measured facts worth keeping.**
- Copernicus DEM: a 25 km window transfers **0.85 MB**, so reads are windowed;
  cached heightmap is ~712 KB per mission. A ring crossing a 1° cell is clipped
  and flagged, not mosaicked.
- Sentinel-2: 1.2 km window **1.46 MB**, 25 km window **15.95 MB**; cached WebP
  is 40–115 KB.
- FIRMS: `VIIRS_SNPP_NRT` returned **zero rows everywhere** on 2026-11-16 while
  `MODIS_NRT` returned 36 for the same area, so the adapter tries VIIRS → MODIS
  and stops at the first non-empty response. A single hardcoded sensor would have
  reported "no fires" indefinitely.
- Brighton has **no fires**, correctly. Zero detections must read as coverage,
  not as an empty box.

**Measurement lesson (recorded because it cost two wrong conclusions).** GDAL
curl-verbose logs report the full object size as `Content-Length` on **HEAD**
responses. Summing that overstates a windowed read by the whole file. Count
`Content-Range` spans on `206` bodies instead. The provider spec's §7.5 has the
corrected table.

**Architecture (Phase 1).** `server/providers/` holds one adapter per source and
one `Gateway` that owns a per-mission file cache, read-time status derivation,
fallback chains, and single-flight background refresh. The API calls the
gateway; the browser calls only the API. Cache lives in
`server/cache/providers/<mission_id>/` (gitignored). Statuses: `fresh`, `stale`,
`offline`, `empty`, `unconfigured`, `unavailable`, `error` — derived from
timestamps on every read, never stored.

**What is real now.** Weather is Open-Meteo for Brighton (BMKG needs an `adm4`
code and the bundled index ships empty, so BMKG reports `unavailable` there and
for any mission outside Indonesia once the index is populated). FIRMS is
**unconfigured** until `PYROSCAN_FIRMS_MAP_KEY` is set in `.env`; the inset says
"add MAP_KEY to enable" and shows nothing fake. Heat, wind vectors, prediction
geometry, severity and advisory remain fixtures marked SIMULASI.

**Still open.** Populate `adm4_index.json` from a licence-cleared boundary
dataset (§15.1). The Phase 3 Sentinel-2 gate **passes** after correcting a
measurement error (§7.5): a 1.2 km window transfers 1.46 MB and a 25 km window
15.95 MB, both inside budget. Phase 3 can proceed as specified. Also pending: the
DEM adapter still downloads whole tiles and should be switched to windowed reads
(~0.85 MB instead of 34–42 MB).
Read this first. Do not rebuild the pipeline.

---

## 1. TL;DR

- **Photogrammetry works** on the Brighton sample: 18/18 aligned, 1.08 px,
  1.64 cm GSD, 0.71 ha.
- **Pipeline works**: ODM task → heightmap/ortho → DEM fusion → spread model →
  advisory → SQLite → FastAPI → dashboard.
- **Dashboard works**: 3D mission console with a **Context → Reconstruction**
  flow. Context is the cached basemap + mission footprint + hotspot pins;
  clicking the footprint/chip or zooming in reveals the photogrammetry patch.
  Reconstruction has the base surfaces, overlays, presets, legend, forecast
  strip, and minimap.
- **UI pivot complete**: paper default + persisted theme dropdown; incident
  header, card rail, elevation profile, and a bright landscape in paper.
  Obsidian keeps the dark studio.
- **Provider layer shipped (Phases 1–3).** Live weather, FIRMS detections,
  Copernicus DEM and Sentinel-2 imagery, cached with source/age; Drone /
  Terrain / Regional tabs. Terrain/Regional draw the 30 m DEM (mosaic + ring)
  with the Sentinel-2 crop.
- **Next: modes Phase 3+** — per-bearing spread, growing front, per-source
  surfaces. Then OSM/Photon labels. No paid keys.
- **Coordinate readout is not implemented.** The top bar shows the mission
  centre, not the cursor. A hover probe/card was discussed; accuracy is limited
  by drone GPS and basemap registration, not by the UI math.

---

## 2. Run it

```powershell
python -m server.selftest
python -m server.import_mission          # imports the existing ODM task
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000
# live dashboard: http://127.0.0.1:8000/dashboard.html

# static-only fallback (fixtures, no API):
python -m http.server 8080 --directory spike/web
# http://127.0.0.1:8080/dashboard.html

python spike\tools\make_dashboard_assets.py   # regenerates base textures
node spike\web\shot.mjs "http://127.0.0.1:8000/dashboard.html" "spike/shots/test.png" --headed
```

Docker/NodeODM (`opendronemap/nodeodm`, port 3000) and Ollama
(`qwen3.5:4b-q4_K_M`) were available during development. Verify with
`docker ps` and `ollama list`.

---

## 3. Architecture

```
Android payload ──Wi-Fi bulk──► photo folder ──watcher──► NodeODM
                                                     │
                                              DSM + ortho
                                                     ▼
                         assets → fusion → spread → advisory → SQLite
                                                     │
                                            FastAPI + SSE
                                                     ▼
                                         Cesium dashboard (web)
```

- One API boundary: FastAPI. Offline-critical path; online providers are cached.
  No Cesium ion, no CDN, no Google tiles.
- **Planned provider gateway** (not built): BMKG/Open-Meteo, NASA FIRMS,
  Copernicus DEM, Sentinel-2, OSM/Photon → FastAPI adapters → cache/TTL →
  API/UI source/age metadata.
- Two languages: Python server, TypeScript/JS UI (current shell is plain JS;
  React/Vite port is pending).
- GPU rule: ODM and LLM never share VRAM (`OLLAMA_KEEP_ALIVE=0`).

---

## 4. Key files

| Path | Role |
|---|---|
| `server/api.py` | REST + SSE + static dashboard; path rebase for clone |
| `Docs/NEXT_AGENT_PROMPT.md` | copy-paste handoff prompt for the next agent |
| `server/providers/` | provider adapters, gateway, cache/TTL, prefetch CLI, selftest |
| `server/db.py` | SQLite schema and queries |
| `server/pipeline/runner.py` | mission orchestration |
| `server/pipeline/assets.py` | ODM → heightmap/ortho/shaded ortho |
| `server/pipeline/fusion.py` | elevation/slope/aspect, `spatial_fusion.json` |
| `server/pipeline/spread.py` | wind + upslope vector model |
| `server/pipeline/advisory.py` | template advisory / optional Ollama |
| `server/photogrammetry/nodeodm.py` | NodeODM client |
| `server/import_mission.py` | import existing ODM task |
| `server/watcher.py` | polling inbox watcher |
| `server/selftest.py` | fusion/spread/advisory/DB checks |
| `spike/web/dashboard.html/.css/.js` | current dashboard |
| `spike/tools/make_dashboard_assets.py` | base textures, heat, floor, minimap |
| `spike/missions/SPIKE_BRIGHTON_ODM/` | mission assets |
| `server/pyroscan.db` | live SQLite |
| `Docs/dashboard_design.md` | design spec and reference gallery |
| `Docs/references/` | FireTrace frames + user references |

---

## 5. API and data

Browser → FastAPI:
`/api/v1/health`, `/missions`, `/missions/latest`, `/missions/{id}`,
`/fusion`, `/advisory`, `/heightmap`, `/ortho.webp`, `/ortho_shaded.webp`,
`/mesh.glb`, `/events` (SSE heartbeat), `/data/*` static.

Server → services: NodeODM REST, Ollama `/api/generate`, BMKG, NASA FIRMS,
Copernicus DEM, Sentinel-2 (Earth Search STAC + AWS COG), Open-Meteo
`/v1/forecast` (all via the provider gateway, cached). Provider routes:
`/missions/{id}/providers`, `/providers/{key}`, `/providers/refresh`,
`/regional_fires`, `/context/dem`, `/context/dem_wide`,
`/context/imagery.webp`, `/context/imagery_wide.webp`. `latest`/`{id}` carry
`providers` (status/age/detail), `imagery` (url, bbox, scene, date, cloud,
resolution, attribution), `imagery_wide` (scenes, date range, tile count),
`dem` and `dem_wide` (bbox, tiles, coverage, clip). Prototype minimap still uses
a cached Esri image; the scene basemap is Sentinel-2.

Data:
- `spike/missions/<id>/heightmap.json` — 384² DSM
- `spike/missions/<id>/ortho.webp` — ortho
- `spike/missions/<id>/ortho_shaded.webp` — hillshaded ortho
- `spike/missions/<id>/spatial_fusion.json`, `advisory.json`
- `spike/web/data/` — terrain/elevation/severity/heat/floor/context assets
- `server/cache/weather.json`
- `server/cache/providers/<mission>/` — `*.envelope.json` + `context_dem.json` +
  `context_imagery.webp` (gitignored, served by the API)

---

## 6. Current dashboard state

- **Indonesia (default, 2026-11-19):** Cesium globe over the archipelago, NASA
  Blue Marble base, 38 OSM province borders, `COVERAGE · INDONESIA`, camera
  clamped to 800–6,000 km. The mission rail, forecast strip and minimap are
  hidden; the incident header reads `Indonesia / NATIONAL VIEW`.
  **Slice 1 only:** no fire counts, dots, province imagery or recon yet.
- **Default view: Context.** Cached bright basemap, area-equivalent mission
  footprint disc + label, **hotspot pins**, `Open reconstruction` pill, and a
  photogrammetry card in the Layers tab. Heat, prediction, flight path, base
  surfaces, and presets are hidden. Minimap hidden.
- **Reconstruction.** Click the footprint, a hotspot, the pill/card, or zoom
  past ~220 m. Camera flies to 220 m / -30°; the patch and the full base/overlay
  stack appear; layer controls become active; minimap returns. `Context` pill
  or zoom out past ~380 m returns.
- **Skin**: paper is the default; the top-bar **theme dropdown**
  (Paper / Obsidian) persists to `localStorage` (`pyroscan-theme`). Context is
  bright in both themes; reconstruction is paper-bright or obsidian-dark.
- **Incident header**: name (`Brighton Beach`), mission id, date/coordinates in
  the top bar. **Incident card** above the tabs: area, photos, GSD, processing,
  aligned, severity.
- **Base surfaces**: Terrain (hybrid photo + tints + 2 m contours), Elevation,
  Shaded ortho, Burn severity. One active at a time. Paper uses feathered-alpha
  variants with a 1.55 tint; the materials swap on theme.
- **Overlays**: Heat (5 bands), Wind (3D arrows), Prediction (Now/+30/+60
  fronts), Hotspots (ringed pins), Flight path. Legend with units/classes.
- **Presets**: Terrain / Fire / Forecast / Burn.
- **Forecast strip**: now → +60, burned area, rate of spread, **elevation
  profile**, key events. The profile is the steepest cardinal/diagonal
  transect through the centre (N–S on Brighton, 157–173 m); the 45° spread
  bearing is flat (161–162 m), so it is not used.
- **Scene**: context = bright context mosaic (`context_bright.png`, 1.35 km,
  opaque centre + alpha ring, CSS haze); reconstruction paper = bright patch,
  obsidian = dark studio floor + grid.
- **Measured**: context p50 14 ms / p95 21 ms; reconstruction p50 21 ms /
  p95 28 ms; HUD 20–28 ms. Headless Edge used Intel UHD, not the RTX 4060; the
  33 ms target is met in this run. Re-check on the discrete GPU.
- **Screenshots**: `Docs/references/ref-pyroscan-paper.png` (context paper),
  `ref-pyroscan-obsidian.png` (context obsidian),
  `ref-pyroscan-recon-paper.png`, `ref-pyroscan-recon-obsidian.png`,
  `ref-pyroscan-theme-menu.png`.
- **Not implemented:** live cursor coordinate probe/card, regional FIRMS view in
  the scene (the inset exists), OSM place labels/geocoder, per-source mode
  surfaces. Provider layers, context DEM and Sentinel-2 imagery now ship.

---

## 7. UI pivot and view revision (done)

The user changed their mind: **reference FireTrace more closely**. Selected:

1. **Warm paper palette + type.** Cream surfaces, ink text, orange/flame
   accents, thin borders, small dense type. Paper is the default; obsidian is
   still available via a persisted top-bar **theme dropdown**.
2. **Incident header + card rail.** Incident name, location, date range across
   the top; incident overview and weather/fire-behavior cards.
3. **Third chart**: elevation profile beside burned area and rate of spread.
4. **Bright natural scene** instead of the dark studio void.

Not selected (do not add unless asked): map callouts/scale, drone fleet, live IR.

**Progress:** Step 1 done — paper tokens/surfaces/chart colors. Step 2 done —
incident header, incident card, top-bar theme dropdown, `started_at`/`ended_at`
in the API payload, `context.name`. Step 3 done — elevation profile chart
(steepest cardinal/diagonal transect) and four-column forecast strip. Step 4
done — bright context mosaic for paper, feathered paper base textures, CSS
horizon haze; obsidian keeps the dark studio.
**View revision done** — Context is the default (basemap + footprint disc +
hotspot pins + Open reconstruction); click/zoom opens Reconstruction at
220 m / -30°; Context pill, minimap, or zoom-out returns. Context stays bright
in both themes.
Screenshots: `spike/shots/context-paper.png`, `context-obsidian.png`,
`recon-paper.png`, `recon-obsidian.png`, `theme-menu-context.png`.

### Why the view revision

The combined patch-on-basemap view mixed a 1.6 cm reconstruction with a
~0.66 m/px basemap; the eye could not tell which was data. The revision hides
the patch until the user asks for it and keeps the hotspot pins visible in
Context. The footprint is an **area-equivalent disc** (0.71 ha), not the exact
irregular ortho boundary.

### Why the reference looks different

FireTrace is not a small patch on a dark plane. It is:

- a **large lit landscape** (kilometres) with aerial imagery on terrain and a
  visible horizon;
- **daylight lighting** — directional sun + ambient/hemisphere, tone mapping and
  exposure, shadows;
- **atmosphere** — sky gradient, fog/haze fading into distance;
- **warm grade**, saturated vegetation, bright exposure;
- likely **Three.js/React**, not Cesium, with a large heightfield.

Our earlier attempt was a **143 m patch on a dark flat satellite plane**, with
no sun, no horizon, no atmosphere, and a muted grade. That is why muting it made
an instrument, not a landscape.

### Compact implementation path (recommended order)

**Step 1 — paper skin (done).**
- Replace `:root` palette with paper/ink tones; add overrides for the hardcoded
  `rgba(20,20,25,...)` surfaces (legend, controls, top bar, rail, strip).
- Cesium labels/points stay charcoal-on-dark; they remain legible on the
  bright patch. Revisit only if the scene grade changes.
- Keep the 3D scene as is for this step; verify contrast and p95.

**Step 2 — incident header + card rail (done).**
- Top bar: incident name (`context.name`), mission id, date + coordinates.
- Compact incident card above the tabs: area, photos, GSD, processing time,
  aligned count, severity. The Mission tab keeps the detailed record + window.
- **Theme dropdown** in the top bar (Paper / Obsidian), persisted in
  `localStorage['pyroscan-theme']`; paper is the default. Menu closes on
  select, outside click, or Escape; arrow keys move between options.
- API payload now exposes `mission.started_at` / `mission.ended_at`;
  `config.CONTEXT.name` is the incident name. No new endpoints.

**Step 3 — third chart (done).**
- `#chart-elev` in the strip; label `Elevation · N–S`; value `157–173 m`.
- Samples the **steepest cardinal/diagonal transect** through the centre
  (0° on Brighton) because the 45° spread-bearing profile is flat (1.1 m
  relief). Title documents the transect.
- Charts grid: `1fr 1fr 1fr 220px`; at 1180 px the events column is 180 px;
  under 900 px events hide and the three charts split the strip.
- The profile is static terrain, not a time series; no forecast cursor.

**Step 4 — bright landscape (done).**
- **Theme interaction:** paper gets the bright landscape; obsidian keeps the
  dark studio. The switch is in `applySceneTheme`, not a CSS filter.
- **Paper**: `context_bright.png` (graded `context.jpg`, 2048², soft alpha,
  ~8.6 MB) as a 1.35 km context mosaic: **opaque centre quad + translucent
  outer ring** at the context bbox, patch base `hmin - 1.6`. Scene background
  `#dfe8e3`. CSS haze over the horizon; camera 300 m / -22°.
- The centre is **opaque** because a translucent context plane drew over the
  mission patch. The outer ring carries the alpha fade, so the horizon stays
  soft without covering the patch; CSS haze adds atmosphere.
- **Paper base variants**: `terrain_base_paper.webp`, `elevation_paper.png`,
  `severity_base_paper.png`, `ortho_shaded_paper.webp` have a 6% blurred
  footprint alpha; `applySceneTheme` swaps materials and applies a 1.55 tint.
- **Obsidian**: studio floor with pad 1.5, dark background, landscape hidden,
  tint 1.0.
- **Still flat:** no context DEM, no real sun/shadows; the coast is a basemap,
  not reconstructed terrain. The patch remains a high-res inset with a feathered
  edge. Esri is prototype-only.
- **Better/full match** options remain: a coarse context DEM or Three.js with
  directional lighting.

Do not fake scale: label the context as 30 m context, keep the mission footprint
distinct, and do not imply reconstruction beyond the measured patch.

### Acceptance

- Paper palette, no dark panels; readable outdoors. **Done.**
- Incident header with location/date; card rail. **Done.**
- Paper/Obsidian theme dropdown persists across reloads. **Done.**
- Three charts, elevation profile included. **Done.**
- Bright landscape with horizon/atmosphere; patch still legible. **Done.**
- Context default with footprint and hotspot pins; click/zoom reveals
  Reconstruction. **Done.**
- Reconstruction camera 220 m / -30°; Context pill, minimap, and zoom-out
  return. **Done.**
- p95 under 33 ms at 1600×900; zero external requests. Context p95 21 ms;
  reconstruction p95 28 ms on Intel UHD; target met in this run. Zero external
  requests holds.
- Keep `Docs/dashboard_design.md` in sync and save new screenshots to
  `Docs/references/`.

---

## 8. Free provider layer — status

**Shipped:** Phase 1 (gateway, cache, weather, FIRMS, source/age) and Phase 2
(Copernicus DEM, windowed reads, `/context/dem`, Context relief). Phase 3's data
layer ships and now renders: STAC search, windowed `TCI.tif` read, graded WebP,
`/context/imagery.webp`, and the Terrain/Regional surface. §9.19–20 record the two
render causes, the evidence and the remaining limits.

The design text below is retained as the record of *why* the layer is shaped this
way. Read it for the rationale, not as a to-do list.

The next planned subsystem is a free/keyless provider layer. No provider code
or approved spec exists yet.

**Locked decisions**
- **Indonesia-first**; Brighton remains the demo.
- **Hybrid live refresh**: fetch when online, always serve cache, show
  source/age/stale. No paid APIs.
- **Mission + 10–25 km regional ring** cache footprint.
- **Auto-resolve BMKG `adm4`** from a bundled Indonesian level-4
  boundary/code index; manual `adm4` fallback; Open-Meteo fallback.

**Providers**

| Provider | Role | Key / account | Cost |
|---|---|---|---|
| BMKG | Indonesian weather/wind primary | none; needs `adm4` | free |
| Open-Meteo | global weather/wind fallback | none (non-commercial) | free |
| NASA FIRMS | regional active fire (NRT) | free `MAP_KEY` | free |
| Copernicus DEM | context terrain (30 m) | none (AWS Open Data) | free |
| Sentinel-2 | context imagery (10 m) | none on AWS; free CDSE account optional | free |
| OSM / Photon | roads, place labels, reverse geocode | none; public policy/self-host | free |
| ODM / Ollama | existing mission reconstruction / advisory | none | local |

**Recommended architecture**
- **A. FastAPI provider gateway + cache** (recommended): one adapter per
  provider, shared `ProviderResult` (`data`, `source`, `observed_at`,
  `fetched_at`, `age`, `status`, `error`, `licence`), file cache, TTL,
  background/CLI prefetch. No Redis/Celery.
- **B. Browser calls providers directly** — rejected: keys/CORS/terms, no
  central cache, weak offline behavior.
- **C. Separate data-pipeline service** — use as a prefetch step inside A for
  heavy DEM/Sentinel/OSM data, not a separate runtime.

**TTLs**: weather 15–30 min; FIRMS 1–3 h; Sentinel 1–5 days; DEM/OSM 30–90 days.

**API/UI**: `/api/v1/missions/{id}/providers` status; payload additions for
`regional_fires`, `context_dem`, `context_imagery`, `places`. UI adds a
**Live data** source/age card, regional FIRMS layer/inset, context terrain and
imagery, OSM labels/place card. Real satellite fire is labelled
`NASA FIRMS · NRT`, not `SIMULASI`.

**Phases**
1. Provider framework + BMKG/Open-Meteo + FIRMS + source/age. FIRMS starts as a
   regional card/inset.
2. Copernicus DEM + regional context terrain.
3. Sentinel-2 context imagery; replace the Esri prototype basemap.
4. OSM/Photon labels + coordinate place card.
5. Hardening: stale/offline states, provider fixtures, failure tests,
   attribution, storage.

**Risks**
- BMKG `adm4`: finding an open level-4 boundary/code dataset that maps cleanly
  to BMKG codes and permits use. Manual `adm4`/Open-Meteo is the safety valve.
- Sentinel-2 clouds/revisit; windowed COG reads needed.
- OSM public tile/Nominatim limits; self-host for production.
- Esri licensing; replace for a free public deployment.
- Hybrid mixed-age data; source/age/stale UI is mandatory.
- Per-mission ring storage ~30–100 MB; no GPU for providers; ODM is still the
  hardware bottleneck.

**Coordinate readout**: not implemented. It is local Cesium math; accuracy is
limited by drone GPS/basemap registration, not by the hover code. OSM/Photon
later supplies place names for a Google-like card. Do not imply survey accuracy.

**Next step**: Phase 1 is implemented and committed. Remaining before Phase 2:
populate the `adm4` index, set `PYROSCAN_FIRMS_MAP_KEY` and capture a real FIRMS
CSV to replace the synthetic fixture. Then start Phase 2 from
`Docs/specs/2026-11-16-free-provider-layer-design.md` §13 (its first task is the
COG-reader gate, §7.5). Keep this file in sync and push after each phase.

---

## 9. Known gaps

1. **YOLO is not wired.** Hotspots are imported fixtures; a new inbox mission
   creates one manual centre hotspot.
2. **Watcher/NodeODM client** are wired but not exercised on a new flight.
3. **Weather** is the cached fixture unless `online=True`; implementation uses
   Open-Meteo, not BMKG. BMKG is planned.
4. **Advisory** is the template (engine severity + closed catalog); `--llm`
   calls qwen3.5:4b and falls back to the template.
5. **Heat, wind, prediction, severity** remain fixtures; labeled SIMULASI.
6. **SSE** is a heartbeat only; mission progress events are not streamed yet.
7. **Frontend** is a static JS shell; React/Vite/Tailwind port pending.
8. **No auth**, **no PWA**; LAN only.
9. **rasterio/watchdog** are not installed (Python 3.14); fusion uses the
   heightmap, watcher polls.
10. **Basemap licensing**: Esri is prototype-only; product needs Sentinel-2 or
    offline tiles.
11. **Bright context is flat**: a 30 m basemap, not a context DEM, and no real
    sun/shadows. The mission patch is a feathered high-res inset, not a seamless
    reconstruction of the surrounding terrain.
12. **Context texture is 8.6 MB PNG**: fine locally; optimize to WebP/1024 if
    load time or memory matters.
13. **Minimap is still static**: context crop + mission box + click-to-Context;
    the camera frustum/heading overlay is not implemented.
14. **Context footprint is an area-equivalent disc** (0.71 ha), not the exact
    irregular ortho boundary. An alpha-contour footprint would be more precise.
15. **Provider layer is Phase 1 only.** Weather (BMKG/Open-Meteo) and regional
    FIRMS detections ship with source/age. Copernicus DEM, Sentinel-2 imagery and
    OSM/Photon are still planned. `adm4_index.json` ships empty, the FIRMS fixture
    is synthetic, and no real FIRMS capture has been parsed yet.
16. **Cursor coordinate readout is not implemented.** The top bar shows the
    mission centre, not the mouse. Hover math is local; absolute accuracy is
    limited by drone GPS and basemap registration.
17. **`mesh.glb` is not committed.** The API `/mesh.glb` endpoint can 404; the
    dashboard builds its mesh from `heightmap.json` and does not use it.
18. **Servers stop on restart.** Start uvicorn with the commands in §2 before
    testing; `api/v1/health` returning 200 is the check.
19. **Sentinel-2 render — FIXED 2026-11-18 (residual limits below).** Two
    independent causes, both proven with the probe:
    **(a) scene selection.** `intersects` is a footprint test, not a raster-grid
    test. At Brighton the 4 km window is centred at 46.8427 N; the neighbouring
    MGRS tile `15TWN` starts at 46.8566 N, so it intersects the search polygon
    and is regularly the **least cloudy** scene. `pick_scenes` ranked by cloud
    only, selected 15TWN, and `read_scene_window` then clipped to a sliver and
    raised `ring lies outside the imagery tile`. It is now ranked by
    *window-centre coverage first*, cloud second (unknown-bbox fixtures keep the
    old order). Probe on the real STAC response: 15TWN was first, 15TWM is first
    now. **(b) rendering.** `buildLandscape()` hardcoded
    `data/context_bright.png`; `contextTexture()` was dead code, so even a good
    asset could not reach the scene. Terrain/Regional now draw the cached crop,
    registered by the provider bbox (the old hardcoded 0.2–0.8 sub-rect was a
    1.78× zoom error), with scene date, cloud, resolution, window and the
    Copernicus credit. Drone keeps the Esri backdrop. **Not a cause:** tile
    choice was the only *geometry* fault — CRS transform, axis order, window
    offsets and clipping were verified correct against the raster.
    **Residual:** live COG reads from `sentinel-cogs` are unusably slow on this
    network (~35 KB/s; a 1.5 MB block exceeds even a 120 s GDAL timeout), so a
    refresh currently fails and the 2026-10-02 cache is what renders. That is a
    link limitation, not a selection bug; `fail_count`/`last_error` record it.
    The cached asset has no per-site cloud mask, so the scene's 0 % is
    scene-level, not a cloud-free guarantee over the patch.
    Regression tests: `s2_ranks_a_covering_scene_above_a_less_cloudy_neighbour`,
    `s2_provider_never_reads_the_neighbour_first`,
    `s2_keeps_unscored_scenes_in_cloud_order`,
    `s2_window_read_keeps_the_utm_axis_order`,
    `s2_window_is_centred_on_the_mission_not_the_clipped_ring`.
20. **Regional ring terrain — FIXED 2026-11-18 (residual limits below).**
    `buildRingTerrain()` builds a 128² mesh over the Copernicus DEM bbox
    (15.6 × 30.2 km here), anchored to the patch datum at the mission centre,
    with a hillshade texture and the 1.35 km patch footprint cut out. Instrumented
    state: primitive `ready`, `show` true in Terrain/Regional and false in Drone,
    16,641 vertices / 32,696 triangles, bounding sphere r = 16.95 km centred on
    the mission, finite heights spanning 135–398 m. The reverted attempt could
    not be inspected (it never reached a commit), so the two named suspects were
    tested directly: a `Color` material with `flat: true` **renders** (suspect
    eliminated); a primitive given a bounding sphere at the Earth's centre
    reports `ready=true`, `show=true` and **draws nothing with no console error**
    — the exact symptom profile of §9.20's original failure. The new mesh derives
    its sphere from its own vertex buffer. **Residual:** the ring meets the fine
    mosaic through a one-cell blend that sits below the patch (invisible at
    Regional scale, but the seam is not survey-accurate); the surface is
    flat-shaded hillshade, not lit; the western edge is the DEM tile clip, which
    the badge already calls "clipped ring".
    Regression test: `node spike/web/test-terrain-math.mjs` (row order, datum
    anchor, index bounds, fill).
21. **Modes are Phase 1 only, plus the ring.** Tabs, presets, per-mode clamps,
    badges and hash deep links work; the DEM ring now draws in Terrain/Regional.
    Not built: per-source surfaces, the per-bearing spread model, and the growing
    front.
22. **DEM chain not started.** 30 m is coarse for fire behaviour (a 10 m firebreak
    is invisible). Intended chain: DEMNAS ~8 m (Indonesia) → USGS 3DEP 10 m/1 m
    (USA demo) → Copernicus 30 m. Licences and access are **unverified**; do not
    write them into a spec as fact until checked.
23. **A persistently failing refresh looks healthy.** TTL (3 d for imagery) keeps
    an 8-hour-old cache `fresh` and green even when every refresh is failing.
    `fail_count` and `last_error` carry the truth but the card does not show it.
24. **The wide layer is a mosaic, not one image.** Regional reads 4 Copernicus
    tiles (100 % coverage here, no clip) and 2 Sentinel-2 scenes
    (`15TWM` 2026-10-02 + `15TWN` 2026-10-10). Two limits: a faint tonal **seam**
    remains where the dates meet (no radiometric matching), and the scenes are
    paired within ±14 days, so a much older neighbour would be labelled
    `multi-date` rather than hidden. Wide downloads measured: DEM ≈ 1.0 MB JSON,
    imagery ≈ 0.3 MB WebP — both far below the 4–8 MB estimate. The wide surface is
    still flat-shaded: no sun, shadows or atmosphere, which is the main gap to
    the FireTrace reference.
25. **The 60 km view makes the mission a marker.** A 143 m patch is ~2 px at that
    range; Regional is landscape context, not a survey view. Terrain (4 km) and
    Drone remain the detail surfaces, and the badge/legend state each surface's
    resolution so the scale ladder is not flattened.
26. **Indonesia mode is the entry shell (slice 1.5).** Cesium globe, bundled
    NASA Blue Marble base, 38 OSM province borders (`admin_level=4`, land-clipped
    with Natural Earth), camera clamp and coverage label. Boundaries are ODbL
    1.0 — see `server/providers/data/PROVINCES.md`; both Blue Marble images are
    public domain.
    **Skin (2026-11-19):** a `Texture / Flat` control sits top-right in Indonesia
    and persists at `localStorage['pyroscan-globe-skin']`. Flat hides both
    imagery layers and sets `globe.baseColor` to `#14211c`; borders, atmosphere
    and the camera stay. If the base image fails to load the globe falls back to
    flat in memory (not persisted, so the next load retries) instead of leaving
    a blank globe. Reference image: `spike/shots/phase8-indonesia-flat.png`.
    **Regional LOD:** `spike/web/data/indonesia_blue_marble.jpg` — 4096×1700,
    663 KB, NASA GIBS WMS 1.1.1 over `94,-12,142,8`, ~1.3 km/px, regenerated by
    `tools/fetch_indonesia_base.py`. It is a second `SingleTileImageryProvider`
    above the world layer, shown only when `indonesia && texture && camera height
    < 2.5 M m`; the `postRender` check reads the camera and writes `show` only
    when the boolean changes. Measured +1 ms at a 2,000 km camera (27 → 28 ms,
    `node spike/web/perf-globe.mjs`), and the crop is visibly sharper than the
    7.4 km/px world base at 900 km (`phase8-indonesia-lod.png`). The crop
    rectangle's edge is a hard edge at 94/142 °E; it is not feathered.
    **Province selection:** click a province (the same `camera.pickEllipsoid` +
    point-in-polygon as hover) to select it, dim the other 37 to alpha 0.22, fly
    to its bbox expanded 8 % (`camera.flyTo`, 1.4 s) and open `#province-panel`
    bottom-left with name, ISO and land area. Selection wins over hover; `Clear`,
    `Esc` or a sea click clears and returns to the Indonesia camera. Leaving the
    mode clears the selection; the panel is hidden outside Indonesia. Panel copy
    says counts/imagery are the next slice — no invented numbers. Evidence:
    `spike/shots/phase8-indonesia-selected.png`.
    **Country fires:** `GET /api/v1/overview/fires?days=5` queries FIRMS once
    over `95,-11,141,6`, merges VIIRS and MODIS, assigns each dot once with a
    bbox prefilter + point-in-polygon, caps 80 dots per province, caches for
    2 h and returns `available:false` with a reason instead of a silent zero.
    The client draws world points, shows counts in hover/panel/legend, and a
    dot click opens sensor/time/FRP/confidence with Drone disabled
    (`no survey at this detection`). Live run: 335 dots, 20 provinces.
    **Province plates:** `GET /api/v1/provinces/{code}/imagery?tier=` builds a
    polygon-masked WebP — preview 2048 px (~288 m), detail 2048 px at 59 m over
    a 121 km window. Two STAC pages (recent dates for tile coverage, clearest
    200 over 180 days) are merged into one least-cloudy scene per MGRS tile,
    up to 60 tiles. Alpha is 0 outside the boundary and where no scene has
    signal, so the base shows through rather than a flat colour. Central
    Kalimantan measured 61 % coverage, 49 scenes, 2026-06-13–11-17, ~60 s
    first build, then cached. Detail is requested only by the `59 m detail`
    button and flies to its rectangle; `Recon here` is a disabled stub with
    the coordinates until the mission-scoped recon pipeline exists.
    **Plate limits:** the mesh is a mosaic of dates, not a radiometrically
    matched composite; cloud remains; the tile picker can pick partially
    empty scenes, so `coverage` is the honest number. The detail window is
    centred on the largest polygon (not the bbox), so island provinces do not
    get a 100 % sea window; one unreadable scene is skipped instead of killing
    the build; and a FIRMS source failure with no rows is a stated reason, not
    a silent zero. Every test stays offline
    except the two live sources (FIRMS, STAC), which the routes treat as
    optional.
    Not built: per-province count labels on the globe (counts live in hover and
    the panel), real recon fetch/site model, province-level 3D terrain, 59 m
    for all 38 at build time, place labels/roads/admin-2. The mock showed why
    province imagery is the hard part: 62 % coverage and cloud survive in a
    composite (`spike/shots/province-plate-mock.png`).
    **Globe performance (2026-11-19):** the globe is fill-rate bound, not
    geometry bound — 520 clamped border polylines cost ~0 ms. MSAA is 1 (was 4),
    FXAA is on only in Indonesia, and `resolutionScale` adapts once per entry
    (1 → 0.85/0.75/0.6) by measuring **postRender cadence**, not rAF (rAF fires
    in bursts headless and reported 7 ms while frames took 49 ms). Measured
    49 ms → 32 ms on the test machine; the baseline after slice 1.5 is still
    ~31 ms, and `node spike/web/perf-globe.mjs` now measures with `postRender`
    and isolates the crop layer. Request-render mode for idle heat is still open.
    **Globe interaction:** Cesium's `ScreenSpaceCameraController` is enabled only
    in Indonesia — left-drag rotates, wheel zooms (min 500 km, max 12,000 km) —
    and the custom orbit is disabled there, so other islands can be brought to
    the centre. Hover uses `camera.pickEllipsoid` + point-in-polygon on the
    bundled boundaries, highlights the province and shows its name; the custom
    zoom/reset/2D buttons are adapted, and the compass follows the live camera.
    `node spike/web/check-indonesia.mjs` covers the skin, the LOD threshold,
    hover, zoom, rotate, selection, fly-to, the Esc clear and the return to
    Terrain.
    **2D map (2026-11-20, supersedes the globe):** Indonesia now renders on a
    Canvas 2D map (`map2d.js`), not the globe. The default view contains the
    whole archipelago (94–142E, 12S–8N) and zoom-out stops there. The bundled
    skin is a **wider 88–150E, 20S–10N** Blue Marble crop
    (`skin_satellite.jpg`, fetched by `tools/fetch_indonesia_context.py`;
    relief is graded from it), so panning inside the image always shows real
    texture — no flat sea, feather or vignette. The viewport is clamped inside
    that image. No hover by design; a click still selects a province.
    Drag/wheel/pinch; prebuilt `Path2D` borders, clipped plate and dots. 343
    dots + 520 rings redraw in ~0.1 ms (40-run mean in headless Edge;
    `node spike/web/perf-map2d.mjs` reports ~0.14 ms/draw), and Cesium's render
    loop is parked (`useDefaultRenderLoop=false`) while Indonesia is shown.
    Skins: Relief (graded Blue Marble relief, default), Satellite, Atlas
    (procedural vector), Flat; persisted at the existing key. **Plates are
    hidden on Atlas/Flat**, and a preview below **80 % clear-sky coverage** is
    suppressed too (chip says `hidden (low coverage)`); the explicit 59 m
    detail still draws. The plate composite masks cloud/shadow per pixel with
    the Sentinel-2 SCL band and fills from up to two dates per tile
    (`read_scene_mosaic(fill_once=True)`); Central Kalimantan measures 57 %
    clear-sky because many 2026 COGs are partly NoData, so its preview is
    hidden rather than shown as a patchwork. Cesium remains
    the renderer for Drone/Terrain/Regional. The globe/LOD code is dormant and
    the 3D-terrain idea is dropped. `check-indonesia.mjs` covers skins, the
    whole-country fit, the zoom-out floor, pan bounds, select, plate, detail,
    Esc and Terrain.

---

**Fire-site 3D context and spread (2026-11-21):** `server/providers/site.py`
builds an 18 km site at any province/detection: Copernicus DEM (257²),
Sentinel-2 cloud-masked with a baked DEM hillshade, Open-Meteo weather and a
deterministic `pyroscan-spread-0.1` model. The client opens it from `3D SITE`,
installs a `CustomHeightmapTerrainProvider`, flies an oblique camera, and draws
13 wind/terrain isochrones (0–360 min, 30 min steps) as terrain-clamped
polylines with a play/pause and scrubber. Site controls zoom/reset on the site,
never the mission orbit (this was the “globe” bug). Tested by
`node spike/web/check-site.mjs`: real terrain height, camera controls, spread
advance, back to map. It is terrain/imagery context, not drone photogrammetry.

## 10. Environment

- Python 3.14, FastAPI, uvicorn, requests, numpy, tifffile, Pillow.
- Node 24, Cesium 1.147 (local), Playwright Edge.
- Docker + NodeODM 3.6.2; Ollama 0.40.5 + `qwen3.5:4b-q4_K_M`.
- RTX 4060 Laptop 8 GB; 12 GB host RAM, 6 GB Docker VM.
- ODM requires `dsm: true`; images upload individually, not as a zip.

---

## 11. References

- FireTrace video: `spike/ref/x_video.mp4`; frames in `Docs/references/`
  (`ref-firetrace-3d.jpg`, `ref-firetrace-drones.jpg`, `ref-firetrace-thermal.jpg`).
- X post: https://x.com/DilumSanjaya/status/2108241054298415258
- User references: `ref-chris-dashboard.png`, `ref-modis-fire-map.png`,
  `ref-elevation.png`, `ref-burn-severity.png`,
  `ref-photogrammetry-process.png`.
- Current shell: `ref-pyroscan-paper.png`, `ref-pyroscan-obsidian.png`,
  `ref-pyroscan-recon-paper.png`, `ref-pyroscan-recon-obsidian.png`,
  `ref-pyroscan-theme-menu.png`, `ref-pyroscan-studio.png`,
  `ref-pyroscan-topo.png`.
- Next-agent prompt: `Docs/NEXT_AGENT_PROMPT.md`.
- Provider spec: `Docs/specs/2026-11-16-free-provider-layer-design.md`.
- Modes + spread spec: `Docs/specs/2026-11-17-mission-modes-and-spread-visualization.md`.
- Mode screenshots: `spike/shots/phase4-modes.png` (Drone),
  `phase4-terrain-mode.png` (Terrain via deep link),
  `phase4-regional.png` (Regional before the fix — mosaic only, the evidence for
  the old §9.20).
- Blocker evidence (2026-11-18): `spike/shots/phase5-drone.png` (backdrop
  unchanged), `phase5-terrain-imagery.png` (Sentinel-2 surface),
  `phase5-regional-ring.png` (DEM ring around the mosaic),
  `phase5-offline-fixtures.png` (static-only fallback, no API),
  `diag-regional-baseline.png` / `diag-terrain-baseline.png` (before: 1.35 km
  island on empty background).
- Wide-layer evidence (2026-11-18 later): `phase6-regional-60km.png` (60 km
  mosaic, scale bar `2 km`, badge `60 km · 59 m image · 2 tiles`),
  `phase6-terrain-4km.png` (full 4 km crop, no west clip),
  `phase6-regional-fallback.png` (wide assets absent + gateway offline →
  15 km ring at 3 km), `phase6-drone.png` (unchanged).
- Indonesia slice 1 (2026-11-19): `phase7-indonesia.png` (globe, 38 OSM borders,
  coverage label), `province-plate-mock.png` and
  `province-plate-mock-click.png` (design mock, real FIRMS/imagery, 62 % cover).

---

## 12. Start here

1. Read `Docs/HANDOFF.md` (this file), `Docs/NEXT_AGENT_PROMPT.md`, and
   `Docs/dashboard_design.md`.
2. Start the API with §2's commands. `curl` `/api/v1/missions/latest` and confirm
   `providers.items` lists six keys (weather, fires, DEM, imagery, DEM wide,
   imagery wide).
3. **The two render blockers are fixed** (§9.19–20). Re-run the probe before
   touching Sentinel-2 selection, and keep Drone's backdrop unchanged. If a
   provider refresh fails on this network, check `last_error` before assuming a
   geometry fault.
4. Then the modes spec (`Docs/specs/2026-11-17-mission-modes-and-spread-visualization.md`):
   Phase 3 per-bearing model, Phase 4 growing front, Phase 5 per-source surfaces.
5. Then the DEM chain (§9.22) once licences are checked, and OSM/Photon (provider
   spec Phase 4).
6. Other lanes: YOLO detections, watcher/NodeODM real mission, SSE progress,
   React/Vite port. Keep this file, `README.md` and screenshots in sync.
