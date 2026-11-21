# Handoff Prompt — Globe Quality, Flat Skin, Province Selection

You are taking over **PyroScan** at `C:\Users\TRISTAN\PYROSCAN` (Windows,
PowerShell). The previous session shipped an Indonesia globe entry mode. The
user now wants: a one-colour globe skin, a sharper (but still fast) globe, and
click-to-select province with a fly-to and a panel.

Read these first, in order:

1. `Docs/HANDOFF.md` — §9.26 is the current state; §9.19–25 is history.
2. `Docs/specs/2026-11-19-indonesia-first-province-splice.md` — slices 1–4.
3. `Docs/plans/2026-11-19-globe-quality-and-province-selection.md` — **your plan.**
4. `spike/web/check-indonesia.mjs` — the browser test you must extend.
5. `spike/web/perf-globe.mjs` — the performance isolation harness.

**Worktree:** the previous session's work is **uncommitted**. Do not `git
reset`, `checkout`, or revert anything. Do not commit unless the user asks.

## Current state (verified)

- `Indonesia` is the default mode: Cesium globe, NASA Blue Marble 5400×2700,
  38 OSM province borders (520 clamped polylines), atmosphere.
- Cesium's `ScreenSpaceCameraController` is enabled **only** in Indonesia
  (left-drag rotates, wheel zooms, 400 km–12,000 km). The mission modes keep the
  custom orbit.
- Hover uses `camera.pickEllipsoid` + point-in-polygon, highlights the province
  and shows `#province-tip`.
- Performance: MSAA 1, FXAA only in Indonesia, adaptive `resolutionScale`
  (1 → 0.85/0.75/0.6) measured with `scene.postRender`; 49 ms → 32 ms.
- Server: `python -m uvicorn server.api:app --host 127.0.0.1 --port 8000`.
  Dashboard: `http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/indonesia`.
- Data: `server/providers/data/provinces.geojson` (38, ODbL), route
  `/api/v1/provinces.geojson`, base image `spike/web/data/world_blue_marble.jpg`.

## What to build (A → B → C, in order)

### A. Flat skin (one colour)

- `Texture · Flat` segmented control, visible only in Indonesia, at the top-right
  of the stage; persist to `localStorage['pyroscan-globe-skin']`.
- Flat: hide all imagery layers, set `globe.baseColor` to a deep slate-green,
  keep borders + atmosphere. It must look deliberate, not broken.
- Automatic fallback to flat if the base image fails to load.
- Acceptance: toggling is instant, persists across reload, and Terrain/Regional
  are unaffected.

### B. Sharper regional LOD

- `tools/fetch_indonesia_base.py` → `spike/web/data/indonesia_blue_marble.jpg`:
  NASA GIBS WMS 1.1.1, `LAYERS=BlueMarble_ShadedRelief_Bathymetry`,
  `BBOX=94,-12,142,8`, **4096×1700**, JPEG. Use the same request pattern as
  `tools/fetch_world_image.py` (WMS **1.1.1**, SRS/BBOX lon,lat order).
- Add it as a second imagery layer above the global one; show only when
  `indonesia && skin === 'texture' && camera height < 2_500_000`. Toggle `show`
  only when the boolean changes (postRender is every frame).
- Lower the globe minimum zoom to **500 km** (from 400) until province imagery
  exists.
- Acceptance: the crop appears below 2,500 km, disappears above, never in flat;
  no frame regression beyond ~2 ms (measure with `perf-globe.mjs`).

### C. Province selection

- Click a province in Indonesia: select, dim the other 37, fly to its bbox
  (`camera.flyTo` with `Rectangle.fromDegrees(w,s,e,n)` expanded ~8%), and open
  `#province-panel` (bottom-left) with name, ISO, land area and a `Clear` button.
- Panel copy must not invent data: say counts/imagery are the next slice.
- Esc or a sea click clears the selection and returns to the Indonesia camera.
- Hover still works; selection takes precedence. Do not break the 520-entity
  buckets (`state.provinceEntities[iso]`).
- Acceptance: click Central Kalimantan → panel `Kalimantan Tengah`,
  `selectedIso === 'ID-KT'`, camera inside the province; Esc clears; Terrain
  hides the panel.

## Acceptance / definition of done

- `node spike/web/check-indonesia.mjs` extended and green (hover, rotate, zoom,
  flat, LOD, select, fly, clear, return to Terrain).
- `python -m server.providers.selftest` 94/94; `python -m server.selftest`;
  `node spike/web/test-terrain-math.mjs`.
- Screenshots: `spike/shots/phase8-indonesia-flat.png`,
  `phase8-indonesia-lod.png`, `phase8-indonesia-selected.png`; allow-list
  `phase8-*.png` in `.gitignore`.
- `Docs/HANDOFF.md` §9.26 updated; spec status notes Slice 1.5.
- No changes to Drone/Terrain/Regional visuals. No paid APIs. Offline still works.

## Traps already paid for

- Cesium Viewer `globe` option takes a Globe or `false`, **not `true`**.
- `scene.pickEllipsoid` does not exist; use `viewer.camera.pickEllipsoid`.
- `worldToWindowCoordinates` is **canvas-relative**; add the canvas rect before
  Playwright mouse moves.
- Measure with `scene.postRender`, not `requestAnimationFrame` (headless rAF
  fires in bursts: it reported 7 ms while frames took 49 ms).
- `resolutionScale` changes the backing store, not CSS coordinates.
- The globe is fill-rate bound. Do not raise MSAA or add post-process passes to
  "improve quality"; add data at the zoom level instead.
- GIBS WMS 1.3.0 needs a TIME value; use **1.1.1** as the scripts do.

## Report back

For each of A/B/C: what changed, the files, the measured effect (frame time via
`perf-globe.mjs`; before/after), tests run, screenshots, and anything the user
should know in plain language. If a step cannot be done (e.g. GIBS unreachable),
say so instead of faking the asset.
