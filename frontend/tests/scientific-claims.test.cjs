const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
function setup(script, page) {
  // Only elements present in the actual HTML exist: catch mismatched result IDs.
  const elements = new Map();
  for (const match of read(page).matchAll(/\bid="([^"]+)"/g)) {
    elements.set(match[1], { textContent: '', innerHTML: '', value: '', style: {},
      dataset: {}, classList: { add() {}, toggle() {} } });
  }
  const messages = [];
  const context = { console, window: {}, setTimeout() {}, setInterval() {},
    requestAnimationFrame(callback) { callback(); },
    FormData: class { constructor() { this.fields = []; } append(...field) { this.fields.push(field); } },
    Session: { get: () => ({ user_id: 1, role: 'reporter' }) },
    Toast: { show: (...args) => messages.push(args) },
    timeAgo: () => 'recently', priorityBadge: value => value, statusBadge: value => value,
    Api: {}, document: { addEventListener() {}, querySelectorAll: () => [],
      getElementById: id => elements.get(id) || null } };
  vm.createContext(context);
  vm.runInContext(read('js/'+script), context);
  return { context, elements, messages, run: source => vm.runInContext(source, context) };
}

function legacyReport(overrides = {}) {
  return { report_id: 7, user_id: 1, disaster_type: 'Fire', severity: 'Moderate Damage',
    latitude: 10, longitude: 76, source: 'Community incident report (unverified)',
    predicted_disaster_type: 'Cyclone', prediction_confidence: 98.4, ai_mismatch: false,
    ...overrides };
}

test('actual report form completes submission without legacy inference or confidence claims', async () => {
  const s = setup('report.js', 'report-disaster.html');
  s.elements.get('report-description').value = 'Community observation';
  s.run("selectedDisasterType='Fire'; userLocation={lat:10,lng:76}");
  let submitted;
  s.context.Api.postForm = async (endpoint, form) => {
    submitted = { endpoint, fields: form.fields };
    return { success: true, report: legacyReport(), severity: 'Moderate Damage' };
  };
  await s.context.handleReportSubmit({ preventDefault() {} });
  assert.equal(submitted.endpoint, '/report-disaster');
  assert.ok(submitted.fields.some(([key, value]) => key === 'disaster_type' && value === 'Fire'));
  assert.equal(s.elements.get('report-form').style.display, 'none');
  assert.equal(s.elements.get('success-state').style.display, 'flex');
  assert.match(s.elements.get('ai-prediction-text').textContent, /Community-reported: Fire/);
  assert.match(s.elements.get('report-severity-text').textContent, /Rule-based severity estimate: Moderate Damage/);
  assert.match(s.elements.get('ai-note-text').textContent, /Not independently verified/);
  assert.equal(s.elements.get('ai-result-box').style.display, 'block');
  assert.equal(s.elements.get('success-map-link').href, 'map.html?report_id=7');
  const text = [...s.elements.values()].map(el => el.textContent).join(' ');
  assert.doesNotMatch(text, /98\.4|Cyclone|AI agrees|CNN|Confidence/);
  assert.equal(s.messages.at(-1)[1], 'success');
});

test('report submission errors retain the form and do not invent a result', async () => {
  for (const response of [null, { success: false, message: 'Rejected' }]) {
    const s = setup('report.js', 'report-disaster.html');
    s.elements.get('report-description').value = 'Community observation';
    s.run("selectedDisasterType='Fire'; userLocation={lat:10,lng:76}");
    s.context.Api.postForm = async () => response;
    await s.context.handleReportSubmit({ preventDefault() {} });
    assert.notEqual(s.elements.get('report-form').style.display, 'none');
    assert.notEqual(s.elements.get('success-state').style.display, 'flex');
    assert.equal(s.elements.get('submit-btn').disabled, false);
    assert.equal(s.messages.at(-1)[1], 'danger');
  }
});

test('citizen report details ignore matching, mismatching and absent legacy predictions', async () => {
  for (const prediction of ['Fire', 'Cyclone', null]) {
    const s = setup('user-dashboard.js', 'user-dashboard.html');
    s.context.Api.get = async () => ({ reports: [legacyReport({ predicted_disaster_type: prediction })] });
    await s.context.loadDisasters();
    const table = s.elements.get('disasters-tbody').innerHTML;
    assert.match(table, /Not independently verified/);
    assert.match(table, /showReportDetails\(7\)/);
    assert.doesNotMatch(table, /class="ai-badge verified"|>Verified<|AI Result|Mismatch|Pending/);
    s.context.window.showReportDetails(7);
    const details = s.elements.get('ai-result-panel').innerHTML;
    assert.match(details, /Community-reported type/);
    assert.match(details, /Fire/);
    assert.match(details, /Rule-based severity estimate/);
    assert.match(details, /Moderate Damage/);
    assert.match(details, /Not independently verified/);
    assert.doesNotMatch(details, /98\.4|CNN|AI agrees|confidence|Cyclone|analyzing/i);
  }
});

test('report detail values are escaped and missing severity is unavailable', async () => {
  const s = setup('user-dashboard.js', 'user-dashboard.html');
  s.context.Api.get = async () => ({ reports: [legacyReport({
    disaster_type: '<img src=x onerror=alert(1)>', severity: null,
    source: '<script>invalid</script>' })] });
  await s.context.loadDisasters();
  s.context.window.showReportDetails(7);
  for (const id of ['disasters-tbody', 'ai-result-panel']) {
    assert.doesNotMatch(s.elements.get(id).innerHTML, /<img|<script/);
  }
  assert.match(s.elements.get('ai-result-panel').innerHTML, /Unavailable/);
});

test('SOS rows link to their own request and never use a same-numbered disaster report', () => {
  const s = setup('user-dashboard.js', 'user-dashboard.html');
  s.context.window._myReports = [legacyReport()];
  s.context.renderRequestTable([{ request_id: 7, request_type: 'Rescue', priority_level: 'High',
    status: 'On Site', progress_status: 'Awaiting admin verification' }]);
  const table = s.elements.get('requests-tbody').innerHTML;
  assert.match(table, /map\.html\?request_id=7/);
  assert.match(table, /High/);
  assert.match(table, /Awaiting admin verification/);
  assert.doesNotMatch(table, /AI Result|showAIResult|showReportDetails|report_id=/);
});

test('admin report rows do not imply scientific or pending verification', async () => {
  const s = setup('admin-dashboard.js', 'admin-dashboard.html');
  s.context.Api.get = async endpoint => endpoint === '/admin/reports'
    ? { success: true, reports: [legacyReport()] } : null;
  await s.context.loadDisasters();
  const table = s.elements.get('disasters-tbody').innerHTML;
  assert.match(table, /Not independently verified/);
  assert.match(table, /map\.html\?report_id=7/);
  assert.doesNotMatch(table, /AI Analysis|Pending Manual Verification|98\.4/);
});

test('visible page copy describes rules and observations without CNN or confidence claims', () => {
  for (const page of ['index.html', 'report-disaster.html', 'user-dashboard.html',
    'help-request.html', 'admin-dashboard.html', 'auth.html']) {
    const visible = read(page).replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/g, '').replace(/<!--[\s\S]*?-->/g, '')
      .replace(/<[^>]+>/g, ' ');
    assert.doesNotMatch(visible, /\bCNN\b|98\.4|AI[- ]Powered|AI Analysis|AI Damage|AI PREVIEW|Confidence Score|Predicted Type/i, page);
  }
  assert.match(read('index.html'), /Not independently verified/);
  assert.doesNotMatch(read('help-request.html'), /responded to within\s*<strong>15 minutes/i);
  assert.match(read('report-disaster.html'), /Rule-based severity estimate/);
  assert.match(read('help-request.html'), /Rule-based priority/);
});
