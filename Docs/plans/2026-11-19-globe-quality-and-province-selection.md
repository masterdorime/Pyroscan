# Globe Quality, Flat Skin, and Province Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the Indonesia globe look intentional at every zoom (flat skin + a sharper regional LOD) without giving back the performance win, and let a user click a province to select it, fly to it, and read a province panel.

**Architecture:** Three independent client changes on top of the shipped Indonesia slice: a persisted skin toggle (texture vs flat), a second imagery layer used below 2,500 km, and a click/selection state that reuses the existing hover point-in-polygon and Cesium `flyTo` with a rectangle. No provider or data-contract changes; one new build-time image asset.

**Tech Stack:** Cesium 1.147, plain JS, Playwright checks, Python for the build asset.

**Spec:** `Docs/specs/2026-11-19-indonesia-first-province-splice.md`
**Status before this plan:** Indonesia slice 1 shipped (globe, 38 OSM borders, hover, Cesium rotate/zoom, adaptive resolution). Worktree uncommitted.

## Global Constraints

- `Drone`, `Terrain`, `Regional` must behave exactly as today.
- No paid APIs; NASA GIBS / Blue Marble only.
- Everything bundled; no runtime tiles.
- Keep `msaaSamples: 1`, FXAA only in Indonesia, adaptive `resolutionScale`.
- Do not commit unless the user asks.
- Tests: `python -m server.providers.selftest` (94/94), `python -m server.selftest`, `node spike/web/test-terrain-math.mjs`, `node spike/web/check-indonesia.mjs`.

## Review Focus

- Flat skin must not leave a stale texture visible after toggling.
- The LOD layer must not double-draw or pop badly at the threshold.
- A selected province must survive hover and be cleared by Esc/sea click.
- `flyTo` a bbox must not break the camera clamp or the compass.
- Terrain/Regional must not inherit flat skin, the extra layer, or the panel.

---

### Task A: Flat skin toggle (one-colour globe)

**Files:** Modify `spike/web/dashboard.html`, `spike/web/dashboard.css`, `spike/web/dashboard.js`; extend `spike/web/check-indonesia.mjs`.

**Interfaces:**
- Produces `state.globeSkin: 'texture' | 'flat'`, persisted at `localStorage['pyroscan-globe-skin']`.
- Produces `applyGlobeSkin()`; DOM `#globe-skin` with `button[data-skin="texture|flat"]`, visible only in Indonesia.
- Flat: both imagery layers hidden, `globe.baseColor = '#14211c'`; borders + atmosphere unchanged.

- [ ] **Step 1: Failing check** — click `[data-skin=flat]`, expect `state.globeSkin === 'flat'`, `imageryLayers.get(0).show === false`, `globe.baseColor` changed; reload, expect persisted.
- [ ] **Step 2: Run it → fail.**
- [ ] **Step 3: Implement** the control (top-right of the stage, two chips), `applyGlobeSkin()`, persistence, and an image-load error handler that falls back to flat.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Screenshot** `spike/shots/phase8-indonesia-flat.png`.

### Task B: Sharper regional LOD (4096 px Indonesia crop)

**Files:** Create `tools/fetch_indonesia_base.py`; create `spike/web/data/indonesia_blue_marble.jpg`; modify `dashboard.js`; extend the check; add a selftest.

**Interfaces:**
- Asset: 4096×1700 JPEG, GIBS WMS 1.1.1, `LAYERS=BlueMarble_ShadedRelief_Bathymetry`, `BBOX=94,-12,142,8`, ~1.2 km/px.
- `state.indonesiaLayer` added after `state.worldLayer`; `show = indonesia && skin==='texture' && camera height < 2_500_000`.
- Globe minimum zoom becomes **500 km** (from 400 km) until province imagery exists.

- [ ] **Step 1: Failing selftest** — file exists, PIL size `(4096, 1700)`, bytes < 5 MB.
- [ ] **Step 2: Implement the fetch script** (same GIBS params as `tools/fetch_world_image.py`), run it, pass the test.
- [ ] **Step 3: Failing check** — `flyTo` a 300 km-high view; expect the crop layer show true; at 6,000 km expect false; in flat expect false.
- [ ] **Step 4: Implement** the layer + a throttled `postRender` height check that only touches `show` when the boolean changes.
- [ ] **Step 5: Run → pass; screenshot** `phase8-indonesia-lod.png`.

### Task C: Province selection, fly-to, panel

**Files:** Modify `dashboard.html`, `dashboard.css`, `dashboard.js`; extend the check.

**Interfaces:**
- `state.selectedIso: string | null`; `selectProvince(feature|null)`; `applyProvinceStyle()`.
- Panel `#province-panel` (bottom-left, ~300 px) with name, ISO, `area_km2`, a `Clear` button, and the note `Counts and province imagery: next slice`.
- Click: `ScreenSpaceEventHandler` LEFT_CLICK in Indonesia → `camera.pickEllipsoid` → `provinceAt(lon, lat)`; sea click clears.
- Fly: `camera.flyTo({ destination: C.Rectangle.fromDegrees(w,s,e,n) expanded by 8%, duration: 1.4 })`.
- Styling: selected border `PROVINCE_HOVER` width 2; others `PROVINCE_LINE` alpha 0.22 (only while a selection exists); hover keeps its own colour; Esc clears and returns to `MODES.indonesia.camera`.

- [ ] **Step 1: Failing check** — programmatic click at the projected position of 114E 0N; expect `selectedIso === 'ID-KT'`, panel visible and containing `Kalimantan Tengah`, camera height < 3,000,000; Esc clears, panel hidden; Terrain hides it.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** selection, dimming, fly-to, panel, Esc, sea-clear.
- [ ] **Step 4: Run → pass; screenshot** `phase8-indonesia-selected.png`.
- [ ] **Step 5: Verify Terrain/Regional** unchanged (globe off, panel hidden, no flat skin, scale 1).

### Task D: Docs and evidence

- [ ] Update `Docs/HANDOFF.md` §9.26 with the skin, LOD and selection.
- [ ] Update the spec status (Slice 1.5).
- [ ] Allow-list `phase8-*.png` in `.gitignore`.
- [ ] Run all offline tests and the browser check; record results.
- [ ] `git diff` review; no unrelated changes.

## Known traps (do not rediscover)

- Cesium's `globe` Viewer option takes a Globe or `false`, **not `true`**.
- `scene.pickEllipsoid` does not exist — use `viewer.camera.pickEllipsoid`.
- `worldToWindowCoordinates` returns **canvas-relative** coords; add
  `canvas.getBoundingClientRect().left/top` before `page.mouse.move`.
- Measure frame cadence with `scene.postRender`, not `requestAnimationFrame`
  (headless rAF fires in bursts and lies).
- `resolutionScale` changes the backing store; the hover pick must stay in
  CSS/canvas client coordinates.
- 520 clamped polylines; changing materials per hover is fine, but loop only
  the affected iso bucket.
