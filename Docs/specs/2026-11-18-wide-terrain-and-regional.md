# PyroScan — Wide Terrain and a Real Regional View

**Date:** 2026-11-18
**Status:** Implemented (same day). Measured results in §13a.
**Builds on:** `2026-11-17-mission-modes-and-spread-visualization.md`,
`2026-11-16-free-provider-layer-design.md`
**Related:** `Docs/HANDOFF.md` §9

---

## 1. The problem

Terrain and Regional render the same scene at two zoom levels. Both draw a
1.35 km photo mosaic inside a 15.6 × 30.2 km ring. The only differences are the
camera preset, the zoom clamp and the badge text, so the tabs are redundant.

The reference (`Docs/references/ref-firetrace-3d.jpg`) shows a landscape: imagery
and relief across the whole frame, tens of kilometres wide. Ours shows a
postage stamp of photo on a flat sage sheet.

Two causes, both verified:

- **We draw less than we download.** The Sentinel-2 fetch covers 4 km but the
  drawing box is the 1.35 km `CONTEXT` bbox. The outer 87 % of the asset is
  unused.
- **The ring has no imagery.** It is a hillshade tint only, so everything beyond
  1.35 km reads as blank ground.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Terrain means | local detail | 4 km of 10 m imagery + 30 m DEM, camera 400 m – 8 km |
| Regional means | landscape context | 60 km box, ~60 m imagery + ~120 m DEM, camera 8 – 80 km |
| Regional width | **60 km** centred on the mission | 100 km leaves only 160 m Sentinel-2 pixels; 30 km is not "big" |
| Detail in the middle | unchanged 10 m patch + 10 m mosaic | the drone asset stays the sharpest thing on screen |
| Wide imagery | **mosaic of 2 Sentinel-2 tiles** | the 60 km box crosses the 15TWM/15TWN edge (see §3) |
| Wide DEM | **mosaic of 4 Copernicus 1° tiles** | the mission is 0.4 km from its tile's west edge |
| Missing wide asset | keep today's ring (hillshade, 15 km) | a fetch failure must never regress the scene |
| Scale | visible scale bar in Regional | "big" must be measurable, not implied |

## 3. Coverage arithmetic (Brighton)

Mission centre: `46.842679 N, 91.993977 W`.

A 60 km box is ±30 km:

- latitude `46.5732 … 47.1119`
- longitude `92.3880 … 91.6001`

Data required:

- **DEM:** floor-lat 46/47 × floor-lon −93/−92 → `N46W093, N46W092, N47W093,
  N47W092`. The current adapter reads one tile and clips, which is why the ring
  is only 15.6 km wide.
- **Imagery:** the box crosses the north edge of `15TWM` (11.8 km from the
  mission) into `15TWN`. One scene cannot cover it. A single-scene box is capped
  at ~24 km, barely larger than today's ring — so the wide layer must mosaic two
  scenes.

## 4. Data plan

Measured on the live COGs (2026-11-18):

| Asset | Source | Overview used | Target | Transfer |
|---|---|---|---|---|
| Wide DEM | Copernicus 30 m, 4 tiles | 120 m | 256² | ~1 MB |
| Wide imagery | Sentinel-2 TCI, 2 tiles | 80 m | 1024² | ~2–4 MB |
| Local imagery | existing 4 km asset | 10 m | 1024² | 0 (cached) |

- DEM tiles are EPSG:4326, so the mosaic needs no reprojection: intersect the
  requested box with each 1° tile, read that window decimated, and place it in
  the output grid by proportion.
- Sentinel-2 tiles are EPSG:32615 for both 15TWM and 15TWN: transform the box to
  UTM once, then clip per tile.
- Each tile read requests an `out_shape`, so GDAL serves overviews instead of
  full resolution. This is what keeps 60 km affordable.

### 4.1 Scene pairing

The wide imagery needs one scene per tile. Picking the least cloudy scene in each
tile independently can pair October with November and produce a visible colour
seam.

Rule: pick a **target date** (the least cloudy scene over the mission tile), then
for every required tile choose the least cloudy scene within ±14 days of it.
Record every scene id and date in the payload. If no scene is within the window,
fall back to the least cloudy available and widen the reported date range.

Payload therefore describes a mosaic, not a scene:

```json
"imagery_wide": {
  "bbox": {...}, "window_km": 60, "resolution_m": 60, "size": 1024,
  "scenes": [
    {"tile": "15TWM", "scene_id": "S2B_15TWM_20261002_0_L2A", "acquired_at": "...", "cloud_pct": 0.0001},
    {"tile": "15TWN", "scene_id": "S2C_15TWN_20261010_0_L2A", "acquired_at": "...", "cloud_pct": 0.012}
  ],
  "date_range": ["2026-10-02", "2026-10-10"],
  "attribution": "Contains modified Copernicus Sentinel data"
}
```

## 5. Providers and API

- `copernicus_dem` gains `window_km`, `size`, `key` and `asset` parameters so one
  adapter serves a local and a wide instance. The local instance keeps today's
  behaviour and asset name.
- `sentinel2` gains `read_scene_mosaic(...)`; the existing `read_scene_window`
  stays for the detail asset. A second provider instance writes
  `context_imagery_wide.webp` with its own envelope, TTL and fallback.
- New keys: `context_dem_wide`, `context_imagery_wide`.
- New routes: `/context/dem_wide`, `/context/imagery_wide.webp`.
- `latest`/`{id}` gain `imagery_wide`; `providers.items` carries both rows with
  their own status, age and detail.
- `prefetch --only` accepts the new keys.

## 6. Scene and modes

- **Terrain:** draw the full 4 km crop (already cached) and extend the context
  mesh to 4 km. Local ring unchanged. Camera 400 m – 8 km, preset 2 km / −30°.
- **Regional:** 60 km wide ring textured with the wide mosaic, with the local
  patch and mosaic on top. Camera 8 – 80 km, preset 25 km / −35°.
- Ring meshes are per-mode: Local ring in Terrain, wide ring in Regional. Two
  overlapping surfaces at different resolutions would z-fight.
- A scale bar (0–10 km, adapting) sits bottom-left in Regional.
- Badges read from the payload: `30 m DEM · 4 km image` and
  `60 km · 60 m image · 2 tiles`. Dates and tile count come from the payload,
  never hardcoded.

## 7. Fallbacks and offline

1. Wide imagery missing → wide ring falls back to the DEM hillshade.
2. Wide DEM missing → Regional falls back to today's 15 km ring; the badge says
   `15 km ring — wide fetch failed`.
3. No network at all → cached assets render, ages shown; the static fixture shell
   keeps working with no wide layer.
4. A failing refresh never blanks a surface that has a cache.

## 8. Honesty

- Regional imagery is ~60 m, not 10 m. The badge and legend say so.
- A mosaicked layer reports its scene count and date range; if the range is wider
  than 14 days the badge appends `multi-date`.
- The 143 m mission patch is ~2 px at 60 km. Regional marks the site with the
  existing label; it does not pretend the survey is visible.
- Terrain never claims 10 m beyond its 4 km box.

## 9. Performance

- One extra texture (1024²) and one extra mesh (128²) on the GPU.
- Both are built once after their fetch resolves; no per-frame work.
- Target: Regional p95 under 33 ms at 1600×900 on the existing test machine.

## 10. Tests (offline)

- `square_extent`: 60 km box is centred and 60 km across in both axes.
- DEM mosaic: four synthetic 1° tiles → full coverage, correct placement, seams
  land on tile boundaries, missing tile flagged `clipped`.
- DEM mosaic reads decimated (`out_shape`) — asserted by output shape and by a
  fixture whose full-resolution values are only visible when decimation is
  requested.
- Scene pairing: picks the within-window scene per tile; widens the range and
  flags `multi-date` when it cannot.
- Wide provider: asset name, bbox, resolution, scene list, envelope.
- Texture registration: the 60 km box maps to the wide image's uv rectangle
  (extend `terrain-math.js` test).
- API: wide assets appear only when cached; providers list both rows.
- Browser: Regional at 60 km with the wide layer; Regional with the wide asset
  removed (hillshade fallback); Drone unchanged; static fixture shell.

## 11. Out of scope

- Sun, shadows, atmosphere and horizon haze (the reference's lighting).
- Place labels, roads, admin boundaries.
- FIRMS dots on the map, wind field, per-bearing spread.
- Multi-mission or multi-date browsing UI.
- Replacing the 30 m DEM with a finer chain.

## 12. Risks

1. **Network.** The wide fetch is 2–4 MB; this link runs at ~35 KB/s and can hit
   the GDAL timeout. Mitigation: read overviews only, keep the old surface as the
   fallback, prefetch on a better connection, and report the failure instead of
   hiding it.
2. **Date seam.** Two tiles, possibly two dates. Mitigation: ±14 day pairing and
   an explicit date range.
3. **A 60 km plate still is not the reference.** Without lighting and atmosphere
   it reads as a tilted map, not a landscape. Mitigation: be explicit that this
   slice buys coverage and registration, not atmosphere.
4. **Memory.** A 1024² texture plus meshes is small, but the heightmaps ship as
   JSON; keep the wide DEM at 256² (~712 KB) rather than 512² (~2.8 MB).

## 13. Slices

- **A — free local detail.** Draw the full 4 km crop; extend the local mesh;
  Terrain preset, clamp, badge and scale bar. No new downloads.
- **B — wide Regional.** DEM mosaic, wide imagery mosaic, wide ring, Regional
  preset/clamp/badge, prefetch, tests. Falls back to A's ring when a fetch fails.

A ships first and is verifiable on its own; B follows without changing A's
contract.

## 13a. What actually shipped (2026-11-18)

- **Terrain:** draws the full 4 km crop. The local DEM provider now mosaics two
  Copernicus tiles, so the old west-edge clip is gone and the badge reads
  `30 m · 4 km image`. Preset 1.2 km / −30°, clamp 400 m – 8 km.
- **Regional:** 60 km box, 4 DEM tiles (100 % coverage, no clip) and 2 Sentinel-2
  scenes (`15TWM` 2026-10-02 + `15TWN` 2026-10-10, 8 days apart, mosaic coverage
  1.0). Measured downloads: wide DEM ≈ 1.0 MB JSON, wide imagery ≈ 0.3 MB WebP.
  Preset 25 km / −35°, clamp 8 – 80 km. Scale bar reads `2 km` at the preset.
- **Honesty:** badge `60 km · 59 m image · 2 tiles`, legend lists both scene dates,
  scale bar is measured at the target distance.
- **Fallback verified** with the wide assets removed and the gateway offline:
  Regional returns to the 15 km ring at 3 km, badge `15 km ring`, no error.
- **Tests:** 91/91 provider cases, pipeline selftest, terrain-math node test.
- **Known:** a faint tonal seam remains where the two imagery dates meet (no
  radiometric matching is done). The wide surface is flat-shaded; no sun or
  atmosphere. Both are recorded in `Docs/HANDOFF.md` §9.
