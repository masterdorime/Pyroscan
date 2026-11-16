import { chromium } from 'playwright-core';

const url = process.argv[2] || 'http://127.0.0.1:8000/dashboard.html';
const out = process.argv[3] || '../shots/weather-tab.png';
const browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR', e.stack || e.message));
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(9000);
await page.click('#tabs button[data-tab="weather"]');
await page.waitForTimeout(600);
const state = await page.evaluate(() => ({
  flagHidden: document.querySelector('#w-flag').hidden,
  note: document.querySelector('#w-note').textContent,
  source: document.querySelector('#w-source').textContent,
  age: document.querySelector('#w-age').textContent,
}));
console.log('WEATHER', JSON.stringify(state));
await page.screenshot({ path: out });
await browser.close();
