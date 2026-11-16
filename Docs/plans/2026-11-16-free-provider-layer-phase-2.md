# Free Provider Layer — Phase 2 (Copernicus DEM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Context view real 30 m terrain from Copernicus DEM, cached per mission, exposed as `/context/dem`, with the same source/age discipline as Phase 1.

**Architecture:** One adapter downloads the single 1° Copernicus cell containing the ring centre, crops and resamples it to a 256² heightmap in the mission's own format, writes it beside the envelope, and deletes the tile. Context rendering builds a coarse Cesium mesh from that heightmap under the existing bright imagery. When no DEM is cached, Context keeps today's flat plane.

**Tech Stack:** Python 3.14, `rasterio` 1.5.2 (cp314 wheel, installed and measured), `requests`, numpy. Dashboard is plain JS + Cesium 1.147, already bundled.

**Spec:** `Docs/specs/2026-11-16-free-provider-layer-design.md` (§5.3, §7.5 — answered — §11.1, §12, §13 Phase 2)

## Global Constraints

- No paid API or key. Copernicus DEM is AWS Open Data, keyless.
- Never transfer more than the measured budget: one tile ≈ 34 MB per ring. `max_tiles` is 1 in this phase; crossing a cell boundary clips and is labelled, it does not mosaic.
- Download to a temp file, read locally with rasterio, delete the temp file in a `finally`. Never hold a 3600² array longer than the crop.
- Context DEM is 30 m. It is never merged into the mission patch, never described as reconstruction, and never compared to the drone DSM as if they shared an accuracy.
- `derive()` status rules, the envelope shape, and the fixture-fallback rules from Phase 1 are unchanged. Reuse `Gateway`, do not fork it.
- The dashboard must keep working with no DEM, no cache, and no network. The flat context plane is the permanent fallback.
- All times UTC ISO-8601 with `Z`.
- Tests run with **no network**. A synthetic GeoTIFF is written with rasterio into a temp dir; the adapter's tile fetcher is injected.
- Do not change the Context → Reconstruction flow, camera thresholds, or the mission patch.

## Review Focus

Five input classes the spec implies but no task's tests otherwise pin down. Each gets a test in the owning task.

1. **Ring crossing a 1° cell boundary.** The single-tile rule means the crop is smaller than the ring. Expected: `clipped: true` in the payload, a smaller `bbox`, and the UI saying "30 m context (clipped)". Silent truncation would make the terrain quietly stop at the mission edge. → Task 3.
2. **Southern and western hemispheres.** Tile names use `S`/`W` with zero-padded degrees. A sign error silently fetches the wrong part of the planet, or 404s. Expected: `S06`/`W092`, and the equator/prime-meridian cases resolve to the correct cell. → Task 1.
3. **No-data sentinels inside a tile.** Copernicus tiles carry `nodata` (often `-32767`) and ocean gaps. Feeding that into a heightmap produces a −32 km spike or a black hole in the mesh. Expected: sentinel and NaN values are excluded from `h_min`/`h_max`, replaced by the tile median, and counted in `nodata_px`. → Task 2.
4. **A failed or partial tile download.** A truncated temp file must never be cropped or cached as if complete. Expected: byte-count check against `Content-Length`, temp deleted, `ProviderError("network"|"http")`, and no asset written. → Task 2.
5. **DEM arriving while the dashboard is open.** The adapter is `allow_inline = False`, so the first Context load returns `unavailable`/`warming`. Expected: the page keeps the flat plane, the Live-data row says "fetching…", and a reload picks up the terrain — no console error, no blank scene. → Task 6.

---

## File Structure

**Create**

| Path | Responsibility |
|---|---|
| `server/providers/copernicus_dem.py` | Cell naming, tile fetch, crop/resample, adapter |
| `server/providers/fixtures/copernicus_dem/README.md` | Provenance note for the synthetic fixture |
| `Docs/plans/` (this file) | — |

**Modify**

| Path | Change |
|---|---|
| `server/providers/registry.py` | Register `context_dem` |
| `server/api.py` | `/context/dem`; `assets.context_dem`; summary already generic |
| `spike/web/dashboard.js` | Context terrain mesh + fallback; Live-data row needs no code |
| `spike/web/dashboard.css` | Nothing unless the clipped note needs a style |
| `README.md`, `server/README.md`, `Docs/HANDOFF.md` | Status, rasterio dependency, storage |

`cache.write_asset` already accepts dotted names (fixed after Phase 1).

---

### Task 1: Cell naming

**Files:**
- Create: `server/providers/copernicus_dem.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Consumes: `Extent`, `ProviderError`.
- Produces: `tile_name(lat: float, lon: float) -> str`; `tile_url(name: str) -> str`; `cell_bounds(name: str) -> tuple[float, float, float, float]` returning `(west, south, east, north)`.

Copernicus naming: `Copernicus_DSM_COG_10_N46_00_W092_00_DEM`. One cell per integer degree; the name encodes the **south-west** corner. Base URL `https://copernicus-dem-30m.s3.amazonaws.com/<name>/<name>.tif`.

- [ ] **Step 1: Write the failing tests**

```python
@case
def dem_tile_name_hemispheres():
    from server.providers.copernicus_dem import tile_name
    assert tile_name(46.84, -91.99) == "Copernicus_DSM_COG_10_N46_00_W092_00_DEM"
    assert tile_name(-6.91, 107.60) == "Copernicus_DSM_COG_10_S07_00_E107_00_DEM"
    assert tile_name(0.4, 0.4) == "Copernicus_DSM_COG_10_N00_00_E000_00_DEM"
    assert tile_name(-0.4, -0.4) == "Copernicus_DSM_COG_10_S01_00_W001_00_DEM"


@case
def dem_cell_bounds_round_trip():
    from server.providers.copernicus_dem import cell_bounds, tile_name
    west, south, east, north = cell_bounds("Copernicus_DSM_COG_10_N46_00_W092_00_DEM")
    assert (west, south) == (-92.0, 46.0)
    assert (east, north) == (-91.0, 47.0)
    assert tile_name(46.5, -91.5) == "Copernicus_DSM_COG_10_N46_00_W092_00_DEM"


@case
def dem_tile_url_is_keyless():
    from server.providers.copernicus_dem import tile_name, tile_url
    name = tile_name(46.84, -91.99)
    url = tile_url(name)
    assert url.startswith("https://copernicus-dem-30m.s3.amazonaws.com/")
    assert url.endswith(f"/{name}/{name}.tif")
    assert "?" not in url and "key" not in url.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest dem_tile_name_hemispheres`
Expected: `ModuleNotFoundError: No module named 'server.providers.copernicus_dem'`.

- [ ] **Step 3: Implement naming**

`tile_name` uses `math.floor` on both coordinates so a negative fraction belongs to the cell below zero (`-0.4` → `-1` → `S01`), builds `N`/`S` and `E`/`W` from that floored value, zero-pads to two digits, and returns the pattern above. Truncation would silently send `-0.4` to `S00`, a cell that does not contain the point. `cell_bounds` parses the name back to `(west, south, east, north)`. `tile_url` is pure string formatting.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest dem_tile_name_hemispheres dem_cell_bounds_round_trip dem_tile_url_is_keyless`
Expected: `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/copernicus_dem.py server/providers/selftest.py
git commit -m "feat(providers): Copernicus DEM cell naming"
```

---

### Task 2: Tile fetch with a byte check

**Files:**
- Modify: `server/providers/copernicus_dem.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Produces: `fetch_tile(name: str, dest: Path, *, timeout: int = 45, max_bytes: int = 80_000_000, getter=None) -> Path`.

`getter` defaults to `requests.get` and exists so tests never touch the network. The function streams to `dest`, enforces `max_bytes`, and verifies the received length against `Content-Length` when the server provides one.

- [ ] **Step 1: Write the failing tests**

```python
class _StreamResp:
    def __init__(self, chunks, length=None, status=200):
        self._chunks = chunks
        self.status_code = status
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def iter_content(self, size):
        yield from self._chunks


@case
def dem_fetch_rejects_truncated_tile():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    try:
        fetch_tile("X", dest, getter=lambda *a, **k: _StreamResp([b"abc"], length=100))
    except ProviderError as e:
        assert e.kind == "network"
        assert not dest.exists()
        return
    raise AssertionError("accepted a short read")


@case
def dem_fetch_enforces_byte_cap():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    big = [b"x" * 1024] * 100
    try:
        fetch_tile("X", dest, max_bytes=4096, getter=lambda *a, **k: _StreamResp(big))
    except ProviderError as e:
        assert e.kind == "http"
        assert not dest.exists()
        return
    raise AssertionError("exceeded the cap without raising")


@case
def dem_fetch_writes_complete_tile():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import fetch_tile
    dest = Path(tempfile.mkdtemp()) / "tile.tif"
    out = fetch_tile("X", dest, getter=lambda *a, **k: _StreamResp([b"ab", b"cd"], length=4))
    assert out.exists() and out.read_bytes() == b"abcd"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest dem_fetch_rejects_truncated_tile`
Expected: `ImportError: cannot import name 'fetch_tile'`.

- [ ] **Step 3: Implement `fetch_tile`**

Check `status_code >= 400` first (`ProviderError("http", ...)`). Stream chunks to `dest`, accumulating a counter; on `counter > max_bytes` abort with `ProviderError("http", "tile exceeds byte cap")`. After the loop, when `Content-Length` was present and differs from `counter`, raise `ProviderError("network", "short read")`. Any raise must `dest.unlink(missing_ok=True)` before propagating, including on the base exception.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest dem_fetch_rejects_truncated_tile dem_fetch_enforces_byte_cap dem_fetch_writes_complete_tile`
Expected: `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/copernicus_dem.py server/providers/selftest.py
git commit -m "feat(providers): streamed DEM tile fetch with byte and length checks"
```

---

### Task 3: Crop and resample to a ring heightmap

**Files:**
- Modify: `server/providers/copernicus_dem.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Produces: `crop_dem(tile_path: Path, extent: Extent, size: int = 256) -> dict` returning `{"heightmap": <mission-format dict>, "clipped": bool, "nodata_px": int, "bbox": {...}}`.

The heightmap dict is exactly the mission shape: `mission_id` (literal `"context"`), `width`, `height`, `west`, `south`, `east`, `north`, `height_scale_m` (1.0), `geoid_offset_m` (0.0), `base_height_m` (0.0), `h_min`, `h_max`, `heights_m` (row-major floats).

- [ ] **Step 1: Write the failing test**

```python
def _synthetic_dem(path, value=200.0, nodata=None, size=120,
                   bounds=(-92.0, 46.0, -91.0, 47.0)):
    import numpy as np, rasterio
    from rasterio.transform import from_bounds
    data = np.full((size, size), value, dtype="float32")
    if nodata is not None:
        data[size // 2, size // 2] = nodata
    profile = {"driver": "GTiff", "height": size, "width": size, "count": 1,
               "dtype": "float32", "crs": "EPSG:4326", "tiled": True,
               "blockxsize": 64, "blockysize": 64,
               "transform": from_bounds(*bounds, size, size)}
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as ds:
        ds.write(data, 1)


@case
def dem_crop_returns_ring_heightmap():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path, value=250.0)
    e = mission_extent({"west": -91.50, "south": 46.50, "east": -91.495, "north": 46.505}, 5)
    out = crop_dem(path, e, size=64)
    hm = out["heightmap"]
    assert hm["width"] == 64 and hm["height"] == 64 and hm["mission_id"] == "context"
    assert len(hm["heights_m"]) == 64 * 64
    assert hm["h_min"] == hm["h_max"] == 250.0
    assert out["clipped"] is False


@case
def dem_crop_reports_clipping_at_a_cell_edge():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path)
    # ring centred on the -92.0 edge, so half of it falls outside this cell
    e = mission_extent({"west": -92.01, "south": 46.84, "east": -91.99, "north": 46.86}, 5)
    out = crop_dem(path, e, size=64)
    assert out["clipped"] is True
    assert out["bbox"]["west"] >= -92.0


@case
def dem_crop_excludes_nodata_from_the_range():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import crop_dem
    path = Path(tempfile.mkdtemp()) / "tile.tif"
    _synthetic_dem(path, value=250.0, nodata=-32767.0)
    e = mission_extent({"west": -92.0, "south": 46.0, "east": -91.0, "north": 47.0}, 5)
    out = crop_dem(path, e, size=64)
    assert out["heightmap"]["h_min"] >= 0
    assert out["nodata_px"] >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest dem_crop_returns_ring_heightmap`
Expected: `ImportError: cannot import name 'crop_dem'`.

- [ ] **Step 3: Implement `crop_dem`**

Open with `rasterio.open` (local path only — never a URL). Intersect the requested bounds with `ds.bounds`; if the intersection is smaller than the request on any side, set `clipped = True`. Read the window with `from_bounds`, replace `ds.nodata` and NaN with `numpy.nan`, count them, and replace with the median of the finite values (or `0.0` when none are finite). Resample to `size × size` with `numpy` (nearest index mapping is acceptable at 30 m). Return the mission-format dict with `h_min`/`h_max` from finite values only.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest dem_crop_returns_ring_heightmap dem_crop_reports_clipping_at_a_cell_edge dem_crop_excludes_nodata_from_the_range`
Expected: `3/3 passed`.

- [ ] **Step 5: Commit**

```bash
git add server/providers/copernicus_dem.py server/providers/selftest.py
git commit -m "feat(providers): crop and resample a DEM tile to a ring heightmap"
```

---

### Task 4: The adapter

**Files:**
- Modify: `server/providers/copernicus_dem.py`, `server/providers/registry.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Produces: `CopernicusDemProvider(*, tile_fetcher=None, size=256)` with `id="copernicus-dem"`, `key="context_dem"`, `ttl_s=2_592_000`, `fetch_timeout_s=45`, `allow_inline=False`, `requires=()`.

`tile_fetcher` is `Callable[[str, Path], Path]` and defaults to `fetch_tile`, so tests inject a function with exactly that signature instead of faking HTTP.

- Adapter envelope `data` per spec §5.3: `bbox`, `width`, `height`, `h_min`, `h_max`, `asset`, `source_resolution_m`, plus `clipped`, `nodata_px`, `source_tile`.

- [ ] **Step 1: Write the failing test**

```python
@case
def dem_adapter_writes_asset_and_payload():
    import tempfile
    from pathlib import Path
    from server.providers.copernicus_dem import (CopernicusDemProvider, cell_bounds,
                                                 tile_name)
    from server.providers.cache import read_envelope, mission_dir

    tile = Path(tempfile.mkdtemp()) / "tile.tif"
    e = _extent()
    _synthetic_dem(tile, value=310.0,
                   bounds=cell_bounds(tile_name(*e.centre)))
    prov = CopernicusDemProvider(
        tile_fetcher=lambda name, dest: dest.write_bytes(tile.read_bytes()) or dest)

    root = Path(tempfile.mkdtemp())
    gw = _gw_from({"context_dem": (prov,)}, root)
    result = gw.refresh_now("M1", "context_dem", e)

    assert result.status == "fresh"
    asset = mission_dir("M1", root) / "context_dem.json"
    assert asset.exists()
    env = read_envelope("M1", "context_dem", root=root)
    assert env["data"]["asset"] == "context_dem.json"
    assert env["data"]["source_resolution_m"] == 30
    assert env["data"]["width"] == 256
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest dem_adapter_writes_asset_and_payload`
Expected: `ImportError: cannot import name 'CopernicusDemProvider'`.

- [ ] **Step 3: Implement the adapter**

`fetch` computes `tile_name(*extent.centre)`, downloads into a `tempfile.mkdtemp()` directory by calling `self.tile_fetcher(name, dest)`, calls `crop_dem`, serialises the heightmap with `json.dumps(..., ensure_ascii=False)`, and returns `ProviderPayload(data, None, extra={"asset_name": "context_dem.json", "asset_bytes": <bytes>})`. **The adapter does not know the mission id**, so `Gateway._do_refresh` writes any `extra["asset_name"]` with `write_asset(mission_id, ...)` before writing the envelope; when `extra` has no `asset_name`, behaviour is unchanged from Phase 1. Remove the temp directory in a `finally`. Register the adapter in `build_registry`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest dem_adapter_writes_asset_and_payload`
Expected: `PASS`. Then the whole suite: `python -m server.providers.selftest` → all pass, and `python -m server.providers.selftest --live` reports `ok context_dem` or a typed failure.

- [ ] **Step 5: Commit**

```bash
git add server/providers/copernicus_dem.py server/providers/registry.py server/providers/gateway.py server/providers/selftest.py
git commit -m "feat(providers): Copernicus DEM adapter with per-mission context asset"
```

---

### Task 5: `/context/dem` and the payload

**Files:**
- Modify: `server/api.py`
- Test: `server/providers/selftest.py`

**Interfaces:**
- Produces: `GET /api/v1/missions/{id}/context/dem` → the heightmap JSON, copying `spike/missions/<id>/heightmap.json` semantics but reading `context_dem.json` from the provider cache. `assets.context_dem` in the payload, `null` until cached.

- [ ] **Step 1: Write the failing test**

```python
@case
def payload_exposes_context_dem_only_when_cached():
    import tempfile
    from pathlib import Path
    import server.api as api_mod
    from server import db
    from server.providers.cache import write_asset

    mission = db.get_mission(db.init_db(), "SPIKE_BRIGHTON_ODM")
    assert mission
    root = Path(tempfile.mkdtemp())
    # weather must be registered: _payload always resolves it
    gw = _gw_from({"weather": (_Spy(),)}, root)
    original = api_mod.default_gateway
    api_mod.default_gateway = lambda: gw
    try:
        payload = api_mod._payload(mission, None)
        assert payload["assets"].get("context_dem") in (None, "")
        write_asset(mission["id"], "context_dem.json", b'{"width":1}', root=root)
        payload = api_mod._payload(mission, None)
        assert payload["assets"]["context_dem"].endswith("/context/dem")
    finally:
        api_mod.default_gateway = original
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m server.providers.selftest payload_exposes_context_dem_only_when_cached`
Expected: `KeyError: 'context_dem'` or `AssertionError`.

- [ ] **Step 3: Implement the endpoint and asset field**

Add the route returning `FileResponse` with `media_type="application/json"`, 404 when the asset is absent. In `_payload`, set `assets["context_dem"]` to the route path only when the asset exists **in the gateway's own cache root** (`cache.mission_dir(mission["id"], gw.root) / "context_dem.json"`), else `None`. Using the global default root here would be wrong under test and under any future per-deployment root.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m server.providers.selftest payload_exposes_context_dem_only_when_cached`
Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add server/api.py server/providers/selftest.py
git commit -m "feat(api): serve the cached context DEM"
```

---

### Task 6: Context terrain in Cesium

**Files:**
- Modify: `spike/web/dashboard.js`, `spike/web/dashboard.html`, `spike/web/dashboard.css`
- Test: browser check (presentation)

**Interfaces:**
- Consumes: `state.f.assets.context_dem`, `state.f.providers.items.context_dem`.
- Produces: `buildContextTerrain()`, called from `init()` after `buildLandscape()`; `renderProviders()` already lists the key with no change.

- [ ] **Step 1: Load the DEM without blocking the shell**

In `init()`, after `state.f` is set, attempt `fetch(f.assets.context_dem)` when the asset exists; store `state.contextDem = heightmap | null`. Never await it before the first render — a missing or slow DEM must not delay the scene.

- [ ] **Step 2: Build the context mesh**

`buildContextTerrain()` creates a 128² plane at the ring bbox, displaces Y by `heights_m * height_scale_m`, and textures it with the existing `context_bright.png`, keeping the Phase 1 alpha ring and haze. Add it to `state.prims.contextTerrain` and show it only in Context mode. When `state.contextDem` is null, do nothing and leave the flat plane as is.

- [ ] **Step 3: Wire mode and theme**

In `setMode`, show `contextTerrain` in Context and hide it in Reconstruction. In `applySceneTheme`, keep the bright material in paper; in obsidian hide the terrain and fall back to the flat plane, matching how the landscape is already handled.

- [ ] **Step 4: Label the resolution**

Add a small line to the Live-data card when `context_dem` is fresh or stale: `30 m context` plus `(clipped)` when `data.clipped` is true. When status is `unavailable`/`warming`, the row already reads `fetching…` and the scene stays flat — verify that.

- [ ] **Step 5: Verify in the browser**

With the DEM cached, screenshot Context in paper and obsidian at 1600×900 to `spike/shots/phase2-context-terrain-paper.png` and `-obsidian.png`. Then delete the cached asset, reload, and screenshot `phase2-context-flat.png` to prove the fallback. Confirm: no console error, the patch is still visibly a separate high-res inset, and the footprint label still reads as reconstruction.

- [ ] **Step 6: Commit**

```bash
git add spike/web/
git commit -m "feat(dashboard): context terrain from the cached 30 m DEM"
```

---

### Task 7: Offline, prefetch, and docs

**Files:**
- Modify: `server/providers/prefetch.py` (no code change expected — verify), `README.md`, `server/README.md`, `Docs/HANDOFF.md`
- Test: suite + browser

- [ ] **Step 1: Prove the offline path**

Run `python -m server.providers.prefetch --mission SPIKE_BRIGHTON_ODM --only context_dem`, confirm a status line and a cached asset. Then with `PYROSCAN_PROVIDER_OFFLINE=1`, confirm the DEM is still served from cache and Context shows terrain. Delete the asset, restart offline, and confirm the flat plane returns with the row reading `unavailable`.

- [ ] **Step 2: Prove the storage budget**

Measure `server/cache/providers/SPIKE_BRIGHTON_ODM/` size and record it in `Docs/HANDOFF.md`. Expected ~200–400 KB (a 256² heightmap), because the 34 MB tile is deleted. If it is larger, the tile was not cleaned up — fix before committing.

- [ ] **Step 3: Update the docs**

`server/README.md`: add `/context/dem`, the `context_dem` provider row (TTL 30 days, one 34 MB tile, 256² crop), and `rasterio` to the install line. `README.md`: Context now has 30 m relief, and the ground is still not reconstruction. `Docs/HANDOFF.md`: Phase 2 shipped, with the measured single-tile behaviour and the clipped-ring limit.

- [ ] **Step 4: Commit and push**

```bash
git add README.md server/README.md Docs/HANDOFF.md
git commit -m "docs: record Phase 2 context terrain"
git push origin main
```

---

## Self-Review

**Spec coverage.** §5.3 contract → Tasks 3–5. §7.5 answered gate → Tasks 1–2 use the measurement (one tile, full transfer, no windowed reads). §11.1 Live-data row → Task 6 Step 4 (generic renderer already covers it). §12 storage → Task 7 Step 2. §13 Phase 2 → all tasks. §11.2/§11.3 unchanged.

**One spec deviation to note for the implementer.** §5.3 describes DEM and imagery as "rounded outward to the provider's native tile grid" and implies a mosaic. Task 3 deliberately does **not** mosaic: it uses the single cell containing the ring centre and sets `clipped`. A 25 km ring fits a 1° cell except near an edge, and mosaicking two 34 MB tiles doubles the transfer for a rare case. The spec's §7.5 text was updated to match. If clipped rings turn out to be common in Indonesia, mosaicking becomes its own task with its own budget.

**Known sequencing constraint.** Task 4 touches `Gateway._do_refresh` to write assets. That is the only Phase 1 file this plan changes, and it must stay backward compatible: when `extra` has no `asset_name`, behaviour is byte-identical.
