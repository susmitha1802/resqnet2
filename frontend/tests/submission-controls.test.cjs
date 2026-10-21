const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

function page(script, html) {
  const nodes = new Map(), calls = [], notices = [];
  for (const match of read(html).matchAll(/\bid="([^"]+)"/g)) nodes.set(match[1], {
    innerHTML: '', textContent: '', value: '', style: {}, classList: { add() {}, remove() {} },
    scrollIntoView() {} });
  const context = { console, window: {}, document: { addEventListener() {},
    getElementById: id => nodes.get(id), querySelectorAll: () => [] },
    Api: { get: async endpoint => {
      calls.push(['GET', endpoint]);
      return ({ '/admin/users': { success: true, users: [{ user_id: 1, name: '<Admin>', role: 'admin', availability: 'available' }] },
        '/admin/volunteers': { success: true, volunteers: [{ volunteer_id: 2, user_name: 'Test', availability_status: 'on_task', assigned_tasks: 1, completed_tasks: 0 }] },
        '/admin/resources?limit=100&offset=0': { success: true, total: 1, resources: [{ resource_id: 3, ngo_name: 'Team', name: 'Water', quantity: 4, unit: 'cases', location: 'Store', allocated_to: null }] },
        '/ngo/resources': { success: true, resources: [] } })[endpoint] || { success: true, requests: [] };
    }, put: async (endpoint, body) => { calls.push(['PUT', endpoint, body]); return { success: true }; } },
    Toast: { show: (...args) => notices.push(args) },
    timeAgo: () => 'recent', priorityBadge: x => x, statusBadge: x => x,
    requestAnimationFrame: callback => callback(), setInterval() {}, setTimeout() {} };
  vm.createContext(context);
  vm.runInContext(read('js/' + script), context);
  return { context, nodes, calls, notices, run: code => vm.runInContext(code, context) };
}

test('actual admin dashboard lists people/resources and sends permitted correction contracts', async () => {
  const s = page('admin-dashboard.js', 'admin-dashboard.html');
  assert.ok(s.nodes.has('section-users') && s.nodes.has('section-resources'));
  await s.context.loadAdminPeople();
  await s.context.loadAdminResources();
  assert.match(s.nodes.get('admin-users-tbody').innerHTML, /&lt;Admin&gt;/);
  assert.match(s.nodes.get('admin-resources-tbody').innerHTML, /Water/);
  s.nodes.set('report-type-7', { value: 'Flood' });
  s.context.loadDisasters = async () => {};
  s.context.loadAnalytics = async () => {};
  s.context.loadDashboard = async () => {};
  s.context.loadRequests = async () => {};
  await s.context.correctReportType(7);
  await s.context.restoreDuplicate(9);
  assert.deepEqual(s.calls.filter(c => c[0] === 'PUT').map(c => c[1]),
    ['/admin/report/7/override', '/help-request/status']);
  assert.equal(s.calls.find(c => c[1] === '/help-request/status')[2].status, 'Pending');
});

test('actual NGO dashboard edits only unallocated resource through owner API', async () => {
  const s = page('ngo-dashboard.js', 'ngo-dashboard.html');
  s.run('inventory = [{resource_id: 4, name: "Water", quantity: 5, location: "Store", allocated_to: null}]');
  s.context.editResource(4);
  assert.equal(s.nodes.get('edit-resource-quantity').value, 5);
  s.nodes.get('edit-resource-quantity').value = '8';
  s.nodes.get('edit-resource-location').value = 'New store';
  // The existing inventory loader refreshes dashboard statistics after a save.
  s.context.loadStats = async () => {};
  await s.context.saveResourceEdit();
  assert.equal(s.calls.find(c => c[0] === 'PUT')[1], '/ngo/resources/4');
  assert.equal(s.calls.find(c => c[0] === 'PUT')[2].quantity, 8);
});

test('NGO allocation offers every backend-eligible active SOS', () => {
  const s = page('ngo-dashboard.js', 'ngo-dashboard.html');
  s.run(`allRequests = ['Pending', 'Accepted', 'En Route', 'On Site', 'Completed', 'Duplicate']
    .map((status, index) => ({request_id: index + 1, request_type: 'Rescue', status}))`);
  s.context.updateAllocationRequestDropdown();
  const options = s.nodes.get('alloc-request').innerHTML;
  for (const id of [1, 2, 3, 4]) assert.match(options, new RegExp(`value="${id}"`));
  for (const id of [5, 6]) assert.doesNotMatch(options, new RegExp(`value="${id}"`));
});

test('citizen progress snapshots use current status and update time without unread badge', () => {
  const s = page('user-dashboard.js', 'user-dashboard.html');
  const times = [];
  s.context.timeAgo = value => { times.push(value); return 'recent'; };
  s.run(`currentRequests = [{request_id: 1, request_type: 'Rescue', status: 'On Site',
    progress_status: 'Awaiting admin verification', created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z'}]`);
  s.context.loadNotifications();
  assert.match(s.nodes.get('notif-list').innerHTML, /Awaiting admin verification/);
  assert.equal(times[0], '2026-01-02T00:00:00Z');
  assert.equal(s.nodes.get('notif-badge').style.display, 'none');
});
