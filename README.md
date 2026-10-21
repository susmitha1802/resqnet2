# ResQNet

Community disaster preparedness and emergency assistance for citizens, volunteers,
NGOs and administrators. Existing SOS acceptance, progress, private completion
proof and admin approval, NGO-owned resources, analytics and Leaflet mapping are
preserved. Flood Intelligence is optional and experimental; community observations
and weather thresholds are **not official disaster warnings**.

Architecture: static HTML/CSS/JavaScript + Leaflet in `frontend/`, Flask role-gated
API and SQLAlchemy records in `backend/`, local SQLite and private uploads under
ignored runtime directories. [SUBMISSION_DEMO.md](SUBMISSION_DEMO.md) gives a
role-by-role rehearsal; [SUBMISSION_READINESS_REPORT.md](SUBMISSION_READINESS_REPORT.md)
separates local demo readiness from public deployment blockers.

This source-only copy contains no accounts, database, uploaded evidence, `.env`,
virtual environment or previous Git history. See [CLEAN_REPO_AUDIT.md](CLEAN_REPO_AUDIT.md)
for copy/validation evidence and [DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md)
for unresolved release requirements. Tests passing does not certify deployment.

## Local setup (PowerShell)

Use Python 3.12 and Node.js with its built-in test runner. Commands below install
only the existing pinned backend requirements; setup was not installed/copied as
part of preparing this repository.

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Create a private local environment file with persistent random signing secrets.
This command refuses to overwrite an existing `.env` and does not print secrets:

```powershell
@'
from pathlib import Path
import secrets
p = Path('backend/.env')
text = Path('backend/.env.example').read_text(encoding='utf-8')
for key in ('SECRET_KEY', 'JWT_SECRET_KEY'):
    text = text.replace('\n' + key + '=\n', '\n' + key + '=' + secrets.token_urlsafe(48) + '\n')
with p.open('x', encoding='utf-8') as output:
    output.write(text)
print('Private backend/.env created; secret values were not printed.')
'@ | .\.venv\Scripts\python.exe -B -
```

Review `backend/.env` privately. Default `DATABASE_URL=sqlite:///resqnet.db` creates
**`backend/instance/resqnet.db`**. `UPLOAD_FOLDER=uploads` resolves to
`backend/uploads`, never frontend. `SEED_DEMO_DATA=False` and `FLASK_DEBUG=False`
must remain false. Do not point this copy at the original project's database.
Blank weather/flood settings produce unavailable results, not sample live alerts.

Initialize fresh tables, then start Flask in terminal 1:

```powershell
.\.venv\Scripts\python.exe -B -c "import sys; sys.path.insert(0, 'backend'); from app import create_app; create_app(); print('Tables initialized; no demo records seeded.')"
.\.venv\Scripts\python.exe -B backend\app.py
```

The factory creates missing tables without resetting existing ones. No demo
accounts or known passwords are provisioned. Register citizens, volunteers and
NGOs through `auth.html`. Admin enrollment remains secret-gated: an operator may
privately set a random `ADMIN_SECRET_CODE` of at least 32 characters, restart the
backend, register an authorized non-demo admin, then unset it and restart.
Never publish that code or change an existing role to bypass access checks.

In terminal 2:

```powershell
.\.venv\Scripts\python.exe -B -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open `http://127.0.0.1:5500/auth.html`. Serve **only `frontend/`**, not this repository.
Local frontend defaults to `http://127.0.0.1:5000`. Existing
`window.RESQNET_API_BASE` or `localStorage.resqnet_api_base` overrides win; inspect
`Api.BASE` and remove stale overrides before login. Hosted pages retain the
previous Render URL in `frontend/js/api.js`; verify/update it for the intended
backend before deployment. Static Netlify variables do not rewrite JavaScript.

The homepage uses the existing backend `/weather/live` proxy. Provide a rotated
`OPENWEATHER_API_KEY` only in the backend environment; never put provider keys in
HTML/JavaScript. See [LOCAL_FLOOD.md](LOCAL_FLOOD.md) for opt-in event API setup.
No satellite data or processing environment is included here.

Map address searches run only after Enter or Search. The backend `/geocode` proxy
shares a one-request-per-second limit and caches lookups, using the existing Redis
rate store across production workers. `NOMINATIM_BASE_URL` can switch providers;
set `NOMINATIM_USER_AGENT` to an app-identifying, contactable value before public
use. GPS coordinates remain usable if lookup fails. OSM tiles retain visible
attribution, browser caching and an origin Referer. Do not submit private text to
the geocoder or use the public service for bulk searches. See the
[Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) and
[tile policy](https://operations.osmfoundation.org/policies/tiles/).

SOS/report evidence accepts one valid JPG or PNG. Owners and admins open stored
images through authenticated private routes; uploads are never served from the
static frontend. NGO owners may edit quantity/location only before allocation.
Admins can review users, volunteer activity and NGO inventory, restore an
unassigned duplicate to Pending, and correct a report type without marking the
community observation scientifically verified.

## Focused verification

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests
node --test frontend/tests/*.test.cjs
node frontend/tests/auth-flow.browser.cjs
node frontend/tests/rbac.browser.cjs
node frontend/tests/detect-location.browser.cjs
```

Browser checks require installed Chrome; `CHROME_BINARY` and `PYTHON_BINARY` may
select existing executables. Tests create only isolated temporary/memory data.
Runtime directory `.gitkeep` files are intentional; databases/uploads remain ignored.
Do not run legacy data repair or demo seeding as part of normal setup.

`netlify.toml` publishes only frontend. `render.yaml` is review-only and proposes
a paid persistent disk, private uploads, production secret generation and Gunicorn.
No deployment has been performed or authorized by preparation of this repository.
Production additionally requires a reachable private Redis-compatible
`RATELIMIT_STORAGE_URI` and an operator-verified `TRUSTED_PROXY_HOPS` value.
`memory://` and zero trusted hops are local defaults, not Render production settings.
See DEPLOYMENT_READINESS.md for the Linux smoke gate and safe Render handoff.
