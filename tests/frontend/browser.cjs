/* Run with Node.js and Playwright/Chromium installed. All data is synthetic. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
(async () => {
  const server = http.createServer((req, res) => {
    const js = req.url === '/heating-curve.js';
    res.setHeader('Content-Type', js ? 'text/javascript' : 'text/html');
    res.end(fs.readFileSync(js ? path.join(__dirname, '../../custom_components/panasonic_cascade/www/heating-curve.js') : path.join(__dirname, 'fixture.html')));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width:900,height:1000}});
    page.on('pageerror', error => { console.error(error); process.exitCode = 1; });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => document.querySelector('#result').textContent.length > 0);
    const result = JSON.parse(await page.locator('#result').textContent());
    assert.equal(result.error, undefined, result.error);
    assert.equal(result.passed.length, 9);
    console.log('Browser checks:', result.passed.join(', '));
    const svg = page.locator('panasonic-cascade-heating-curve').locator('svg');
    await svg.dispatchEvent('pointerdown', {clientX:400,pointerType:'touch'});
    assert.match(await page.locator('panasonic-cascade-heating-curve').locator('.readout').textContent(), /Außen:.*Wasser:/);
    await page.locator('#result').evaluate(el => el.remove());
    await page.screenshot({path:'heating-curve-desktop.png'});
    for (const width of [320,375,768]) {
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow at ${width}px`);
      await page.screenshot({path:`heating-curve-${width}.png`});
    }
  } finally { if (browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; });
