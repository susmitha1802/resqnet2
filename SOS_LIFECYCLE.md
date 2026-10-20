# SOS lifecycle and focused checks

No schema or enum additions. Acceptance still uses authenticated
`PUT /volunteer/accept-task` with `{ "request_id": 123 }`.

| Action | HelpRequest status | ReliefTask status | Verification |
| --- | --- | --- | --- |
| Citizen submits SOS | Pending | No task | — |
| Available volunteer accepts | Accepted | Assigned | Pending (not yet reviewable) |
| Assigned volunteer / admin marks travel | En Route | En Route | Pending |
| Assigned volunteer / admin marks arrival | On Site | On Site | Pending |
| Assigned volunteer uploads proof | On Site | Proof Submitted | Pending; awaiting admin verification |
| Admin rejects | On Site | On Site | Rejected; volunteer must resubmit |
| Volunteer resubmits | On Site | Proof Submitted | Pending; previous reviewer cleared |
| Admin approves stored proof | Completed | Completed | Approved; reviewer and completion time saved |

Proof may also be uploaded directly from Assigned or En Route; this records
arrival as On Site. No generic endpoint can set Completed, invent an assignment,
move an active task backwards, or reset a request awaiting review. Admins
can classify unassigned Pending requests as Duplicate and reopen Duplicate as
Pending. NGO inventory/allocation endpoints are unchanged.

Each task/request transition uses conditional writes and a single transaction.
Rejected or pending proof keeps the volunteer on_task. Approval increments the
completion counter once and releases the volunteer unless another legacy active
task exists. Existing acceptance tests remain applicable.

Private proof is validated as PNG/JPEG, saved with a generated name below the
configured UPLOAD_FOLDER/task_proofs, and represented in JSON by an authenticated
task URL. Only the assigned volunteer and admins can GET
`/volunteer/tasks/<task_id>/proof`. The old filename route is removed. Admin
View proof fetches with the JWT Authorization header and shows a temporary blob
image; no token is put in URLs and no absolute filesystem path is serialized.
Existing absolute or `/uploads/task_proofs/...` references work only when they
resolve inside the configured private directory. Keep UPLOAD_FOLDER private
when configuring any external web server.

The existing verification queue supplies View proof, Approve and Reject.
Citizens see awaiting-review/rejection text beside a valid request status;
their visible dashboard refreshes every 15 seconds. Active map requests now
include En Route and On Site. Historical Completed records without valid
approval are explicitly labelled "Legacy completion; admin verification unconfirmed".

Known legacy data errors can be inspected without starting Flask or seeding:

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
.\.venv\Scripts\python.exe -B backend\repair_sos_data.py
# Apply reviewed repairs; SQLite is backed up automatically first:
.\.venv\Scripts\python.exe -B backend\repair_sos_data.py --apply
```

The tool changes illegal request Proof Submitted to On Site only when exactly
one task is awaiting review. Legacy demo task verification Verified becomes
Pending; historical Completed status is retained, without inventing approval.
Incompatible legacy request records stop the repair for manual reconciliation.
For non-SQLite databases, take a normal database backup before applying.
Stop application writes during repair. Preserve existing proof files; moving
UPLOAD_FOLDER or losing those files requires separate recovery. Replaced rejected
images remain private but are not a versioned proof-history feature.

Focused tests (no network, processing, or existing DB writes):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -p test_sos_lifecycle.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -p test_volunteer_acceptance.py -v
node --test frontend\tests\sos-lifecycle.test.cjs frontend\tests\volunteer-acceptance.test.cjs
node --check frontend\js\admin-dashboard.js
node --check frontend\js\user-dashboard.js
node --check frontend\js\volunteer-dashboard.js
```

Manual browser check: citizen submits SOS; volunteer accepts, records travel /
arrival and uploads proof; admin opens proof with View proof, rejects once,
then approves resubmitted proof. Citizen should show awaiting verification,
resubmission needed, then Completed. Another user must not view the private image
or upload proof; replayed review must fail without incrementing the counter twice.
