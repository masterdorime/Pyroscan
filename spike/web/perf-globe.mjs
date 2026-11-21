import { chromium } from 'playwright-core';

const url = 'http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/indonesia';
const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await page.goto(url, { waitUntil: 'load' });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
await page.waitForTimeout(5000); // texture upload + first frames

// rAF fires in bursts headless and lies about rendered cadence; postRender is
// the frame the compositor actually got.
async function measure(label, n = 40) {
  const ms = await page.evaluate((n) => new Promise((resolve) => {
    const scene = state.viewer.scene;
    const samples = [];
    let last = 0;
    const listener = () => {
      const now = performance.now();
      if (last) samples.push(now - last);
      last = now;
      if (samples.length >= n) {
        scene.postRender.removeEventListener(listener);
        samples.sort((a, b) => a - b);
        resolve(samples[Math.floor(samples.length / 2)]);
      }
    };
    scene.postRender.addEventListener(listener);
  }), n);
  console.log(label.padEnd(32), Math.round(ms), 'ms/frame', (1000 / ms).toFixed(1), 'fps');
  return ms;
}

async function set(fn) {
  await page.evaluate(fn);
  await page.waitForTimeout(700);
}

await measure('baseline (auto-tuned)');
console.log('tuned scale', await page.evaluate(() => state.viewer.resolutionScale));
await set(() => { state.viewer.scene.postProcessStages.fxaa.enabled = false; });
await measure('fxaa off');
await set(() => { state.viewer.scene.postProcessStages.fxaa.enabled = true; });
await set(() => { state.provinces.show = false; });
await measure('no province lines');
await set(() => { state.provinces.show = true; state.viewer.scene.skyAtmosphere.show = false; });
await measure('no atmosphere');
await set(() => { state.viewer.scene.skyAtmosphere.show = true; });
await set(() => setGlobeSkin('flat'));
await measure('flat skin (no imagery)');
await set(() => setGlobeSkin('texture'));
await set(() => { state.viewer.resolutionScale = 0.75; });
await measure('resolutionScale 0.75');
await set(() => { state.viewer.resolutionScale = 0.5; });
await measure('resolutionScale 0.50');
await set(() => { state.viewer.resolutionScale = 1.0; });

// The regional crop is the only new per-frame cost; isolate it at a fixed
// 2,000 km camera. The cached desired state keeps syncGlobeLayers from
// reverting the manual `show`.
await set(() => {
  state.viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(114, 0, 2000000),
    orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
  });
  state.viewer.resolutionScale = 1.0;
});
await page.waitForTimeout(1500);
await set(() => { state.indonesiaLayer.show = false; state.globeLayerState = { world: true, crop: true }; });
await measure('2000 km · world only');
await set(() => { state.indonesiaLayer.show = true; state.globeLayerState = { world: true, crop: true }; });
await measure('2000 km · + 4096 crop');

console.log(JSON.stringify(await page.evaluate(() => ({
  dpr: window.devicePixelRatio,
  canvas: [state.canvas.width, state.canvas.height],
  msaa: state.viewer.scene.msaaSamples,
  resolutionScale: state.viewer.resolutionScale,
  skin: state.globeSkin,
  cropShown: state.indonesiaLayer.show,
  entities: state.provinces ? state.provinces.entities.values.length : 0,
})), null, 2));

await browser.close();
