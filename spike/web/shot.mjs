import { chromium } from 'playwright-core';

const url = process.argv[2] || 'http://127.0.0.1:8080/';
const out = process.argv[3] || '../shots/diag.png';
const headless = !process.argv.includes('--headed');
const browser = await chromium.launch({ channel: 'msedge', headless, args: ['--use-angle=d3d11', '--enable-gpu'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR', e.stack || e.message));
page.on('console', (m) => console.log('CONSOLE', m.type(), m.text()));
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(12000);
console.log('READY', await page.evaluate(() => window.__ready));
const hudCount = await page.locator('#hud').count();
if (hudCount) console.log('HUD', (await page.locator('#hud').innerText()).replace(/\n/g, ' | '));
const errCount = await page.locator('#err').count();
if (errCount) console.log('ERR', (await page.locator('#err').innerText()).replace(/\n/g, ' | '));
await page.screenshot({ path: out });
await browser.close();

