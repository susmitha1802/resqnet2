# ResQNet deployment readiness

Backend review updated 20 October 2026. **Not yet cleared for production:** actual
Linux/Gunicorn, Redis, Render mount/proxy, backup and hosted workflow gates remain.
All work and dependency installation for this review stayed inside the new ResQNet
project; the original resqnet1 was not accessed or changed. No real database was
opened, migrated or reset, and no service was deployed or pushed.

See [CLEAN_REPO_AUDIT.md](CLEAN_REPO_AUDIT.md) for the earlier source-copy inventory.
Its initial test/staging snapshot is historical; the results below supersede it.

## Retained protections

- JWT identity and current database role enforce API permissions; changing browser
  role fields does not grant access. Admin enrollment requires an operator secret.
- SOS/contact/private proof access is role/ownership checked. Anonymous map data is
  aggregate-only, and responder previews omit private free text/contact details.
- SOS completion requires admin approval of assigned-volunteer proof, with
  synchronized transactional request/task states and rollback/conflict checks.
- NGO resources and allocation remain owner scoped; analytics are admin-only.
- Production requires persistent signing/session secrets, exact HTTPS CORS origins,
  debug/seeding disabled, durable SQLite and private upload storage.
- Runtime uploads are validated and privately stored; private/auth responses are
  not cacheable. Identified HTML injection paths remain escaped.
- Homepage weather now uses the existing backend proxy. No provider key is present
  in browser source. Weather advisories and optional Flood Intelligence remain
  unvalidated, never official disaster warnings or confirmed damage.

## Environment and hosting

Local setup in README.md creates fresh SQLite tables with seeding disabled.
`backend/.env.example` contains blank secret fields and harmless defaults only.

| Variable | Production requirement |
| --- | --- |
| `APP_ENV` | `production`; Render selects this automatically. |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Independent persistent random values, at least 32 characters; generated/stored privately. |
| `ADMIN_SECRET_CODE` | Unset normally. For authorized enrollment only, private random value of at least 32 characters; unset afterward. |
| `FLASK_DEBUG`, `SEED_DEMO_DATA` | `False`. Demo identities remain blocked in production. |
| `CORS_ORIGINS` | Exact actual HTTPS frontend origins, no wildcard/trailing slash. |
| `PERSISTENT_STORAGE_PATH` | Actual mounted private storage root. |
| `DATABASE_URL` | Proposed SQLite path: `sqlite:////var/data/resqnet/resqnet.db`. Do not point at the original local database. |
| `UPLOAD_FOLDER` | Proposed private mounted path: `/var/data/resqnet/uploads`. |
| `RATELIMIT_STORAGE_URI` | Private reachable Redis/Redis-compatible service URL; memory counters and silent fallback are prohibited. |
| `TRUSTED_PROXY_HOPS` | Operator-verified number of trusted `X-Forwarded-For` entries, from 1 to 5 on Render. No assumed default is supplied. |
| `OPENWEATHER_API_KEY` | Optional rotated backend-only provider key. Missing configuration returns 503. |
| `FLOOD_API_BASE_URL` | Optional separately reviewed reachable upstream; blank leaves the specialist module unavailable. |

`netlify.toml` publishes only `frontend/` with security/cache headers. The Netlify
base directory must resolve to this project. `render.yaml` proposes a **paid**
starter service/disk, `backend/` root, Python 3.12.15, Gunicorn, generated secrets
and a durable `/var/data/resqnet` mount. It is review-only and has not been applied.
Verify actual API hostname in `frontend/js/api.js`; its previous hosted default
may not be the new service. Netlify environment variables do not rewrite static JS.

The blueprint now requests both rate-limit settings explicitly. It does **not**
provision Redis. Create/configure an appropriate Render Key Value service in the
same private region/network, provide its private URL only to the backend, and
verify availability/capacity. No external store has been created or tested here.
Production checks Redis connectivity before database initialization and refuses
startup when unavailable. Runtime Redis errors return generic 503 and block the
handler; no in-memory fallback accepts an uncounted operation.

The intended configured frontend is `https://resqnet1-2026.netlify.app`. Exact
origin/preflight, authorization-header access and denied origins are tested. Its
actual hosting settings/domain ownership and a new API hostname are unverified;
change the allowlist to the actual frontend origin if it differs.

## Targeted repairs and evidence

| Dependency | Previous pin | Reviewed pin | Evidence |
| --- | --- | --- | --- |
| Flask | 3.1.2 | 3.1.3 | Previous version has a reported advisory; security patch retained within 3.1. |
| Pillow | 11.3.0 | 13.0.0 | Multiple image-processing advisories; required update, PNG/JPEG restrictions retained. |
| Werkzeug | 3.1.3 | 3.1.9 | Security fixes, including Windows special-name path handling. |
| python-dotenv | 1.1.1 | 1.2.4 | Reported advisory fixed; external environment still takes precedence. |

Public PyPI metadata was checked for every installed runtime distribution:
**35 packages, zero advisory matches after updates**; `pip check` passed. This is
a dated advisory-feed check, not a guarantee of no undiscovered issues. Remaining
direct pins were retained where no advisory required a change. Transitive versions
are resolver-selected rather than a complete cross-platform lock; recheck during
the Linux build. [PyPI metadata API](https://docs.pypi.org/api/json/),
[Pillow advisories](https://github.com/python-pillow/Pillow/security/advisories),
[Werkzeug advisories](https://github.com/pallets/werkzeug/security/advisories).

Flask-Limiter with its Redis extra is the only new application dependency, needed
for the missing abuse controls. Defaults per client IP and endpoint are 60/minute
for mutations and 120/minute for reads, with these explicit limits:

- Login 10/minute; registration and contact 5/hour each.
- SOS/report creation, proof upload and admin weather fetch 10/minute each.
- Public live weather 30/minute.

Health and HEAD/OPTIONS are exempt. Throttled requests return JSON 429 and
`Retry-After`; all original JWT/role/ownership checks remain. Limits include failed
attempts and are not guarantees against distributed attacks. Tune them with
realistic shared-network/emergency traffic and retain edge protections.

Only the configured trusted suffix of `X-Forwarded-For` affects client identity;
untrusted headers are ignored locally and forwarded Host/Port are never trusted.
Verify the actual Render proxy chain before choosing the hop count: too many
trusted entries can permit spoofing; too few can throttle everyone as one client.
[Render application abuse guidance](https://render.com/articles/how-render-handles-ddos-attacks),
[ProxyFix trust requirements](https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/),
[Flask-Limiter storage](https://flask-limiter.readthedocs.io/en/stable/configuration.html).

## Database and private images

This deployment uses one Render instance, one Gunicorn worker and mounted SQLite.
The guard now verifies that Render's configured storage root is an actual mount,
not merely an absolute ephemeral directory. SQLite and all upload subdirectories
must resolve within that private mount; escaping upload symlinks are rejected.
Flask and Netlify do not serve the upload directory. Proof viewing remains JWT-
checked for the assigned volunteer/admin; report paths are not public URLs.

Empty databases initialize from model metadata at runtime, after storage checks.
An existing database with missing tables/columns fails before any DDL or data
repair. Compatible existing schemas are opened without `create_all()` changes.
No model/schema change was introduced, so a matching database needs no migration.
There is no automatic migration framework or full type/index/constraint/legacy-data
validation: any imported/incompatible database needs a separately reviewed backup
and migration plan. Do not run reset, demo seed or repair scripts as deployment steps.
Non-SQLite production URLs are refused pending a reviewed driver/migration plan.

Tests prove temporary SQLite records and private images survive a second app
factory and are not publicly accessible. This does **not** prove Render persistence.
Use a paid disk, monitor the proposed 1 GiB capacity, and test backup/restore plus
restart/redeploy retention before release. A disk restricts the service to one
instance and prevents zero-downtime deploys. Build/pre-deploy commands cannot access
it; do not initialize/migrate this SQLite file there.
[Render disks](https://render.com/docs/disks), [deployment lifecycle](https://render.com/docs/deploys).

## Verification and Linux gate

Final local regressions: **78 backend tests and 53 frontend tests passed**.
Backend tests include ten new production checks for throttling, spoofed headers,
Redis-outage failure, schema/data preservation, image persistence and actual WSGI
import/startup. SQLAlchemy `Query.get()` deprecation warnings remain. All data was
memory-only/temporary; Redis health/outage tests use mocks or isolated memory
counters, not a live Redis instance.

Python 3.12.10 on Windows installed the reviewed requirements successfully. Existing
`backend/wsgi.py` remains the correct callable and passes subprocess import plus
health/schema checks. Gunicorn requires Linux/Unix facilities; this machine has
no usable WSL/Docker. **No actual Gunicorn process or Linux build was executed.**
The explicit `gthread` worker, one worker, four threads and 90-second timeout in
the blueprint are compatible configuration choices, not a completed Linux test.

Run locally:

```powershell
.\.venv\Scripts\python.exe -B -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -B -m pip check
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests
node --test frontend/tests/*.test.cjs
```

Before deployment, run on an isolated Linux Python 3.12 environment with a dedicated
test Redis instance. Set `SMOKE_REDIS_URL` privately; never use production Redis.
The smoke gate creates only temporary SQLite/uploads, imports the actual WSGI app,
runs real Gunicorn, checks CORS/private paths/rate limits and restarts it. It never
flushes Redis or reads an existing database. No secrets are printed.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -B -m unittest discover -s backend/tests
.venv/bin/python -B backend/tests/gunicorn_smoke.py
```

## Safe Render handoff (not executed)

1. Revoke/rotate the old exposed provider key separately; do not copy original
   `.env`, database, uploads or history. Review and approve these working-tree
   changes before any separately authorized commit/push/deployment.
2. Pass the isolated Linux gate and dependency review. Create/approve the external
   Redis-compatible service, privately supply its URL, and verify the actual proxy
   chain. Do not guess `TRUSTED_PROXY_HOPS` or use public client-supplied entries.
3. Review `render.yaml`: backend root, paid starter/disk, mount and storage paths,
   actual CORS origin, generated persistent signing secrets, debug/seeding off.
   Set optional provider keys only in backend environment. No `.env` is deployed.
4. When separately authorized, apply the reviewed configuration. Build command:
   `pip install -r requirements.txt`. Start command from `backend/`:
   `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --worker-class gthread --timeout 90 wsgi:application`.
   Leave SQLite pre-deploy initialization/migration commands empty; the disk exists
   only at runtime. Fresh tables initialize then; incompatible schemas refuse startup.
5. Before opening service to users, verify `/health`, CORS preflight and browser
   API origin; provision an authorized non-demo admin through restricted enrollment,
   then disable enrollment. Check cross-role access, authenticated private proofs,
   rate-limit behavior and Redis outage handling. Do not log tokens/contact data.
6. Test disk retention across restart/redeploy, and a coordinated SQLite/private-
   uploads backup/restore in a separate environment. Confirm HTTPS, capacity alerts,
   access controls and emergency/shared-network behavior before public use.

Required operator environment names only: `APP_ENV`, `SECRET_KEY`, `JWT_SECRET_KEY`,
`FLASK_DEBUG`, `SEED_DEMO_DATA`, `CORS_ORIGINS`, `DATABASE_URL`,
`PERSISTENT_STORAGE_PATH`, `UPLOAD_FOLDER`, `RATELIMIT_STORAGE_URI`,
`TRUSTED_PROXY_HOPS`, `PYTHON_VERSION`. Render supplies `PORT` and `RENDER`.
Optional: `ADMIN_SECRET_CODE`, `OPENWEATHER_API_KEY`, `FLOOD_API_BASE_URL`,
`MAX_CONTENT_LENGTH`.

Files changed in this backend review: `render.yaml`, `backend/.env.example`,
`backend/requirements.txt`, `backend/config.py`, `backend/security.py`,
`backend/app.py`, `backend/database.py`, `backend/rate_limits.py`,
`backend/tests/test_deployment_security.py`, `backend/tests/test_production_backend.py`,
`backend/tests/gunicorn_smoke.py`, `README.md`, `CLEAN_REPO_AUDIT.md`,
`DEPLOYMENT_READINESS.md`. WSGI entry point, application workflows, frontend and
Flood Intelligence code were inspected/preserved without redesign.

## Remaining release blockers

1. Revoke/rotate the previously exposed OpenWeather key from the original project.
   A fresh history does not revoke keys or remove copies of the original history.
   Rotate any formerly used published signing/admin/demo credentials as appropriate.
2. Run the Linux/Gunicorn gate and a compatible hosted build; local dependency
   updates/checks passed but no Linux or hosted process was verified.
3. Provision/verify Redis, proxy identity, actual disk persistence, HTTPS/API origins,
   backup/restore, ingress controls and operational rate thresholds.
4. Provision authorized non-demo accounts after setup. JWTs remain in localStorage
   and logout does not revoke a copied 24-hour token; this is not a penetration test.
5. Verify hosted end-to-end workflows separately. The public NGO directory still
   has legacy location fallback behavior requiring accuracy/publication review.
   No official alert feed or satellite validation is implied by passing tests.

No remote repository, commit, push or deployment was created. Do not apply hosting
configuration or publish until these issues and the staged-source review are approved.
