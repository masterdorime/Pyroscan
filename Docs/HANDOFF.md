# PyroScan — Handoff

**Date:** 2026-11-16
**Repo:** https://github.com/masterdorime/Pyroscan (public, `main`). Raw drone data and the reference video are not committed; the demo DB, mission assets, Cesium bundle, and screenshots are.
**Status: Phase 2 shipped** — provider gateway + BMKG/Open-Meteo weather +
NASA FIRMS regional detections + Copernicus 30 m context terrain, all with
per-provider source/age. Phases 3–5 (Sentinel-2, OSM/Photon, hardening) are
planned, not built. Specs and plans: `Docs/specs/2026-11-16-free-provider-layer-design.md`,
`Docs/plans/2026-11-16-free-provider-layer-phase-1.md`,
`Docs/plans/2026-11-16-free-provider-layer-phase-2.md`.

**Phase 2 measured facts.** A Copernicus tile is 34 MB (Brighton) / 42 MB
(S07 Indonesia). Every remote read transferred the whole object, even for one
pixel, so the adapter downloads once, crops to a 256² ring heightmap, and
deletes the tile. Cached cost is ~700 KB per mission, not the 25 MB the spec
originally budgeted. A ring crossing a 1° cell boundary is clipped and flagged
(`clipped: true`), not mosaicked. Context renders relief over the 1.35 km
mosaic footprint only, anchored so the DEM at the mission centre meets the old
plane — the shape is real, the absolute datum is tied to the mission.

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
dataset (§15.1). Verify the FIRMS parser against a real capture — the committed
CSV is synthetic. The Phase 2 COG gate (§7.5) is **answered**: rasterio installs
on 3.14, but every Copernicus DEM read transfers the whole 34 MB tile, so DEM is
budgeted as one full tile per ring (~68 MB when a ring crosses a 1° cell). Phase
3 must repeat that probe against a Sentinel-2 `visual` COG before assuming
windowed reads.
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
  Obsidian keeps the dark studio. The scene is a flat context basemap, not a
  context DEM.
- **Next: free provider layer (planning).** Indonesia-first, hybrid live
  refresh, mission + 10–25 km regional ring, auto-resolved BMKG `adm4`.
  Planned: BMKG, Open-Meteo, NASA FIRMS, Copernicus DEM, Sentinel-2,
  OSM/Photon. No paid keys. Spec and implementation are **not done**.
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

Server → services: NodeODM REST, Ollama `/api/generate`, Open-Meteo
`/v1/forecast` (cached; optional). **Planned:** BMKG, NASA FIRMS, Copernicus
DEM, Sentinel-2, OSM/Photon via a provider gateway; `/providers` status,
`/regional`, `/context`; per-provider source/age. Prototype minimap uses a
cached Esri image; product path is Sentinel-2 or an offline tile pack.

Data:
- `spike/missions/<id>/heightmap.json` — 384² DSM
- `spike/missions/<id>/ortho.webp` — ortho
- `spike/missions/<id>/ortho_shaded.webp` — hillshaded ortho
- `spike/missions/<id>/spatial_fusion.json`, `advisory.json`
- `spike/web/data/` — terrain/elevation/severity/heat/floor/context assets
- `server/cache/weather.json`
- **Planned:** `server/cache/providers/<mission>/` — provider payloads + metadata

---

## 6. Current dashboard state

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
- **Not implemented:** live cursor coordinate probe/card, provider layers,
  regional FIRMS view, context DEM/imagery, OSM place labels/geocoder.

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

## 8. Free provider layer — planning (not implemented)

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
18. **Provider servers were stopped by a restart.** Start uvicorn/static server
    with the commands in §2 before testing.

---

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
- Provider spec (planned): `Docs/specs/2026-11-16-free-provider-layer-design.md`.

---

## 12. Start here

1. Read `Docs/HANDOFF.md`, `Docs/NEXT_AGENT_PROMPT.md`, and
   `Docs/dashboard_design.md`.
2. Start the API and/or static server with the commands in §2; the previous
   background servers were stopped by a restart.
3. The UI pivot and view revision are complete; review
   `spike/shots/context-paper.png`, `recon-paper.png`, `context-obsidian.png`,
   `recon-obsidian.png`, and `theme-menu-context.png`.
4. **Current task:** execute
   `Docs/plans/2026-11-16-free-provider-layer-phase-1.md` (the spec at
   `Docs/specs/2026-11-16-free-provider-layer-design.md` is approved). Phase 1 =
   provider framework + BMKG/Open-Meteo + FIRMS + source/age.
5. After Phase 1: Phase 2 DEM, Phase 3 Sentinel-2, Phase 4 OSM/Photon, Phase 5
   hardening — each gets its own plan from the same spec.
6. Other lanes after/parallel: YOLO detections, watcher/NodeODM real mission,
   SSE progress, React/Vite port. Keep docs and screenshots in sync.
