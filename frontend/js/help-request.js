/**
 * ResQNet — Help Request Form Logic
 * Uses Leaflet click-to-pick + Nominatim reverse geocoding (no API key).
 */

let uploadedImage = null;
let userLocation = null;
let aiPreviewShown = false;
let pickerMap = null;

/* ── Local rule-based priority preview; server computes final priority ── */
function computeAIPriority(type, peopleStr) {
  let score = 0;
  const people = parseInt(peopleStr, 10) || 0;
  
  if (type === 'Rescue' || type === 'Medical') score += 50;
  else if (type === 'Evacuation') score += 30;
  else score += 10;
  
  if (people > 10) score += 40;
  else if (people > 4) score += 20;
  else score += 10;

  if (score > 60) return { level: 'High', color: 'var(--danger)', reason: 'Critical needs / Many people affected.' };
  if (score > 30) return { level: 'Medium', color: 'var(--warning)', reason: 'Moderate risk / Multiple people.' };
  return { level: 'Low', color: 'var(--success)', reason: 'Standard priority / Few people.' };
}

/* ── Rule-based Priority Preview ── */
function updateAIPreview() {
  const type = document.getElementById('request-type')?.value;
  const people = document.getElementById('people-count')?.value;

  if (!type || !people) return;

  const { level, color, reason } = computeAIPriority(type, people);
  const panel = document.getElementById('ai-preview-panel');
  if (!panel) return;

  panel.style.display = 'block';
  if (!aiPreviewShown) {
    panel.style.animation = 'slideInUp 0.4s ease';
    aiPreviewShown = true;
  }

  document.getElementById('ai-priority-level').textContent = level;
  document.getElementById('ai-priority-level').style.color = color;
  document.getElementById('ai-priority-reason').textContent = reason;
}

/* ── Set Location Fields ── */
function setLocationFields(lat, lng, address) {
  userLocation = { lat, lng };
  document.getElementById('lat-input').value = lat.toFixed(6);
  document.getElementById('lng-input').value = lng.toFixed(6);
  const display = document.getElementById('location-display');
  if (display) display.textContent = `📍 ${address || lat.toFixed(4) + ', ' + lng.toFixed(4)}`;
}

/* ── Init Leaflet Location Picker ── */
async function initLocationPicker() {
  if (!document.getElementById('location-picker-map')) return;
  if (typeof ResQMap === 'undefined') {
    setTimeout(initLocationPicker, 300);
    return;
  }

  // Initialize manual picking without requesting GPS or a remote profile.
  // Browser location is requested only by the Detect Location action.
  const optLoc = { lat: 20.5937, lng: 78.9629, zoom: 5 };
  pickerMap = ResQMap.createMap('location-picker-map', { lat: optLoc.lat, lng: optLoc.lng, zoom: optLoc.zoom });

  ResQMap.enableLocationPicker(pickerMap, async (lat, lng, address) => {
    document.getElementById('get-location-btn').dataset.locationChanged = 'true';
    setLocationFields(lat, lng, address);
    Toast.show(`📍 Location selected: ${address}`, 'success');
  });

  ResQMap.attachSearchBar(pickerMap, 'loc-search-input', 'loc-search-results', (lat, lng, name) => {
    document.getElementById('get-location-btn').dataset.locationChanged = 'true';
    setLocationFields(lat, lng, name);
  });
}

/* ── GPS Detect ── */
function getLocation(event) {
  return ResQMap.detectFormLocation(event, {
    button: document.getElementById('get-location-btn'),
    status: document.getElementById('location-status'),
    map: pickerMap,
    onLocation: setLocationFields
  });
}

/* ── Image Upload ── */
function initImageUpload() {
  const drop = document.getElementById('img-drop-area');
  const input = document.getElementById('img-input');
  const preview = document.getElementById('img-preview');

  drop?.addEventListener('click', () => input?.click());
  drop?.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('drag-over'); });
  drop?.addEventListener('dragleave', () => drop.classList.remove('drag-over'));
  drop?.addEventListener('drop', (e) => {
    e.preventDefault(); drop.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) handleImage(f);
  });
  input?.addEventListener('change', () => { if (input.files[0]) handleImage(input.files[0]); });

  function handleImage(file) {
    if (!file.type.startsWith('image/')) { Toast.show('Please upload an image file', 'warning'); return; }
    uploadedImage = file;
    const url = URL.createObjectURL(file);
    if (preview) {
      preview.style.display = 'block';
      preview.innerHTML = `
        <div style="position:relative;display:inline-block">
          <img src="${url}" style="max-width:200px;max-height:150px;border-radius:10px;border:1px solid var(--border-glass)">
          <button onclick="removeImage()" style="position:absolute;top:-8px;right:-8px;width:24px;height:24px;border-radius:50%;background:var(--danger);border:none;color:white;cursor:pointer">✕</button>
        </div>
        <p style="color:var(--text-muted);font-size:0.8rem;margin-top:8px">Any rule-based severity estimate is unvalidated and does not confirm damage.</p>
      `;
    }
    if (drop) drop.style.display = 'none';
  }
}

window.removeImage = function () {
  uploadedImage = null;
  const preview = document.getElementById('img-preview');
  const drop = document.getElementById('img-drop-area');
  if (preview) { preview.style.display = 'none'; preview.innerHTML = ''; }
  if (drop) drop.style.display = 'block';
};

/* ── Submit Handler ── */
async function handleHelpRequest(e) {
  e.preventDefault();

  const name = document.getElementById('req-name').value.trim();
  const contact = document.getElementById('req-contact').value.trim();
  const type = document.getElementById('request-type').value;
  const people = document.getElementById('people-count').value;
  const desc = document.getElementById('req-description').value.trim();

  if (!name || !contact || !type || !people) { Toast.show('Please fill in all required fields', 'warning'); return; }
  if (!userLocation) { Toast.show('Please select your location on the map or click "Detect Location"', 'warning'); return; }

  const { level } = computeAIPriority(type, people);
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.innerHTML = '⏳ Processing...';

  const formData = new FormData();
  formData.append('name', name);
  formData.append('contact', contact);
  formData.append('request_type', type);
  formData.append('number_of_people', people);
  formData.append('description', desc);
  formData.append('latitude', userLocation.lat);
  formData.append('longitude', userLocation.lng);
  formData.append('priority_level', level);
  if (uploadedImage) formData.append('image', uploadedImage);

  const res = await Api.postForm('/help-request', formData);

  // ── Network failure: Api.postForm returns null on a thrown/network error ──
  if (res === null) {
    Toast.show('Network error — could not reach the server. Please check your connection and try again.', 'danger', 5000);
    btn.disabled = false;
    btn.innerHTML = '🆘 Submit Help Request';
    return;
  }

  // ── Backend validation / server error: never show success UI for these ──
  if (!res.success) {
    Toast.show(res.message || 'Could not submit help request. Please try again.', 'danger', 5000);
    btn.disabled = false;
    btn.innerHTML = '🆘 Submit Help Request';
    return;
  }

  // ── Use the server-computed priority/status as the source of truth ──
  const serverPriority = res.request?.priority_level || level;

  document.getElementById('help-form').style.display = 'none';
  document.getElementById('success-state').style.display = 'flex';
  document.getElementById('success-priority').textContent = serverPriority;
  document.getElementById('success-priority').className = `badge-${serverPriority.toLowerCase()}`;

  const mapLink = document.getElementById('success-map-link');
  if (mapLink && res?.request?.request_id) {
    mapLink.href = `map.html?request_id=${res.request.request_id}`;
  }

  Toast.show(`Help request submitted! Priority: ${serverPriority} 🚨`, serverPriority === 'High' ? 'danger' : 'success');
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', () => {
  if (!Session.isLoggedIn()) { location.href = 'auth.html'; return; }

  document.getElementById('request-type')?.addEventListener('change', updateAIPreview);
  document.getElementById('people-count')?.addEventListener('input', updateAIPreview);
  document.getElementById('get-location-btn')?.addEventListener('click', getLocation);
  document.getElementById('help-form')?.addEventListener('submit', handleHelpRequest);
  initImageUpload();
  initLocationPicker();
});
