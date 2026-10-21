# ResQNet feature completeness audit and development plan

Audit date: 20 October 2026. Scope: this `ResQNet` directory only. The original
`resqnet1` repository was not accessed or modified. This audit adds this document
only; it does not repair application code, change existing records, install
packages, run satellite processing, or deploy anything.

## Assessment and evidence standard

The core registration/RBAC, volunteer acceptance, proof review, NGO ownership and
admin analytics contracts have passing isolated regressions. The entire application
is **not complete**: report input can corrupt shared feeds, several notification
controls misrepresent success, availability/location persistence is inconsistent,
and a browser map-centering check fails. The current deployment proposal also
conflicts with the requirement to use free services only.

- **COMPLETE**: the specifically described behavior is implemented and verified by
  a test or audit probe. This does not certify external providers, real rescues,
  every UI interaction, or production deployment.
- **PARTIAL**: implementation exists, but a confirmed gap, reliability issue or
  missing verification prevents an end-to-end completeness claim.
- **MISSING**: the requested capability has no corresponding implementation.
- **BLOCKED**: implemented code needs external configuration, data or infrastructure
  that was not available/verified in this audit.

Read `RBAC_AUDIT.md`, `DEPLOYMENT_READINESS.md`, `README.md`, `SOS_LIFECYCLE.md`,
`LOCAL_FLOOD.md`, and the actual HTML/JavaScript, Flask factory/routes, models,
privacy/storage/configuration helpers and test suites. Earlier browser evidence
in historical documents is not treated as verification of this copy.

The checked runtime directories `backend/instance/` and `backend/uploads/` contain
only `.gitkeep`. All API probes used fresh **in-memory SQLite** and temporary upload
directories, with synthetic accounts. No existing application database was opened.
Frontend probes executed the existing files with simulated API/DOM state. Headless
Chrome tests used temporary profiles; their verification limits appear below.

## Storage and authorization map

| Records / storage | Actual purpose and access |
| --- | --- |
| `backend/models.py:20`, `users` | Hashed password, current role, private contact/profile data, overloaded location/skills fields, availability. JWT identity resolves to this current DB account in `backend/routes/middleware.py`, not a trusted browser role. |
| `backend/models.py:156`, `help_requests` | Citizen SOS, exact location/contact, priority, duplicate flag and rescue status. Owner/admin/assigned volunteer may read private details; other responders receive structured, coarse previews through `backend/access.py`. |
| `backend/models.py:244`, `volunteers` | Separate availability, saved GPS and task counters. These are not consistently reflected in `users` or `/profile`; see G3. |
| `backend/models.py:287`, `relief_tasks` | Volunteer/request assignment, progress, private proof reference/notes, verification and completion. Assigned volunteer uploads; admin reviews. |
| `backend/models.py:86`, `disaster_reports` | Community observations and heuristic severity. No incident-resolution or publication-approval field; never inherently a verified alert. |
| `backend/models.py:343`, `relief_resources` | NGO creator, inventory quantity/location and whole-resource allocation to an SOS. Ownership is enforced by the API. |
| `backend/models.py:433,480`, `weather_alerts`, `preparedness_pings` | Stored advisories and responder acknowledgements. Ping status is `Sent`, `Acknowledged` or `Unavailable`; it is distinct from responder availability. |
| `backend/models.py:397`, `contact_messages` | Public contact submission; admin-only listing, read and delete actions. No email delivery is implemented. |
| `backend/private_uploads.py`, `backend/sos_lifecycle.py` | PNG/JPEG validation, generated filenames and private filesystem storage. Only task proofs have an authenticated viewing route. SOS/report images are stored but have no equivalent viewing integration. |
| `backend/config.py`, `backend/database.py` | Local SQLite defaults to `backend/instance/resqnet.db`. Empty schema initialization is supported; incompatible existing schemas fail without migration. No migration framework is present. |

## Detailed feature checklist

Each row is a separate checklist item. COMPLETE rows describe their tested scope;
unverified parts are explicitly separated rather than inferred from a button.

### 1. Citizen

| Feature | Classification | Files, API/storage and evidence |
| --- | --- | --- |
| Registration and login | COMPLETE | `frontend/auth.html`, `frontend/js/auth.js`; `POST /register`, `POST /login`, `backend/routes/auth.py:37,103`; `users`. `backend/tests/test_rbac.py` verifies all roles, invalid role and current-role login/profile behavior; real volunteer registration browser check also exercises shared auth code. |
| Citizen redirect, guard, logout/account switching | COMPLETE | `frontend/js/main.js:15,127`, `frontend/js/auth.js`, `frontend/user-dashboard.html`, `frontend/js/user-dashboard.js`; `/profile` refreshes cached role. Node auth/RBAC tests and Chrome RBAC check verify the four dashboards and wrong-dashboard redirect. Logout removes token/user/role; no server-side token revocation is claimed. |
| Read own profile | COMPLETE | `GET /profile`, `backend/routes/auth.py:128`, `User.to_dict`; `populateUserInfo()` in `frontend/js/user-dashboard.js:14`. Auth/RBAC tests verify DB-authoritative role/profile. Displayed membership date is still hardcoded in `frontend/user-dashboard.html:235` (G9). |
| SOS creation and priority | PARTIAL | `frontend/help-request.html`, `frontend/js/help-request.js:137`, `POST /help-request`, `backend/routes/help_requests.py:41`, `help_requests`. Reporter-only creation and rule-based priority exist; audit probe created an SOS, but invalid coordinates and invalid images were accepted (G2). Existing rate-limit tests exercise rejection/throttling, not a complete valid form-to-completion browser journey. |
| GPS, address lookup, map/manual location | COMPLETE | `frontend/js/help-request.js`, `frontend/js/report.js`, `frontend/js/leaflet-map.js:379` onward; `detectFormLocation`, correct Nominatim `/reverse?format=jsonv2&lat=...&lon=...`, coordinates set before address lookup. Node tests and six Chrome form scenarios verify physical button clicks, permission denial, lookup failure, retained coordinates/manual entry and no navigation/submission. Real device GPS/provider availability remains unverified. |
| SOS image upload | PARTIAL | Single `image` multipart field; `backend/routes/help_requests.py:89`, `backend/private_uploads.py`; private `uploads/requests/`. Invalid-image result is silently treated as no upload; no owner/admin image viewer (G2/G8). Proof-image viewer is a separate working feature. |
| Own SOS list, rescue status and tracking | COMPLETE | `GET /help-requests`, `GET /help-request/<id>`; `backend/access.py`; `frontend/js/user-dashboard.js:57,79,126`, 15-second visible-page polling. Lifecycle/RBAC tests verify own details, synchronized progress, awaiting review, rejection and approved completion. The timeline is current snapshots, not a stored transition history. |
| Citizen notifications | PARTIAL | `frontend/js/user-dashboard.js:137` builds five current request snapshots, ordered/timestamped by creation. Inline notification controls in `frontend/user-dashboard.html` clear UI state only. No notification record/read-state persistence; awaiting-proof display uses raw status here instead of `progress_status` (G7). This is in-page awareness, not verified external delivery. |
| Disaster reporting | PARTIAL | `frontend/report-disaster.html`, `frontend/js/report.js:132`, `POST /report-disaster`, `GET /reports`, `GET /report/<id>`, `disaster_reports`. Ownership/redaction and valid upload tests pass; unvalidated disaster type commits a poison enum row (G1). UI accepts up to five `images` while backend saves only the first (G8). |
| SOS/report analysis buttons and trust labels | PARTIAL | `frontend/js/user-dashboard.js:73,198,212`, `frontend/js/report.js:174`; SOS IDs are passed to a report-only lookup, so the SOS “AI Result” action can do nothing or select an unrelated same-numbered report. Copied report type is presented as AI agreement/verification; no CNN is called (G5/G9). |

### 2. Volunteer

| Feature | Classification | Files, API/storage and evidence |
| --- | --- | --- |
| Registration, login and volunteer-only dashboard | COMPLETE | Same auth routes plus creation of `volunteers` row; `frontend/js/auth.js:132`, `frontend/js/volunteer-dashboard.js:557`. `auth-flow.browser.cjs --warm-cache` passes against real temporary Flask auth: submitted/stored/profile role volunteer, correct redirect/dashboard and logout. No existing role is promoted. |
| Profile/contact and completed counter | COMPLETE | `populateVolunteerInfo`, `updateStats`, `frontend/js/volunteer-dashboard.js:39,59`; profile contact from authenticated `/profile`, completion from own tasks. RBAC browser check verifies volunteer identity and assigned proof task. Availability/GPS fields are separately incomplete below. |
| Registration availability, readiness changes and reload | PARTIAL | `users.availability` vs `volunteers.availability_status`; `backend/routes/auth.py:77,87`, `PUT /volunteer/update-status` at `backend/routes/volunteers.py:106`; dashboard select at `frontend/volunteer-dashboard.html:194`. Registration with unavailable stores an available Volunteer; initial UI is not hydrated from the operational record (G3). Active-task backend guard correctly rejects clearing busy state. |
| Nearby SOS discovery, sorting and location persistence | PARTIAL | `GET /help-requests`, `/reports`; `frontend/js/volunteer-dashboard.js:293,354,418`; pending requests sorted by priority/distance; accept UI requires <=50 km. Unknown location gets sentinel distance 9999 rather than an honest unknown label. GPS is saved to Volunteer but fallback reads User `/profile` coordinates (G3); unauthorized pending previews remain coarse by design. |
| SOS acceptance and duplicate protection | COMPLETE | `PUT /volunteer/accept-task` with integer `request_id`; `backend/routes/volunteers.py:53`, `frontend/js/volunteer-dashboard.js:148`; conditional request/volunteer updates and one active task. Seven backend acceptance tests plus frontend acceptance tests cover authorization, replay/conflict, rollback and excluding incident cards. |
| Own assignments independent of GPS | COMPLETE | `GET /volunteer/tasks`, `backend/routes/volunteers.py:35`, `loadMyTasks()`/initialization at `frontend/js/volunteer-dashboard.js:338,557`. Own tasks load before waiting for GPS and are not location filtered; frontend RBAC/acceptance tests verify response parsing. |
| Rescue progress and private proof upload | COMPLETE | `PUT /help-request/status`, `POST /volunteer/upload-proof/<task_id>`; `backend/sos_lifecycle.py`, `frontend/js/volunteer-dashboard.js:198,249,261`. Seventeen lifecycle tests cover ordering, enum safety, assigned-user checks, rejection/resubmission, conflicts and transaction/file rollback. |
| Completed rescue history | COMPLETE | `GET /volunteer/tasks` includes completed tasks, `renderMyTasks()` renders the list without filtering them out; completed counter filters `Completed`. Lifecycle tests verify saved completion. No distinct history page is promised or required. |
| Preparedness acknowledgement | PARTIAL | API ownership/replay checks pass in `test_rbac.py`; `frontend/js/volunteer-dashboard.js:574,606` and later inline script `frontend/volunteer-dashboard.html:332,352` define conflicting `respondToPing` signatures. Actual combined-file probe submits the ping ID as status and then displays success after HTTP 400 (G4). |
| Notify nearest NGO | PARTIAL | Visible on distant/unknown-location SOS cards in `frontend/js/volunteer-dashboard.js:140`; `notifyNearestNGO()` at line 192 only shows success. Audit execution made zero network calls. No corresponding SOS notification route/storage exists (G4). |

### 3. NGO

| Feature | Classification | Files, API/storage and evidence |
| --- | --- | --- |
| Registration/login and NGO guard | COMPLETE | `frontend/auth.html`, `frontend/js/auth.js`, `backend/routes/auth.py`; `users` role plus organization metadata in location/skills. Flask all-role registration/login/profile tests and simulated-API Chrome NGO guard pass. |
| Organization profile/location | PARTIAL | `frontend/js/ngo-dashboard.js:23`, `backend/routes/auth.py:79`; organization name occupies `User.location`, area/type are JSON in skills. Form registration number has no persistence contract. No canonical organization coordinates; public `/ngo/locations` substitutes Hyderabad for ordinary organization names (G6). |
| Resource creation and own inventory | COMPLETE | `GET/POST /ngo/resources`, `backend/routes/ngo.py:78,100`, `frontend/js/ngo-dashboard.js:255,308`; `relief_resources.added_by` comes from JWT. RBAC tests cover creation, ignored creator impersonation and separate inventories. Malformed quantity/type validation remains incomplete (G2). |
| Update existing inventory quantity/location | MISSING | `backend/routes/ngo.py` exposes list/create/allocate only; `frontend/js/ngo-dashboard.js:265` renders cards without edit persistence. No resource-update endpoint. This is an explicit requested audit capability, not a claim that existing allocation is broken. |
| Resource availability and ownership | COMPLETE | Unallocated resources populate allocation selection; allocation is owner checked and uses a conditional claim in `PUT /ngo/allocate`, `backend/routes/ngo.py:235`. `test_rbac.py:40,54` verifies cross-owner denial and duplicate allocation rejection. Availability here means the whole resource row is allocated/unallocated, not remaining stock accounting. |
| SOS visibility, allocation and allocation history | COMPLETE | `GET /ngo/requests`, `GET /ngo/dashboard`, `PUT /ngo/allocate`; `frontend/js/ngo-dashboard.js:107,354,375`; active SOS preview is intentionally redacted, owned resource allocations survive inventory reload and populate history. Backend ownership tests verify the contract; full NGO browser actions were not rerun. |
| NGO readiness | PARTIAL | `frontend/ngo-dashboard.html:612`, `frontend/js/ngo-dashboard.js:521` calls volunteer-only `PUT /volunteer/update-status`; actual NGO token gets 403. Admin summary reads unchanged `users.availability`, usually its default available (G6). |
| NGO preparedness alerts/response | PARTIAL | `GET /preparedness/my-pings`, `PUT /preparedness/ping/<id>`; `frontend/js/ngo-dashboard.js:456,488`, `preparedness_pings`. Backend role/ownership and duplicate checks pass. Acknowledgement does not change resource inventory or NGO availability; live UI delivery needs an integrated test and explicit wording. |
| Resource visibility beyond owning NGO | PARTIAL | Owner-only list is correct. No cross-NGO public catalogue is promised; do not expose one. The requested admin resource overview is missing below, so coordination visibility is incomplete. |

### 4. Admin

| Feature | Classification | Files, API/storage and evidence |
| --- | --- | --- |
| Authentication and privileged enrollment | COMPLETE | Admin enrollment requires private configured `ADMIN_SECRET_CODE`; DB current role gates `/admin/*`. `backend/routes/auth.py`, `backend/routes/middleware.py`, `frontend/js/admin-dashboard.js:550` guard. RBAC/deployment-security tests reject wrong roles, forged claims, expired/deleted identities and production demo accounts. |
| User management | PARTIAL | Admin-only `GET /admin/users`, `GET /admin/volunteers`, `backend/routes/admin.py:159,167` provide DB lists. Dashboard has no calls/navigation for these lists and no role/disable/change-user API. Minimal missing connection is a read-only admin view; do not invent role promotion or account deletion requirements. |
| SOS monitoring and allowed status changes | PARTIAL | `GET /admin/dashboard`, `/admin/requests`, `PUT /help-request/status`; `frontend/js/admin-dashboard.js:246` renders a read-only request table. Backend status policy and counts are tested: arbitrary completion is denied and admin can reverse an unassigned duplicate classification through the API. There is no dashboard call to this status route, so duplicate recovery is not available through the normal admin UI (G9). Proof approval remains connected separately. |
| Volunteer activity | PARTIAL | Dashboard has counts, verification rows and preparedness summary; `/admin/volunteers` has records but no dashboard integration/task history view. `backend/routes/admin.py:33,159`, `frontend/js/admin-dashboard.js:55,731`; count correctness tested, detailed activity connection absent. |
| Pending proof review, private image, approval/rejection | COMPLETE | `GET /admin/pending-verifications`, `PUT /admin/verify-task/<id>`, authenticated `GET /volunteer/tasks/<id>/proof`; `backend/routes/admin.py:183,191`, `frontend/js/admin-dashboard.js:400,442,478`. Lifecycle/frontend tests cover image authorization, blob viewing, duplicate actions, approval, rejection and rollback. |
| NGO resource overview | MISSING | No admin resource-list route or dashboard integration. Current `GET /ngo/resources` deliberately requires NGO and returns only its owner inventory. An admin must not impersonate an NGO to inspect allocations. |
| Actual counts and charts | COMPLETE | `GET /admin/dashboard`, `/admin/analytics`; `backend/routes/admin.py:33,67`, `frontend/js/admin-dashboard.js` Chart.js renderers. Four SQLite analytics regressions compare aggregates against independently computed fixture counts, including UTC dates and Duplicate; frontend analytics tests cover chart data and failed refresh preservation. This verifies temporary records, not a live database. |
| Disaster report review/override | PARTIAL | `GET /admin/reports`, `PUT /admin/report/<id>/override`; `backend/routes/admin.py:118,229`, dashboard reports section. Invalid override commits an unreadable enum (G1). No verified incident-resolution workflow; changing type is not scientific verification. |
| Contact inbox and preparedness coordination | PARTIAL | `POST /contact`, admin list/read/delete in `backend/routes/contact.py`; homepage contact form and `frontend/js/admin-dashboard.js:319` are connected. Advisory creation/pings have auth tests, but typed “Notify All volunteers/NGOs” controls call the same untyped endpoint and can report success on API errors (G4). Inbox lacks focused full CRUD regression coverage. |

### 5. Maps and disaster intelligence

| Feature | Classification | Files, API/storage and evidence |
| --- | --- | --- |
| Existing Leaflet map, OSM attribution, filters and legend | COMPLETE | `frontend/map.html`, `frontend/js/leaflet-map.js:25`, `frontend/css/styles.css`; existing map/layers reused, OSM URL and attribution retained. Node map tests and Chrome overview/demo-hide check pass. No new map library or pipeline is needed. Provider-policy issues are separately recorded below. |
| Role-aware incident and volunteer markers | COMPLETE | `GET /map/data`, `backend/app.py:444`, `backend/access.py`; anonymous aggregate-only, citizen own records, responder coarse previews, authorized exact details. Map provenance/RBAC tests verify these boundaries and outside-Hyderabad records. Popups use each record's coordinates/status/source. |
| Linked incident centering and later viewport preservation | PARTIAL | `frontend/map.html:256,293,403`, `frontend/js/leaflet-map.js:265`; one-time target flag and user-chosen viewport guard exist, Node tests pass. Existing Chrome script fails at `frontend/tests/detect-location.browser.cjs:152` on linked-report latitude, twice. The later search/refresh assertions therefore did not run; browser correctness is not certified (G10). |
| Active/resolved SOS lifecycle on map | COMPLETE | `/map/data` selects Pending/Accepted/En Route/On Site; approved Completed leaves active feed but remains in citizen/task history. Source and lifecycle tests cover the stored states. Disaster reports have no analogous resolved status and remain recent observations, not ongoing confirmed emergencies. |
| NGO marker location accuracy | PARTIAL | `GET /ngo/locations`, `backend/routes/ngo.py:195`; map addNgoDepotMarkers uses public results. Unknown coordinates currently become Hyderabad (reproduced; G6). Also use organization identity rather than assuming account holder's name is the organization. |
| Weather display | BLOCKED | `GET /weather/live`, `backend/routes/alerts.py:103`, dashboard/homepage proxy calls. Missing `OPENWEATHER_API_KEY` returns unavailable/503; key stays backend-only. Error/redaction tests pass, but no configured live provider response was verified. Optional for local SOS completion. |
| Disaster advisories and risk zones | PARTIAL | `/alerts`, admin `POST /alerts`, `/alerts/fetch`, `/map/risk-zones`; `backend/map_provenance.py`, `backend/routes/alerts.py`, `backend/routes/map_risk.py`. Demo fingerprints excluded and descriptions marked unverified; tests pass. Thresholds/current-weather text and report-density heuristic are not official forecasts. Live provider-backed branch is blocked without weather configuration. |
| Official disaster warning feed | MISSING | No official-agency feed client, verification provenance or integration appears in routes/dependencies. Existing community/OWM heuristics must not be relabeled official. Adding such a feed is not a prerequisite for the existing local SOS workflow. |
| Optional historical Flood Intelligence code | COMPLETE | `frontend/js/flood-intelligence.js`, `frontend/map.html:66,225`, `backend/routes/flood.py`, `LOCAL_FLOOD.md`; allowlisted `/api/flood/events/kerala-discovery-check/metadata`, `/summary`, `/layers/{candidate,buildings,roads,bridges}`. Backend/frontend tests verify pagination, byte/feature limits, upstream failures, projection, toggles, summary and scientific notices. |
| Actual flood event display | BLOCKED | Needs configured/reachable `FLOOD_API_BASE_URL` and existing processed event. Neither real upstream event results nor generated satellite datasets were loaded in this audit. Candidates, potential exposure and hypothetical connectivity must retain their caveats; no real-time/confirmed-flood claim is justified. |
| Free OSM/Nominatim service compliance | PARTIAL | `frontend/js/leaflet-map.js:210` implements search-as-you-type at 600 ms; public Nominatim forbids client autocomplete and requires aggregate rate control/identification. `netlify.toml` sets `Referrer-Policy=no-referrer`, conflicting with OSM tile identification. See policy evidence and P1-8; existing reverse endpoint correctness does not establish policy compliance. |

### 6. Shared behavior, security and configuration

| Feature | Classification | Files and evidence |
| --- | --- | --- |
| Role navigation and local static links | COMPLETE | `frontend/js/main.js`, dashboard guards, `frontend/js/auth.js`; Node/Chrome role tests pass. HTML reference audit across actual pages found zero missing local href/src files and zero missing explicit fragment targets. This does not verify every click handler. |
| API origin selection | COMPLETE | `frontend/js/api.js:7`: explicit window override, then localStorage override, local host -> port 5000, otherwise previous hosted Render default. Node RBAC/security checks cover local behavior. Intended hosted endpoint/CORS pair remains a release configuration gate; Netlify does not substitute static JS environment variables. |
| Responsive layouts and scrolling | PARTIAL | `frontend/css/styles.css:1437` onward, dashboard styles, flood scroll/mobile rules in `frontend/map.html:66–95`. Responsive rules and sidebar toggle exist. No complete mobile/touch/keyboard/overflow review was performed; desktop Chrome checks do not prove mobile usability. |
| Validation and transaction failure handling | PARTIAL | Proof/lifecycle/acceptance conflict and rollback regressions pass. Reports lack enum validation/rollback safety; SOS and volunteer coordinates lack finite/bounds checks; NGO quantity/contact/auth JSON types are not consistently checked (G1/G2). These contracts need targeted tests, not a broad architecture rewrite. |
| Loading/error states and duplicate actions | PARTIAL | Auth, SOS/report submission, acceptance, proof upload and review disable/re-enable controls and show failures. Some dashboard list reads silently preserve stale/empty content, readiness updates style before success, and notification handlers fabricate success (G4/G9). |
| Core private-data/RBAC boundaries | COMPLETE | `backend/routes/middleware.py`, `backend/access.py`, proof route, owner-scoped NGO routes, private response cache headers. Cross-role/RBAC, proof and security regressions pass. No anonymous SOS contacts/exact private incident records/private proof URLs are intentionally exposed. This scoped result is not a full penetration-test claim. |
| Input display and session hardening | PARTIAL | Existing escaping helpers/tests protect inspected user-controlled text. Tokens remain in localStorage; logout does not revoke issued JWTs (24-hour expiry). Pending validation issues and third-party geocoder HTML rendering need review before stronger security claims. No new auth architecture is proposed for the local completion plan. |
| Persistent secrets, production CORS, rate limiting | COMPLETE | `backend/security.py`, `backend/config.py`, `backend/rate_limits.py`, `backend/tests/test_production_backend.py`, `test_deployment_security.py` verify fail-fast settings, exact origins, proxy/rate controls and fail-closed store errors. Real hosted proxy/Redis operation is separately unverified. |
| Database initialization/local private storage | COMPLETE | `backend/database.py`, private upload/proof helpers, `.gitignore`; tests create fresh schemas, preserve data across factories and refuse incompatible schema without changes. No existing records migrated in this audit. |
| Free-only durable hosting, hosted integration and Linux runtime | BLOCKED | Existing `render.yaml` explicitly proposes paid starter + persistent disk, SQLite/private filesystem uploads, and external Redis. Windows cannot verify Gunicorn/Linux. A free durable database/private image-storage design and compatible configuration must be validated before deployment; passing local tests does not solve this. |
| Homepage operational statistics/marketing accuracy | PARTIAL | `frontend/index.html:482,766`, `frontend/auth.html:614`, `frontend/user-dashboard.html:235`: static CNN/98.4%, response-time/people-helped claims and fixed join date are not DB evidence. Homepage counts use private arrays instead of aggregate fields; anonymous active count can show 0 when total_active is 7 (G5/G7/G9). |

## Confirmed gaps and reproduction evidence

These probes did not change application files. “Stored” below always means the
probe's temporary database, never a real user's record.

| ID | Confirmed failure / exact link | Observation |
| --- | --- | --- |
| G1 | `backend/routes/reports.py:37–82`, `backend/routes/admin.py:229–241`, enum at `backend/models.py:91` | POST a synthetic unknown disaster type: HTTP 500, raw SQL count confirms one committed invalid row; subsequent `/reports`, `/map/data`, `/admin/reports` each return 500. Valid report followed by unknown admin override also returns 500 and commits invalid type. `LookupError` occurs on enum deserialization after commit. SQLite Enum does not reject this write automatically. |
| G2 | `backend/routes/help_requests.py:43–95`, `backend/routes/volunteers.py:133`, `backend/routes/reports.py:71–72`, `backend/routes/ngo.py:125` | Synthetic SOS at latitude/longitude 999 with invalid PNG bytes returned 201 and no image path. Report float conversion is unguarded; volunteer GPS values lack bounds checks. NGO quantity compares raw JSON with zero, which is unsafe for string/null types. Stored invalid coordinates can make distance/markers unreliable. |
| G3 | `backend/routes/auth.py:72–88`, `backend/models.py:59,244`, `backend/routes/volunteers.py:108,133`, `frontend/js/volunteer-dashboard.js:418` | Register unavailable volunteer -> `users.availability=unavailable`, `volunteers.availability_status=available`. Save GPS -> 200 and Volunteer GPS exists, but `/profile.user.location_lat` remains null; browser fallback reads that null User field. No account role mismatch was reproduced. |
| G4 | `frontend/volunteer-dashboard.html:352` shadows `frontend/js/volunteer-dashboard.js:606`; also JS line192 and `frontend/js/admin-dashboard.js:774` | Execute actual external JS then actual inline script: dynamic `(123,'Acknowledged')` action sends `{status:123}`; simulated HTTP 400 still produces success toast. “Notify nearest NGO” produces success with zero requests. Admin typed bulk notification loops same role-agnostic `/alerts/<id>/notify`, ignores unsuccessful bodies and labels totals by selected role. Backend advisory/ping authorization is intact. |
| G5 | `backend/routes/reports.py:66–67`, `backend/ai/severity.py`, `frontend/js/report.js:174`, `frontend/js/user-dashboard.js:198,239`, `frontend/index.html:482–505` | Report type is copied from user input and confidence is null; severity is image-color/type heuristics. UI still labels matching input “Verified”/“AI agrees”, calls it CNN prediction, and homepage displays static 98.4% confidence. No CNN inference pipeline/model dependency is connected. |
| G6 | `backend/routes/ngo.py:195–231`, `frontend/js/ngo-dashboard.js:521`, `backend/routes/preparedness.py:83` | NGO readiness PUT gets 403 from volunteer-only role check. Unknown NGO location returned exactly Hyderabad fallback. Admin readiness counts use unchanged User availability; an advisory acknowledgement is not an availability update. |
| G7 | `frontend/index.html:766`, `backend/app.py:444,506`, `frontend/js/user-dashboard.js:137` | Execute actual homepage loadStats with aggregate-only response `{total_active:7, requests:[]}` -> displayed active incidents 0. Completed is always 0 from an active-only map list; registered-volunteer total is mislabeled deployed. A private-data fix should not be undone to populate counters. Citizen notifications use creation times/raw statuses, not actual update/read state. |
| G8 | `frontend/js/report.js:103,150`, `backend/routes/reports.py:53–57`, `backend/private_uploads.py` | Five-image frontend affordance submits repeated `images` fields; backend accesses only `request.files['images']`, one model image_path. Saved SOS/report images have no authenticated retrieval route/UI. Proof viewing is separately implemented and must stay private. |
| G9 | `frontend/js/user-dashboard.js:73,212`, `frontend/user-dashboard.html:235`, `frontend/auth.html:614`, admin/NGO dashboard scripts | SOS AI Result routes a request ID into report lookup; fixed membership date and operational tickers are placeholders. Admin users/volunteers, report override and generic SOS status endpoints lack dashboard calls; no admin resource overview. API list failures can look like an empty dataset. No missing static file/fragment links were found. |
| G10 | `frontend/tests/detect-location.browser.cjs:152`, `frontend/map.html:403–409` | Chrome test twice fails expected linked-report center latitude 12.9716 within 0.01. Six form scenarios and map overview/demo filtering passed before failure. Exact distinction between application behavior and assertion/animation assumptions remains unconfirmed; do not blindly change map logic or weaken the assertion. |

Duplicate detection is a **rule**, not identity verification:
`backend/ai/duplicate.py` treats same-type requests within 0.5 km/60 minutes as
duplicates, regardless of requester. SOS creation examines Pending/Accepted rows;
admin can restore an unassigned Duplicate to Pending using existing status route.
The rule and the restored `is_duplicate` flag/status consistency need focused
tests before claiming distinct nearby households cannot be suppressed.

## Actual current user journeys

1. **Citizen:** register reporter -> authenticated citizen dashboard -> submit SOS
   with GPS or map selection -> own request polling shows progress -> admin-approved
   completion. A separate disaster observation never creates an assignable SOS.
   Images are stored privately; report/SOS image review and notification details
   are incomplete. Other citizens' precise incident locations remain hidden.
2. **Volunteer:** register volunteer -> verified role redirect -> GPS sets distance
   -> accept eligible Pending SOS within the UI's 50 km threshold -> own task list
   -> En Route -> On Site -> proof -> wait for admin -> approved history or rejected
   resubmission. Existing assignments remain available without GPS. Reload after
   denied GPS can lose the saved location fallback; distant SOS NGO-notify is fake.
3. **NGO:** register -> own dashboard -> create resource -> choose an active,
   redacted SOS -> allocate own unallocated resource -> see allocation history.
   Existing inventory cannot be edited; readiness select fails; public depot GPS
   is not trustworthy when no coordinates were stored.
4. **Admin:** authorized enrollment/login -> actual counts/charts and SOS table ->
   pending verification -> JWT-protected image dialog -> approve/reject -> states
   and counters synchronize. Advisory/ping and contact inbox routes exist. Detailed
   user/volunteer lists and NGO resources are not connected to admin navigation.

## Prioritized implementation plan

Effort is relative: **S** roughly half a day, **M** 1–2 days, **L** 3–5 days of
focused work including tests, assuming the current environment. These are planning
estimates, not delivery promises. All tasks are proposed; none was implemented.

### P0 — broken core workflows / serious data or trust issues

| Task | Likely files | Acceptance tests | Effort |
| --- | --- | --- | --- |
| **P0-1: Prevent report enum corruption** (G1) | `backend/routes/reports.py`, `backend/routes/admin.py`; focused new report-validation tests under `backend/tests/` | Unknown/null/wrong-type disaster types rejected before persistence; invalid override leaves original row unchanged; valid create/override succeed; after every rejection `/reports`, `/map/data`, `/admin/reports` remain 200; DB failure rolls back and cleans a newly written upload. No record reset or automatic legacy rewrite. | S–M |
| **P0-2: Remove false scientific verification claims** (G5) | `frontend/js/report.js`, `frontend/js/user-dashboard.js`, `frontend/index.html`; `backend/routes/reports.py` response semantics if necessary; focused frontend regressions | Current heuristic result explicitly labeled unvalidated/manual observation; copied user type never shown as independent CNN/verified result; absent confidence displays unavailable, not fake measured certainty. Preserve rule-based prioritization and Flood Intelligence caveats; do not add/train a model. | S |
| **P0-3: Make emergency notification results truthful** (G4) | `frontend/volunteer-dashboard.html`, `frontend/js/volunteer-dashboard.js`, `frontend/js/admin-dashboard.js`; existing preparedness/alerts routes only if a contract correction is needed | Test actual HTML+external script execution; one ping handler receives ID+allowed status; 400/401/403/409/503 never show success or hide pending banner; acknowledged ping reloads accurately. Nearest-NGO action must clearly say unavailable until real delivery exists; never pretend success. Bulk notifier truthfully reports actual recipient scope/count and failures. No new messaging service required. | M |

### P1 — essential completion and verified local operation

| Task | Likely files | Acceptance tests | Effort |
| --- | --- | --- | --- |
| **P1-1: Validate SOS/GPS/JSON inputs consistently** (G2) | `backend/routes/help_requests.py`, `backend/routes/volunteers.py`, `backend/routes/auth.py`, `backend/routes/ngo.py`, `backend/routes/contact.py`; relevant tests | Nonfinite/out-of-range coordinates, malformed types/JSON, invalid enums and nonpositive/noninteger quantities return 400 without writes; invalid SOS image is rejected; zero-valued valid coordinates accepted; valid SOS still completes through proof approval. | M |
| **P1-2: Reconcile operational availability and saved location** (G3/G6) | `backend/routes/auth.py` registration/profile projection, `backend/routes/volunteers.py`, `backend/routes/ngo.py`, `frontend/js/volunteer-dashboard.js`, `frontend/js/ngo-dashboard.js`, corresponding HTML | Registration unavailable stays unavailable for acceptance; readiness hydrates correctly after reload; GPS permission denied after prior save uses authorized saved Volunteer GPS; active tasks retain busy guard; NGO's own readiness persists through an NGO-authorized operation and changes admin summary; cross-role changes forbidden. No silent role changes. | M |
| **P1-3: Resolve map browser regression and remove fabricated NGO positions** (G6/G10) | `frontend/map.html`, `frontend/js/leaflet-map.js`, `backend/routes/ngo.py`, `frontend/tests/detect-location.browser.cjs`, `map-display.test.cjs` | First diagnose center/animation/popup behavior with real Leaflet. Linked SOS/report and search stay in intended area after refresh/filter/user pan; assert stable intended behavior without masking failures. Unknown NGO positions produce no fabricated marker; legitimate coordinates outside Hyderabad render correctly; preserve privacy and optional overlays. | M |
| **P1-4: Connect missing admin coordination controls** (G9) | `frontend/admin-dashboard.html`, `frontend/js/admin-dashboard.js`, `backend/routes/admin.py` (minimal resource read projection), existing `/help-request/status` and report-override APIs, focused RBAC/UI tests | Admin can view existing user roles, volunteer activity and NGO resources/allocations from actual records, correct an unassigned duplicate and submit a valid report-type correction. Offer only server-permitted actions; proof approval remains the sole completion path. Nonadmins denied by server; no invented role-edit/account-deletion actions. Existing analytics/proof workflows remain unchanged. | M |
| **P1-5: Complete requested inventory update contract** | `backend/routes/ngo.py`, `frontend/js/ngo-dashboard.js`, `frontend/ngo-dashboard.html`, focused NGO ownership tests | Owner can update an existing unallocated resource's valid quantity/location and see it after reload; other NGO/admin-through-NGO-route denied; allocated resources cannot be silently reassigned or delivery history overwritten. Keep current whole-resource allocation semantics. | M |
| **P1-6: Align incident image handling with current storage/privacy** (G8) | `frontend/js/report.js`, `frontend/report-disaster.html`, `backend/routes/reports.py`, `backend/routes/help_requests.py`, `backend/private_uploads.py`, small admin/citizen viewer integration | Make the current single-image contract explicit rather than silently discard extra files; authorized owner/admin can view supported stored SOS/report image; outsiders/anonymous denied, path traversal rejected, no absolute path/public private-upload URL in responses. Keep proof route regression intact. | M |
| **P1-7: Correct aggregate stats and SOS awareness** (G7/G9) | `frontend/index.html`, `frontend/js/user-dashboard.js`, `frontend/user-dashboard.html`, `backend/app.py` only for a missing aggregate definition | Anonymous homepage uses real aggregate counts with clearly defined incident/rescue/volunteer labels and no private records; completed value matches DB aggregate, API errors show unavailable rather than 0; notification text reflects awaiting verification/rejection and actual update time. SOS AI Result uses correct existing SOS priority data or is removed if no meaningful result, never a report ID collision. | S–M |
| **P1-8: Make existing free map services policy-compliant** | `frontend/js/leaflet-map.js`, `netlify.toml`, related map/form tests and documentation | Use explicit user-submitted address search rather than public Nominatim autocomplete; enforce/cache within provider limits and document switching/identification. Origin-only referrer or another reviewed provider-identification mechanism preserves private paths/coordinates while satisfying tile service rules. Attribution visible; no bulk downloads; GPS/manual selection remains usable on geocoder failure. | M |
| **P1-9: Verify free-only durable hosting feasibility before any deployment** | `render.yaml`, `backend/config.py`, `backend/security.py`, upload helpers, `backend/requirements.txt` only if a selected free datastore needs a driver, `DEPLOYMENT_READINESS.md`, `README.md`, `frontend/js/api.js` | Demonstrate a $0 configuration with durable DB and private evidence storage across restart/redeploy, authorized image access, no expiring-data surprise, rate-store availability, limits/backup plan and intended frontend CORS/API pair. Keep local SQLite supported. Do not merely change plan to free while leaving ephemeral storage. No provider is provisioned by this audit. | L / external decision |
| **P1-10: Close current integration coverage gaps** | Existing `backend/tests/`, `frontend/tests/`; local-only temporary fixtures | Full actual forms: reporter SOS -> volunteer acceptance/progress/proof -> admin reject/resubmit/approve -> citizen completed; NGO create/update/allocate; admin inbox CRUD; two distinct nearby households and admin duplicate recovery, flag/status consistency. Run once with real HTML and isolated Flask storage, all four role-denial checks, GPS/CDN failures. Linux smoke separately needs isolated test Redis. | M |

### P2 — polish and optional work

| Task | Likely files | Acceptance tests | Effort |
| --- | --- | --- | --- |
| **P2-1: Responsive/accessibility/error-state pass** | `frontend/css/styles.css`, existing dashboard HTML/JS, `frontend/map.html` | Phone/desktop widths, keyboard focus, scrolling and proof dialog work; no covering GPS button, unreadable tables or unavailable-map crash; readiness/status UI rolls back on failure; valid role navigation retained. | M |
| **P2-2: Remove remaining sample statistics and polish status feedback** | `frontend/auth.html`, `frontend/user-dashboard.html`, admin/volunteer dashboard HTML/JS | Join date uses own created_at; static people-helped/response-time ticker explicitly illustrative or removed; status controls reflect saved values and errors; no “safe/no emergency” claim from an empty feed. | S |
| **P2-3: Optional specialist verification** | `LOCAL_FLOOD.md`, `frontend/js/flood-intelligence.js`, `backend/routes/flood.py`, existing flood tests only if defects found | With an already processed upstream event, inspect actual bounded pages/summary, toggles, legend/mobile scroll and unavailable upstream behavior. Historical candidates/exposure/connectivity stay unvalidated. No satellite processing or scientific-gate change. | S / configured upstream |

Read-only profiles, snapshot timelines and whole-resource allocation are the
current product contracts. Profile editing, push/SMS/email delivery, a separate
history page, account-role administration and new official-alert providers are
not automatically added to the essential backlog merely because other platforms
have them.

Recommended sequence: P0-1 -> P0-2 -> P0-3 -> P1-1 -> P1-2 -> P1-3 -> P1-7 ->
P1-6 -> P1-4 -> P1-5 -> P1-8 -> P1-10, then P2 polish. P1-9 is a separate
pre-deployment decision/gate after local core correctness; it must be resolved
before applying any hosting configuration. Optional external modules must not
block the citizen/volunteer/admin local SOS demonstration.

## Free-services constraint and external-policy evidence

Current `render.yaml` uses `plan: starter` and a paid persistent disk. Do not apply
it under the new free-only requirement. Render documents that free web-service
filesystems are ephemeral and cannot attach persistent disks; its free Postgres
also expires after 30 days. Therefore changing only the service plan would lose
SQLite records/private uploads. Keep the architecture locally; assess an approved
free durable datastore and private image store, or another free hosting arrangement,
with actual retention/quotas and restart tests before choosing changes. No free
provider setup, Linux Gunicorn runtime or hosted Redis has been verified here.
[Render free-service documentation](https://render.com/docs/free), checked 20 October 2026.

Public Nominatim requires at most one request/second in aggregate, application
identification, attribution and a switchable service; client autocomplete is
forbidden. Existing 600 ms input debouncing does not meet that contract. Manual
GPS/map selection should remain usable without geocoding; do not send personal or
confidential material to the service.
[Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/), checked 20 October 2026.

OSM raster tiles require visible attribution, browser Referer identification and
normal caching; no bulk/offline prefetch. Netlify's current `no-referrer` prevents
the required Referer. A narrowly reviewed origin-only policy can identify the
application without forwarding private URL paths/query coordinates.
[OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/), checked 20 October 2026.

## Tests executed and remaining verification

| Check | Result |
| --- | --- |
| `.venv\Scripts\python.exe -B -m unittest discover -s backend/tests` | **78 passed**, 0 failures. SQLAlchemy legacy Query.get deprecation warnings remain. Uses isolated memory/temp data. |
| `node --test frontend/tests/*.test.cjs` | **53 passed**, 0 failures. These are contract/VM checks, not complete physical-browser workflows. |
| Python AST syntax check | **41 backend Python files parsed**, 0 failures; no bytecode/database changes required. |
| `node --check` for `frontend/js/*.js` | **11 scripts passed**, 0 failures. |
| HTML local file and explicit fragment reference scan | No missing targets. Does not certify handler/API behavior. |
| `node frontend/tests/auth-flow.browser.cjs --warm-cache` | **PASS**, actual auth.html + temporary real Flask API, volunteer registration/stored role/profile/login/dashboard/logout; old cached auth URL unused. |
| `node frontend/tests/rbac.browser.cjs` | **PASS**, four dashboard identities and volunteer visiting citizen dashboard redirects correctly; API responses are simulated. |
| `node frontend/tests/detect-location.browser.cjs` | **FAIL**, twice at line 152 linked-report center assertion. Before failure, six physical form-button scenarios and map overview/demo exclusion/flood-warning checks passed. Later location-search/refresh checks did not execute. |
| Additional isolated API/actual-script probes | Confirmed G1/G2/G3/G4/G6/G7 as documented; these are diagnostic observations, not added passing regression tests. |

Initial sandboxed Chrome attempts timed out establishing `Page.enable`; reruns
outside that sandbox executed the browser checks described above. The map assertion
failure persisted when run alone. No tests were edited to make them pass.

Not performed: real user/account testing, actual device GPS, live weather/flood
upstream checks, full mobile visual audit, external message delivery, current
dependency vulnerability rescan, Linux/Gunicorn/real Redis smoke, or hosted
Netlify/Render validation. Historical user-reported local workflows are valuable
context but do not replace these current verification limits.

Safe commands to repeat existing focused tests (no installs or live DB required):

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests
node --test frontend/tests/*.test.cjs

# Smaller relevant backend subset; discovery provides test-module imports.
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -p test_rbac.py
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -p test_sos_lifecycle.py
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -p test_admin_analytics.py

# Existing Chrome required. Temporary profiles; no real accounts or provider requests.
$env:PYTHONDONTWRITEBYTECODE = '1'
node frontend/tests/auth-flow.browser.cjs --warm-cache
node frontend/tests/rbac.browser.cjs
node frontend/tests/detect-location.browser.cjs  # Currently fails at linked-report center.

Get-ChildItem frontend/js -Filter *.js | ForEach-Object { node --check $_.FullName }
```

The separate `backend/tests/gunicorn_smoke.py` requires Linux and a privately
configured dedicated test `SMOKE_REDIS_URL`; it was not run on Windows. Never point
that test at production Redis or the original database.

## First development task

**Implement P0-1: validate disaster-report creation and admin override before
commit, with rollback/upload cleanup and regression tests proving invalid input
cannot break shared feeds.** This is a reproduced persistent data-integrity defect,
needs no external service or schema reset, and has a small, testable scope.
