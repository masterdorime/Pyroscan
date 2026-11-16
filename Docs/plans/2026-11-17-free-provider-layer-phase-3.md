# Free Provider Layer — Phase 3 (Sentinel-2 Imagery) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the Esri prototype basemap with real Sentinel-2 L2A context imagery, fetched over the measured COG path, cached per mission, and labelled with its scene date and cloud cover.

**Architecture:** A STAC search (Earth Search, keyless) picks the least-cloudy scene touching the ring in the last 90 days. One windowed read of its `TCI.tif` (true colour, 10 m) is reprojected to the ring bbox and resized to 1024², then encoded to WebP and cached beside the envelope. The dashboard swaps its context texture when an image exists and otherwise keeps today's mosaic.

**Tech Stack:** Python 3.14, `requests`, `rasterio` 1.5.2, `numpy`, Pillow (all present). Cesium dashboard, plain JS.

**Spec:** `Docs/specs/2026-11-16-free-provider-layer-design.md` §5.4, §7.5 (corrected), §11.1, §12, §13 Phase 3

## Global Constraints

- Keyless only. Earth Search STAC and the `sentinel-cogs` bucket need no account.
- Windowed reads only: a 1.2 km window measured 1.46 MB, a 25 km window 15.95 MB. Never download a full `TCI.tif` (290–330 MB).
- Reuse the Phase 1 envelope/cache/gateway unchanged. One asset per key, written through `extra`.
- Imagery is context, never reconstruction. Show the scene date and cloud cover; never imply the imagery and the drone patch share a capture.
- The dashboard keeps working with no imagery, no cache and no network: the existing mosaic stays the fallback, and its Esri attribution stays with it.
- All times UTC ISO-8601 with `Z`. Tests run offline; STAC and raster reads are injected.

## Review Focus

1. **Scene older than the ring's interest.** A 60-day-old scene is a correct answer, not a bug — but it must be dated. Expected: `acquired_at` surfaced and rendered, never a bare "Sentinel-2". → Task 4.
2. **No scene under the cloud threshold in 90 days.** Expected: `unavailable`/`no_usable_scene`, the previous cache still served if present, the old mosaic otherwise. Never a blank context. → Task 2.
3. **Antimeridian/UTM zone edge.** The tile is EPSG:326xx; passing degrees to `from_bounds` yields a 0×0 window (this actually happened during the gate). Expected: bounds reprojected, and a non-empty window asserted. → Task 3.
4. **Cloud mask absence.** `eo:cloud_cover` is scene-level; a 1 % scene can still be cloudy over the mission. Expected: imagery is labelled with the scene figure and not described as clear over the site. → Task 4.
5. **A 1024² WebP of a 25 km ring implies ~24 m/px.** Expected: `resolution_m` reports the source (10) and the UI says "10 m source", not "10 m shown". → Task 4.

---

## File Structure

| Path | Responsibility |
|---|---|
| `server/providers/sentinel2.py` | STAC search, scene choice, windowed read, WebP asset, adapter |
| `server/providers/fixtures/sentinel2/search.json` | Trimmed real STAC response |
| `server/providers/registry.py` | Register `context_imagery` |
| `server/api.py` | `/context/imagery.webp`, `assets.context_imagery` |
| `spike/web/dashboard.js` | Use the S2 texture when present, label it, keep the fallback |
| `README.md`, `server/README.md`, `Docs/HANDOFF.md` | Attribution split, status |

---

### Task 1: STAC search and scene choice

- Create `server/providers/sentinel2.py`; test in `selftest.py`.
- Produces: `search_scenes(extent, *, days=90, limit=10, poster=None) -> list[dict]`; `pick_scene(features, *, max_cloud=40.0) -> dict | None` returning `{"scene_id", "acquired_at", "cloud_pct", "href"}`.
- Test: a committed real response yields a scene with `cloud_pct` and a `.tif` href; a fixture where every scene exceeds `max_cloud` yields `None`; `acquired_at` ends with `Z`.
- Step 1: capture one real search response into `fixtures/sentinel2/search.json` (Brighton, 90 days, sorted by cloud). Step 2: write the failing tests. Step 3: implement. Step 4: `python -m server.providers.selftest s2_picks_the_least_cloudy_scene s2_returns_none_when_all_scenes_are_cloudy`. Step 5: commit.

### Task 2: Adapter skeleton with honesty states

- Modify `sentinel2.py`, `registry.py`.
- Produces: `Sentinel2Provider(*, reader=None, size=1024)` with `id="sentinel-2"`, `key="context_imagery"`, `ttl_s=259_200`, `fetch_timeout_s=45`, `allow_inline=False`, `requires=()`.
- No scene → `raise ProviderError("missing", "no_usable_scene")`; STAC failure → `ProviderError("network"|"parse", ...)`.
- Test: no usable scene raises kind `missing` with detail `no_usable_scene`; the gateway reports `unavailable`. Register and assert `build_registry` contains `context_imagery`.
- Commit.

### Task 3: Windowed read and reprojection

- Modify `sentinel2.py`.
- Produces: `read_scene_window(source, extent, *, size) -> numpy.ndarray` (H×W×3 uint8), reprojecting the ring bbox from EPSG:4326 into the dataset CRS with `rasterio.warp.transform_bounds`.
- Test: build a small UTM tile with `rasterio` (EPSG:32615, 10 m, 3 bands) around a known point; assert the returned array is non-empty, `(size, size, 3)`, and that a degree/UTM mix-up would be caught by asserting `shape[0] > 0`.
- Commit.

### Task 4: WebP asset, payload, and endpoint

- Modify `sentinel2.py`, `api.py`; test in `selftest.py`.
- Produces: payload per spec §5.4 (`bbox`, `asset`, `scene_id`, `acquired_at`, `cloud_pct`, `resolution_m`, `bands`), `asset_name="context_imagery.webp"`; `GET /api/v1/missions/{id}/context/imagery.webp`; `assets.context_imagery` when the file exists.
- Test: encoding produces bytes starting `RIFF`/`WEBP`, Pillow can reopen them, and the payload carries `resolution_m: 10` plus the scene date; the endpoint returns the asset path only when cached.
- Commit.

### Task 5: Dashboard swap with fallback

- Modify `spike/web/dashboard.js`.
- `loadContextImagery(live)` sets `state.contextImageryUrl`; both `buildLandscape` and `buildContextTerrain` use it as the material image when set, otherwise `data/context_bright.png`. Live-data row reads `Sentinel-2 · {scene date} · {cloud}% cloud · 10 m source`.
- Browser check: with imagery cached, screenshot paper and obsidian; with the asset deleted, confirm the old mosaic and the Esri attribution return and no console error.
- Commit.

### Task 6: Docs, offline proof, storage

- Update attribution split (Sentinel-2 when shown, Esri when falling back), status, storage table (imagery ~200–600 KB WebP), and the Phase 3 gate outcome.
- Measure cache size; run the full suite; push.
- Commit.

## Self-Review

Spec coverage: §5.4 → Tasks 3–4; §7.5 corrected measurement → Tasks 3/6; §11.1 row → Task 5; §12 storage → Task 6; §13 Phase 3 → all.

Deviation to note: the spec says Phase 3 "replaces the Esri context mosaic". This plan keeps the mosaic as a fallback rather than deleting it, because the offline guarantee outranks the licensing tidy-up. Attribution therefore becomes conditional, which is more work than deleting Esri outright but does not regress the offline path. If the imagery proves reliable across a few missions, removing the fallback becomes a one-line follow-up.
