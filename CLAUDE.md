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
SNMP_ENABLED=false       # enable SNMPv3 polling for FortiManager/FortiAnalyzer/FortiAuthenticator CPU/mem
SNMP_PORT=161
SNMP_TIMEOUT=5
SNMP_RETRIES=1
SNMP_POLL_INTERVAL=60    # seconds between background poll cycles
SNMP_USER=
SNMP_AUTH_PROTOCOL=SHA   # SHA | SHA256
SNMP_AUTH_KEY=
SNMP_PRIV_PROTOCOL=AES   # AES | AES192 | AES256
SNMP_PRIV_KEY=
```

Infrastructure dashboard targets (FortiManager, FortiAnalyzer, FortiCollector, FortiAuthenticator, etc.)
are defined in `infra_targets.json` (gitignored). Copy `infra_targets.example.json` to get started.
Each entry is `{ "label": "...", "host": "...", "type": "..." }`. Add or remove entries freely.
An optional `"token"` field on any entry sets a per-device bearer token (each Fortinet appliance
type generates its own token). Token priority: per-device `"token"` → `FMG_API_TOKEN` → username/password.

CPU/memory for `FortiManager`, `FortiAnalyzer`, and `FortiAuthenticator` entries is sourced via
SNMPv3 polling (see `app/infra_health_cache.py`), not FMG JSON-RPC — FortiAuthenticator in
particular has no JSON-RPC status/resource API. A background poller
(`app/infra_health_cache.py`, `SNMP_POLL_INTERVAL` seconds, default 60) queries each target and
caches `{cpu, mem, snmp_status}`; `/api/infrastructure` reads instantly from this cache. Optional
per-device `"snmp_user"` / `"snmp_auth_key"` / `"snmp_priv_key"` / `"snmp_auth_protocol"` /
`"snmp_priv_protocol"` fields override the global `SNMP_*` `.env` defaults, following the same
override-over-default pattern as `"token"`. `FortiCollector` entries (and any other type) continue
to use the legacy FMG JSON-RPC CPU/mem path unchanged.

CPU/mem OIDs live in `OID_MAP` in `app/infra_health_cache.py`. FortiManager's OIDs are confirmed
against a real FMG-VM64-KVM (v7.6.7), cross-checked against the FMG GUI's System Resources widget
— CPU is a direct percentage OID (`fmSystem` group, `1.3.6.1.4.1.12356.103.2.1.1.0`), but memory
has no native percentage OID and is derived from used-KB/total-KB. FortiAnalyzer and
FortiAuthenticator OIDs are still NOT confirmed against real hardware — verify both with
`snmpwalk` or Fortinet's official MIBs before enabling `SNMP_ENABLED=true` for those types in any
production environment.

SNMPv3 privacy (AES) requires the `cryptography` package — without it, `pysnmp` fails silently
with `Ciphering services not available` on every request needing `authPriv`.

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
  hygiene.py           # Rule hygiene check engine (6 checks: unnamed, unlogged, shadow, disabled, expired, unhit)
  device_review.py     # Device Review check engine — interface protocol checks; add new checks here
  rule_review.py       # Policy analysis + route-tracing engine; zone policy integration
  zone_db.py           # Zone policy DB engine — loads policy_db.json, runs queries, validates, handles CRUD
  summary_job.py       # Background job: managed firewall + rule counts; nightly APScheduler
  adom_cache.py        # Background cache: ADOM list from FortiManager, refreshed every 30 min
  groups.py            # Group management: tab permissions + ADOM access control (groups.json)
  decorators.py        # login_required, tab_required, admin_required, check_adom_access
  app_settings.py      # Persistent app settings (app_settings.json); used for external_api_enabled toggle
  api_tokens.py        # Bearer token CRUD for the external API; SHA-256 hashes stored in api_tokens.json
  routes/
    auth_routes.py            # /login, /logout
    dashboard_routes.py       # /, /firewalls, /versions (Jinja2 pages)
    api_routes.py             # /api/* JSON endpoints consumed by frontend JS
    hygiene_routes.py         # /hygiene page + /api/hygiene/* endpoints
    rule_review_routes.py     # /rule-review page + /api/rule-review/* endpoints
    zone_routes.py            # /zone-policy page + /api/zone/* endpoints
    device_review_routes.py   # /device-review page + /api/device-review/* endpoints
    admin_routes.py           # /admin page + /admin/api/* group/user/log/ADOM/settings/token endpoints
    pending_changes_routes.py # /pending-changes page + /api/pending-changes/* endpoints
    external_api_routes.py    # /external/api/* bearer-token endpoints for FW-Analyst integration
wsgi.py                # Entry point; SSL context wiring
policy_db.json         # Network segmentation policy database (gitignored — runtime data)
groups.json            # Group definitions (gitignored — copy from groups.example.json); includes tab and ADOM permissions
app_settings.json      # App feature flags (gitignored — copy from app_settings.example.json)
api_tokens.json        # Hashed bearer tokens (gitignored — copy from api_tokens.example.json)
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
2. **Hygiene Analysis** (below) — select ADOM + package, run 6 checks, filter/export findings (CSV/JSON/PDF).

Backend: `POST /api/hygiene/policies` returns `srcaddr_exp`, `dstaddr_exp`, `service_exp` arrays with `{name, type, members?, detail?}` objects alongside the flat name lists. Also returns `srcintf`/`dstintf`.

### Device Review tab

`GET /device-review` → `device_review.html` + `device_review.js`

Runs configurable security checks against every device in a selected ADOM. Combines interface-protocol analysis with CIS hardening checks in a single unified results table.

**Workflow:**
1. Select ADOM → device list loads automatically.
2. Choose which checks to run (all checked by default).
3. For parameterised CIS checks, a **Check Parameters** panel appears — enter expected IPs before running.
4. Click **Run Analysis** — a per-device progress loop fires, findings appear in a filterable, paginated table.
5. Export results as CSV, JSON, or PDF.

**Result values:**
- `INSECURE` — red: cleartext protocols (HTTP, Telnet) are enabled
- `FAIL` — red: CIS check failed (server missing, sync disabled, etc.)
- `WARN` — yellow: no secure management alternative present
- `CONFIG_MISSING` — yellow: CIS check ran but no expected values were supplied; device value shown for information
- `PASS` — green: CIS check passed
- `INFO` — blue: informational finding (e.g. PING enabled)

**Implemented checks (18 total):**

| Key | Name | CIS Level | data_keys | Parameterised |
|-----|------|-----------|-----------|---------------|
| `interface_protocols` | Interface Protocols | — | `interfaces` | No |
| `ntp_config` | NTP Configuration | L1 | `ntp` | Yes (expected IPs) |
| `syslog_config` | Syslog Configuration | L1 | `syslog` | Yes (expected IPs) |
| `trusted_hosts` | Trusted Hosts on Admin Accounts | L1 | `admins` | No |
| `default_admin` | Default 'admin' Account | L1 | `admins` | No |
| `idle_timeout` | Admin Idle Timeout | L1 | `system_global` | Yes (max minutes) |
| `lockout_threshold` | Admin Lockout Threshold | L1 | `system_global` | Yes (max attempts) |
| `password_length` | Password Minimum Length | L1 | `password_policy` | Yes (min chars) |
| `log_disk` | Local Disk Logging | L1 | `log_disk` | No |
| `log_severity` | Log Severity Level | L1 | `log_disk` | Yes (max severity) |
| `log_faz` | FortiAnalyzer Logging | L1 | `log_faz` | Yes (expected FAZ IP) |
| `dns_servers` | DNS Servers | L1 | `dns` | Yes (expected IPs) |
| `snmp_version` | SNMP Version Enforcement | L1 | `snmp_community`, `snmp_sysinfo` | No |
| `snmp_readonly` | SNMP Read-Only | L2 | `snmp_users` | No |
| `tls_version` | Minimum TLS Version | L1 | `system_global` | Yes (min TLS) |
| `ssh_ciphers` | SSH Strong Ciphers | L2 | `system_global` | No |
| `firmware_version` | Firmware Version Compliance | L1 | `device_meta` | Yes (min version) |
| `ha_sync` | HA Sync Status | L2 | `ha_status` | No |

Note: `system_global` is fetched once and shared by `idle_timeout`, `lockout_threshold`, `tls_version`, and `ssh_ciphers`. `admins` is shared by `trusted_hosts` and `default_admin`. `log_disk` is shared by `log_disk` and `log_severity`. `device_meta` is populated from the device list (no extra API call).

**Check engine — `app/device_review.py`:**

The check registry (`CHECKS` list) is the single place to add new checks. Each entry is:

```python
{
    "key":          "my_check",           # unique ID used in API + JS
    "name":         "Display Name",       # shown in UI checkbox list
    "description":  "One-line summary",   # tooltip
    "data_keys":    ["interfaces"],       # which device data blobs to fetch
                                          # see implemented data_keys above
    "params_schema": [],                  # [] = binary check, no user input
                                          # or list of input descriptors:
                                          # [{"key","label","type","placeholder","required"}]
    "run":          _my_check_function,   # callable(device_name, device_data, params) -> list[Row]
}
```

`device_data` is a dict populated by the route from the `data_keys` list — only the keys needed by selected checks are fetched per device. `params` is the user-supplied values for that check (empty dict for binary checks).

A `Row` dict must contain: `device`, `interface` (or `"system"` for device-level checks), `vdom`, `ip`, `type` (or `"system"`), `status`, `check`, `result`, `detail`, `protocols`, `has_insecure`, `has_secure`.

`CHECKS_META` (serialisable — no `run` key) is passed to both the page template and the frontend as `CHECK_DEFS`, driving the params panel UI dynamically.

**API endpoints:**
- `GET  /api/device-review/adoms/<adom>/devices` — list devices in an ADOM
- `POST /api/device-review/run/device` — body: `{ adom, device, checks, check_params }` — single device (used by progress loop)
- `POST /api/device-review/run` — body: `{ adom, devices, checks, check_params }` — bulk run; `devices: []` means all, `checks` absent means all, `check_params` maps check key → param dict

**Adding a new CIS check (binary example):**
1. Add a proxy method to `fmg_client.py` if new device data is needed.
2. Add a fetch branch in `_fetch_device_data()` in `device_review_routes.py` for the new `data_key`.
3. Write `_run_my_check(device_name, device_data, params) -> list[Row]` in `device_review.py`.
4. Append an entry to `CHECKS` with the appropriate `data_keys` and empty `params_schema`.
No template or frontend JS changes are needed for binary checks.

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

Zone evaluation logic: block all > block only (service match) > allow only (service match) > allow all > implicit UNKNOWN. Zone hierarchy is supported via `parents[]` and zone name expansion.

**Access types:**
- `allow all` — permits all traffic between zones regardless of service
- `allow only` — permits traffic only if the requested service matches the policy's service list; non-matching services fall through to later rules (allowlist semantics)
- `block all` — denies all traffic between zones regardless of service
- `block only` — denies traffic only if the requested service matches the policy's service list (denylist semantics)

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

### Map tab (Beta)

`GET /map` → `map.html` + `map.js`

Interactive Leaflet map displaying all managed devices in selected ADOMs. Device markers color-coded by health status (green/yellow/red/offline). Backend: `app/map_cache.py` maintains in-memory device cache with periodic refresh from FortiManager; `app/map_regions.py` provides regional grouping. Routes in `app/routes/map_routes.py`:
- `GET /map` — page (tab_required)
- `GET /api/map/devices` — device list with coordinates (filtered by ADOM access)

#### Map → Firewalls deep-link

`map.html` injects `window._canSeeFirewalls = {{ ('firewalls' in allowed_tabs) | tojson }}` before `map.js` loads. When `true`, each device popup includes a **View Details →** anchor linking to `/firewalls?device=<encodeURIComponent(device.name)>&adom=<encodeURIComponent(device.adom)>`. `firewalls.js` reads these params in `checkDeepLink()` at page load, pre-fills `#searchInput`, calls `doSearch()`, then auto-clicks the matching `[data-device]` button to open the detail modal. The URL is cleaned with `history.replaceState()` immediately after reading params.

#### Health status ledger

`#mapHealthLedger` is a `position:fixed` overlay (bottom-right, `z-index:1000`) populated by `updateHealthLedger()` in `map.js`. It counts `.status` values from the `allDevices` array and displays four `.ledger-item` spans using `.status-dot` color classes (`green`, `yellow`, `red`, `offline`). Called once from `loadDevices()` after `renderMarkers()`. Fleet-wide counts — not affected by ADOM filter.

New CSS classes added to `style.css`: `.map-health-ledger`, `.ledger-item`, `.map-popup-footer`, `.map-popup-details-link`.

### DIFF tab (Beta)

`GET /pending-changes` → `pending_changes.html` + `pending_changes.js`

Shows FortiManager install-preview diffs per device. All operations are read-only — the tab triggers FMG's install-preview workflow but never pushes any configuration to devices.

**Workflow:**
1. Select ADOM → device table loads with sync status for every device (parallelised, 10-worker thread pool).
2. Optionally filter by name/IP, or check **Pending only** to show only devices with outstanding changes.
3. Click a device row → diff panel fetches and renders the per-VDOM CLI diff.
4. Click **+ Add to Export Queue** to stage the diff for bulk export.
5. Export the queue as CSV, JSON, or PDF.

**Status fields per device:**

| Field | Values | Meaning |
|---|---|---|
| `conf_status` | `insync` / `outofsync` | Device config vs. FMG database |
| `db_status` | `modified` / `nochange` | FMG database has changes not yet installed |
| `pkg_status` | `modified` / `nochange` | Policy package modified but not yet installed |

Table rows show a single compact badge (highest-priority state). The diff panel header shows all three badges simultaneously.

**Diff parsing:** `parse_preview_diff()` in `app/fmg_client.py` chains two FMG JSON-RPC calls — trigger (`_exec` on `/securityconsole/install/package`) then poll (`/task/taskid`) — to obtain the raw CLI diff text. It parses each line into `{type: "add"|"remove"|"modify", line: str}` objects grouped by VDOM.

**Export queue:** Multiple devices can be staged before exporting. Changing ADOM clears the queue with a confirmation prompt. Each export includes a metadata header (ADOM, device list, timestamp, username via `PC_USER` template global).

**Routes in `app/routes/pending_changes_routes.py`:**
- `GET /pending-changes` — page (tab_required)
- `GET /api/pending-changes/adoms` — ADOM list (forti-prefix filtered, ADOM-access filtered)
- `GET /api/pending-changes/adoms/<adom>/devices` — device list with status fields
- `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` — trigger + return parsed diff

### External API

`app/routes/external_api_routes.py` — blueprint at `/external/api/`

Provides read-only zone policy access to external programs (e.g. FW-Analyst) via bearer token authentication. No browser session is required.

**Feature gate:** The external API is disabled by default. Enable it in **Admin → External API** — this writes `{"external_api_enabled": true}` to `app_settings.json`. Disabling it returns 503 on all `/external/api/` requests without touching token records.

**Authentication:** Every request must include `Authorization: Bearer <token>`. Tokens are created in Admin → External API → New Token. Plaintext is shown once; only the SHA-256 hash is stored in `api_tokens.json`.

**Endpoints (all read-only):**
- `POST /external/api/zone/query` — same payload/response as internal `/api/zone/query`
- `GET  /external/api/zone/zones` — zone list
- `GET  /external/api/zone/policies` — policy list

**CSRF:** `/external/api/` requests are exempt from CSRF validation (bearer token is the auth mechanism, no session cookie exists).

**Supporting modules:**
- `app/app_settings.py` — atomic read/write of `app_settings.json` (feature flags)
- `app/api_tokens.py` — token create/list/revoke/validate; tokens stored as SHA-256 hashes

**Admin endpoints added to `admin_routes.py`:**
- `GET/PUT /admin/api/settings` — get/set `external_api_enabled`
- `GET /admin/api/tokens` — list tokens
- `POST /admin/api/tokens` — create token (returns plaintext once)
- `DELETE /admin/api/tokens/<id>` — revoke token

## Dependency management

This project uses `uv`. `uv.lock` is committed; `pyproject.toml` should be too. Do not use `pip install` directly — use `uv add <package>` to keep the lockfile in sync.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
