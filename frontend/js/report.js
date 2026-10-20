/**
 * ResQNet — Disaster Report Form Logic
 * Uses Leaflet click-to-pick + Nominatim reverse geocoding (no API key).
 */

let selectedDisasterType = null;
let uploadedFiles = [];
let userLocation = null;
let pickerMap = null;

/* ── Disaster Type Selection ── */
function selectDisasterType(type) {
  selectedDisasterType = type;
  document.querySelectorAll('.disaster-chip').forEach(c => {
    c.classList.toggle('selected', c.dataset.type === type);
  });
  document.getElementById('disaster-type-input').value = type;

  // Show severity hint
  const hints = {
    Flood: { icon: '🌊', desc: 'Report water levels, affected areas, and number of trapped people.' },
    Cyclone: { icon: '🌀', desc: 'Mention wind intensity, structural damage, and evacuation needs.' },
    Earthquake: { icon: '🌍', desc: 'Describe magnitude impact, building collapses, and trapped reporters.' },
    Landslide: { icon: '⛰️', desc: 'Report blocked roads, buried structures, and safe zones.' },
    Fire: { icon: '🔥', desc: 'Indicate fire spread area, evacuation status, and proximity to structures.' }
  };

  const hintBox = document.getElementById('disaster-hint');
  if (hintBox && hints[type]) {
    hintBox.innerHTML = `<div class="resq-alert info" style="margin:0">${hints[type].icon} <span><strong>${type}</strong> — ${hints[type].desc}</span></div>`;
    hintBox.style.display = 'block';
  }
}

/* ── Set Location Fields ── */
function setLocationFields(lat, lng, address) {
  userLocation = { lat, lng };
  document.getElementById('lat-input').value = lat.toFixed(6);
  document.getElementById('lng-input').value = lng.toFixed(6);

  const locInput = document.getElementById('location-input');
  const locStatus = document.getElementById('location-status');
  if (locInput) locInput.value = address || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  if (locStatus) locStatus.textContent = `✅ Location set: ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
}

/* ── Init Leaflet Location Picker ── */
async function initLocationPicker() {
  if (!document.getElementById('location-picker-map')) return;
  if (typeof ResQMap === 'undefined') {
    console.warn('ResQMap not loaded yet — will retry');
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

  // Address search
  ResQMap.attachSearchBar(pickerMap, 'loc-search-input', 'loc-search-results', (lat, lng, name) => {
    document.getElementById('get-location-btn').dataset.locationChanged = 'true';
    setLocationFields(lat, lng, name);
  });
}

/* ── GPS Detect Button ── */
function getLocation(event) {
  return ResQMap.detectFormLocation(event, {
    button: document.getElementById('get-location-btn'),
    status: document.getElementById('location-status'),
    map: pickerMap,
    onLocation: setLocationFields
  });
}

/* ── File Upload ── */
function initFileUpload() {
  const dropArea = document.getElementById('file-drop-area');
  const fileInput = document.getElementById('file-input');
  const preview = document.getElementById('file-preview');

  if (!dropArea || !fileInput) return;

  dropArea.addEventListener('click', () => fileInput.click());
  dropArea.addEventListener('dragover', (e) => { e.preventDefault(); dropArea.classList.add('drag-over'); });
  dropArea.addEventListener('dragleave', () => dropArea.classList.remove('drag-over'));
  dropArea.addEventListener('drop', (e) => {
    e.preventDefault(); dropArea.classList.remove('drag-over');
    handleFiles([...e.dataTransfer.files]);
  });
  fileInput.addEventListener('change', () => handleFiles([...fileInput.files]));

  function handleFiles(files) {
    files.forEach(file => {
      if (uploadedFiles.length >= 5) { Toast.show('Maximum 5 files allowed', 'warning'); return; }
      if (file.size > 10 * 1024 * 1024) { Toast.show(`${file.name} exceeds 10MB limit`, 'danger'); return; }
      uploadedFiles.push(file);
      renderPreviews();
    });
  }

  function renderPreviews() {
    if (!preview) return;
    preview.innerHTML = uploadedFiles.map((f, i) => `
      <div style="position:relative;display:inline-block;margin:4px">
        <div style="width:80px;height:80px;border-radius:8px;background:var(--bg-card-2);border:1px solid var(--border-glass);display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:0.65rem;color:var(--text-muted);text-align:center;padding:4px;overflow:hidden">
          ${f.type.startsWith('image/') ? `<img src="${URL.createObjectURL(f)}" style="width:100%;height:100%;object-fit:cover;border-radius:6px">` : `📁<br>${f.name.slice(0, 12)}`}
        </div>
        <button onclick="removeFile(${i})" style="position:absolute;top:-6px;right:-6px;width:20px;height:20px;border-radius:50%;background:var(--danger);border:none;color:white;font-size:0.65rem;cursor:pointer;display:flex;align-items:center;justify-content:center">✕</button>
      </div>
    `).join('');
  }
}

window.removeFile = function (i) {
  uploadedFiles.splice(i, 1);
  const preview = document.getElementById('file-preview');
  if (preview) {
    const items = preview.children;
    if (items[i]) items[i].remove();
  }
};

/* ── Submit Handler ── */
async function handleReportSubmit(e) {
  e.preventDefault();

  if (!selectedDisasterType) { Toast.show('Please select a disaster type', 'warning'); return; }
  const desc = document.getElementById('report-description').value.trim();
  if (!desc) { Toast.show('Please provide a description', 'warning'); return; }
  if (!userLocation) { Toast.show('Please select your location on the map or click "Detect My Location"', 'warning'); return; }

  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.innerHTML = '⏳ Submitting report...';

  const formData = new FormData();
  formData.append('disaster_type', selectedDisasterType);
  formData.append('description', desc);
  formData.append('latitude', userLocation.lat);
  formData.append('longitude', userLocation.lng);
  uploadedFiles.forEach(f => formData.append('images', f));

  const data = await Api.postForm('/report-disaster', formData);

  // ── Network failure: Api.postForm returns null on a thrown/network error ──
  if (data === null) {
    Toast.show('Network error — could not reach the server. Please check your connection and try again.', 'danger', 5000);
    btn.disabled = false;
    btn.innerHTML = '🚨 Submit Disaster Report';
    return;
  }

  // ── Backend validation / server error: never show success UI for these ──
  if (!data.success) {
    Toast.show(data.message || 'Could not submit disaster report. Please try again.', 'danger', 5000);
    btn.disabled = false;
    btn.innerHTML = '🚨 Submit Disaster Report';
    return;
  }

  // ── Genuine success ──
  document.getElementById('report-form').style.display = 'none';
  document.getElementById('success-state').style.display = 'flex';

  // Inject AI prediction if available
  if (data?.report?.predicted_disaster_type && data.report.predicted_disaster_type !== 'Unknown') {
    const aiPred = data.report.predicted_disaster_type;
    const aiConf = data.report.prediction_confidence;
    const aiMismatch = data.report.ai_mismatch;
    const userType = selectedDisasterType;
    
    document.getElementById('ai-prediction-text').textContent = aiPred;
    document.getElementById('ai-reporter-type').textContent = userType;
    document.getElementById('ai-confidence-pct').textContent = aiConf + '%';
    
    // Confidence Bar styling
    const bar = document.getElementById('ai-confidence-bar');
    const lbl = document.getElementById('ai-confidence-label');
    bar.style.width = aiConf + '%';
    bar.className = 'ai-conf-fill';
    
    if (aiConf >= 80) {
      bar.classList.add('high');
      lbl.textContent = 'High';
    } else if (aiConf >= 50) {
      bar.classList.add('medium');
      lbl.textContent = 'Medium';
    } else {
      bar.classList.add('low');
      lbl.textContent = 'Low';
    }
    
    // Status Badge
    const badge = document.getElementById('ai-status-badge');
    if (aiMismatch) {
      badge.className = 'ai-badge mismatch';
      badge.innerHTML = '⚠ AI prediction differs';
    } else {
      badge.className = 'ai-badge verified';
      badge.innerHTML = '✅ AI agrees with report';
    }
    
    // Display uploaded image in AI card
    if (uploadedFiles.length > 0) {
      const imgEl = document.getElementById('ai-uploaded-img');
      imgEl.src = URL.createObjectURL(uploadedFiles[0]);
      imgEl.style.display = 'block';
    }

    document.getElementById('ai-result-box').style.display = 'block';
  } else if (data?.ai_note) {
    document.getElementById('ai-prediction-text').textContent = 'AI analysis not available';
    const confTrack = document.querySelector('.ai-conf-track');
    if (confTrack) confTrack.style.display = 'none';
    document.getElementById('ai-confidence-pct').textContent = 'N/A';
    document.getElementById('ai-reporter-type').textContent = selectedDisasterType;
    
    const badge = document.getElementById('ai-status-badge');
    badge.className = 'ai-badge medium';
    badge.innerHTML = 'ℹ Manual Review Needed';

    const noteEl = document.getElementById('ai-note-text');
    if (noteEl) { noteEl.textContent = data.ai_note; noteEl.style.display = 'block'; }
    document.getElementById('ai-result-box').style.display = 'block';
  }

  const mapLink = document.getElementById('success-map-link');
  if (mapLink && data?.report?.report_id) {
    mapLink.href = `map.html?report_id=${data.report.report_id}`;
  }

  Toast.show('Disaster report submitted successfully! 🚨', 'success');
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', () => {
  if (!Session.isLoggedIn()) { location.href = 'auth.html'; return; }

  document.querySelectorAll('.disaster-chip').forEach(c => {
    c.addEventListener('click', () => selectDisasterType(c.dataset.type));
  });

  document.getElementById('get-location-btn')?.addEventListener('click', getLocation);
  document.getElementById('report-form')?.addEventListener('submit', handleReportSubmit);
  initFileUpload();
  initLocationPicker();
});
