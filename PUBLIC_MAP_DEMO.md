# Fictional map scenarios on the existing Supabase database

This is a deliberate, one-time operation for the current live database. It adds
**three fictional exercise markers only**. It does not add SOS requests, disaster
observations, users, proof images or preparedness notifications. The markers are
hidden from operational feeds, statistics and the default public map. Visitors
can show them with **Show DEMO** or a `map.html?demo=1` link, where a persistent
banner and every marker say they are fictional. They are not live emergencies.

The Render Free service has no shell or one-off job access. Run the command from
a trusted local machine with a network connection to Supabase's Session Pooler.
Do not run it as a Flask startup hook or put database credentials in Git,
Netlify, browser code or a support ticket. First confirm in the Render and
Supabase dashboards that the project reference is the **same current database**;
take a reviewed backup before modifying that database.

Create the Git-ignored `backend/.env.demo-map` locally with only these names:

```text
RESQNET_DEMO_DATABASE_URL=<the current Supabase Session Pooler URL with postgresql+psycopg and sslmode=require>
SUPABASE_URL=<the matching https://project-ref.supabase.co origin>
```

Never share the file or its values. The script checks that both URLs refer to
the same Supabase project, use port 5432 and TLS, and never prints connection
details. It does not initialize or migrate a schema. On Windows, from the
repository root:

```powershell
.\.venv\Scripts\python.exe -B backend/public_map_demo.py status
.\.venv\Scripts\python.exe -B backend/public_map_demo.py seed
.\.venv\Scripts\python.exe -B backend/public_map_demo.py status
```

`seed` is idempotent. It refuses an incomplete or edited fixture. It leaves
all unrelated rows untouched. After the reviewed backend and frontend commits
have deployed, open `https://resqnet2026.netlify.app/map.html?demo=1` and confirm
three blue dashed DEMO markers plus the fictional-scenario banner. The normal
map, operational counts and `/public/stats` must exclude them. If the API says
the scenarios are unavailable, verify the deployed commit and the fixture
status; never invent markers or alter real records to force a display.

To remove only the intact three-marker fixture:

```powershell
.\.venv\Scripts\python.exe -B backend/public_map_demo.py cleanup
```

Cleanup refuses changed rows or any responder acknowledgement linked to them.
Afterward, remove `backend/.env.demo-map` from the local machine and verify the
demo endpoint returns an empty list. The separate eight-account local staging
fixture in [DEMO_STAGING.md](DEMO_STAGING.md) is never copied to production.
