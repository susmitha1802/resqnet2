const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = name => fs.readFileSync(path.join(__dirname, '../js', name), 'utf8');
function setup() {
  const storage = new Map(), labels = [{ textContent: '' }, { textContent: '' }];
  const context = { window: {}, location: { href: '' },
    localStorage: { getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
    document: { addEventListener() {}, querySelectorAll: () => labels },
    Api: { get: async () => ({ success: true, user: { role: 'volunteer', name: 'Test' } }) },
    setTimeout: fn => fn(), console };
  vm.createContext(context); vm.runInContext(source('main.js'), context);
  return { context, storage, labels, run: code => vm.runInContext(code, context) };
}
test('server profile overrides manipulated role and routes every account correctly', async () => {
  const s = setup();
  for (const [role, page, label] of [['reporter','user','Disaster Reporter'], ['volunteer','volunteer','Volunteer'], ['ngo','ngo','NGO / Organization'], ['admin','admin','Administrator']]) {
    s.run("Session.set({role:'admin'}, 'test-session');");
    s.context.Api.get = async endpoint => { assert.equal(endpoint, '/profile'); return { success: true, user: { role } }; };
    assert.equal(await s.run('Session.verifyRole()'), true);
    s.run('Session.redirectIfLoggedIn()');
    assert.equal(s.context.location.href, page+'-dashboard.html');
    assert.equal(s.labels[0].textContent, label);
    assert.equal(s.labels[1].textContent, label);
  }
});
test('wrong dashboard is redirected using server role before dashboard data loads', async () => {
  const s = setup(); s.run("Session.set({role:'admin'}, 'test-session')");
  assert.equal(await s.run("Session.verifyRole('admin')"), false);
  assert.equal(s.context.location.href, 'volunteer-dashboard.html');
});
test('logout/account switching removes old credentials; no demo token bypass', () => {
  const s = setup(); s.run("Session.set({role:'admin'}, 'old-session'); Session.logout();");
  for (const key of ['resqnet_user','resqnet_token','resqnet_role']) assert.equal(s.storage.has(key), false);
  s.run("Session.set({role:'reporter'}, 'new-session'); Session.set({role:'volunteer'});");
  assert.equal(s.storage.has('resqnet_token'), false);
  s.run("Session.set({role:'admin'}, 'demo-token-fake');");
  assert.equal(s.run('Session.isTokenValid()'), false);
});
test('unverifiable profile fails closed and clears stale account data', async () => {
  const s = setup(); s.run("Session.set({role:'admin'}, 'test-session')");
  s.context.Api.get = async () => null;
  assert.equal(await s.run("Session.verifyRole('admin')"), false);
  assert.equal(s.storage.has('resqnet_user'), false);
  assert.match(s.context.location.href, /^auth.html/);
});
test('local pages default to local backend and explicit overrides are preserved', () => {
  for (const [host, override, expected] of [['127.0.0.1',null,'http://127.0.0.1:5000'],['localhost',null,'http://127.0.0.1:5000'],['example.invalid',null,'https://resqnet-backend-y3ur.onrender.com'],['localhost','http://local-override','http://local-override']]) {
    const context = { window: { location: { hostname: host } }, localStorage: { getItem: () => override } };
    vm.createContext(context); vm.runInContext(source('api.js'), context);
    assert.equal(vm.runInContext('Api.BASE', context), expected);
  }
});
test('all dashboards await authoritative guard; volunteer tasks start before GPS/map', () => {
  for (const page of ['user','volunteer','ngo','admin']) assert.match(source(page+'-dashboard.js'), /if \(!await Session.verifyRole\(/);
  const init = source('volunteer-dashboard.js').split('/* ── Init ── */')[1];
  assert.ok(init.indexOf('loadMyTasks()') < init.indexOf('await syncLocation()'));
});
test('pending profile response cannot overwrite a newly switched account', async () => {
  const s = setup(); s.run("Session.set({role:'admin'}, 'old-session')");
  let complete;
  s.context.Api.get = () => new Promise(resolve => { complete = resolve; });
  const verification = s.run("Session.verifyRole('admin')");
  s.run("Session.set({role:'reporter'}, 'new-session')");
  complete({ success: true, user: { role: 'admin' } });
  assert.equal(await verification, false);
  assert.equal(s.run('Session.role()'), 'reporter');
});
test('volunteer task lists load despite pending GPS and failures show an error', async () => {
  let init;
  const target = { innerHTML: '', textContent: '' }, calls = [];
  const context = { window: {}, console, document: { addEventListener: (_, fn) => { init = fn; }, getElementById: () => target },
    Session: { verifyRole: async () => true, get: () => ({ volunteer: { availability_status: 'available' } }) },
    Api: { get: async () => null } };
  vm.createContext(context); vm.runInContext(source('volunteer-dashboard.js'), context);
  assert.equal(await context.loadMyTasks(), false);
  assert.match(target.innerHTML, /Unable to load assigned tasks/);
  assert.equal(await context.loadNearbyRequests(), false);
  assert.match(target.textContent, /Unable to load available requests/);
  Object.assign(context, { populateVolunteerInfo() {}, initFilters() {}, syncLocation: () => new Promise(() => {}),
    loadMyTasks: async () => calls.push('tasks'), loadNearbyRequests: async () => calls.push('requests'),
    loadPreparednessAlerts: async () => {}, loadVolunteerAlerts: async () => {} });
  init(); await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls.sort(), ['requests', 'tasks']);
});
