/**
 * ResQNet — Shared Leaflet Map Utilities
 * Zero API key required. Uses:
 *   - Leaflet.js 1.9.4 (mapping)
 *   - OpenStreetMap tiles (free, no key)
 *   - Leaflet.markercluster (clustering)
 *   - Nominatim (geocoding, free, no key)
 */

/* ── OSM Dark Tile Layer ──────────────────────────────────────────────────── */
const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/**
 * Create a Leaflet map with standard OpenStreetMap tiles.
 */
window.ResQMap = {

  /**
   * Initialize a Leaflet map in the given container element ID.
   * @param {string} containerId - DOM element ID
   * @param {object} opts - { lat, lng, zoom }
   * @returns {L.Map}
   */
  createMap(containerId, { lat = 17.4401, lng = 78.4487, zoom = 12 } = {}) {
    const map = L.map(containerId, {
      center: [lat, lng],
      zoom,
      zoomControl: true,
      attributionControl: true,
    });

    // Interactive viewing only: retain browser caching, attribution and Referer.
    // https://operations.osmfoundation.org/policies/tiles/
    L.tileLayer(OSM_TILE_URL, {
      attribution: OSM_ATTRIBUTION,
      maxZoom: 19,
      updateWhenIdle: true,
      detectRetina: false,
      referrerPolicy: 'strict-origin-when-cross-origin'
    }).addTo(map);

    // Apply dark CSS filter to the map container for consistent theming
    const container = document.getElementById(containerId);
    if (container) container.style.filter = 'brightness(0.88) contrast(1.05)';

    return map;
  },

  /* ── Marker Factories ─────────────────────────────────────────────────── */

  /**
   * Create a simple coloured circle marker icon.
   */
  circleIcon(color, size = 24) {
    return L.divIcon({
      className: '',
      html: `<div style="
        width:${size}px;height:${size}px;border-radius:50%;
        background:${color};border:3px solid white;
        box-shadow:0 0 8px ${color},0 2px 8px rgba(0,0,0,0.4);
      "></div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, -(size / 2 + 4)],
    });
  },

  /**
   * Create a pulsing circle marker icon (for High-priority markers).
   */
  pulseIcon(color) {
    const size = 26;
    const innerSize = 14;
    return L.divIcon({
      className: '',
      html: `<div style="position:relative;width:${size}px;height:${size}px;cursor:pointer">
        <div style="position:absolute;inset:0;border-radius:50%;background:${color};opacity:0.35;animation:resq-ripple 1.5s ease-out infinite"></div>
        <div style="position:absolute;top:${(size - innerSize) / 2}px;left:${(size - innerSize) / 2}px;width:${innerSize}px;height:${innerSize}px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 8px ${color}"></div>
      </div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, -(size / 2 + 4)],
    });
  },

  /**
   * Colour for a help request based on priority.
   */
  priorityColor(priority) {
    return priority === 'High' ? '#EF4444' : priority === 'Medium' ? '#F59E0B' : '#10B981';
  },

  /* ── Marker Cluster Group ─────────────────────────────────────────────── */
  createClusterGroup() {
    if (typeof L.markerClusterGroup !== 'function') return null;
    return L.markerClusterGroup({
      maxClusterRadius: 60,
      iconCreateFunction(cluster) {
        const count = cluster.getChildCount();
        return L.divIcon({
          html: `<div style="
            width:38px;height:38px;border-radius:50%;
            background:rgba(255,75,43,0.85);border:3px solid rgba(255,255,255,0.7);
            display:flex;align-items:center;justify-content:center;
            font-weight:800;font-size:0.78rem;color:white;
            box-shadow:0 0 10px rgba(255,75,43,0.5);
          ">${count}</div>`,
          className: '',
          iconSize: [38, 38],
          iconAnchor: [19, 19],
        });
      },
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
    });
  },

  /* ── Popup Styling ────────────────────────────────────────────────────── */
  /**
   * Create a styled dark popup HTML string.
   */
  popupHtml(content) {
    return `<div style="
      font-family:'Inter',sans-serif;min-width:200px;
      color:#F0F4FF;font-size:0.85rem;line-height:1.55;
    ">${content}</div>`;
  },

  /* ── Nominatim Geocoding (no API key) ─────────────────────────────────── */

  /**
   * Forward geocoding — address string → { lat, lng, displayName }
   * Backend enforces the shared application limit and caches responses.
   */
  async geocode(query) {
    if (!query || query.trim().length < 3) return null;
    try {
      const url = `${Api.BASE}/geocode?kind=search&q=${encodeURIComponent(query)}`;
      const res = await fetch(url);
      if (!res.ok) return [];
      const payload = await res.json();
      const data = payload.result || [];
      return data.map(r => ({
        lat: parseFloat(r.lat),
        lng: parseFloat(r.lon),
        displayName: r.display_name,
        shortName: r.display_name.split(',').slice(0, 3).join(', '),
      }));
    } catch {
      return [];
    }
  },

  /**
   * Reverse geocoding — { lat, lng } → readable address string
   */
  async reverseGeocode(lat, lng) {
    try {
      const url = `${Api.BASE}/geocode?kind=reverse&lat=${lat}&lon=${lng}`;
      const res = await fetch(url);
      const data = (await res.json()).result;
      if (data?.display_name) {
        // Return a concise 3-part address
        return data.display_name.split(',').slice(0, 3).join(', ');
      }
      return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    } catch {
      return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    }
  },

  /* ── Click-to-Pick Location ────────────────────────────────────────────── */

  /**
   * Enable click-to-pick on a map.
   * Calls onPick(lat, lng, addressString) whenever user clicks.
   */
  enableLocationPicker(map, onPick) {
    let pickerMarker = null;

    map.on('click', async (e) => {
      const { lat, lng } = e.latlng;

      if (pickerMarker) {
        pickerMarker.setLatLng([lat, lng]);
      } else {
        pickerMarker = L.marker([lat, lng], {
          icon: ResQMap.pulseIcon('#FF4B2B'),
          zIndexOffset: 1000,
        }).addTo(map);
      }

      pickerMarker.bindPopup(`<div style="color:#111;font-size:0.82rem">📍 Selected Location<br>${lat.toFixed(5)}, ${lng.toFixed(5)}</div>`).openPopup();

      // Reverse geocode in background
      const address = await ResQMap.reverseGeocode(lat, lng);
      onPick(lat, lng, address);
    });

    return {
      clear() {
        if (pickerMarker) { pickerMarker.remove(); pickerMarker = null; }
      }
    };
  },

  /* ── Address Search Bar ────────────────────────────────────────────────── */

  /**
   * Attach a search input (by element ID) to the map.
   * Search only on explicit Enter/button action; no provider autocomplete.
   */
  attachSearchBar(map, inputId, resultsId, onSelect) {
    const input = document.getElementById(inputId);
    const results = document.getElementById(resultsId);
    if (!input || !results) return;

    const search = async () => {
      const q = input.value.trim();
      if (q.length < 3) { results.style.display = 'none'; return; }
        const hits = await ResQMap.geocode(q);
        if (!hits || !hits.length) { results.style.display = 'none'; return; }

        results.innerHTML = hits.map((h, i) => `
          <div data-idx="${i}" style="
            padding:10px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.05);
            font-size:0.82rem;color:#e5e7eb;transition:background 0.15s;
          " onmouseover="this.style.background='rgba(255,75,43,0.12)'"
             onmouseout="this.style.background=''">${ResQMap.escapeHtml(h.shortName)}</div>
        `).join('');

        results.style.display = 'block';

        results.querySelectorAll('[data-idx]').forEach(el => {
          el.addEventListener('click', () => {
            const h = hits[parseInt(el.dataset.idx)];
            map.setView([h.lat, h.lng], 15);
            input.value = h.shortName;
            results.style.display = 'none';
            if (onSelect) onSelect(h.lat, h.lng, h.shortName);
          });
        });
    };
    input.addEventListener('input', () => { results.style.display = 'none'; });
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); search(); } });
    document.getElementById(`${inputId}-button`)?.addEventListener('click', event => { event.preventDefault(); search(); });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
      if (!input.contains(e.target) && !results.contains(e.target)) {
        results.style.display = 'none';
      }
    });
  },
};

/* ── Global CSS for pulse animation ────────────────────────────────────── */
// Shared display helpers keep each popup tied to its own API record.
ResQMap.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
ResQMap.hasCoordinates = (lat, lng) => lat !== null && lat !== undefined && lat !== ''
  && lng !== null && lng !== undefined && lng !== '' && Number.isFinite(Number(lat))
  && Number.isFinite(Number(lng)) && Math.abs(Number(lat)) <= 90 && Math.abs(Number(lng)) <= 180;
ResQMap.initialMapView = search => {
  const params = new URLSearchParams(search);
  return params.has('lat') && params.has('lng') && ResQMap.hasCoordinates(params.get('lat'), params.get('lng'))
    ? { lat: Number(params.get('lat')), lng: Number(params.get('lng')), zoom: 15 }
    : { lat: 20.5937, lng: 78.9629, zoom: 5 };
};
ResQMap.isDemoRiskZone = zone => zone.is_demo === true || /^(demo|sample)/i.test(zone.source || '')
  || (zone.description === 'Severe flash flooding expected in the Hyderabad region over the next 48 hours.'
      && Number(zone.lat) === 17.4401 && Number(zone.lng) === 78.4487
      && zone.alert_type === 'Flood' && zone.severity === 'Emergency' && Number(zone.radius_km) === 50);
ResQMap.incidentPopup = (item, kind) => {
  const escape = ResQMap.escapeHtml;
  const report = kind === 'report';
  return ResQMap.popupHtml(`<b>${item.is_demo ? 'DEMO / SAMPLE · ' : ''}${escape(report ? item.disaster_type : item.request_type)}</b>
    <div>Location: ${Number(item.latitude).toFixed(5)}, ${Number(item.longitude).toFixed(5)}${item.location_precision ? ` (${escape(item.location_precision)})` : ''}</div>
    <div>Status: ${escape(item.progress_status || item.status || 'Reported; not independently verified')}</div>
    <div>Source: ${escape(item.source || (report ? 'Community incident report (unverified)' : 'Community SOS request'))}</div>
    ${report ? '' : `<div>People requesting help: ${escape(item.number_of_people)}</div>`}
    <div>${escape(item.description)}</div>`);
};
ResQMap.riskZonePopup = zone => {
  const escape = ResQMap.escapeHtml;
  return ResQMap.popupHtml(`<b>${ResQMap.isDemoRiskZone(zone) ? 'DEMO / SAMPLE · ' : ''}${escape(zone.alert_type)} — ${escape(zone.risk_level)} risk estimate</b>
    <div>Location: ${Number(zone.lat).toFixed(5)}, ${Number(zone.lng).toFixed(5)}</div>
    <div>Status: ${escape(zone.status || 'Active alert')}</div>
    <div>Source: ${escape(zone.source || 'Alert API; source not supplied')}</div>
    <div>${escape(zone.description)}</div>
    <div>${escape(zone.risk_basis || 'Rule-based estimate; not an official warning or verified forecast')}</div>
    <div>Issued: ${escape(zone.issued_at || 'Not supplied')} · Expires: ${escape(zone.expires_at || 'Not supplied')}</div>`);
};

(function injectCSS() {
  if (document.getElementById('resqmap-style')) return;
  const style = document.createElement('style');
  style.id = 'resqmap-style';
  style.textContent = `
    @keyframes resq-ripple {
      0%   { transform: scale(0);   opacity: 0.8; }
      100% { transform: scale(4);   opacity: 0;   }
    }
    .leaflet-popup-content-wrapper {
      background: #111827 !important;
      border: 1px solid rgba(255,75,43,0.3) !important;
      border-radius: 12px !important;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6) !important;
      color: #F0F4FF !important;
    }
    .leaflet-popup-tip { background: #111827 !important; }
    .leaflet-popup-close-button { color: #9CA3AF !important; font-size: 18px !important; top: 6px !important; right: 8px !important; }
    .leaflet-popup-content { margin: 14px 16px !important; }
    .leaflet-control-zoom a { background:#1f2937 !important; color:#e5e7eb !important; border-color: rgba(255,255,255,0.1) !important; }
    .leaflet-control-zoom a:hover { background:#374151 !important; }
    .leaflet-control-attribution { background: rgba(17,24,39,0.85) !important; color:#6b7280 !important; font-size:0.65rem !important; }
    .leaflet-control-attribution a { color:#9ca3af !important; }
  `;
  document.head.appendChild(style);
})();

/* ── Phase 6: Risk Zones & NGO Depots ───────────────────────────────────── */
async function loadRiskZones(mapInstance, targetGroup = null) {
  try {
    const apiBase = (typeof Api !== 'undefined' && Api.BASE) ? Api.BASE : API_BASE;
    const res = await fetch(`${apiBase}/map/risk-zones`);
    const data = await res.json();
    if (!data.zones) return;

    const colors = { High: '#ef4444', Medium: '#f97316', Low: '#eab308', Safe: '#22c55e' };
    const icons = { Cyclone: '🌀', Flood: '🌊', Heatwave: '☀️', Storm: '⛈️' };

    data.zones.forEach(zone => {
      // Defensive check also protects local pages pointed at an older API.
      if (ResQMap.isDemoRiskZone(zone) || !ResQMap.hasCoordinates(zone.lat, zone.lng)) return;
      const color = colors[zone.risk_level] || '#22c55e';
      const icon = icons[zone.alert_type] || '⚠️';

      // Circle
      L.circle([zone.lat, zone.lng], {
        color: color,
        fillColor: color,
        fillOpacity: 0.15,
        opacity: 0.6,
        weight: 2,
        radius: zone.radius_km * 1000
      }).bindPopup(ResQMap.riskZonePopup(zone)).addTo(targetGroup || mapInstance);

      // Center marker
      const centerIcon = L.divIcon({
        className: '',
        html: `<div style="
          width:24px;height:24px;border-radius:50%;
          background:${color};border:2px solid white;
          box-shadow:0 0 8px ${color};
          display:flex;align-items:center;justify-content:center;
          font-size:12px;color:white;
        ">${icon}</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      });
      L.marker([zone.lat, zone.lng], { icon: centerIcon }).bindTooltip(`${icon} ${zone.alert_type} (${zone.risk_level} risk estimate)`)
        .bindPopup(ResQMap.riskZonePopup(zone)).addTo(targetGroup || mapInstance);
    });
  } catch (err) {
    console.warn('Could not load risk zones', err);
  }
}

async function addNgoDepotMarkers(mapInstance, targetGroup = null) {
  try {
    const apiBase = (typeof Api !== 'undefined' && Api.BASE) ? Api.BASE : API_BASE;
    const res = await fetch(`${apiBase}/ngo/locations`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.locations) return;

    data.locations.forEach(ngo => {
      if (typeof ngo.latitude !== 'number' || typeof ngo.longitude !== 'number'
          || !ResQMap.hasCoordinates(ngo.latitude, ngo.longitude)) return;

      const icon = L.divIcon({
        className: '',
        html: `<div style="
          width:28px;height:28px;border-radius:6px;
          background:#1F2937;border:2px solid #60A5FA;
          box-shadow:0 0 8px rgba(96,165,250,0.5);
          display:flex;align-items:center;justify-content:center;
          font-size:14px;
        ">🏢</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14]
      });
      L.marker([Number(ngo.latitude), Number(ngo.longitude)], { icon })
        .bindPopup(ResQMap.popupHtml(`<b>🏢 ${ResQMap.escapeHtml(ngo.name)}</b><br>Relief Depot & Organization HQ`))
        .addTo(targetGroup || mapInstance);
    });
  } catch (err) {
    console.warn('Could not load NGO locations', err);
  }
}


/* ── Phase 7: Operational Hub (Geolocation, Reverse Geocode, Layers) ── */

window._geocodeCache = {};

ResQMap.reverseGeocode = async function (lat, lng) {
  lat = Number(lat);
  lng = Number(lng);
  const fallback = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  const key = `${lat.toFixed(5)},${lng.toFixed(5)}`;
  if (window._geocodeCache[key]) return window._geocodeCache[key];
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(`${Api.BASE}/geocode?kind=reverse&lat=${lat}&lon=${lng}`, {
      signal: controller.signal, headers: { Accept: 'application/json' }, redirect: 'error'
    });
    if (!res.ok) throw new Error('Nominatim error');
    const data = (await res.json()).result || {};
    const address = data.address || {};
    const name = typeof data.display_name === 'string' && data.display_name.trim()
      ? data.display_name.split(',').slice(0, 3).join(', ')
      : address.village || address.town || address.city || address.county || address.state;
    if (!name) return fallback;
    window._geocodeCache[key] = name;
    return name;
  } catch (_) { return fallback; }
  finally { clearTimeout(timeout); }
};

// Form-only GPS action: no persistence, public location links, or navigation.
ResQMap.detectFormLocation = async function (event, { button, onLocation, map, status }) {
  event?.preventDefault();
  event?.stopPropagation();
  if (!button || button.disabled) return;
  const originalLabel = button.textContent;
  const notify = (message, kind = 'warning') => {
    if (status) status.textContent = message;
    Toast.show(message, kind);
  };
  if (!navigator.geolocation) {
    notify('Location detection is not supported. Search for an address or select a point on the map.');
    return;
  }
  button.disabled = true;
  delete button.dataset.locationChanged;
  button.textContent = 'Detecting location…';
  if (status) status.textContent = 'Allow location access when your browser asks.';
  try {
    const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(
      resolve, reject, { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    ));
    const { latitude: lat, longitude: lng } = position.coords;
    if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
      throw new Error('Invalid coordinates');
    }
    if (button.dataset.locationChanged === 'true') {
      notify('Your manually selected location was kept.', 'success');
      return;
    }
    // Keep submission usable even if the address service is slow or unavailable.
    onLocation(lat, lng);
    if (map) map.setView([lat, lng], 15);
    const fallback = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
    let address;
    try { address = await ResQMap.reverseGeocode(lat, lng); } catch (_) { address = fallback; }
    // Do not overwrite a manual selection made while the lookup was in flight.
    if (button.dataset.locationChanged === 'true') {
      notify('Your manually selected location was kept.', 'success');
      return;
    }
    onLocation(lat, lng, address || fallback);
    notify(address && address !== fallback ? 'Location captured. Check the selected point before submitting.'
      : 'Coordinates captured. Address lookup is unavailable; you can still submit.', address && address !== fallback ? 'success' : 'warning');
  } catch (error) {
    const message = error.code === 1 ? 'Location permission denied. Search for an address or select a point on the map.'
      : error.code === 3 ? 'Location detection timed out. Try again or select a point on the map.'
      : 'Location is unavailable. Search for an address or select a point on the map.';
    notify(message);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
    delete button.dataset.locationChanged;
  }
};

ResQMap.getUserLocation = function () {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation not supported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      err => reject(err),
      { enableHighAccuracy: true, timeout: 5000 }
    );
  });
};

ResQMap.getOptimalLocation = async function () {
  try {
    if (typeof getActiveLocation === 'function') {
      const loc = await getActiveLocation();
      if (loc) return { lat: loc.lat, lng: loc.lng, zoom: 12 };
    } else {
      // Fallback: try HTML5 geolocation
      const pos = await this.getUserLocation();
      return { lat: pos.lat, lng: pos.lng, zoom: 12 };
    }
  } catch (e) {
    console.warn("Location detection failed, using default.");
  }
  return { lat: 20.5937, lng: 78.9629, zoom: 5 }; // India Center
};

ResQMap.setupOperationalMap = async function (containerId, role = 'admin') {
  let centerLat = null;
  let centerLng = null;
  let hasUserLocation = false;

  // Use shared getActiveLocation() helper: browser geolocation → PostgreSQL profile
  if (typeof getActiveLocation === 'function') {
    const loc = await getActiveLocation();
    if (loc) {
      centerLat = loc.lat;
      centerLng = loc.lng;
      hasUserLocation = true;
    }
  } else {
    // Inline fallback when api.js helper is not yet available
    try {
      const pos = await ResQMap.getUserLocation();
      centerLat = pos.lat;
      centerLng = pos.lng;
      hasUserLocation = true;
    } catch (err) {
      try {
        const apiBase = (typeof Api !== 'undefined' && Api.BASE) ? Api.BASE : API_BASE;
        const token = localStorage.getItem('resqnet_token');
        if (token) {
          const res = await fetch(`${apiBase}/profile`, { headers: { 'Authorization': `Bearer ${token}` } });
          const data = await res.json();
          if (data.user && data.user.location_lat != null) {
            centerLat = data.user.location_lat;
            centerLng = data.user.location_lng;
            hasUserLocation = true;
          }
        }
      } catch (fallbackErr) { }
    }
  }

  // Fall back to India center (no specific city) when location is unavailable
  const mapLat = centerLat != null ? centerLat : 20.5937;
  const mapLng = centerLng != null ? centerLng : 78.9629;
  const mapZoom = centerLat != null ? 12 : 5;
  const map = ResQMap.createMap(containerId, { lat: mapLat, lng: mapLng, zoom: mapZoom });

  // Layer Groups
  const layers = {
    disasterReports: L.layerGroup(),
    volunteers: L.layerGroup(),
    ngos: L.layerGroup(),
    riskZones: L.layerGroup(),
    currentLocation: L.layerGroup()
  };

  // Add all layers initially (except maybe Volunteers for Reporters)
  layers.riskZones.addTo(map);
  layers.disasterReports.addTo(map);
  layers.ngos.addTo(map);
  if (role !== 'reporter') layers.volunteers.addTo(map);
  layers.currentLocation.addTo(map);

  // Layer Control
  L.control.layers(null, {
    "Risk Zones": layers.riskZones,
    "Incidents & Reports": layers.disasterReports,
    "NGO Depots": layers.ngos,
    "Volunteers": layers.volunteers,
    "My Location": layers.currentLocation
  }, { position: 'topright' }).addTo(map);

  // Plot Current Location (only when we have a real location, not the India-center fallback)
  if (hasUserLocation && centerLat != null) {
    const userIcon = L.divIcon({
      className: '',
      html: `<div style="width:20px;height:20px;border-radius:50%;background:#3b82f6;border:3px solid white;box-shadow:0 0 10px #3b82f6;"></div>`,
      iconSize: [20, 20], iconAnchor: [10, 10]
    });
    L.marker([centerLat, centerLng], { icon: userIcon })
      .bindPopup("<b>📍 Your Current Location</b>")
      .addTo(layers.currentLocation);
  }

  // Load Data
  await loadRiskZones(map, layers.riskZones);
  await addNgoDepotMarkers(map, layers.ngos);

  // Fetch Requests & Reports
  try {
    const apiBase = (typeof Api !== 'undefined' && Api.BASE) ? Api.BASE : API_BASE;
    const data = await (await fetch(`${apiBase}/map/data`)).json();

    // Plot Requests
    (data.requests || []).forEach(r => {
      if (r.is_demo || !ResQMap.hasCoordinates(r.latitude, r.longitude)) return;
      const color = ResQMap.priorityColor(r.priority_level || 'Medium');
      const icon = (r.priority_level === 'High') ? ResQMap.pulseIcon(color) : ResQMap.circleIcon(color);
      const markerId = `req-${r.request_id}`;

      const marker = L.marker([r.latitude, r.longitude], { icon }).addTo(layers.disasterReports);
      marker.bindPopup(ResQMap.incidentPopup(r, 'request'));
    });

    // Plot AI Reports
    (data.reports || []).forEach(r => {
      if (r.is_demo || !ResQMap.hasCoordinates(r.latitude, r.longitude)) return;
      const color = '#f97316'; // Orange for reports
      const icon = ResQMap.circleIcon(color);
      const markerId = `rep-${r.report_id}`;

      const marker = L.marker([r.latitude, r.longitude], { icon }).addTo(layers.disasterReports);
      marker.bindPopup(ResQMap.incidentPopup(r, 'report'));
    });

    // Plot Volunteers (if allowed)
    if (role !== 'reporter') {
      (data.volunteers || []).forEach(v => {
        if (!ResQMap.hasCoordinates(v.last_location_lat, v.last_location_lng)) return;
        const icon = ResQMap.circleIcon('#3B82F6', 16);
        L.marker([v.last_location_lat, v.last_location_lng], { icon })
          .bindPopup(`<b>Volunteer ${ResQMap.escapeHtml(v.user_name || '')}</b><br>Status: ${ResQMap.escapeHtml(v.availability_status)}`)
          .addTo(layers.volunteers);
      });
    }

  } catch (e) {
    console.warn("Operational map data fetch failed", e);
  }

  return map;
};
