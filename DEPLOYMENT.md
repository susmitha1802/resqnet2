# Render Free + Netlify Free + Supabase Free preview

This is a **deployment preparation guide**, not a live deployment or an
emergency-service availability guarantee. Use a new Supabase project and test
identities first. Never paste a database password, API key, JWT secret, private
contact record or proof image into Git, Netlify variables, browser code or
support tickets. The original `resqnet1` and its database are not deployment
inputs. Do not apply an automatic migration to existing data.

## 1. Supabase dashboard

1. Create a **Free** project and note its project URL. In **Storage**, create a
   bucket named for `SUPABASE_STORAGE_BUCKET`, set it **Private** (never Public),
   and restrict uploads to `image/png` and `image/jpeg` with a 10 MB object cap.
   The backend validates bytes and serves images only through its authorized
   Flask routes. Do not add broad `anon`/`authenticated` Storage policies. Obtain
   a new `sb_secret_...` server key from **Settings → API Keys**; store it only
   in Render as `SUPABASE_SECRET_KEY`. A leaked secret bypasses RLS. [Storage
   bucket access](https://supabase.com/docs/guides/storage/buckets/fundamentals),
   [API keys](https://supabase.com/docs/guides/getting-started/api-keys).
2. From **Connect**, copy the **Session pooler** PostgreSQL URL (port 5432). This
   supports IPv4 where direct Free connections may be IPv6-only. Use
   `postgresql+psycopg://.../postgres?sslmode=require` for `DATABASE_URL`, with
   the exact host/username supplied by the dashboard; encode special password
   characters. Do not use transaction pooling on port 6543. For stronger server
   identity verification, obtain the Supabase CA and test
   `sslmode=verify-full` with `sslrootcert` in a private secret file. [Connection
   methods and TLS](https://supabase.com/docs/guides/database/connecting-to-postgres).
3. ResQNet accesses PostgreSQL only from Flask. In Supabase **Settings → Data API**,
   disable the Data API if the project permits it; otherwise remove `anon` and
   `authenticated` grants or enable restrictive RLS on all new ResQNet tables.
   Verify anonymous REST requests cannot read or mutate `users`, SOS, reports,
   tasks or contacts. Flask's own JWT does **not** authorize Supabase's Data API.
   [Secure data / Data API](https://supabase.com/docs/guides/database/secure-data).
4. On a **new empty application schema**, the Flask startup initializer creates
   model tables and PostgreSQL enum types. It refuses an incomplete existing
   schema; it does not migrate or overwrite records. Review schema, native enums,
   indexes and role/grants in a disposable project before any real import. Existing
   local SQLite rows and filesystem images are **not** copied by this code.

## 2. Render dashboard

1. Create a **Free Key Value** instance in the same region as the web service.
   Prefer its **internal** Redis URL, enable internal authentication if available,
   and keep external access disabled. Set this private URL as
   `RATELIMIT_STORAGE_URI`. Free Key Value is in-memory and may restart; the app
   then fails closed until Redis is healthy. [Key Value connection](https://render.com/docs/key-value),
   [Free limitations](https://render.com/docs/free).
2. Review `render.yaml`, then connect `susmitha1802/resqnet2` to one **Free**
   Python web service with root directory `backend`. Build installs
   `requirements.txt`; start uses the existing `wsgi:application` Gunicorn
   target. There is **no Render disk**. Select the correct Git branch/commit.
3. Enter `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
   `SUPABASE_STORAGE_BUCKET`, `RATELIMIT_STORAGE_URI`, `CORS_ORIGINS` and
   `TRUSTED_PROXY_HOPS` in Render's private Environment controls. Set
   `CORS_ORIGINS` to the final exact Netlify HTTPS origin (and any explicitly
   needed HTTPS preview origin). Verify the real Render forwarding chain before
   choosing `TRUSTED_PROXY_HOPS`; a wrong value permits rate-limit bypass or
   coalesces users. `SECRET_KEY` and `JWT_SECRET_KEY` must be independent,
   persistent, high-entropy values; Render's `generateValue` initializes them.
   Set `ADMIN_SECRET_CODE` privately only if controlled admin registration is
   intended. `APP_ENV=production`, `FLASK_DEBUG=False`,
   `SEED_DEMO_DATA=False`, `STORAGE_BACKEND=supabase` are required.
4. Confirm `/health` and startup logs. Startup refuses missing secrets, local
   production uploads on Render, invalid Supabase/TLS config, or unavailable
   Redis. Do not disable these checks to make deployment pass. A healthy
   `/health` alone does not prove database/storage/Redis durability.

### Temporary Render proxy check (before public access)

1. After reviewing and deploying this code to a restricted preview, set
   `TRUSTED_PROXY_HOPS=1` and `PROXY_DIAGNOSTIC_ENABLED=True` in Render's private
   Environment controls and redeploy. The diagnostic is absent by default and,
   when enabled, requires an existing admin JWT. It returns only a keyed
   comparison code for the address used by rate limiting; it never returns or
   logs IPs or forwarded headers. Keep the preview restricted to test users.
2. Sign in as the same test admin on the Netlify admin dashboard from network A.
   In that page's browser console, run the snippet below. Repeat on network B
   (for example, a phone using mobile data rather than the same Wi-Fi). Check
   DevTools Network to confirm the second request actually carried the spoofed
   `X-Forwarded-For` header; if the browser removes it, use a private HTTP client
   with the same admin JWT instead. Never paste the JWT or full request headers
   into logs, screenshots, tickets or chat.

   ```js
   async function proxyCode(spoof = false) {
     const response = await fetch(`${Api.BASE}/admin/proxy-diagnostic`, {
       headers: {
         Authorization: `Bearer ${Api.getToken()}`,
         ...(spoof ? { 'X-Forwarded-For': '192.0.2.123' } : {})
       }, cache: 'no-store'
     });
     if (!response.ok) throw new Error(`Diagnostic HTTP ${response.status}`);
     return (await response.json()).client_code;
   }
   console.log(await proxyCode(), await proxyCode(true));
   ```

   The two codes on each network must match; the code from network A must
   differ from network B. If either condition fails, do not open public access
   or increase the hop count by guesswork: inspect the actual Render forwarding
   chain privately and confirm the trusted rightmost value with Render support.
   This comparison tests the address used by Flask-Limiter, not network uptime.
3. Set `PROXY_DIAGNOSTIC_ENABLED=False` (or remove it) and redeploy. Confirm
   `/admin/proxy-diagnostic` now returns 404. Keep the verified hop count and
   normal authentication, rate limiting and production checks enabled.

## 3. Netlify dashboard

1. Connect the same reviewed branch. Use the repository's `netlify.toml`:
   `node scripts/build-netlify.cjs` copies `frontend/` to ignored `dist/` and
   inserts a **public HTTPS API origin** into the generated `dist/js/api.js`.
   Set `RESQNET_API_BASE` in Netlify Environment to the actual Render service
   origin, without a path. Never place a database URL, Supabase secret or Redis
   URL there. A missing/non-HTTPS origin fails the build.
2. Publish `dist/`, inspect the actual Netlify URL and update Render
   `CORS_ORIGINS` to that exact origin. Review Netlify deploy previews separately;
   a wildcard CORS origin is rejected. In the browser, verify `/profile` targets
   the intended Render service, not an old deployment or localStorage override.

## Required environment variable names

Render: `APP_ENV`, `SECRET_KEY`, `JWT_SECRET_KEY`, `DATABASE_URL`,
`STORAGE_BACKEND`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
`SUPABASE_STORAGE_BUCKET`, `RATELIMIT_STORAGE_URI`, `CORS_ORIGINS`,
`TRUSTED_PROXY_HOPS`, `FLASK_DEBUG`, `SEED_DEMO_DATA`. Optional:
`ADMIN_SECRET_CODE`, `OPENWEATHER_API_KEY`, `FLOOD_API_BASE_URL`,
`NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `MAX_CONTENT_LENGTH`.
Netlify: `RESQNET_API_BASE` (public origin only).

## Verification and limits before public access

- With synthetic accounts, test all four roles, SOS/report uploads, private
  owner/admin image reads, volunteer-only proof submission, admin-only approval,
  NGO ownership, logout, rate-limit 429 and Redis-outage 503. Verify public
  Supabase Storage URLs and anonymous Data API reads are denied. Check no key or
  absolute/private path appears in browser responses or built JS.
- Run a restart/cold-start test. Render Free sleeps after 15 minutes of idle
  traffic, has about a one-minute wake time and 750 free instance-hours per
  workspace per month; its filesystem is ephemeral. Supabase Free currently
  limits database size to **500 MB**, Storage to **1 GB**, egress to **5 GB**,
  can pause after low activity, and has no included daily backup feature.
  Monitor limits and maintain a reviewed off-service backup/restore procedure.
  Check Render's outbound-bandwidth billing controls as well as Supabase quotas;
  free compute does not imply unlimited zero-cost egress.
  [Render Free](https://render.com/docs/free), [Supabase pricing](https://supabase.com/pricing),
  [Supabase pausing](https://supabase.com/docs/guides/platform/free-project-pausing).
- Supabase Storage and PostgreSQL are separate systems: a failed DB transaction
  triggers compensating object deletion, but a network failure during deletion
  can leave an orphan. Monitor/reconcile private objects before quotas fill.
  Do not infer atomic cross-service transactions.
- No live Supabase project, PostgreSQL schema, Redis service, Render proxy,
  Netlify build or end-to-end hosted browser flow has been verified in this
  preparation. Free tiers and sleeping make this unsuitable as a guaranteed
  emergency dispatch channel. Keep a human fallback and do not call historical
  flood candidates or heuristic alerts verified real-time warnings.

Rollback: pause frontend access, retain Supabase database and private bucket,
save a verified backup, revert only the reviewed application release, and test
restoration with synthetic or authorized data. Never reset or delete existing
records merely to satisfy `create_all()`.
