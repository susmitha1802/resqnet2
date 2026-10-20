# ResQNet RBAC audit and targeted repair

This is historical evidence from the original working project, retained for code
and policy context. It does not describe accounts or records in this fresh copy.
Current preparation results and release limits are in CLEAN_REPO_AUDIT.md and
DEPLOYMENT_READINESS.md; later security repairs supersede older findings below.

Latest deployment/security review: [DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md).
It supersedes historical CORS/JWT/demo-seed findings below: production now requires
persistent secrets and exact HTTPS origins, blocks demo credentials, and rejects
demo seeding. Existing invalid notification rows remain unchanged; future seeding
uses valid statuses and refuses nonempty databases. Release blockers remain.

## Admin Analytics SQLite repair

Reproduced through the actual `GET /admin/analytics` handler with an authorized
admin and recent requests in an in-memory SQLite database. The weekly query used:

```sql
SELECT CAST(help_requests.created_at AS DATE) AS day, count(help_requests.request_id)
FROM help_requests WHERE help_requests.created_at >= ? GROUP BY day ORDER BY day;
```

SQLite returned integer `2026` for that cast, whereas SQLAlchemy's Date result
processor expected an ISO date string and raised `TypeError: fromisoformat:
argument must be str`. A read-only query on the existing database confirmed the
integer conversion. The handler now groups/orders by `date(created_at)`, yielding
full `YYYY-MM-DD` values, and retains the existing rolling seven-day UTC window.
There is no data update, reset or migration.

The count/chart check also reproduced existing presentation defects: the status
chart omitted Duplicate records, unavailable volunteers were included in On Active
Task, and all tasks were labelled Tasks Completed. The chart now includes Duplicate;
the summary uses explicit `busy_volunteers` (recorded `on_task` availability) and
`completed_tasks` (recorded Completed task status) counts. Existing response fields
remain compatible. Failed API calls no longer overwrite existing values with zero
or empty charts. These counts report stored statuses; legacy status inconsistencies
are not silently repaired or reclassified.

Files changed: `backend/routes/admin.py`, `frontend/js/admin-dashboard.js`,
`backend/tests/test_admin_analytics.py`, `backend/tests/test_rbac.py`,
`frontend/tests/admin-analytics.test.cjs`, `RBAC_AUDIT.md`.
The RBAC test now expects the analytics handler to work rather than expecting its
former TypeError. Admin-only server authorization is unchanged and tested against
anonymous callers, reporter/volunteer/NGO callers and a forged admin role claim.

Verification: 4 new backend analytics tests + 15 existing admin/RBAC tests + 17
existing SOS lifecycle tests passed (36 total). Frontend analytics/RBAC/SOS tests
passed (17 total). The date regression covers multiple dates in the same year,
UTC midnight boundaries, ordering, within/outside the seven-day cutoff, empty
incident data, all aggregation groups and independent Python record counts.
The frontend checks verify chart categories/counts, trend points, summary values
and API-failure behavior using the actual dashboard script.

A read-only SQLite backup into memory was also passed through the real admin
routes with an isolated test JWT secret. All groups, daily points and dashboard
counts matched independently read existing records: 6 requests, 3 reports, 4
volunteers (1 available, 2 recorded on_task), and 1 completed task at verification
time. No existing data or real-account credentials were changed/accessed for login.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_admin_analytics.py
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_rbac.py
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_sos_lifecycle.py
node --test frontend/tests/admin-analytics.test.cjs frontend/tests/rbac.test.cjs frontend/tests/sos-lifecycle.test.cjs
node --check frontend/js/admin-dashboard.js
```

Restart the local Flask service to load the backend change, then hard-refresh the
admin dashboard, sign in as admin and confirm `/admin/analytics` returns 200 with
ISO dates and the charts load. No browser rendering check or live PostgreSQL test
was performed for this repair. Existing external weather-key requirements and
other separately documented risks remain; no deployment or flood pipeline changes.

## Follow-up: persistent redirect and warm browser cache

A real Chrome warm-cache regression reproduced the reported sequence after the
earlier source fix. The test first cached the pre-fix role handler under the
original `/js/auth.js` URL, then reloaded the current, complete `auth.html` while
the server offered the repaired script. The unversioned URL reused the cached
handler: Volunteer registration landed on `/user-dashboard.html`, and the actual
Flask `/profile` returned `reporter`. The handler sent reporter; the registration
route stored that role rather than changing volunteer to reporter. This is a
controlled reproduction of stale-script behavior, not inspection of the user's
private browser cache or proof of the current real account's identity.

The product fix is one script URL change in `frontend/auth.html`:
`js/auth.js?v=role-state-20261020`. A freshly loaded auth document now requests the
repaired script even while the old unversioned asset remains in browser cache.
No guard, backend permission, database role or redirect mapping was overridden.

The two redirect paths are distinct:

- Login saves the backend-returned user/token and calls
  `Session.redirectIfLoggedIn()` (`frontend/js/auth.js:84–86`).
- Direct volunteer-page access calls `Session.verifyRole('volunteer')`
  (`frontend/js/volunteer-dashboard.js:557`); `main.js:123–141` retrieves `/profile`
  and redirects to the dashboard matching that database role. A reporter landing
  on the citizen dashboard here is the required authorization behavior.

No application code generates `/resqnet1/frontend/volunteer-dashboard.html`.
The current frontend server root is already `frontend`; that extra path returns
404. The correct address is `http://127.0.0.1:5500/volunteer-dashboard.html`.
Live served auth/main/API/volunteer scripts matched the files on disk. No service
worker registration was found. Duplicate role-card click bindings are idempotent
and were not the reproduced cause. The latest six existing local account records
are reporters, but no account is assumed to be the currently authenticated browser
user without its `/profile` output. No existing account was changed.

Files changed in this cache follow-up:

- `frontend/auth.html`: version the repaired auth script URL.
- `frontend/tests/auth-flow.browser.cjs`: warm-cache regression, safe role trace,
  reporter manual-URL/cached-role denial, temporary browser-profile cleanup.
- `RBAC_AUDIT.md`: findings, verification and recovery instructions.

Actual results: the warm-cache test **failed before** the URL change with
`page=/user-dashboard.html, profileRole=reporter`; it **passed afterward** with
submitted/stored/profile role `volunteer`. All four cold browser role flows passed,
including registration, login, logout, profile and dashboard checks. The reporter
test also manipulates its cached role to volunteer and confirms the real database
role still denies access. Real frontend files and Flask authentication routes are
used; accounts/uploads/database/browser profiles are temporary. External CDNs are
disabled. The warm cache is deliberately seeded with the old handler; no user's
personal browser profile is accessed. Focused backend: 15 RBAC + 17 SOS lifecycle
tests passed. Focused frontend: 13 auth/RBAC tests passed. Syntax/diff checks passed.

```powershell
node frontend/tests/auth-flow.browser.cjs --warm-cache
node frontend/tests/auth-flow.browser.cjs
node --test frontend/tests/auth-flow.test.cjs frontend/tests/rbac.test.cjs
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_rbac.py
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_sos_lifecycle.py
```

For the real browser:

1. Log out of the current dashboard. Open
   `http://127.0.0.1:5500/auth.html?refresh=role-state-20261020` so the auth document
   is fetched afresh. Confirm the loaded auth script has the `?v=role-state-20261020`
   suffix in DevTools Network. The live local server was checked serving that URL
   with exactly the repaired script bytes.
2. Confirm `Api.BASE` is the intended backend (`http://127.0.0.1:5000` for default
   local use). A stored override remains intentional configuration; it is not
   silently removed. Do not mix localhost and 127.0.0.1 storage origins.
3. If an existing account's `/profile` role is reporter, it remains reporter after
   this fix. Register a new, distinct email with Volunteer selected, then sign out
   and sign in again. Reusing an existing email returns 409 rather than converting
   it. Existing-account conversion requires separate explicit authorization.
4. Verify `/profile` role `volunteer`, the volunteer dashboard URL/label and a
   successful `/volunteer/tasks` response. No assignments is a valid empty task
   result. Do not bypass the guard if `/profile` says reporter.

The user's current session/backend override is still unverified pending the
requested privacy-safe `/profile` snapshot. The reproduced cache defect is fixed;
no claim is made that an unidentified existing reporter account is a volunteer.

## Follow-up: registration role defect reproduced and fixed

The auth-page registration selector updated `window.selectedRole`
(`frontend/auth.html:592–604`), but `frontend/js/auth.js` declared a separate
top-level `let selectedRole`. A classic script's global lexical `let` is not the
same storage as a property on `window`. Selecting Volunteer/NGO/Admin left the
registration handler's role as reporter. Tests using the real inline selector
reproduced all three incorrect registration payloads before the repair.

`auth.js` now uses the selector's `window.selectedRole` consistently. It also
reads the actual `reg-org-name` and `reg-availability` form fields; targeted tests
reproduced NGO registration rejection and incorrect volunteer availability from
the old nonexistent field IDs. Login still sends email/password only, saves the
backend user/role/token, and uses the existing four-role redirects. JWT identity,
database authorization and SOS lifecycle code are unchanged in this follow-up.

An account created through the broken selector could therefore genuinely be a
reporter, for which the citizen redirect is correct. **The affected real account's
role and registration history are not confirmed without its authenticated profile.**
No existing account was promoted. Registration intent cannot be reconstructed from
the current database role alone; the application has no registration-role history.

Read-only environment checks found the configured database is SQLite at
`backend/instance/resqnet.db`, with 6 reporter and 3 volunteer accounts. No volunteer
profile was attached to a non-volunteer user. Services on local ports 5000 and 5500
responded, and served auth HTML/JS/API helper bytes matched the working files.
The affected browser's API override and the running backend process's database
selection still require confirmation; these checks do not establish that its
current session uses this database.

Exact files changed in this follow-up:

- `frontend/js/auth.js`
- `frontend/tests/auth-flow.test.cjs`
- `frontend/tests/auth-flow.browser.cjs`
- `backend/tests/auth_browser_server.py`
- `RBAC_AUDIT.md`

Focused results: **39 backend tests passed** (15 RBAC, 17 SOS lifecycle, 7 acceptance);
**26 frontend tests passed** (auth flow, RBAC, acceptance and SOS lifecycle).
JavaScript syntax and whitespace checks passed. No final focused test failures
or skips. The initial failing tests reproduced the defects described above.

**Four real headless Chrome role flows passed** against the actual Flask routes
using a temporary in-memory database: register from auth.html, verify database
role through `/profile`, log out, log in again, and check dashboard URL/role label.
Logout/account switching and stale role keys were checked; the volunteer flow
also verified `/volunteer/tasks` access and the citizen-page redirect guard.
Only external CDN assets were intercepted; registration, password authentication,
JWT verification, profile and task API responses came from the real Flask routes.
The sandboxed Chrome renderer timed out; the same isolated test passed outside
the sandbox. **This verifies temporary volunteer login, not the affected existing
account.** No real accounts, existing database rows, pipeline or deployment changed.

Reproduce these focused checks from the repository:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_rbac.py
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_sos_lifecycle.py
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_volunteer_acceptance.py
node --test frontend/tests/auth-flow.test.cjs frontend/tests/rbac.test.cjs frontend/tests/volunteer-acceptance.test.cjs frontend/tests/sos-lifecycle.test.cjs
node frontend/tests/auth-flow.browser.cjs
node --check frontend/js/auth.js
```

The browser script starts its own temporary API/frontend server, uses installed
Chrome and the existing `.venv`, and stops them afterward. It does not target
your existing service on port 5000 or write to its database.

### Verify the affected account manually

1. Use `http://127.0.0.1:5500` consistently. Log out of the current dashboard,
   open `auth.html`, and hard-refresh with Ctrl+Shift+R so the repaired script loads.
2. Check `Api.BASE` in the console. For the intended default local service it must
   be `http://127.0.0.1:5000`. A deliberate API override must point to the backend
   containing the intended account. Sign in again after changing backend origins.
3. Sign in with the affected account, then run this privacy-safe diagnostic:

   ```javascript
   (async () => {
     const p = await Api.get('/profile');
     console.table({backend: Api.BASE, user_id: p?.user?.user_id, role: p?.user?.role});
   })();
   ```

4. If `/profile` says `reporter`, the user dashboard is the authorized destination.
   To participate as a volunteer, log out, choose Register -> Volunteer and use a
   distinct email for a new account. Converting the existing account instead
   requires explicit authorization and a reviewed update of both the User role
   and Volunteer profile; no role-change endpoint or automatic conversion was added.
5. If `/profile` says `volunteer`, confirm `volunteer-dashboard.html`, Volunteer
   labels and a successful `/volunteer/tasks` response. Empty tasks are legitimate
   for an account with no assignments; assignments belong to the accepting account.
   Log out and sign in again to verify normal navigation.
6. Repeat login/logout with authorized accounts for each mapping:
   reporter -> user-dashboard.html; volunteer -> volunteer-dashboard.html;
   ngo -> ngo-dashboard.html; admin -> admin-dashboard.html. Admin registration
   still requires the configured secret; never bypass the server check.

If the same backend's profile returns volunteer but a fresh login still lands on
the citizen page, capture only backend origin, numeric user ID, role and final
page URL for follow-up. Do not share passwords, JWTs or full personal responses.

## Findings and evidence

- The supplied browser URL was `http://127.0.0.1:5500/user-dashboard.html`.
  Its role labels are citizen labels (`frontend/user-dashboard.html:45,220`).
  The volunteer HTML labels were already Volunteer (`frontend/volunteer-dashboard.html:112,267`).
  This confirms the wrong *page* for the observed label, not a database role change.
- Login and profile derive the role from the same database User; JWT identity is
  the string user ID, with no authoritative role claim. Injecting `role=admin`
  in login input or a signed token's extra claims does not grant admin access.
- The exact cause of this user's empty tasks remains **unverified**: the active
  browser's `/profile`, API origin and task response were not supplied. No real
  account was logged into or changed during this repair.
- Reproduced frontend weaknesses: guards trusted cached roles; assignments waited
  behind GPS and map initialization; failed task responses had no useful error.
  Local HTML previously defaulted to the hosted backend. These are repaired.
- `GET /volunteer/tasks` filters by the authenticated volunteer ID, with no
  distance/status exclusion. Pending SOS leaves `/help-requests` after acceptance.
  The 50 km frontend acceptance condition and priority/type/search filters remain;
  distance does not hide assigned tasks. Incident reports remain nonassignable.
- Reproduced security defects: public SOS/contact/volunteer-location disclosure,
  unrestricted cross-NGO inventory/allocation, NGO progress updates on another
  volunteer's task, unrestricted authenticated alert-response access, and malformed
  profile identities. Targeted memory-only regression tests now pass.
- Duplicate preparedness routes in `alerts.py` were registered before the stricter
  `preparedness.py` routes. Removing those duplicates activates the existing
  ownership, role and repeat-response checks without changing the API paths.

## Permission matrix and actual test coverage

R=reporter, V=volunteer, N=ngo, A=admin. Protected routes reject anonymous requests
with 401 and wrong roles with 403. Invalid token format/signature remains the
existing 422 API contract; expired/missing/deleted/malformed identities return 401.
Owned-resource misses use 404; duplicate assignments/allocations/transitions use 409.

The protected matrix test exercises each listed method against anonymous + all
four roles. A PASS for a gate means denied callers are rejected and authorized
callers reach validation or the handler; it does not mean every business operation
or external service succeeded. Valid acceptance/proof/ownership workflows have
separate tests. Exceptions are called out explicitly below.

| Method and endpoint | Permission / projection | Actual checks |
|---|---|---|
| POST `/register` | Public; R/V/N selectable; A requires configured secret | PASS: all roles, invalid role, disabled admin registration |
| POST `/login` | Public; DB role, password checked | PASS: all four roles; client role ignored |
| GET `/profile` | R/V/N/A, own DB identity | PASS: gate, roles, invalid/expired/deleted identities |
| POST `/seed-demo-users` | A **and DEBUG**; automatic seeding separately opt-in | PASS: role gate; disabled-debug returns 403 |
| POST `/report-disaster` | R/V/N/A; author always JWT identity | PASS: role gate; existing cross-role reporting preserved |
| GET `/reports` | R own only; V/N previews; A full text | PASS: gate, reporter ownership, coordinator redaction |
| GET `/report/<id>` | R own only; V/N preview; A full; no private image paths | PASS: gate, foreign reporter 403, missing record 404 |
| POST `/help-request` | R only; owner is JWT identity | PASS: gate |
| GET `/help-requests` | R own; V/N pending previews; A all | PASS: gates, redaction, cross-account ownership |
| GET `/help-request/<id>` | R own; V pending preview or own assignment; N preview; A full | PASS: reporter denial, V preview then assigned private access |
| PUT `/help-request/status` | V own active task; A permitted progress/duplicate handling | PASS: role gate, ownership, transition/rollback tests; Completed denied here |
| GET `/volunteer/tasks` | V own tasks, including all progress stages | PASS: gate, ownership, acceptance/lifecycle regression |
| PUT `/volunteer/accept-task` | V available, eligible unassigned Pending SOS | PASS: gate, success, duplicate/conflict, rollback |
| PUT `/volunteer/update-status` | V own availability; busy-task guard | PASS: gate + lifecycle regression |
| PUT `/volunteer/update-location` | V own location | PASS: role gate |
| POST `/volunteer/upload-proof/<task_id>` | Assigned V, active task only | PASS: gate, ownership, safe enum, duplicate, rollback |
| GET `/volunteer/tasks/<task_id>/proof` | Assigned V or A; private no-store image | PASS: gate, ownership, path restriction, image viewing |
| GET `/ngo/dashboard` | N; own inventory counts, redacted coordination | PASS: role gate |
| GET `/ngo/resources` | N own `added_by` | PASS: gate, cross-NGO isolation |
| POST `/ngo/resources` | N; `added_by` from JWT | PASS: gate, creator impersonation attempt |
| GET `/ngo/requests` | N; redacted coordination records | PASS: role gate |
| PUT `/ngo/allocate` | N own resource, active SOS; conditional atomic claim | PASS: gate, own success, foreign 404, duplicate 409 |
| GET `/ngo/locations` | Public organization directory; no user contact fields | PASS: public/all-role access |
| GET `/admin/dashboard` | A | PASS: role gate |
| GET `/admin/analytics` | A | PASS: gates, successful SQLite query, record counts and ISO daily groups |
| GET `/admin/reports` | A | PASS: role gate |
| GET `/admin/requests` | A | PASS: role gate |
| GET `/admin/volunteers` | A | PASS: role gate |
| GET `/admin/users` | A | PASS: gate; forged role claim denied |
| GET `/admin/pending-verifications` | A | PASS: gate + lifecycle queue |
| PUT `/admin/verify-task/<id>` | A; valid pending proof required | PASS: gate, approve/reject, duplicate, rollback |
| PUT `/admin/report/<id>/override` | A | PASS: role gate |
| POST `/contact` | Public submission; no private record retrieval | PASS: public/all-role validation |
| GET `/admin/contact-messages` | A | PASS: role gate |
| PUT `/admin/contact-messages/<id>/read` | A | PASS: role gate |
| DELETE `/admin/contact-messages/<id>` | A | PASS: role gate |
| GET `/alerts` | Public, existing active/demo filtering | PASS: public matrix + provenance tests |
| GET `/weather/live` | Public | Gate open; **500 without key**, external weather not exercised |
| POST `/alerts` | A | PASS: role gate |
| POST `/alerts/fetch` | A | PASS: denials; **500 without key**, no external request made |
| PUT `/alerts/<id>/notify` | A; demo alerts cannot notify | PASS: role gate |
| GET `/alerts/<id>/responses` | A | PASS: gate; non-admin denied before private ping reads |
| GET `/preparedness/my-pings` | V/N own | PASS: role gate; dedicated owner-filtered handler |
| PUT `/preparedness/ping/<id>` | V/N own Sent ping | PASS: role gate; dedicated ownership/duplicate checks |
| GET `/preparedness/summary` | A | PASS: role gate |
| GET `/map/data` | Public aggregates; R own incidents; V/N redacted; A full | PASS: public/all-role matrix, private-field and location checks |
| GET `/map/risk-zones` | Public warning provenance | PASS: public matrix + provenance tests |
| GET `/public/stats`, `/health` | Public aggregates/health | PASS: public/all-role matrix |
| GET `/api/flood/events/kerala-discovery-check/{metadata,summary}` | Public approved specialist event allowlist | PASS: existing bounded proxy suite |
| GET `/api/flood/events/kerala-discovery-check/layers/{candidate,buildings,roads,bridges}` | Public bounded/paginated event layers | PASS: existing proxy + frontend pagination suite |

Swagger UI/specification and static frontend assets are public infrastructure;
they do not grant access to the APIs. Unknown flood events/resources remain 404.

## Privacy and session policy

No model currently records incident-publication approval. Anonymous `/map/data`
therefore returns counts, not SOS, report or volunteer records. This does not
invent approval from an incident status. Public warnings and the existing NGO
organization directory remain available.

SOS exact coordinates/contact/free text are restricted to the requester, assigned
volunteer and admin. Volunteer/NGO previews omit names, contacts, descriptions,
user IDs, private uploads and assigned-person names; coordinates use a 0.01-degree
grid and are explicitly labelled approximate. Report previews similarly omit
author identity/free text/uploads. Reporters' map incidents are owner-filtered.
Other authenticated users' volunteer markers are anonymous and approximate.
This is limited disclosure, not a claim of irreversible anonymization.

Dashboard guards await `/profile` from the configured API, replace cached identity
and labels, and redirect using its DB role. A late profile response cannot overwrite
a newly switched account. Logout clears all three credential/identity keys; there
is no sessionStorage authentication in the existing application. Missing replacement
tokens no longer reuse an old account's token; demo-token shortcuts are rejected.
`resqnet_api_base` remains a configuration override across logout intentionally.

Local pages on localhost/127.0.0.1 default to `http://127.0.0.1:5000`; explicit
overrides win. Hosted pages retain the hosted default. Those two frontend hostnames
and different ports have separate browser storage. Use one origin consistently.

## Exact files changed for this repair

Backend: `backend/access.py`, `backend/app.py`, `backend/config.py`,
`backend/extensions.py`, `backend/routes/auth.py`, `backend/routes/middleware.py`,
`backend/routes/help_requests.py`, `backend/routes/ngo.py`,
`backend/routes/reports.py`, `backend/routes/alerts.py`, `backend/routes/preparedness.py`.

Frontend: `frontend/js/main.js`, `frontend/js/api.js`, `frontend/js/auth.js`,
`frontend/js/user-dashboard.js`, `frontend/js/volunteer-dashboard.js`,
`frontend/js/ngo-dashboard.js`, `frontend/js/admin-dashboard.js`,
`frontend/js/leaflet-map.js`, `frontend/map.html`.

Tests/documentation: `backend/tests/test_rbac.py`,
`backend/tests/test_map_provenance.py`, `frontend/tests/rbac.test.cjs`,
`frontend/tests/rbac.browser.cjs`, `frontend/tests/flood-intelligence.test.cjs`,
`RBAC_AUDIT.md`. The Flood Intelligence test change only adds the compact panel's
missing metrics/date elements to its test adapter; module/pipeline code is unchanged.
Other pre-existing working-tree changes were preserved.

## Verification and exact commands

From PowerShell in the repository:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests
node --test frontend/tests/*.test.cjs
node frontend/tests/rbac.browser.cjs
'api','auth','main','user-dashboard','volunteer-dashboard','ngo-dashboard','admin-dashboard','leaflet-map' | ForEach-Object { node --check "frontend/js/$_.js" }
```

Backend: 50 tests passed. Frontend: 40 tests passed. Changed JavaScript syntax
checks passed. Five headless Chrome checks passed using real local HTML/JS but
simulated accounts/API responses: all four dashboard roles, volunteer assigned
proof-review task display, and wrong-dashboard redirect. External scripts/services
were intercepted; Leaflet availability was not required for assignment loading.
No real-account end-to-end browser acceptance test was performed. First sandboxed
Chrome attempts could not enable the renderer; the isolated test passed outside
the sandbox. No packages were installed.

Known handler failures above are explicitly asserted/documented by the RBAC gate
test, not counted as working business features. External weather/real account/live
Flood Mapper browser calls were not tested. All database tests use memory-only
fixtures and temporary upload directories; no repair script or production writes.

## Manual browser verification

Start backend and frontend in separate PowerShell terminals from this repository:

```powershell
.\.venv\Scripts\python.exe backend/app.py
# Other terminal; serve ONLY frontend, not the repository or uploads:
.\.venv\Scripts\python.exe -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Use `http://127.0.0.1:5500/auth.html`. Check `Api.BASE` is the intended backend;
remove an unintended `resqnet_api_base` override and reload before signing in.
Existing `DATABASE_URL`/dotenv settings still select the database; SQLite's default
is `backend/instance/resqnet.db`, not the similarly named file beside app.py.
Never print JWTs, authorization headers or personal response fields for diagnostics.

Use disposable accounts/data on a separate local test database for submissions:

1. Reporter: login redirects to user dashboard; submit SOS/report, see own progress;
   another reporter cannot read that SOS by ID. Anonymous map contains only totals.
2. Volunteer: login redirects to volunteer dashboard with Volunteer labels; deny
   GPS and confirm assigned tasks still load. Allow GPS to evaluate nearby pending
   requests; accept an eligible SOS once. Progress En Route -> On Site -> upload
   proof; task shows Proof Submitted while request remains On Site awaiting review.
3. NGO: login redirects to NGO dashboard; only that NGO's inventory is visible.
   Allocate its resource; another NGO's resource ID is inaccessible. SOS previews
   remain redacted. NGO task-status/proof-approval requests are rejected.
4. Admin: login redirects to admin dashboard; review proof via authenticated image
   viewer. Reject returns task/request to On Site; approve completes both. Other
   roles cannot approve, and generic status updates cannot complete requests.
5. Logout between accounts. Altering local role fields must not grant access:
   reloading a dashboard restores the `/profile` role and redirects as needed.

## Compatibility, migration and remaining risks

- No schema migration, account reset, data-repair script, production-data update,
  satellite processing or deployment. Existing acceptance and SOS enums unchanged.
- Admin registration now requires an explicitly configured `ADMIN_SECRET_CODE`;
  the previous built-in shared code is no longer accepted implicitly.
- DEBUG and automatic demo seeding now default off. `SEED_DEMO_DATA=True` is an
  explicit disposable-local-data opt-in; this repair never invoked it on real data.
  Existing demo accounts/records are untouched and still require a separately
  authorized credential review before exposing a service publicly.
- Without `JWT_SECRET_KEY`, a random process-local fallback replaces the predictable
  Flask-secret fallback. Set a persistent, strong environment secret for shared or
  multi-worker services. Without it, restarting invalidates existing login tokens.
- Admin Analytics' SQLite date-cast failure is repaired (see the repair above).
  Weather APIs require a valid key and currently return 500 when unconfigured.
- The existing demo generator writes `PreparednessPing.status='Pending'`, whereas
  its model permits Sent/Acknowledged/Unavailable. Existing rows with that value
  caused enum errors in notification reads in the initial audit tests. Authorized
  reads now exclude invalid enum rows, and those rows cannot be updated through
  the ping endpoint (404); valid records retain ownership and duplicate checks.
  Neither existing records nor the seed generator were repaired. Review separately
  before opting into new demo seeding; no data repair was applied automatically.
- Current browser account, hosted/local database equivalence and the earlier real
  assignment remain unverified. Changing API origins requires fresh authentication.
- Public incident publication approval is not implemented; anonymous incident
  records stay hidden rather than adding a schema/approval workflow in this repair.
- Existing broad CORS, absence of login rate limiting, localStorage token exposure
  to XSS, and template escaping elsewhere need separate hardening. Logout removes
  browser credentials but does not revoke a copied JWT before its expiry.
- Serve only `frontend`; do not expose backend/database/upload directories through
  a generic static server. Protected proof routes are authorization-checked, but
  this cannot protect files exposed by an incorrectly configured external server.
- NGO locations are the existing public organization directory, not a new consent
  system. Resource rows with incorrect historical `added_by` ownership may disappear
  from an NGO's view; do not reassign existing rows without review/authorization.

This is scoped RBAC verification, not a claim of complete application security.
