import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';

const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto('http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/indonesia',
  { waitUntil: 'load' });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
await page.waitForTimeout(2500);

// a cached mountain site: 18 km DEM + Sentinel, no drone photos
await page.evaluate(() => openSite(102.5, -3.5, null));
await page.waitForFunction(() => state.viewMode === 'site', null, { timeout: 240000 });
await page.waitForTimeout(8000);

const site = await page.evaluate(() => {
  const v = state.viewer;
  const c = Cesium.Cartographic.fromDegrees(102.5, -3.5);
  let ground = null;
  try { ground = v.scene.globe.getHeight(c); } catch (e) { ground = null; }
  return {
    mode: state.viewMode,
    name: document.querySelector('#site-name').textContent,
    panel: !document.querySelector('#site-panel').hidden,
    map: getComputedStyle(document.querySelector('#map2d')).display,
    cesium: getComputedStyle(document.querySelector('#cesium')).visibility,
    terrain: v.terrainProvider === state.siteTerrain,
    ground,
    height: Math.round(v.camera.positionCartographic.height),
    pitch: Math.round(Cesium.Math.toDegrees(v.camera.pitch)),
    imagery: v.imageryLayers.length,
    modes: getComputedStyle(document.querySelector('#modes')).display,
    facts: document.querySelector('#site-facts').textContent,
    terrainText: document.querySelector('#site-terrain').textContent,
    fireCount: document.querySelector('#site-fire-count').textContent,
    profile: document.querySelector('#site-profile').width,
    rail: !document.querySelector('#site-rail').hidden,
    strip: !document.querySelector('#site-strip').hidden,
    risk: document.querySelector('#sr-risk').textContent,
    live: document.querySelector('#sr-firms').textContent,
    area: document.querySelector('#ss-area-val').textContent,
    events: document.querySelectorAll('#ss-events-list li').length,
  };
});
console.log(JSON.stringify(site, null, 2));
assert.equal(site.mode, 'site');
assert.equal(site.name, 'Bengkulu');
assert.equal(site.panel, true);
assert.equal(site.map, 'none');
assert.equal(site.cesium, 'visible');
assert.equal(site.terrain, true);
assert.ok(site.ground > 100, `terrain height ${site.ground}`);
assert.ok(site.height > 1000 && site.height < 40000, `camera ${site.height}`);
assert.ok(site.pitch < -20, `pitch ${site.pitch}`);
assert.equal(site.modes, 'none');
assert.match(site.facts, /8\.8 m\/px/);
assert.match(site.terrainText, /relief/);
assert.match(site.fireCount, /within/);
assert.ok(site.profile > 400, `profile canvas ${site.profile}`);
assert.equal(site.rail, true, 'site rail hidden');
assert.equal(site.strip, true, 'site strip hidden');
assert.match(site.risk, /LOW|MEDIUM|HIGH|CRITICAL/);
assert.match(site.live, /dots/);
assert.match(site.area, /ha/);
assert.ok(site.events > 0, 'no site key events');
assert.deepEqual(errors, []);
await page.screenshot({ path: 'spike/shots/phase10-site.png' });

const spread = await page.evaluate(() => ({
  frames: state.spreadFrames.length,
  hidden: document.querySelector('#site-spread').hidden,
  label: document.querySelector('#spread-label').textContent,
  risk: document.querySelector('#spread-risk').textContent,
  playing: state.spreadPlaying,
}));
console.log('spread', JSON.stringify(spread));
assert.ok(spread.frames >= 12, `spread frames ${spread.frames}`);
assert.equal(spread.hidden, false);
assert.match(spread.risk, /m\/min/);
assert.equal(spread.playing, true);
await page.waitForTimeout(1000);
const nextLabel = await page.evaluate(() =>
  document.querySelector('#spread-label').textContent);
assert.notEqual(nextLabel, spread.label, 'spread animation did not advance');

// site scales: 4 km keeps its own DEM + Sentinel context
await page.click('.site-scales button[data-km="4"]');
await page.waitForFunction(
  () => state.site && Math.round(state.site.window_km) === 4,
  null, { timeout: 180000 });
await page.waitForTimeout(1500);
const smallSite = await page.evaluate(() => ({
  km: state.site.window_km,
  height: Math.round(state.viewer.camera.positionCartographic.height),
  facts: document.querySelector('#site-facts').textContent,
  active: document.querySelector('.site-scales button.active').dataset.km,
}));
console.log('site 4 km', JSON.stringify(smallSite));
assert.equal(Math.round(smallSite.km), 4);
assert.ok(smallSite.height < 10000, `4 km camera ${smallSite.height}`);
assert.match(smallSite.facts, /4 km/);
assert.equal(smallSite.active, '4');

// controls stay on the site; they must not fly out to the Indonesia globe
const h0 = await page.evaluate(() =>
  Math.round(state.viewer.camera.positionCartographic.height));
await page.click('#zoom-out');
await page.waitForTimeout(700);
const h1 = await page.evaluate(() =>
  Math.round(state.viewer.camera.positionCartographic.height));
assert.ok(h1 > h0 && h1 < 40000, `site zoom-out ${h0} -> ${h1}`);
await page.click('#zoom-in');
await page.waitForTimeout(700);
const h2 = await page.evaluate(() =>
  Math.round(state.viewer.camera.positionCartographic.height));
assert.ok(h2 < h1, `site zoom-in ${h1} -> ${h2}`);
await page.click('#reset');
await page.waitForTimeout(900);
const reset = await page.evaluate(() => ({
  h: Math.round(state.viewer.camera.positionCartographic.height),
  pitch: Math.round(Cesium.Math.toDegrees(state.viewer.camera.pitch)),
  site: Boolean(state.site),
}));
console.log('site controls', JSON.stringify({ h0, h1, h2, reset }));
assert.ok(reset.h > 1500 && reset.h < 16000, `reset height ${reset.h}`);
assert.ok(reset.pitch < -30, `reset pitch ${reset.pitch}`);
assert.equal(reset.site, true);

// a drag or wheel on the terrain must stay on the site, not fly to the globe
await page.mouse.move(900, 420);
await page.mouse.down();
await page.mouse.move(950, 450, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(700);
const dragged = await page.evaluate(() => ({
  mode: state.viewMode,
  h: Math.round(state.viewer.camera.positionCartographic.height),
}));
console.log('site drag', JSON.stringify(dragged));
assert.equal(dragged.mode, 'site');
assert.ok(dragged.h < 40000, `drag left the site: ${dragged.h} m`);
await page.mouse.move(900, 420);
await page.mouse.wheel(0, 400);
await page.waitForTimeout(700);
const wheeled = await page.evaluate(() => ({
  mode: state.viewMode,
  h: Math.round(state.viewer.camera.positionCartographic.height),
}));
console.log('site wheel', JSON.stringify(wheeled));
assert.equal(wheeled.mode, 'site');
assert.ok(wheeled.h < 40000, `wheel left the site: ${wheeled.h} m`);

// 60 km regional context uses its own wider DEM + imagery
await page.click('.site-scales button[data-km="60"]');
await page.waitForFunction(
  () => state.site && Math.round(state.site.window_km) === 60,
  null, { timeout: 180000 });
await page.waitForTimeout(1500);
const regional = await page.evaluate(() => ({
  km: state.site.window_km,
  height: Math.round(state.viewer.camera.positionCartographic.height),
  facts: document.querySelector('#site-facts').textContent,
}));
console.log('site 60 km', JSON.stringify(regional));
assert.equal(Math.round(regional.km), 60);
assert.ok(regional.height > 12000, `60 km camera ${regional.height}`);
assert.match(regional.facts, /60 km/);

await page.click('#site-back');
await page.waitForTimeout(1500);
const back = await page.evaluate(() => ({
  mode: state.viewMode,
  site: state.site,
  map: getComputedStyle(document.querySelector('#map2d')).display,
  panel: document.querySelector('#site-panel').hidden,
}));
console.log(JSON.stringify(back));
assert.equal(back.mode, 'indonesia');
assert.equal(back.site, null);
assert.equal(back.map, 'block');
assert.equal(back.panel, true);
assert.deepEqual(errors, []);

await browser.close();
console.log('PASS site: 3D terrain, imagery, panel, back to map');
