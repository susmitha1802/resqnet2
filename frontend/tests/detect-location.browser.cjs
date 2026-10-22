// Optional focused browser smoke: installed Chrome + Node's built-in CDP WebSocket.
// GPS/address responses are simulated; no SOS submissions or real OSM tile requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { setTimeout: delay } = require('node:timers/promises');

async function main() {
  const root = path.resolve(__dirname, '..');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'resqnet-location-'));
  const chrome = process.env.CHROME_BINARY || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const server = http.createServer((request, response) => {
    const file = path.resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://local').pathname));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404); response.end(); return;
    }
    response.setHeader('Content-Type', { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(response);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const origin = `http://127.0.0.1:${server.address().port}`;
  const child = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let ws, send, nextId = 0, mode = 'success';
  const pending = new Map();
  try {
    const activePort = path.join(profile, 'DevToolsActivePort');
    let port;
    for (let n = 0; n < 100; n++) {
      try { port = fs.readFileSync(activePort, 'utf8').split('\n')[0]; } catch (error) {
        if (!['ENOENT', 'EBUSY'].includes(error.code)) throw error;
      }
      if (/^\d+$/.test(port || '')) break;
      await delay(100);
    }
    assert.match(port || '', /^\d+$/, 'Chrome debugging endpoint did not start');
    const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    ws = new WebSocket(pages.find(target => target.type === 'page').webSocketDebuggerUrl);
    await once(ws, 'open');
    send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
    ws.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      if (message.id) {
        const task = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) task?.reject(new Error(message.error.message)); else task?.resolve(message.result);
      } else if (message.method === 'Fetch.requestPaused') {
        const { requestId, request } = message.params;
        let body, type;
        if (request.url.includes('/geocode?')) {
          body = JSON.stringify({ success: true, result: request.url.includes('kind=search')
            ? [{ lat: '28.6139', lon: '77.2090', display_name: 'New Delhi, India' }]
            : { display_name: 'Mock Road, Mock Town, Mock State' } });
          type = 'application/json';
        } else if (request.url.includes('/map/demo-scenarios')) {
          body = JSON.stringify({success:true,scenarios:[{title:'Fictional coastal exercise',
            latitude:17.6868,longitude:83.2185,is_demo:true,
            notice:'FICTIONAL DEMO location. Not a real incident or alert.'}]});
          type = 'application/json';
        } else if (request.url.includes('/map/data')) {
          body = JSON.stringify({ success: true, requests: [{ request_id: 1, request_type: 'Food', priority_level: 'Medium',
            number_of_people: 2, latitude: 9.9312, longitude: 76.2673, status: 'On Site', source: 'Community SOS request' }],
            reports: [{ report_id: 2, disaster_type: 'Flood', latitude: 12.9716, longitude: 77.5946,
              status: 'Reported; not independently verified', source: 'Community incident report (unverified)', description: 'Bengaluru observation' }],
            volunteers: [{ volunteer_id: 3, user_name: 'Test volunteer', availability_status: 'available', last_location_lat: 12.97, last_location_lng: 77.59 }] });
          type = 'application/json';
        } else if (request.url.includes('/map/risk-zones')) {
          body = JSON.stringify({ zones: [
            { lat: 17.4401, lng: 78.4487, radius_km: 50, alert_type: 'Flood', severity: 'Emergency', risk_level: 'High',
              description: 'Severe flash flooding expected in the Hyderabad region over the next 48 hours.' },
            { lat: 9.9312, lng: 76.2673, radius_km: 2, alert_type: 'Flood', severity: 'Watch', risk_level: 'Low',
              description: 'Manual observation', source: 'Manual', status: 'Active alert' }
          ] }); type = 'application/json';
        } else if (request.url.includes('/ngo/locations')) {
          body = JSON.stringify({ locations: [
            { name: 'Valid depot', latitude: 0, longitude: 0 },
            { name: 'Unknown depot', latitude: null, longitude: null },
            { name: 'Invalid depot', latitude: 999, longitude: 77 }
          ] }); type = 'application/json';
        } else if (/tile\.openstreetmap\.org|basemaps\.cartocdn\.com/.test(request.url)) {
          body = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6JXcAAAAASUVORK5CYII=', 'base64');
          type = 'image/png';
        }
        const action = body !== undefined ? send('Fetch.fulfillRequest', { requestId,
          responseCode: mode === 'lookup-failure' && type === 'application/json' ? 503 : 200,
          responseHeaders: [{ name: 'Content-Type', value: type }, { name: 'Access-Control-Allow-Origin', value: '*' },
            { name: 'Access-Control-Allow-Headers', value: 'Content-Type, Authorization' }, { name: 'Access-Control-Allow-Methods', value: 'GET, OPTIONS' }],
          body: Buffer.from(body).toString('base64') }) : send('Fetch.continueRequest', { requestId });
        action.catch(() => {});
      }
    });
    await send('Page.enable');
    await send('Fetch.enable', { patterns: ['*/geocode?*', '*tile.openstreetmap.org*', '*basemaps.cartocdn.com*',
      '*/map/data*', '*/map/demo-scenarios*', '*/map/risk-zones*', '*/ngo/locations*'].map(urlPattern => ({ urlPattern })) });
    await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await send('Emulation.setGeolocationOverride', { latitude: 17.4401, longitude: 78.4487, accuracy: 5 });
    await send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('resqnet_user', JSON.stringify({user_id:1,name:'Location Test',role:'reporter'})); localStorage.setItem('resqnet_token','demo-token-location-test'); localStorage.setItem('resqnet_role','reporter');` });
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    for (const page of ['help-request', 'report-disaster']) {
      for (const scenario of ['success', 'lookup-failure', 'denied']) {
        mode = scenario;
        await send('Browser.setPermission', { permission: { name: 'geolocation' }, setting: scenario === 'denied' ? 'denied' : 'granted', origin });
        await send('Page.navigate', { url: `${origin}/${page}.html?location-test=${scenario}` });
        let ready = false;
        for (let n = 0; n < 100; n++) {
          ready = await evaluate(`document.readyState === 'complete' && typeof getLocation === 'function' && typeof pickerMap !== 'undefined' && pickerMap !== null`);
          if (ready) break;
          await delay(100);
        }
        assert.ok(ready, `${page}: Leaflet and form did not initialize`);
        if (scenario === 'denied') await evaluate(`setLocationFields(12, 77, 'Manual address')`);
        const point = await evaluate(`(() => { const b=document.getElementById('get-location-btn'); b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2; return {x,y,hit:!!document.elementFromPoint(x,y)?.closest('#get-location-btn')}; })()`);
        assert.ok(point.hit, `${page}: another element covers Detect Location`);
        await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
        await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
        for (let n = 0; n < 100; n++) {
          const done = await evaluate(`document.getElementById('get-location-btn').disabled === false && document.getElementById('lat-input').value !== ''`);
          if (done) break;
          await delay(100);
        }
        const result = await evaluate(`({lat:document.getElementById('lat-input').value,lng:document.getElementById('lng-input').value,url:location.href,visible:getComputedStyle(document.getElementById('${page === 'help-request' ? 'help-form' : 'report-form'}')).display})`);
        assert.equal(result.lat, scenario === 'denied' ? '12.000000' : '17.440100');
        assert.equal(result.lng, scenario === 'denied' ? '77.000000' : '78.448700');
        assert.ok(result.url.startsWith(`${origin}/${page}.html`));
        assert.notEqual(result.visible, 'none');
        const targets = await send('Target.getTargets');
        assert.equal(targets.targetInfos.filter(target => target.type === 'page').length, 1, 'Unexpected navigation opened a new tab');
        console.log(`PASS browser: ${page}, ${scenario}, physical button click, coordinates retained, no navigation/submission`);
      }
    }
    mode = 'map';
    await send('Page.navigate', { url: `${origin}/map.html` });
    for (let n = 0; n < 100; n++) {
      if (await evaluate(`typeof L !== 'undefined' && typeof map !== 'undefined' && map instanceof L.Map && document.getElementById('live-count').textContent === '2'`)) break;
      await delay(100);
    }
    assert.equal(await evaluate('map.getZoom()'), 5);
    assert.ok(Math.abs(await evaluate('map.getCenter().lat') - 20.5937) < .01);
    assert.equal(await evaluate(`(() => { let demo=false; map.eachLayer(l=>{if(l.getPopup && String(l.getPopup()?.getContent()).includes('Severe flash flooding')) demo=true;});return demo; })()`), false);
    assert.match(await evaluate(`document.querySelector('.flood-panel').textContent`), /Unvalidated results/);
    for (let n = 0; n < 100; n++) {
      if (await evaluate(`(() => { let found=false; map.eachLayer(l=>{if(l.getPopup && String(l.getPopup()?.getContent()).includes('Valid depot')) found=true;}); return found; })()`)) break;
      await delay(100);
    }
    const depots = await evaluate(`(() => {const names=[];map.eachLayer(l=>{if(l.getPopup) names.push(String(l.getPopup()?.getContent()));});return names.join(' ');})()`);
    assert.match(depots, /Valid depot/);
    assert.doesNotMatch(depots, /Unknown depot|Invalid depot/);
    console.log('PASS browser: live map overview, valid-only NGO markers, legacy demo alert hidden, Flood Intelligence warning retained');

    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', {url:`${origin}/map.html?demo=1`});
    for (let n=0;n<100;n++) {
      if (await evaluate(`document.getElementById('map-demo-banner')?.hidden === false &&
        [...document.querySelectorAll('.leaflet-marker-icon')].some(el=>el.textContent.includes('DEMO'))`)) break;
      await delay(100);
    }
    assert.match(await evaluate(`document.getElementById('map-demo-banner').textContent`), /FICTIONAL DEMO SCENARIOS/);
    assert.ok(await evaluate(`document.getElementById('map-demo-banner').getBoundingClientRect().right <= innerWidth`));
    assert.equal(await evaluate(`document.getElementById('map-demo-toggle').getAttribute('aria-pressed')`),'true');
    assert.equal(await evaluate(`document.getElementById('live-count').textContent`),'2');
    await evaluate(`document.getElementById('map-demo-toggle').click()`);
    assert.equal(await evaluate(`document.getElementById('map-demo-banner').hidden`),true);
    console.log('PASS browser: opt-in fictional map markers are labeled and separate from live counts');
    await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    await send('Page.navigate', { url: `${origin}/map.html?report_id=2` });
    for (let n = 0; n < 100; n++) {
      if (await evaluate(`window._foundTargetMarker === true && !!document.querySelector('.leaflet-popup-content')`)) break;
      await delay(100);
    }
    const linkedState = await evaluate(`({center:map.getCenter(),found:window._foundTargetMarker})`);
    assert.equal(linkedState.found, true, 'Linked report marker did not render');
    assert.ok(Math.abs(linkedState.center.lat - 12.9716) < .01);
    const popup = await evaluate(`document.querySelector('.leaflet-popup-content').textContent`);
    assert.match(popup, /12\.97160, 77\.59460/);
    assert.match(popup, /not independently verified/);
    assert.match(popup, /Community incident report/);
    await evaluate(`(() => {const input=document.getElementById('map-search-input');input.value='New Delhi';document.getElementById('map-search-input-button').click();})()`);
    for (let n = 0; n < 50; n++) {
      if (await evaluate(`!!document.querySelector('#map-search-results [data-idx]')`)) break;
      await delay(100);
    }
    const searchPoint = await evaluate(`(() => {const r=document.querySelector('#map-search-results [data-idx]').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...searchPoint, button: 'left', clickCount: 1 });
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...searchPoint, button: 'left', clickCount: 1 });
    await evaluate(`(async()=>{await loadMapData();applyMapFilter('Disasters');await loadMapData();})()`);
    assert.ok(Math.abs(await evaluate('map.getCenter().lat') - 28.6139) < .01);
    assert.ok(Math.abs(await evaluate('map.getCenter().lng') - 77.209) < .01);
    console.log('PASS browser: outside-Hyderabad popup matches its record; address selection survives data refresh and filters');

    await send('Page.navigate', { url: `${origin}/map.html?request_id=1` });
    for (let n = 0; n < 100; n++) {
      if (await evaluate(`window._foundTargetMarker === true && !!document.querySelector('.leaflet-popup-content')`)) break;
      await delay(100);
    }
    assert.equal(await evaluate('window._foundTargetMarker'), true, 'Linked SOS marker did not render');
    assert.ok(Math.abs(await evaluate('map.getCenter().lat') - 9.9312) < .01);
    assert.match(await evaluate(`document.querySelector('.leaflet-popup-content').textContent`), /9\.93120, 76\.26730/);
    await evaluate(`(async()=>{map.fire('dragstart');map.panTo([19.076,72.8777],{animate:false});await loadMapData();applyMapFilter('Disasters');await loadMapData();})()`);
    assert.ok(Math.abs(await evaluate('map.getCenter().lat') - 19.076) < .01);
    assert.ok(Math.abs(await evaluate('map.getCenter().lng') - 72.8777) < .01);
    console.log('PASS browser: linked SOS centers on its record; panning survives refresh and filtering');
  } finally {
    if (send && ws?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
    ws?.close();
    if (child.exitCode === null) child.kill();
    await new Promise(resolve => server.close(resolve));
    // Remove only the generated browser profile inside the intended temp directory.
    if (path.dirname(path.resolve(profile)) === path.resolve(os.tmpdir()) && path.basename(profile).startsWith('resqnet-location-')) {
      for (let n = 0; n < 20; n++) {
        try { fs.rmSync(profile, { recursive: true, force: true }); break; } catch (_) { await delay(100); }
      }
    }
  }
}
const watchdog = setTimeout(() => { console.error('Browser smoke timed out'); process.exit(1); }, 55000);
main().then(() => clearTimeout(watchdog), error => { clearTimeout(watchdog); console.error(error); process.exitCode = 1; });
