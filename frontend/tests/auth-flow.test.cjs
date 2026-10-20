// Auth page's real inline role selector + shared scripts; no accounts are written.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'auth.html'), 'utf8');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');
function setup() {
  const elements = new Map(), storage = new Map(), calls = [], timers = [];
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]));
  const element = id => {
    if (!ids.has(id)) return null;
    if (!elements.has(id)) elements.set(id, {value: '', checked: true, style: {}, classList: {add() {},remove() {},toggle() {}}, addEventListener() {}});
    return elements.get(id);
  };
  const context = { document: { addEventListener() {}, getElementById: element, querySelectorAll: () => [] },
    location: { href: '' }, localStorage: {getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)},
    setInterval() {}, setTimeout: fn => timers.push(fn), console,
    Api: { post: async (endpoint, body) => { calls.push({endpoint, body}); return {success:false, message:'Test validation'}; } } };
  context.window = context;
  vm.createContext(context);
  for (const file of ['main.js','auth.js']) vm.runInContext(fs.readFileSync(path.join(root,'js',file),'utf8'),context);
  vm.runInContext(inline,context);
  vm.runInContext('Toast.show = () => {};',context);
  for (const [id,value] of Object.entries({'reg-name':'Test','reg-email':'test@test.invalid','reg-phone':'test','reg-password':'test-password','reg-confirm':'test-password','reg-org-name':'Test organization','reg-availability':'available','admin-secret-code':'test-only','login-email':'test@test.invalid','login-password':'test-password'})) element(id).value=value;
  return {context,calls,storage,timers, run: s => vm.runInContext(s,context)};
}
for (const role of ['reporter','volunteer','ngo','admin']) {
  test(`selecting ${role} sends the selected registration role`,async () => {
    const s=setup(); s.context.selectRole(role);
    await s.context.handleRegister({preventDefault() {}});
    assert.equal(s.calls[0].endpoint,'/register');
    assert.equal(s.calls[0].body.role,role);
    if (role==='volunteer') {
      assert.ok(Array.isArray(s.calls[0].body.skills));
      assert.equal(s.calls[0].body.availability,'available');
    }
    if (role==='ngo') assert.equal(s.calls[0].body.org_name,'Test organization');
    if (role==='admin') assert.equal(s.calls[0].body.admin_secret_code,'test-only');
  });
}
test('login replaces a stale account and routes using every returned DB role',async () => {
  const s=setup();
  for (const [role,page] of [['reporter','user'],['volunteer','volunteer'],['ngo','ngo'],['admin','admin']]) {
    s.run("Session.set({name:'Old account',role:'reporter'}, 'old-test-session')");
    s.context.Api.post=async (endpoint,body) => {
      assert.equal(endpoint,'/login'); assert.equal('role' in body,false);
      return {success:true,token:'new-test-session',role,user:{name:'Test account',role}};
    };
    await s.context.handleLogin({preventDefault() {}});
    s.timers.splice(0).forEach(fn=>fn());
    assert.equal(s.context.location.href,page+'-dashboard.html');
    assert.equal(s.storage.get('resqnet_token'),'new-test-session');
    assert.equal(JSON.parse(s.storage.get('resqnet_user')).role,role);
    s.run('Session.logout()');
    assert.equal(s.context.location.href,'auth.html');
    for (const key of ['resqnet_user','resqnet_token','resqnet_role']) assert.equal(s.storage.has(key),false);
  }
});
