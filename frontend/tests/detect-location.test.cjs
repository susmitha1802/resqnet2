const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(form) {
  const elements = new Map(), calls = [], messages = [], timers = new Map();
  let timerId = 0, success, failure, options;
  for (const id of ['get-location-btn', 'lat-input', 'lng-input', 'location-input', 'location-display', 'location-status']) {
    elements.set(id, { textContent: id === 'get-location-btn' ? 'Detect Location' : '', value: '', dataset: {}, style: {} });
  }
  const context = {
    document: { getElementById: id => elements.get(id), addEventListener() {}, createElement: () => ({}), head: { appendChild() {} } },
    navigator: { geolocation: { getCurrentPosition(ok, bad, settings) { success = ok; failure = bad; options = settings; } } },
    AbortController, console, Toast: { show: (message, kind) => messages.push({ message, kind }) },
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id),
    fetch: async (url, settings) => { calls.push({ url, settings }); return { ok: true, json: async () => ({ display_name: 'Local Road, Test Town, Test State' }) }; },
  };
  context.window = context;
  vm.createContext(context);
  for (const file of ['leaflet-map.js', `${form}.js`]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../js', file), 'utf8'), context);
  }
  let prevented = false, stopped = false;
  const event = { preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } };
  return { context, elements, calls, messages, timers, event,
    success: () => success({ coords: { latitude: 17.4401, longitude: 78.4487 } }), failure: code => failure({ code }),
    options: () => options, prevented: () => prevented && stopped,
    run: source => vm.runInContext(source, context) };
}

for (const form of ['help-request', 'report']) {
  test(`${form}: click requests GPS, fills existing fields and never navigates or submits`, async () => {
    const s = setup(form);
    const pending = s.context.getLocation(s.event);
    assert.equal(s.prevented(), true);
    assert.equal(s.options().timeout, 10000);
    assert.equal(s.options().maximumAge, 0);
    assert.equal(s.elements.get('get-location-btn').disabled, true);
    s.success();
    await pending;
    assert.equal(s.elements.get('lat-input').value, '17.440100');
    assert.equal(s.elements.get('lng-input').value, '78.448700');
    assert.match(form === 'report' ? s.elements.get('location-input').value : s.elements.get('location-display').textContent, /Local Road/);
    assert.equal(s.calls.length, 1);
    const url = new URL(s.calls[0].url);
    assert.equal(url.origin + url.pathname, 'https://nominatim.openstreetmap.org/reverse');
    assert.equal(url.searchParams.get('format'), 'jsonv2');
    assert.equal(url.searchParams.get('lon'), '78.4487');
    assert.equal(s.calls[0].settings.redirect, 'error');
    assert.equal(s.elements.get('get-location-btn').disabled, false);
    assert.equal(s.elements.get('get-location-btn').textContent, 'Detect Location');
    assert.equal(s.run('userLocation.lat'), 17.4401);
  });

  test(`${form}: coordinates are saved before address lookup completes or fails`, async () => {
    const s = setup(form);
    let reject;
    s.context.fetch = () => new Promise((_, fail) => { reject = fail; });
    const pending = s.context.getLocation(s.event);
    s.success();
    await Promise.resolve();
    assert.equal(s.elements.get('lat-input').value, '17.440100');
    assert.equal(s.run('userLocation.lng'), 78.4487);
    reject(new Error('offline'));
    await pending;
    assert.match(s.messages.at(-1).message, /Coordinates captured/);
    assert.equal(s.elements.get('get-location-btn').disabled, false);
  });

  test(`${form}: denied, unavailable and timed-out GPS preserve manual coordinates and allow retry`, async () => {
    for (const [code, phrase] of [[1, /permission denied/], [2, /unavailable/], [3, /timed out/]]) {
      const s = setup(form);
      s.context.setLocationFields(12, 77, 'Manual address');
      const pending = s.context.getLocation(s.event);
      s.failure(code);
      await pending;
      assert.equal(s.elements.get('lat-input').value, '12.000000');
      assert.match(s.messages.at(-1).message, phrase);
      assert.equal(s.elements.get('get-location-btn').disabled, false);
      assert.equal(s.calls.length, 0);
    }
  });

  test(`${form}: unsupported geolocation does not submit or erase manual selection`, async () => {
    const s = setup(form);
    s.context.setLocationFields(12, 77, 'Manual address');
    s.context.navigator.geolocation = undefined;
    await s.context.getLocation(s.event);
    assert.equal(s.prevented(), true);
    assert.match(s.messages[0].message, /not supported/);
    assert.equal(s.elements.get('lat-input').value, '12.000000');
  });

  test(`${form}: manual map selection wins over a pending GPS address lookup`, async () => {
    const s = setup(form);
    s.elements.set('location-picker-map', {});
    s.context.ResQMap.getOptimalLocation = async () => ({ lat: 20, lng: 78, zoom: 5 });
    s.context.ResQMap.createMap = () => ({ setView() {} });
    s.context.ResQMap.enableLocationPicker = (_map, handler) => { s.manualPick = handler; };
    s.context.ResQMap.attachSearchBar = () => {};
    await s.context.initLocationPicker();
    let resolve;
    s.context.fetch = () => new Promise(done => { resolve = done; });
    const pending = s.context.getLocation(s.event);
    s.success();
    await Promise.resolve();
    await s.manualPick(12, 77, 'Manual address');
    resolve({ ok: true, json: async () => ({ display_name: 'GPS address' }) });
    await pending;
    assert.equal(s.elements.get('lat-input').value, '12.000000');
    assert.match(s.messages.at(-1).message, /manually selected location was kept/);
  });
}

test('reverse lookup handles HTTP/JSON/coverage failures and aborts slow requests', async () => {
  for (const response of [{ ok: false }, { ok: true, json: async () => { throw new Error('HTML'); } },
                           { ok: true, json: async () => ({}) }]) {
    const s = setup('help-request');
    s.context.fetch = async () => response;
    assert.equal(await s.context.ResQMap.reverseGeocode(17, 78), '17.00000, 78.00000');
    assert.equal(s.timers.size, 0);
  }
  const s = setup('report');
  s.context.fetch = (_url, options) => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('timeout'))));
  const pending = s.context.ResQMap.reverseGeocode(17, 78);
  [...s.timers.values()][0]();
  assert.equal(await pending, '17.00000, 78.00000');
  assert.equal(s.timers.size, 0);
});

test('form markup uses non-submit buttons, contains map controls, and retains search/manual pick bindings', () => {
  for (const [page, form] of [['help-request', 'help-request'], ['report-disaster', 'report']]) {
    const html = fs.readFileSync(path.join(__dirname, `../${page}.html`), 'utf8');
    const js = fs.readFileSync(path.join(__dirname, `../js/${form}.js`), 'utf8');
    const button = html.match(/<button\b[^>]*id="get-location-btn"[^>]*>/)[0];
    assert.match(button, /type="button"/);
    assert.doesNotMatch(button, /href=|onclick=/);
    assert.match(html, /id="location-picker-map" style="position:relative;isolation:isolate;/);
    assert.match(js, /addEventListener\('click', getLocation\)/);
    assert.match(js, /ResQMap\.attachSearchBar/);
    assert.match(js, /ResQMap\.enableLocationPicker/);
    assert.match(js, /Session\.isLoggedIn\(\)/);
  }
});
