# Stage A: local Flood Intelligence

Read-only integration for `kerala-discovery-check`. No processing, deployment,
new reporting backend, or authority-only details. Existing ResQNet reporting,
SOS, role checks, risk zones and dashboards continue to use their existing APIs.

Run in separate PowerShell terminals. Use Python 3.12 for ResQNet's pinned
NumPy dependency. Keep the existing Flood Mapper environment and event artifacts.

**1. Flood Mapper event API** (reads and verifies existing results):

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\flood-damage-mapper'
$env:GDAL_PAM_ENABLED = 'NO' # Prevent GIS sidecar writes during read-only serving.
.\.venv\Scripts\python.exe -B -m src.event_api --host 127.0.0.1 --port 8765
```

**2. ResQNet Flask** (one-time environment setup, then start):

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
# Skip these two setup commands if .venv is already installed:
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:FLOOD_API_BASE_URL = 'http://127.0.0.1:8765'
# Configure persistent private signing secrets using README.md first.
Set-Location backend
..\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000
```

The upstream setting is the service origin (no `/api` suffix). It defaults to
disabled, never to a production localhost URL. Existing `backend/.env` settings
still apply; externally supplied environment values take precedence over dotenv.
Ensure the JWT and database settings are usable locally. A remote database configured there
remains remote; select your existing local database before starting if needed.

**3. Static frontend**:

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
.\.venv\Scripts\python.exe -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:5500/map.html`. In that page's browser developer console,
set the API override once (also applies to login and the other existing pages):

```javascript
localStorage.setItem('resqnet_api_base', 'http://127.0.0.1:5000');
location.reload();
```

Expand **Flood Intelligence** at bottom left, load the summary, select layers,
and click **View event area**. Layers stay off until selected. Each request loads
250 features; **Load next page** follows upstream `next_offset`. Counts show
partial/complete results. Each layer stops at 2,000 displayed features with an
explicit partial notice. Road ways in the summary differ from road geometry
pieces displayed on the map. No automatic map recentering occurs.

To restore the existing hosted API default:
`localStorage.removeItem('resqnet_api_base'); location.reload();`

Proxy routes are `/api/flood/events/kerala-discovery-check/{metadata,summary}`
and `/layers/{candidate,buildings,roads,bridges}`. Layer queries allow only
`limit=1..500`, `offset=0..1000000`, and optional EPSG:4326
`bbox=west,south,east,north`. Each response is capped at 4 MiB; upstream requests
time out after 30 seconds (45 seconds in the browser) and redirects are rejected. No graph, raw OSM,
provenance endpoint, arbitrary event, or arbitrary upstream URL is exposed.
Missing artifacts or failed verification show unavailable results, without
legacy fallback. Public fields are allowlisted; no new authority routes exist.

Focused checks (from `ResQNet`):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -p test_flood.py -v
node --test frontend\tests\flood-intelligence.test.cjs
node --check frontend\js\flood-intelligence.js
Invoke-RestMethod 'http://127.0.0.1:5000/api/flood/events/kerala-discovery-check/summary'
Invoke-RestMethod 'http://127.0.0.1:5000/api/flood/events/kerala-discovery-check/layers/buildings?limit=5&offset=0'
```

Before deployment: provide a reachable event service and its verified artifacts,
configure the backend upstream URL and frontend API origin, review public data
approval/CORS and production secrets, and perform browser checks of existing
authenticated workflows. The local event API is a development WSGI server.
Scientific readiness remains NOT_READY; exposure and network results remain
experimental. No confirmed damage, closures, passability or isolation is claimed.

## Real-data verification — 21 October 2026

The existing `flood-damage-mapper/src/event_api.py` and `src/event_dashboard.py`
already implement the required read-only adapter. ResQNet's existing allowlisted
proxy successfully served their real outputs. No replacement adapter, imagery
download, processing rerun or artifact copy is needed. The panel now reads the
existing metadata endpoint as well as summary, checks their event identity/date,
and displays actual radar observation timestamps and geographic coverage.

The reviewed event is **2024-08-20**, with coverage **76.2–76.5 E, 9.8–10.1 N**.
That reference date differs from observation and processing dates:

- Sentinel-1 GRD: **2024-08-13 00:41:18 UTC** and **2024-08-25 00:41:18 UTC**,
  relative orbit 165, descending, VV/VH. Level 5 uses exploratory -5 dB thresholds
  for both polarizations with AND fusion: 167,948 candidate pixels before Level 6.
- Level 6: Copernicus GLO-30 elevation, a 5-degree slope screen and a pre-event
  radar-darkness proxy (July 8, August 1 and August 13). This proxy is **not a
  validated permanent-water mask** and may over-filter. It retains **7,111 pixels /
  0.7111 km²**; `FILTERING_COMPLETE` is execution status, while scientific readiness
  stays `NOT_READY` and validation was not performed.
- Sentinel-2 L2A optical observations: **August 15 and August 23, 2024**, tiles
  43PFM/43PFL. Only 408 candidate pixels (5.74%) have paired usable optical evidence.
  Categories are **0 supported, 67 contradicted, 1,959 ambiguous, 5,085 unknown**.
  Level 7 remains `NOT_READY`, `READY_FOR_OSM_EXPOSURE=NO`. Unknown does not mean dry.
- Historical OSM cutoff: **2024-08-19T23:59:59Z**. Level 9 is
  `EXPERIMENTAL_POTENTIAL_EXPOSURE`: **274 buildings, 246 road ways / 276 geometry
  segments, 3,125.9584 m of road overlap, 16 bridges** (11 direct, 5 buffer-only).
  Full exposed OSM geometries can extend beyond the AOI; their whole footprint or
  road length must not be interpreted as inundated. No contact/tag dump is exposed.
- Level 10 is `EXPERIMENTAL_HYPOTHETICAL_NETWORK`: 256 physical edges removed in
  the hypothetical scenario, zero multisensor-supported affected edges. This is
  not observed road closure, passability, emergency-service access or isolation.

Selected artifacts, relative to `flood-damage-mapper/data/events/kerala-discovery-check/`:

| Level | Reviewed source |
| --- | --- |
| 5 | `level5/runs/20261019T074501055116Z-c2f1728f/experiments/level5_report.json`, provenance, raw/cleaned candidate GeoTIFFs; change GeoTIFFs in the run's `changes/` |
| 6 | `level6/runs/20261019T080523679178Z-db530064/`: `run_report.json`, `provenance.json`, `candidate_flood_filtered.tif`, DEM, slope, water proxy and reason rasters |
| 7 | `level7/classification/level7_evidence_20261019T080523679178Z-db530064.json`; evidence/confidence/reason GeoTIFFs in `level7/classification/20261019T082843493838Z/`; diagnostics and QA under `level7/` |
| 9 | `level9/runs/20261019T084408663207Z-ecedbc64/`: `level9_exposure.gpkg`, exposure report, provenance and QA |
| 10 | `level10/runs/20261019T125103902119Z-18fcd981/`: baseline GraphML, network diagnostics, provenance and QA |

The selected candidate SHA-256 is
`3b4eddc7ab003236885c2e7bcbb66ef10c101adfa2665fbf41e6b55ffbc2f081`.
The upstream loader verified the selected artifact hashes and cross-level lineage.
It does not fall back to the separate legacy/synthetic outputs under
`data/processed/` and `outputs/reports/`. Level 8's shared historical OSM manifest is
`outputs/reports/level8_historical_osm.json`. No event-specific Level 11 or trained
AI prediction is exposed by the reviewed event contract.

The analysis grid and exposure GeoPackage use **EPSG:32643**, with 10 m raster
pixels. Existing API code simplifies polygons by 8 m and infrastructure by 4 m in
that metric CRS, then transforms to **EPSG:4326 longitude/latitude** for GeoJSON.
ResQNet passes these bounded geometries to Leaflet; it does not recompute areas or
overlap lengths from simplified display geometry. GeoJSON is served from the
GeoPackage on demand, rather than requiring an exported GeoJSON copy.

**Display completeness:** the stored candidate layer contains **2,146 polygons**.
The browser intentionally loads at most **2,000**, in pages of 250, and labels it
partial. Its summary area describes the complete raster, not only the visible
subset. All 274 buildings, 276 road segments and 16 bridges fit within the cap.
Optional historical overlays remain off until selected and do not enter live SOS
feeds or automatically recenter the map.

Repeat the actual-data check without opening or modifying an application database:

```powershell
# Keep the event API from terminal 1 running, then in ResQNet:
.\.venv\Scripts\python.exe -B backend/tests/flood_real_data_smoke.py
# Optional isolated proxy + actual frontend on 127.0.0.1:8766 (no application DB):
.\.venv\Scripts\python.exe -B backend/tests/flood_real_data_smoke.py --serve
# In another terminal, with installed Chrome:
node frontend/tests/flood-real-data.browser.cjs
```

Verified: actual HTTP proxy pagination/property filtering, valid EPSG:4326 geometry,
AOI-intersecting bounds, counts reconciled to the event summary, empty out-of-area
queries, and rejected oversized page requests. Headless Chrome loaded the actual
`map.html`, summary/metadata and four real layers through the proxy; it checked
dates, NOT_READY, pagination/cap, event focus and layer removal. Only unrelated
incident APIs and OSM tile requests were stubbed; flood responses were not mocked.
These checks verify integration, not scientific validity or production hosting.

The event API remains a local development server. Hosted use still needs a reachable
read-only service with its verified artifact chain; the existing provenance embeds
local paths, so moving it requires a separately reviewed portability plan. Real
ground-truth validation, official alerts and current conditions remain outside this
historical integration. Stop the two test services with Ctrl+C when finished.
