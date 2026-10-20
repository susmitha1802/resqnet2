# Stage A: local Flood Intelligence

Read-only integration for `kerala-discovery-check`. No processing, deployment,
new reporting backend, or authority-only details. Existing ResQNet reporting,
SOS, role checks, risk zones and dashboards continue to use their existing APIs.

Run in separate PowerShell terminals. Use Python 3.12 for ResQNet's pinned
NumPy dependency. Keep the existing Flood Mapper environment and event artifacts.

**1. Flood Mapper event API** (reads and verifies existing results):

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\flood-damage-mapper'
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

Focused checks (from `resqnet1`):

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
