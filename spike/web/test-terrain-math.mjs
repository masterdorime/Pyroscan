/* Offline regression test for the terrain grid math (node, no browser).
 *
 *   node spike/web/test-terrain-math.mjs
 *
 * It pins the things that silently break the DEM surface: bbox orientation
 * (row 0 is north), the datum anchor, a complete index buffer, and no NaNs.
 */
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import assert from 'node:assert/strict';

// terrain-math.js is a classic script for the browser (the package is ESM), so
// load its source rather than importing it.
const sandbox = {};
runInNewContext(readFileSync(new URL('./terrain-math.js', import.meta.url), 'utf8'), sandbox);
const TM = sandbox.TerrainMath;
assert.ok(TM && typeof TM.buildGrid === 'function', 'terrain-math.js exposes TerrainMath');

const dem = {
  west: -92.0, south: 46.7, east: -91.8, north: 46.9,
  width: 4, height: 4,
  // north row first: NW=100, NE=200, SW=300, SE=400
  heights_m: [
    100, 100, 100, 200,
    100, 100, 100, 200,
    300, 300, 300, 400,
    300, 300, 300, 400,
  ],
};

// --- sampling: the heightmap's first row is the north edge ------------------
assert.equal(TM.sampleDem(dem, -92.0, 46.9), 100, 'NW corner');
assert.equal(TM.sampleDem(dem, -91.8, 46.9), 200, 'NE corner');
assert.equal(TM.sampleDem(dem, -92.0, 46.7), 300, 'SW corner');
assert.equal(TM.sampleDem(dem, -91.8, 46.7), 400, 'SE corner');
assert.equal(TM.sampleDem(dem, -92.1, 46.8), null, 'outside west');
assert.equal(TM.sampleDem(dem, -91.9, 46.6), null, 'outside south');

// --- datum anchor: the DEM centre lands exactly on the patch plane ---------
const datum = 154.4;
const offset = TM.anchorOffset(dem, -91.9, 46.8, datum);
assert.equal(TM.sampleDem(dem, -91.9, 46.8) + offset, datum);

// --- grid: geometry counts, corners, and no holes --------------------------
const grid = TM.buildGrid(dem, dem, 8, offset);
assert.equal(grid.vertexCount, 9 * 9);
assert.equal(grid.triangleCount, 8 * 8 * 2);
assert.equal(grid.idx.length, grid.triangleCount * 3);
assert.ok(grid.idx.every((k) => Number.isInteger(k) && k >= 0 && k < grid.vertexCount));
assert.equal(grid.sampled, 1, 'the grid covers the dem');

// row 0 is north; column 0 is west
assert.equal(grid.lat[0], dem.north);
assert.equal(grid.lon[0], dem.west);
assert.equal(grid.lon[8], dem.east);
assert.equal(grid.lat[8 * 9], dem.south);

// The vertex height is the DEM sample plus the shared offset, everywhere.
for (let k = 0; k < grid.vertexCount; k++) {
  const expect = TM.sampleDem(dem, grid.lon[k], grid.lat[k]) + offset;
  assert.equal(grid.height[k], expect, `vertex ${k}`);
  assert.ok(Number.isFinite(grid.height[k]));
}
assert.equal(grid.height[0], 100 + offset, 'north-west vertex');
assert.equal(grid.height[8 * 9 + 8], 400 + offset, 'south-east vertex');

// st runs 0..1 west→east and 0..1 north→south, independently of the heights.
assert.deepEqual([grid.st[0], grid.st[1]], [0, 0]);
assert.deepEqual([grid.st[8 * 2], grid.st[8 * 2 + 1]], [1, 0]);
assert.deepEqual([grid.st[(8 * 9) * 2], grid.st[(8 * 9) * 2 + 1]], [0, 1]);

// --- a bbox partly outside the DEM is filled, not NaN ----------------------
const wide = { west: -92.2, south: 46.6, east: -91.6, north: 47.0 };
const partial = TM.buildGrid(wide, dem, 10, offset);
assert.ok(partial.sampled < 1, 'the wide grid leaves the dem');
assert.ok(partial.height.some((h) => h == null), 'and reports the holes');
TM.fillMissing(partial, datum);
assert.ok(partial.height.every(Number.isFinite), 'filled with the datum');

// --- texture registration: which part of the photo covers a box -------------
const image = { west: -92.0202, south: 46.8247, east: -91.9677, north: 46.8606 };
const same = TM.textureRect(image, image);
// The function runs in a vm realm, so its arrays are not this realm's Array:
// compare values, not prototypes.
assert.deepEqual(Array.from(same), [0, 0, 1, 1], 'identical boxes use the whole texture');

// 1.35 km box inside a 4 km image -> the central ~34 % of both axes
const inner = {
  west: image.west + 0.33 * (image.east - image.west),
  south: image.south + 0.33 * (image.north - image.south),
  east: image.west + 0.67 * (image.east - image.west),
  north: image.south + 0.67 * (image.north - image.south),
};
const rect = TM.textureRect(inner, image);
assert.ok(Math.abs(rect[0] - 0.33) < 1e-9 && Math.abs(rect[2] - 0.67) < 1e-9);
assert.ok(Math.abs(rect[1] - 0.33) < 1e-9 && Math.abs(rect[3] - 0.67) < 1e-9);
assert.ok(rect[1] < rect[3], 'v grows southwards, so v0 is the north edge');

// A box larger than the image is clamped, never sampled outside it.
const wider = { west: image.west - 1, south: image.south - 1,
  east: image.east + 1, north: image.north + 1 };
assert.deepEqual(Array.from(TM.textureRect(wider, image)), [0, 0, 1, 1]);
assert.deepEqual(Array.from(TM.textureRect(null, image)), [0, 1, 0, 0]);

// --- scale bar: a round number of metres inside the pixel budget ------------
const km = TM.scaleBar(15, 140);           // 15 m/px * 140 px = 2100 m
assert.equal(km.metres, 2000);
assert.equal(km.label, '2 km');
assert.ok(km.px <= 140 && km.px > 70);
const m = TM.scaleBar(0.4, 140);           // 56 m of room
assert.equal(m.metres, 50);
assert.equal(m.label, '50 m');
assert.equal(TM.scaleBar(0, 140).label, '');

console.log('PASS terrain-math: sampling, anchor, winding bounds, fill, texture rect, scale bar');

