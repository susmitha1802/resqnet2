const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(search = '') {
  const elements = new Map(), markers = [], circles = [], intervals = [];
  let init, api = { success: true, requests: [], reports: [], volunteers: [] };
  let demoApi = {success:true,scenarios:[]};
  const map = { views: [], fits: [], on() {}, removeLayer() {}, setView(point, zoom) { this.views.push({ point, zoom }); }, fitBounds(bounds) { this.fits.push(bounds); } };
  const group = () => ({ items: [], addLayer(item) { this.items.push(item); },
    getLayers() { return this.items; }, addTo() { return this; } });
  const mark = coords => ({ coords, getLatLng: () => coords, bindPopup(html) { this.popup = html; return this; },
    bindTooltip() { return this; }, addTo(target) { target?.addLayer?.(this); return this; }, openPopup() { this.opened = true; } });
  const context = {
    URL, URLSearchParams, location: { search, href: 'http://local/map.html'+search, pathname: '/map.html' }, console,
    history: {replaceState() {}},
    document: { getElementById: id => { if (!elements.has(id)) elements.set(id, { style: {}, textContent: '',
      setAttribute(name, value) { this[name] = value; } }); return elements.get(id); },
      querySelectorAll: () => [], createElement: () => ({}), head: { appendChild() {} } },
    addEventListener: (_name, handler) => { init = handler; }, setInterval: callback => intervals.push(callback),
    Api: { BASE: 'http://local-api', get: async endpoint => endpoint === '/map/demo-scenarios' ? demoApi : api },
    FloodIntelligence: { attach() {} }, Toast: { show() {} },
    fetch: async () => ({ ok: true, json: async () => ({ zones: [], locations: [] }) }),
    L: { layerGroup: group, marker: coords => { const item = mark(coords); markers.push(item); return item; },
      circle: coords => { const item = mark(coords); circles.push(item); return item; }, divIcon: value => value },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../js/leaflet-map.js'), 'utf8'), context);
  Object.assign(context.ResQMap, { createMap: (_id, view) => { map.initial = view; return map; }, attachSearchBar: (_m, _i, _r, handler) => { context.searchPlace = handler; },
    createClusterGroup: group, pulseIcon: () => ({}), circleIcon: () => ({}) });
  const html = fs.readFileSync(path.join(__dirname, '../map.html'), 'utf8');
  const inline = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]).find(s => s.includes('async function loadMapData'));
  vm.runInContext(inline, context);
  return { context, map, markers, circles, intervals, init: () => init(),
    data: value => { api = value; }, demoData: value => { demoApi = value; }, elements };
}

test('fictional map markers are opt-in, labeled and excluded from live incident counts', async () => {
  const scenario = {title:'<fake>', latitude:17.6868, longitude:83.2185,
    notice:'FICTIONAL DEMO location',is_demo:true};
  const normal = setup();
  normal.demoData({success:true,scenarios:[scenario]});
  await normal.init();
  assert.equal(normal.markers.length,0);
  assert.equal(normal.elements.get('live-count').textContent,0);
  const demo = setup('?demo=1');
  demo.demoData({success:true,scenarios:[scenario]});
  await demo.init();
  assert.equal(demo.markers.length,1);
  assert.match(demo.markers[0].popup,/FICTIONAL DEMO/);
  assert.match(demo.markers[0].popup,/&lt;fake&gt;/);
  assert.equal(demo.elements.get('map-demo-banner').hidden,false);
  assert.equal(demo.elements.get('live-count').textContent,0);
  assert.equal(demo.elements.get('map-demo-toggle')['aria-pressed'],'true');
  demo.context.toggleDemoScenarios();
  await Promise.resolve();
  assert.equal(demo.elements.get('map-demo-banner').hidden,true);
});

const request = { request_id: 1, request_type: 'Rescue', priority_level: 'High', number_of_people: 2,
  latitude: 9.9312, longitude: 76.2673, status: 'En Route', source: 'Community SOS request', description: 'Kochi request' };
const report = { report_id: 2, disaster_type: 'Flood', latitude: 12.9716, longitude: 77.5946,
  status: 'Reported; not independently verified', source: 'Community incident report (unverified)', description: 'Bengaluru report' };

test('initial view is a country overview, valid coordinates include zero, invalid pairs do not center Hyderabad', async () => {
  const s = setup(); await s.init();
  assert.equal(s.map.initial.zoom, 5);
  assert.equal(s.map.initial.lat, 20.5937);
  assert.equal(s.context.ResQMap.initialMapView('?lat=0&lng=0').lat, 0);
  assert.equal(s.context.ResQMap.initialMapView('?lat=91&lng=78').zoom, 5);
  assert.equal(s.context.ResQMap.initialMapView('?lat=9.9').zoom, 5);
});

test('linked report centers once; polling, panning, search and filters do not force a return', async () => {
  const s = setup('?report_id=2');
  s.data({ success: true, requests: [request], reports: [report], volunteers: [] });
  await s.init();
  assert.equal(s.map.views.length, 1);
  assert.equal(s.map.views[0].point[0], 12.9716);
  s.map.setView([28.6139, 77.209], 10);
  await s.context.loadMapData();
  assert.equal(s.map.views.length, 2);
  s.context.searchPlace(19.076, 72.8777);
  s.context.applyMapFilter('Disasters');
  await Promise.resolve();
  assert.equal(s.map.views.at(-1).point[0], 19.076);
  assert.equal(s.map.fits.length, 0);
});

test('linked SOS uses a plain Leaflet layer group safely and only centers once', async () => {
  const s = setup('?request_id=1');
  s.data({ success: true, requests: [request], reports: [], volunteers: [] });
  await s.init(); await s.context.loadMapData();
  assert.equal(s.map.views.length, 1);
  assert.equal(s.map.views[0].point[0], 9.9312);
});

test('volunteer marker rendering does not interrupt a linked disaster report', async () => {
  const s = setup('?report_id=2');
  s.data({ success: true, requests: [request], reports: [report], volunteers: [
    { volunteer_id: 3, user_name: '<Volunteer>', availability_status: 'available',
      last_location_lat: 12.97, last_location_lng: 77.59 }
  ] });
  await s.init();
  assert.equal(s.map.views[0].point[0], 12.9716);
  assert.equal(s.markers.find(marker => marker.coords[0] === 12.9716).opened, true);
  assert.match(s.markers.find(marker => marker.coords[0] === 12.97).popup, /&lt;Volunteer&gt;/);
});

test('a user location choice wins even if linked incident data is still loading', async () => {
  const s = setup('?report_id=2');
  s.data({ success: true, requests: [], reports: [report], volunteers: [] });
  const loading = s.init();
  s.context.searchPlace(28.6139, 77.209);
  await loading;
  assert.equal(s.map.views.length, 1);
  assert.equal(s.map.views[0].point[0], 28.6139);
});

test('incident popups use the corresponding record location/status/source and escape descriptions', async () => {
  const s = setup();
  s.data({ success: true, requests: [{ ...request, description: '<script>bad()</script>' }], reports: [report], volunteers: [] });
  await s.init();
  assert.match(s.markers[0].popup, /9\.93120, 76\.26730/);
  assert.match(s.markers[0].popup, /En Route/);
  assert.match(s.markers[0].popup, /Community SOS request/);
  assert.doesNotMatch(s.markers[0].popup, /<script>/);
  assert.match(s.markers[1].popup, /12\.97160, 77\.59460/);
  assert.match(s.markers[1].popup, /not independently verified/);
  assert.doesNotMatch(s.markers[1].popup, /Hyderabad|AI Analysis/);
});

test('legacy demo alert is excluded defensively; real zone popup includes provenance and no claimed verification', async () => {
  const s = setup();
  const legacy = { lat: 17.4401, lng: 78.4487, radius_km: 50, alert_type: 'Flood', severity: 'Emergency',
    risk_level: 'High', description: 'Severe flash flooding expected in the Hyderabad region over the next 48 hours.' };
  const real = { lat: 9.9312, lng: 76.2673, radius_km: 2, alert_type: 'Flood', severity: 'Watch', risk_level: 'Low',
    description: 'Observed rainfall', source: 'Manual', status: 'Active alert' };
  s.context.fetch = async () => ({ ok: true, json: async () => ({ zones: [legacy, real] }) });
  await s.context.loadRiskZones(s.map);
  assert.equal(s.circles.length, 1);
  assert.match(s.circles[0].popup, /9\.93120, 76\.26730/);
  assert.match(s.circles[0].popup, /Source: Manual/);
  assert.match(s.circles[0].popup, /Status: Active alert/);
  assert.match(s.circles[0].popup, /not an official warning/);
  assert.match(s.context.ResQMap.riskZonePopup({ ...legacy, is_demo: true }), /DEMO \/ SAMPLE/);
});

test('NGO markers require valid coordinates, including zero, without a Hyderabad fallback', async () => {
  const s = setup();
  s.context.fetch = async () => ({ ok: true, json: async () => ({ locations: [
    { name: 'Unknown', latitude: null, longitude: null },
    { name: 'Invalid', latitude: 999, longitude: 77 },
    { name: 'Wrong type', latitude: false, longitude: false },
    { name: 'Valid origin', latitude: 0, longitude: 0 },
    { name: 'Valid outside Hyderabad', latitude: 12.9716, longitude: 77.5946 }
  ] }) });
  await s.context.addNgoDepotMarkers(s.map);
  assert.deepEqual(s.markers.map(marker => Array.from(marker.coords)), [[0, 0], [12.9716, 77.5946]]);
  assert.match(s.markers[0].popup, /Valid origin/);
});
