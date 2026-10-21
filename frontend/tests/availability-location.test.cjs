const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

function dashboard(role, server, geolocation) {
  const html = read(role + '-dashboard.html');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const elements = new Map(ids.map(id => [id, {
    value: '', disabled: false, className: '', textContent: '', style: {},
    classList: { toggle() {} }, addEventListener() {}
  }]));
  const messages = [], calls = [];
  const context = { console, navigator: { geolocation },
    document: { addEventListener() {}, getElementById: id => elements.get(id) || null,
      querySelectorAll: () => [] },
    Session: { get: () => structuredClone(server.user), getToken: () => 'fixture-token',
      set: user => { server.user = structuredClone(user); } },
    Api: { put: async (endpoint, body) => {
      calls.push({ endpoint, body: structuredClone(body) });
      if (server.failWrites) return { success: false, message: 'Fixture write rejected' };
      if (endpoint === '/volunteer/update-status') {
        server.user.volunteer.availability_status = body.status;
        server.user.availability = body.status;
        return { success: true, volunteer: { availability_status: body.status } };
      }
      if (endpoint === '/volunteer/update-location') {
        server.user.volunteer.last_location_lat = body.latitude;
        server.user.volunteer.last_location_lng = body.longitude;
        return { success: true, volunteer: {
          last_location_lat: body.latitude, last_location_lng: body.longitude
        } };
      }
      if (endpoint === '/ngo/readiness') {
        server.user.availability = body.status;
        return { success: true, availability: body.status };
      }
      throw new Error('Unexpected write ' + endpoint);
    } },
    Toast: { show: (message, kind) => messages.push({ message, kind }) } };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(read('js/' + role + '-dashboard.js'), context);
  return { context, elements, messages, calls, evaluate: code => vm.runInContext(code, context) };
}

test('volunteer select hydrates saved operational status and survives a new page load', async () => {
  const server = { user: { name: 'Fixture', role: 'volunteer', availability: 'unavailable',
    volunteer: { availability_status: 'unavailable', last_location_lat: null, last_location_lng: null } } };
  const first = dashboard('volunteer', server, null);
  assert.match(read('volunteer-dashboard.html'), /id="vol-status-select"/);
  first.context.applyVolunteerStatus(server.user.volunteer.availability_status);
  const select = first.elements.get('vol-status-select');
  assert.equal(select.value, 'unavailable');
  select.value = 'available';
  await first.context.updateVolunteerStatusSelect(select);
  assert.deepEqual(first.calls[0], { endpoint: '/volunteer/update-status', body: { status: 'available' } });
  assert.equal(server.user.volunteer.availability_status, 'available');
  const reload = dashboard('volunteer', server, null);
  reload.context.applyVolunteerStatus(server.user.volunteer.availability_status);
  assert.equal(reload.elements.get('vol-status-select').value, 'available');
  server.failWrites = true;
  reload.elements.get('vol-status-select').value = 'unavailable';
  await reload.context.updateVolunteerStatusSelect(reload.elements.get('vol-status-select'));
  assert.equal(reload.elements.get('vol-status-select').value, 'available');
  assert.equal(reload.messages.at(-1).kind, 'danger');
  assert.equal(server.user.volunteer.availability_status, 'available');
});

test('volunteer saved GPS survives permission denial, reload and failed replacement', async () => {
  const server = { user: { name: 'Fixture', role: 'volunteer', availability: 'available',
    volunteer: { availability_status: 'available', last_location_lat: null, last_location_lng: null } } };
  let permitted = true;
  const geolocation = { getCurrentPosition(success, fail) {
    if (permitted) success({ coords: { latitude: 0, longitude: -180 } });
    else fail({ code: 1 });
  } };
  const first = dashboard('volunteer', server, geolocation);
  assert.equal(await first.context.syncLocation(), 'fresh');
  assert.deepEqual(first.calls[0], { endpoint: '/volunteer/update-location',
    body: { latitude: 0, longitude: -180 } });
  permitted = false;
  const reload = dashboard('volunteer', server, geolocation);
  assert.equal(await reload.context.syncLocation(), 'saved');
  assert.equal(reload.evaluate('volunteerLat'), 0);
  assert.equal(reload.evaluate('volunteerLng'), -180);
  assert.equal(reload.calls.length, 0);
  permitted = true;
  server.failWrites = true;
  assert.equal(await reload.context.syncLocation(), 'saved');
  assert.equal(reload.evaluate('volunteerLat'), 0);
  assert.equal(reload.evaluate('volunteerLng'), -180);
  assert.equal(server.user.volunteer.last_location_lat, 0);
});

test('NGO readiness uses its own route, persists on reload and reverts on failure', async () => {
  const server = { user: { name: 'Fixture', role: 'ngo', location: 'Organization',
    availability: 'unavailable' } };
  const first = dashboard('ngo', server, null);
  assert.match(read('ngo-dashboard.html'), /id="ngo-status-select"/);
  first.context.populateNgoInfo();
  const select = first.elements.get('ngo-status-select');
  assert.equal(select.value, 'unavailable');
  select.value = 'available';
  await first.context.updateNGOStatusSelect(select);
  assert.deepEqual(first.calls[0], { endpoint: '/ngo/readiness', body: { status: 'available' } });
  assert.equal(server.user.availability, 'available');
  const reload = dashboard('ngo', server, null);
  reload.context.populateNgoInfo();
  assert.equal(reload.elements.get('ngo-status-select').value, 'available');
  server.failWrites = true;
  reload.elements.get('ngo-status-select').value = 'unavailable';
  await reload.context.updateNGOStatusSelect(reload.elements.get('ngo-status-select'));
  assert.equal(reload.elements.get('ngo-status-select').value, 'available');
  assert.equal(reload.messages.at(-1).kind, 'danger');
  assert.equal(server.user.availability, 'available');
});
