# Config-Diff Scheduled Export — Design Spec

**Date:** 2026-07-23  
**Branch:** development  
**Status:** Approved

---

## Overview

Three related improvements to the Config-Delta tab and Admin panel:

1. Protect the manual bulk export from accidental browser navigation loss.
2. Add server-side scheduled Config-Delta exports that email results on a weekly schedule.
3. Add a "Config-Diff" admin sub-tab for managing SMTP settings and scheduled jobs.

---

## 1. Config-Delta Tab — Navigation Warning

**File:** `app/static/js/pending_changes.js`

Add a `beforeunload` event listener that fires only while a bulk export is in progress:

- Registered at the start of `exportAllDevices()`.
- Removed on loop completion, cancellation, or error.
- Uses the standard browser confirmation dialog — no custom UI.
- No change to the PDF/print behavior introduced in the prior fix.

---

## 2. Data Storage

### `smtp_config.json` (project root, gitignored)

Global SMTP configuration — one record:

```json
{
  "host": "",
  "port": 25,
  "tls_mode": "none",
  "username": "",
  "password": "",
  "from_address": "",
  "run_history_days": 30,
  "enabled": true
}
```

- `tls_mode`: `"none"` | `"starttls"` | `"ssl"`
- `username` / `password` / `from_address`: optional — blank means unauthenticated internal relay
- `run_history_days`: how many days of per-job run history to retain (default 30)

Add `smtp_config.json` and `smtp_config.example.json` to `.gitignore` and repo respectively.

### `config_diff_jobs.json` (project root, gitignored)

Array of scheduled job definitions with embedded run history:

```json
[
  {
    "id": "<uuid4>",
    "adom": "ENTERPRISE-SERVICES",
    "day_of_week": "MON",
    "time": "06:00",
    "format": "pdf",
    "email": "user@example.com",
    "enabled": true,
    "created_at": "2026-07-23T10:00:00Z",
    "runs": [
      {
        "ran_at": "2026-07-21T06:00:12Z",
        "status": "ok",
        "devices_total": 57,
        "devices_with_changes": 25
      },
      {
        "ran_at": "2026-07-14T06:01:03Z",
        "status": "error",
        "error": "SMTP connection refused"
      }
    ]
  }
]
```

- `day_of_week`: `"SUN"` | `"MON"` | `"TUE"` | `"WED"` | `"THU"` | `"FRI"` | `"SAT"`
- `time`: 24-hour `"HH:MM"` string
- `format`: `"pdf"` | `"csv"` | `"json"`
- `runs`: newest first; records older than `run_history_days` are pruned on each successful execution

Add `config_diff_jobs.json` and `config_diff_jobs.example.json` to `.gitignore` and repo respectively.

---

## 3. New Backend Modules

### `app/smtp_client.py`

Thin wrapper around Python stdlib `smtplib` and `email`. No new dependencies.

**Functions:**

- `send_email(to: str, subject: str, body_html: str, attachments: list[dict] = []) -> None`
  - Reads `smtp_config.json` via `app/app_settings.py`-style atomic read.
  - Connects with appropriate TLS mode.
  - Attaches files as `(filename, bytes, mimetype)` tuples.
  - Raises a descriptive exception on failure; caller is responsible for logging.

- `test_connection(to_address: str) -> dict`
  - Sends a plain test email.
  - Returns `{"ok": True}` or `{"ok": False, "error": "<message>"}`.
  - Never raises — always returns a dict so the API route can respond cleanly.

### `app/config_diff_scheduler.py`

Scheduled job engine following the same pattern as `summary_job.py`.

**Module-level state:**
- `_scheduler`: single `BackgroundScheduler` instance
- `_jobs_lock`: `threading.Lock` for safe concurrent access to the JSON file

**Functions:**

- `init_scheduler(app)` — called from `app/__init__.py`. Loads `config_diff_jobs.json`, registers each enabled job as an APScheduler `CronTrigger`. Starts the scheduler.

- `run_job(job_id: str)` — executes a single job:
  1. Loads job definition from JSON.
  2. Fetches all device diffs for the ADOM using the existing 10-worker thread pool logic from `pending_changes_routes.py` (extracted to a shared helper).
  3. Builds the export payload in the requested format (PDF HTML string / CSV string / JSON string).
  4. Sends via `smtp_client.send_email()` — body contains a brief summary (total devices, devices with changes); the export file is attached.
  5. Writes a run record to `runs[]` (status `"ok"` or `"error"`).
  6. Prunes `runs[]` entries older than `run_history_days`.
  7. Saves back to `config_diff_jobs.json` atomically.
  8. Logs success or error to the app logger (visible in the Logs sub-tab).

- `register_job(job: dict)` — adds an APScheduler cron entry for a job at runtime.
- `unregister_job(job_id: str)` — removes an APScheduler cron entry at runtime.
- `get_all_jobs() -> list` — returns current job definitions with run history.
- `create_job(job_data: dict) -> dict` — assigns UUID, saves to JSON, registers with scheduler.
- `update_job(job_id: str, job_data: dict) -> dict` — updates JSON, re-registers cron trigger.
- `delete_job(job_id: str)` — removes from JSON, unregisters from scheduler.

**Shared export helper:** Extract `_run_bulk_preview(adom, devices)` from `pending_changes_routes.py` into a module-level function usable by both the route (browser-triggered) and the scheduler (server-triggered).

---

## 4. Admin API Routes (added to `admin_routes.py`)

### SMTP Config

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/api/smtp` | Get current SMTP config (password masked) |
| `PUT` | `/admin/api/smtp` | Save SMTP config |
| `POST` | `/admin/api/smtp/test` | Send test email; body: `{"to": "..."}` |

### Scheduled Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/api/config-diff/jobs` | List all jobs with run history |
| `POST` | `/admin/api/config-diff/jobs` | Create a job |
| `PUT` | `/admin/api/config-diff/jobs/<id>` | Update a job |
| `DELETE` | `/admin/api/config-diff/jobs/<id>` | Delete a job |
| `POST` | `/admin/api/config-diff/jobs/<id>/run` | Trigger immediate run (async, returns 202) |
| `GET` | `/admin/api/config-diff/jobs/<id>/status` | Poll run status for the most recent run — returns `{"running": bool, "last_run": {ran_at, status, error?}}` |

All routes are `admin_required`.

---

## 5. Admin UI — Config-Diff Sub-tab

**File:** `app/templates/admin.html` + `app/static/js/admin.js`

Added between "External API" and "Logs" in the tab bar:

```html
<button class="admin-tab" data-panel="config-diff">Config-Diff</button>
```

### Panel structure

**Section 1: SMTP Configuration**

Form fields:
- Host (text)
- Port (number, default 25)
- TLS Mode (select: None / STARTTLS / SSL)
- Username (text, optional)
- Password (password, optional — shows placeholder `••••••` if saved)
- From Address (text, optional)
- Run History Retention (number, default 30, suffix "days")

Buttons:
- **Save** — `PUT /admin/api/smtp`, shows inline success/error message
- **Test** — prompts inline for a "Send test to" email address, calls `POST /admin/api/smtp/test`, shows colored result inline. Failure also written to app log.

---

**Section 2: Scheduled Jobs**

Jobs table columns: ADOM | Day | Time | Format | Email | Last Run | Status | Actions

- **Status badge**: green `OK`, red `ERROR` (hover tooltip shows error message), grey `Never`
- **Actions**: Edit | Delete | Run Now

**Add Job / Edit Job** — inline form below the table (not a modal):
- ADOM (select, from `/admin/api/adoms`)
- Day of Week (select: SUN–SAT)
- Time (time input, 24hr)
- Format (select: PDF / CSV / JSON, default PDF)
- Email to (text)
- Enabled (toggle)
- Buttons: Save | Cancel

**Run Now** — calls `POST /admin/api/config-diff/jobs/<id>/run`, polls `/status` every 3s, updates the Last Run / Status cells inline when done.

---

## 6. Startup Wiring

`app/__init__.py` — add after existing scheduler inits:

```python
from app.config_diff_scheduler import init_scheduler as init_config_diff_scheduler
with app.app_context():
    init_config_diff_scheduler(app)
```

---

## 7. Example Files

`smtp_config.example.json` and `config_diff_jobs.example.json` committed to repo with blank/placeholder values, following the pattern of `infra_targets.example.json`.

---

## 8. Error Handling

- SMTP failures during scheduled runs: logged to app logger at `ERROR` level, run record written with `status: "error"` and the exception message.
- FMG unreachable during scheduled run: run record written as `"error"`, job does not retry (next scheduled occurrence will try again).
- Missing `smtp_config.json`: `init_scheduler` logs a warning and skips email jobs; file is created with defaults on first Save in the Admin UI.
- Missing `config_diff_jobs.json`: treated as empty list on startup; created on first job save.

---

## 9. Out of Scope

- Multiple recipients per job (single email address only for now)
- Retry logic on SMTP failure
- Job run triggered from the Config-Delta tab directly (manual export stays browser-side)
- Email templates / branding
