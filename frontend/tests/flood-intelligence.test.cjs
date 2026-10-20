// Focused module behavior checks with a small DOM/Leaflet adapter; no packages.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor() { this.children = []; this.textContent = ''; this.hidden = false; this.style = {}; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.append(item); }
  replaceChildren() { this.children = []; }
  get childElementCount() { return this.children.length; }
  set innerHTML(_html) {
    this.selectors = Object.fromEntries(['status', 'summary', 'metrics', 'date', 'load', 'focus', 'layers'].map(k => [`[data-${k}]`, new Element()]));
  }
  querySelector(selector) { return this.selectors[selector]; }
}

function setup() {
  const controls = [], overlays = [], requests = [];
  const summary = {
    event_date: '2024-07-30', aoi_bbox_epsg4326: [75, 9, 77, 11], candidate: { pixels: 7, area_km2: 0.1 },
    exposure: { buildings: { candidate_intersecting: 2 }, roads: { candidate_intersecting: 3, candidate_overlap_length_m: 4 }, bridges: { potentially_exposed: 1 } },
    network: { hypothetical_disruption: { affected_physical_edges: 5 } },
    scientific_status: { level7: 'NOT_READY', confirmed_flood: false },
    optical_evidence: { categories: { SUPPORTED: { pixels: 0 } } },
    availability: { settlements: { available: false, reason: 'No verified settlements' }, ai: { available: false, reason: 'No model' } }, warnings: ['Experimental'],
  };
  let fail = false;
  const context = {
    window: {}, WeakSet, AbortController, setTimeout, clearTimeout, Api: { BASE: 'http://local-backend' },
    document: { createElement: () => new Element(), createTextNode: text => text },
    L: {
      control: () => { const c = { addTo: () => { c.panel = c.onAdd(); } }; controls.push(c); return c; },
      DomUtil: { create: () => new Element() }, DomEvent: { disableClickPropagation() {}, disableScrollPropagation() {} },
      geoJSON: () => { const o = { pages: [], addData(data) { this.pages.push(data); }, addTo() { return this; } }; overlays.push(o); return o; },
    },
    fetch: async url => {
      requests.push(url);
      if (fail) return { ok: false, json: async () => ({ error: 'Unavailable' }) };
      return { ok: true, json: async () => url.endsWith('/summary') ? summary : {
        type: 'FeatureCollection', features: [{}], next_offset: url.includes('offset=0') ? 1 : null,
      } };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../js/flood-intelligence.js'), 'utf8'), context);
  const map = { fitBounds(bounds) { this.bounds = bounds; }, removeLayer(layer) { this.removed = layer; } };
  return { context, controls, overlays, requests, map, fail: () => { fail = true; } };
}

test('reuse map, opt-in loading, bounded pagination, toggles, uncertainty and errors', async () => {
  const s = setup();
  s.context.window.FloodIntelligence.attach(s.map);
  s.context.window.FloodIntelligence.attach(s.map);
  assert.equal(s.controls.length, 1);
  assert.equal(s.requests.length, 0);
  const panel = s.controls[0].panel;
  await panel.querySelector('[data-load]').onclick();
  const lines = panel.querySelector('[data-summary]').children.map(p => p.textContent).join(' ');
  assert.match(lines, /NOT_READY/);
  assert.match(lines, /not observed closures/);
  assert.match(lines, /No verified settlements/);
  assert.equal(s.map.bounds, undefined);
  panel.querySelector('[data-focus]').onclick();
  assert.equal(s.map.bounds.length, 2);
  const rows = panel.querySelector('[data-layers]').children;
  assert.equal(rows.length, 4);
  const [label, , more, count] = rows[0].children;
  const toggle = label.children[0];
  toggle.checked = true;
  toggle.onchange();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(s.requests.at(-1), /layers\/candidate\?limit=250&offset=0$/);
  assert.match(count.textContent, /partial/);
  await more.onclick();
  assert.match(s.requests.at(-1), /offset=1$/);
  assert.match(count.textContent, /complete/);
  assert.equal(more.hidden, true);
  toggle.checked = false;
  toggle.onchange();
  assert.equal(s.map.removed, s.overlays[0]);
  s.fail();
  await panel.querySelector('[data-load]').onclick();
  assert.match(panel.querySelector('[data-status]').textContent, /unavailable/);
  assert.equal(panel.querySelector('[data-load]').disabled, false);
});
