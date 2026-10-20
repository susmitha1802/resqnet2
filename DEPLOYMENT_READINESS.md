# ResQNet deployment readiness

This is a fresh source-only preparation, not a deployed or security-certified
service. See [CLEAN_REPO_AUDIT.md](CLEAN_REPO_AUDIT.md) for the copy inventory,
exclusions, tests and original-project preservation check. Historical RBAC evidence
is retained in RBAC_AUDIT.md; no original accounts or records exist in this copy.

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
| `OPENWEATHER_API_KEY` | Optional rotated backend-only provider key. Missing configuration returns 503. |
| `FLOOD_API_BASE_URL` | Optional separately reviewed reachable upstream; blank leaves the specialist module unavailable. |

`netlify.toml` publishes only `frontend/` with security/cache headers. The Netlify
base directory must resolve to this project. `render.yaml` proposes a **paid**
starter service/disk, `backend/` root, Python 3.12.15, Gunicorn, generated secrets
and a durable `/var/data/resqnet` mount. It is review-only and has not been applied.
Verify actual API hostname in `frontend/js/api.js`; its previous hosted default
may not be the new service. Netlify environment variables do not rewrite static JS.

## Remaining release blockers

1. Revoke/rotate the previously exposed OpenWeather key from the original project.
   A fresh history does not revoke keys or remove copies of the original history.
   Rotate any formerly used published signing/admin/demo credentials as appropriate.
2. Review pinned dependency advisories and run a compatible Linux/Gunicorn build.
   No package upgrades/installations or hosted build were performed in preparation.
3. Configure and verify ingress rate limits, HTTPS, actual frontend/API origins,
   secret persistence, private storage, backups and restore/restart behavior.
4. Provision authorized non-demo accounts after setup. JWTs remain in localStorage
   and logout does not revoke a copied 24-hour token; this is not a penetration test.
5. Verify hosted end-to-end workflows separately. The public NGO directory still
   has legacy location fallback behavior requiring accuracy/publication review.
   No official alert feed or satellite validation is implied by passing tests.

No remote repository, commit, push or deployment was created. Do not apply hosting
configuration or publish until these issues and the staged-source review are approved.
