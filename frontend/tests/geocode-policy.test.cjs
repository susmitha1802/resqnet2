const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('actual map script and markup search only after explicit Enter or button', async () => {
  const handlers = {};
  const element = name => ({ value: 'Kochi', style: {}, contains: () => false,
    addEventListener(type, fn) { handlers[`${name}:${type}`] = fn; }, querySelectorAll: () => [] });
  const input = element('input'), results = element('results'), button = element('button');
  const nodes = { 'map-search-input': input, 'map-search-results': results,
    'map-search-input-button': button };
  const context = { document: { getElementById: id => nodes[id], addEventListener() {},
    createElement: () => ({}), head: { appendChild() {} } }, window: {}, console };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/leaflet-map.js'), 'utf8'), context);
  let searches = 0;
  context.ResQMap.geocode = async () => { searches++; return []; };
  context.ResQMap.attachSearchBar({}, 'map-search-input', 'map-search-results');
  handlers['input:input']();
  assert.equal(searches, 0);
  let prevented = false;
  handlers['input:keydown']({ key: 'Enter', preventDefault() { prevented = true; } });
  await Promise.resolve();
  assert.equal(prevented, true);
  assert.equal(searches, 1);
  handlers['button:click']({ preventDefault() {} });
  await Promise.resolve();
  assert.equal(searches, 2);
  for (const file of ['map.html', 'help-request.html', 'report-disaster.html']) {
    const html = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
    assert.match(html, /id="(?:map|loc)-search-input-button"/);
  }
});
