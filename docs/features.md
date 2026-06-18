# Feature Reference

## Managed Network Summary

The **summary bar** at the top of the Dashboard shows the total scale of the managed firewall estate.

| Stat | Source | Meaning |
|---|---|---|
| **Managed Firewalls** | `dvmdb` device count per ADOM | Total FortiGate devices registered across all ADOMs with at least one device |
| **Policy Rules Managed** | Policy package enumeration | Sum of all firewall policy entries across every package in every active ADOM |

Data is **never calculated on page load**. A background job runs instead:

1. **On app startup** — fires automatically, stores results in memory. The Dashboard shows spinners while the calculation runs (typically 4–5 minutes on large instances).
2. **Nightly at 01:00** (configurable via `SUMMARY_REFRESH_HOUR`) — APScheduler triggers a fresh calculation.
3. **On demand (admin only)** — `POST /api/summary/refresh` kicks off an immediate recalculation.

FortiManager has no single "total rule count" API. The job enumerates every ADOM, skips empty system ADOMs, enumerates every policy package, and fetches policy IDs per package. On a production instance with ~135 packages and ~14,700 rules this takes roughly 4–5 minutes.

---

## Rule Review

Two sections on a single page: a full **Policy Rules** viewer and a **Hygiene Analysis** panel. All analysis is read-only.

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

Runs configurable security checks against the management-plane interfaces of every device in a selected ADOM.

### Workflow

1. Select an ADOM — the device grid loads with all devices selected by default.
2. Filter or deselect devices using the searchable grid.
3. Choose which checks to run (all enabled by default).
4. Click **Run Analysis** — findings appear in a filterable, paginated table.
5. Export results as **CSV**, **JSON**, or **PDF** (PDF includes ADOM, timestamp, and device count — suitable as compliance evidence).

### Severity Levels

| Severity | Meaning |
|---|---|
| `INSECURE` | Red — cleartext protocol (HTTP, Telnet) is enabled |
| `WARN` | Yellow — no secure management alternative (HTTPS, SSH) is present |
| `INFO` | Blue — informational finding (e.g. PING enabled) |

### Adding a New Check

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

Helps engineers validate firewall rule change requests before submitting them. For each requested flow it answers:

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

When zone policy is configured, Rule Validation calls the zone policy API to check whether the requested flow is permitted at the network segmentation layer — independent of any specific firewall rule. If zone policy is not configured, the tab degrades gracefully (firewall policy analysis still works).

### Path Analysis

For each flow the engine fetches live routing table and interface data from FortiManager, then checks whether the source and destination IPs resolve to different interfaces on the selected device. A **⚠ Not In Path** result means the traffic likely routes through a different firewall.

---

## Zone Policy

A self-contained network segmentation policy browser. It reads `policy_db.json` from the project root and requires no FortiManager connection.

### Sub-tabs

| Sub-tab | Description |
|---|---|
| **Query Flow** | Enter source/destination IPs (multi-line or comma-separated) and optional service; get an ALLOWED / BLOCKED / UNKNOWN verdict with the governing rule |
| **Browse** | Zone accordion list (searchable) and full policy table (filterable by access type and severity) |
| **Validate** | Schema validation report — error and warning counts |
| **Edit Database** | *(admin only)* Add/remove/modify zones, subnets, and policy rules; changes are written back to `policy_db.json` atomically |

### Zone Evaluation Precedence

Block all → block only (service match) → allow all → implicit UNKNOWN.

### policy_db.json Format

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

Renders all managed FortiGate devices on an interactive OpenStreetMap base layer using Leaflet and the MarkerCluster plugin.

### Internet Connectivity

The **app server** requires no internet access — all JavaScript, CSS, and the US states GeoJSON are bundled under `app/static/vendor/`.

The **user's browser** makes tile requests to `https://{s}.tile.openstreetmap.org`. If this domain is blocked, the map shows a grey background but pins, clustering, and popups all continue to work. For air-gapped deployments, change the `L.tileLayer(...)` URL in `app/static/js/map.js` to point to a self-hosted tile server.

### Location Data

FortiManager stores `latitude` and `longitude` for each device. These can be set manually in **Device Manager → device properties → Location**, or inferred via IP geolocation (`location_from: diag`). Devices where both fields are `0.0` are silently excluded from the map.

Location data is fetched at app startup and re-fetched every 24 hours (configurable via `MAP_CACHE_INTERVAL_HOURS`).

### Map Features

| Feature | Detail |
|---|---|
| **Colour by region** | Device pins are coloured by US geographic region. Each region groups a configurable set of states and has its own hex colour. |
| **Clustering** | Nearby devices merge into a count bubble at low zoom levels. |
| **Device popup** | Click a pin to see name, region, ADOM, platform, firmware version, description, connection status, and exact coordinates. |
| **ADOM filter** | Checkboxes let users show/hide devices per ADOM instantly — no server round-trip. |
| **Refresh button** | Admin-only; triggers an immediate background refresh. |

### Region Configuration

Admins can add, rename, or delete regions and change state assignments and colours without restarting the app:

1. Navigate to **⚙ Admin → Map Region Colors**.
2. Click **+ Add Region** to create a new region, or edit an existing row.
3. Use the multi-select in each row to assign states. A state can only belong to one region.
4. Use the colour picker to set the pin colour.
5. Click **Save**.

Changes are written to `map_regions.json` and take effect on the next map page load. Default regions:

| Region | States | Default colour |
|---|---|---|
| Upper Midwest | Minnesota, Wisconsin, North Dakota, South Dakota | Blue (`#1976d2`) |
| Colorado | Colorado | Red (`#e53935`) |
| Southwest | Texas, New Mexico | Green (`#43a047`) |
| Other | Any state not in a named region | Near-black (`#333333`) |

---

## External API

Allows programs like **FW-Analyst** to query zone policy data programmatically without a browser session. All endpoints are read-only.

### Enabling

1. Log in as an admin and go to **Admin → External API**.
2. Check **External API enabled** and click **Save**.

When disabled (the default), all `/external/api/` requests return `503 {"error": "External API is disabled"}`.

### Token Management

1. Click **+ New Token**, enter a descriptive name (e.g. `FW-Analyst-Prod`), and click **Generate Token**.
2. Copy the token value — **it is shown only once**.
3. Tokens can be revoked at any time from the same panel.

### Making Requests

```http
POST /external/api/zone/query
Authorization: Bearer 4th_<your-token>
Content-Type: application/json

{"src": "10.1.0.5", "dst": "10.2.0.10", "service": "443"}
```

### Python Example

```python
import requests

resp = requests.post(
    "https://4thealth.yourdomain.com/external/api/zone/query",
    headers={"Authorization": "Bearer 4th_<your-token>"},
    json={"src": "10.1.0.5", "dst": "10.2.0.10", "service": "443"},
    verify=False,
)
data = resp.json()
```

### Runtime Files

| File | Purpose |
|---|---|
| `app_settings.json` | Stores `external_api_enabled` flag (created automatically) |
| `api_tokens.json` | Stores SHA-256 token hashes (created automatically) |

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

- The buffer holds up to **2,000 entries** and is reset on process restart.
- Use the level and component filters to narrow results.
- The **Set** button changes the capture level at runtime — no restart required.

---

## Extending the Application

Adding a new page follows this five-step pattern:

1. **API data** — add a route to `app/routes/api_routes.py` (or a new blueprint).
2. **Page route** — add a route decorated with `@tab_required("my_tab_key")`.
3. **Template** — add `app/templates/<page>.html` extending `base.html`.
4. **JavaScript** — add `app/static/js/<page>.js`; reference it in the template's `{% block scripts %}`.
5. **Tab registry** — call `registry.register("my_tab_key", "Display Name", "blueprint.view")` in the route module.

The new tab key appears automatically in the Admin group-editor checklist. No build tools or transpilers — the entire front end is plain HTML, CSS, and JavaScript.
