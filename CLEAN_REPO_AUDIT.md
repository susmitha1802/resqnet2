# Clean ResQNet source preparation

Original: `D:\B.Tech\Hackathons\MultiModel-AI-26\resqnet1` (read-only).
Destination: `D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet` (absent before copying).

## Copy scope and changes

84 reviewed source/test/documentation/configuration files were copied from the
latest working tree, including uncommitted fixes. Backend routes, models, AI
heuristics, focused backend tests, frontend HTML/CSS/JS/tests and safe deployment
configuration were retained. All existing required static references resolve;
JSON configuration was retained. No original Git object or history was copied.
Two empty runtime-directory `.gitkeep` files and this audit were added.

Sensitive/runtime exclusions: the entire original `.git` (31 files), `.venv`
(4,013 files), uploads (3 files), instance directory (2 files), all real `.env`
files, databases/SQLite sidecars, backups, caches, logs and generated data. The
unused `backend/ai/disaster.h5` binary was excluded because current classification
does not reference it and its provenance is unreviewed. Legacy `start.bat` was
excluded because it installs packages automatically and has incorrect paths;
README.md supplies explicit setup commands. No Flood Mapper datasets were copied.

Only the new copy was adjusted:

- Homepage provider credential removed before writing the copy; weather now uses
  existing `/weather/live`, with an unavailable state and a focused regression.
- Demo seed HTTP fixtures are clearly synthetic; private-looking organization and
  personal contacts were excluded. Standalone seed contacts are non-routable
  placeholders. Demo passwords remain random/undisclosed and production seeding
  remains prohibited. Legacy fingerprint constants and test-only identities remain
  as provenance/security fixtures, not existing accounts or login credentials.
- Swagger no longer displays example passwords/phone numbers; editor Python
  settings are portable. Runtime files align to the existing deployment's Python
  3.12.15 pin; that Linux patch build was not executed locally.
- Browser test harness accepts `PYTHON_BINARY` so validation can reuse an installed
  interpreter without copying environments. Runtime workflows were not redesigned.
- README/env template/ignore rules and operational guides describe this clean copy;
  historical RBAC evidence is clearly labelled and later security findings prevail.

Ten critical workflow/module files were hash-identical to the original, including
SOS lifecycle/volunteer/admin/NGO routes, privacy projections, auth/session/API code
and both Flood Intelligence integration modules. Satellite processing was untouched.

## Safe configuration

`.gitignore` covers Python/JS environments and caches, Flask databases and SQLite
sidecars, uploads, secrets/private keys, backups, logs, generated datasets/model
binaries and build/coverage outputs. It permits `.env.example`, required application
source, normal JSON/static assets and the two empty runtime placeholders.

`backend/.env.example` has blank signing, enrollment, weather and flood values;
development defaults, seeding/debug disabled, local SQLite/private uploads and
explicit local/previous-hosted CORS origins. No credentials were copied into it.
README's environment creation was executed in a temporary directory: it generated
two distinct random secrets without printing them and refused to overwrite `.env`.

## Validation

- Backend: **68 passed**, including cross-role auth, SOS acceptance/proof review,
  rollback, NGO ownership, analytics, weather/pings, privacy and bounded flood proxy.
- Frontend: **53 passed**, including the new homepage weather proxy regression.
- Actual clean-copy `auth.html` plus Flask routes: four isolated Chrome flows
  passed registration, profile, login redirect, role dashboard and logout. Fresh
  temporary accounts/database/browser profile; no real accounts or external CDNs.
- Syntax: 37 Python files, 23 standalone JS files and 8 inline scripts passed.
  All 100 checked local HTML resource/link references resolve.
- Fresh temporary SQLite initialized successfully, contained no users, had required
  tables, and returned HTTP 200 from `/health`. No persistent DB or `.env` was left
  in this repository. No existing records were copied or changed.
- Available lightweight secret checks found no provider tokens, private keys,
  literal JWTs or inline weather keys. Gitleaks/detect-secrets/trufflehog were not
  installed; none was installed for this task. Test-only passwords/codes and
  clearly synthetic fixtures are expected, not production secrets. This is a
  bounded source review, not proof against every possible credential format.

Tests reused the original's installed Python 3.12 interpreter with bytecode writes
disabled; packages/environments were not installed or copied. Existing SQLAlchemy
`Query.get()` deprecation warnings remain. Hosted services, deployment, a full Linux
build, penetration testing and the full operational browser journey were not verified.

## Original preservation exception

A SHA-256 snapshot covered all 4,171 original files, including Git metadata,
environment, database, uploads and virtual environment. Subsequent comparison
found **only `.git/gk/config` changed during the run**. The agent did not write or
restore that file; its cause is unverified. Every other file hash matched,
including HEAD, index, refs, core Git config, source, databases and uploads.
Therefore complete byte-for-byte preservation of all original metadata cannot
be claimed. No original files were deleted/added, records reset, Git history
rewritten, commands committed/pushed, or original configuration edited by the agent.

## Git preparation and remaining blockers

After source/tests/configuration validation, a fresh local `main` branch was
initialized and **87 reviewed files staged**: 12 root configuration/docs, 42 backend
files (including tests/placeholders) and 33 frontend files (including tests).
The staged manifest matches reviewed source; 52 files have Git's normal CRLF/LF
normalization only. Staged contents passed the same secret-pattern review and
runtime-ignore probes. Git has **zero commits, zero remotes**, and only 87 staged
additions, with no unstaged/untracked files. No original history was imported.
No commit, push or deployment was performed.

Before release: revoke/rotate the original exposed provider key and any published
credentials actually used; fresh history does not revoke secrets. Review dependency
advisories and Linux compatibility, configure actual API/CORS/HTTPS/secret/durable
storage settings, verify backups and rate limits, create authorized non-demo admins,
and verify hosted workflows. NGO fallback marker accuracy and localStorage/copied
JWT revocation limitations remain. See DEPLOYMENT_READINESS.md.

## Commands after explicit approval

First create an **empty private** GitHub repository manually; no README/history or
credentials in its URL. Substitute its actual SSH URL in these PowerShell commands:

```powershell
Set-Location 'D:\B.Tech\Hackathons\MultiModel-AI-26\ResQNet'
git status --short
git diff --cached --stat
git commit -m "Initial reviewed ResQNet source"
$approvedRemote = Read-Host 'SSH URL of your approved empty private GitHub repository'
git remote add origin $approvedRemote
git push -u origin main
```

These commands were not executed. Commit approval is separate from deployment
approval; review the preservation exception and security blockers first.
