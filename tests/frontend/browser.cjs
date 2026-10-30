/* Run with Node.js and Playwright/Chromium installed. All data is synthetic. */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
(async () => {
  let lateReady = false;
  const server = http.createServer((req, res) => {
    if (req.url === '/empty') { res.setHeader('Content-Type','text/html'); res.end('<!doctype html><body></body>'); return; }
    const late = req.url.startsWith('/late-card.js?');
    if (late && !lateReady) { res.writeHead(404); res.end('Not ready'); return; }
    const js = req.url.startsWith('/heating-curve.js') || late;
    res.setHeader('Content-Type', js ? 'text/javascript' : 'text/html');
    res.end(fs.readFileSync(js ? path.join(__dirname, '../../custom_components/panasonic_cascade/www/heating-curve.js') : path.join(__dirname, 'fixture.html')));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await (process.env.BROWSER_ENGINE === 'webkit' ? webkit : chromium).launch({headless: true, ...(process.env.BROWSER_EXECUTABLE_PATH ? {executablePath:process.env.BROWSER_EXECUTABLE_PATH} : {})});
    const recovery = await browser.newPage();
    await recovery.goto(`http://127.0.0.1:${server.address().port}/empty`);
    assert.equal(await recovery.evaluate(async () => {
      try { await import('/late-card.js?boot=before'); return false; } catch (_) { return true; }
    }), true);
    lateReady = true;
    assert.equal(await recovery.evaluate(async () => {
      await import('/late-card.js?boot=after');
      return !!customElements.get('panasonic-cascade-heating-curve');
    }), true);
    await recovery.close();
    console.log('Fresh boot resource recovers after initial HTTP 404');
    // Reproduce the early-module race: app.js swaps the global registry after
    // the extra module begins. Use a fresh document for every cold/warm order.
    for (const delay of [0, 30, 150, 400]) {
      const cold = await browser.newPage();
      await cold.goto(`http://127.0.0.1:${server.address().port}/empty`);
      const registered = await cold.evaluate(async delay => {
        document.body.append(document.createElement('home-assistant'));
        const native = window.customElements;
        native.define('early-registration-probe', class extends HTMLElement {});
        const loading = import('/heating-curve.js?cold=' + delay);
        await new Promise(resolve => setTimeout(resolve, delay));
        const definitions = new Map();
        Object.defineProperty(window, 'customElements', {configurable:true, value:{
          get: name => definitions.get(name),
          define: (name, constructor) => { native.define(name, constructor); definitions.set(name, constructor); }
        }});
        // Verify that this fixture actually loses an early native definition.
        if (customElements.get('early-registration-probe')) throw Error('Race fixture did not replace registry');
        customElements.define('home-assistant', class extends HTMLElement {});
        await Promise.all([loading, import('/heating-curve.js?second=' + delay)]);
        return !!customElements.get('panasonic-cascade-heating-curve');
      }, delay);
      assert.equal(registered, true, `Missing curve after registry replacement at ${delay}ms`);
      await cold.close();
    }
    console.log('Cold-load registry replacement and concurrent resource imports recover in all orders');
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
