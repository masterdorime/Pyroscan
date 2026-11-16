import { chromium } from 'playwright-core';

const browser = await chromium.launch({ channel: 'msedge', headless: false });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.stack || e.message));
await page.goto('http://127.0.0.1:8000/dashboard.html?bases=1');
await page.waitForTimeout(6000);

const shot = async (name) => {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `../shots/${name}.png` });
};

await shot('base-elevation');
await page.check('input[name="base"][value="ortho"]');
await shot('base-ortho');
await page.check('input[name="base"][value="severity"]');
await shot('base-severity');
await page.click('.presets button[data-preset="forecast"]');
await shot('preset-forecast');
await page.click('.presets button[data-preset="terrain"]');
await shot('preset-terrain');
await page.click('.presets button[data-preset="burn"]');
await shot('preset-burn');

console.log('errors', errors.length, errors.join('\n'));
await browser.close();
