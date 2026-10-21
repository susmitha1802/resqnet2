/* Optional Stage A overlays. The caller owns and initializes the Leaflet map. */
window.FloodIntelligence = (() => {
  const EVENT = 'kerala-discovery-check';
  const attached = new WeakSet();
  const specs = {
    candidate: ['Unvalidated flood candidate', '#38bdf8'],
    buildings: ['Potential building exposure', '#fbbf24'],
    roads: ['Potential road exposure', '#f472b6'],
    bridges: ['Potential bridge exposure', '#c084fc'],
  };

  function attach(map) {
    if (attached.has(map)) return;
    attached.add(map);
    const control = L.control({ position: 'bottomleft' });
    control.onAdd = () => {
      const panel = L.DomUtil.create('div');
      panel.className = 'flood-panel';
      panel.innerHTML = `<details><summary class="flood-heading">Flood Intelligence
        <span class="flood-warning">Unvalidated results. Check conditions on the ground.</span></summary>
        <div class="flood-scroll">
        <div class="flood-actions"><button type="button" data-focus disabled>View event area</button>
        <button type="button" data-load>Load event summary</button></div>
        <p class="flood-caption">Optional layers · candidate flooding and potential exposure</p>
        <div data-layers class="flood-layers"></div>
        <p data-status role="status" aria-live="polite">Optional layers are off.</p>
        <dl data-metrics class="flood-metrics" aria-label="Event results"></dl>
        <p data-date class="flood-caption">Historical event · ${EVENT}</p>
        <details class="flood-science"><summary>Scientific details &amp; limitations</summary>
        <p>Candidate flooding is unvalidated. Infrastructure overlaps indicate potential exposure. Network disruption is hypothetical. These results do not confirm flooding, damage, road closure, passability, or settlement isolation.</p>
        <p>Colors indicate layer type, not confidence. Road ways in the summary can contain multiple map features. Loaded feature counts are not confirmed impacts.</p>
        <div data-summary></div>
        <p>Historical OpenStreetMap data © OpenStreetMap contributors. Flood Mapper results do not replace current ground observations.</p>
        </details>
        <a href="report-disaster.html">Report a disaster using ResQNet</a>
        </div>
      </details>`;
      L.DomEvent.disableClickPropagation(panel);
      L.DomEvent.disableScrollPropagation(panel);
      const status = panel.querySelector('[data-status]');
      const summary = panel.querySelector('[data-summary]');
      const load = panel.querySelector('[data-load]');
      const focus = panel.querySelector('[data-focus]');
      const layerBox = panel.querySelector('[data-layers]');
      const metrics = panel.querySelector('[data-metrics]');
      const date = panel.querySelector('[data-date]');
      const layerToggles = [];
      let bbox;

      function metric(label, value, unit = '', digits = 0) {
        const card = document.createElement('div');
        const name = document.createElement('dt');
        const number = document.createElement('dd');
        name.textContent = label;
        number.textContent = typeof value === 'number' && Number.isFinite(value)
          ? `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${unit}` : 'Unavailable';
        card.append(name, number);
        metrics.appendChild(card);
      }

      async function get(path) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 45000);
        try {
          const response = await fetch(`${Api.BASE}/api/flood/events/${EVENT}/${path}`, { signal: controller.signal });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Flood service unavailable.');
          return data;
        } finally { clearTimeout(timer); }
      }

      function line(text) {
        const p = document.createElement('p');
        p.textContent = text;
        summary.appendChild(p);
      }

      focus.onclick = () => {
        if (bbox) map.fitBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]]);
      };
      load.onclick = async () => {
        load.disabled = true;
        status.textContent = 'Loading historical event results…';
        try {
          const [s, metadata] = await Promise.all([get('summary'), get('metadata')]);
          if (metadata.event_id !== EVENT || s.event_id !== EVENT || metadata.event_date !== s.event_date) {
            throw new Error('Event metadata does not match the summary');
          }
          summary.replaceChildren();
          bbox = s.aoi_bbox_epsg4326;
          focus.disabled = !Array.isArray(bbox) || bbox.length !== 4;
          metrics.replaceChildren();
          metric('Candidate area', s.candidate.area_km2, ' km²', 4);
          metric('Buildings · potential', s.exposure.buildings.candidate_intersecting);
          metric('Road overlap', s.exposure.roads.candidate_overlap_length_m, ' m', 1);
          metric('Bridges · potential', s.exposure.bridges.potentially_exposed);
          date.textContent = `Historical event: ${s.event_date} · ${EVENT}`;
          const pair = metadata.acquisition_pair || {};
          line(`Sentinel-1 observations: before ${pair.before_acquisition || 'unavailable'}; after ${pair.after_acquisition || 'unavailable'}. The event date is a reference date, not an observation or forecast date.`);
          line(`Coverage (EPSG:4326 west, south, east, north): ${(metadata.aoi_bbox_epsg4326 || []).join(', ')}. Map geometries are simplified for display; measurements come from the processed source data.`);
          line(`Candidate: ${s.candidate.pixels} pixels / ${s.candidate.area_km2} km². Potential road exposure: ${s.exposure.roads.candidate_intersecting} road ways.`);
          line(`Hypothetical network: ${s.network.hypothetical_disruption.affected_physical_edges} removed physical segments. This is a scenario, not observed closures.`);
          line(`Scientific status: ${Object.entries(s.scientific_status).map(([k, v]) => `${k}=${v}`).join('; ')}.`);
          line(`Optical evidence: ${Object.entries(s.optical_evidence.categories).map(([k, v]) => `${k}: ${v.pixels} pixels`).join('; ')}.`);
          // Flood Mapper availability is scoped to that event; reporting stays in ResQNet.
          for (const key of ['settlements', 'ai']) {
            const item = s.availability[key];
            if (!item.available) line(item.reason);
          }
          (s.warnings || []).forEach(line);
          layerToggles.forEach(toggle => { toggle.disabled = false; });
          status.textContent = 'Choose layers, then View event area.';
          load.textContent = 'Refresh event summary';
        } catch (err) {
          status.textContent = `Flood Intelligence unavailable: ${err.message}. Existing ResQNet services are separate.`;
        } finally { load.disabled = false; }
      };

      function makeLayers() {
        for (const [key, [label, color]] of Object.entries(specs)) {
          const row = document.createElement('div');
          row.className = 'flood-layer-row';
          const labelEl = document.createElement('label');
          const toggle = document.createElement('input');
          toggle.type = 'checkbox';
          toggle.disabled = true;
          layerToggles.push(toggle);
          labelEl.append(toggle, document.createTextNode(` ${label}`));
          labelEl.style.color = color;
          const more = document.createElement('button');
          more.type = 'button';
          more.textContent = 'Load next page';
          more.hidden = true;
          const count = document.createElement('span');
          row.append(labelEl, document.createElement('br'), more, count);
          layerBox.appendChild(row);
          const overlay = L.geoJSON(null, {
            style: { color, weight: key === 'roads' ? 3 : 2, fillOpacity: 0.22 },
            pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { color, radius: 5 }),
            onEachFeature: (feature, item) => {
              const popup = document.createElement('div');
              popup.textContent = `${label}. ${feature.properties.name || ''} Unconfirmed; field verification required.`;
              item.bindPopup(popup);
            },
          });
          let offset = 0, loaded = 0, busy = false;
          async function page() {
            if (busy || offset === null) return;
            busy = true;
            more.disabled = true;
            status.textContent = `Loading ${label}…`;
            try {
              const data = await get(`layers/${key}?limit=250&offset=${offset}`);
              overlay.addData(data);
              loaded += data.features.length;
              offset = data.next_offset;
              count.textContent = ` ${loaded} features loaded${offset !== null ? ' (partial)' : ' (complete)'}`;
              more.hidden = offset === null || loaded >= 2000 || !toggle.checked;
              status.textContent = loaded >= 2000 && offset !== null
                ? 'Display capped at 2,000 features for this layer; results are partial.'
                : 'Layer loaded. Feature counts describe geometry, not confirmed impacts.';
              if (toggle.checked) overlay.addTo(map);
            } catch (err) {
              status.textContent = `${label} unavailable: ${err.message}`;
              more.hidden = !toggle.checked; // Retry the same page, preserving existing data.
            } finally { busy = false; more.disabled = false; }
          }
          toggle.onchange = () => {
            if (toggle.checked) {
              overlay.addTo(map);
              more.hidden = offset === null || loaded >= 2000;
              if (!loaded) page();
            } else { map.removeLayer(overlay); more.hidden = true; }
          };
          more.onclick = page;
        }
      }
      makeLayers();
      return panel;
    };
    control.addTo(map);
  }
  return { attach };
})();
