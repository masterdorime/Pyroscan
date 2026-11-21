/* Terrain grid math shared by the context mosaic and the regional ring.
 *
 * No Cesium, no DOM: a classic script so `dashboard.html` can load it with a
 * plain tag, and `spike/web/test-terrain-math.mjs` can require the same file in
 * node. Keeping the sampling and the anchoring here is what makes the two
 * surfaces use one datum instead of two guesses.
 */
(function (root) {
  'use strict';

  /** Bilinear-free sample of a DEM heightmap, or null outside its bbox. */
  function sampleDem(dem, lon, lat) {
    if (!dem || !dem.heights_m || !dem.width || !dem.height) return null;
    const u = (lon - dem.west) / (dem.east - dem.west);
    const v = (dem.north - lat) / (dem.north - dem.south);
    if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
    const x = Math.min(dem.width - 1, Math.max(0, Math.round(u * (dem.width - 1))));
    const y = Math.min(dem.height - 1, Math.max(0, Math.round(v * (dem.height - 1))));
    const h = dem.heights_m[y * dem.width + x];
    return Number.isFinite(h) ? h : null;
  }

  /** Height that puts the DEM at the mission centre onto the patch's datum. */
  function anchorOffset(dem, lon, lat, datumHeight) {
    const centreH = sampleDem(dem, lon, lat);
    return centreH == null ? 0 : datumHeight - centreH;
  }

  /**
   * A regular lon/lat grid over `bbox` with heights from `dem`.
   *
   * Returns {lon, lat, height, st, nx, ny, finite} arrays in row-major order,
   * north to south, plus the index list for 2*nx*ny triangles. `st` is the
   * mesh coordinate pair (0..1 west→east, 0..1 north→south) that the texture
   * mapper turns into atlas coordinates; it is not the heightmap's own uv.
   */
  function buildGrid(bbox, dem, n, offset) {
    const nx = n, ny = n;
    const lon = [], lat = [], height = [], st = [];
    let finite = 0;
    for (let j = 0; j <= ny; j++) {
      const v = j / ny;
      const la = bbox.north - (bbox.north - bbox.south) * v;
      for (let i = 0; i <= nx; i++) {
        const u = i / nx;
        const lo = bbox.west + (bbox.east - bbox.west) * u;
        const h = sampleDem(dem, lo, la);
        lon.push(lo); lat.push(la);
        height.push(h == null ? null : h + offset);
        if (h != null) finite++;
        st.push(u, v);
      }
    }
    const idx = [];
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const a = j * (nx + 1) + i;
        const b = a + 1;
        const d = a + nx + 1;
        const e = d + 1;
        idx.push(a, b, d, b, e, d);
      }
    }
    return {
      lon, lat, height, st, idx, nx, ny,
      vertexCount: lon.length,
      triangleCount: idx.length / 3,
      finite,
      sampled: finite / lon.length,
    };
  }

  /** Replace null heights with a fallback so the mesh never has holes. */
  function fillMissing(grid, fallback) {
    for (let i = 0; i < grid.height.length; i++) {
      if (grid.height[i] == null) grid.height[i] = fallback;
    }
    return grid;
  }

  const clamp01 = (v) => Math.min(1, Math.max(0, v));

  /**
   * Where `box` sits inside `imageBox`, as texture coordinates [u0, v0, u1, v1].
   * `v` grows southwards (row 0 is the north edge of the image), matching the
   * mesh convention. Missing boxes return a sentinel the caller must not use.
   */
  function textureRect(box, imageBox) {
    if (!box || !imageBox) return [0, 1, 0, 0];
    const du = (imageBox.east - imageBox.west) || 1e-9;
    const dv = (imageBox.north - imageBox.south) || 1e-9;
    return [
      clamp01((box.west - imageBox.west) / du),
      clamp01((imageBox.north - box.north) / dv),
      clamp01((box.east - imageBox.west) / du),
      clamp01((imageBox.north - box.south) / dv),
    ];
  }

  /**
   * A scale bar that fits `maxPx`: the largest 1/2/5 x 10^n metre length whose
   * pixel width stays inside the budget. Returns {metres, px, label}.
   */
  function scaleBar(metresPerPixel, maxPx) {
    const mpp = Number(metresPerPixel);
    const budget = Number(maxPx);
    if (!(mpp > 0) || !(budget > 0)) return { metres: 0, px: 0, label: '' };
    const room = mpp * budget;
    const decade = Math.pow(10, Math.floor(Math.log10(room)));
    let metres = decade;
    for (const step of [decade, 2 * decade, 5 * decade, 10 * decade]) {
      if (step <= room) metres = step;
    }
    const label = metres >= 1000
      ? `${Number((metres / 1000).toFixed(1))} km`
      : `${Number(metres.toFixed(metres < 1 ? 1 : 0))} m`;
    return { metres, px: metres / mpp, label };
  }

  const api = { sampleDem, anchorOffset, buildGrid, fillMissing, textureRect, scaleBar };
  root.TerrainMath = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof globalThis !== 'undefined' ? globalThis : this));
