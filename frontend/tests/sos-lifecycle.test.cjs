const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(file) {
  const elements = new Map(), calls = [], toasts = [], dialogs = [], revoked = [], logouts = [];
  const create = tag => ({ tag, style: {}, children: [], append(...children) { this.children.push(...children); },
    showModal() { this.open = true; }, close() { this.onclose(); }, remove() { this.removed = true; } });
  const context = {
    console, confirm: () => true,
    document: { addEventListener() {}, getElementById: id => elements.get(id) || null,
      querySelectorAll: () => [], createElement: create, body: { appendChild: el => dialogs.push(el) } },
    Api: { BASE: 'http://local-api', headers: () => ({ Authorization: 'Bearer jwt' }),
      fetchWithTimeout: async (url, options) => { calls.push({ url, options }); return { ok: true, status: 200, blob: async () => ({ type: 'image/png' }) }; },
      get: async () => ({ success: true, verifications: [] }) },
    URL: { createObjectURL: () => 'blob:private-proof', revokeObjectURL: url => revoked.push(url) },
    Session: { logout: message => logouts.push(message) }, Toast: { show: (message, kind) => toasts.push({ message, kind }) },
    statusBadge: value => value, priorityBadge: value => value, timeAgo: () => 'now',
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js', file), 'utf8'), context);
  return { context, elements, calls, toasts, dialogs, revoked, logouts, run: source => vm.runInContext(source, context) };
}

test('proof viewer fetches with JWT, uses a blob dialog and revokes the private URL', async () => {
  const s = setup('admin-dashboard.js');
  await s.context.viewTaskProof(9);
  assert.equal(s.calls[0].url, 'http://local-api/volunteer/tasks/9/proof');
  assert.equal(s.calls[0].options.headers.Authorization, 'Bearer jwt');
  assert.doesNotMatch(s.calls[0].url, /token|jwt/);
  assert.equal(s.dialogs.length, 1);
  assert.equal(s.dialogs[0].children[1].src, 'blob:private-proof');
  s.dialogs[0].close();
  assert.deepEqual(s.revoked, ['blob:private-proof']);
  assert.equal(s.dialogs[0].removed, true);
});

test('proof viewing denies expired sessions, access errors and non-image bodies', async () => {
  for (const status of [401, 403, 404, 200]) {
    const s = setup('admin-dashboard.js');
    s.context.Api.fetchWithTimeout = async () => ({ status, ok: status === 200, blob: async () => ({ type: 'text/html' }) });
    await s.context.viewTaskProof(9);
    assert.equal(s.dialogs.length, 0);
    assert.equal(s.logouts.length, status === 401 ? 1 : 0);
    if (status !== 401) assert.equal(s.toasts[0].kind, 'danger');
  }
});

test('review queue escapes volunteer notes and offers authenticated proof controls', async () => {
  const s = setup('admin-dashboard.js');
  const table = { innerHTML: '' };
  s.elements.set('verifications-tbody', table);
  s.context.Api.get = async () => ({ success: true, verifications: [{ task_id: 9, volunteer_id: 2,
    completion_notes: '<img src=x onerror="evil()">', proof_image_path: 'C:/private/proof.png' }] });
  await s.context.loadVerifications();
  assert.doesNotMatch(table.innerHTML, /<img|C:\/private/);
  assert.match(table.innerHTML, /&lt;img/);
  assert.match(table.innerHTML, /viewTaskProof\(9\)/);
  assert.match(table.innerHTML, /reviewTask\(9, 'Approve'\)/);
  assert.match(table.innerHTML, /reviewTask\(9, 'Reject'\)/);
});

test('review blocks duplicate clicks, refreshes on success and handles failed review', async () => {
  const s = setup('admin-dashboard.js');
  let resolve, count = 0;
  s.run('let refreshes = 0; loadVerifications = loadDashboard = loadRequests = async () => { refreshes++; };');
  s.context.Api.put = () => { count++; return new Promise(done => { resolve = done; }); };
  const first = s.context.reviewTask(9, 'Approve');
  await s.context.reviewTask(9, 'Approve');
  assert.equal(count, 1);
  resolve({ success: true });
  await first;
  assert.equal(s.run('refreshes'), 3);
  assert.equal(s.run('reviewingTasks.size'), 0);
  s.context.Api.put = async () => ({ success: false, message: 'Already reviewed' });
  await s.context.reviewTask(9, 'Reject');
  assert.equal(s.toasts.at(-1).message, 'Already reviewed');
});

test('citizen request table and timeline show awaiting verification and rejected progress', () => {
  const s = setup('user-dashboard.js');
  const table = { innerHTML: '' }, timeline = { innerHTML: '' };
  s.elements.set('requests-tbody', table);
  s.elements.set('timeline-container', timeline);
  const rows = [{ request_id: 7, request_type: 'Rescue', status: 'On Site', progress_status: 'Awaiting admin verification' },
    { request_id: 8, request_type: 'Food', status: 'On Site', progress_status: 'Proof rejected; volunteer resubmission needed' }];
  s.context.renderRequestTable(rows);
  s.context.renderTimeline(rows);
  for (const result of [table.innerHTML, timeline.innerHTML]) {
    assert.match(result, /Awaiting admin verification/);
    assert.match(result, /Proof rejected/);
    assert.doesNotMatch(result, /Completed/);
  }
});

test('volunteer proof upload uses JWT and multipart contract and blocks duplicate submits', async () => {
  const s = setup('volunteer-dashboard.js');
  s.context.Session.getToken = () => 'jwt';
  s.context.FormData = class { constructor() { this.values = new Map(); } append(key, value) { this.values.set(key, value); } };
  const file = { name: 'proof.png' }, button = {};
  s.elements.set('proof_img_9', { files: [file] });
  s.elements.set('proof_notes_9', { value: 'Delivered supplies' });
  s.run('loadMyTasks = async () => true;');
  const event = { preventDefault() {}, target: { querySelector: () => button } };
  let resolve;
  s.context.Api.fetchWithTimeout = (url, options) => {
    s.calls.push({ url, options });
    return new Promise(done => { resolve = done; });
  };
  const upload = s.context.submitProof(event, 9);
  await s.context.submitProof(event, 9);
  assert.equal(s.calls.length, 1);
  assert.equal(s.calls[0].url, 'http://local-api/volunteer/upload-proof/9');
  assert.equal(s.calls[0].options.method, 'POST');
  assert.equal(s.calls[0].options.headers.Authorization, 'Bearer jwt');
  assert.equal(s.calls[0].options.body.values.get('proof_image'), file);
  assert.equal(s.calls[0].options.body.values.get('notes'), 'Delivered supplies');
  assert.equal(s.calls[0].options.headers['Content-Type'], undefined);
  resolve({ ok: true, status: 200, json: async () => ({ success: true }) });
  await upload;
  assert.equal(s.run('uploadingProofs.size'), 0);
  assert.equal(button.disabled, false);
  assert.equal(s.toasts[0].kind, 'success');
});
