# Isolated ResQNet sample data

This fixture is fictional and is **not an emergency feed**. It belongs only in a
separate staging database. The existing Render production database is not an
input to these commands. Keep `SEED_DEMO_DATA=False`, `DEMO_MODE=False` and
`PROXY_DIAGNOSTIC_ENABLED=False` on the public production service.

From the repository root on a local development machine:

```powershell
.\.venv\Scripts\python.exe -B backend/seed_demo.py seed
.\.venv\Scripts\python.exe -B backend/seed_demo.py status
.\.venv\Scripts\python.exe -B backend/seed_demo.py serve
```

`seed` prompts for a password without echoing it (minimum 12 characters) and
creates the ignored `backend/instance/demo_staging.db`. It never uses the
configured `DATABASE_URL`. `serve` binds only `127.0.0.1:5001`; it has
`DEMO_MODE=True` so tagged examples appear on the staging map and the homepage
statistics identify themselves as fictional. To use the existing local static
frontend with this backend, open the page from `127.0.0.1:5500` and set
`localStorage.setItem('resqnet_api_base', 'http://127.0.0.1:5001')` in that
page's console, then reload. Remove this local override when finished with
`localStorage.removeItem('resqnet_api_base')`. Do not point the published
Netlify frontend at this local service.

If the demo password is forgotten or a noninteractive seed used an ephemeral
password, run `.\.venv\Scripts\python.exe -B backend/seed_demo.py set-password`.
It prompts privately and changes only the eight intact staging demo accounts.

The eight sample sign-ins use the entered password and these example-only
addresses: `admin@resqnet-demo.invalid`, `relief-one@resqnet-demo.invalid`,
`relief-two@resqnet-demo.invalid`, `volunteer-one@resqnet-demo.invalid`,
`volunteer-two@resqnet-demo.invalid`, `volunteer-three@resqnet-demo.invalid`,
`citizen-one@resqnet-demo.invalid`, and `citizen-two@resqnet-demo.invalid`.
The accounts cover all four roles. All names, observations, SOS descriptions,
resources and the exercise bulletin are visibly marked DEMO. One private
synthetic proof card reads "DEMO ONLY - NO REAL RESCUE"; it supports the
completed-task history without implying real evidence. There are no live
weather observations, emergency calls or AI confidence measurements.
`/public/stats` counts the staging rows and returns
`demo_mode: true`; a production response returns `demo_mode: false`.

The seed is a single transaction and an identical rerun does nothing. It
refuses an existing, mixed, or altered database. Cleanup is deliberately
conservative: it removes the complete tagged fixture and refuses to delete
anything if other records or edited markers are present. It does not delete
the staging database file or user-created uploads.

```powershell
.\.venv\Scripts\python.exe -B backend/seed_demo.py cleanup
```

For a hosted demonstration, provision a separate staging service and database,
review its security controls and backup policy, and verify that its database
identifier differs from production. Do not copy production records. The
public Render service rejects demo mode and demo account sign-ins; these
local commands also refuse to run under `APP_ENV=production` or on Render.
No live demo data will appear on the current Netlify/Render deployment until a
separate staging deployment is established or production seeding is explicitly
approved and redesigned with suitable safeguards.
