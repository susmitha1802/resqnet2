function escapeResourceText(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/**
 * ResQNet — NGO Dashboard Logic
 * Route guard: ngo role only.
 * Loads active requests, manages inventory, handles resource allocation,
 * renders mini-map with request pins.
 */

let allRequests = [];
let inventory = [];
let allocHistory = [];
let ngoMap = null;
let mapMarkers = [];
let savedNGOStatus = null;
let ngoStatusInFlight = false;

const TYPE_ICONS = { Rescue: '🚁', Food: '🍱', Water: '💧', Medicine: '💊', Shelter: '🏠' };
const TYPE_COLORS = { Rescue: '#EF4444', Food: '#F59E0B', Water: '#3B82F6', Medicine: '#10B981', Shelter: '#8B5CF6' };


/* ── Populate NGO Info ─────────────────────────────────────────────────────── */
function populateNgoInfo() {
  const user = Session.get();
  if (!user) return;

  const name = user.name || 'NGO';
  const initials = name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  const orgName = user.location || user.name; // location field stores org name

  const avEl = document.getElementById('sidebar-avatar');
  if (avEl) avEl.textContent = initials;
  const unEl = document.getElementById('sidebar-username');
  if (unEl) unEl.textContent = name;
  const orgEl1 = document.getElementById('ngo-org-name');
  if (orgEl1) orgEl1.textContent = orgName;
  const orgEl2 = document.getElementById('header-org-name');
  if (orgEl2) orgEl2.textContent = orgName;
  applyNGOStatus(user.availability);
}

function applyNGOStatus(status) {
  if (!['available', 'unavailable'].includes(status)) return;
  savedNGOStatus = status;
  const select = document.getElementById('ngo-status-select');
  if (select) {
    select.value = status;
    select.className = `readiness-select ${status === 'available' ? 'ready' : 'offline'}`;
  }
}

/* ── Tab Navigation ────────────────────────────────────────────────────────── */
function showSection(name) {
  // Hide all sections
  document.querySelectorAll('.tab-section').forEach(s => s.style.display = 'none');

  // Show target section
  const target = document.getElementById('section-' + name);
  if (target) target.style.display = 'block';

  // Update active state in sidebar
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  const activeLink = document.querySelector(`[data-section="${name}"]`);
  if (activeLink) activeLink.classList.add('active');
}

/* ── Animate counter ───────────────────────────────────────────────────────── */
function animateStat(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  let v = 0;
  const step = () => {
    v = Math.min(v + Math.ceil(Math.max(target, 1) / 15), target);
    el.textContent = v;
    if (v < target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}


/* ── Load dashboard stats ──────────────────────────────────────────────────── */
async function loadStats() {
  const data = await Api.get('/ngo/dashboard');
  if (!data?.stats) return;

  const s = data.stats;
  animateStat('stat-active', s.total_active_requests || 0);
  animateStat('stat-urgent', s.high_priority_requests || 0);
  animateStat('stat-resources', s.resources_in_inventory || 0);
  animateStat('stat-allocated', s.allocated_resources || 0);

  // Update impact bars
  const total = s.total_active_requests || 1;
  const high = s.high_priority_requests || 0;
  const resTotal = s.resources_in_inventory || 1;
  const resAlloc = s.allocated_resources || 0;

  const covPct = Math.min(100, Math.round((resAlloc / Math.max(total, 1)) * 100));
  const highPct = Math.min(100, Math.round((high / total) * 100));
  const allocPct = Math.min(100, Math.round((resAlloc / resTotal) * 100));

  setTimeout(() => {
    setBar('ngo-coverage', 'ngo-coverage-bar', covPct);
    setBar('ngo-high-pct', 'ngo-high-bar', highPct);
    setBar('ngo-alloc-pct', 'ngo-alloc-bar', allocPct);
  }, 400);
}

function setBar(labelId, barId, pct) {
  const el = document.getElementById(labelId);
  if (el) el.textContent = pct + '%';
  const bar = document.getElementById(barId);
  if (bar) bar.style.width = pct + '%';
}


/* ── Load Active Requests ──────────────────────────────────────────────────── */
async function loadRequests() {
  const data = await Api.get('/ngo/requests');
  let requests = data?.requests || [];



  allRequests = requests;
  applyRequestFilters();
  updateMapMarkers();
  updateAllocationRequestDropdown();
  renderTypeBreakdown();
}

function applyRequestFilters() {
  const prio = document.getElementById('req-priority-filter')?.value || '';
  const type = document.getElementById('req-type-filter')?.value || '';

  let filtered = [...allRequests];
  if (prio) filtered = filtered.filter(r => r.priority_level === prio);
  if (type) filtered = filtered.filter(r => r.request_type === type);

  renderRequestsTable(filtered);
}

function renderRequestsTable(requests) {
  const tbody = document.getElementById('requests-tbody');
  if (!tbody) return;

  if (!requests.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">
      <div class="empty-state-icon">📭</div>
      <div class="empty-state-title">No active requests</div>
      <div class="empty-state-desc">All requests are resolved or none submitted yet</div>
    </div></td></tr>`;
    return;
  }

  tbody.innerHTML = requests.map(r => {
    const icon = TYPE_ICONS[r.request_type] || '📋';
    const color = TYPE_COLORS[r.request_type] || '#9CA3AF';
    const dotClass = r.priority_level === 'High' ? 'critical' : r.status === 'Pending' ? 'pending' : 'active';

    return `<tr>
      <td><span style="font-family:monospace;font-size:0.8rem;color:var(--text-muted)">#${r.request_id}</span></td>
      <td><span style="color:${color};font-weight:600">${icon} ${r.request_type}</span></td>
      <td style="font-weight:600">${escapeResourceText(r.name || 'Assistance request')}</td>
      <td><span style="color:var(--text-secondary)">${r.number_of_people} people</span></td>
      <td>${priorityBadge(r.priority_level)}</td>
      <td><span class="status-dot ${dotClass}"></span>${r.status}</td>
      <td style="color:var(--text-muted);font-size:0.8rem">${timeAgo(r.created_at)}</td>
      <td>
        <button class="btn-resq-outline" style="padding:4px 12px;font-size:0.75rem"
          onclick="quickAllocate(${r.request_id}, '${r.request_type}')">
          🔗 Allocate
        </button>
      </td>
    </tr>`;
  }).join('');
}

function renderTypeBreakdown() {
  const container = document.getElementById('type-breakdown');
  if (!container) return;

  const counts = {};
  allRequests.forEach(r => { counts[r.request_type] = (counts[r.request_type] || 0) + 1; });
  const total = allRequests.length || 1;

  if (!Object.keys(counts).length) {
    container.innerHTML = `<div style="color:var(--text-muted);font-size:0.82rem;text-align:center">No data</div>`;
    return;
  }

  container.innerHTML = Object.entries(counts).map(([type, count]) => {
    const pct = Math.round((count / total) * 100);
    const color = TYPE_COLORS[type] || '#9CA3AF';
    const icon = TYPE_ICONS[type] || '📋';
    return `<div>
      <div class="distribution-label">
        <span>${icon} ${type}</span>
        <span>${count} (${pct}%)</span>
      </div>
      <div class="distribution-track">
        <div class="distribution-fill" style="background:${color};width:${pct}%;transition:width 0.8s ease"></div>
      </div>
    </div>`;
  }).join('');
}

/* Quick allocate shortcut — pre-fill allocation form */
function quickAllocate(requestId, requestType) {
  const reqSelect = document.getElementById('alloc-request');
  if (reqSelect) reqSelect.value = requestId;
  document.getElementById('allocation-section')?.scrollIntoView({ behavior: 'smooth' });
  Toast.show(`Selected request #${requestId} (${requestType}) for allocation`, 'info');
}


/* ── Map ────────────────────────────────────────────────────────────────────── */
let infoWindow = null;  // kept for compatibility — popups handled by Leaflet
let mapMarkerLib = null;

async function initMap() {
  if (ngoMap) return;
  // Center map on the user's real location; fall back to a zoom-out view if unavailable
  const loc = await getActiveLocation();
  const lat = loc ? loc.lat : 20.5937;   // India center — not a specific city
  const lng = loc ? loc.lng : 78.9629;
  const zoom = loc ? 11 : 5;
  ngoMap = ResQMap.createMap('ngo-map', { lat, lng, zoom });
  ngoMap._leafletMarkers = [];

  // If map initializes after data is loaded, draw markers
  if (allRequests.length > 0) updateMapMarkers();
}

// Ensure initMap is global (no longer a Google callback, but keeps API)
window.initMap = initMap;

function updateMapMarkers() {
  if (!ngoMap) return;

  // Clear old markers
  (ngoMap._leafletMarkers || []).forEach(m => ngoMap.removeLayer(m));
  ngoMap._leafletMarkers = [];

  allRequests.forEach(r => {
    if (!r.latitude || !r.longitude) return;
    const color = TYPE_COLORS[r.request_type] || '#9CA3AF';
    const icon = ResQMap.circleIcon(color, 12);

    const popup = ResQMap.popupHtml(`
      <b>${TYPE_ICONS[r.request_type] || '📋'} ${r.request_type}</b><br>
      ${escapeResourceText(r.name || 'Assistance request')} — ${r.number_of_people} people<br>
      <span style="color:${color}">${r.priority_level} Priority</span>
    `);

    const marker = L.marker(
      [parseFloat(r.latitude), parseFloat(r.longitude)],
      { icon }
    ).bindPopup(popup).addTo(ngoMap);

    ngoMap._leafletMarkers.push(marker);
  });
}


/* ── Inventory Management ──────────────────────────────────────────────────── */
async function loadInventory() {
  const data = await Api.get('/ngo/resources');
  let res = data?.resources || [];

  inventory = res;
  renderInventory();
  updateAllocationResourceDropdown();
  await loadStats(); // refresh stats with new resource count
}

function renderInventory() {
  const tbody = document.getElementById('inventory-tbody');
  if (!tbody) return;

  if (!inventory.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-muted)">
      No resources yet. Click "+ Add Resource" to add items to your inventory.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = inventory.map(r => {
    const isAllocated = !!r.allocated_to;
    const status = isAllocated
      ? `<span class="badge-medium">Allocated → #${r.allocated_to}</span>`
      : `<span class="badge-" style="background:rgba(16,185,129,0.15);color:#10B981;padding:4px 10px;border-radius:20px;font-size:0.75rem;font-weight:600">Available</span>`;

    return `<tr>
      <td><span style="font-family:monospace;font-size:0.8rem;color:var(--text-muted)">#${r.resource_id}</span></td>
      <td style="font-weight:600">${escapeResourceText(r.name)}</td>
      <td>${TYPE_ICONS[r.category] || '📦'} ${escapeResourceText(r.category)}</td>
      <td><strong>${r.quantity.toLocaleString()}</strong> <span style="color:var(--text-muted);font-size:0.8rem">${escapeResourceText(r.unit)}</span></td>
      <td style="color:var(--text-secondary);font-size:0.82rem">${escapeResourceText(r.location || '—')}</td>
      <td>${status}</td>
      <td>
        ${!isAllocated ? `<button class="btn-resq-outline" style="padding:4px 12px;font-size:0.75rem"
          onclick="quickAllocateResource(${r.resource_id})">🔗 Assign</button>
          <button class="btn-resq-outline" onclick="editResource(${r.resource_id})">Edit</button>` : `<span style="color:var(--text-muted);font-size:0.78rem">Deployed</span>`}
      </td>
    </tr>`;
  }).join('');
}

function quickAllocateResource(resourceId) {
  const resSelect = document.getElementById('alloc-resource');
  if (resSelect) resSelect.value = resourceId;
  document.getElementById('allocation-section')?.scrollIntoView({ behavior: 'smooth' });
}

function editResource(resourceId) {
  const resource = inventory.find(r => r.resource_id === resourceId && !r.allocated_to);
  if (!resource) { Toast.show('Only unallocated resources can be edited', 'warning'); return; }
  document.getElementById('edit-resource-id').value = resourceId;
  document.getElementById('edit-resource-label').textContent = `#${resourceId}`;
  document.getElementById('edit-resource-quantity').value = resource.quantity;
  document.getElementById('edit-resource-location').value = resource.location || '';
  document.getElementById('edit-resource-form').classList.add('open');
  document.getElementById('edit-resource-form').scrollIntoView({ behavior: 'smooth' });
}

async function saveResourceEdit() {
  const id = Number(document.getElementById('edit-resource-id').value);
  const quantity = Number(document.getElementById('edit-resource-quantity').value);
  const location = document.getElementById('edit-resource-location').value.trim();
  if (!Number.isSafeInteger(quantity) || quantity <= 0) { Toast.show('Enter a positive whole quantity', 'warning'); return; }
  const result = await Api.put(`/ngo/resources/${id}`, { quantity, location });
  Toast.show(result?.success ? 'Resource updated' : (result?.message || 'Resource update failed'), result?.success ? 'success' : 'danger');
  if (result?.success) {
    document.getElementById('edit-resource-form').classList.remove('open');
    await loadInventory();
  }
}

function toggleAddResourceForm() {
  const form = document.getElementById('add-resource-form');
  form?.classList.toggle('open');
}

async function addResource() {
  const name = document.getElementById('res-name')?.value.trim();
  const category = document.getElementById('res-category')?.value;
  const quantity = parseInt(document.getElementById('res-quantity')?.value || '0');
  const unit = document.getElementById('res-unit')?.value.trim() || 'units';
  const location = document.getElementById('res-location')?.value.trim() || '';

  if (!name || quantity <= 0) {
    Toast.show('Please fill in name and a valid quantity', 'warning');
    return;
  }

  const data = await Api.post('/ngo/resources', { name, category, quantity, unit, location });

  if (data?.success) {
    Toast.show(`✅ ${name} added to inventory!`, 'success');
    // Clear form
    ['res-name', 'res-quantity', 'res-unit', 'res-location'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    toggleAddResourceForm();
    await loadInventory();
  } else {
    Toast.show(data?.message || 'Failed to add resource', 'danger');
  }
}


/* ── Resource Allocation ─────────────────────────────────────────────────────── */
function updateAllocationResourceDropdown() {
  const sel = document.getElementById('alloc-resource');
  if (!sel) return;
  const available = inventory.filter(r => !r.allocated_to);
  sel.innerHTML = `<option value="">— Choose resource —</option>` +
    available.map(r => `<option value="${r.resource_id}">${escapeResourceText(r.name)} (${r.quantity} ${escapeResourceText(r.unit)})</option>`).join('');
}

function updateAllocationRequestDropdown() {
  const sel = document.getElementById('alloc-request');
  if (!sel) return;
  const active = allRequests.filter(r => ['Pending', 'Accepted', 'En Route', 'On Site'].includes(r.status));
  sel.innerHTML = `<option value="">— Choose request —</option>` +
    active.map(r => `<option value="${r.request_id}">#${r.request_id} — ${TYPE_ICONS[r.request_type] || ''} ${r.request_type} (${escapeResourceText(r.name || 'Assistance request')})</option>`).join('');
}

async function allocateResource() {
  const resourceId = parseInt(document.getElementById('alloc-resource')?.value);
  const requestId = parseInt(document.getElementById('alloc-request')?.value);

  if (!resourceId || !requestId) {
    Toast.show('Please select both a resource and a help request', 'warning');
    return;
  }

  const data = await Api.put('/ngo/allocate', { resource_id: resourceId, request_id: requestId });

  if (data?.success) {
    Toast.show(`✅ Resource #${resourceId} allocated to Request #${requestId}!`, 'success');
    allocHistory.unshift({ resourceId, requestId, at: new Date().toISOString() });
    renderAllocHistory();
    await Promise.all([loadInventory(), loadRequests()]);
  } else {
    Toast.show(data?.message || 'Allocation failed', 'danger');
  }
}

function renderAllocHistory() {
  const container = document.getElementById('alloc-history-list');
  if (!container) return;
  if (!allocHistory.length) {
    container.innerHTML = `<div style="color:var(--text-muted);font-size:0.82rem;text-align:center">No allocations yet</div>`;
    return;
  }
  container.innerHTML = allocHistory.slice(0, 5).map(a =>
    `<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-glass);font-size:0.8rem">
      <span>Resource #${a.resourceId} → Request #${a.requestId}</span>
      <span style="color:var(--text-muted)">${timeAgo(a.at)}</span>
    </div>`
  ).join('');
}


/* ── Filter listeners ─────────────────────────────────────────────────────── */
function initFilters() {
  document.getElementById('req-priority-filter')?.addEventListener('change', applyRequestFilters);
  document.getElementById('req-type-filter')?.addEventListener('change', applyRequestFilters);
}


/* ── Init ──────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  // Route guard: ngo role only
  if (!await Session.verifyRole('ngo')) return;

  if (typeof showSection === 'function') {
    showSection('dashboard');
  }

  populateNgoInfo();
  initMap();
  initFilters();

  // Load all data in parallel
  await Promise.all([loadRequests(), loadInventory(), loadPreparednessAlerts(), loadNGOAlerts(), loadWeather()]);
  await loadStats();
});

/* ── Weather — uses real NGO/user location ── */
async function loadWeather() {
  const loc = await getActiveLocation();
  if (!loc) {
    const descEl = document.getElementById('weather-desc');
    if (descEl) descEl.textContent = 'Enable location access to load weather';
    return;
  }
  try {
    const data = await Api.get(`/weather/live?lat=${loc.lat}&lng=${loc.lng}`);
    if (!data?.success || !data.current) throw new Error(data?.message || 'No data');
    const cur = data.current;

    const iconCode = cur.weather[0].icon;
    const temp = Math.round(cur.main.temp);
    const desc = cur.weather[0].description.replace(/\b\w/g, c => c.toUpperCase());
    const humidity = cur.main.humidity;
    const pressure = cur.main.pressure;
    const wind = cur.wind.speed;
    const visibility = cur.visibility ? (cur.visibility / 1000).toFixed(1) : '--';

    const iconEl = document.getElementById('weather-icon');
    if (iconEl) iconEl.innerHTML = `<img src="https://openweathermap.org/img/wn/${iconCode}.png" width="40" />`;
    const tempEl = document.getElementById('weather-temp');
    if (tempEl) tempEl.textContent = `${temp}°C`;
    const descEl = document.getElementById('weather-desc');
    if (descEl) descEl.textContent = desc;

    const humEl = document.getElementById('w-humidity');
    if (humEl) humEl.textContent = `${humidity}%`;
    const windEl = document.getElementById('w-wind');
    if (windEl) windEl.textContent = `${wind} m/s`;
    const pressEl = document.getElementById('w-pressure');
    if (pressEl) pressEl.textContent = `${pressure} hPa`;
    const visEl = document.getElementById('w-visibility');
    if (visEl) visEl.textContent = `${visibility} km`;
  } catch (e) { console.error('Failed to load weather', e); }
}

/* ── Preparedness Alerts ── */
const respondingPings = new Set();
async function loadPreparednessAlerts() {
  try {
    const data = await Api.notificationRequest('/preparedness/my-pings');
    if (!Array.isArray(data.pings) || data.pings.some(p => !Number.isInteger(p.ping_id) || p.ping_id <= 0
      || !['Sent', 'Acknowledged', 'Unavailable'].includes(p.status))) {
      throw new Error('Could not read preparedness responses. Reload before retrying.');
    }

    const bannerHTML = `
      <div id="preparedness-banner" style="background:var(--bg-card);border:1px solid var(--accent-red);border-radius:var(--radius);padding:20px;margin-bottom:20px;box-shadow:var(--glow-red-sm)">
      ${data.pings.map(ping => `<div style="margin-bottom:16px;">
        <h3 style="color:var(--accent-red);margin-bottom:8px;font-size:1.1rem">Preparedness advisory — ${escapeResourceText(ping.alert_type)} ${escapeResourceText(ping.severity)}</h3>
        <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:16px">${escapeResourceText(ping.description)}</p>
        ${ping.status === 'Sent' ? `
        <div style="margin-bottom:12px">Awaiting your response. This does not update inventory or readiness.</div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <button type="button" data-ping-id="${ping.ping_id}" class="btn-resq" onclick="respondToPing(${ping.ping_id}, 'Acknowledged')" ${respondingPings.has(ping.ping_id) ? 'disabled' : ''}>Acknowledge advisory</button>
          <button type="button" data-ping-id="${ping.ping_id}" class="btn-resq-outline" onclick="respondToPing(${ping.ping_id}, 'Unavailable')" ${respondingPings.has(ping.ping_id) ? 'disabled' : ''}>Unavailable</button>
        </div>` : `<p>Response saved: ${escapeResourceText(ping.status)}</p>`}
      </div>`).join('')}
      </div>
    `;

    document.getElementById('preparedness-banner')?.remove();
    const anchor = document.querySelector('.stats-grid-4');
    if (anchor && data.pings.length) anchor.insertAdjacentHTML('beforebegin', bannerHTML);
    return true;
  } catch (error) {
    Toast.show(error.message || 'Could not load preparedness responses.', 'danger');
    return false;
  }
}

async function respondToPing(pingId, status) {
  if (!Number.isInteger(pingId) || pingId <= 0 || !['Acknowledged', 'Unavailable'].includes(status)) {
    Toast.show('Choose a valid advisory response.', 'danger');
    return;
  }
  if (respondingPings.has(pingId)) return;
  respondingPings.add(pingId);
  const buttons = () => document.querySelectorAll(`[data-ping-id="${pingId}"]`);
  buttons().forEach(button => { button.disabled = true; });
  try {
    const data = await Api.notificationRequest(`/preparedness/ping/${pingId}`, 'PUT', { status });
    if (data.ping?.ping_id !== pingId || data.ping.status !== status) {
      throw new Error('Could not confirm the saved response. Reload before retrying.');
    }
    Toast.show(`Response saved: ${status}. Inventory and readiness are unchanged.`, 'success');
    if (!await loadPreparednessAlerts()) Toast.show('Response was saved, but the display could not refresh. Reload to check it.', 'warning');
  } catch (error) {
    Toast.show(error.message || 'Could not confirm the response. Reload before retrying.', 'danger');
  } finally {
    respondingPings.delete(pingId);
    buttons().forEach(button => { button.disabled = false; });
  }
}

async function loadNGOAlerts() {
  try {
    const data = await Api.get('/alerts');
    const container = document.getElementById('ngo-alerts-list');
    if (!container) return;
    if (data && data.success && data.alerts && data.alerts.length > 0) {
      const a = data.alerts[0]; // just show top alert for simplicity
      container.innerHTML = `
        <div style="font-weight:700;color:var(--text-primary);font-size:1.1rem;margin-bottom:4px">⚠ ${a.alert_type} ${a.severity}</div>
        <div style="color:var(--text-secondary);font-size:0.9rem">${escapeResourceText(a.description)}</div>
      `;
    } else {
      container.innerHTML = '<p style="color:var(--text-muted);font-size:0.9rem">🟢 No active alerts. Conditions unconfirmed.</p>';
    }
  } catch (e) { console.error('Failed to load NGO alerts', e); }
}

async function updateNGOStatusSelect(select) {
  if (ngoStatusInFlight) return;
  const previous = savedNGOStatus;
  const requested = select.value;
  ngoStatusInFlight = true;
  select.disabled = true;
  try {
    const data = await Api.put('/ngo/readiness', { status: requested });
    if (!data?.success || data.availability !== requested) {
      throw new Error(data?.message || 'Could not save readiness');
    }
    applyNGOStatus(requested);
    const user = Session.get();
    if (user) Session.set({ ...user, availability: requested }, Session.getToken());
    Toast.show('NGO readiness saved', 'success');
  } catch (e) {
    applyNGOStatus(previous);
    Toast.show(e.message || 'Could not save readiness', 'danger');
  } finally {
    select.disabled = false;
    ngoStatusInFlight = false;
  }
}

// Expose globals for inline HTML handlers
window.addResource = addResource;
window.allocateResource = allocateResource;
window.loadRequests = loadRequests;
window.toggleAddResourceForm = toggleAddResourceForm;
window.quickAllocate = quickAllocate;
window.quickAllocateResource = quickAllocateResource;
window.respondToPing = respondToPing;
window.updateNGOStatusSelect = updateNGOStatusSelect;
