# 4THealth — Network Operations Dashboard

A read-only web dashboard for monitoring FortiManager, FortiAnalyzer, FortiAuthenticator,
and managed FortiGate firewalls. All FortiGate data flows **through FortiManager's
JSON-RPC API** — no direct device connections are made.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![FortiManager](https://img.shields.io/badge/FortiManager-7.4.x%20%7C%207.6.x-red)

---

## Table of Contents

- [Requirements & Compatibility](#requirements--compatibility)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start-macos--local-development)
- [User Management](#user-management)
- [Groups & Tab Permissions](#groups--tab-permissions)
- [Application Logging](#application-logging)
- [Configuration Reference](#configuration-reference-env)
- [API Endpoints](#api-endpoints)
- [Managed Network Summary](#managed-network-summary)
- [Rule Review](#rule-review)
- [Device Review](#device-review)
- [Rule Validation](#rule-validation)
- [Zone Policy](#zone-policy)
- [Map (Beta)](#map-beta)
- [Security Notes](#security-notes)
- [Production Deployment](#production-deployment)
- [Extending the Application](#extending-the-application)
- [Contributing](#contributing)
- [License](#license)

---

## Requirements & Compatibility

| Requirement | Version |
|---|---|
| Python | 3.11 or later |
| FortiManager | **7.4.x** or **7.6.x** (tested) |
| Browser | Any modern browser (Chrome, Firefox, Edge, Safari) |
| Docker (optional) | 20.10+ with Compose v2 |

> **FortiManager compatibility note:** The application has been tested against FortiManager
> 7.4.x and 7.6.x. The JSON-RPC API used is stable across both versions. Earlier versions
> may work but are untested.

---

## Features

| Page | What it shows |
|---|---|
| **Dashboard** | Infrastructure health cards for all devices in `infra_targets.json` (FortiManager, FortiAnalyzer, FortiCollector, FortiAuthenticator, etc.) — hostname, version, serial, HA mode/role, CPU %, memory %, disk |
| **Managed Network Summary** | Stat bar at the top of the Dashboard — total managed firewalls and total policy rules, calculated by a background job and refreshed nightly |
| **Firewalls** | Per-ADOM device list with green/yellow/red health indicator, paginated table (10/25/50/100), full-text search by name or IP |
| **Device Detail** | Modal pop-up — system info, CPU/memory, interfaces, IPv4 routing table with filter and pagination, BGP/OSPF neighbors, IPsec tunnels |
| **Device Versions** | Per-ADOM version distribution chart — clickable bars filter the device list; CSV and JSON export |
| **Rule Review** | Policy viewer (full rule table with search, pagination, group expansion, and export) plus seven automated hygiene checks; export findings as CSV, JSON, or PDF |
| **Device Review** | Configurable management-interface security audit — checks for cleartext protocols (HTTP, Telnet), missing secure alternatives, and informational findings; export evidence as CSV, JSON, or PDF |
| **Rule Validation** | Pre-change analysis — enter requested flows (source IP, destination IP, port), select policy packages, and get per-flow verdicts: PERMITTED, EXPLICITLY_DENIED, MODIFIABLE, or NEW_RULE_NEEDED; integrates zone segmentation policy checks and per-device path analysis |
| **Zone Policy** | Self-contained network segmentation policy browser — query flows against the zone policy database, browse zones and rules, validate the schema, and edit the database (admin only); no FortiManager connection required |
| **Map (Beta)** | Interactive geographic map of all managed FortiGate devices, coloured by configurable US geographic region; devices cluster at zoom-out and split to individual pins at city level |
| **Admin** | *(admin only)* Group management, tab-level and ADOM-level permissions, map region configuration, and application log viewer |
| **Auto-refresh** | Configurable: manual, 1 min, 5 min (default), 10 min, 15 min |
| **Light / Dark mode** | Toggle in the nav bar; preference saved in `localStorage` |
| **Contextual Help** | In-app help panel (? button) covering all tabs, admin configuration, and FAQ |

---

## Architecture

```
4thealth/
├── app/
│   ├── __init__.py              Flask application factory; registers blueprints, starts schedulers
│   ├── config.py                Settings loaded from .env
│   ├── auth.py                  Local bcrypt auth + optional RADIUS authentication
│   ├── app_logger.py            In-memory ring-buffer logger (TRACE/DEBUG/INFO/WARN/ERROR)
│   ├── decorators.py            login_required, tab_required, admin_required, check_adom_access
│   ├── registry.py              Tab key registry; maps keys to display names and routes
│   ├── groups.py                Group CRUD, tab-permission checks, ADOM access control
│   ├── fmg_client.py            FortiManager JSON-RPC client (context-manager; auto login/logout)
│   ├── hygiene.py               Rule hygiene check engine (7 checks, read-only)
│   ├── device_review.py         Device Review check engine; add new checks here
│   ├── rule_review.py           Rule Validation — flow/policy matching, path analysis, zone integration
│   ├── zone_db.py               Zone policy DB engine — loads policy_db.json, runs queries, CRUD
│   ├── map_regions.py           Map region config — load/save map_regions.json, state validation
│   ├── map_cache.py             Background cache: device lat/lon for all ADOMs, refreshed daily
│   ├── adom_cache.py            Background cache: ADOM list from FortiManager, refreshed every 30 min
│   ├── summary_job.py           Background job: managed firewall + rule counts, nightly APScheduler
│   ├── routes/
│   │   ├── auth_routes.py            /login  /logout
│   │   ├── dashboard_routes.py       /  /firewalls  /versions
│   │   ├── api_routes.py             /api/*  (JSON data endpoints)
│   │   ├── admin_routes.py           /admin  /admin/api/*  (admin only)
│   │   ├── hygiene_routes.py         /hygiene  /api/hygiene/*
│   │   ├── device_review_routes.py   /device-review  /api/device-review/*
│   │   ├── rule_review_routes.py     /rule-review  /api/rule-review/*
│   │   ├── zone_routes.py            /zone-policy  /api/zone/*
│   │   └── map_routes.py             /map  /api/map/*
│   ├── templates/               Jinja2 templates (one per page, all extend base.html)
│   └── static/
│       ├── css/style.css        CSS custom properties — light & dark themes
│       ├── vendor/
│       │   ├── leaflet/         Leaflet 1.9.4 (bundled — no CDN required)
│       │   ├── markercluster/   Leaflet.markercluster 1.5.3 (bundled)
│       │   └── us-states.json   US state boundary GeoJSON for map region lookup
│       └── js/                  One JS module per page + shared helpers
├── wsgi.py                      WSGI entry point; wires SSL context for Gunicorn
├── manage_users.py              CLI: add / delete / list users / generate SECRET_KEY
├── pyproject.toml               Project metadata and dependencies (uv)
├── .env.example                 Template — copy to .env and fill in values
├── groups.example.json          Template for groups.json (gitignored runtime file)
├── infra_targets.example.json   Template for infra_targets.json (gitignored runtime file)
├── Dockerfile                   Container image definition
├── docker-compose.yml           Single-container stack with bind-mounted runtime data
└── production.md                Full production deployment guide (Linux + optional RADIUS)
```

---

## Quick Start (macOS / local development)

[uv](https://docs.astral.sh/uv/) is the recommended dependency manager. Install once:

```bash
brew install uv
```

Then from the project root:

```bash
# 1. Install all dependencies into an isolated .venv
uv sync

# 2. Copy and configure the environment file
cp .env.example .env
# Edit .env: set SECRET_KEY, FMG_PRIMARY_HOST, and FMG_API_TOKEN
# (or FMG_USERNAME + FMG_PASSWORD as a fallback)

# 3. Copy and configure the group definitions
cp groups.example.json groups.json
# Edit groups.json: rename groups, set tab permissions, add members

# 4. Copy and configure the infrastructure dashboard targets
cp infra_targets.example.json infra_targets.json
# Edit infra_targets.json: set the host IP for each appliance

# 5. Generate a strong SECRET_KEY
uv run python manage_users.py secret
# Paste the output into .env as SECRET_KEY=...

# 6. Create the first local admin account
uv run python manage_users.py add admin --role admin

# 7. Start the development server
uv run python wsgi.py
# Browse to http://localhost:5000
```

> `uv sync` reads `pyproject.toml`, creates `.venv` automatically, and writes
> `uv.lock`. No manual virtualenv activation is needed — prefix commands with `uv run`.

### Optional: HTTPS locally

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout certs/key.pem -out certs/cert.pem \
  -days 3650 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

uv run python wsgi.py
# Listens on https://localhost:5443
```

Cert and key files are covered by the existing `*.pem` gitignore rule.

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

Passwords are stored as **bcrypt hashes** in `users.json` (gitignored).

Roles:
- `admin` — full access to all tabs, the Admin page, and debug API endpoints
- `viewer` — access restricted to the tabs their groups permit

> When RADIUS is enabled (`RADIUS_ENABLED=true`), the `manage_users.py` accounts
> serve as emergency local fallback. RADIUS users do not need entries in `users.json`.
> See `production.md` for the RADIUS configuration guide.

---

## Groups & Tab Permissions

Groups are managed through **Admin → Groups & Permissions**.
Definitions are stored in `groups.json` (gitignored — copy from `groups.example.json`).

### How it works

1. An admin creates a group (e.g. `NOC-Team`).
2. The admin selects which **navigation tabs** the group can see.
3. Optionally, the admin restricts the group to specific **ADOMs**.
4. The admin adds members in one or both ways:
   - **Members** — individual local accounts (users.json).
   - **AD / RADIUS Groups** — one or more AD group names (e.g. `4THealth-NOC`). Any RADIUS user whose `Filter-Id` or `Class` reply attribute matches one of these strings is automatically treated as a member at login. No per-user configuration required for large AD groups.
5. On next login, each member's session reflects the union of allowed tabs across all groups they belong to.

**Admins always have full access** regardless of group membership.

### ADOM access control

Each group has an optional ADOM restriction:

- **Unrestricted (default)** — members see all ADOMs in every tab the group permits.
- **Restricted** — members can only see ADOMs explicitly listed in the group's allowed ADOM list.

When a user belongs to multiple groups and at least one is unrestricted, that user has full ADOM access. Restrictions only apply when *all* of a user's groups have ADOM restriction enabled.

New ADOMs discovered from FortiManager are **never automatically added** to a restricted group's allowed list — an admin must explicitly grant access.

### Registering a new tab

When adding a new page, register its tab key in `app/registry.py`:

```python
registry.register("my_new_tab", "My New Tab", "blueprint.view_function")
```

Protect the route with `@tab_required("my_new_tab")`. The new key appears immediately in the Admin group-editor checklist.

---

## Application Logging

The **Admin → Application Logs** tab shows the in-memory log buffer in real time.

| Level | When used |
|---|---|
| `ERROR` | Unhandled exceptions, authentication failures |
| `WARN` | Failed login attempts, unexpected API responses |
| `INFO` | Login/logout events, group changes *(default)* |
| `DEBUG` | Admin page access, API round-trips |
| `TRACE` | Detailed per-request data for deep troubleshooting |

- The active level controls **what is written** to the buffer (not just what is displayed). Setting `DEBUG` captures DEBUG and above; TRACE events are still dropped.
- The buffer holds up to **2,000 entries** and is reset on process restart.
- Use the level and component filters to narrow results.
- The **Set** button changes the capture level at runtime — no restart required.

---

## Configuration Reference (`.env`)

Copy `.env.example` to `.env` and fill in your values. The file is gitignored — never commit credentials.

### Core

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key — generate with `manage_users.py secret` |
| `COOKIE_SECURE` | `auto` | `true` for HTTPS, `false` for HTTP, `auto` detects cert presence |
| `PORT` | `5000` / `5443` | Listening port (auto-selects 5443 when cert files are present) |
| `SSL_CERT` | `certs/cert.pem` | Path to TLS certificate |
| `SSL_KEY` | `certs/key.pem` | Path to TLS private key |

### FortiManager

| Variable | Default | Description |
|---|---|---|
| `FMG_PRIMARY_HOST` | *(required)* | FortiManager IP or hostname — used for all ADOM, device, and policy queries |
| `FMG_API_TOKEN` | — | Bearer token (preferred) — generate in FMG under System Settings → Administrators |
| `FMG_USERNAME` | — | API account username (fallback when no token is set) |
| `FMG_PASSWORD` | — | API account password (fallback) |
| `FMG_VERIFY_SSL` | `false` | Set `true` to validate the FortiManager TLS certificate |
| `FMG_TIMEOUT` | `30` | API request timeout in seconds |

### Infrastructure Dashboard Targets (`infra_targets.json`)

Health cards on the Dashboard are driven by `infra_targets.json` (gitignored — copy from `infra_targets.example.json`). Each entry is a JSON object:

```json
{ "label": "Display Name", "host": "10.0.0.1", "type": "FortiManager" }
```

Valid `type` values: `FortiManager`, `FortiAnalyzer`, `FortiCollector`, `FortiAuthenticator` — or any string you choose for the badge label. To add a device, append an entry and restart the app.

#### Per-device bearer tokens

Each Fortinet appliance type generates its own API token independently. Use an optional `"token"` field per entry:

```json
[
  { "label": "FortiManager Primary",  "host": "10.0.0.1", "type": "FortiManager",  "token": "fmg-token" },
  { "label": "FortiAnalyzer Primary", "host": "10.0.0.3", "type": "FortiAnalyzer", "token": "faz-token" }
]
```

Token priority (first match wins): per-entry `"token"` → `FMG_API_TOKEN` → `FMG_USERNAME`/`FMG_PASSWORD`.

### Health Thresholds

| Variable | Default | Description |
|---|---|---|
| `CPU_WARN` / `CPU_CRIT` | `70` / `90` | CPU % thresholds for yellow / red |
| `MEM_WARN` / `MEM_CRIT` | `75` / `90` | Memory % thresholds for yellow / red |

### Managed Network Summary Schedule

| Variable | Default | Description |
|---|---|---|
| `SUMMARY_REFRESH_HOUR` | `1` | Hour (0–23, server local time) the nightly recalculation fires |
| `SUMMARY_REFRESH_MINUTE` | `0` | Minute within that hour (default: 01:00) |

### Map Cache

| Variable | Default | Description |
|---|---|---|
| `MAP_CACHE_INTERVAL_HOURS` | `24` | How often to re-fetch device lat/lon from FortiManager |

### RADIUS Authentication (optional)

| Variable | Default | Description |
|---|---|---|
| `RADIUS_ENABLED` | `false` | Set `true` to enable RADIUS authentication |
| `RADIUS_HOST` | — | Primary FAC IP or hostname |
| `RADIUS_PORT` | `1812` | Primary FAC UDP port |
| `RADIUS_HOST_2` | — | Secondary FAC IP or hostname (HA failover — leave blank if unused) |
| `RADIUS_PORT_2` | `1812` | Secondary FAC UDP port |
| `RADIUS_SECRET` | — | Shared secret (same on both FACs) |
| `RADIUS_TIMEOUT` | `10` | Per-server request timeout in seconds |
| `RADIUS_GROUP_ADMIN` | — | `Filter-Id` / `Class` value that maps to the `admin` role |
| `RADIUS_GROUP_VIEWER` | — | `Filter-Id` / `Class` value that maps to the `viewer` role |

---

## API Endpoints

All endpoints require an authenticated session (HTTP 401 otherwise).
`*` = admin role required.

| Method | Path | Description |
|---|---|---|
| GET | `/api/infrastructure` | Health data for all devices in `infra_targets.json` |
| GET | `/api/infrastructure/raw` `*` | Raw FortiManager responses — for debugging field names |
| GET | `/api/summary` | Managed network summary (firewall total, rule total) — served from in-memory cache |
| POST | `/api/summary/refresh` `*` | Trigger an immediate background recalculation |
| GET | `/api/adoms` | List all ADOMs visible to the authenticated user |
| GET | `/api/adoms/<adom>/devices` | List all devices in an ADOM |
| GET | `/api/adoms/<adom>/devices/<name>/health` | Full live health for a device |
| GET | `/api/adoms/<adom>/devices/<name>/raw` `*` | Raw proxy payloads per health endpoint |
| GET | `/api/search?q=<query>` | Search all ADOMs by device name or IP |
| GET | `/api/hygiene/adoms/<adom>/packages` | List policy packages in an ADOM |
| POST | `/api/hygiene/policies` | Fetch policy rules for a package |
| POST | `/api/hygiene/run` | Run selected hygiene checks against a package |
| GET | `/api/device-review/adoms/<adom>/devices` | List devices in an ADOM for the Device Review tab |
| POST | `/api/device-review/run` | Run selected security checks against chosen devices |
| GET | `/api/rule-review/adoms` | List ADOMs for the Rule Validation package selector |
| GET | `/api/rule-review/adoms/<adom>/packages` | List policy packages in an ADOM |
| POST | `/api/rule-review/parse-import` | Parse an uploaded CSV or XLSX file into flow rows |
| GET | `/api/rule-review/zone-status` | Check whether the zone policy integration is reachable |
| POST | `/api/rule-review/analyze` | Analyze flows against selected policy packages |
| POST | `/api/zone/query` | Query flows against the zone policy database |
| GET | `/api/zone/zones` | List all zones |
| GET | `/api/zone/policies` | List all segmentation policies |
| GET | `/api/zone/validate` | Validate the zone policy database schema |
| GET | `/api/map/devices` | Cached device list with lat/lon (filtered to user's allowed ADOMs) |
| GET | `/api/map/regions` | Region definitions (name, states, colour) used by the map |
| GET | `/api/map/status` | Lightweight cache status poll |
| POST | `/api/map/refresh` `*` | Trigger an immediate background map cache refresh |
| GET | `/admin/api/groups` `*` | List all groups |
| POST | `/admin/api/groups` `*` | Create a group |
| PUT | `/admin/api/groups/<name>` `*` | Update a group's members, tabs, and ADOM access |
| DELETE | `/admin/api/groups/<name>` `*` | Delete a group |
| GET | `/admin/api/users` `*` | List local users (for group member picker) |
| GET | `/admin/api/tabs` `*` | List registered tab keys and display names |
| GET | `/admin/api/adoms` `*` | List known ADOMs from the background cache |
| GET | `/admin/api/map-regions` `*` | Get current map region configuration |
| PUT | `/admin/api/map-regions` `*` | Update map region names, state assignments, and colours |
| GET | `/admin/api/logs` `*` | Fetch log entries (filter by level and component) |
| POST | `/admin/api/logs/level` `*` | Change the active log capture level at runtime |
| DELETE | `/admin/api/logs` `*` | Clear the in-memory log buffer |

---

## Managed Network Summary

The **summary bar** at the top of the Dashboard shows the total scale of the managed firewall estate.

| Stat | Source | Meaning |
|---|---|---|
| **Managed Firewalls** | `dvmdb` device count per ADOM | Total FortiGate devices registered across all ADOMs with at least one device |
| **Policy Rules Managed** | Policy package enumeration | Sum of all firewall policy entries across every package in every active ADOM |

### How it works

Data is **never calculated on page load** — that would add several minutes of latency. A background job runs instead:

1. **On app startup** — fires automatically, runs in the background, stores results in memory. The Dashboard shows spinners for the first few minutes while the calculation runs.
2. **Nightly at 01:00** (configurable) — APScheduler triggers a fresh calculation.
3. **On demand (admin only)** — `POST /api/summary/refresh` kicks off an immediate recalculation.

Because results are stored in memory, they are reset on process restart and repopulated automatically by the startup job.

### Why the first calculation takes several minutes

FortiManager has no single "total rule count" API. The job must enumerate every ADOM, skip empty system ADOMs, enumerate every policy package per active ADOM, and fetch policy IDs for each package. On a production instance with ~135 packages and ~14,700 rules this takes roughly 4–5 minutes. The nightly schedule means that cost is paid once a day at a quiet time.

---

## Rule Review

The **Rule Review** tab provides two sections on a single page: a full **Policy Rules** viewer and a **Hygiene Analysis** panel. All analysis is read-only — nothing is written back to FortiManager.

### Policy Rules

1. Select an **ADOM** and **Policy Package** — the full rule table loads automatically.
2. Search using the full-text search box (supports regex). Optionally scope the search to a single field.
3. Click any address group or service group triangle to expand its members inline.
4. Page through rules using 10 / 25 / 50 / 100 per-page pagination.
5. Export as **CSV**, **JSON**, or **PDF** — each export includes a filter context header.

### Hygiene Analysis

1. Select an **ADOM** and **Policy Package** (independent from the viewer selectors above).
2. Choose the checks to run (all enabled by default).
3. Click **Run Analysis**.
4. Filter by text or check category, and export findings as **CSV**, **JSON**, or **PDF**.

### Available Checks

| Check | Display name | What it finds |
|---|---|---|
| `unnamed` | Unnamed Rules | Rules with no name and/or no comment |
| `unlogged` | Unlogged Rules | Rules where `logtraffic` is disabled or not set |
| `shadow` | Shadow Rules | Enabled rules unreachable because a broader any/any/any rule appears above them |
| `disabled` | Disabled / Inactive Rules | Rules whose `status` field is `disable` |
| `expired` | Expired Rules | Rules referencing a time-based schedule whose end-date has passed |
| `unhit` | Unused / Un-Hit Rules | Rules where the hit counter is 0 |
| `no_deny_all` | Missing Deny-All Default | Package-level finding when no deny-all rule exists |

---

## Device Review

The **Device Review** tab runs configurable security checks against the management-plane interfaces of every device in a selected ADOM.

### Workflow

1. Select an ADOM — the device grid loads with all devices selected by default.
2. Filter or deselect devices using the searchable grid.
3. Choose which checks to run (all enabled by default).
4. Click **Run Analysis** — findings appear in a filterable, paginated table.
5. Export results as **CSV**, **JSON**, or **PDF** (PDF includes ADOM, timestamp, and device count — suitable as compliance evidence).

### Severity levels

| Severity | Meaning |
|---|---|
| `INSECURE` | Red — cleartext protocol (HTTP, Telnet) is enabled |
| `WARN` | Yellow — no secure management alternative (HTTPS, SSH) is present |
| `INFO` | Blue — informational finding (e.g. PING enabled) |

### Adding a new check

The check registry in `app/device_review.py` is the single place to add checks:

```python
{
    "key":         "my_check",
    "name":        "Display Name",
    "description": "One-line summary",
    "severity":    "INSECURE|WARN|INFO",
    "run":         _my_check_function,   # callable(device_name, interfaces) -> list[Finding]
}
```

---

## Rule Validation

The **Rule Validation** tab helps engineers validate firewall rule change requests before submitting them. For each requested flow it answers:

1. Is the traffic already permitted by an existing policy?
2. If blocked — can an existing rule be modified, or is a new rule needed?
3. Is the selected firewall actually in the traffic path?

All analysis is read-only.

### Workflow

1. **Define Flows** — enter source IP, destination IP, and port combinations manually, or import a CSV/XLSX file.
2. **Select Policy Packages** — pick an ADOM and package; repeat for multiple packages.
3. Click **Review** to start the analysis.

### Verdicts

| Verdict | Meaning |
|---|---|
| `PERMITTED` | An existing enabled rule matches and its action is `accept` |
| `EXPLICITLY_DENIED` | A rule matches and its action is `deny` |
| `MODIFIABLE` | A rule exists but needs adjustment (e.g. service or address expansion) |
| `NEW_RULE_NEEDED` | No matching rule found — a new policy entry must be created |

### CSV / XLSX Import

| Column (aliases accepted) | Description |
|---|---|
| `source` / `src` | Source IP address or CIDR subnet |
| `destination` / `dst` / `dest` | Destination IP address or CIDR subnet |
| `port` / `service` / `svc` | TCP/UDP port number, port name, or `tcp/8443` style |
| `comment` / `note` | Free-text reason (optional) |

Column order does not matter; headers are case-insensitive.

### Zone Policy Integration

When `ZONE_SCRIPT_URL` is configured, Rule Validation calls the zone policy API to check whether the requested flow is permitted at the network segmentation layer — independent of any specific firewall rule. If zone policy is not configured, the Rule Validation tab degrades gracefully (firewall policy analysis still works).

### Path Analysis

For each flow the engine fetches live routing table and interface data from FortiManager, then checks whether the source and destination IPs resolve to different interfaces on the selected device. A **⚠ Not In Path** result means the traffic likely routes through a different firewall — proceed with caution before adding a rule.

---

## Zone Policy

The **Zone Policy** tab is a self-contained network segmentation policy browser. It reads `policy_db.json` from the project root and requires no FortiManager connection.

### Sub-tabs

| Sub-tab | Description |
|---|---|
| **Query Flow** | Enter source/destination IPs (multi-line or comma-separated) and optional service; get an ALLOWED / BLOCKED / UNKNOWN verdict with the governing rule |
| **Browse** | Zone accordion list (searchable) and full policy table (filterable by access type and severity) |
| **Validate** | Schema validation report — error and warning counts |
| **Edit Database** | *(admin only)* Add/remove/modify zones, subnets, and policy rules; changes are written back to `policy_db.json` atomically |

### Zone evaluation precedence

Block all → block only (service match) → allow all → implicit UNKNOWN.

### policy_db.json format

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

---

## Map (Beta)

The **Map (Beta)** tab renders all managed FortiGate devices on an interactive OpenStreetMap base layer using Leaflet and the MarkerCluster plugin.

### Internet connectivity

The **app server** requires no internet access — all JavaScript, CSS, and the US states GeoJSON are bundled under `app/static/vendor/`.

The **user's browser** makes tile requests to `https://{s}.tile.openstreetmap.org`. If this domain is blocked, the map shows a grey background but pins, clustering, and popups all continue to work. For air-gapped deployments, change the `L.tileLayer(...)` URL in `app/static/js/map.js` to point to a self-hosted tile server.

### How location data is sourced

FortiManager stores a `latitude` and `longitude` for each device in its inventory. These can be set manually in **Device Manager → device properties → Location**, or inferred automatically via IP geolocation (`location_from: diag`). Devices where both fields are `0.0` are silently excluded from the map.

### Caching

Location data is fetched at app startup and re-fetched once every 24 hours (configurable via `MAP_CACHE_INTERVAL_HOURS`). Coordinates rarely change so daily refresh is sufficient; the map loads instantly on every page visit.

### Map features

| Feature | Detail |
|---|---|
| **Colour by region** | Device pins are coloured by US geographic region. Each region groups a configurable set of states and has its own hex colour. Devices in states not assigned to any region appear in the **Other** colour. |
| **Clustering** | Nearby devices merge into a count bubble at low zoom levels. The bubble colour reflects the most common region among clustered devices. |
| **Zoom to expand** | Click any cluster to zoom in. Individual pins appear at city level. |
| **Device popup** | Click a pin to see name, region, ADOM, platform, firmware version, description, connection status, and exact coordinates. |
| **ADOM filter** | Checkboxes let users show/hide devices per ADOM instantly — no server round-trip. |
| **Status bar** | Shows refresh progress while the cache warms; disappears when complete. |
| **Refresh button** | Admin-only; triggers an immediate background refresh and shows progress. |

### Region configuration

Device pin colours are defined by US geographic regions. Default regions:

| Region | States | Default colour |
|---|---|---|
| Upper Midwest | Minnesota, Wisconsin, North Dakota, South Dakota | Blue (`#1976d2`) |
| Colorado | Colorado | Red (`#e53935`) |
| Southwest | Texas, New Mexico | Green (`#43a047`) |
| Other | Any state not in a named region | Near-black (`#333333`) |

Admins can add, rename, or delete regions and change state assignments and colours without restarting the app:

1. Navigate to **⚙ Admin → Map Region Colors**.
2. Click **+ Add Region** to create a new region, or edit an existing row.
3. Use the multi-select in each row to assign states (hold **Ctrl/Cmd** for multi-select). A state can only belong to one region.
4. Use the colour picker to set the pin colour.
5. Click the **×** button to delete a region — its states return to the *Other* pool.
6. Click **Save**.

Changes are written to `map_regions.json` in the project root and take effect on the next map page load. If `map_regions.json` is absent, the application falls back to the defaults above.

### ADOM access control

`/api/map/devices` applies the same ADOM filter as all other device endpoints — restricted users only see devices from their allowed ADOMs.

---

## Security Notes

- All FortiManager calls are **read-only** — only `get` and proxy `monitor` operations are used. No device configuration is ever changed.
- Passwords are **bcrypt-hashed**; `users.json` is gitignored.
- The `.env` file is gitignored — never commit credentials.
- `groups.json` is gitignored; copy from `groups.example.json`.
- Open-redirect protection is enforced on the login `?next=` parameter.
- `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE=Lax`, and automatic `SESSION_COOKIE_SECURE` (when TLS is active) are all set.
- Flask session cookies are cryptographically signed with `SECRET_KEY`.
- All `/admin/*` routes enforce the `admin` role server-side — the nav-link hiding is cosmetic only.

---

## Production Deployment

See **[production.md](production.md)** for the complete step-by-step guide:

- Phase 1 — Linux server prerequisites and OS packages
- Phase 2 — Application deployment, systemd service, Gunicorn
- Phase 3 — Nginx reverse proxy with TLS termination
- Phase 4 — RADIUS authentication with group-to-role mapping
- Phase 5 — Hardening (fail2ban, rate limiting, security checklist)
- Phase 6 — Monitoring, updates, certificate renewal, backup

See **[container.md](container.md)** for Docker and Docker Compose deployment.

> **Gunicorn worker class:** Always use `--worker-class gthread`. The default `sync`
> worker forks child processes — background threads (summary job, map cache, ADOM cache)
> do not transfer to forked workers and the schedulers will never fire.
>
> In the standard production layout, Gunicorn binds to `127.0.0.1:8100` and Nginx
> terminates TLS on port 443. Port 5443 is only used in direct/dev mode (no Nginx).
>
> ```bash
> # Standard production (behind Nginx on port 443)
> gunicorn --workers 2 --threads 4 --worker-class gthread --bind 127.0.0.1:8100 wsgi:app
>
> # Direct mode / development (no Nginx — app handles TLS itself)
> gunicorn --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:5443 wsgi:app
> ```

---

## Extending the Application

Adding a new page follows this five-step pattern:

1. **API data** — add a route to `app/routes/api_routes.py` (or a new blueprint).
2. **Page route** — add a route decorated with `@tab_required("my_tab_key")`.
3. **Template** — add `app/templates/<page>.html` extending `base.html`.
4. **JavaScript** — add `app/static/js/<page>.js`; reference it in the template's `{% block scripts %}`.
5. **Tab registry** — call `registry.register("my_tab_key", "Display Name", "blueprint.view")` in the route module.

The new tab key appears automatically in the Admin group-editor checklist. No build tools or transpilers — the entire front end is plain HTML, CSS, and JavaScript.

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Key points:
- One feature or fix per pull request.
- Run `uv run pytest` and `uv run flake8` before submitting.
- Update the README if your change affects user-visible behaviour.
- Never commit credentials, `.env`, or runtime data files.

To report a security vulnerability, follow the process in [SECURITY.md](SECURITY.md).

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.
