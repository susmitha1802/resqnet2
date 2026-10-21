const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const counts = (volunteer = 1, ngo = 1, already_recorded = 0) => ({ success: true,
  pings_created: volunteer + ngo, pings_sent: volunteer + ngo, by_role: { volunteer, ngo }, already_recorded });

// Execute actual local API, shared auth, dashboard and inline scripts in HTML order.
// Mapping/CDN scripts and automatic dashboard initialization are outside this focused DOM harness.
function page(role = 'volunteer', server = {}) {
  const html = read(role+'-dashboard.html');
  const elements = new Map(), calls = [], messages = [], storage = new Map();
  let notificationButtons = [];
  const attributes = text => Object.fromEntries([...text.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
  function makeElement(attrs = {}) {
    let markup = '';
    const el = { attrs, style: {}, textContent: '', disabled: false, classList: { add() {}, toggle() {} },
      addEventListener() {}, remove() { elements.delete(attrs.id); },
      insertAdjacentHTML(_position, value) {
        const inserted = makeElement({ id: 'preparedness-banner' });
        elements.set('preparedness-banner', inserted); inserted.innerHTML = value;
      } };
    Object.defineProperty(el, 'innerHTML', { get: () => markup, set: value => {
      markup = value;
      if (['ping-banner', 'preparedness-banner'].includes(attrs.id)) {
        notificationButtons = [...value.matchAll(/<button\b([^>]+)>/g)].map(m => {
          const button = makeElement(attributes(m[1])); button.disabled = /\bdisabled\b/.test(m[1]); return button;
        });
      }
    } });
    return el;
  }
  for (const tag of html.matchAll(/<[^>]+\bid="[^"]+"[^>]*>/g)) {
    const attrs = attributes(tag[0]); elements.set(attrs.id, makeElement(attrs));
  }
  const statsTag = html.match(/<[^>]+class="[^"]*stats-grid-4[^>]+>/);
  const statsAnchor = statsTag ? makeElement(attributes(statsTag[0])) : null;
  const batchButton = makeElement({ 'data-notify': '', onclick: 'notifyAllResponders()' });
  storage.set('resqnet_token', 'synthetic-test-token');
  storage.set('resqnet_user', JSON.stringify({ user_id: 1, name: 'Fixture', role }));
  server.pingStatus ??= 'Sent';
  const response = (status, data, malformed = false) => ({ status, ok: status >= 200 && status < 300,
    json: async () => { if (malformed) throw new SyntaxError('Fixture invalid JSON'); return structuredClone(data); } });
  const context = { console, AbortController, setTimeout: () => 1, clearTimeout() {}, setInterval() {},
    location: { hostname: '127.0.0.1', href: '' }, addEventListener() {},
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    document: { addEventListener() {}, getElementById: id => elements.get(id) || null,
      querySelector: selector => selector === '.stats-grid-4' ? statsAnchor : null,
      querySelectorAll: selector => selector === '[data-notify]' ? [batchButton]
        : selector.startsWith('[data-ping-id=') ? notificationButtons.filter(b => selector.includes('"'+b.attrs['data-ping-id']+'"')) : [] },
    fetch: async (url, options) => {
      const endpoint = new URL(url).pathname;
      calls.push({ endpoint, ...options });
      if (server.networkError && options.method === 'PUT') throw new Error('Fixture network unavailable');
      if (endpoint === '/preparedness/my-pings') {
        if (server.failReads) return response(503, { success: false, message: 'Fixture read unavailable' });
        return response(200, { success: true, pings: [{ ping_id: 7, status: server.pingStatus,
          alert_type: 'Storm', severity: 'Watch', description: 'Unverified fixture advisory' }] });
      }
      if (endpoint === '/preparedness/ping/7') {
        if (server.waitForPut) await server.waitForPut();
        const status = server.putStatus ?? 200;
        const submitted = JSON.parse(options.body).status;
        const body = server.putBody ?? { success: true, ping: { ping_id: 7, status: submitted } };
        if (status === 200 && body.success && body.ping) server.pingStatus = submitted;
        if (server.failReadsAfterWrite) server.failReads = true;
        return response(status, body, server.malformed);
      }
      if (endpoint === '/alerts') return response(server.readStatus ?? 200,
        server.alertsBody ?? { success: true, alerts: [{ alert_id: 1 }, { alert_id: 2 }] });
      if (endpoint.endsWith('/notify')) {
        if (server.waitForPut) await server.waitForPut();
        const id = Number(endpoint.split('/')[2]);
        const result = server.results?.[id] ?? { status: 200, body: counts() };
        return response(result.status, result.body, server.malformed);
      }
      if (endpoint.endsWith('/responses')) return response(server.readStatus ?? 200,
        { success: true, responses: [{ user_name: 'Fixture', status: 'Sent' }] });
      throw new Error('Unexpected fixture request: '+endpoint);
    } };
  context.window = context;
  vm.createContext(context);
  const executed = [];
  for (const script of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
    const src = attributes(script[1]).src;
    if (src && (!src.startsWith('js/') || src.startsWith('js/leaflet-map.js'))) continue;
    const code = src ? read(src.split('?')[0]) : script[2];
    vm.runInContext(code, context, { filename: src || role+'-inline.js' });
    executed.push(code);
  }
  context.Toast.show = (message, kind) => messages.push({ message, kind });
  const banner = () => elements.get(role === 'volunteer' ? 'ping-banner' : 'preparedness-banner');
  const click = status => {
    const button = notificationButtons.find(b => b.attrs.onclick?.includes("'"+status+"'"));
    assert.ok(button, 'Actual rendered response control missing');
    return vm.runInContext(button.attrs.onclick, context);
  };
  return { context, elements, calls, messages, storage, server, banner, click, notificationButtons: () => notificationButtons,
    batchButton, executed, run: code => vm.runInContext(code, context) };
}

test('volunteer HTML and external JS define exactly one acknowledgement handler', () => {
  const s = page();
  assert.equal(s.executed.join('\n').match(/(?:async )?function respondToPing\(/g).length, 1);
  assert.doesNotMatch(read('volunteer-dashboard.html'), /respondToPing\('Acknowledged'\)|loadMyPings/);
});

for (const role of ['volunteer', 'ngo']) {
  test(`${role}: actual rendered controls use ID/status and persisted responses survive reload`, async () => {
    for (const status of ['Acknowledged', 'Unavailable']) {
      const server = {};
      const s = page(role, server);
      await s.context.loadPreparednessAlerts();
      assert.match(s.banner().innerHTML, /Awaiting your response/);
      await s.click(status);
      const write = s.calls.find(c => c.method === 'PUT');
      assert.equal(write.endpoint, '/preparedness/ping/7');
      assert.deepEqual(JSON.parse(write.body), { status });
      assert.ok(write.headers.Authorization.startsWith('Bearer '));
      assert.match(s.banner().innerHTML, new RegExp('Response saved: '+status));
      const reloaded = page(role, server);
      await reloaded.context.loadPreparednessAlerts();
      assert.match(reloaded.banner().innerHTML, new RegExp('Response saved: '+status));
      assert.equal(reloaded.notificationButtons().length, 0);
    }
  });

  test(`${role}: failed HTTP/API results never hide pending alerts or show success`, async () => {
    for (const status of [400, 401, 403, 409, 503, 200]) {
      const s = page(role, { putStatus: status, putBody: { success: status !== 200,
        message: 'Fixture response rejected', ping: { ping_id: 7, status: 'Acknowledged' } } });
      await s.context.loadPreparednessAlerts();
      const before = s.banner().innerHTML;
      await s.click('Acknowledged');
      assert.equal(s.banner().innerHTML, before);
      assert.equal(s.messages.some(m => m.kind === 'success'), false);
      assert.ok(s.messages.some(m => m.kind === 'danger'));
      assert.ok(s.notificationButtons().every(b => !b.disabled));
      if (status === 401) {
        assert.equal(s.storage.has('resqnet_token'), false);
        assert.match(s.context.location.href, /^auth.html/);
      }
    }
  });
}

test('network/JSON errors retain pending UI; successful writes with failed refresh are distinguished', async () => {
  for (const failure of [{ networkError: true }, { malformed: true }, { putBody: { success: true } }]) {
    const s = page('volunteer', failure);
    await s.context.loadPreparednessAlerts();
    await s.click('Acknowledged');
    assert.match(s.banner().innerHTML, /Awaiting your response/);
    assert.equal(s.messages.some(m => m.kind === 'success'), false);
  }
  const s = page('volunteer', { failReadsAfterWrite: true });
  await s.context.loadPreparednessAlerts();
  await s.click('Acknowledged');
  assert.equal(s.server.pingStatus, 'Acknowledged');
  assert.ok(s.messages.some(m => m.kind === 'warning' && /saved.*could not refresh/.test(m.message)));
  assert.match(s.banner().innerHTML, /Awaiting your response/);
});

test('duplicate acknowledgement clicks and invalid statuses cannot create extra writes', async () => {
  let release;
  const s = page('volunteer', { waitForPut: () => new Promise(resolve => { release = resolve; }) });
  await s.context.loadPreparednessAlerts();
  const first = s.click('Acknowledged');
  await s.click('Acknowledged');
  assert.ok(s.notificationButtons().every(b => b.disabled));
  assert.equal(s.calls.filter(c => c.method === 'PUT').length, 1);
  release(); await first;
  await s.context.respondToPing(7, 'Ready');
  assert.equal(s.calls.filter(c => c.method === 'PUT').length, 1);
});

test('nearest NGO action is explicitly unavailable and makes no delivery claim or API call', async () => {
  const s = page();
  const card = s.context.renderRequestCard({ request_id: 7, request_type: 'Rescue', status: 'Pending' }, 60);
  assert.match(card, /notification unavailable/);
  assert.doesNotMatch(card, /onclick="notifyNearestNGO/);
  await s.context.notifyNearestNGO(7);
  assert.equal(s.calls.length, 0);
  assert.equal(s.messages.at(-1).kind, 'warning');
});

test('actual admin bulk control reports combined persisted counts and partial failures', async () => {
  const s = page('admin', { results: { 1: { status: 200, body: counts() },
    2: { status: 503, body: { ...counts(100, 100), message: 'Fixture store unavailable' } } } });
  const handler = read('admin-dashboard.html').match(/onclick="(notifyAllResponders\([^\"]*\))"/)[1];
  assert.equal(handler, 'notifyAllResponders()');
  await s.run(handler);
  assert.equal(s.messages.at(-1).kind, 'warning');
  assert.match(s.messages.at(-1).message, /2 new in-app alert records \(1 volunteer, 1 NGO\)/);
  assert.match(s.messages.at(-1).message, /1 advisories failed or unconfirmed/);
  assert.match(s.messages.at(-1).message, /No external delivery or acknowledgement confirmed/);
  assert.equal(s.batchButton.disabled, false);
});

test('admin failures, zero records and failed listing cannot be reported as successful delivery', async () => {
  for (const status of [400, 401, 403, 409, 503]) {
    const s = page('admin', { results: { 1: { status, body: counts() }, 2: { status, body: counts() } } });
    await s.context.notifyAllResponders();
    assert.equal(s.messages.some(m => m.kind === 'success'), false);
    assert.equal(s.messages.at(-1).kind, 'danger');
    assert.match(s.messages.at(-1).message, /0 new in-app alert records/);
  }
  const zero = page('admin', { results: { 1: { status: 200, body: counts(0, 0, 2) } } });
  await zero.context.notifyAll(1);
  assert.equal(zero.messages.at(-1).kind, 'info');
  assert.match(zero.messages.at(-1).message, /0 new.*2 already recorded/);
  const missing = page('admin', { readStatus: 503 });
  await missing.context.notifyAllResponders();
  assert.equal(missing.calls.some(c => c.method === 'PUT'), false);
  assert.equal(missing.messages.at(-1).kind, 'danger');
});

test('admin single and bulk controls share a duplicate-click guard; responses distinguish awaiting reply', async () => {
  let release;
  const s = page('admin', { waitForPut: () => new Promise(resolve => { release = resolve; }) });
  const first = s.context.notifyAll(1);
  await Promise.resolve();
  await s.context.notifyAllResponders();
  assert.equal(s.calls.filter(c => c.method === 'PUT').length, 1);
  assert.equal(s.batchButton.disabled, true);
  release(); await first;
  assert.equal(s.batchButton.disabled, false);
  await s.context.viewResponses(1);
  assert.match(s.messages.at(-1).message, /Awaiting response/);
  assert.doesNotMatch(s.messages.at(-1).message, /Acknowledged/);
});
