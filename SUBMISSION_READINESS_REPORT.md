# ResQNet pre-submission readiness — 21 October 2026

**Local demonstration: READY FOR LOCAL DEMONSTRATION**, using a fresh local database,
synthetic accounts and the [demo script](SUBMISSION_DEMO.md). A Chrome test now
uses the real frontend pages and a temporary Flask database to submit an SOS,
accept and progress it, upload proof, edit and allocate NGO stock, approve proof,
and show Completed to the citizen. An operator still needs to rehearse the flow
manually on the intended devices.

**Public deployment: NOT READY FOR PUBLIC DEPLOYMENT.** The proposed Render
configuration requires a paid persistent disk; a verified free, durable database
and private image store have not been selected. Production Redis, the final
Netlify API origin/CORS pair, Linux/Gunicorn operation and hosted upstreams also
need verification. No deployment was attempted.

## Completed local behavior

| Area | Verified behavior and limit |
| --- | --- |
| Citizen | Registration/login and own SOS tracking remain role-scoped. A valid SOS can carry one private PNG/JPEG, which its owner or an admin can open through an authenticated route. Status snapshots now show actual update times, awaiting review and rejection. Homepage statistics use aggregate counts; unavailable data stays unavailable. Community reports remain unverified observations. |
| Volunteer | Existing acceptance, En Route/On Site, private proof, resubmission and completed history remain. Availability and saved GPS survive reload. Assigned volunteers cannot view the citizen's incident image through the new owner/admin route. |
| NGO | Owners can edit the quantity/location of an unallocated resource, reload it and allocate it to a Pending, Accepted, En Route or On Site SOS. Cross-owner or post-allocation edits are rejected; the whole-resource allocation model remains. Readiness persists through the NGO-authorized route. |
| Admin | Dashboard now connects user and volunteer lists, paginated NGO inventory/allocations, unassigned Duplicate recovery and report-type correction. Proof review/approval is still required for rescue completion. Analytics and in-app notification results remain scoped to actual persisted records. |
| Map and flood | Existing Leaflet map, OSM tiles/attribution, location selection, filters and historical overlays remain. Address search requires Enter/Search and passes through a bounded, rate-limited backend geocoder; GPS coordinates remain usable if lookup fails. Flood Intelligence is separate from live SOS and remains scientifically unvalidated. |

## Files changed in this implementation run

Backend: `backend/.env.example`, `backend/access.py`, `backend/app.py`,
`backend/private_uploads.py`, `backend/rate_limits.py`,
`backend/sos_lifecycle.py`,
`backend/routes/admin.py`, `backend/routes/geocode.py` (new),
`backend/routes/help_requests.py`, `backend/routes/ngo.py`,
`backend/routes/reports.py`, `backend/routes/volunteers.py`, and
`backend/tests/test_input_validation.py`.

Frontend: `frontend/admin-dashboard.html`, `frontend/auth.html`,
`frontend/css/styles.css`, `frontend/help-request.html`, `frontend/index.html`,
`frontend/map.html`, `frontend/ngo-dashboard.html`,
`frontend/report-disaster.html`, `frontend/user-dashboard.html`,
`frontend/js/admin-dashboard.js`, `frontend/js/api.js`,
`frontend/js/leaflet-map.js`, `frontend/js/ngo-dashboard.js`,
`frontend/js/report.js`, `frontend/js/user-dashboard.js`,
`frontend/tests/auth-flow.browser.cjs`, `frontend/tests/detect-location.browser.cjs`,
`frontend/tests/detect-location.test.cjs`,
`frontend/tests/geocode-policy.test.cjs` (new),
`frontend/tests/private-images.test.cjs` (new),
`frontend/tests/rbac.browser.cjs`,
`frontend/tests/scientific-claims.test.cjs`, and
`frontend/tests/submission-controls.test.cjs` (new).

Configuration/docs: `netlify.toml`, `README.md`, `SUBMISSION_DEMO.md` (new),
and this report. The worktree also contains earlier uncommitted P0/P1 and flood
integration changes; this list describes this implementation run, not every
file currently shown by `git status`.

## Verification

| Check | Result |
| --- | --- |
| Full backend `unittest` discovery | **127 passed**, 0 failed; in-memory/temporary records only. Includes SOS lifecycle, cross-role access, NGO ownership, admin aggregates, duplicate recovery, image privacy, malformed-image rejection and geocoder limits. |
| Full frontend Node suite | **83 passed**, 0 failed; includes actual HTML/external-script contracts. |
| Python AST / JavaScript syntax | **49 Python files parsed**, all frontend JavaScript syntax checks passed. |
| Chrome auth and rescue smoke | **PASS**: real auth/SOS/volunteer/NGO/admin/citizen pages with a temporary Flask API. A citizen submitted a valid SOS; a volunteer accepted, progressed and uploaded proof; an NGO created, edited and allocated inventory to the active SOS; an admin viewed the protected proof and approved; citizen re-login showed Completed. Separate warm-cache volunteer role check also passed. |
| Chrome four-role dashboard smoke | **PASS**: simulated API accounts, guards, preparedness failure/success/reload, and phone (390px), tablet (768px), desktop (1280px) dashboard width/navigation checks. A newly found narrow-screen overflow was fixed with min-width constraints. |
| Chrome GPS/map smoke | **PASS**: simulated provider/API responses, location denial/failure, linked locations, search/filter/pan, NGO marker exclusion and flood warnings. |
| Flood real-data HTTP and Chrome map smoke | **PASS** outside the sandbox with read-only access to the existing local event; temporary services stopped afterward. |
| `git diff --check` | **PASS** after the final changes. |

Temporary browser accounts do not constitute a real-device field test. The
complete rescue flow was also tested at the Flask API level with synthetic
reporter, volunteer, NGO and admin records. A malformed proof PNG found during
browser testing exposed an uncaught Pillow `SyntaxError`; proof and incident
upload handlers now reject it cleanly with no task/request write. No live weather,
SMS, email or push
delivery was verified or claimed.

## Historical Flood Intelligence check

The existing `kerala-discovery-check` event reports Sentinel-1 observations on
**13 and 25 August 2024**, candidate area **0.7111 km²**, **274** potentially
exposed buildings, **3,125.96 m** of road overlap and **16** bridges. The map
caps the candidate layer at **2,000 of 2,146** polygons and marks it partial.
Level 6/7 validation remains **NOT_READY**. Buildings are potential exposure;
road connectivity is hypothetical. These are historical experimental outputs,
not confirmed flooding, a current warning or a verified closure. No satellite
processing or source artifacts were changed.

## Remaining defects and deployment gates

- Complete a manual local rehearsal on a phone and desktop with synthetic
  accounts, including real browser geolocation permission, report/SOS image
  access, rejected/resubmitted proof and role switching. Automated browser
  fixtures do not verify real device GPS or third-party availability.
- Choose and test a genuinely free durable database, private evidence storage,
  rate-limit Redis-compatible store and backup/retention procedure before using
  Render free hosting. Its ephemeral filesystem cannot retain SQLite/uploads.
  The existing `render.yaml` is review-only under the free-only constraint.
- Set an app-identifying, contactable `NOMINATIM_USER_AGENT`, then verify public
  OSM/Nominatim quotas, caching and attribution for the intended traffic. Current
  local backend limits upstream lookups to one per second globally; the final
  production configuration needs shared Redis and provider review. See
  [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/)
  and [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/).
- Configure the final frontend API base and exact backend CORS origin together;
  run isolated Linux/Gunicorn and production-secret/Redis smoke checks. Hosted
  weather and historical flood upstreams remain optional until configured and
  reviewed. No official disaster-warning feed is implemented.
- Existing local tests still do not prove every mobile screen, assistive-tech
  interaction, external provider outage or real rescue operation.

## Exact steps before submission

1. Review this worktree and run the isolated checks in [README.md](README.md).
2. Use the fresh local setup in README; keep `SEED_DEMO_DATA=False`, do not copy
   real records, and serve only `frontend/` on port 5500 with Flask on 5000.
3. Perform the full role-by-role [local demonstration](SUBMISSION_DEMO.md),
   recording any actual UI/device failures before presenting it.
4. If showing the optional flood map, start only the existing read-only event
   service using [LOCAL_FLOOD.md](LOCAL_FLOOD.md), keep all uncertainty notices
   visible and stop the service afterward.
5. Resolve the separate free-only deployment gates above before any public
   release. No commit, push or deployment is part of this report.

The original `resqnet1` repository, flood-processing repository and outputs,
and all real user databases were left untouched. No dependencies were installed.
