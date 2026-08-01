# Scheduled Device Review Jobs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Device Review Jobs section to the Admin → "Scheduled" tab (renamed from "Config-Diff") so admins can schedule CIS audit runs against an ADOM and receive emailed PDF/CSV/JSON reports.

**Architecture:** A new `app/device_review_scheduler.py` mirrors `config_diff_scheduler.py` exactly in structure (APScheduler CronTrigger, fcntl locking, atomic JSON persistence). A new `bulk_device_review_adom()` function in `device_review_routes.py` provides the scheduler with a session-free entry point. Six new admin API endpoints and a new UI section in the Scheduled panel wire everything together.

**Tech Stack:** Python/Flask, APScheduler, threading, fcntl, uv (dependency management); vanilla JS for the admin UI.

## Global Constraints

- Never use `pip install` — always `uv add <package>` to keep lockfile in sync
- `device_review_jobs.json` must be gitignored (runtime data); `device_review_jobs.example.json` is committed
- Zero changes to `config_diff_scheduler.py`, `device_review.py`, or `smtp_client.py`
- All new admin routes use `@_admin_required` decorator (matches existing pattern in `admin_routes.py`)
- `_execute_job` must acquire fcntl file lock before running (prevents duplicate execution across gthread workers)
- APScheduler prefix for device review jobs: `"dr_"` (config-diff uses `"config_diff_"`)
- Run tests with: `python -m pytest tests/ -v` from project root
- ADOM filter (strip names starting with "forti"): already applied by `/admin/api/adoms` — reuse that endpoint

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/device_review_scheduler.py` | APScheduler engine for device review jobs |
| Create | `device_review_jobs.example.json` | Committed empty-array example |
| Create | `tests/test_device_review_scheduler.py` | TDD test suite (written first) |
| Modify | `.gitignore` | Add `device_review_jobs.json` |
| Modify | `app/routes/device_review_routes.py` | Add `bulk_device_review_adom()` |
| Modify | `app/routes/admin_routes.py` | 6 new device-review job endpoints |
| Modify | `app/__init__.py` | Register `device_review_scheduler.init_scheduler()` |
| Modify | `app/templates/admin.html` | Rename tab; add Device Review Jobs section |
| Modify | `app/static/js/admin.js` | Rename panel trigger; add DR jobs UI |
| Modify | `CLAUDE.md` | Document new module, schema, endpoints |

---

## Task 1: Tests, gitignore, example file

**Files:**
- Create: `tests/test_device_review_scheduler.py`
- Create: `device_review_jobs.example.json`
- Modify: `.gitignore` (add one line)

**Interfaces:**
- Produces: test fixtures and assertions that `app/device_review_scheduler` must satisfy

- [ ] **Step 1: Add `device_review_jobs.json` to `.gitignore`**

Open `.gitignore`. After line 16 (`config_diff_jobs.json`), add:
```
device_review_jobs.json
```

- [ ] **Step 2: Create the example file**

Create `device_review_jobs.example.json` at the project root:
```json
[]
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_device_review_scheduler.py`:

```python
import json
import datetime
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    p = tmp_path / "device_review_jobs.json"
    monkeypatch.setattr("app.device_review_scheduler._JOBS_PATH", p)
    return p


def test_get_all_jobs_empty(jobs_path):
    from app import device_review_scheduler as sched
    assert sched.get_all_jobs() == []


def test_create_job_assigns_id(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Test Job",
        "adom": "TEST",
        "days_of_week": ["MON"],
        "time": "06:00",
        "checks": [],
        "check_params": {},
        "format": "pdf",
        "email": "x@x.com",
        "enabled": True,
    })
    assert "id" in job
    assert len(sched.get_all_jobs()) == 1


def test_create_job_persists_all_fields(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "CIS Audit",
        "adom": "Enterprise",
        "days_of_week": ["MON", "FRI"],
        "time": "02:00",
        "checks": ["ntp_config", "trusted_hosts"],
        "check_params": {"ntp_config": {"expected_servers": "10.1.1.1"}},
        "format": "csv",
        "email": "alice@corp.com, bob@corp.com",
        "enabled": True,
    })
    stored = sched.get_all_jobs()[0]
    assert stored["name"] == "CIS Audit"
    assert stored["checks"] == ["ntp_config", "trusted_hosts"]
    assert stored["check_params"] == {"ntp_config": {"expected_servers": "10.1.1.1"}}
    assert stored["email"] == "alice@corp.com, bob@corp.com"
    assert stored["days_of_week"] == ["MON", "FRI"]


def test_update_job(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Old Name", "adom": "TEST", "days_of_week": ["MON"],
        "time": "06:00", "checks": [], "check_params": {},
        "format": "pdf", "email": "x@x.com", "enabled": True,
    })
    updated = sched.update_job(job["id"], {**job, "email": "new@x.com", "name": "New Name"})
    assert updated["email"] == "new@x.com"
    assert updated["name"] == "New Name"
    assert sched.get_all_jobs()[0]["email"] == "new@x.com"


def test_delete_job(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Test", "adom": "TEST", "days_of_week": ["MON"],
        "time": "06:00", "checks": [], "check_params": {},
        "format": "pdf", "email": "x@x.com", "enabled": True,
    })
    sched.delete_job(job["id"])
    assert sched.get_all_jobs() == []


def test_delete_job_unknown_raises(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(KeyError):
        sched.delete_job("nonexistent-id")


def test_validate_empty_days(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": [], "time": "06:00",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_validate_invalid_day_code(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": ["MONDAY"], "time": "06:00",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_validate_bad_time_format(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="time"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": ["MON"], "time": "6am",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_is_job_running_false_initially(jobs_path):
    from app import device_review_scheduler as sched
    assert sched.is_job_running("any-id") is False


def test_prune_old_runs(jobs_path):
    from app import device_review_scheduler as sched
    old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=40)).isoformat() + "Z"
    recent_ts = datetime.datetime.utcnow().isoformat() + "Z"
    job = sched.create_job({
        "name": "T", "adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
        "checks": [], "check_params": {}, "format": "pdf",
        "email": "x@x.com", "enabled": True,
    })
    jobs = json.loads(jobs_path.read_text())
    jobs[0]["runs"] = [
        {"ran_at": old_ts, "status": "ok", "devices_total": 1, "devices_reviewed": 1,
         "total_findings": 5, "fail_count": 1},
        {"ran_at": recent_ts, "status": "ok", "devices_total": 2, "devices_reviewed": 2,
         "total_findings": 3, "fail_count": 0},
    ]
    jobs_path.write_text(json.dumps(jobs))
    sched._prune_runs(job["id"], retention_days=30)
    remaining = sched.get_all_jobs()[0]["runs"]
    assert len(remaining) == 1
    assert remaining[0]["ran_at"] == recent_ts


def test_execute_job_sends_email(jobs_path, monkeypatch):
    from app import device_review_scheduler as sched

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": ["trusted_hosts"], "check_params": {},
        "format": "pdf", "email": "test@corp.com", "enabled": True,
    })

    fake_results = [
        {"device": "fw-01", "ip": "10.0.0.1",
         "rows": [{"device": "fw-01", "check": "Trusted Hosts on Admin Accounts (CIS)",
                   "result": "PASS", "interface": "system", "vdom": "root",
                   "ip": "", "detail": "All admins have trusted hosts",
                   "protocols": [], "has_insecure": False, "has_secure": False}],
         "error": None},
    ]

    sent = {}

    def fake_bulk(adom, checks, check_params, max_workers=4):
        return fake_results

    def fake_send(to, subject, body_html, attachments):
        sent["to"] = to
        sent["subject"] = subject
        sent["attachments"] = attachments

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom", fake_bulk
    )
    monkeypatch.setattr("app.device_review_scheduler._send_email", fake_send)

    sched._execute_job(job["id"])

    assert sent["to"] == "test@corp.com"
    assert "CorpADOM" in sent["subject"]
    assert len(sent["attachments"]) == 1


def test_execute_job_appends_run_record(jobs_path, monkeypatch):
    from app import device_review_scheduler as sched

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": [], "check_params": {}, "format": "pdf",
        "email": "test@corp.com", "enabled": True,
    })

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "app.device_review_scheduler._send_email",
        lambda *a, **kw: None,
    )

    sched._execute_job(job["id"])

    runs = sched.get_all_jobs()[0]["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert "ran_at" in runs[0]


def test_build_attachment_json(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "PASS",
             "interface": "system", "vdom": "root", "ip": "", "detail": "ok",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "json", results, "2026-08-01T00:00:00Z")
    data = json.loads(att["data"])
    assert data["adom"] == "Corp"
    assert data["exported_at"] == "2026-08-01T00:00:00Z"
    assert len(data["rows"]) == 1


def test_build_attachment_csv(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "PASS",
             "interface": "system", "vdom": "root", "ip": "", "detail": "ok",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "csv", results, "2026-08-01T00:00:00Z")
    text = att["data"].decode()
    assert "Corp" in text
    assert "fw-01" in text
    assert "PASS" in text


def test_build_attachment_pdf_html(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "FAIL",
             "interface": "system", "vdom": "root", "ip": "", "detail": "No NTP",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "pdf", results, "2026-08-01T00:00:00Z")
    html = att["data"].decode()
    assert "Corp" in html
    assert "4THealth" in html
    assert "fw-01" in html
```

- [ ] **Step 4: Run tests to confirm they all fail**

```bash
python -m pytest tests/test_device_review_scheduler.py -v 2>&1 | head -40
```
Expected: all tests fail with `ModuleNotFoundError: No module named 'app.device_review_scheduler'`

- [ ] **Step 5: Commit**

```bash
git add tests/test_device_review_scheduler.py device_review_jobs.example.json .gitignore
git commit -m "test: add TDD tests for device_review_scheduler; add gitignore and example file"
```

---

## Task 2: `app/device_review_scheduler.py`

**Files:**
- Create: `app/device_review_scheduler.py`

**Interfaces:**
- Consumes: `bulk_device_review_adom` imported lazily from `app.routes.device_review_routes` (Task 3); `send_email` from `app.smtp_client`
- Produces:
  - `get_all_jobs() -> list[dict]`
  - `create_job(data: dict) -> dict`
  - `update_job(job_id: str, data: dict) -> dict`
  - `delete_job(job_id: str) -> None`
  - `run_job_now(job_id: str) -> None`
  - `is_job_running(job_id: str) -> bool`
  - `init_scheduler(app) -> None`
  - `_execute_job(job_id: str) -> None` (internal, called by APScheduler and tests)
  - `_prune_runs(job_id: str, retention_days: int = 30) -> None` (internal, called by tests)
  - `_build_attachment_dr(adom, fmt, results, generated_at) -> dict` (internal, called by tests)
  - `_bulk_device_review_adom` module-level name (monkeypatched in tests — see Step 3)
  - `_send_email` module-level name (monkeypatched in tests — see Step 3)

- [ ] **Step 1: Create `app/device_review_scheduler.py`**

```python
"""Scheduled Device Review email export engine.

Jobs and run history are persisted in device_review_jobs.json (project root).
Each enabled job is registered as an APScheduler CronTrigger at startup.
"""

from __future__ import annotations

import csv
import datetime
import fcntl
import io
import json
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from app.atomic_io import atomic_write_json
from app.app_logger import app_log

_JOBS_PATH = Path(__file__).parent.parent / "device_review_jobs.json"
_lock = threading.Lock()
_scheduler = None  # BackgroundScheduler instance, set by init_scheduler
_running_jobs: set[str] = set()

_VALID_DAYS = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}


# ── Indirection points (monkeypatched in tests) ───────────────────────────────

def _bulk_device_review_adom(adom, checks, check_params, max_workers=4):
    from app.routes.device_review_routes import bulk_device_review_adom
    return bulk_device_review_adom(adom, checks, check_params, max_workers)


def _send_email(to, subject, body_html, attachments):
    from app.smtp_client import send_email
    send_email(to, subject, body_html, attachments)


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_job_fields(data: dict) -> None:
    days = data.get("days_of_week")
    if not isinstance(days, list) or not days:
        raise ValueError("days_of_week must be a non-empty list")
    invalid = [d for d in days if d not in _VALID_DAYS]
    if invalid:
        raise ValueError(
            f"days_of_week contains invalid codes: {invalid}. Must be from {sorted(_VALID_DAYS)}"
        )
    time_str = data.get("time", "")
    parts = time_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("time must be HH:MM format")
    if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
        raise ValueError("time HH must be 0-23, MM must be 0-59")


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if not _JOBS_PATH.exists():
        return []
    try:
        with open(_JOBS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(jobs: list[dict]) -> None:
    atomic_write_json(_JOBS_PATH, jobs)


# ── Public CRUD ───────────────────────────────────────────────────────────────

def get_all_jobs() -> list[dict]:
    with _lock:
        return _load()


def create_job(data: dict) -> dict:
    _validate_job_fields(data)
    job: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", "").strip(),
        "adom": data.get("adom", ""),
        "days_of_week": data["days_of_week"],
        "time": data["time"],
        "checks": data.get("checks") or [],
        "check_params": data.get("check_params") or {},
        "format": data.get("format", "pdf"),
        "email": data.get("email", ""),
        "enabled": bool(data.get("enabled", True)),
        "runs": [],
    }
    with _lock:
        jobs = _load()
        jobs.append(job)
        _save(jobs)
    if job["enabled"]:
        _register(job)
    return job


def update_job(job_id: str, data: dict) -> dict:
    _validate_job_fields(data)
    with _lock:
        jobs = _load()
        idx = next((i for i, j in enumerate(jobs) if j["id"] == job_id), None)
        if idx is None:
            raise KeyError(f"Job {job_id} not found")
        existing = jobs[idx]
        existing.update({
            "name": data.get("name", existing.get("name", "")).strip(),
            "adom": data.get("adom", existing["adom"]),
            "days_of_week": data["days_of_week"],
            "time": data["time"],
            "checks": data.get("checks") or [],
            "check_params": data.get("check_params") or {},
            "format": data.get("format", existing.get("format", "pdf")),
            "email": data.get("email", existing["email"]),
            "enabled": bool(data.get("enabled", True)),
        })
        jobs[idx] = existing
        _save(jobs)
    _unregister(job_id)
    if existing["enabled"]:
        _register(existing)
    return existing


def delete_job(job_id: str) -> None:
    with _lock:
        jobs = _load()
        new_jobs = [j for j in jobs if j["id"] != job_id]
        if len(new_jobs) == len(jobs):
            raise KeyError(f"Job {job_id} not found")
        _save(new_jobs)
    _unregister(job_id)


def run_job_now(job_id: str) -> None:
    t = threading.Thread(target=_execute_job, args=[job_id], daemon=True)
    t.start()


def is_job_running(job_id: str) -> bool:
    return job_id in _running_jobs


# ── Run history ───────────────────────────────────────────────────────────────

def _prune_runs(job_id: str, retention_days: int = 30) -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    with _lock:
        jobs = _load()
        for job in jobs:
            if job["id"] != job_id:
                continue
            job["runs"] = [
                r for r in job.get("runs", [])
                if datetime.datetime.fromisoformat(r["ran_at"].rstrip("Z")) >= cutoff
            ]
        _save(jobs)


def _append_run(job_id: str, record: dict) -> None:
    with _lock:
        jobs = _load()
        for job in jobs:
            if job["id"] == job_id:
                job.setdefault("runs", []).insert(0, record)
        _save(jobs)


# ── Lock helper ───────────────────────────────────────────────────────────────

def _try_acquire_job_lock(job_id: str):
    lock_path = Path(tempfile.gettempdir()) / f"4thealth_dr_{job_id}.lock"
    try:
        fh = open(lock_path, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


# ── Core execution ────────────────────────────────────────────────────────────

def _execute_job(job_id: str) -> None:
    lock_fh = _try_acquire_job_lock(job_id)
    if lock_fh is None:
        app_log("INFO", "device_review_scheduler",
                f"Job {job_id} already running — skipping")
        return
    _running_jobs.add(job_id)
    try:
        with _lock:
            jobs = _load()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            app_log("ERROR", "device_review_scheduler", f"Job {job_id} not found")
            return

        adom = job["adom"]
        fmt = job.get("format", "pdf")
        email = job["email"]
        checks = job.get("checks") or []
        check_params = job.get("check_params") or {}

        app_log("INFO", "device_review_scheduler",
                f"Running scheduled Device Review: adom={adom} format={fmt} to={email}")

        results = _bulk_device_review_adom(adom, checks, check_params, max_workers=4)

        all_rows = [r for dev in results for r in dev.get("rows", [])]
        fail_count = sum(
            1 for r in all_rows if r.get("result") in ("FAIL", "INSECURE")
        )

        record: dict[str, Any] = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "ok",
            "devices_total": len(results),
            "devices_reviewed": sum(1 for d in results if not d.get("error")),
            "total_findings": len(all_rows),
            "fail_count": fail_count,
        }

        generated_at = record["ran_at"]
        subject = f"4THealth Device Review — {adom} — {generated_at[:10]}"
        body_html = _build_summary_html(adom, results, generated_at)
        attachment = _build_attachment_dr(adom, fmt, results, generated_at)

        _send_email(email, subject, body_html, [attachment])
        _append_run(job_id, record)
        _prune_runs(job_id)
        app_log("INFO", "device_review_scheduler",
                f"Device Review report sent: adom={adom} devices={len(results)} "
                f"findings={len(all_rows)} fails={fail_count} to={email}")

    except Exception as exc:
        record = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "error",
            "error": str(exc),
        }
        _append_run(job_id, record)
        app_log("ERROR", "device_review_scheduler",
                f"Device Review scheduled job {job_id} failed: {exc}")
    finally:
        _running_jobs.discard(job_id)
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass


# ── Email builders ────────────────────────────────────────────────────────────

_RESULT_COLOR = {
    "PASS": "#166534",
    "FAIL": "#991b1b",
    "INSECURE": "#991b1b",
    "WARN": "#92400e",
    "CONFIG_MISSING": "#92400e",
    "INFO": "#1e40af",
}


def _build_summary_html(adom: str, results: list[dict], generated_at: str) -> str:
    all_rows = [r for dev in results for r in dev.get("rows", [])]
    by_check: dict[str, dict] = {}
    for row in all_rows:
        check = row.get("check", "Unknown")
        if check not in by_check:
            by_check[check] = {"PASS": 0, "FAIL": 0, "INSECURE": 0,
                                "WARN": 0, "CONFIG_MISSING": 0, "INFO": 0}
        result = row.get("result", "")
        if result in by_check[check]:
            by_check[check][result] += 1

    rows_html = ""
    for check, counts in sorted(by_check.items()):
        fail = counts["FAIL"] + counts["INSECURE"]
        warn = counts["WARN"] + counts["CONFIG_MISSING"]
        rows_html += (
            f"<tr><td style='padding:4px 8px'>{check}</td>"
            f"<td style='padding:4px 8px;color:#166534'>{counts['PASS']}</td>"
            f"<td style='padding:4px 8px;color:#991b1b'>{fail}</td>"
            f"<td style='padding:4px 8px;color:#92400e'>{warn}</td></tr>\n"
        )

    errors = [d["device"] for d in results if d.get("error")]
    error_note = ""
    if errors:
        error_note = (
            f"<p style='color:#991b1b'>Errors on devices: {', '.join(errors)}</p>"
        )

    return f"""
<h2 style="font-family:sans-serif">4THealth Device Review — {adom}</h2>
<p style="font-family:sans-serif;color:#6b7280">Generated: {generated_at}</p>
<p style="font-family:sans-serif">Devices scanned: {len(results)}</p>
{error_note}
<table style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
  <thead>
    <tr style="background:#f3f4f6">
      <th style="padding:4px 8px;text-align:left">Check</th>
      <th style="padding:4px 8px">Pass</th>
      <th style="padding:4px 8px">Fail/Insecure</th>
      <th style="padding:4px 8px">Warn</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
<p style="font-family:sans-serif;font-size:11px;color:#9ca3af;margin-top:16px">
  See attached report for full findings detail.
</p>"""


def _build_attachment_dr(
    adom: str, fmt: str, results: list[dict], generated_at: str
) -> dict:
    all_rows = [r for dev in results for r in dev.get("rows", [])]
    safe_adom = adom.replace(" ", "_")
    date_str = generated_at[:10]

    if fmt == "json":
        payload = json.dumps({
            "report_type": "device_review",
            "adom": adom,
            "exported_at": generated_at,
            "rows": all_rows,
        }, indent=2).encode()
        return {
            "filename": f"device_review_{safe_adom}_{date_str}.json",
            "data": payload,
            "mimetype": "application/json",
        }

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# 4THealth Device Review"])
        w.writerow([f"# ADOM: {adom}"])
        w.writerow([f"# Generated: {generated_at}"])
        w.writerow([])
        w.writerow(["Device", "Check", "Result", "Interface", "VDOM", "IP", "Detail"])
        for row in all_rows:
            w.writerow([
                row.get("device", ""),
                row.get("check", ""),
                row.get("result", ""),
                row.get("interface", ""),
                row.get("vdom", ""),
                row.get("ip", ""),
                row.get("detail", ""),
            ])
        return {
            "filename": f"device_review_{safe_adom}_{date_str}.csv",
            "data": buf.getvalue().encode(),
            "mimetype": "text/csv",
        }

    # pdf → styled HTML
    html = _build_pdf_html_dr(adom, all_rows, generated_at)
    return {
        "filename": f"device_review_{safe_adom}_{date_str}.html",
        "data": html.encode(),
        "mimetype": "text/html",
    }


def _build_pdf_html_dr(adom: str, rows: list[dict], generated_at: str) -> str:
    rows_html = ""
    for row in rows:
        color = _RESULT_COLOR.get(row.get("result", ""), "#374151")
        rows_html += (
            f"<tr>"
            f"<td>{row.get('device','')}</td>"
            f"<td>{row.get('check','')}</td>"
            f"<td style='color:{color};font-weight:600'>{row.get('result','')}</td>"
            f"<td>{row.get('interface','')}</td>"
            f"<td>{row.get('vdom','')}</td>"
            f"<td>{row.get('ip','')}</td>"
            f"<td>{row.get('detail','')}</td>"
            f"</tr>\n"
        )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body{{font-family:sans-serif;font-size:12px;color:#111}}
  h1{{font-size:18px;margin-bottom:4px}}
  .meta{{color:#6b7280;margin-bottom:16px;font-size:11px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #e5e7eb;padding:4px 8px;text-align:left}}
  th{{background:#f3f4f6;font-weight:600}}
  tr:nth-child(even){{background:#fafafa}}
</style>
</head>
<body>
<h1>4THealth Device Review Scheduler</h1>
<div class="meta">
  ADOM: {adom} &nbsp;|&nbsp;
  Devices scanned: {len({r.get('device') for r in rows})} &nbsp;|&nbsp;
  Total findings: {len(rows)} &nbsp;|&nbsp;
  Generated: {generated_at}
</div>
<table>
  <thead>
    <tr>
      <th>Device</th><th>Check</th><th>Result</th>
      <th>Interface</th><th>VDOM</th><th>IP</th><th>Detail</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</body>
</html>"""


# ── APScheduler integration ───────────────────────────────────────────────────

def _apscheduler_id(job_id: str) -> str:
    return f"dr_{job_id}"


def _register(job: dict) -> None:
    if _scheduler is None:
        return
    from apscheduler.triggers.cron import CronTrigger
    day_map = {
        "SUN": "sun", "MON": "mon", "TUE": "tue", "WED": "wed",
        "THU": "thu", "FRI": "fri", "SAT": "sat",
    }
    h, m = job["time"].split(":")
    day_str = ",".join(day_map[d] for d in job["days_of_week"])
    _scheduler.add_job(
        _execute_job,
        CronTrigger(day_of_week=day_str, hour=int(h), minute=int(m)),
        args=[job["id"]],
        id=_apscheduler_id(job["id"]),
        replace_existing=True,
    )


def _unregister(job_id: str) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_apscheduler_id(job_id))
    except Exception:
        pass


def init_scheduler(app) -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True)
    jobs = _load()
    for job in jobs:
        if job.get("enabled"):
            try:
                _register(job)
            except Exception as exc:
                app_log("ERROR", "device_review_scheduler",
                        f"Failed to register job {job.get('id','?')}: {exc}")
    _scheduler.start()
    app_log("INFO", "device_review_scheduler",
            f"Device Review scheduler started with "
            f"{sum(1 for j in jobs if j.get('enabled'))} active jobs")
```

- [ ] **Step 2: Run the tests**

```bash
python -m pytest tests/test_device_review_scheduler.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/device_review_scheduler.py
git commit -m "feat: add device_review_scheduler with APScheduler, CRUD, and email builders"
```

---

## Task 3: `bulk_device_review_adom()` in `device_review_routes.py`

**Files:**
- Modify: `app/routes/device_review_routes.py` (add function above the existing `device_review_run` route at line 243)
- Test is inline (existing test infrastructure)

**Interfaces:**
- Consumes: `_needed_data_keys()`, `_fetch_device_data()`, `run_checks()`, `make_client()`, `CHECKS_META` — all already in this file
- Produces:
  - `bulk_device_review_adom(adom: str, checks: list[str], check_params: dict, max_workers: int = 4) -> list[dict]`
  - Return shape: `[{"device": str, "ip": str, "rows": list[dict], "error": str | None}]`

- [ ] **Step 1: Write a test for `bulk_device_review_adom`**

Add to a new file `tests/test_bulk_device_review.py`:

```python
from unittest.mock import patch, MagicMock


def test_bulk_device_review_adom_aggregates(app_ctx):
    """bulk_device_review_adom returns one entry per device with rows and no error."""
    from app.routes.device_review_routes import bulk_device_review_adom

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get_devices.return_value = [
        {"name": "fw-01", "ip": "10.0.0.1", "conn_status": "up"},
        {"name": "fw-02", "ip": "10.0.0.2", "conn_status": "up"},
    ]
    mock_client.get_device_ntp.return_value = {}

    fake_row = {
        "device": "fw-01", "check": "NTP Configuration (CIS)", "result": "CONFIG_MISSING",
        "interface": "system", "vdom": "root", "ip": "", "detail": "no param",
        "protocols": [], "has_insecure": False, "has_secure": False,
    }

    with patch("app.routes.device_review_routes.make_client", return_value=mock_client):
        with patch("app.routes.device_review_routes.run_checks", return_value=[fake_row]):
            results = bulk_device_review_adom(
                "TEST", ["ntp_config"], {}, max_workers=2
            )

    assert len(results) == 2
    assert all("device" in r for r in results)
    assert all("rows" in r for r in results)
    assert all(r["error"] is None for r in results)
```

Note: `app_ctx` is a pytest fixture — check if it exists in `tests/conftest.py`. If not, add it there:
```python
import pytest
from app import create_app

@pytest.fixture
def app_ctx():
    app = create_app({"TESTING": True})
    with app.app_context():
        yield app
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
python -m pytest tests/test_bulk_device_review.py -v 2>&1 | head -20
```
Expected: `ImportError` — `cannot import name 'bulk_device_review_adom'`

- [ ] **Step 3: Add `bulk_device_review_adom` to `device_review_routes.py`**

Insert directly before the `# ── API: bulk run checks ──` comment at line 240 (after the `device_review_run_one` route ends at line 237):

```python
# ── Scheduler entry point (session-free) ─────────────────────────────────────


def bulk_device_review_adom(
    adom: str,
    checks: list[str] | None,
    check_params: dict,
    max_workers: int = 4,
) -> list[dict]:
    """Run device review checks against all devices in an ADOM.

    Designed for the scheduler — no Flask request context required.
    Returns list of {device, ip, rows, error}.
    """
    import concurrent.futures

    valid_keys = {c["key"] for c in CHECKS_META}
    if checks:
        checks = [k for k in checks if k in valid_keys]
    needed = _needed_data_keys(checks if checks else None)

    try:
        with make_client() as client:
            all_devices = client.get_devices(adom)
    except Exception as exc:
        app_log("ERROR", "device_review_routes",
                f"bulk_device_review_adom: get_devices failed for {adom}: {exc}")
        return []

    def _run_one(dev: dict) -> dict:
        name = dev.get("name", "")
        ip = dev.get("ip", dev.get("mgmt_ip", ""))
        try:
            with make_client() as c:
                device_data = _fetch_device_data(c, adom, name, needed, dev)
            rows = run_checks(name, device_data, checks if checks else None, check_params)
            return {"device": name, "ip": ip, "rows": rows, "error": None}
        except Exception as exc:
            app_log("ERROR", "device_review_routes",
                    f"bulk_device_review_adom: check failed for {name}: {exc}")
            return {"device": name, "ip": ip, "rows": [], "error": str(exc)}

    valid_devices = [d for d in all_devices if isinstance(d, dict) and d.get("name")]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, d): d for d in valid_devices}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    return results
```

Also add the missing import at the top of `device_review_routes.py` — check if `app_log` is already imported; if not add:
```python
from app.app_logger import app_log
```

- [ ] **Step 4: Run the test**

```bash
python -m pytest tests/test_bulk_device_review.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/device_review_routes.py tests/test_bulk_device_review.py
git commit -m "feat: add bulk_device_review_adom() for scheduler use"
```

---

## Task 4: Admin API endpoints

**Files:**
- Modify: `app/routes/admin_routes.py`

**Interfaces:**
- Consumes: `app.device_review_scheduler` — import as `_dr_sched` at top of file alongside `_sched`
- Produces: 6 new routes under `/admin/api/device-review/jobs/...`

- [ ] **Step 1: Add import at the top of `admin_routes.py`**

Find the existing import line (around line 10-20):
```python
from app import config_diff_scheduler as _sched
```
Add directly below it:
```python
from app import device_review_scheduler as _dr_sched
```

- [ ] **Step 2: Add the 6 endpoints**

Append at the end of `admin_routes.py` (after the last `admin_cdiff_jobs_status` function):

```python
# ── Device Review: Scheduled Jobs ─────────────────────────────────────────────


@bp.route("/api/device-review/jobs")
@_admin_required
def admin_dr_jobs_list():
    return jsonify(_dr_sched.get_all_jobs())


@bp.route("/api/device-review/jobs", methods=["POST"])
@_admin_required
def admin_dr_jobs_create():
    data = request.get_json(force=True) or {}
    try:
        job = _dr_sched.create_job(data)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job), 201


@bp.route("/api/device-review/jobs/<job_id>", methods=["PUT"])
@_admin_required
def admin_dr_jobs_update(job_id: str):
    data = request.get_json(force=True) or {}
    try:
        job = _dr_sched.update_job(job_id, data)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job)


@bp.route("/api/device-review/jobs/<job_id>", methods=["DELETE"])
@_admin_required
def admin_dr_jobs_delete(job_id: str):
    try:
        _dr_sched.delete_job(job_id)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True})


@bp.route("/api/device-review/jobs/<job_id>/run", methods=["POST"])
@_admin_required
def admin_dr_jobs_run(job_id: str):
    jobs = _dr_sched.get_all_jobs()
    if not any(j["id"] == job_id for j in jobs):
        return jsonify({"error": "Job not found"}), 404
    _dr_sched.run_job_now(job_id)
    return jsonify({"ok": True, "message": "Job started"}), 202


@bp.route("/api/device-review/jobs/<job_id>/status")
@_admin_required
def admin_dr_jobs_status(job_id: str):
    jobs = _dr_sched.get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    last_run = job["runs"][0] if job.get("runs") else None
    return jsonify({"running": _dr_sched.is_job_running(job_id), "last_run": last_run})
```

- [ ] **Step 3: Smoke-test the endpoints**

```bash
python -m pytest tests/ -v -k "admin" 2>&1 | tail -20
```
Confirm no import errors in the admin routes module.

- [ ] **Step 4: Commit**

```bash
git add app/routes/admin_routes.py
git commit -m "feat: add admin API endpoints for device review scheduled jobs"
```

---

## Task 5: Register scheduler in `app/__init__.py`

**Files:**
- Modify: `app/__init__.py`

**Interfaces:**
- Consumes: `device_review_scheduler.init_scheduler`

- [ ] **Step 1: Add the registration block**

In `app/__init__.py`, find the existing Config-Diff block (around line 133–145):
```python
    if not app.config.get("TESTING") and not app.config.get(
        "_CONFIG_DIFF_SCHEDULER_STARTED"
    ):
        app.config["_CONFIG_DIFF_SCHEDULER_STARTED"] = True
        try:
            from app.config_diff_scheduler import (
                init_scheduler as init_config_diff_scheduler,
            )
            with app.app_context():
                init_config_diff_scheduler(app)
        except Exception as exc:
            app.logger.warning("Config-Diff scheduler failed to start: %s", exc)
```

Add the following block immediately after it:
```python
    if not app.config.get("TESTING") and not app.config.get(
        "_DR_SCHEDULER_STARTED"
    ):
        app.config["_DR_SCHEDULER_STARTED"] = True
        try:
            from app.device_review_scheduler import (
                init_scheduler as init_dr_scheduler,
            )
            with app.app_context():
                init_dr_scheduler(app)
        except Exception as exc:
            app.logger.warning("Device Review scheduler failed to start: %s", exc)
```

- [ ] **Step 2: Verify the app starts without errors**

```bash
python -c "from app import create_app; app = create_app({'TESTING': True}); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/__init__.py
git commit -m "feat: register device_review_scheduler in app factory"
```

---

## Task 6: `admin.html` — rename tab and add Device Review Jobs section

**Files:**
- Modify: `app/templates/admin.html`

**Interfaces:**
- Consumes: `CHECKS_META` from the device review blueprint — passed as `checks` template variable; it is already available on the device review page but NOT on the admin page. We will pass `CHECKS_META` to the admin template via a context processor or template global. See Step 1 below.

- [ ] **Step 1: Pass CHECKS_META to the admin template**

In `app/routes/admin_routes.py`, find the admin page route (it will be something like `@bp.route("/admin")`). Add `checks_meta` to its render_template call:

```python
from app.device_review import CHECKS_META as _DR_CHECKS_META

@bp.route("")
@_admin_required
def admin_page():
    return render_template("admin.html", checks_meta=_DR_CHECKS_META)
```

If the route already passes other variables, just add `checks_meta=_DR_CHECKS_META`.

- [ ] **Step 2: Rename the tab button and panel id**

In `admin.html`, change line 16:
```html
  <button class="admin-tab" data-panel="config-diff">Config-Diff</button>
```
to:
```html
  <button class="admin-tab" data-panel="scheduled">Scheduled</button>
```

Change line 142:
```html
<div class="admin-panel" id="panel-config-diff">
```
to:
```html
<div class="admin-panel" id="panel-scheduled">
```

- [ ] **Step 3: Update the SMTP description to mention both job types**

Change line 147:
```html
    <p class="admin-panel-desc">Global email settings used by all scheduled Config-Delta exports.</p>
```
to:
```html
    <p class="admin-panel-desc">Global email settings used by all scheduled jobs (Config-Delta and Device Review).</p>
```

- [ ] **Step 4: Add the Device Review Jobs section**

Insert directly before the closing `</div>` of `panel-scheduled` (currently line 263, `</div>` after the jobs table):

```html
  <!-- Device Review Scheduled Jobs -->
  <div class="admin-panel-header" style="margin-top:2rem">
    <h3>Device Review Jobs</h3>
    <p class="admin-panel-desc">Each job runs CIS hardening checks against all devices in an ADOM and emails a report.</p>
  </div>
  <button class="btn-primary" onclick="showDRJobForm()" style="margin-bottom:12px">+ Add Job</button>

  <!-- Add/Edit inline form -->
  <div id="drJobForm" class="job-form-panel" style="display:none">
    <h4 style="margin:0 0 12px" id="drJobFormTitle">New Device Review Job</h4>
    <input type="hidden" id="drJobFormId">
    <div class="form-row">
      <label>Name</label>
      <input type="text" id="drJobFormName" placeholder="e.g. Weekly CIS Audit — Enterprise" style="min-width:280px">
    </div>
    <div class="form-row">
      <label>ADOM</label>
      <select id="drJobFormAdom" style="min-width:200px"></select>
    </div>
    <div class="form-row">
      <label>Day(s)</label>
      <div class="day-picker">
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-SUN" value="SUN"> Sun</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-MON" value="MON"> Mon</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-TUE" value="TUE"> Tue</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-WED" value="WED"> Wed</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-THU" value="THU"> Thu</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-FRI" value="FRI"> Fri</label>
        <label class="day-picker-item"><input type="checkbox" id="drDayChk-SAT" value="SAT"> Sat</label>
      </div>
    </div>
    <div class="form-row">
      <label>Time (24h)</label>
      <input type="time" id="drJobFormTime" value="06:00">
    </div>
    <div class="form-row" style="align-items:flex-start">
      <label style="padding-top:4px">Checks</label>
      <div id="drCheckList" style="display:flex;flex-direction:column;gap:4px;max-height:260px;overflow-y:auto;padding:4px 0">
        {% for check in checks_meta %}
        <label style="display:flex;align-items:center;gap:6px;font-size:.88rem;cursor:pointer">
          <input type="checkbox" name="drJobCheck" value="{{ check.key }}" checked
                 onchange="updateDRParamsPanel()">
          <span title="{{ check.description }}">{{ check.name }}</span>
        </label>
        {% endfor %}
      </div>
    </div>
    <div id="drParamsPanel" style="display:none;margin-left:0;margin-top:8px">
      <label style="font-size:.85rem;font-weight:600;color:var(--text-muted)">Check Parameters</label>
      <div id="drParamsFields" style="margin-top:6px"></div>
    </div>
    <div class="form-row">
      <label>Format</label>
      <select id="drJobFormFormat">
        <option value="pdf" selected>HTML (styled report)</option>
        <option value="csv">CSV</option>
        <option value="json">JSON</option>
      </select>
    </div>
    <div class="form-row">
      <label>Email To</label>
      <input type="text" id="drJobFormEmail" placeholder="alice@corp.com, bob@corp.com" style="min-width:280px">
    </div>
    <div class="form-row">
      <label>Enabled</label>
      <input type="checkbox" id="drJobFormEnabled" checked>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn-primary" onclick="saveDRJob()">Save</button>
      <button class="btn-secondary" onclick="cancelDRJobForm()">Cancel</button>
      <span id="drJobFormMsg" style="font-size:12px;align-self:center"></span>
    </div>
  </div>

  <!-- Device Review Jobs table -->
  <div style="overflow-x:auto;margin-top:12px">
    <table class="admin-table" id="drJobsTable">
      <thead>
        <tr>
          <th>Name</th><th>ADOM</th><th>Days</th><th>Time</th><th>Checks</th>
          <th>Format</th><th>Email</th><th>Last Run</th><th>Status</th><th>Actions</th>
        </tr>
      </thead>
      <tbody id="drJobsTableBody">
        <tr><td colspan="10" style="color:#6b7280;text-align:center">Loading…</td></tr>
      </tbody>
    </table>
  </div>
```

Also pass `checks_meta` as a JSON variable for JS use by adding inside the `<head>` or just before the closing `</body>` tag (pick whichever the existing `CHECK_DEFS` pattern uses in `device_review.html`). Add just before `</body>`:

```html
<script>
  const DR_CHECK_DEFS = {{ checks_meta | tojson }};
</script>
```

- [ ] **Step 5: Verify the template renders**

```bash
python -c "
from app import create_app
app = create_app({'TESTING': True})
with app.test_client() as c:
    from flask_login import FlaskLoginClient
    pass
print('template import OK')
"
```

Or just start the dev server briefly: `python wsgi.py` and navigate to `/admin` — confirm the "Scheduled" tab appears and the Device Review Jobs section renders.

- [ ] **Step 6: Commit**

```bash
git add app/templates/admin.html app/routes/admin_routes.py
git commit -m "feat: rename admin Config-Diff tab to Scheduled; add Device Review Jobs section"
```

---

## Task 7: `admin.js` — rename panel trigger and add Device Review Jobs UI

**Files:**
- Modify: `app/static/js/admin.js`

**Interfaces:**
- Consumes: `DR_CHECK_DEFS` (global set by admin.html in Task 6), `/admin/api/device-review/jobs/*` endpoints (Task 4), `/admin/api/adoms` (existing)
- Produces: full CRUD UI for Device Review jobs matching Config-Delta pattern

- [ ] **Step 1: Rename the panel-switch trigger**

On line 15:
```js
      if (btn.dataset.panel === 'config-diff') { loadSMTP(); loadJobs(); }
```
Change to:
```js
      if (btn.dataset.panel === 'scheduled') { loadSMTP(); loadJobs(); loadDRJobs(); }
```

- [ ] **Step 2: Append the Device Review Jobs JS at the end of `admin.js`** (before the closing `})();` of the IIFE)

```js
/* ── Device Review: Scheduled Jobs ─────────────────────────────────────────── */

let _drJobs = [];

async function loadDRJobs() {
  const res = await fetch('/admin/api/device-review/jobs');
  _drJobs = res.ok ? await res.json() : [];
  renderDRJobsTable();
}

function renderDRJobsTable() {
  const tbody = document.getElementById('drJobsTableBody');
  if (!tbody) return;
  if (!_drJobs.length) {
    tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text-muted);text-align:center">No scheduled jobs.</td></tr>';
    return;
  }
  const totalChecks = (DR_CHECK_DEFS || []).length;
  tbody.innerHTML = _drJobs.map(j => {
    const last  = j.runs && j.runs[0];
    const ts    = last ? new Date(last.ran_at).toLocaleString() : '—';
    const badge = !last
      ? '<span style="color:var(--text-muted)">Never</span>'
      : last.status === 'ok'
        ? `<span style="color:#166534;font-weight:600" title="Findings: ${last.total_findings||0} | Fails: ${last.fail_count||0}">OK</span>`
        : `<span style="color:var(--danger);font-weight:600" title="${escH(last.error||'')}">ERROR</span>`;
    const checksCount = j.checks && j.checks.length ? `${j.checks.length} / ${totalChecks}` : `All (${totalChecks})`;
    return `<tr>
      <td>${escH(j.name||'')}</td>
      <td>${escH(j.adom)}</td>
      <td>${(j.days_of_week||[]).map(d=>_DAY_LABELS[d]||d).join(', ')}</td>
      <td>${escH(j.time)}</td>
      <td>${escH(checksCount)}</td>
      <td>${escH(j.format === 'pdf' ? 'HTML' : (j.format||'').toUpperCase())}</td>
      <td>${escH(j.email)}</td>
      <td style="font-size:11px">${ts}</td>
      <td>${badge}</td>
      <td>
        <button class="btn-sm" onclick="editDRJob('${j.id}')">Edit</button>
        <button class="btn-sm" style="color:var(--danger)" onclick="deleteDRJob('${j.id}')">Delete</button>
        <button class="btn-sm" id="drRunBtn-${j.id}" onclick="runDRJobNow('${j.id}')">Run Now</button>
      </td>
    </tr>`;
  }).join('');
}

async function loadDRJobAdoms() {
  const sel = document.getElementById('drJobFormAdom');
  if (!sel) return;
  const res  = await fetch('/admin/api/adoms');
  const data = res.ok ? await res.json() : {};
  sel.innerHTML = (data.adoms || []).map(a => `<option value="${escH(a)}">${escH(a)}</option>`).join('');
}

function showDRJobForm(job) {
  document.getElementById('drJobFormTitle').textContent = job ? 'Edit Device Review Job' : 'New Device Review Job';
  document.getElementById('drJobFormId').value      = job ? job.id : '';
  document.getElementById('drJobFormName').value    = job ? (job.name||'') : '';
  document.getElementById('drJobFormAdom').value    = job ? job.adom : '';
  const activeDays = job ? (job.days_of_week || ['MON']) : ['MON'];
  _DAY_CODES.forEach(code => {
    const chk = document.getElementById('drDayChk-' + code);
    if (chk) chk.checked = activeDays.includes(code);
  });
  document.getElementById('drJobFormTime').value    = job ? job.time : '06:00';
  document.getElementById('drJobFormFormat').value  = job ? job.format : 'pdf';
  document.getElementById('drJobFormEmail').value   = job ? job.email : '';
  document.getElementById('drJobFormEnabled').checked = job ? !!job.enabled : true;

  // Restore check selections
  const savedChecks = job && job.checks && job.checks.length ? new Set(job.checks) : null;
  document.querySelectorAll('input[name="drJobCheck"]').forEach(cb => {
    cb.checked = savedChecks ? savedChecks.has(cb.value) : true;
  });

  // Restore param values
  if (job && job.check_params) {
    Object.entries(job.check_params).forEach(([checkKey, paramValues]) => {
      Object.entries(paramValues).forEach(([paramKey, val]) => {
        const inp = document.getElementById(`drAdminParam_${checkKey}_${paramKey}`);
        if (inp) inp.value = val;
      });
    });
  }

  document.getElementById('drJobFormMsg').textContent = '';
  document.getElementById('drJobForm').style.display = 'block';
  loadDRJobAdoms();
  updateDRParamsPanel();
}

function cancelDRJobForm() {
  document.getElementById('drJobForm').style.display = 'none';
}

function editDRJob(id) {
  const job = _drJobs.find(j => j.id === id);
  if (job) showDRJobForm(job);
}

function updateDRParamsPanel() {
  const checkedKeys = new Set(
    [...document.querySelectorAll('input[name="drJobCheck"]:checked')].map(cb => cb.value)
  );
  const panel  = document.getElementById('drParamsPanel');
  const fields = document.getElementById('drParamsFields');
  if (!panel || !fields) return;

  const active = (DR_CHECK_DEFS || []).filter(
    c => checkedKeys.has(c.key) && c.params_schema && c.params_schema.length > 0
  );

  if (!active.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';

  // Preserve typed values before rebuild
  const savedValues = {};
  fields.querySelectorAll('.dr-admin-param-input').forEach(inp => {
    savedValues[`${inp.dataset.checkKey}_${inp.dataset.paramKey}`] = inp.value;
  });

  fields.innerHTML = '';
  active.forEach(check => {
    check.params_schema.forEach(param => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:.6rem;margin-bottom:.5rem;flex-wrap:wrap';

      const lbl = document.createElement('label');
      lbl.style.cssText = 'min-width:180px;font-size:.88rem;font-weight:600;color:var(--text)';
      lbl.textContent = `${check.name} — ${param.label}:`;

      const inp = document.createElement('input');
      inp.type = 'text';
      inp.id   = `drAdminParam_${check.key}_${param.key}`;
      inp.dataset.checkKey  = check.key;
      inp.dataset.paramKey  = param.key;
      inp.placeholder = param.placeholder || '';
      inp.className   = 'form-control dr-admin-param-input';
      inp.style.cssText = 'max-width:360px;font-size:.88rem';

      const savedKey = `${check.key}_${param.key}`;
      if (savedValues[savedKey] !== undefined) inp.value = savedValues[savedKey];

      row.appendChild(lbl);
      row.appendChild(inp);
      fields.appendChild(row);
    });
  });
}

function _collectDRCheckParams() {
  const params = {};
  document.querySelectorAll('.dr-admin-param-input').forEach(inp => {
    const ck  = inp.dataset.checkKey;
    const pk  = inp.dataset.paramKey;
    const val = (inp.value || '').trim();
    if (!val) return;
    if (!params[ck]) params[ck] = {};
    params[ck][pk] = val;
  });
  return params;
}

async function saveDRJob() {
  const msg  = document.getElementById('drJobFormMsg');
  const id   = document.getElementById('drJobFormId').value;
  const selectedDays = _DAY_CODES.filter(code => {
    const chk = document.getElementById('drDayChk-' + code);
    return chk && chk.checked;
  });
  if (!selectedDays.length) {
    msg.style.color = 'var(--danger)';
    msg.textContent = 'Select at least one day.';
    return;
  }
  const selectedChecks = [...document.querySelectorAll('input[name="drJobCheck"]:checked')].map(cb => cb.value);
  const payload = {
    name:         document.getElementById('drJobFormName').value.trim(),
    adom:         document.getElementById('drJobFormAdom').value,
    days_of_week: selectedDays,
    time:         document.getElementById('drJobFormTime').value,
    checks:       selectedChecks,
    check_params: _collectDRCheckParams(),
    format:       document.getElementById('drJobFormFormat').value,
    email:        document.getElementById('drJobFormEmail').value.trim(),
    enabled:      document.getElementById('drJobFormEnabled').checked,
  };
  const url    = id ? `/admin/api/device-review/jobs/${id}` : '/admin/api/device-review/jobs';
  const method = id ? 'PUT' : 'POST';
  const res    = await fetch(url, { method,
    headers: {'Content-Type':'application/json','X-CSRF-Token': getCSRF()},
    body: JSON.stringify(payload) });
  if (res.ok) {
    cancelDRJobForm();
    loadDRJobs();
  } else {
    const err = await res.json().catch(() => ({}));
    msg.style.color = 'var(--danger)';
    msg.textContent = err.error || 'Save failed.';
  }
}

async function deleteDRJob(id) {
  if (!confirm('Delete this Device Review job?')) return;
  await fetch(`/admin/api/device-review/jobs/${id}`, { method: 'DELETE',
    headers: {'X-CSRF-Token': getCSRF()} });
  loadDRJobs();
}

async function runDRJobNow(id) {
  const btn = document.getElementById(`drRunBtn-${id}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  const runRes = await fetch(`/admin/api/device-review/jobs/${id}/run`, { method: 'POST',
    headers: {'X-CSRF-Token': getCSRF()} });
  if (!runRes.ok) {
    if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
    return;
  }
  const poll = setInterval(async () => {
    try {
      const res  = await fetch(`/admin/api/device-review/jobs/${id}/status`);
      const data = await res.json();
      if (!data.running) {
        clearInterval(poll);
        if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
        loadDRJobs();
      }
    } catch (_) {
      clearInterval(poll);
      if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
    }
  }, 3000);
}
```

- [ ] **Step 3: Verify no JS syntax errors**

Open the browser dev console on `/admin` and confirm no errors. Click the Scheduled tab — SMTP loads, Config-Delta jobs table loads, Device Review jobs table shows "No scheduled jobs."

- [ ] **Step 4: Commit**

```bash
git add app/static/js/admin.js
git commit -m "feat: add Device Review scheduled jobs UI to admin Scheduled panel"
```

---

## Task 8: CLAUDE.md and graphify update

**Files:**
- Modify: `CLAUDE.md`
- Run: `graphify update .`

- [ ] **Step 1: Update CLAUDE.md**

Find the `### Config-Diff Scheduled Exports` section and rename it to `### Scheduled Exports`. Update the description to cover both job types. Add a new subsection:

```markdown
#### Device Review Scheduled Jobs

`app/device_review_scheduler.py` — APScheduler-based scheduler mirroring `config_diff_scheduler.py`.

Persists jobs in `device_review_jobs.json` (gitignored; copy `device_review_jobs.example.json` to create).

**Job schema:**
```json
{
  "id": "uuid",
  "name": "Weekly CIS Audit",
  "adom": "Enterprise Services",
  "days_of_week": ["MON", "FRI"],
  "time": "02:00",
  "checks": ["ntp_config", "trusted_hosts"],
  "check_params": { "ntp_config": { "expected_servers": "10.1.1.1" } },
  "email": "alice@corp.com, bob@corp.com",
  "format": "pdf",
  "enabled": true,
  "runs": [...]
}
```

`checks`: list of check keys from `CHECKS_META`; empty list = run all 18.
`check_params`: only entries for parameterized checks; omitted keys = `CONFIG_MISSING`.
`email`: comma-separated string — `smtp_client._parse_recipients()` handles splitting.

**`bulk_device_review_adom(adom, checks, check_params, max_workers=4)`** in `app/routes/device_review_routes.py` — session-free entry point for the scheduler. Uses `ThreadPoolExecutor(max_workers=4)`.

**Admin API endpoints** (all `admin_required`):
- `GET /admin/api/device-review/jobs`
- `POST /admin/api/device-review/jobs`
- `PUT /admin/api/device-review/jobs/<id>`
- `DELETE /admin/api/device-review/jobs/<id>`
- `POST /admin/api/device-review/jobs/<id>/run`
- `GET /admin/api/device-review/jobs/<id>/status`
```

Also update the "Config-Diff" references to "Scheduled" wherever the admin tab is described.

- [ ] **Step 2: Run graphify update**

```bash
graphify update .
```

- [ ] **Step 3: Run the full test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -30
```
All tests should pass.

- [ ] **Step 4: Final commit**

```bash
git add CLAUDE.md graphify-out/
git commit -m "docs: update CLAUDE.md and graphify for scheduled device review jobs"
```

---

## Self-Review

**Spec coverage check:**
- [x] Admin tab renamed Config-Diff → Scheduled → Task 6
- [x] SMTP section unchanged → Tasks 6 (no SMTP changes)
- [x] Config-Delta email multi-recipient retrofit (UI only) → Task 7 uses comma-separated `email` field; backend already handles it
- [x] `device_review_scheduler.py` module → Task 2
- [x] `device_review_jobs.json` gitignored → Task 1
- [x] `device_review_jobs.example.json` committed → Task 1
- [x] `bulk_device_review_adom()` → Task 3
- [x] 6 admin API endpoints → Task 4
- [x] Register in `__init__.py` → Task 5
- [x] UI: Name, ADOM, Days, Time, Checks, Parameters, Format, Email, Enabled → Task 6+7
- [x] Parameters panel dynamic rendering → Task 7
- [x] Checks column shows count → Task 7 (`renderDRJobsTable`)
- [x] Run Now + polling → Task 7
- [x] TDD (tests before implementation) → Tasks 1→2, 3 have tests before code
- [x] CLAUDE.md updated → Task 8
- [x] graphify updated → Task 8

**Type consistency:**
- `bulk_device_review_adom` is defined in Task 3 and imported lazily in `_bulk_device_review_adom()` wrapper in Task 2 ✓
- `_send_email` wrapper in Task 2 matches monkeypatch target in Task 1 tests ✓
- `_prune_runs(job_id, retention_days=30)` signature matches test call `sched._prune_runs(job["id"], retention_days=30)` ✓
- `_build_attachment_dr` called with `(adom, fmt, results, generated_at)` in both `_execute_job` and tests ✓
- `DR_CHECK_DEFS` set in admin.html template, consumed by `updateDRParamsPanel()` in admin.js ✓
