import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';

const url = process.argv[2] ||
  'http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/indonesia';
const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.addInitScript(() => {
  try { localStorage.setItem('pyroscan-globe-skin', 'relief'); } catch (e) {}
});
await page.goto(url, { waitUntil: 'load' });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
await page.waitForFunction(
  () => typeof state !== 'undefined' && state.map2d !== null,
  null, { timeout: 30000 });
await page.waitForTimeout(2500);

// --- the 2D map is the Indonesia renderer; Cesium is parked --------------
const initial = await page.evaluate(() => ({
  mode: state.mode,
  map: Boolean(state.map2d),
  mapDisplay: getComputedStyle(document.querySelector('#map2d')).display,
  mapSize: [document.querySelector('#map2d').clientWidth,
            document.querySelector('#map2d').clientHeight],
  cesium: getComputedStyle(document.querySelector('#cesium')).visibility,
  loop: state.viewer.useDefaultRenderLoop,
  view: state.map2d.view(),
  skinButtons: [...document.querySelectorAll('#globe-skin button')]
    .map((b) => b.dataset.skin),
  legend: document.querySelector('#legend-body').textContent.replace(/\s+/g, ' '),
}));
console.log(JSON.stringify(initial, null, 2));
assert.equal(initial.mode, 'indonesia');
assert.equal(initial.map, true);
assert.equal(initial.mapDisplay, 'block');
assert.ok(initial.mapSize[0] > 1200 && initial.mapSize[1] > 600,
  `map canvas ${initial.mapSize}`);
assert.equal(initial.cesium, 'hidden');
assert.equal(initial.loop, false);
assert.equal(initial.view.skin, 'relief');
assert.equal(initial.view.scale, initial.view.fit);
assert.deepEqual(initial.skinButtons, ['relief', 'satellite', 'atlas', 'flat']);
assert.match(initial.legend, /Relief/);
assert.match(initial.legend, /NASA FIRMS/);
assert.deepEqual(errors, []);

// --- fires reach the 2D map ----------------------------------------------
await page.waitForFunction(
  () => typeof state !== 'undefined'
    && (state.fires !== null || state.firesReason !== null),
  null, { timeout: 90000 });
const fires = await page.evaluate(() => ({
  available: state.fires && state.fires.available,
  dots: state.map2d.view().dots,
  data: state.fires ? state.fires.dots.length : 0,
  legend: document.querySelector('#legend-body').textContent,
}));
console.log('fires', JSON.stringify(fires));
assert.equal(fires.available, true);
assert.ok(fires.dots > 0);
assert.equal(fires.dots, fires.data);
assert.match(fires.legend, /NASA FIRMS/);

// fire pins are hoverable and show sensor/FRP/time
const pinDot = await page.evaluate(() => {
  const d = state.fires.dots.find((x) => x.iso === 'ID-KT') || state.fires.dots[0];
  const r = document.querySelector('#map2d').getBoundingClientRect();
  const p = state.map2d.project(d.lon, d.lat);
  return { x: Math.round(r.left + p.x), y: Math.round(r.top + p.y) };
});
await page.mouse.move(pinDot.x, pinDot.y, { steps: 4 });
await page.waitForTimeout(450);
const pin = await page.evaluate(() => ({
  tip: document.querySelector('#province-tip').textContent,
  hidden: document.querySelector('#province-tip').hidden,
  cursor: document.querySelector('#map2d').style.cursor,
}));
console.log('pin hover', JSON.stringify(pin));
assert.equal(pin.hidden, false);
assert.match(pin.tip, /MW/);
assert.equal(pin.cursor, 'pointer');

// --- the default view shows the whole archipelago ------------------------
const whole = await page.evaluate(() => {
  const c = document.querySelector('#map2d');
  const tl = state.map2d.project(94, 8);
  const br = state.map2d.project(142, -12);
  return { w: c.clientWidth, h: c.clientHeight, tl, br };
});
console.log('whole', JSON.stringify(whole));
assert.ok(whole.tl.x >= 0 && whole.tl.y >= 0, 'north-west is cropped');
assert.ok(whole.br.x <= whole.w && whole.br.y <= whole.h, 'south-east is cropped');

// zoom-out stops at the whole-country fit (no tiny map in a sea of nothing)
await page.mouse.move(800, 450);
for (let i = 0; i < 8; i++) await page.mouse.wheel(0, 500);
await page.waitForTimeout(350);
const zoomedOut = await page.evaluate(() => state.map2d.view());
console.log('zoom-out floor', zoomedOut.scale, 'fit', zoomedOut.fit);
assert.ok(Math.abs(zoomedOut.scale - zoomedOut.fit) < 1,
  `zoomed out below the fit: ${zoomedOut.scale} < ${zoomedOut.fit}`);

async function mapPoint(lon, lat) {
  return page.evaluate(([lon, lat]) => {
    const rect = document.querySelector('#map2d').getBoundingClientRect();
    const p = state.map2d.project(lon, lat);
    return { x: Math.round(rect.left + p.x), y: Math.round(rect.top + p.y) };
  }, [lon, lat]);
}
const kt = await mapPoint(114, 0);

// --- wheel zoom keeps the cursor point fixed -----------------------------
const beforeZoom = await page.evaluate(() => state.map2d.view().scale);
await page.mouse.move(kt.x, kt.y);
await page.mouse.wheel(0, -600);
await page.waitForTimeout(400);
const afterZoom = await page.evaluate(() => state.map2d.view().scale);
const ktAfter = await mapPoint(114, 0);
console.log('zoom', beforeZoom, '->', afterZoom, 'cursor drift',
  Math.abs(ktAfter.x - kt.x), Math.abs(ktAfter.y - kt.y));
assert.ok(afterZoom > beforeZoom * 1.2, `${beforeZoom} -> ${afterZoom}`);
assert.ok(Math.abs(ktAfter.x - kt.x) <= 8, 'zoom drifted from the cursor');

// --- drag pans -----------------------------------------------------------
const beforePan = await page.evaluate(() => state.map2d.view());
await page.mouse.move(800, 450);
await page.mouse.down();
await page.mouse.move(860, 470, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(300);
const afterPan = await page.evaluate(() => state.map2d.view());
console.log('pan tx', beforePan.tx, '->', afterPan.tx);
assert.ok(afterPan.tx > beforePan.tx + 20, `tx ${beforePan.tx} -> ${afterPan.tx}`);

// a hard drag must stay inside the real texture, so no flat sea or vignette
await page.mouse.move(800, 450);
await page.mouse.down();
await page.mouse.move(1560, 850, { steps: 12 });
await page.mouse.up();
await page.waitForTimeout(300);
const coverage = await page.evaluate(() => {
  const c = document.querySelector('#map2d');
  const tl = state.map2d.project(88, 10);
  const br = state.map2d.project(150, -20);
  return { w: c.clientWidth, h: c.clientHeight, tl, br };
});
console.log('edge clamp', JSON.stringify(coverage));
assert.ok(coverage.tl.x <= 1 && coverage.tl.y <= 1,
  'flat sea exposed at the west/north edge');
assert.ok(coverage.br.x >= coverage.w - 1 && coverage.br.y >= coverage.h - 1,
  'flat sea exposed at the east/south edge');

// --- reset, select, plate ------------------------------------------------
await page.evaluate(() => state.map2d.reset());
await page.waitForTimeout(700);
const kt2 = await mapPoint(114, 0);
await page.mouse.click(kt2.x, kt2.y);
await page.waitForTimeout(900);
const selected = await page.evaluate(() => ({
  iso: state.selectedIso,
  panel: !document.querySelector('#province-panel').hidden,
  name: document.querySelector('#pp-name').textContent,
  count: document.querySelector('#pp-count').textContent,
  view: state.map2d.view(),
  legend: document.querySelector('#legend-body').textContent,
}));
console.log('selected', JSON.stringify(selected));
assert.equal(selected.iso, 'ID-KT');
assert.equal(selected.panel, true);
assert.equal(selected.name, 'Kalimantan Tengah');
assert.equal(selected.view.selected, 'ID-KT');
assert.ok(selected.view.scale > initial.view.fit, 'selection did not zoom');
assert.equal(await page.evaluate(() => document.querySelector('#pp-site').disabled),
  false, '3D site is not offered for a selected province');
await page.waitForFunction(
  () => typeof state !== 'undefined' && state.map2d.view().plate,
  null, { timeout: 120000 });
const plate = await page.evaluate(() => ({
  chip: document.querySelector('#pp-imagery').textContent,
  detail: document.querySelector('#pp-detail').disabled,
  legend: document.querySelector('#legend-body').textContent,
}));
console.log('plate', JSON.stringify(plate));
assert.match(plate.chip, /scenes/);
assert.equal(plate.detail, false);
assert.match(plate.legend, /Plate/);
await page.screenshot({ path: 'spike/shots/phase9-map2d-selected.png' });

// --- detail tier ---------------------------------------------------------
await page.click('#pp-detail');
await page.waitForFunction(
  () => typeof state !== 'undefined' && state.map2d.view().detail,
  null, { timeout: 120000 });
await page.waitForTimeout(700);
const detail = await page.evaluate(() => ({
  chip: document.querySelector('#pp-imagery').textContent,
  detail: state.detailMeta,
  view: state.map2d.view(),
}));
console.log('detail', JSON.stringify(detail));
assert.equal(detail.detail.tier, 'detail');
assert.equal(detail.detail.resolution_m, 59);
assert.match(detail.chip, /59 m detail/);
await page.screenshot({ path: 'spike/shots/phase9-map2d-detail.png' });

// --- skins ---------------------------------------------------------------
for (const skin of ['satellite', 'atlas', 'flat', 'relief']) {
  await page.click(`[data-skin="${skin}"]`);
  await page.waitForTimeout(350);
  const current = await page.evaluate(() => state.map2d.view().skin);
  assert.equal(current, skin);
  if (skin === 'atlas') {
    const atlas = await page.evaluate(() => ({
      chip: document.querySelector('#pp-imagery').textContent,
      detailDisabled: document.querySelector('#pp-detail').disabled,
    }));
    assert.match(atlas.chip, /hidden on atlas/);
    assert.equal(atlas.detailDisabled, true);
    await page.screenshot({ path: 'spike/shots/phase9-skin-atlas.png' });
  }
}
await page.waitForTimeout(500);
assert.deepEqual(errors, []);

// --- Esc clears selection and returns to the fit view --------------------
await page.keyboard.press('Escape');
await page.waitForTimeout(700);
const cleared = await page.evaluate(() => ({
  iso: state.selectedIso,
  panel: document.querySelector('#province-panel').hidden,
  view: state.map2d.view(),
}));
console.log('cleared', JSON.stringify(cleared));
assert.equal(cleared.iso, null);
assert.equal(cleared.panel, true);
assert.equal(cleared.view.selected, null);
assert.ok(Math.abs(cleared.view.scale - initial.view.fit) < 2,
  `scale ${cleared.view.scale} vs fit ${initial.view.fit}`);

// --- draw cost -----------------------------------------------------------
const ms = await page.evaluate(() => {
  const t0 = performance.now();
  for (let i = 0; i < 40; i++) state.map2d.render();
  return (performance.now() - t0) / 40;
});
console.log('map render ms', ms.toFixed(2));
assert.ok(ms < 16, `map draw ${ms.toFixed(2)} ms`);

// --- mission modes still use Cesium --------------------------------------
await page.evaluate(() => setViewMode('terrain', { animate: false }));
await page.waitForTimeout(900);
const terrain = await page.evaluate(() => ({
  mode: state.viewMode,
  map: getComputedStyle(document.querySelector('#map2d')).display,
  cesium: getComputedStyle(document.querySelector('#cesium')).visibility,
  loop: state.viewer.useDefaultRenderLoop,
  globe: state.viewer.scene.globe.show,
  rail: getComputedStyle(document.querySelector('#rail')).display,
  name: document.querySelector('#incident-name').textContent,
}));
console.log(JSON.stringify(terrain, null, 2));
assert.equal(terrain.mode, 'terrain');
assert.equal(terrain.map, 'none');
assert.equal(terrain.cesium, 'visible');
assert.equal(terrain.loop, true);
assert.equal(terrain.globe, false);
assert.notEqual(terrain.rail, 'none');
assert.match(terrain.name, /Brighton/);

await page.evaluate(() => setViewMode('indonesia', { animate: false }));
await page.waitForTimeout(900);
const back = await page.evaluate(() => ({
  mode: state.viewMode,
  map: getComputedStyle(document.querySelector('#map2d')).display,
  cesium: getComputedStyle(document.querySelector('#cesium')).visibility,
  loop: state.viewer.useDefaultRenderLoop,
  selected: state.selectedIso,
}));
console.log('back', JSON.stringify(back));
assert.equal(back.map, 'block');
assert.equal(back.cesium, 'hidden');
assert.equal(back.loop, false);
assert.equal(back.selected, null);
assert.deepEqual(errors, []);

await page.screenshot({ path: 'spike/shots/phase9-map2d.png' });
await browser.close();
console.log('PASS map2d: skins, whole-country fit, zoom, pan, select, plate, detail, clear, terrain');
