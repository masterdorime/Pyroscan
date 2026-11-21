import { chromium } from 'playwright-core';

const url = process.argv[2] ||
  'http://127.0.0.1:8000/dashboard.html#/SPIKE_BRIGHTON_ODM/indonesia';
const browser = await chromium.launch({ channel: 'msedge', headless: true,
  args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await page.goto(url, { waitUntil: 'load' });
await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
await page.waitForFunction(() => state.map2d !== null, null, { timeout: 30000 });
await page.waitForTimeout(1500);

const result = await page.evaluate(() => {
  const map = state.map2d;
  const view = map.view();
  const t0 = performance.now();
  for (let i = 0; i < 200; i++) map.render();
  return { draw: (performance.now() - t0) / 200, dots: view.dots,
           scale: view.scale };
});
console.log(JSON.stringify(result));
await browser.close();
if (result.draw > 2) {
  console.error(`FAIL map2d draw ${result.draw.toFixed(2)} ms/frame`);
  process.exit(1);
}
console.log(`PASS map2d: ${result.draw.toFixed(2)} ms/draw, ${result.dots} dots`);
