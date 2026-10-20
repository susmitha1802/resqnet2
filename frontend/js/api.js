/**
 * ResQNet — API Helper
 * Centralized fetch wrapper for all backend calls
 */

// Explicit local override; deployed behavior keeps its existing default.
const API_BASE = window.RESQNET_API_BASE || localStorage.getItem('resqnet_api_base') || (["localhost", "127.0.0.1"].includes(window.location?.hostname) ? "http://127.0.0.1:5000" : "https://resqnet-backend-y3ur.onrender.com");
const Api = {
  /** Centralized base URL — use Api.BASE everywhere instead of hardcoding */
  BASE: API_BASE,

  /** Get JWT token from localStorage */
  getToken() {
    return localStorage.getItem('resqnet_token');
  },

  /** Build headers */
  headers(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    const token = this.getToken();
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  },

  /** Fetch with 60-second timeout for Render cold starts */
  async fetchWithTimeout(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 60000);
    options.signal = controller.signal;
    try {
      const res = await fetch(url, options);
      clearTimeout(timeoutId);
      return res;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        throw new Error('Server is waking up — please try again in a moment.');
      }
      throw err;
    }
  },

  /** GET request */
  async get(endpoint) {
    try {
      const res = await this.fetchWithTimeout(`${API_BASE}${endpoint}`, {
        method: 'GET',
        headers: this.headers()
      });
      if (res.status === 401 || res.status === 422) {
        if (!endpoint.includes('/login')) {
          Session.logout('Session invalid or expired. Please log in again.');
        }
      }
      return await res.json();
    } catch (err) {
      console.warn(`[API] GET ${endpoint} failed (offline?):`, err.message);
      return null;
    }
  },

  /** POST request */
  async post(endpoint, body) {
    try {
      const res = await this.fetchWithTimeout(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify(body)
      });
      if (res.status === 401 || res.status === 422) {
        if (!endpoint.includes('/login') && !endpoint.includes('/register')) {
          Session.logout('Session invalid or expired. Please log in again.');
        }
      }
      return await res.json();
    } catch (err) {
      console.warn(`[API] POST ${endpoint} failed (offline?):`, err.message);
      return null;
    }
  },

  /** PUT request */
  async put(endpoint, body) {
    try {
      const res = await this.fetchWithTimeout(`${API_BASE}${endpoint}`, {
        method: 'PUT',
        headers: this.headers(),
        body: JSON.stringify(body)
      });
      if (res.status === 401 || res.status === 422) {
        Session.logout('Session invalid or expired. Please log in again.');
      }
      return await res.json();
    } catch (err) {
      console.warn(`[API] PUT ${endpoint} failed (offline?):`, err.message);
      return null;
    }
  },

  /** DELETE request */
  async delete(endpoint) {
    try {
      const res = await this.fetchWithTimeout(`${API_BASE}${endpoint}`, {
        method: 'DELETE',
        headers: this.headers()
      });
      if (res.status === 401 || res.status === 422) {
        Session.logout('Session invalid or expired. Please log in again.');
      }
      return await res.json();
    } catch (err) {
      console.warn(`[API] DELETE ${endpoint} failed (offline?):`, err.message);
      return null;
    }
  },

  /** POST with FormData (file upload) */
  async postForm(endpoint, formData) {
    try {
      const h = {};
      const token = this.getToken();
      if (token) h['Authorization'] = `Bearer ${token}`;
      const res = await this.fetchWithTimeout(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: h,
        body: formData
      });
      return await res.json();
    } catch (err) {
      console.warn(`[API] POST (form) ${endpoint} failed:`, err.message);
      return null;
    }
  }
};

window.Api = Api;

/**
 * getActiveLocation()
 * Resolves the user's real coordinates for weather / risk / preparedness calls.
 *
 * Priority:
 *   1. Browser Geolocation (most accurate, live position)
 *   2. location_lat / location_lng from the user's saved profile (PostgreSQL)
 *   3. Returns null — callers must handle gracefully (show a message, skip the call)
 *
 * Never falls back to a hardcoded city.
 *
 * @returns {Promise<{lat: number, lng: number, source: string} | null>}
 */
window.getActiveLocation = async function getActiveLocation() {
  // 1. Try browser geolocation (5-second timeout)
  const fromBrowser = await new Promise((resolve) => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, source: 'browser' }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 5000 }
    );
  });
  if (fromBrowser) return fromBrowser;

  // 2. Fall back to profile location stored in PostgreSQL
  try {
    const data = await Api.get('/profile');
    const user = data?.user;
    if (user && user.location_lat != null && user.location_lng != null) {
      return { lat: user.location_lat, lng: user.location_lng, source: 'profile' };
    }
  } catch (_) { }

  // 3. No location available
  return null;
};
