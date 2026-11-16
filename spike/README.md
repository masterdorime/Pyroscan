# PyroScan feasibility spike — photogrammetry + Cesium

## Verdict: both halves work

NodeODM turned the Brighton Beach set into a georeferenced orthophoto, DSM and
textured GLB, and Cesium rendered the real ortho + DSM offline with a hotspot
pin and vector arrow.

| Metric | Value |
|---|---|
| Images submitted / reconstructed | 18 / 18 (**100%**) |
| Reprojection error | 1.08 px |
| GSD | 1.64 cm/px |
| First full run (CPU, 20 cores) | 507 s (8.5 min) |
| Restart with DSM (cached stages) | 127 s |
| Orthophoto | 6505 × 6152 RGBA, 2 cm/px |
| DSM | 2 cm/px, 153.5–174.2 m |
| Textured GLB | 14.2 MB |
| Cesium p95 (256x256 mesh, 4096 WebP) | ~35 ms, 0 external requests |

Evidence: `spike/shots/track-b-real-3.png`, `spike/data/c16574ae-*/odm_report/stats.json`.

## Findings that change the docs

1. **ODM 3.6.2 does not generate a DEM by default.** It logs
   `DEM will not be generated` unless `dsm` or `dtm` is set. FR-SRV-02's option
   list is missing this; the pipeline must send `dsm: true` (surface) or
   `dtm: true` (ground).
2. **`CustomHeightmapTerrainProvider` renders a skirt pedestal at 100 m scale.**
   Cesium closes tile edges to the ellipsoid, so a 140 m patch becomes a tower.
   Rendering the DEM as a **mesh primitive** with the globe hidden works and
   matches the PRD's existing `mesh.glb` plan. FR-DSH-01 should change.
3. **Preserve the orthophoto alpha channel.** Converting ODM's RGBA ortho to RGB
   makes the reconstruction footprint render as black wedges.
4. **CPU misses the 4-minute KPI**: 18 photos took 8.5 min. The target is 30
   photos on GPU, which is still untested. Docker has 6 GB of the host's 12 GB
   RAM — below the PRD's 16/32 GB baseline.

## Reproduce

```powershell
# NodeODM (CPU)
docker run -d --name nodeodm -p 3000:3000 -v C:\Users\TRISTAN\PYROSCAN\spike\data:/var/www/data opendronemap/nodeodm

# options must be a JSON array of {name,value}
# [{"name":"use-exif","value":true},{"name":"gps-accuracy","value":15},
#  {"name":"resize-to","value":2000},{"name":"feature-quality","value":"medium"},
#  {"name":"pc-quality","value":"medium"},{"name":"orthophoto-resolution","value":2},
#  {"name":"dsm","value":true},{"name":"dem-resolution","value":2}]

python spike\tools\make_odm_assets.py
python -m http.server 8080 --directory spike/web
```

GPU is visible inside Docker (`nvidia/cuda` test passed, RTX 4060 8188 MiB), but
`opendronemap/nodeodm:gpu` has not been benchmarked yet.

## Live pipeline

The rail now reads SQLite instead of fixtures:

```powershell
python -m server.import_mission
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/dashboard.html
```

The 8080 static page still works as a fixture fallback. Endpoints, deviations
and known gaps: `server/README.md`.

## Dashboard shell (design prototype)

Open `http://127.0.0.1:8080/dashboard.html` with the server command above.

- 3D mission console: free orbit, cached basemap, real ortho/DSM.
- **Context default:** cached basemap + area-equivalent mission disc + hotspot
  pins + `Open reconstruction`; patch/heat/prediction/flight/base controls
  hidden. Click footprint/hotspot/pill or zoom ≤220 m to open Reconstruction.
- **Reconstruction:** patch + base/overlays; camera 220 m / -30°; `Context`
  pill, minimap, or zoom ≥380 m returns.
- **Base surface** (reconstruction): Terrain, Elevation, Shaded ortho, Burn
  severity — one at a time.
- **Presets**: Terrain / Fire / Forecast / Burn.
- **Overlays** (reconstruction): Heat, Wind, Prediction, Hotspots, Flight.
- Right rail: **Layers / Mission / Advisory / Weather**, persistent severity.
- Forecast strip: now → +60 min, burned area, rate of spread, N–S elevation
  profile, key events.
- Real: ortho, DSM, shaded ortho, bright context. Fixtures marked **SIMULASI**.
- Paper: bright 1.35 km context mosaic (opaque centre + alpha ring) + haze;
  obsidian: dark studio floor + grid. Context stays bright in both themes.
- **Paper/obsidian skin (Steps 1–4)**: paper default with a persisted top-bar
  theme dropdown; incident header + card rail; elevation profile; bright
  landscape. Obsidian keeps the dark studio.
- Measured at 1600×900: Context p50 14 / p95 21 ms; Reconstruction p50 21 /
  p95 28 ms; HUD 20–28 ms on Intel UHD. The 33 ms target is met in this run;
  0 external requests.
- Design spec and reference gallery: `Docs/dashboard_design.md`.

## Files

```
spike/data/brighton_beach/           18 photos + published DSM
spike/data/c16574ae-*/               full ODM project (ortho, DSM, GLB, stats)
spike/tools/make_odm_assets.py       ODM -> heightmap.json + ortho.webp
spike/tools/make_dashboard_assets.py elevation/severity/heat + shaded ortho + paper variants
spike/web/dashboard.html/.css/.js    mission console shell
spike/web/data/elevation.png         topographic base (hillshade + contours)
spike/web/data/terrain_base.webp     hybrid terrain (photo + contours)
spike/web/data/severity_base.png     5-class severity base
spike/web/data/ortho_shaded.webp     hillshaded orthophoto
spike/web/data/context_bright.png    graded 1.35 km bright context
spike/web/data/*_paper.*             feathered paper base variants
spike/web/data/studio_floor.png      dark floor + grid (obsidian)
spike/web/data/context_near.jpg      minimap context crop
spike/web/data/shadow.png            contact shadow
spike/web/data/fixtures.json         mission + fixture layers
spike/web/data/context.jpg           cached offline basemap
spike/web/index.html                 offline Cesium mesh viewer + p95 HUD
spike/web/shot.mjs                   Playwright screenshot + console capture
spike/shots/                         evidence
```

