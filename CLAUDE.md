# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Read-only web dashboard for monitoring FortiGate firewalls via FortiManager. All integrations are strictly read-only — nothing in this project pushes configuration to Fortinet devices.

## Running the Flask web app

```bash
# Install dependencies
uv sync

# Development
python wsgi.py            # https://localhost:5443

# Production (gthread worker required for background summary job)
gunicorn --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:5443 wsgi:app
```

The app auto-enables HTTPS if `certs/cert.pem` and `certs/key.pem` exist (self-signed is fine; generate with `openssl req -x509 ...`). Both cert files are gitignored.

Configuration is read from `.env` (gitignored). Key variables:

```
SECRET_KEY=              # Flask session signing key
FMG_PRIMARY_HOST=<your-fortimanager-ip>   # Used for ADOM/device/policy queries
FMG_API_TOKEN=your-bearer-token-here   # preferred
# FMG_USERNAME=your-api-username         # fallback if no token
# FMG_PASSWORD=your-api-password
FMG_VERIFY_SSL=false
CPU_WARN=70  CPU_CRIT=90
MEM_WARN=75  MEM_CRIT=90
SUMMARY_REFRESH_HOUR=1   # nightly summary recalculation hour (default 01:00)
SUMMARY_REFRESH_MINUTE=0
```

Infrastructure dashboard targets (FortiManager, FortiAnalyzer, FortiCollector, FortiAuthenticator, etc.)
are defined in `infra_targets.json` (gitignored). Copy `infra_targets.example.json` to get started.
Each entry is `{ "label": "...", "host": "...", "type": "..." }`. Add or remove entries freely.
An optional `"token"` field on any entry sets a per-device bearer token (each Fortinet appliance
type generates its own token). Token priority: per-device `"token"` → `FMG_API_TOKEN` → username/password.

## User management

```bash
python manage_users.py add <username> [--password <pw>] [--role admin|viewer]
python manage_users.py list
python manage_users.py delete <username>
python manage_users.py secret   # generate a SECRET_KEY value
```

User accounts are stored in `users.json` (committed). Passwords are bcrypt-hashed.

## Flask app architecture

```
app/
  __init__.py          # Flask app factory, registers blueprints, starts background schedulers
  config.py            # Reads .env into a Config object
  auth.py              # Session-based login; bcrypt password verify against users.json
  fmg_client.py        # FortiManager JSON-RPC client (context manager: auto login/logout)
  hygiene.py           # Rule hygiene check engine (7 checks: unnamed, unlogged, shadow, disabled, expired, unhit, no_deny_all)
  device_review.py     # Device Review check engine — interface protocol checks; add new checks here
  rule_review.py       # Policy analysis + route-tracing engine; zone policy integration
  zone_db.py           # Zone policy DB engine — loads policy_db.json, runs queries, validates, handles CRUD
  summary_job.py       # Background job: managed firewall + rule counts; nightly APScheduler
  adom_cache.py        # Background cache: ADOM list from FortiManager, refreshed every 30 min
  groups.py            # Group management: tab permissions + ADOM access control (groups.json)
  decorators.py        # login_required, tab_required, admin_required, check_adom_access
  routes/
    auth_routes.py            # /login, /logout
    dashboard_routes.py       # /, /firewalls, /versions (Jinja2 pages)
    api_routes.py             # /api/* JSON endpoints consumed by frontend JS
    hygiene_routes.py         # /hygiene page + /api/hygiene/* endpoints
    rule_review_routes.py     # /rule-review page + /api/rule-review/* endpoints
    zone_routes.py            # /zone-policy page + /api/zone/* endpoints
    device_review_routes.py   # /device-review page + /api/device-review/* endpoints
    admin_routes.py           # /admin page + /admin/api/* group/user/log/ADOM endpoints
wsgi.py                # Entry point; SSL context wiring
policy_db.json         # Network segmentation policy database (gitignored — runtime data)
groups.json            # Group definitions (gitignored — copy from groups.example.json); includes tab and ADOM permissions
```

### ADOM filtering convention

All ADOM list endpoints filter out names that start with `"forti"` (case-insensitive) — these are FortiManager system ADOMs (FortiManager_Managed_Devices, etc.) that don't contain real firewall policy packages. Both `/api/adoms` and `/api/rule-review/adoms` apply this filter. Any new ADOM-returning endpoint should do the same.

### ADOM access control

Groups have two layers of access control:

1. **Tab access** — which navigation tabs a non-admin user can see (existing).
2. **ADOM access** — which FortiManager ADOMs a non-admin user can interact with (added).

Each group in `groups.json` may include:
```json
{
  "adom_restrict": true,
  "allowed_adoms": ["Enterprise Services", "Enterprise Dev", "Enterprise SDWAN"]
}
```

**Access rules:**
- Admin users → always unrestricted (all ADOMs, all tabs).
- Non-admin users with at least one group where `adom_restrict=false` → unrestricted ADOM access.
- Non-admin users where every group has `adom_restrict=true` → union of their `allowed_adoms` lists.
- User in no group → no ADOM access.

**Enforcement** (`app/decorators.py → check_adom_access(adom)`): called at the top of every ADOM-scoped API route. Returns a 403 JSON response if the user cannot access the ADOM. ADOM list endpoints (`/api/adoms`, `/api/rule-review/adoms`) silently filter out inaccessible ADOMs.

**ADOM cache** (`app/adom_cache.py`): queries FortiManager at startup and every 30 minutes. The admin UI uses this list to populate the ADOM checkbox picker in the group editor. New ADOMs are discovered automatically but are **never automatically added** to any group's `allowed_adoms` list — restricted groups must be explicitly updated by an admin.

**Admin API endpoint** `GET /admin/api/adoms` returns `{ adoms: [...], last_updated, status }` from the cache.

### FortiManager client design

`FMGClient` in `app/fmg_client.py` authenticates to FortiManager's JSON-RPC API (`/jsonrpc`) and queries managed FortiGate devices through FortiManager's proxy endpoint (`/sys/proxy/json`). This means the app never connects directly to individual firewalls — all firewall data flows through FortiManager.

Health status uses a three-tier model: green (healthy), yellow (warn threshold crossed), red (crit threshold crossed or unreachable). Thresholds are the `CPU_WARN/CRIT` and `MEM_WARN/CRIT` env vars.

Sessions expire after 1 hour. `COOKIE_SECURE` is automatically set when SSL is active.

### Background summary job

`app/summary_job.py` runs a background thread at startup and on a nightly schedule (APScheduler). It enumerates all ADOMs, counts managed devices and policy rules (only in ADOMs that have devices — empty system ADOMs are skipped). Results live in an in-memory dict; `/api/summary` reads from it instantly.

**Critical production requirement:** Gunicorn must use `--worker-class gthread`. The default `sync` worker forks child processes — background threads from the parent do not transfer, so the scheduler would never fire. Use `--workers 2 --threads 4 --worker-class gthread`.

### Rule Review tab

`GET /hygiene` → `hygiene.html` + `hygiene.js`

Two-section layout (tab displays as "Rule Review" in the nav; internal key remains `rule_hygiene`):
1. **Policy Rules** (top) — select ADOM + package, rule table loads automatically. Features:
   - Independent ADOM/package selectors from the Hygiene Analysis section below
   - Full-text regex search across name, ID, comment, source, destination, service, interfaces
   - Field-scoped filter dropdown (search within a single column)
   - Address groups and service groups expand inline (click the triangle) to show member objects
   - Address objects show subnet detail when available
   - Interface badges (source = blue, destination = green)
   - Page size 10/25/50/100 with `<< < … > >>` pagination
   - Export (CSV/JSON/PDF) — each export includes a filter header block at the top (package, ADOM, timestamp, search terms, total/filtered counts)
2. **Hygiene Analysis** (below) — select ADOM + package, run 7 checks, filter/export findings (CSV/JSON/PDF).

Backend: `POST /api/hygiene/policies` returns `srcaddr_exp`, `dstaddr_exp`, `service_exp` arrays with `{name, type, members?, detail?}` objects alongside the flat name lists. Also returns `srcintf`/`dstintf`.

### Device Review tab

`GET /device-review` → `device_review.html` + `device_review.js`

Runs configurable security checks against the management-plane interfaces of every device in a selected ADOM.

**Workflow:**
1. Select ADOM → device list loads automatically (all selected by default).
2. Filter/deselect devices using the searchable grid.
3. Choose which checks to run (all checked by default).
4. Click **Run Analysis** — findings appear in a filterable, paginated table.
5. Export results as CSV, JSON, or PDF (PDF includes ADOM, date/time, device count — suitable as compliance evidence).

**Result severity levels:**
- `INSECURE` — red highlight: cleartext protocols (HTTP, Telnet) are enabled
- `WARN` — yellow: no secure management alternative (HTTPS/SSH) present
- `INFO` — blue: informational findings (e.g. PING enabled)

**Check engine — `app/device_review.py`:**

The check registry (`CHECKS` list) is the single place to add new checks. Each entry is:

```python
{
    "key":         "my_check",           # unique ID used in API + permissions
    "name":        "Display Name",       # shown in UI checkbox list
    "description": "One-line summary",   # tooltip
    "severity":    "INSECURE|WARN|INFO", # drives badge colour
    "run":         _my_check_function,   # callable(device_name, interfaces) -> list[Finding]
}
```

A `Finding` dict must contain `device`, `interface`, `ip`, `check`, `result`, `detail`, and optionally `protocols`.

**API endpoints:**
- `GET  /api/device-review/adoms/<adom>/devices` — list devices in an ADOM
- `POST /api/device-review/run` — body: `{ adom, devices: [...], checks: [...] }` — run selected checks; `devices: []` means all devices, `checks` absent means all checks

### Rule Validation tab

`GET /rule-review` → `rule_review.html` + `rule_review.js`

Three-step workflow: define flows → select policy packages → review results.
- Resolves address and service objects for each ADOM to match flows against policies
- Performs path-relevance checks using live device routing + interface data via FMG proxy
- Integrates zone policy (via `app.zone_db`) for segmentation policy verdicts — reads `policy_db.json` directly, no external service required
- Generates FortiOS CLI snippets for new/modified rules
- Verdict categories: PERMITTED / MODIFIABLE / NEW_RULE_NEEDED / EXPLICITLY_DENIED

### Zone Policy tab

`GET /zone-policy` → `zone_policy.html` + `zone_policy.js`

Self-contained network segmentation policy browser. No FortiManager connection required — all data comes from `policy_db.json` in the project root.

Four sub-tab panels:
1. **Query Flow** — enter source/destination IPs (multi-line or comma-separated), optional service, get ALLOWED/BLOCKED/UNKNOWN verdict with governing rules
2. **Browse** — zone accordion list (searchable, filterable) + full policy table (filterable by access type/severity)
3. **Validate** — schema validation report with error/warning counts
4. **Edit Database** (admin only) — add/remove/modify zones, subnets, and policy rules in-place

Backend: `app/zone_db.py` is the single source of truth — query engine, validation, and all CRUD mutations. It writes back to `policy_db.json` atomically. Routes in `app/routes/zone_routes.py`:
- `POST /api/zone/query` — flow query (tab_required)
- `GET /api/zone/zones`, `GET /api/zone/policies`, `GET /api/zone/validate` — read-only (tab_required)
- Zone/subnet/policy mutation routes — admin_required

Zone evaluation logic: block all > block only (service match) > allow all > implicit UNKNOWN. Zone hierarchy is supported via `parents[]` and zone name expansion.

#### policy_db.json

Runtime data file (gitignored). Copy from a known-good source or build from scratch. Structure:

```json
{
  "zones": {
    "ZoneName": {
      "domain": "Default", "is_shared": false, "description": "",
      "subnets": [{"subnet": "10.1.0.0/16", "description": ""}],
      "children": [], "parents": []
    }
  },
  "policies": [
    {
      "policy_set": "Corp", "from_zone": "ZoneA", "to_zone": "ZoneB",
      "access_type": "allow all", "severity": "high",
      "services": [], "description": ""
    }
  ]
}
```

#### Standalone production deployment

4THealth can run standalone (without FortiManager) if only the Zone Policy tab is needed. The only requirement is `policy_db.json`. All other tabs degrade gracefully when FMG is unreachable. To deploy standalone:

1. Copy `policy_db.json` to the project root
2. Create `users.json` with at least one account (`python manage_users.py add ...`)
3. Set `SECRET_KEY` and optionally `FMG_PRIMARY_HOST` in `.env`
4. Generate TLS certs: `openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem -out certs/cert.pem -days 365 -nodes`
5. Run: `gunicorn --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:5443 wsgi:app`

## Dependency management

This project uses `uv`. `uv.lock` is committed; `pyproject.toml` should be too. Do not use `pip install` directly — use `uv add <package>` to keep the lockfile in sync.
