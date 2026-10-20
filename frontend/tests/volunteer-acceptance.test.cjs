const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const calls = [], messages = [], logouts = [];
  const context = {
    window: {}, document: { addEventListener() {}, getElementById() { return null; } },
    Session: { getToken: () => 'jwt-token', logout: message => logouts.push(message) },
    Toast: { show: (message, kind) => messages.push({ message, kind }) },
    Api: { BASE: 'http://local-api', headers: () => ({ Authorization: 'Bearer jwt-token', 'Content-Type': 'application/json' }),
      fetchWithTimeout: async (url, options) => { calls.push({ url, options }); return { ok: true, status: 200, json: async () => ({ success: true }) }; } },
    timeAgo: () => 'now', console,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/volunteer-dashboard.js'), 'utf8'), context);
  const loadNearbyRequests = context.loadNearbyRequests;
  vm.runInContext(`nearbyRequests = [{request_id: 7, request_type: 'Rescue', status: 'Pending', distance: 2}];
    loadNearbyRequests = async () => true; loadMyTasks = async () => true;`, context);
  return { context, calls, messages, logouts, loadNearbyRequests, run: source => vm.runInContext(source, context) };
}

test('acceptance sends the authenticated PUT contract, refreshes and prevents replay', async () => {
  const s = setup();
  s.run('let refreshes = 0; loadNearbyRequests = async () => { refreshes++; return true; }; loadMyTasks = async () => { refreshes++; return true; };');
  await s.context.acceptTask(7);
  assert.equal(s.calls.length, 1);
  assert.equal(s.calls[0].url, 'http://local-api/volunteer/accept-task');
  assert.equal(s.calls[0].options.method, 'PUT');
  assert.equal(s.calls[0].options.headers.Authorization, 'Bearer jwt-token');
  assert.deepEqual(JSON.parse(s.calls[0].options.body), { request_id: 7 });
  assert.equal(s.run('refreshes'), 2);
  assert.equal(s.run('nearbyRequests[0].status'), 'Accepted');
  assert.equal(s.messages.filter(m => m.kind === 'success').length, 1);
  await s.context.acceptTask(7);
  assert.equal(s.calls.length, 1);
});

test('incident reports and non-pending or invalid requests never expose Accept', () => {
  const s = setup();
  for (const fields of [{ is_report: true }, { request_id: 'R4' }, { status: 'Accepted' },
                         { request_type: 'Flood' }, { request_id: 0 }]) {
    const card = s.context.renderRequestCard({ request_id: 7, request_type: 'Rescue', status: 'Pending', ...fields }, 2);
    assert.doesNotMatch(card, /onclick="acceptTask/);
  }
  assert.match(s.context.renderRequestCard({ request_id: 7, request_type: 'Rescue', status: 'Pending' }, 2), /onclick="acceptTask\(7\)/);
  assert.doesNotMatch(s.context.renderRequestCard({ request_id: 7, request_type: 'Rescue', status: 'Pending' }, 60), /onclick="acceptTask/);
});

test('actual request/report feeds keep incident cards information-only', async () => {
  const s = setup();
  const container = { innerHTML: '' };
  s.context.document.getElementById = id => id === 'nearby-requests' ? container : null;
  s.run('volunteerLat = 17.4; volunteerLng = 78.4;');
  s.context.Api.get = async url => url === '/help-requests'
    ? { success: true, requests: [{ request_id: 7, request_type: 'Rescue', status: 'Pending', latitude: 17.4, longitude: 78.4 }] }
    : { success: true, reports: [{ report_id: 7, disaster_type: 'Flood', latitude: 17.4, longitude: 78.4 }] };
  assert.equal(await s.loadNearbyRequests(), true);
  assert.equal((container.innerHTML.match(/onclick="acceptTask/g) || []).length, 1);
  assert.match(container.innerHTML, /Incident report · information only/);
  assert.doesNotMatch(container.innerHTML, /acceptTask\(R7\)/);
  await s.context.acceptTask('R7');
  assert.equal(s.calls.length, 0);
  s.context.Api.get = async () => null;
  assert.equal(await s.loadNearbyRequests(), false);
  assert.match(container.innerHTML, /Incident report · information only/);
});

test('double click is blocked until the first request completes', async () => {
  const s = setup();
  let resolve;
  s.context.Api.fetchWithTimeout = () => { s.calls.push('request'); return new Promise(done => { resolve = done; }); };
  const first = s.context.acceptTask(7);
  assert.equal(s.run('acceptanceInFlight'), true);
  assert.match(s.context.renderRequestCard({ request_id: 8, request_type: 'Food', status: 'Pending' }, 2), /disabled/);
  await s.context.acceptTask(7);
  assert.equal(s.calls.length, 1);
  resolve({ ok: true, status: 200, json: async () => ({ success: true }) });
  await first;
  assert.equal(s.run('acceptanceInFlight'), false);
});

test('expired sessions log out; forbidden and conflict responses never show success', async () => {
  for (const status of [401, 422, 403, 409, 500]) {
    const s = setup();
    s.context.Api.fetchWithTimeout = async () => ({ ok: false, status, json: async () => ({ message: 'Task unavailable' }) });
    await s.context.acceptTask(7);
    assert.equal(s.messages.some(m => m.kind === 'success'), false);
    assert.equal(s.logouts.length, [401, 422].includes(status) ? 1 : 0);
    if ([403, 409, 500].includes(status)) assert.equal(s.messages[0].message, 'Task unavailable');
    assert.equal(s.run('acceptanceInFlight'), false);
  }
});

test('network and invalid JSON failures restore controls with an uncertain-result message', async () => {
  for (const fetch of [async () => { throw new Error('offline'); },
                       async () => ({ status: 502, json: async () => { throw new Error('not JSON'); } })]) {
    const s = setup();
    s.context.Api.fetchWithTimeout = fetch;
    await s.context.acceptTask(7);
    assert.match(s.messages[0].message, /Could not confirm/);
    assert.equal(s.run('acceptanceInFlight'), false);
  }
});

test('successful assignment remains successful when dashboard refresh fails', async () => {
  const s = setup();
  s.run('loadMyTasks = async () => false;');
  await s.context.acceptTask(7);
  assert.equal(s.messages[0].kind, 'success');
  assert.match(s.messages[1].message, /Task accepted, but the dashboard/);
  assert.equal(s.run('isAssignableRequest(nearbyRequests[0])'), false);
});
