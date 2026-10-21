# Local ResQNet demonstration

Use a fresh local database created by the steps in [README.md](README.md). Keep
`SEED_DEMO_DATA=False`. Run Flask on `127.0.0.1:5000` and serve only `frontend/`
on `127.0.0.1:5500`. Use synthetic demonstration accounts; never show tokens,
contact details or evidence images on a public screen.

1. Register one citizen, one volunteer and one NGO in `auth.html`. Log into each
   account and confirm its own dashboard. An admin needs a privately configured
   `ADMIN_SECRET_CODE` during authorized registration; remove it after enrollment.
2. Citizen: submit a Rescue SOS with a map point, optional single PNG/JPG, and
   view its Pending status. A community disaster report is a separate observation.
3. Volunteer: mark available, locate the Pending SOS, accept it once, move to
   En Route and On Site, then submit private proof. Show the citizen's “Awaiting
   admin verification” progress. A replayed acceptance or proof fails.
4. Admin: open Verification, view the JWT-protected proof, reject once, let the
   volunteer resubmit, then approve. Show the citizen's Completed status and
   the admin analytics count. The admin can also inspect read-only user and NGO
   inventory lists, restore an unassigned Duplicate SOS to Pending, and correct
   a report type without claiming scientific verification.
5. NGO: create an inventory item, edit its quantity/location while unallocated,
   allocate it to an active SOS, and confirm that a later edit is rejected.
6. Map: show a linked SOS/report, pan, filter and search a location by pressing
   Search. The map retains user-selected viewport and marks community reports as
   unverified. Use Flood Intelligence only as an optional historical layer; it
   does not describe live flooding or confirmed road closures.

Optional flood layer: start the existing event API using [LOCAL_FLOOD.md](LOCAL_FLOOD.md),
set `FLOOD_API_BASE_URL=http://127.0.0.1:8765` for ResQNet and open `map.html`.
The `kerala-discovery-check` event reports candidate area, potential exposure and
hypothetical connectivity with `NOT_READY` scientific status.

Focused isolated checks from the ResQNet root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests
node --test frontend/tests/*.test.cjs
node frontend/tests/auth-flow.browser.cjs --warm-cache
node frontend/tests/rbac.browser.cjs
node frontend/tests/detect-location.browser.cjs
```

Chrome browser scripts use temporary profiles, isolated/mocked APIs and no real
accounts. They do not replace a manual rehearsal with the actual local accounts.
