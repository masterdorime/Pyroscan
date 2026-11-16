import { chromium } from 'playwright-core';

const browser = await chromium.launch({ channel: 'msedge', headless: false });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.stack || e.message));
await page.goto(process.argv[2] || 'http://127.0.0.1:8000/dashboard.html?verify=1');
await page.waitForTimeout(6000);

for (const tab of ['mission', 'advisory', 'weather']) {
  await page.click(`#tabs button[data-tab="${tab}"]`);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `../shots/tab-${tab}.png` });
}

await page.click('#tabs button[data-tab="layers"]');
await page.evaluate(() => {
  const el = document.querySelector('#forecast');
  el.value = '60';
  el.dispatchEvent(new Event('input', { bubbles: true }));
});
await page.waitForTimeout(800);
await page.screenshot({ path: '../shots/forecast-60.png' });

await page.click('#toggle-2d');
await page.waitForTimeout(800);
await page.screenshot({ path: '../shots/topdown.png' });

await page.click('#toggle-2d');
await page.click('#rail-toggle');
await page.waitForTimeout(500);
await page.screenshot({ path: '../shots/collapsed.png' });

console.log('errors', errors.length, errors.join('\n'));
await browser.close();
