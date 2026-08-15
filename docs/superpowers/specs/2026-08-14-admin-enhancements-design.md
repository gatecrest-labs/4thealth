# Admin Enhancements Design

**Date:** 2026-08-14  
**Branch:** development  
**Status:** Approved for implementation

## Overview

Three enhancements to the Admin tab and related areas:

1. **Move Zone Policy Edit Database** from the Zone Policy tab to the Admin tab under a new "Zone Policy" subsection — restricting editing to admins at the UI level, not just the API level.
2. **Add SCP as a backup transfer protocol** alongside the existing SFTP and FTP options.
3. **Host resource graphs** (CPU, Memory, Disk) displayed above the Admin tab bar, with selectable time ranges and 90-day historical retention.

---

## Feature 1: Move Edit Database to Admin Tab

### Motivation

The "Edit Database" sub-tab in the Zone Policy page is already guarded by `{% if session.get('role') == 'admin' %}` in the template and by `@admin_required` on every backend mutation route. However, placing it inside the Zone Policy tab creates a confusing experience for non-admin users (the tab is simply invisible to them, but its absence is unexplained). Moving it to the Admin tab consolidates all write operations in one place and makes the Zone Policy tab fully read-only for all users.

### Changes

**`app/templates/zone_policy.html`**
- Remove the `<button class="zp-tab zp-tab-btn" data-panel="edit">Edit Database</button>` tab button.
- Remove the entire `{% if session.get('role') == 'admin' %}...{% endif %}` block containing `panel-edit` and all its child sections.
- Remove the `<script>window._zpIsAdmin = ...</script>` injection — no longer needed on this page.

**`app/static/js/zone_policy.js`**
- Remove all edit-related code: `zpBackupBtn` click handler, zone/subnet/policy form wiring, dropdown population functions for the edit forms (`populateZpEditZoneSelects`, etc.), and all `fetch('/api/zone/zone/...')`, `fetch('/api/zone/subnet/...')`, `fetch('/api/zone/policy/...')` calls.
- The read-only functions (query, browse, validate) remain unchanged.

**`app/templates/admin.html`**
- Add a new tab button `<button class="admin-tab" data-panel="zone-policy">Zone Policy</button>` to the tab bar (placed after Backup, before Application Logs).
- Add a matching `<div class="admin-panel" id="panel-zone-policy">` panel with the identical HTML content from the old `panel-edit`: backup button, zone operations section, subnet operations section, policy rule operations section.

**`app/static/js/admin.js`**
- Add all zone policy edit JS under a `// --- Zone Policy Edit ---` section: dropdown population on panel activation, all form submit handlers for zone/subnet/policy CRUD, and the backup button handler.
- On admin page load, populate zone/policy dropdowns when the zone-policy panel is activated (lazy-load on first tab click).

**Backend:** No changes — all `/api/zone/*` mutation routes are already `@admin_required`.

---

## Feature 2: SCP Backup Transfer Protocol

### Motivation

SCP (Secure Copy Protocol) is an SSH-based file transfer protocol commonly available on RHEL servers and network appliances. Some environments restrict SFTP but permit SCP, or prefer SCP for simpler scripting. Adding it alongside SFTP and FTP rounds out the SSH-family transfer options.

### Changes

**`pyproject.toml` / `uv.lock`**
- Add `scp` package via `uv add scp`. The `scp` PyPI package wraps `paramiko`'s SSH transport and provides `SCPClient`. Paramiko is already a dependency.

**`app/backup_scheduler.py`**
- `transfer_file(cfg, local_path)`: add an `elif protocol == "scp"` branch after the SFTP branch.
  ```python
  elif protocol == "scp":
      import scp as scp_lib
      ssh = paramiko.SSHClient()
      ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
      ssh.connect(host, port=port, username=username, password=password)
      with scp_lib.SCPClient(ssh.get_transport()) as scpc:
          scpc.put(local_path, remote_path)
      ssh.close()
  ```
- `test_connection(cfg)`: add matching `elif protocol == "scp"` branch — connect via SSH, list the remote directory via `exec_command('ls -la ' + remote_dir)` to verify credentials and path.

**`app/templates/admin.html`**
- Add `<option value="scp">SCP</option>` to the protocol `<select>` in the backup panel, positioned after SFTP.
- The FTP plaintext warning banner already checks `if (protocol === 'ftp')` — SCP uses SSH so no warning is shown for it. No template logic changes needed beyond the new `<option>`.
- Default port (22) and field set (host, port, username, password, remote dir) are identical to SFTP — no new form fields required.

**`backup_config.json` schema:** Unchanged. The `ftp` sub-dict's `protocol` field will accept `"scp"` as a third value. No migration needed; existing configs default to `"sftp"`.

---

## Feature 3: Host Resource Graphs

### Motivation

The 4THealth server itself has no self-monitoring. Admins have no visibility into whether the server running the app is resource-constrained. Adding CPU, memory, and disk graphs in the Admin tab provides at-a-glance health for the host (or container), helping diagnose slow API responses or disk-full backup failures.

### Architecture

```
psutil (every 60s)
    → app/host_metrics.py::record_sample()
    → SQLite: host_metrics.db (project root, gitignored)

GET /admin/api/host-metrics?range=1h
    → host_metrics.get_metrics(range)
    → aggregated rows from SQLite
    → JSON response

admin.html (Chart.js line charts)
    ← time-range pill selector (1h default)
    ← three cards: CPU / Memory / Disk
```

### Storage: SQLite

File: `host_metrics.db` at the project root (added to `.gitignore`).

```sql
CREATE TABLE IF NOT EXISTS host_metrics (
    ts    INTEGER NOT NULL,
    cpu   REAL,
    mem   REAL,
    disk  REAL
);
CREATE INDEX IF NOT EXISTS idx_ts ON host_metrics(ts);
```

At 60-second polling, 90 days of retention = ~130,000 rows. Trivial for SQLite with the `ts` index. No rollup tables — aggregation is done at query time with `GROUP BY`.

### Data Collection: `app/host_metrics.py`

New module, mirroring `app/infra_health_cache.py` in structure.

**Functions:**

`init_db(db_path)` — called once at startup; creates table and index if absent.

`record_sample(db_path)` — called by APScheduler every 60 seconds:
```python
cpu  = psutil.cpu_percent(interval=None)
mem  = psutil.virtual_memory().percent
disk = psutil.disk_usage('/').percent
# INSERT INTO host_metrics VALUES (int(time.time()), cpu, mem, disk)
```

`get_metrics(db_path, range_key)` — queries with per-range bucketing:

| `range_key` | Window | Bucket (seconds) | ~Points |
|---|---|---|---|
| `1h`  | 3,600 s    | 60 (raw)    | 60  |
| `4h`  | 14,400 s   | 300 (5 min) | 48  |
| `12h` | 43,200 s   | 600 (10 min)| 72  |
| `1d`  | 86,400 s   | 900 (15 min)| 96  |
| `7d`  | 604,800 s  | 3,600 (1 hr)| 168 |
| `14d` | 1,209,600 s| 7,200 (2 hr)| 168 |

SQL pattern:
```sql
SELECT (ts / :bucket) * :bucket AS t,
       AVG(cpu), AVG(mem), AVG(disk)
FROM host_metrics
WHERE ts >= strftime('%s','now') - :window
GROUP BY t
ORDER BY t;
```
Returns `{cpu: [{ts, v},...], mem: [...], disk: [...]}`.

`prune_old_data(db_path)` — deletes rows older than 90 days; run by APScheduler once daily.

`init_scheduler(app)` — registers:
1. `record_sample` interval job: every 60 seconds, starting immediately via a daemon thread (same pattern as `infra_health_cache.poll_now()`).
2. `prune_old_data` cron job: daily at 03:00.

**`app/__init__.py`** — add `host_metrics.init_scheduler(app)` alongside the other eight scheduler init calls.

### API: `GET /admin/api/host-metrics`

Added to `app/routes/admin_routes.py`, protected by `@_admin_required`.

Query param: `range` — one of `1h`, `4h`, `12h`, `1d`, `7d`, `14d`. Defaults to `1h` if absent or invalid.

Response:
```json
{
  "cpu":  [{"ts": 1723633200, "v": 42.1}, ...],
  "mem":  [{"ts": 1723633200, "v": 61.3}, ...],
  "disk": [{"ts": 1723633200, "v": 34.8}, ...],
  "range": "1h",
  "generated_at": 1723636800
}
```

### Frontend

**Chart.js** — added as a vendored file at `app/static/js/vendor/chart.min.js` (downloaded once, no CDN dependency in production). Version 4.x.

**`app/templates/admin.html`** — new `<div class="admin-metrics-header">` inserted between the page `<h1>` and the tab bar `<div class="admin-tabs">`.

Layout: time-range pill selector row (`1h · 4h · 12h · 1d · 7d · 14d`) above three equal-width `<canvas>` cards (CPU / Memory / Disk), each in a card div with a title and the chart.

The Memory card includes an info icon tooltip: shown only when `window._inDocker === true` (injected by the template via `os.path.exists('/.dockerenv')`), with text "Reflects host memory — container memory limit may differ."

**`app/static/js/admin.js`** — new `// --- Host Metrics Charts ---` section:
- Three `Chart` instances (line, smooth, no points, filled area), Y-axis 0–100%, X-axis formatted by range (HH:MM for short ranges, MMM D HH:MM for multi-day).
- `loadMetrics(range)` — fetches `/admin/api/host-metrics?range=<range>`, updates all three charts' data and labels in one call.
- Time-range pill click handler calls `loadMetrics(range)` and updates active pill styling.
- Charts load on admin page ready with default range `1h`; auto-refresh every 60 seconds while the admin page is open (matches the polling interval).

**`app/routes/admin_routes.py`** — `admin_page()` adds `in_docker=os.path.exists('/.dockerenv')` to the template context.

### Dependencies Added

| Package | Purpose |
|---|---|
| `psutil` | CPU, memory, disk reads |
| `scp` | SCP file transfer (Feature 2) |

Both added via `uv add psutil scp`.

### Files Added/Changed Summary

| File | Action |
|---|---|
| `app/host_metrics.py` | New |
| `app/routes/admin_routes.py` | Add host-metrics endpoint + `in_docker` context |
| `app/__init__.py` | Register `host_metrics.init_scheduler` |
| `app/templates/admin.html` | Add Zone Policy panel, SCP option, metrics header |
| `app/templates/zone_policy.html` | Remove Edit Database tab + panel + `_zpIsAdmin` |
| `app/static/js/admin.js` | Add zone-policy edit JS + chart JS |
| `app/static/js/zone_policy.js` | Remove edit JS |
| `app/static/js/vendor/chart.min.js` | New (vendored Chart.js) |
| `app/backup_scheduler.py` | Add SCP protocol branch |
| `app/static/css/style.css` | Add `.admin-metrics-header` layout styles |
| `host_metrics.db` | New at runtime (gitignored) |
| `pyproject.toml` / `uv.lock` | Add `psutil`, `scp` |
| `.gitignore` | Add `host_metrics.db` |
