# Scheduled Device Review Jobs — Design

**Date:** 2026-08-01
**Status:** Approved

---

## Overview

Rename the Admin → "Config-Diff" tab to "Scheduled". Add a Device Review Jobs section below the existing Config-Delta Jobs section. Users can create scheduled jobs that run Device Review checks against an ADOM on a recurring schedule and email the results as PDF/CSV/JSON attachments.

This is the first step toward a general-purpose "Scheduled Reports" area — additional report types (Hygiene, Rule Validation) can be added as new sections in the same tab following the same pattern.

---

## Scope

### New files
- `app/device_review_scheduler.py` — APScheduler-based scheduler for Device Review jobs
- `device_review_jobs.json` — runtime job persistence (gitignored)
- `device_review_jobs.example.json` — committed example/template
- `tests/test_device_review_scheduler.py` — test suite (written before implementation)

### Modified files
- `app/routes/device_review_routes.py` — add `bulk_device_review_adom()` for scheduler use
- `app/routes/admin_routes.py` — 6 new endpoints under `/admin/api/device-review/jobs/...`
- `app/__init__.py` — register `device_review_scheduler.init_scheduler()`
- `app/templates/admin.html` — rename tab; add Device Review Jobs section
- `app/static/js/admin.js` — Device Review jobs UI logic
- `.gitignore` — add `device_review_jobs.json`
- `CLAUDE.md` — document new scheduler, job schema, endpoints

### Zero changes to
`config_diff_scheduler.py`, `device_review.py`, `smtp_client.py`

---

## Data Schema — `device_review_jobs.json`

Array of job objects at the project root (same location as `config_diff_jobs.json`).

```json
[
  {
    "id": "uuid4-string",
    "name": "Weekly CIS Audit — Enterprise",
    "adom": "Enterprise Services",
    "days_of_week": ["MON", "FRI"],
    "time": "02:00",
    "checks": ["ntp_config", "syslog_config", "trusted_hosts", "firmware_version"],
    "check_params": {
      "ntp_config":       { "expected_servers": "10.1.1.1, 10.1.1.2" },
      "syslog_config":    { "expected_servers": "10.2.2.1" },
      "firmware_version": { "min_version": "7.4.3" }
    },
    "email": "alice@corp.com, bob@corp.com",
    "format": "pdf",
    "enabled": true,
    "runs": [
      {
        "ran_at": "2026-08-01T02:00:00Z",
        "status": "ok",
        "devices_total": 12,
        "devices_reviewed": 12,
        "total_findings": 47,
        "fail_count": 3
      }
    ]
  }
]
```

**Field rules:**
- `checks`: list of check keys from `CHECKS_META`; empty list = run all 18 checks
- `check_params`: only entries for parameterized checks that have values — omitted keys mean no param supplied (check runs as `CONFIG_MISSING`)
- `email`: comma-separated string, split at send time; supports multiple recipients
- `format`: `"pdf"` | `"csv"` | `"json"`
- `runs`: pruned to last `run_history_days` days (read from `smtp_config.json`, default 30)

---

## `device_review_scheduler.py` — Structure

Mirrors `config_diff_scheduler.py` exactly:

| Symbol | Purpose |
|--------|---------|
| `_JOBS_PATH` | `Path("device_review_jobs.json")` |
| `_lock` | `threading.Lock` |
| `_scheduler` | `BackgroundScheduler` instance |
| `_running_jobs` | `set()` — tracks in-flight jobs |
| `_validate_job_fields(data)` | validates `days_of_week`, `time`, `checks` list |
| `get_all_jobs()` | public read |
| `create_job(data)` | uuid4 id, validate, register |
| `update_job(id, data)` | validate, unregister/re-register |
| `delete_job(id)` | unregister, remove from JSON |
| `run_job_now(id)` | daemon thread |
| `is_job_running(id)` | bool |
| `init_scheduler()` | called from `app/__init__.py` |
| `_execute_job(job_id)` | core execution (see below) |

### `_execute_job` flow

```
1. Acquire fcntl file lock (skip if already running — same pattern as config_diff_scheduler)
2. Load job from device_review_jobs.json
3. Call bulk_device_review_adom(adom, checks, check_params) from device_review_routes.py
4. Count findings: total, fail_count (FAIL + INSECURE rows)
5. Build summary HTML email body (per-check pass/fail/warn table)
6. Build attachment (PDF/CSV/JSON) from all findings rows
7. Pass email string directly to send_email() — smtp_client._parse_recipients() already splits on comma internally
8. send_email(job["email"], subject, body_html, [attachment])
9. Append run record, prune old runs
```

**Email subject:** `4THealth Device Review — {adom} — {YYYY-MM-DD}`

---

## `bulk_device_review_adom()` — New function in `device_review_routes.py`

```python
def bulk_device_review_adom(
    adom: str,
    checks: list[str],
    check_params: dict,
    max_workers: int = 4,
) -> list[dict]:
    """Run selected device review checks against all devices in an ADOM.

    Returns list of {device, ip, rows, error}.
    Uses ThreadPoolExecutor(max_workers) — no FMG staging locks involved.
    """
```

- Fetches device list via `make_client().get_devices(adom)`
- Runs `_fetch_device_data()` + `run_checks()` per device via `ThreadPoolExecutor`
- Returns `[{device, ip, rows, error}]` — same shape the interactive single-device endpoint returns, just aggregated

---

## Admin API Endpoints

All under `admin_required` decorator. Pattern mirrors existing Config-Delta endpoints exactly.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/api/device-review/jobs` | List all jobs |
| `POST` | `/admin/api/device-review/jobs` | Create job |
| `PUT` | `/admin/api/device-review/jobs/<id>` | Update job |
| `DELETE` | `/admin/api/device-review/jobs/<id>` | Delete job |
| `POST` | `/admin/api/device-review/jobs/<id>/run` | Fire now (202) |
| `GET` | `/admin/api/device-review/jobs/<id>/status` | `{running, last_run}` |

---

## Admin UI — "Scheduled" Tab

### Tab rename
`Config-Diff` → `Scheduled` in both `admin.html` and `admin.js`.

### Layout
```
┌─ SMTP Settings ─────────────────────────────────────────────┐
│  (unchanged)                                                 │
└─────────────────────────────────────────────────────────────┘

┌─ Config-Delta Jobs ─────────────────────────────────────────┐
│  (unchanged — existing table + form, visually grouped)       │
└─────────────────────────────────────────────────────────────┘

┌─ Device Review Jobs ────────────────────────────────────────┐
│  [+ Add Job]                                                 │
│                                                              │
│  ┌ Add/Edit Form (hidden until + clicked) ────────────────┐ │
│  │ Name         [text]                                     │ │
│  │ ADOM         [select — loaded from /admin/api/adoms]   │ │
│  │ Days         [MON TUE WED THU FRI SAT SUN checkboxes]  │ │
│  │ Time         [HH:MM]                                    │ │
│  │ Checks       [checklist — all 18, all checked default] │ │
│  │ Parameters   [dynamic inputs for ticked param checks]  │ │
│  │ Format       [PDF / CSV / JSON]                         │ │
│  │ Email        [text, comma-separated]                    │ │
│  │ Enabled      [checkbox]                                 │ │
│  │              [Save]  [Cancel]                           │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  Table: Name | ADOM | Days | Time | Checks | Format |       │
│         Email | Last Run | Status | Actions                  │
│         (Edit / Delete / Run Now)                            │
└─────────────────────────────────────────────────────────────┘
```

### Parameters panel
Rendered dynamically in JS: when a check with `params_schema` is ticked, its param inputs appear inline below the checklist. On uncheck, inputs are removed and values cleared. Mirrors the existing Device Review tab's `renderParamsPanel()` pattern in `device_review.js`.

### Checks column in table
Shows count of selected checks (e.g. "14 / 18") rather than listing all names — avoids overflowing the cell.

### Multiple recipients
`email` field is a plain text input; tooltip/placeholder reads `"e.g. alice@corp.com, bob@corp.com"`. The raw comma-separated string is passed directly to `send_email()` — `smtp_client._parse_recipients()` already handles splitting internally, so no changes to `smtp_client.py` are needed.

**Config-Delta retrofit (UI only):** The existing Config-Delta job form's `email` input and the jobs table display will both be updated to show/accept comma-separated addresses. No backend change needed — `send_email()` already supports it.

---

## `.gitignore` Addition

```
device_review_jobs.json
```

Added alongside the existing `config_diff_jobs.json` entry (line 16).

---

## Testing Strategy

Tests written **before** implementation (`tests/test_device_review_scheduler.py`):

1. `test_create_job_persists` — create a job, reload from JSON, verify fields
2. `test_validate_days_of_week` — invalid day codes raise `ValueError`
3. `test_validate_time_format` — bad HH:MM raises `ValueError`
4. `test_delete_job_removes_from_json` — delete, verify gone
5. `test_run_job_now_fires_thread` — mock `_execute_job`, verify thread starts
6. `test_execute_job_sends_email` — mock `bulk_device_review_adom` + `send_email`, verify called with correct args
7. `test_execute_job_appends_run_record` — verify run history entry written
8. `test_prune_runs_respects_retention` — runs older than retention days are removed
9. `test_bulk_device_review_adom_aggregates` — mock FMG client + run_checks, verify result shape

---

## CLAUDE.md Updates

- Rename "Config-Diff Scheduled Exports" section to "Scheduled Exports"
- Add "Device Review Scheduled Jobs" subsection documenting:
  - `app/device_review_scheduler.py` module
  - `device_review_jobs.json` schema
  - New `bulk_device_review_adom()` function
  - Admin API endpoints
- Add `device_review_jobs.json` to the gitignored runtime files list
