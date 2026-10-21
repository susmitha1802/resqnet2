/**
 * ResQNet — API Helper
 * Centralized fetch wrapper for all backend calls
 */

// Netlify's build replaces this public URL token in its output only. No secret belongs here.
const DEPLOYED_API_BASE = '__RESQNET_API_BASE__';
const IS_LOCAL_FRONTEND = ["localhost", "127.0.0.1"].includes(window.location?.hostname);
const API_BASE = IS_LOCAL_FRONTEND
  ? (window.RESQNET_API_BASE || localStorage.getItem('resqnet_api_base') || "http://127.0.0.1:5000")
  : (DEPLOYED_API_BASE.startsWith('https://') ? DEPLOYED_API_BASE : '');
const Api = {
  /** Centralized base URL — use Api.BASE everywhere instead of hardcoding */
  BASE: API_BASE,

  async viewPrivateImage(path) {
    if (!/^\/(?:report|help-request)\/\d+\/image$/.test(path || '')) return false;
    const response = await this.fetchWithTimeout(`${this.BASE}${path}`, {
      headers: { Authorization: `Bearer ${this.getToken() || ''}` }
    });
    if (!response.ok) throw new Error('Image unavailable or access denied.');
    const blob = await response.blob();
    if (!['image/png', 'image/jpeg'].includes(blob.type)) throw new Error('Image format is unsupported.');
    const url = URL.createObjectURL(blob);
    const dialog = document.createElement('dialog');
    dialog.style.cssText = 'max-width:min(92vw,900px);max-height:92vh;background:#111827;color:white;border:1px solid #64748b;border-radius:8px;padding:16px';
    const close = document.createElement('button');
    close.textContent = 'Close image';
    close.type = 'button';
    const image = document.createElement('img');
    image.src = url;
    image.alt = 'Private incident evidence';
    image.style.cssText = 'display:block;max-width:100%;max-height:75vh;object-fit:contain;margin-top:12px';
    dialog.append(close, image);
    document.body.append(dialog);
    const dismiss = () => { dialog.close(); dialog.remove(); URL.revokeObjectURL(url); };
    close.addEventListener('click', dismiss);
    dialog.addEventListener('cancel', event => { event.preventDefault(); dismiss(); });
    dialog.showModal();
    return true;
  },

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

  /** Notification controls require both a successful HTTP status and API result. */
  async notificationRequest(endpoint, method = 'GET', body) {
    const response = await this.fetchWithTimeout(`${this.BASE}${endpoint}`, {
      method, headers: this.headers(),
      ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    if (response.status === 401 || response.status === 422) {
      Session.logout('Session expired. Please log in again.');
    }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error('Could not confirm the server result. Reload before retrying.'); }
    if (!response.ok || data?.success !== true) {
      const error = new Error(typeof data?.message === 'string' ? data.message
        : `Notification request failed (HTTP ${response.status}). Reload before retrying.`);
      error.status = response.status;
      throw error;
    }
    return data;
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
