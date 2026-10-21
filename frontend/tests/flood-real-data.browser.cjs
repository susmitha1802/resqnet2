// Opt-in real-data smoke. Start flood_real_data_smoke.py --serve first.
// Flood responses are real HTTP; only unrelated incident APIs and map tiles are stubbed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { setTimeout: delay } = require('node:timers/promises');

async function main() {
  const origin = process.env.FLOOD_SMOKE_ORIGIN || 'http://127.0.0.1:8766';
  assert.equal(new URL(origin).hostname, '127.0.0.1', 'Use only the isolated loopback smoke server');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-flood-'));
  const chrome = spawn(process.env.CHROME_BINARY || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
      '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let ws, send, sequence = 0;
  const pending = new Map();
  try {
    let port;
    for (let i = 0; i < 100 && !port; i++) {
      try { port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch (_) {}
      if (!port) await delay(100);
    }
    assert.match(port || '', /^\d+$/);
    const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    ws = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
    await once(ws, 'open');
    send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ id, method, params }));
    });
    ws.addEventListener('message', ({ data }) => {
      const m = JSON.parse(data);
      if (m.id) {
        const task = pending.get(m.id);
        if (!task) return;
        clearTimeout(task.timer); pending.delete(m.id);
        if (m.error) task.reject(new Error(m.error.message)); else task.resolve(m.result);
      } else if (m.method === 'Fetch.requestPaused') {
        const { requestId, request } = m.params;
        const tile = request.url.includes('tile.openstreetmap.org');
        const body = tile ? Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6JXcAAAAASUVORK5CYII=', 'base64')
          : Buffer.from(JSON.stringify({ success: true, requests: [], reports: [], volunteers: [], zones: [], locations: [] }));
        send('Fetch.fulfillRequest', { requestId, responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: tile ? 'image/png' : 'application/json' }], body: body.toString('base64') }).catch(() => {});
      }
    });
    await send('Page.enable');
    await send('Fetch.enable', { patterns: ['*tile.openstreetmap.org*', '*/map/data*', '*/map/risk-zones*', '*/ngo/locations*'].map(urlPattern => ({ urlPattern })) });
    await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('resqnet_api_base', ${JSON.stringify(origin)});` });
    const evaluate = async expression => {
      const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    };
    const waitFor = async (expression, label) => {
      for (let i = 0; i < 150; i++) {
        if (await evaluate(expression)) return;
        await delay(100);
      }
      throw new Error(`Timed out: ${label}`);
    };
    await send('Page.navigate', { url: `${origin}/map.html` });
    await waitFor(`document.readyState === 'complete' && !!document.querySelector('.flood-panel')`, 'map initialization');
    const initial = await evaluate('({lat:map.getCenter().lat,lng:map.getCenter().lng,zoom:map.getZoom()})');
    await evaluate(`document.querySelector('.flood-panel > details').open=true;document.querySelector('[data-load]').click()`);
    await waitFor(`document.querySelector('[data-metrics]').children.length===4 && !document.querySelector('[data-load]').disabled`, 'real event summary');
    const details = await evaluate(`document.querySelector('[data-summary]').textContent`);
    assert.match(details, /2024-08-13/); assert.match(details, /2024-08-25/);
    assert.match(details, /NOT_READY/); assert.match(details, /SUPPORTED: 0 pixels/);
    assert.deepEqual(await evaluate('({lat:map.getCenter().lat,lng:map.getCenter().lng,zoom:map.getZoom()})'), initial);
    const expected = [2000, 274, 276, 16];
    for (let index = 0; index < 4; index++) {
      const row = `document.querySelectorAll('.flood-layer-row')[${index}]`;
      await evaluate(`(()=>{const t=${row}.querySelector('input');t.checked=true;t.dispatchEvent(new Event('change'));})()`);
      await waitFor(`${row}.querySelector('span').textContent.includes('features loaded') && !${row}.querySelector('button').disabled`, `layer ${index}`);
      for (let page = 0; page < 8 && !(await evaluate(`${row}.querySelector('button').hidden`)); page++) {
        await evaluate(`${row}.querySelector('button').click()`);
        await waitFor(`!${row}.querySelector('button').disabled`, 'next real page');
      }
      const count = await evaluate(`${row}.querySelector('span').textContent`);
      assert.match(count, new RegExp(`${expected[index]} features loaded`));
      assert.match(count, index === 0 ? /partial/ : /complete/);
      assert.equal(await evaluate(`${row}.querySelector('button').hidden`), true);
    }
    const sizes = await evaluate(`(()=>{const sizes=[];map.eachLayer(l=>{if(l instanceof L.GeoJSON)sizes.push(l.getLayers().length);});return sizes;})()`);
    assert.deepEqual(sizes.sort((a,b)=>a-b), expected.slice().sort((a,b)=>a-b));
    await evaluate(`document.querySelector('[data-focus]').click()`);
    await waitFor(`Math.abs(map.getCenter().lat-9.95)<.02 && Math.abs(map.getCenter().lng-76.35)<.02`, 'event bounds');
    await evaluate(`(()=>{const t=document.querySelector('.flood-layer-row input');t.checked=false;t.dispatchEvent(new Event('change'));})()`);
    assert.equal(await evaluate(`(()=>{let n=0;map.eachLayer(l=>{if(l instanceof L.GeoJSON)n++;});return n;})()`), 3);
    console.log('PASS real-data browser: actual map + proxy + event API; observation dates, NOT_READY, four overlays, pagination, 2000-feature partial cap, focus and toggle removal.');
  } finally {
    if (send && ws?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
    ws?.close();
    if (chrome.exitCode === null) chrome.kill();
    if (path.dirname(path.resolve(profile)) === path.resolve(os.tmpdir()) && path.basename(profile).startsWith('resqnet-flood-')) {
      for (let i = 0; i < 20; i++) {
        try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (_) { await delay(100); }
      }
    }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
