# 4THealth — Network Operations Dashboard

A read-only web dashboard for monitoring FortiManager, FortiAnalyzer, FortiAuthenticator,
and managed FortiGate firewalls. All connectivity goes **through FortiManager's
JSON-RPC API** — no direct FortiGate connections are made.

---

## Features

| Page | What it shows |
|---|---|
| **Dashboard** | Infrastructure health cards for all devices defined in `infra_targets.json` (FortiManager, FortiAnalyzer, FortiCollector, FortiAuthenticator, etc.) — hostname, version, serial, HA mode/role, CPU %, memory %, disk |
| **Managed Network Summary** | Stat bar at the top of the Dashboard — total managed firewalls and total policy rules. Calculated by a background job at startup and refreshed nightly. |
| **Firewalls** | Per-ADOM device list with green/yellow/red health dot, paginated table (10/25/50/100), full-text search by name or IP |
| **Device Detail** | Modal pop-up — system info, CPU/memory, interfaces, IPv4 routing table with filter+pagination, BGP/OSPF neighbors, IPsec tunnels |
| **Device Versions** | Per-ADOM version distribution chart — clickable bars filter the device list; 10/20/50 pagination; CSV and JSON export |
| **Rule Review** | Policy viewer (full rule table with search, pagination, and exports) plus automated hygiene checks — select ADOM + package, browse all rules or run hygiene checks, export as CSV / JSON / PDF |
| **Rule Validation** | Pre-change analysis — enter requested flows (src IP, dst IP, port), select policy packages, and get per-flow verdicts: PERMITTED, EXPLICITLY_DENIED, MODIFIABLE, or NEW_RULE_NEEDED. Integrates with the zone-script segmentation policy tool for zone-level verdicts and checks whether each firewall is actually in the traffic path. |
| **Map (Beta)** | Interactive geographic map of all managed FortiGate devices. Each ADOM gets a distinct colour; devices cluster at zoom-out and split to individual pins at city level. Click any pin for device details. Location data is cached at startup and refreshed daily. |
| **Admin** | *(admin role only)* Group management, tab-level permissions, and application log viewer |
| **Auto-refresh** | Configurable: manual, 1 min, 5 min (default), 10 min, 15 min |
| **Light / Dark mode** | Toggle in the nav bar; preference saved in `localStorage` |
| **Contextual Help** | In-app help panel (? button in nav bar) — 5 tabbed sections covering Overview, Dashboard, Firewalls, Versions, and FAQ |

---

## Architecture

```
fortigate-health/
├── app/
│   ├── __init__.py              Flask application factory (also starts background scheduler)
│   ├── config.py                Settings loaded from .env
│   ├── auth.py                  bcrypt local auth + AD/LDAP (see production.md)
│   ├── app_logger.py            In-memory ring-buffer logger (TRACE/DEBUG/INFO/WARN/ERROR)
│   ├── groups.py                Group CRUD + tab-permission registry
│   ├── fmg_client.py            FortiManager JSON-RPC client
│   ├── hygiene.py               Rule hygiene check engine (7 checks, read-only)
│   ├── summary_job.py           Background job: firewall + rule counts, nightly scheduler
│   ├── map_cache.py             Background cache: device lat/lon for all ADOMs, refreshed daily
│   ├── rule_review.py           Rule Validation analysis engine (flow/policy matching, zone API, path check)
│   ├── routes/
│   │   ├── auth_routes.py       /login  /logout
│   │   ├── dashboard_routes.py  /  /firewalls  /versions
│   │   ├── api_routes.py        /api/*  (JSON — all data endpoints)
│   │   ├── admin_routes.py      /admin  /admin/api/*  (admin only)
│   │   ├── hygiene_routes.py    /hygiene  /api/hygiene/*
│   │   ├── rule_review_routes.py /rule-review  /api/rule-review/*
│   │   └── map_routes.py         /map  /api/map/*
│   ├── templates/
│   │   ├── base.html            Nav bar, theme toggle, layout shell
│   │   ├── login.html           Login page
│   │   ├── dashboard.html       Infrastructure health cards + managed network summary bar
│   │   ├── firewalls.html       Firewall browser + detail modal
│   │   ├── versions.html        Device version distribution report
│   │   ├── hygiene.html         Rule Review — policy viewer + hygiene analysis
│   │   ├── rule_review.html     Rule Validation — flow entry, package selector, results cards
│   │   └── admin.html           Groups/permissions + log viewer
│   └── static/
│       ├── css/style.css        CSS custom properties — light & dark themes
│       ├── vendor/
│       │   ├── leaflet/         Leaflet 1.9.4 JS + CSS (bundled — no CDN needed)
│       │   ├── markercluster/   Leaflet.markercluster 1.5.3 (bundled)
│       │   └── us-states.json   US state boundaries GeoJSON for region colour lookup
│       └── js/
│           ├── dashboard.js     Infrastructure card rendering + summary bar polling
│           ├── firewalls.js     Device table, detail modal, route widget
│           ├── versions.js      Version chart, filterable table, CSV/JSON export
│           ├── hygiene.js       Policy viewer + hygiene analysis, paginated results, CSV/JSON/PDF export
│           ├── rule_review.js   Rule Validation — flow table, analysis request, card rendering
│           ├── map.js           Device location map — Leaflet + MarkerCluster + ADOM filter
│           ├── admin.js         Group editor + log viewer
│           └── help.js          Contextual in-app help panel
├── wsgi.py                      WSGI entry point (supports SSL + gunicorn)
├── manage_users.py              CLI: add / delete / list users / generate secret key
├── groups.json                  Group definitions (gitignored — copy from groups.example.json)
├── groups.example.json          Template for groups.json — copy and edit
├── infra_targets.json           Infrastructure dashboard host list (gitignored — copy from example)
├── infra_targets.example.json   Template for infra_targets.json — copy and edit
├── pyproject.toml               Project metadata + dependencies (uv)
├── requirements.txt             Pip-compatible fallback
├── .env.example                 Template — copy to .env and fill in values
└── production.md                Full production deployment guide (Linux + AD)
```

---

## Developer Documentation

A dedicated developer guide (HTML format) is available at [`developer-guide.html`](developer-guide.html).
It covers application architecture, data flow, authentication modes (local and Active Directory),
all API endpoints, and a step-by-step contributor onboarding checklist for both development
and production environments.

Production security hardening handoff is documented in [`SECURITY_PRODUCTION_HANDOFF.md`](SECURITY_PRODUCTION_HANDOFF.md).

---

## Quick Start (macOS / local development — using uv)

[uv](https://docs.astral.sh/uv/) is the recommended tool. Install once:

```bash
brew install uv
```

Then from the `fortigate-health` directory:

```bash
# 1. Install all dependencies into an isolated .venv
uv sync

# 2. Copy and configure the environment file
cp .env.example .env
# Edit .env: set SECRET_KEY, FMG_PRIMARY_HOST, and either FMG_API_TOKEN or FMG_USERNAME+FMG_PASSWORD

# 3. Copy and configure the group definitions
cp groups.example.json groups.json
# Edit groups.json: rename groups, set tab permissions, and add members as needed

# 4. Copy and configure the infrastructure dashboard targets
cp infra_targets.example.json infra_targets.json
# Edit infra_targets.json: set the correct IPs for each device
# Add or remove entries as needed — one JSON object per device

# 5. Generate a strong SECRET_KEY
uv run python manage_users.py secret
# Copy the output into .env as SECRET_KEY=...

# 6. Create the first local user account
uv run python manage_users.py add admin --role admin
# You will be prompted for a password

# 7. Start the development server
uv run python wsgi.py
# Browse to http://localhost:5000
```

> `uv sync` reads `pyproject.toml`, creates `.venv` automatically, and writes
> `uv.lock`. No manual venv activation needed — prefix all commands with `uv run`.

### Optional: Enable HTTPS locally

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -days 3650 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

uv run python wsgi.py
# Now listens on https://localhost:5443
```

The cert and key files are git-ignored by the existing `*.pem` rule.

---

## User Management

```bash
# Add a user (prompts for password)
uv run python manage_users.py add <username> --role admin|viewer

# List all users
uv run python manage_users.py list

# Remove a user
uv run python manage_users.py delete <username>

# Generate a new SECRET_KEY value
uv run python manage_users.py secret
```

Passwords are stored as **bcrypt hashes** in `users.json` (git-ignored).

For new environments, start with `users.example.json` and then create runtime users with
`uv run python manage_users.py add ...`.

Roles:
- `admin` — full access to all tabs, the Admin page, and raw/debug API endpoints
- `viewer` — access is restricted to the tabs their groups permit

> In production with Active Directory enabled (`AD_ENABLED=true`), the `manage_users.py`
> user accounts serve only as emergency local fallback. AD users do not need entries
> in `users.json`. See `production.md → Phase 4`.

---

## Groups & Tab Permissions

Groups are managed entirely through the **Admin → Groups & Permissions** UI.
Group definitions are stored in `groups.json` (gitignored — copy from `groups.example.json` to get started).

### How it works

1. An admin creates a group (e.g. `NOC-Team`).
2. The admin selects which **navigation tabs** the group can see (Dashboard, Firewalls, Device Versions — and any tabs added in the future).
3. The admin adds **viewer accounts** as members.
4. On next login, each member's session reflects the union of allowed tabs across all groups they belong to.

**Admins always have full access** regardless of group membership.

### Registering a new tab

When you add a new page to the application, register its tab key in `app/groups.py`:

```python
KNOWN_TABS: dict[str, str] = {
    "dashboard":  "Dashboard",
    "firewalls":  "Firewalls",
    "versions":   "Device Versions",
    "my_new_tab": "My New Tab",   # ← add your tab here
}
```

The new tab key will appear immediately in the Admin group-editor checklist.
Protect the new route with `@tab_required("my_new_tab")` in `dashboard_routes.py`.

### Active Directory migration

When AD authentication is enabled (see `production.md`), AD group membership replaces
the `users.json` member lists. The tab-permission store in `groups.json` remains the
same — group names just need to match the AD group names (or the mapped role strings).
See `production.md → Phase 4` for the migration checklist.

> **Important:** when AD is enabled, the Admin UI member pickers show local users only.
> AD-sourced members are not listed there — membership is resolved dynamically at login
> from the user's `memberOf` attribute in Active Directory.

---

## Application Logging

The **Admin → Application Logs** tab provides a live view of the in-memory log buffer.

Log levels (lowest → highest verbosity, matching Terraform's `TF_LOG` convention):

| Level | When to use |
|---|---|
| `ERROR` | Unhandled exceptions, authentication failures |
| `WARN` | Failed login attempts, unexpected API responses |
| `INFO` | Login/logout events, group changes *(default)* |
| `DEBUG` | Admin page access, API round-trips |
| `TRACE` | Detailed per-request data for deep troubleshooting |

- The active level filters **what gets written** to the buffer (not just what is displayed).
  Setting `DEBUG` means DEBUG and above are captured; TRACE events are still dropped.
- The buffer holds up to **2 000 entries** and is reset on process restart.
- Use the **filter** controls to narrow by level threshold or component (`auth`, `admin`, etc.).
- The **Set** button changes the active capture level at runtime — no restart needed.

---

## Configuration Reference (`.env`)

Copy `.env.example` to `.env` and fill in your values. The file is git-ignored — never commit it.

### Core

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key — generate with `manage_users.py secret` |
| `COOKIE_SECURE` | `auto` | `true` behind HTTPS, `false` for HTTP, `auto` detects cert presence |
| `PORT` | `5000` / `5443` | Listening port (auto-selects 5443 when cert is present) |
| `SSL_CERT` | `certs/cert.pem` | Path to TLS certificate |
| `SSL_KEY` | `certs/key.pem` | Path to TLS private key |

### FortiManager / Infrastructure

| Variable | Default | Description |
|---|---|---|
| `FMG_PRIMARY_HOST` | *(required)* | FortiManager primary — used for ADOM, device, and policy queries |
| `FMG_API_TOKEN` | — | Bearer token (preferred) — generate on FMG under System Settings → Administrators → API token |
| `FMG_USERNAME` | — | API account username (fallback when no token is set) |
| `FMG_PASSWORD` | — | API account password (fallback when no token is set) |
| `FMG_VERIFY_SSL` | `false` | Set `true` to validate the FMG TLS certificate |
| `FMG_TIMEOUT` | `30` | API request timeout in seconds |

### Infrastructure Dashboard Targets (`infra_targets.json`)

Infrastructure health cards are driven by `infra_targets.json` (gitignored — copy from `infra_targets.example.json`). Each entry is one JSON object:

```json
{ "label": "Display Name", "host": "10.0.0.1", "type": "FortiManager" }
```

Valid `type` values: `FortiManager`, `FortiAnalyzer`, `FortiCollector`, `FortiAuthenticator` — or any string you choose for the badge label.

To add a new device, append an entry to the array and restart the app. No code changes are needed.

#### Per-device bearer tokens

Each Fortinet appliance type (FMG, FAZ, FortiCollector, FortiAuthenticator) generates its own API token independently. Add an optional `"token"` field to any entry to use that device's specific token:

```json
[
  { "label": "FortiManager Primary",  "host": "10.0.0.1", "type": "FortiManager",  "token": "fmg-primary-token" },
  { "label": "FortiAnalyzer Primary", "host": "10.0.0.3", "type": "FortiAnalyzer", "token": "faz-primary-token" },
  { "label": "FortiCollector #1",     "host": "10.0.0.5", "type": "FortiCollector" }
]
```

Token priority per device (first match wins):
1. `"token"` field in the `infra_targets.json` entry
2. `FMG_API_TOKEN` in `.env` (global fallback)
3. `FMG_USERNAME` / `FMG_PASSWORD` in `.env` (last resort)

### Zone-Script Segmentation Policy Integration (Rule Validation tab)

| Variable | Default | Description |
|---|---|---|
| `ZONE_SCRIPT_URL` | — | Base URL of the zone-script API, e.g. `https://nspolicy.yourdomain.internal`. Leave blank to fall back to importing `query_flow.py` directly from `../zone-script` on disk. |
| `ZONE_SCRIPT_USERNAME` | — | HTTP Basic Auth username for the zone-script `POST /api/query` endpoint |
| `ZONE_SCRIPT_PASSWORD` | — | HTTP Basic Auth password for the zone-script `POST /api/query` endpoint |
| `ZONE_SCRIPT_VERIFY_SSL` | `false` | Set `true` to validate the zone-script TLS certificate |

Recommendation: create a dedicated read-only service account on zone-script (e.g. `4thealth-svc`) and restrict its source IP to the 4THealth server. Users authenticate to 4THealth separately — these credentials are for machine-to-machine API access only.

### Health Thresholds

| Variable | Default | Description |
|---|---|---|
| `CPU_WARN` / `CPU_CRIT` | `70` / `90` | CPU % thresholds for yellow / red |
| `MEM_WARN` / `MEM_CRIT` | `75` / `90` | Memory % thresholds for yellow / red |

### Managed Network Summary Schedule

| Variable | Default | Description |
|---|---|---|
| `SUMMARY_REFRESH_HOUR` | `1` | Hour (0–23, server local time) the nightly recalculation fires |
| `SUMMARY_REFRESH_MINUTE` | `0` | Minute within that hour (default: 01:00 local time) |

### Map (Beta) Cache

| Variable | Default | Description |
|---|---|---|
| `MAP_CACHE_INTERVAL_HOURS` | `24` | How often to re-fetch device lat/lon from FortiManager (once per day is sufficient — coordinates rarely change) |

### Active Directory (optional — leave unset for local-only auth)

| Variable | Default | Description |
|---|---|---|
| `AD_ENABLED` | `false` | Set `true` to enable Active Directory authentication |
| `AD_SERVER` | — | LDAP server URI, e.g. `ldaps://dc.yourdomain.com:636` |
| `AD_DOMAIN` | — | NetBIOS domain name |
| `AD_BASE_DN` | — | `DC=yourdomain,DC=com` |
| `AD_BIND_USER` | — | Full DN of the LDAP service account |
| `AD_BIND_PASSWORD` | — | Service account password |
| `AD_USER_SEARCH` | — | OU to search for users |
| `AD_GROUP_ADMIN` | — | Full DN of the AD group that maps to the `admin` role |
| `AD_GROUP_VIEWER` | — | Full DN of the AD group that maps to the `viewer` role |
| `AD_VERIFY_SSL` | `false` | Set `true` to validate the domain controller TLS cert |

---

## API Endpoints

All endpoints require an authenticated session (HTTP 401 otherwise).
`*` = admin role required.

| Method | Path | Description |
|---|---|---|
| GET | `/api/infrastructure` | Health data for all devices defined in `infra_targets.json` |
| GET | `/api/infrastructure/raw` * | Raw FMG responses — for debugging field names |
| GET | `/api/summary` | Managed network summary (firewalls total, rules total) — served from in-memory cache, instant response |
| POST | `/api/summary/refresh` * | *(admin only)* Trigger an immediate background recalculation |
| GET | `/api/adoms` | List all ADOMs |
| GET | `/api/adoms/<adom>/devices` | List all devices in an ADOM |
| GET | `/api/adoms/<adom>/devices/<name>/health` | Full live health for a device |
| GET | `/api/adoms/<adom>/devices/<name>/raw` * | Raw proxy payloads per health endpoint |
| GET | `/api/search?q=<query>` | Search all ADOMs by device name or IP |
| GET | `/api/hygiene/adoms/<adom>/packages` | List policy packages in an ADOM |
| POST | `/api/hygiene/run` | Run selected hygiene checks against a package |
| GET | `/api/rule-review/adoms` | List ADOMs (for Rule Validation package selector) |
| GET | `/api/rule-review/adoms/<adom>/packages` | List policy packages in an ADOM (Rule Validation) |
| POST | `/api/rule-review/parse-import` | Parse an uploaded CSV or XLSX file into flow rows |
| GET | `/api/rule-review/zone-status` | Check whether zone-script API is reachable |
| POST | `/api/rule-review/analyze` | Analyze requested flows against selected policy packages |
| GET | `/api/map/devices` | Cached device list with lat/lon (filtered to user's allowed ADOMs) |
| GET | `/api/map/status` | Lightweight cache status poll (status, last_updated, device_count, per-ADOM progress) |
| POST | `/api/map/refresh` * | *(admin only)* Trigger an immediate background cache refresh |
| GET | `/admin/api/groups` * | List all groups |
| POST | `/admin/api/groups` * | Create a group |
| PUT | `/admin/api/groups/<name>` * | Update a group's members and tab permissions |
| DELETE | `/admin/api/groups/<name>` * | Delete a group |
| GET | `/admin/api/users` * | List all local users (for member picker) |
| GET | `/admin/api/tabs` * | List registered tab keys and display names |
| GET | `/admin/api/logs` * | Fetch log entries (filter by level / component) |
| POST | `/admin/api/logs/level` * | Change active log capture level at runtime |
| DELETE | `/admin/api/logs` * | Clear the in-memory log buffer |

---

## Managed Network Summary

The **summary bar** at the top of the Dashboard gives leadership and engineering at every level
a quick read on the scale of the managed firewall estate.

| Stat | Source | Meaning |
|---|---|---|
| **Managed Firewalls** | `dvmdb` device count per ADOM | Total FortiGate devices registered across all ADOMs that have at least one device |
| **Policy Rules Managed** | Policy package enumeration | Sum of all firewall policy entries across every package in every ADOM with devices |

### How it works

The data is **never calculated on page load** — that would add several minutes of latency.
Instead, a background job runs in a dedicated thread:

1. **On app startup** — the job fires automatically, runs in the background, and stores results in memory. The dashboard shows animated spinners for the ~4–5 minutes the first calculation takes, then the numbers appear.
2. **Nightly at 01:00** (configurable) — APScheduler fires a fresh calculation. Results are stored back in memory and the `last_updated` timestamp is updated. Any user who opens the dashboard after that sees the new numbers immediately.
3. **On demand (admin only)** — a `POST /api/summary/refresh` call kicks off an immediate recalculation without restarting the app. Useful after a large change window.

Because results are held in memory, they survive across page refreshes and between different users' sessions — but are reset if the process restarts (e.g. after a deployment). The startup run re-populates them automatically.

### Why it takes several minutes to calculate

FortiManager doesn't expose a single "total rule count" API. The job must:

1. Enumerate all ADOMs (~24 on the tested FMG instance)
2. Skip ADOMs with no managed devices (20 of the 24 are empty system ADOMs)
3. For each ADOM with devices, enumerate every policy package
4. Fetch `policyid` for each package (lightweight — only the ID field is requested)
5. Sum all counts

On the tested production FMG with ~135 packages and ~14,700 rules, this takes roughly 4–5 minutes. The nightly schedule means that cost is paid once a day at a quiet time.

### Schedule configuration

Add to `.env` to change the nightly refresh time:

```dotenv
SUMMARY_REFRESH_HOUR=1    # 0–23, server local time (default: 1 = 01:00)
SUMMARY_REFRESH_MINUTE=0  # 0–59 (default: 0)
```

---

## Rule Review

The **Rule Review** tab provides two sections on a single page: a full **Policy Rules** viewer at the top and a **Hygiene Analysis** panel below. All analysis is read-only — nothing is written back to FortiManager or any device.

### Policy Rules

1. Select an **ADOM** from the drop-down.
2. Select a **Policy Package** — the full rule table loads automatically.
3. Search using the full-text search box (supports regex). Optionally scope the search to a single field (Name, Comment, Source, Destination, etc.).
4. Click any address group or service group triangle to expand its members inline.
5. Page through rules using 10 / 25 / 50 / 100 per-page and `«« « 1 2 3 … » »»` pagination.
6. Export as **CSV**, **JSON**, or **PDF** — each includes a filter context header.

### Hygiene Analysis Workflow

1. Select an **ADOM** and **Policy Package** (independent from the Policy Rules selectors above).
2. Tick the **checks** you want to run (all are selected by default).
3. Click **Run Analysis**.
4. Page through findings using the standard 10 / 25 / 50 / 100 per-page control and `«« « … » »»` pagination.
5. Filter by free text or by check category.
6. Export the filtered results as **CSV**, **JSON**, or **PDF** (browser print dialog).

### Available Checks

| Check key | Display name | What it finds |
|---|---|---|
| `unnamed` | Unnamed Rules | Rules with no name and/or no comment |
| `unlogged` | Unlogged Rules | Rules where `logtraffic` is disabled or not set |
| `shadow` | Shadow Rules | Enabled rules that are completely unreachable because a broader `src=any / dst=any / svc=any` rule appears above them |
| `disabled` | Disabled / Inactive Rules | Rules whose `status` field is `disable` |
| `expired` | Expired Rules | Rules referencing a time-based schedule whose end-date has passed; named schedule references are flagged for manual review |
| `unhit` | Unused / Un-Hit Rules | Rules where the hit counter is 0 (only reported when FMG includes the counter in the policy config record) |
| `no_deny_all` | Missing Deny-All Default | Package-level finding when no enabled `src=any / dst=any / svc=any / action=deny` rule exists |

### Export formats

| Format | Contents |
|---|---|
| CSV | Seq, Policy ID, Policy Name, Check, Detail — UTF-8, comma-separated |
| JSON | Full metadata (ADOM, package, policy count, run timestamp) + all finding objects |
| PDF | Opens a printable HTML page in a new browser tab; use the browser's **Save as PDF** option |

### Tab permissions

`rule_hygiene` is a standard tab key registered in `KNOWN_TABS`.
Grant or revoke access per group in **Admin → Groups & Permissions**, exactly as with
any other tab. The tab displays as **Rule Review** in the navigation bar.

---

## Rule Validation

The **Rule Validation** tab helps engineers validate firewall rule change requests before submitting them. It answers three questions for each requested flow:

1. **Is the traffic already permitted** by an existing policy rule?
2. **Is the traffic blocked** — and can the existing rule be modified, or does a new rule need to be created?
3. **Is the firewall even in the traffic path** between source and destination?

All analysis is read-only. Nothing is written to FortiManager or any device.

### Workflow

1. **Define Flows** — enter one or more source IP / destination IP / port combinations.
   - **Manual entry**: type directly into the form. The Source and Destination fields accept multiple IPs — one per line, or comma-separated. Click **Add** to add all source × destination combinations to the flow table.
   - **Import**: click **Import CSV / XLSX** and upload a spreadsheet. Expected columns: `source`, `destination`, `port` (or `service`), `comment` (optional). Column headers are case-insensitive and several aliases are accepted (e.g. `src`, `dst`, `svc`, `note`).

2. **Select Policy Packages** — pick an ADOM, then a policy package, and click **Add Package**. Repeat for as many packages as needed. Analysis will run every flow against every selected package.

3. Click **Review** to start the analysis.

### Result Cards

Each flow produces one result card, styled with a colored left border:

| Border color | Meaning |
|---|---|
| Green | Flow is PERMITTED by an existing rule |
| Red | Flow is BLOCKED (explicitly denied or no matching rule) |
| Gray | Status is UNKNOWN (policy could not be resolved) |

Each card shows:
- **Verdict** — one of `PERMITTED`, `EXPLICITLY_DENIED`, `MODIFIABLE`, `NEW_RULE_NEEDED`
- **Zone policy section** — if the zone-script integration is configured, the src/dst security zones and the governing segmentation rule are shown. This is the network-level segmentation verdict independent of any specific firewall rule.
- **FortiGate policy section** — the matching or modifiable rules from the selected policy packages, displayed as monospace rule rows.
- **Path analysis** — whether the firewall is in the traffic path between source and destination, based on live routing table and interface data fetched from FortiManager. A "⚠ Not In Path" result means the traffic likely routes through a different device — proceed with caution before adding a rule.
- **FortiOS CLI** — for flows that need a new rule or a modified rule, a FortiOS CLI snippet is generated. All snippets are also collected in the **CLI output panel** at the bottom of the page, with Copy All and Download buttons.

### Verdicts

| Verdict | Meaning |
|---|---|
| `PERMITTED` | An existing enabled rule matches the flow and its action is `accept` |
| `EXPLICITLY_DENIED` | A rule matches and its action is `deny` |
| `MODIFIABLE` | A rule exists but needs adjustment (e.g. service or source/dest expansion) |
| `NEW_RULE_NEEDED` | No matching rule found — a new policy entry must be created |

### CSV / XLSX Import Format

| Column header (aliases accepted) | Description |
|---|---|
| `source` / `src` / `source_ip` | Source IP address or subnet (CIDR) |
| `destination` / `dst` / `dest` / `destination_ip` | Destination IP address or subnet |
| `port` / `ports` / `service` / `services` / `svc` | TCP/UDP port number, port name, or `tcp/8443` style |
| `comment` / `comments` / `note` / `notes` | Free-text reason for the request (optional) |

The first row must be a header row. Column order does not matter.

### Zone Policy Integration

When `ZONE_SCRIPT_URL` is set in `.env`, the Rule Validation engine calls the zone-script API (`POST /api/query`) using HTTP Basic Auth with the configured service account credentials. The zone-script tool maintains a database of network segmentation policies that determine which security zones can communicate — independent of any specific firewall rule.

If `ZONE_SCRIPT_URL` is not set, the engine falls back to importing `query_flow.py` directly from `../zone-script` on disk (development mode).

A zone status badge in the page header shows whether the zone-script API is reachable.

### Path Analysis

For each flow, the engine checks whether the selected firewall is actually between the source and destination by:

1. Fetching the live interface list for each device the policy package is installed on (via FortiManager proxy).
2. Fetching the live IPv4 routing table for each device.
3. Matching the source and destination IPs against interface subnets and routing prefixes using longest-prefix matching.

Confidence levels:
- **High / ✓ In Path** — source and destination resolve to different interfaces on the device.
- **Medium / ⚠ Not In Path** — both IPs resolve to the same interface (same segment), or only one side is reachable. The firewall likely does not see this traffic.
- **Low / ? Path Unknown** — no routing or interface data was available (may be a permissions issue or the device is offline).

### Tab permissions

`rule_review` is a standard tab key. Grant access in **Admin → Groups & Permissions** by editing the relevant group and checking the **Rule Validation** box.

---

## Map (Beta)

The **Map (Beta)** tab renders all managed FortiGate devices on an interactive OpenStreetMap base layer using Leaflet and the MarkerCluster plugin.

### Internet connectivity requirement

The **app server itself requires no internet access** — all JavaScript, CSS, and the US states GeoJSON are bundled under `app/static/vendor/`.

The **user's browser** makes tile requests to `https://{s}.tile.openstreetmap.org` to render the map background. If that domain is blocked by the corporate proxy, the map will show a grey background but device pins, clustering, and popups all continue to work normally. For a fully air-gapped deployment, change the `L.tileLayer(...)` URL in `app/static/js/map.js` to point to a self-hosted tile server.

### How location data is sourced

FortiManager stores a `latitude` and `longitude` for each device in its inventory (`dvmdb`). These can be set manually in **Device Manager → device properties → Location**, or inferred automatically via IP geolocation (`location_from: diag`). Devices where both fields are `0.0` have no location configured and are silently excluded from the map.

### Caching

Location data is fetched from FortiManager at app startup and re-fetched once every 24 hours (configurable via `MAP_CACHE_INTERVAL_HOURS` in `.env`). The cache stores name, ADOM, lat/lon, platform, version, connection status, and description for each device. Because device coordinates rarely change, daily refresh is sufficient; the map loads instantly on every page visit.

| Variable | Default | Description |
|---|---|---|
| `MAP_CACHE_INTERVAL_HOURS` | `24` | How often to re-fetch device locations from FortiManager |

### Map features

| Feature | Detail |
|---|---|
| **Colour by ADOM** | Each ADOM is assigned a distinct colour from a 12-colour palette. Both the legend and the cluster circles use these colours. |
| **Clustering** | Nearby devices merge into a count bubble at low zoom levels. The bubble colour reflects the most common ADOM among clustered devices. |
| **Zoom to expand** | Click any cluster to zoom in. At city level individual pins appear. |
| **Device popup** | Click a pin to see name, ADOM, platform, firmware version, description, connection status, and exact coordinates. |
| **ADOM filter** | Checkboxes above the map let users show/hide devices per ADOM instantly — no server round-trip. |
| **Status bar** | Shows refresh progress (N / total ADOMs — current ADOM) while the cache warms. Disappears when complete. |
| **Refresh button** | Admin-only button triggers an immediate background refresh. Progress is shown in the status bar; the map updates when done. |

### ADOM access control

The `/api/map/devices` endpoint applies the same ADOM filter as all other device endpoints — users in restricted groups only see devices from their allowed ADOMs.

### Tab permissions

`map_view` is a standard tab key. Grant access in **Admin → Groups & Permissions** by editing the relevant group and checking the **Map (Beta)** box.

---

## Security Notes

- All FortiManager calls are **read-only** — only `get` and proxy `monitor`
  endpoints are used. No device configuration is ever changed.
- Passwords are bcrypt-hashed; `users.json` is git-ignored.
- The `.env` file is git-ignored — never commit credentials.
- `groups.json` is git-ignored; copy from `groups.example.json` and customise for your environment.
- Open-redirect protection is enforced on the login `?next=` parameter.
- `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE=Lax`, and automatic
  `SESSION_COOKIE_SECURE` (when TLS is detected) are all set.
- Flask session cookies are cryptographically signed with `SECRET_KEY` and
  cannot be tampered with by clients.
- All `/admin/*` routes enforce the `admin` role server-side — the nav link
  hiding is cosmetic only.

---

## Production Deployment

See **[production.md](production.md)** for the complete step-by-step guide covering:

- Phase 1 — Linux server prerequisites and OS packages
- Phase 2 — Application deployment, systemd service, gunicorn
- Phase 3 — Nginx reverse proxy with TLS termination
- Phase 4 — Active Directory / LDAP authentication with group-to-role mapping
- Phase 5 — Migrating local groups to AD groups
- Phase 6 — Hardening (fail2ban, rate limiting, SELinux, security checklist)
- Phase 7 — Monitoring, updates, certificate renewal, backup

Each phase includes an AI prompt you can paste into Claude or ChatGPT to get
targeted help if you hit an issue.

---

## Extending the Application

Adding a new page follows this pattern:

1. **API data** — add a route to `app/routes/api_routes.py`
2. **Page route** — add a route to `app/routes/dashboard_routes.py`, decorated with `@tab_required("my_tab_key")`
3. **Template** — add `app/templates/<page>.html` extending `base.html`
4. **JavaScript** — add `app/static/js/<page>.js`, reference it in the template's `{% block scripts %}`
5. **Tab registry** — add `"my_tab_key": "Display Name"` to `KNOWN_TABS` in `app/groups.py`

The new tab key will automatically appear in the Admin group-editor checklist.
No build tools, no transpilers — the entire front end is plain HTML/CSS/JavaScript.
