function escapeCitizenText(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/**
 * ResQNet — User Dashboard Logic
 * All data loaded from the real API — no mock data.
 */

let currentRequests = [];
let selectedRequest = null;

async function viewCitizenImage(path) {
  try { await Api.viewPrivateImage(path); }
  catch (error) { Toast.show(error.message || 'Image unavailable', 'danger'); }
}

/* ── Populate User Info ── */
function populateUserInfo() {
  const user = Session.get();
  if (user) {
    const initials = user.name.split(' ').map(n=>n[0]).join('').toUpperCase().slice(0,2);
    const pa = document.getElementById('profile-avatar');
    if (pa) pa.textContent = initials;
    const pn = document.getElementById('profile-name');
    if (pn) pn.textContent = user.name;
    const sa = document.getElementById('sidebar-avatar');
    if (sa) sa.textContent = initials;
    const su = document.getElementById('sidebar-username');
    if (su) su.textContent = user.name;
    document.querySelectorAll('.profile-email').forEach(el => el.textContent = user.email || '—');
    document.querySelectorAll('.profile-phone').forEach(el => el.textContent = user.phone || '—');
    const memberSince = document.getElementById('profile-member-since');
    if (memberSince) memberSince.textContent = user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unavailable';
  }
}

/* ── Update Stats ── */
function updateStats() {
  const total = currentRequests.length;
  const pending = currentRequests.filter(r => r.status === 'Pending').length;
  const completed = currentRequests.filter(r => r.status === 'Completed').length;
  const accepted = currentRequests.filter(r => r.status === 'Accepted').length;

  animateStatCounter('stat-total', total);
  animateStatCounter('stat-pending', pending);
  animateStatCounter('stat-completed', completed);
  animateStatCounter('stat-accepted', accepted);
}

function animateStatCounter(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  let start = 0;
  const step = () => {
    start = Math.min(start + Math.ceil(Math.max(target, 1) / 20), target);
    el.textContent = start;
    if (start < target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ── Render Request History Table ── */
function renderRequestTable(requests) {
  const tbody = document.getElementById('requests-tbody');
  if (!tbody) return;

  if (!requests.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-state-icon">📭</div><div class="empty-state-title">No requests yet</div><div class="empty-state-desc">Submit a help request to get started</div></div></td></tr>`;
    return;
  }

  tbody.innerHTML = requests.map(r => `
    <tr>
      <td><span style="font-family:monospace;font-size:0.8rem;color:var(--text-muted)">#${r.request_id}</span></td>
      <td>${r.request_type}</td>
      <td>${priorityBadge(r.priority_level)}</td>
      <td>${statusBadge(r.status)}${r.progress_status && r.progress_status !== r.status ? `<div style="font-size:0.75rem">${r.progress_status}</div>` : ''}</td>
      <td style="color:var(--text-muted);font-size:0.78rem">${timeAgo(r.created_at)}</td>
      <td><a class="btn-resq-outline" style="padding:3px 10px;font-size:0.72rem;" href="map.html?request_id=${r.request_id}">Map</a>${r.image_url ? `<button class="btn-resq-outline" onclick="viewCitizenImage('${r.image_url}')">Image</button>` : ''}</td>
    </tr>
  `).join('');
}

/* ── Render Timeline ── */
function renderTimeline(requests) {
  const container = document.getElementById('timeline-container');
  if (!container) return;

  if (!requests.length) {
    container.innerHTML = `<div style="text-align:center;color:var(--text-muted);padding:20px">No requests to track.</div>`;
    return;
  }

  container.innerHTML = requests.map(r => {
    const color = r.status === 'Completed' ? '#10b981' : (r.status === 'Accepted' ? '#3b82f6' : '#f59e0b');
    return `<div style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border-subtle);">
  <div style="width:10px;height:10px;border-radius:50%;background:${color};flex-shrink:0;margin-top:4px;"></div>
  <div>
    <div style="font-weight:600;font-size:0.85rem;">${r.request_type} — ${r.progress_status || r.status}</div>
    <div style="font-size:0.75rem;color:var(--text-muted);">${timeAgo(r.updated_at || r.created_at)}</div>
  </div>
</div>`;
  }).join('');
}

/* ── Filters ── */
function initFilters() {
  const searchInput = document.getElementById('search-input');
  const statusFilter = document.getElementById('status-filter');
  const typeFilter = document.getElementById('type-filter');

  const applyFilters = () => {
    let filtered = [...currentRequests];
    const query = searchInput?.value.toLowerCase() || '';
    const status = statusFilter?.value || '';
    const type = typeFilter?.value || '';

    if (query) filtered = filtered.filter(r => r.request_type?.toLowerCase().includes(query) || r.description?.toLowerCase().includes(query));
    if (status) filtered = filtered.filter(r => r.status === status);
    if (type) filtered = filtered.filter(r => r.request_type === type);

    renderRequestTable(filtered);
    renderTimeline(filtered);
  };

  searchInput?.addEventListener('input', applyFilters);
  statusFilter?.addEventListener('change', applyFilters);
  typeFilter?.addEventListener('change', applyFilters);
}

/* ── Fetch from real API ── */
async function loadRequests() {
  const data = await Api.get('/help-requests');
  if (!data?.success || !Array.isArray(data.requests)) return;
  currentRequests = data.requests;

  updateStats();
  renderRequestTable(currentRequests);
  renderTimeline(currentRequests);
  loadNotifications();
}

function loadNotifications() {
  const notifList = document.getElementById('notif-list');
  const notifBadge = document.getElementById('notif-badge');
  if (!notifList) return;

  if (currentRequests.length === 0) {
    notifList.innerHTML = '<div class="notif-empty" style="padding:20px;text-align:center;color:var(--text-muted)">No requests to track yet.</div>';
    if (notifBadge) notifBadge.style.display = 'none';
    return;
  }

  const recent = [...currentRequests].sort((a,b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)).slice(0, 5);
  notifList.innerHTML = recent.map(r => `
    <div style="padding:12px;border-bottom:1px solid var(--border-subtle)">
      <div style="font-weight:600;font-size:0.85rem">Current request progress</div>
      <div style="font-size:0.8rem;color:var(--text-secondary)">Your ${r.request_type} request is now <strong>${escapeCitizenText(r.progress_status || r.status)}</strong></div>
      <div style="font-size:0.7rem;color:var(--text-muted);margin-top:4px">${timeAgo(r.updated_at || r.created_at)}</div>
    </div>
  `).join('');

  // There is no persisted unread/delivery state for these request snapshots.
  if (notifBadge) notifBadge.style.display = 'none';
}

/* ── Fetch Disaster Reports ── */
async function loadDisasters() {
  const data = await Api.get('/reports');
  const user = Session.get();
  if (!user) return;

  const myReports = (data.reports || []).filter(r => r.user_id === user.user_id);
  const tbody = document.getElementById('disasters-tbody');

  if (!tbody) return;

  if (myReports.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:30px;color:var(--text-muted)">You have not reported any disasters.</td></tr>';
    return;
  }

  // Attach reports to window for easy access
  window._myReports = myReports;

  tbody.innerHTML = myReports.map(r => `
    <tr>
      <td style="font-weight:600">
        🔥 ${escapeCitizenText(r.disaster_type)}
      </td>
      <td>
        <span class="priority-badge" style="
          background:${r.severity?.includes('Severe') ? 'rgba(239,68,68,0.2)' : (r.severity?.includes('Moderate') ? 'rgba(245,158,11,0.2)' : 'rgba(16,185,129,0.2)')};
          color:${r.severity?.includes('Severe') ? '#EF4444' : (r.severity?.includes('Moderate') ? '#F59E0B' : '#10B981')}
        ">${escapeCitizenText(r.severity || 'Unavailable')}</span>
      </td>
      <td style="color:var(--text-secondary)">📍 ${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}</td>
      <td>
        <span class="ai-badge medium">Not independently verified</span>
      </td>
      <td style="color:var(--text-secondary)">${timeAgo(r.created_at)}</td>
      <td>
        <div style="display:flex;gap:6px">
          <button type="button" onclick="showReportDetails(${r.report_id})" class="btn-resq-outline" style="padding:4px 8px;font-size:0.75rem">Report details</button>
          ${r.image_url ? `<button type="button" onclick="viewCitizenImage('${r.image_url}')" class="btn-resq-outline">Image</button>` : ''}
          <a href="map.html?report_id=${r.report_id}" class="btn-resq-outline" style="padding:4px 8px;font-size:0.75rem">🗺️ Map</a>
        </div>
      </td>
    </tr>
  `).join('');
}

window.showReportDetails = function(reportId) {
  const r = window._myReports?.find(x => x.report_id === reportId);
  const panel = document.getElementById('ai-result-panel');
  if (!panel || !r) return;

  panel.innerHTML = `
    <div class="ai-card" style="margin-top:0; border:none; box-shadow:none;">
      <div class="ai-card-title">Report details</div>
      <div class="ai-comparison-grid">
        <div class="ai-comp-col">
          <div class="ai-comp-label">Community-reported type</div>
          <div class="ai-comp-value">${escapeCitizenText(r.disaster_type)}</div>
        </div>
        <div class="ai-comp-col" style="border-color: var(--accent-blue);">
          <div class="ai-comp-label">Rule-based severity estimate</div>
          <div class="ai-comp-value" style="color: var(--accent-blue);">${escapeCitizenText(r.severity || 'Unavailable')}</div>
        </div>
      </div>
      <p>Source: ${escapeCitizenText(r.source || 'Community incident report (unverified)')}</p>
      <p>Not independently verified. Severity uses unvalidated image-color/type rules and does not confirm damage.</p>
    </div>
  `;
}


/* ── Live Clock ── */
function startClock() {
  const el = document.getElementById('eoc-clock');
  if (!el) return;
  const update = () => {
    const now = new Date();
    el.textContent = now.toLocaleString('en-IN', {
      weekday: 'short', day: '2-digit', month: 'short',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
    });
  };
  update();
  setInterval(update, 1000);
}

/* ── Live Weather — uses real user location ── */
async function loadWeather() {
  const loc = await getActiveLocation();
  if (!loc) {
    const mainEl = document.getElementById('weather-current-main');
    if (mainEl) mainEl.innerHTML = '<span style="color:var(--text-muted);font-size:0.85rem">📍 Enable location access to load weather</span>';
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

    const mainEl = document.getElementById('weather-current-main');
    if (mainEl) mainEl.innerHTML = `
      <img src="https://openweathermap.org/img/wn/${iconCode}@2x.png" width="60" style="filter:drop-shadow(0 0 8px rgba(255,200,50,0.5))" />
      <div>
        <div class="eoc-weather-temp">${temp}°C</div>
        <div class="eoc-weather-desc" id="weather-current-desc">${escapeCitizenText(desc)}</div>
      </div>
    `;

    const metricsEl = document.getElementById('weather-current-metrics');
    if (metricsEl) metricsEl.innerHTML = `
      <div class="eoc-weather-stat"><span class="eoc-weather-stat-label">Humidity</span><span class="eoc-weather-stat-val">${humidity}%</span></div>
      <div class="eoc-weather-stat"><span class="eoc-weather-stat-label">Wind</span><span class="eoc-weather-stat-val">${wind} m/s</span></div>
      <div class="eoc-weather-stat"><span class="eoc-weather-stat-label">Pressure</span><span class="eoc-weather-stat-val">${pressure} hPa</span></div>
      <div class="eoc-weather-stat"><span class="eoc-weather-stat-label">Visibility</span><span class="eoc-weather-stat-val">${visibility} km</span></div>
    `;
  } catch (e) { console.error('Failed to load weather', e); }
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', async () => {
  // Route guard: reporter role only
  if (!await Session.verifyRole('reporter')) return;
  populateUserInfo();
  startClock();
  await Promise.all([
    loadWeather(),
    loadRequests(),
    loadDisasters()
  ]);
  initFilters();
  setInterval(() => { if (!document.hidden) loadRequests(); }, 15000);
});
