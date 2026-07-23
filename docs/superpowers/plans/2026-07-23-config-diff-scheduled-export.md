# Config-Diff Scheduled Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `beforeunload` navigation guard to the Config-Delta bulk export, an SMTP email module, a server-side APScheduler-based weekly export engine, and an Admin "Config-Diff" sub-tab for managing SMTP settings and scheduled jobs.

**Architecture:** File-based persistence (`smtp_config.json`, `config_diff_jobs.json`) following the existing `app_settings.json` / `api_tokens.json` pattern. A new `app/smtp_client.py` wraps stdlib `smtplib`. A new `app/config_diff_scheduler.py` registers APScheduler cron jobs at startup (called from `app/__init__.py`), reusing the existing 10-worker `ThreadPoolExecutor` bulk-preview logic extracted from `pending_changes_routes.py`. The Admin UI gains a fourth sub-tab panel in `admin.html` + `admin.js`.

**Tech Stack:** Python stdlib `smtplib` + `email`, APScheduler 3.x (`BackgroundScheduler`, `CronTrigger`), Flask, vanilla JS (no new frontend deps).

## Global Constraints

- Python ≥ 3.11
- No new `pyproject.toml` dependencies — `smtplib`/`email` are stdlib; APScheduler is already installed
- All new JSON files are gitignored; example files committed alongside them
- All admin API routes decorated with `@_admin_required` (imported as `from app.decorators import admin_required as _admin_required`)
- Atomic JSON writes via `app.atomic_io.atomic_write_json`
- App log calls: `app_log(level, component, message, **extra)` from `app.app_logger`
- Run tests with: `pytest tests/ -v`
- `uv sync` to install deps, never `pip install`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/static/js/pending_changes.js` | Modify | Add `beforeunload` guard around bulk export |
| `app/smtp_client.py` | Create | SMTP send + test, stdlib only |
| `smtp_config.json` | Create (gitignored) | Runtime SMTP config |
| `smtp_config.example.json` | Create | Committed example |
| `app/config_diff_scheduler.py` | Create | Job engine: load/save/register/run |
| `config_diff_jobs.json` | Create (gitignored) | Runtime job + run-history store |
| `config_diff_jobs.example.json` | Create | Committed example |
| `app/routes/pending_changes_routes.py` | Modify | Extract `bulk_preview_adom()` helper |
| `app/routes/admin_routes.py` | Modify | Add SMTP + job CRUD routes |
| `app/templates/admin.html` | Modify | Add Config-Diff sub-tab panel |
| `app/static/js/admin.js` | Modify | Add SMTP form + jobs table JS |
| `app/__init__.py` | Modify | Wire `init_scheduler` call |
| `.gitignore` | Modify | Add new gitignored JSON files |
| `CHANGELOG.md` | Modify | Document new features |
| `docs/features.md` | Modify | Document Config-Diff admin tab + nav guard |
| `docs/api-reference.md` | Modify | Document new admin API endpoints |
| `docs/configuration.md` | Modify | Document smtp_config.json variables |
| `CLAUDE.md` | Modify | Add Config-Diff scheduler section |
| `tests/test_smtp_client.py` | Create | Unit tests for smtp_client |
| `tests/test_config_diff_scheduler.py` | Create | Unit tests for scheduler CRUD + pruning |

---

## Task 1: Navigation Guard on Bulk Export

**Files:**
- Modify: `app/static/js/pending_changes.js`

**Interfaces:**
- Consumes: existing `exportAllDevices(format)` function
- Produces: nothing new — side-effect only

- [ ] **Step 1: Locate the export start and end points**

Open `app/static/js/pending_changes.js`. Find `async function exportAllDevices(format)` (around line 458). Identify:
- The line where `bulkRunning = true` is set (early in the function, around line 470) — this is where to register the listener.
- All three exit points where `bulkRunning = false` is set (around lines 538–539) — these are where to remove the listener.

- [ ] **Step 2: Add the guard**

Add a module-level handler reference just after the `let bulkCancelled` declaration (around line 32):

```js
let _beforeUnloadHandler = null;
```

Inside `exportAllDevices`, immediately after `bulkRunning = true; bulkCancelled = false;` add:

```js
_beforeUnloadHandler = e => { e.preventDefault(); e.returnValue = ''; };
window.addEventListener('beforeunload', _beforeUnloadHandler);
```

At every `updateExportAllState()` call that ends the run (there are two — one in the catch block and one after the loop), add before it:

```js
if (_beforeUnloadHandler) { window.removeEventListener('beforeunload', _beforeUnloadHandler); _beforeUnloadHandler = null; }
```

- [ ] **Step 3: Manual test**

Start the dev server (`python wsgi.py`). Open the Config-Delta tab, select an ADOM, pick PDF, click Export All. While the progress counter is running, try to close or navigate to another tab. The browser should prompt "Leave site? Changes you made may not be saved." After the export completes, navigating away should produce no prompt.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "feat: add beforeunload guard during Config-Delta bulk export"
```

---

## Task 2: SMTP Client Module

**Files:**
- Create: `app/smtp_client.py`
- Create: `smtp_config.json` (gitignored)
- Create: `smtp_config.example.json`
- Modify: `.gitignore`
- Create: `tests/test_smtp_client.py`

**Interfaces:**
- Produces:
  - `load_smtp_config() -> dict` — returns config dict with keys: `host`, `port`, `tls_mode`, `username`, `password`, `from_address`, `run_history_days`, `enabled`
  - `save_smtp_config(cfg: dict) -> None`
  - `send_email(to: str, subject: str, body_html: str, attachments: list[dict] = []) -> None` — attachment dict: `{"filename": str, "data": bytes, "mimetype": str}`
  - `test_connection(to_address: str) -> dict` — returns `{"ok": True}` or `{"ok": False, "error": str}`

- [ ] **Step 1: Write failing tests**

Create `tests/test_smtp_client.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_load_smtp_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    cfg = smtp_client.load_smtp_config()
    assert cfg["port"] == 25
    assert cfg["tls_mode"] == "none"
    assert cfg["run_history_days"] == 30
    assert cfg["enabled"] is True


def test_save_and_reload_smtp_config(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "mail.internal", "port": 587, "tls_mode": "starttls",
                                   "username": "", "password": "", "from_address": "noreply@x.com",
                                   "run_history_days": 14, "enabled": True})
    cfg = smtp_client.load_smtp_config()
    assert cfg["host"] == "mail.internal"
    assert cfg["port"] == 587
    assert cfg["run_history_days"] == 14


def test_test_connection_returns_error_when_smtp_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "127.0.0.1", "port": 19999, "tls_mode": "none",
                                   "username": "", "password": "", "from_address": "test@x.com",
                                   "run_history_days": 30, "enabled": True})
    result = smtp_client.test_connection("dest@x.com")
    assert result["ok"] is False
    assert "error" in result


def test_send_email_raises_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "mail.internal", "port": 25, "tls_mode": "none",
                                   "username": "", "password": "", "from_address": "",
                                   "run_history_days": 30, "enabled": False})
    with pytest.raises(RuntimeError, match="SMTP not enabled"):
        smtp_client.send_email("x@x.com", "Test", "<p>hi</p>")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_smtp_client.py -v
```
Expected: `ModuleNotFoundError` or `AttributeError` (module doesn't exist yet).

- [ ] **Step 3: Create `smtp_config.example.json`**

```json
{
  "host": "",
  "port": 25,
  "tls_mode": "none",
  "username": "",
  "password": "",
  "from_address": "",
  "run_history_days": 30,
  "enabled": false
}
```

- [ ] **Step 4: Add `smtp_config.json` to `.gitignore`**

Add these two lines to `.gitignore` (alongside the existing `config_diff_jobs.json` entries you'll add in Task 3):

```
smtp_config.json
config_diff_jobs.json
```

- [ ] **Step 5: Create `app/smtp_client.py`**

```python
"""SMTP email client — wraps stdlib smtplib for 4THealth scheduled exports."""
from __future__ import annotations

import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from app.atomic_io import atomic_write_json

_CONFIG_PATH = Path(__file__).parent.parent / "smtp_config.json"
_lock = threading.Lock()

_DEFAULTS: dict = {
    "host": "",
    "port": 25,
    "tls_mode": "none",
    "username": "",
    "password": "",
    "from_address": "",
    "run_history_days": 30,
    "enabled": False,
}


def load_smtp_config() -> dict:
    import json
    with _lock:
        if not _CONFIG_PATH.exists():
            return dict(_DEFAULTS)
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except Exception:
            return dict(_DEFAULTS)


def save_smtp_config(cfg: dict) -> None:
    with _lock:
        atomic_write_json(_CONFIG_PATH, {**_DEFAULTS, **cfg})


def _build_message(cfg: dict, to: str, subject: str, body_html: str,
                   attachments: list[dict]) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = cfg.get("from_address") or cfg.get("host", "4thealth")
    msg["To"] = to
    msg.attach(MIMEText(body_html, "html"))
    for att in attachments:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(att["data"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=att["filename"])
        part.add_header("Content-Type", att["mimetype"])
        msg.attach(part)
    return msg


def _connect(cfg: dict) -> smtplib.SMTP:
    tls = cfg.get("tls_mode", "none")
    host = cfg["host"]
    port = int(cfg.get("port", 25))
    if tls == "ssl":
        conn = smtplib.SMTP_SSL(host, port, timeout=10)
    else:
        conn = smtplib.SMTP(host, port, timeout=10)
        if tls == "starttls":
            conn.starttls()
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    if username:
        conn.login(username, password)
    return conn


def send_email(to: str, subject: str, body_html: str,
               attachments: list[dict] | None = None) -> None:
    cfg = load_smtp_config()
    if not cfg.get("enabled"):
        raise RuntimeError("SMTP not enabled — configure SMTP in Admin → Config-Diff")
    if not cfg.get("host"):
        raise RuntimeError("SMTP host not configured")
    msg = _build_message(cfg, to, subject, body_html, attachments or [])
    conn = _connect(cfg)
    try:
        conn.sendmail(msg["From"], [to], msg.as_string())
    finally:
        try:
            conn.quit()
        except Exception:
            pass


def test_connection(to_address: str) -> dict:
    try:
        send_email(to_address, "4THealth SMTP Test",
                   "<p>SMTP connection test from 4THealth — if you received this, SMTP is working.</p>")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_smtp_client.py -v
```
Expected: 4 PASSED.

- [ ] **Step 7: Commit**

```bash
git add app/smtp_client.py smtp_config.example.json .gitignore tests/test_smtp_client.py
git commit -m "feat: add smtp_client module with send/test and file-based config"
```

---

## Task 3: Bulk Preview Helper Extraction

**Files:**
- Modify: `app/routes/pending_changes_routes.py`

**Interfaces:**
- Produces: `bulk_preview_adom(adom: str) -> list[dict]` — module-level function importable by the scheduler. Each dict: `{"device": str, "ip": str, "status": "ok"|"no_changes"|"error", "summary": dict, "vdoms": list, "raw": str, "error": str|None}`

- [ ] **Step 1: Write failing test**

Add to `tests/test_pending_changes.py` (or create a new file `tests/test_bulk_preview_helper.py`):

```python
def test_bulk_preview_adom_importable():
    from app.routes.pending_changes_routes import bulk_preview_adom
    assert callable(bulk_preview_adom)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_bulk_preview_helper.py -v
```
Expected: FAIL — `ImportError: cannot import name 'bulk_preview_adom'`.

- [ ] **Step 3: Extract the helper**

In `app/routes/pending_changes_routes.py`, add this function **above** the `@bp.route("/pending-changes")` decorator (around line 105). It consolidates device-list fetch + parallel preview into a single reusable callable:

```python
def bulk_preview_adom(adom: str) -> list[dict]:
    """Fetch install-preview diffs for every device in *adom* in parallel.

    Returns a list of result dicts — one per device — in the same shape the
    browser bulk-export uses:
      {"device", "ip", "status": "ok"|"no_changes"|"error",
       "summary", "vdoms", "raw", "error"}
    """
    from app.fmg_helpers import make_client
    from app.fmg_client import FMGError, parse_preview_diff

    with make_client() as client:
        raw_devices = client.get_devices_with_sync_status(adom)

    seen: set[str] = set()
    devices = []
    for d in raw_devices:
        if not isinstance(d, dict):
            continue
        name = d.get("name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        devices.append({"name": name,
                         "ip": d.get("ip", d.get("mgmt_ip", ""))})

    def _preview_one(dev: dict) -> dict:
        try:
            with make_client() as client:
                raw = client.get_install_preview(adom, dev["name"])
            parsed = parse_preview_diff(raw)
            if not any(v.get("changes") for v in parsed.get("vdoms", [])):
                return {"device": dev["name"], "ip": dev["ip"],
                        "status": "no_changes", "summary": {}, "vdoms": [], "raw": ""}
            return {"device": dev["name"], "ip": dev["ip"], "status": "ok",
                    "summary": parsed["summary"], "vdoms": parsed["vdoms"],
                    "raw": parsed["raw"], "error": None}
        except Exception as exc:
            return {"device": dev["name"], "ip": dev["ip"],
                    "status": "error", "summary": {}, "vdoms": [], "raw": "",
                    "error": str(exc)}

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_preview_one, d): d for d in devices}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_bulk_preview_helper.py -v
```
Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/routes/pending_changes_routes.py tests/test_bulk_preview_helper.py
git commit -m "refactor: extract bulk_preview_adom helper from pending_changes_routes"
```

---

## Task 4: Config-Diff Scheduler

**Files:**
- Create: `app/config_diff_scheduler.py`
- Create: `config_diff_jobs.example.json`
- Create: `tests/test_config_diff_scheduler.py`

**Interfaces:**
- Consumes: `bulk_preview_adom(adom)` from `app.routes.pending_changes_routes`, `send_email(to, subject, body_html, attachments)` from `app.smtp_client`
- Produces:
  - `init_scheduler(app) -> None`
  - `get_all_jobs() -> list[dict]`
  - `create_job(data: dict) -> dict` — returns job dict with assigned `id`
  - `update_job(job_id: str, data: dict) -> dict`
  - `delete_job(job_id: str) -> None`
  - `run_job_now(job_id: str) -> None` — fires in a daemon thread

- [ ] **Step 1: Write failing tests**

Create `tests/test_config_diff_scheduler.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    p = tmp_path / "config_diff_jobs.json"
    monkeypatch.setattr("app.config_diff_scheduler._JOBS_PATH", p)
    return p


def test_get_all_jobs_empty(jobs_path):
    from app import config_diff_scheduler as sched
    assert sched.get_all_jobs() == []


def test_create_job_assigns_id(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({
        "adom": "TEST", "day_of_week": "MON", "time": "06:00",
        "format": "pdf", "email": "x@x.com", "enabled": True
    })
    assert "id" in job
    assert len(sched.get_all_jobs()) == 1


def test_update_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    updated = sched.update_job(job["id"], {**job, "email": "new@x.com"})
    assert updated["email"] == "new@x.com"
    assert sched.get_all_jobs()[0]["email"] == "new@x.com"


def test_delete_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    sched.delete_job(job["id"])
    assert sched.get_all_jobs() == []


def test_prune_old_runs(jobs_path):
    from app import config_diff_scheduler as sched
    import datetime
    old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=40)).isoformat() + "Z"
    recent_ts = datetime.datetime.utcnow().isoformat() + "Z"
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    # Manually inject run history with one old and one recent entry
    jobs = json.loads(jobs_path.read_text())
    jobs[0]["runs"] = [
        {"ran_at": old_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 0},
        {"ran_at": recent_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 1},
    ]
    jobs_path.write_text(json.dumps(jobs))
    sched._prune_runs(job["id"], retention_days=30)
    remaining = sched.get_all_jobs()[0]["runs"]
    assert len(remaining) == 1
    assert remaining[0]["ran_at"] == recent_ts
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config_diff_scheduler.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `config_diff_jobs.example.json`**

```json
[]
```

- [ ] **Step 4: Create `app/config_diff_scheduler.py`**

```python
"""Scheduled Config-Delta email export engine.

Jobs and run history are persisted in config_diff_jobs.json (project root).
Each enabled job is registered as an APScheduler CronTrigger at startup.
"""
from __future__ import annotations

import datetime
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from app.atomic_io import atomic_write_json
from app.app_logger import app_log

_JOBS_PATH = Path(__file__).parent.parent / "config_diff_jobs.json"
_lock = threading.Lock()
_scheduler = None          # BackgroundScheduler instance, set by init_scheduler
_running_jobs: set[str] = set()   # job IDs currently executing (for status polling)


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
    job: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "adom": data["adom"],
        "day_of_week": data["day_of_week"],
        "time": data["time"],
        "format": data.get("format", "pdf"),
        "email": data["email"],
        "enabled": bool(data.get("enabled", True)),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "runs": [],
    }
    with _lock:
        jobs = _load()
        jobs.append(job)
        _save(jobs)
    if job["enabled"] and _scheduler is not None:
        _register(job)
    return job


def update_job(job_id: str, data: dict) -> dict:
    with _lock:
        jobs = _load()
        for i, j in enumerate(jobs):
            if j["id"] == job_id:
                jobs[i] = {**j,
                            "adom": data["adom"],
                            "day_of_week": data["day_of_week"],
                            "time": data["time"],
                            "format": data.get("format", "pdf"),
                            "email": data["email"],
                            "enabled": bool(data.get("enabled", True))}
                _save(jobs)
                updated = jobs[i]
                break
        else:
            raise KeyError(f"Job {job_id} not found")
    if _scheduler is not None:
        _unregister(job_id)
        if updated["enabled"]:
            _register(updated)
    return updated


def delete_job(job_id: str) -> None:
    with _lock:
        jobs = _load()
        jobs = [j for j in jobs if j["id"] != job_id]
        _save(jobs)
    if _scheduler is not None:
        _unregister(job_id)


def run_job_now(job_id: str) -> None:
    """Fire the job in a daemon thread; returns immediately."""
    t = threading.Thread(target=_execute_job, args=(job_id,),
                         name=f"config_diff_{job_id[:8]}", daemon=True)
    t.start()


# ── Run history ───────────────────────────────────────────────────────────────

def _prune_runs(job_id: str, retention_days: int | None = None) -> None:
    from app.smtp_client import load_smtp_config
    days = retention_days if retention_days is not None else load_smtp_config().get("run_history_days", 30)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    with _lock:
        jobs = _load()
        for j in jobs:
            if j["id"] == job_id:
                j["runs"] = [
                    r for r in j.get("runs", [])
                    if datetime.datetime.fromisoformat(r["ran_at"].rstrip("Z")) >= cutoff
                ]
        _save(jobs)


def _append_run(job_id: str, record: dict) -> None:
    with _lock:
        jobs = _load()
        for j in jobs:
            if j["id"] == job_id:
                j.setdefault("runs", []).insert(0, record)
        _save(jobs)


# ── Job execution ─────────────────────────────────────────────────────────────

def _execute_job(job_id: str) -> None:
    _running_jobs.add(job_id)
    try:
        with _lock:
            jobs = _load()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            app_log("ERROR", "config_diff_scheduler", f"Job {job_id} not found")
            return

        adom = job["adom"]
        fmt = job.get("format", "pdf")
        email = job["email"]

        app_log("INFO", "config_diff_scheduler",
                f"Running scheduled Config-Delta export: adom={adom} format={fmt} to={email}")

        from app.routes.pending_changes_routes import bulk_preview_adom
        results = bulk_preview_adom(adom)

        ok_count = sum(1 for r in results if r["status"] == "ok")
        record: dict[str, Any] = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "ok",
            "devices_total": len(results),
            "devices_with_changes": ok_count,
        }

        subject = f"4THealth Config-Delta — {adom} — {datetime.date.today()}"
        body_html = _build_summary_html(adom, results)
        attachment = _build_attachment(adom, fmt, results)

        from app.smtp_client import send_email
        send_email(email, subject, body_html, [attachment])

        _append_run(job_id, record)
        _prune_runs(job_id)
        app_log("INFO", "config_diff_scheduler",
                f"Config-Delta export sent: adom={adom} devices={len(results)} changes={ok_count} to={email}")

    except Exception as exc:
        record = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "error",
            "error": str(exc),
        }
        _append_run(job_id, record)
        app_log("ERROR", "config_diff_scheduler",
                f"Config-Delta scheduled export failed for job {job_id}: {exc}")
    finally:
        _running_jobs.discard(job_id)


def _build_summary_html(adom: str, results: list[dict]) -> str:
    ok = [r for r in results if r["status"] == "ok"]
    none_ = [r for r in results if r["status"] == "no_changes"]
    err = [r for r in results if r["status"] == "error"]
    rows = "".join(
        f'<tr><td>{r["device"]}</td><td>{r.get("ip","")}</td>'
        f'<td style="color:{"#166534" if r["status"]=="ok" else "#b91c1c" if r["status"]=="error" else "#6b7280"}">'
        f'{r["status"]}</td></tr>'
        for r in results
    )
    return (
        f"<h2>Config-Delta Export — {adom}</h2>"
        f"<p><strong>{len(results)}</strong> devices scanned | "
        f"<strong>{len(ok)}</strong> with changes | "
        f"<strong>{len(none_)}</strong> in sync | "
        f"<strong>{len(err)}</strong> errors</p>"
        f"<table border='1' cellpadding='4' cellspacing='0'>"
        f"<thead><tr><th>Device</th><th>IP</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<p>Full diff is attached.</p>"
    )


def _build_attachment(adom: str, fmt: str, results: list[dict]) -> dict:
    import csv, io
    date = datetime.date.today().isoformat()
    if fmt == "json":
        data = json.dumps({"adom": adom, "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
                            "results": results}, indent=2).encode()
        return {"filename": f"config-delta-{adom}-{date}.json",
                "data": data, "mimetype": "application/json"}
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["device", "ip", "status", "vdom", "type", "line"])
        for r in results:
            if r["status"] == "ok":
                for v in r.get("vdoms", []):
                    for c in v.get("changes", []):
                        w.writerow([r["device"], r.get("ip",""), r["status"], v["name"], c["type"], c["line"]])
            else:
                w.writerow([r["device"], r.get("ip",""), r["status"], "", "", r.get("error","")])
        return {"filename": f"config-delta-{adom}-{date}.csv",
                "data": buf.getvalue().encode(), "mimetype": "text/csv"}
    # default: pdf (HTML attachment)
    body = _build_pdf_html(adom, results)
    return {"filename": f"config-delta-{adom}-{date}.pdf.html",
            "data": body.encode(), "mimetype": "text/html"}


def _build_pdf_html(adom: str, results: list[dict]) -> str:
    def esc(s):
        return str(s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    sections = []
    for i, r in enumerate(results):
        pb = "page-break-before:always;" if i > 0 else ""
        if r["status"] == "no_changes":
            body = '<p style="color:#6b7280;font-style:italic">No pending changes.</p>'
        elif r["status"] == "error":
            body = f'<p style="color:#b91c1c">Error: {esc(r.get("error",""))}</p>'
        else:
            vdom_blocks = ""
            for v in r.get("vdoms", []):
                lines = "".join(
                    f'<span style="color:{"#166534" if c["type"]=="add" else "#b91c1c" if c["type"]=="remove" else "#92400e"};display:block">'
                    f'{esc(("+" if c["type"]=="add" else "-" if c["type"]=="remove" else "~") + " " + c["line"])}</span>'
                    for c in v.get("changes", [])
                )
                vdom_blocks += f'<strong>vdom: {esc(v["name"])}</strong><pre style="background:#f8f9fa;padding:8px;font-size:9px;white-space:pre-wrap">{lines}</pre>'
            body = vdom_blocks or '<p style="color:#6b7280;font-style:italic">No changes.</p>'
        sections.append(f'<div style="{pb}padding-top:1cm"><h2>{esc(r["device"])}</h2>'
                        f'<div style="color:#6b7280;font-size:10px">{esc(r.get("ip",""))}</div>{body}</div>')
    return (f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Config-Delta — {esc(adom)}</title>'
            f'<style>body{{font-family:Arial,sans-serif;font-size:11px;margin:1.5cm}}'
            f'h2{{font-size:14px}}@media print{{@page{{margin:1.2cm}}}}</style></head>'
            f'<body>{"".join(sections)}</body></html>')


# ── APScheduler integration ───────────────────────────────────────────────────

def _apscheduler_id(job_id: str) -> str:
    return f"config_diff_{job_id}"


def _register(job: dict) -> None:
    if _scheduler is None:
        return
    from apscheduler.triggers.cron import CronTrigger
    day_map = {"SUN": "sun", "MON": "mon", "TUE": "tue", "WED": "wed",
               "THU": "thu", "FRI": "fri", "SAT": "sat"}
    h, m = job["time"].split(":")
    _scheduler.add_job(
        _execute_job,
        CronTrigger(day_of_week=day_map[job["day_of_week"]], hour=int(h), minute=int(m)),
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


def is_job_running(job_id: str) -> bool:
    return job_id in _running_jobs


def init_scheduler(app) -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True)
    jobs = _load()
    for job in jobs:
        if job.get("enabled"):
            _register(job)
    _scheduler.start()
    app_log("INFO", "config_diff_scheduler",
            f"Config-Diff scheduler started with {sum(1 for j in jobs if j.get('enabled'))} active jobs")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_config_diff_scheduler.py -v
```
Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/config_diff_scheduler.py config_diff_jobs.example.json tests/test_config_diff_scheduler.py
git commit -m "feat: add config_diff_scheduler with APScheduler cron jobs and run history"
```

---

## Task 5: Wire Scheduler into App Factory

**Files:**
- Modify: `app/__init__.py`

**Interfaces:**
- Consumes: `init_scheduler` from `app.config_diff_scheduler`

- [ ] **Step 1: Locate the last scheduler init block**

Open `app/__init__.py`. Find the last `init_*_scheduler` call (around line 131 — `init_pending_status_scheduler`).

- [ ] **Step 2: Add the new init call after it**

```python
        try:
            from app.config_diff_scheduler import (
                init_scheduler as init_config_diff_scheduler,
            )
            with app.app_context():
                init_config_diff_scheduler(app)
        except Exception as exc:
            app.logger.warning("Config-Diff scheduler failed to start: %s", exc)
```

- [ ] **Step 3: Verify app starts cleanly**

```bash
python wsgi.py &
sleep 3 && curl -sk https://localhost:5443/login | grep -q "4THealth" && echo "OK"
kill %1
```
Expected: `OK` with no traceback in the server output.

- [ ] **Step 4: Commit**

```bash
git add app/__init__.py
git commit -m "feat: wire config_diff_scheduler into app factory"
```

---

## Task 6: Admin API Routes

**Files:**
- Modify: `app/routes/admin_routes.py`

**Interfaces:**
- Consumes: `load_smtp_config`, `save_smtp_config`, `test_connection` from `app.smtp_client`; `get_all_jobs`, `create_job`, `update_job`, `delete_job`, `run_job_now`, `is_job_running` from `app.config_diff_scheduler`

**New endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/api/smtp` | Get SMTP config (password masked) |
| PUT | `/admin/api/smtp` | Save SMTP config |
| POST | `/admin/api/smtp/test` | Send test email; body `{"to":"..."}` |
| GET | `/admin/api/config-diff/jobs` | List all jobs with run history |
| POST | `/admin/api/config-diff/jobs` | Create job |
| PUT | `/admin/api/config-diff/jobs/<id>` | Update job |
| DELETE | `/admin/api/config-diff/jobs/<id>` | Delete job |
| POST | `/admin/api/config-diff/jobs/<id>/run` | Trigger immediate run (202) |
| GET | `/admin/api/config-diff/jobs/<id>/status` | Poll run status; returns `{"running": bool, "last_run": {...}}` |

- [ ] **Step 1: Add imports at the top of `admin_routes.py`**

After the existing imports, add:

```python
from app import smtp_client as _smtp
from app import config_diff_scheduler as _sched
```

- [ ] **Step 2: Add SMTP routes**

Append to `admin_routes.py` (before the final `__all__` or at the end of the file):

```python
# ── Config-Diff: SMTP ─────────────────────────────────────────────────────────

@bp.route("/api/smtp")
@_admin_required
def admin_smtp_get():
    cfg = _smtp.load_smtp_config()
    cfg["password"] = "••••••" if cfg.get("password") else ""
    return jsonify(cfg)


@bp.route("/api/smtp", methods=["PUT"])
@_admin_required
def admin_smtp_put():
    data = request.get_json(force=True) or {}
    existing = _smtp.load_smtp_config()
    # Preserve saved password if the masked placeholder was submitted back
    if data.get("password") == "••••••":
        data["password"] = existing.get("password", "")
    _smtp.save_smtp_config(data)
    return jsonify({"ok": True})


@bp.route("/api/smtp/test", methods=["POST"])
@_admin_required
def admin_smtp_test():
    data = request.get_json(force=True) or {}
    to = (data.get("to") or "").strip()
    if not to:
        return jsonify({"ok": False, "error": "No recipient address provided"}), 400
    result = _smtp.test_connection(to)
    return jsonify(result)


# ── Config-Diff: Jobs ─────────────────────────────────────────────────────────

@bp.route("/api/config-diff/jobs")
@_admin_required
def admin_cdiff_jobs_list():
    return jsonify(_sched.get_all_jobs())


@bp.route("/api/config-diff/jobs", methods=["POST"])
@_admin_required
def admin_cdiff_jobs_create():
    data = request.get_json(force=True) or {}
    try:
        job = _sched.create_job(data)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(job), 201


@bp.route("/api/config-diff/jobs/<job_id>", methods=["PUT"])
@_admin_required
def admin_cdiff_jobs_update(job_id: str):
    data = request.get_json(force=True) or {}
    try:
        job = _sched.update_job(job_id, data)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(job)


@bp.route("/api/config-diff/jobs/<job_id>", methods=["DELETE"])
@_admin_required
def admin_cdiff_jobs_delete(job_id: str):
    try:
        _sched.delete_job(job_id)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True})


@bp.route("/api/config-diff/jobs/<job_id>/run", methods=["POST"])
@_admin_required
def admin_cdiff_jobs_run(job_id: str):
    jobs = _sched.get_all_jobs()
    if not any(j["id"] == job_id for j in jobs):
        return jsonify({"error": "Job not found"}), 404
    _sched.run_job_now(job_id)
    return jsonify({"ok": True, "message": "Job started"}), 202


@bp.route("/api/config-diff/jobs/<job_id>/status")
@_admin_required
def admin_cdiff_jobs_status(job_id: str):
    jobs = _sched.get_all_jobs()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    last_run = job["runs"][0] if job.get("runs") else None
    return jsonify({"running": _sched.is_job_running(job_id), "last_run": last_run})
```

- [ ] **Step 3: Verify routes appear**

```bash
python -c "from app import create_app; app = create_app(); rules = [str(r) for r in app.url_map.iter_rules() if 'smtp' in str(r) or 'config-diff' in str(r)]; print('\n'.join(rules))"
```
Expected: 9 routes printed including `/admin/api/smtp`, `/admin/api/smtp/test`, and all `/admin/api/config-diff/jobs*` variants.

- [ ] **Step 4: Commit**

```bash
git add app/routes/admin_routes.py
git commit -m "feat: add admin API routes for SMTP config and Config-Diff job CRUD"
```

---

## Task 7: Admin UI — Config-Diff Sub-tab

**Files:**
- Modify: `app/templates/admin.html`
- Modify: `app/static/js/admin.js`

- [ ] **Step 1: Add the tab button to `admin.html`**

Find the line:
```html
  <button class="admin-tab" data-panel="logs">Application Logs</button>
```
Insert before it:
```html
  <button class="admin-tab" data-panel="config-diff">Config-Diff</button>
```

- [ ] **Step 2: Add the panel HTML**

Find the opening tag of `<div class="admin-panel" id="panel-logs">` and insert the following block immediately before it:

```html
<div class="admin-panel" id="panel-config-diff">

  <!-- SMTP Configuration -->
  <div class="admin-panel-header">
    <h3>SMTP Configuration</h3>
    <p class="admin-panel-desc">Global email settings used by all scheduled Config-Delta exports.</p>
  </div>
  <div style="max-width:520px">
    <div class="form-row">
      <label>Host</label>
      <input type="text" id="smtpHost" placeholder="mail.internal.example.com">
    </div>
    <div class="form-row">
      <label>Port</label>
      <input type="number" id="smtpPort" value="25" style="width:100px">
    </div>
    <div class="form-row">
      <label>TLS Mode</label>
      <select id="smtpTls">
        <option value="none">None (plain)</option>
        <option value="starttls">STARTTLS (port 587)</option>
        <option value="ssl">SSL/TLS (port 465)</option>
      </select>
    </div>
    <div class="form-row">
      <label>Username <span style="font-weight:normal;color:#6b7280">(optional)</span></label>
      <input type="text" id="smtpUsername" placeholder="Leave blank for unauthenticated relay">
    </div>
    <div class="form-row">
      <label>Password <span style="font-weight:normal;color:#6b7280">(optional)</span></label>
      <input type="password" id="smtpPassword" placeholder="Leave blank for unauthenticated relay">
    </div>
    <div class="form-row">
      <label>From Address <span style="font-weight:normal;color:#6b7280">(optional)</span></label>
      <input type="text" id="smtpFrom" placeholder="4thealth@example.com">
    </div>
    <div class="form-row">
      <label>Run History Retention</label>
      <input type="number" id="smtpRetentionDays" value="30" style="width:80px"> days
    </div>
    <div class="form-row">
      <label>Enabled</label>
      <input type="checkbox" id="smtpEnabled">
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
      <button class="btn-primary" onclick="saveSMTP()">Save</button>
      <button class="btn-secondary" onclick="testSMTP()">Test</button>
      <input type="text" id="smtpTestTo" placeholder="Send test to..." style="width:220px">
      <span id="smtpMsg" style="font-size:12px"></span>
    </div>
  </div>

  <!-- Scheduled Jobs -->
  <div class="admin-panel-header" style="margin-top:2rem">
    <h3>Scheduled Exports</h3>
    <p class="admin-panel-desc">Each job fetches Config-Delta diffs for an entire ADOM and emails the results.</p>
  </div>
  <button class="btn-primary" onclick="showJobForm()" style="margin-bottom:12px">+ Add Job</button>

  <!-- Add/Edit inline form -->
  <div id="jobForm" style="display:none;background:#f3f4f6;border:1px solid #d1d5db;border-radius:6px;padding:16px;max-width:560px;margin-bottom:16px">
    <h4 style="margin:0 0 12px" id="jobFormTitle">New Scheduled Export</h4>
    <input type="hidden" id="jobFormId">
    <div class="form-row">
      <label>ADOM</label>
      <select id="jobFormAdom" style="min-width:200px"></select>
    </div>
    <div class="form-row">
      <label>Day of Week</label>
      <select id="jobFormDay">
        <option value="SUN">Sunday</option>
        <option value="MON">Monday</option>
        <option value="TUE">Tuesday</option>
        <option value="WED">Wednesday</option>
        <option value="THU">Thursday</option>
        <option value="FRI">Friday</option>
        <option value="SAT">Saturday</option>
      </select>
    </div>
    <div class="form-row">
      <label>Time (24h)</label>
      <input type="time" id="jobFormTime" value="06:00">
    </div>
    <div class="form-row">
      <label>Format</label>
      <select id="jobFormFormat">
        <option value="pdf" selected>PDF</option>
        <option value="csv">CSV</option>
        <option value="json">JSON</option>
      </select>
    </div>
    <div class="form-row">
      <label>Email To</label>
      <input type="email" id="jobFormEmail" placeholder="recipient@example.com" style="min-width:240px">
    </div>
    <div class="form-row">
      <label>Enabled</label>
      <input type="checkbox" id="jobFormEnabled" checked>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn-primary" onclick="saveJob()">Save</button>
      <button class="btn-secondary" onclick="cancelJobForm()">Cancel</button>
      <span id="jobFormMsg" style="font-size:12px;align-self:center"></span>
    </div>
  </div>

  <!-- Jobs table -->
  <div style="overflow-x:auto">
    <table class="admin-table" id="jobsTable">
      <thead>
        <tr>
          <th>ADOM</th><th>Day</th><th>Time</th><th>Format</th>
          <th>Email</th><th>Last Run</th><th>Status</th><th>Actions</th>
        </tr>
      </thead>
      <tbody id="jobsTableBody">
        <tr><td colspan="8" style="color:#6b7280;text-align:center">Loading…</td></tr>
      </tbody>
    </table>
  </div>

</div>
```

- [ ] **Step 3: Add JS to `admin.js`**

Append to the end of `app/static/js/admin.js`:

```js
/* ── Config-Diff: SMTP ───────────────────────────────────────────────────── */

async function loadSMTP() {
  const res = await fetch('/admin/api/smtp');
  if (!res.ok) return;
  const cfg = await res.json();
  document.getElementById('smtpHost').value          = cfg.host || '';
  document.getElementById('smtpPort').value          = cfg.port || 25;
  document.getElementById('smtpTls').value           = cfg.tls_mode || 'none';
  document.getElementById('smtpUsername').value      = cfg.username || '';
  document.getElementById('smtpPassword').value      = cfg.password || '';
  document.getElementById('smtpFrom').value          = cfg.from_address || '';
  document.getElementById('smtpRetentionDays').value = cfg.run_history_days || 30;
  document.getElementById('smtpEnabled').checked     = !!cfg.enabled;
}

async function saveSMTP() {
  const msg = document.getElementById('smtpMsg');
  const payload = {
    host:              document.getElementById('smtpHost').value.trim(),
    port:              parseInt(document.getElementById('smtpPort').value) || 25,
    tls_mode:          document.getElementById('smtpTls').value,
    username:          document.getElementById('smtpUsername').value.trim(),
    password:          document.getElementById('smtpPassword').value,
    from_address:      document.getElementById('smtpFrom').value.trim(),
    run_history_days:  parseInt(document.getElementById('smtpRetentionDays').value) || 30,
    enabled:           document.getElementById('smtpEnabled').checked,
  };
  const res = await fetch('/admin/api/smtp', { method: 'PUT',
    headers: {'Content-Type':'application/json', 'X-CSRFToken': getCSRF()},
    body: JSON.stringify(payload) });
  msg.style.color = res.ok ? '#166534' : '#b91c1c';
  msg.textContent = res.ok ? 'Saved.' : 'Save failed.';
  setTimeout(() => msg.textContent = '', 3000);
}

async function testSMTP() {
  const msg = document.getElementById('smtpMsg');
  const to  = document.getElementById('smtpTestTo').value.trim();
  if (!to) { msg.style.color='#b91c1c'; msg.textContent='Enter a test recipient first.'; return; }
  msg.style.color = '#6b7280'; msg.textContent = 'Sending…';
  const res  = await fetch('/admin/api/smtp/test', { method: 'POST',
    headers: {'Content-Type':'application/json', 'X-CSRFToken': getCSRF()},
    body: JSON.stringify({to}) });
  const data = await res.json();
  msg.style.color = data.ok ? '#166534' : '#b91c1c';
  msg.textContent = data.ok ? 'Test email sent!' : `Error: ${data.error}`;
}

/* ── Config-Diff: Jobs ───────────────────────────────────────────────────── */

let _cdiffJobs = [];

async function loadJobs() {
  const res = await fetch('/admin/api/config-diff/jobs');
  _cdiffJobs = res.ok ? await res.json() : [];
  renderJobsTable();
}

function renderJobsTable() {
  const tbody = document.getElementById('jobsTableBody');
  if (!tbody) return;
  if (!_cdiffJobs.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="color:#6b7280;text-align:center">No scheduled jobs.</td></tr>';
    return;
  }
  tbody.innerHTML = _cdiffJobs.map(j => {
    const last = j.runs && j.runs[0];
    const ts   = last ? new Date(last.ran_at).toLocaleString() : '—';
    const badge = !last ? '<span style="color:#6b7280">Never</span>'
      : last.status === 'ok'
        ? '<span style="color:#166534;font-weight:600">OK</span>'
        : `<span style="color:#b91c1c;font-weight:600" title="${escH(last.error||'')}">ERROR</span>`;
    return `<tr>
      <td>${escH(j.adom)}</td>
      <td>${escH(j.day_of_week)}</td>
      <td>${escH(j.time)}</td>
      <td>${escH(j.format.toUpperCase())}</td>
      <td>${escH(j.email)}</td>
      <td style="font-size:11px">${ts}</td>
      <td>${badge}</td>
      <td>
        <button class="btn-sm" onclick="editJob('${j.id}')">Edit</button>
        <button class="btn-sm btn-danger" onclick="deleteJob('${j.id}')">Delete</button>
        <button class="btn-sm" id="runBtn-${j.id}" onclick="runJobNow('${j.id}')">Run Now</button>
      </td>
    </tr>`;
  }).join('');
}

function escH(s) {
  return String(s||'').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadJobAdoms() {
  const sel = document.getElementById('jobFormAdom');
  if (!sel) return;
  const res = await fetch('/admin/api/adoms');
  const data = res.ok ? await res.json() : [];
  sel.innerHTML = data.map(a => `<option value="${escH(a.name)}">${escH(a.name)}</option>`).join('');
}

function showJobForm(job) {
  document.getElementById('jobFormTitle').textContent = job ? 'Edit Scheduled Export' : 'New Scheduled Export';
  document.getElementById('jobFormId').value      = job ? job.id : '';
  document.getElementById('jobFormAdom').value    = job ? job.adom : '';
  document.getElementById('jobFormDay').value     = job ? job.day_of_week : 'MON';
  document.getElementById('jobFormTime').value    = job ? job.time : '06:00';
  document.getElementById('jobFormFormat').value  = job ? job.format : 'pdf';
  document.getElementById('jobFormEmail').value   = job ? job.email : '';
  document.getElementById('jobFormEnabled').checked = job ? !!job.enabled : true;
  document.getElementById('jobFormMsg').textContent = '';
  document.getElementById('jobForm').style.display = 'block';
  loadJobAdoms();
}

function cancelJobForm() {
  document.getElementById('jobForm').style.display = 'none';
}

function editJob(id) {
  const job = _cdiffJobs.find(j => j.id === id);
  if (job) showJobForm(job);
}

async function saveJob() {
  const msg    = document.getElementById('jobFormMsg');
  const id     = document.getElementById('jobFormId').value;
  const payload = {
    adom:        document.getElementById('jobFormAdom').value,
    day_of_week: document.getElementById('jobFormDay').value,
    time:        document.getElementById('jobFormTime').value,
    format:      document.getElementById('jobFormFormat').value,
    email:       document.getElementById('jobFormEmail').value.trim(),
    enabled:     document.getElementById('jobFormEnabled').checked,
  };
  const url    = id ? `/admin/api/config-diff/jobs/${id}` : '/admin/api/config-diff/jobs';
  const method = id ? 'PUT' : 'POST';
  const res    = await fetch(url, { method,
    headers: {'Content-Type':'application/json','X-CSRFToken': getCSRF()},
    body: JSON.stringify(payload) });
  if (res.ok) {
    cancelJobForm();
    loadJobs();
  } else {
    const err = await res.json().catch(() => ({}));
    msg.style.color = '#b91c1c';
    msg.textContent = err.error || 'Save failed.';
  }
}

async function deleteJob(id) {
  if (!confirm('Delete this scheduled export?')) return;
  await fetch(`/admin/api/config-diff/jobs/${id}`, { method: 'DELETE',
    headers: {'X-CSRFToken': getCSRF()} });
  loadJobs();
}

async function runJobNow(id) {
  const btn = document.getElementById(`runBtn-${id}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  await fetch(`/admin/api/config-diff/jobs/${id}/run`, { method: 'POST',
    headers: {'X-CSRFToken': getCSRF()} });
  // Poll status every 3s until done
  const poll = setInterval(async () => {
    const res  = await fetch(`/admin/api/config-diff/jobs/${id}/status`);
    const data = await res.json();
    if (!data.running) {
      clearInterval(poll);
      if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
      loadJobs();
    }
  }, 3000);
}

function getCSRF() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}
```

- [ ] **Step 4: Wire panel load into tab-switch handler**

In `admin.js`, find the existing tab-switching code (look for `data-panel` or `adminTabs` click handler). In the block that runs when a panel becomes active, add a case for `config-diff`:

```js
if (panel === 'config-diff') { loadSMTP(); loadJobs(); }
```

- [ ] **Step 5: Manual test**

Start the dev server. Navigate to Admin → Config-Diff. Verify:
- SMTP form loads with defaults.
- Save button POPs a "Saved." message.
- Test button with a valid address sends (or shows a meaningful error if SMTP not configured).
- "Add Job" shows the inline form with ADOM dropdown populated.
- Saving a job adds it to the table.
- Edit / Delete work.
- "Run Now" disables the button, polls, and re-enables when done.

- [ ] **Step 6: Commit**

```bash
git add app/templates/admin.html app/static/js/admin.js
git commit -m "feat: add Config-Diff admin sub-tab with SMTP config and scheduled jobs UI"
```

---

## Task 8: Integration Testing

**Files:**
- Run: `tests/` (all existing + new tests)
- Manual: browser smoke-test

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests pass (no regressions to existing tests; all new tests from Tasks 2, 3, 4 pass).

- [ ] **Step 2: Verify app starts cleanly with all schedulers**

```bash
python wsgi.py &
sleep 3
curl -sk https://localhost:5443/login | grep -q "4THealth" && echo "APP OK"
kill %1
```
Expected: `APP OK` with no tracebacks in server output. Look specifically for the log line `Config-Diff scheduler started with X active jobs`.

- [ ] **Step 3: Test SMTP config UI**

1. Log in as admin, navigate to **Admin → Config-Diff**.
2. Verify SMTP form loads with defaults (port 25, TLS None, enabled unchecked).
3. Fill in your internal SMTP relay host, click **Save** → "Saved." message appears.
4. Click **Test** with a valid recipient → verify email received or a meaningful error shown inline.

- [ ] **Step 4: Test scheduled jobs UI**

1. Click **+ Add Job**.
2. Select an ADOM, day = Monday, time = 06:00, format = PDF, enter a valid email.
3. Click **Save** → job appears in table with "Never" last-run status.
4. Click **Edit** → form pre-fills with saved values. Change the email, save → table updates.
5. Click **Run Now** → button shows "Running…", poll completes, Last Run updates with OK or ERROR badge.
6. Check the **Logs** sub-tab → confirm a `config_diff_scheduler` INFO entry appears for the run.
7. Click **Delete** on the job → confirm dialog appears, job removed from table.

- [ ] **Step 5: Test navigation guard**

1. Navigate to **Config-Delta**, select an ADOM with many devices.
2. Click **Export All**.
3. While the progress counter is running, try to navigate to another tab in the app.
4. Browser should show a "Leave site?" confirmation dialog.
5. Let the export complete — navigating away afterwards should produce no prompt.

- [ ] **Step 6: Commit test results note**

No code changes expected. If any fixes were needed, commit them with descriptive messages before proceeding to Task 9.

---

## Task 9: Update Docs, CHANGELOG, CLAUDE.md, and Graphify

> Run after Task 8 integration testing passes with no open issues.

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/features.md`
- Modify: `docs/api-reference.md`
- Modify: `docs/configuration.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update `CHANGELOG.md`**

Insert a new entry at the top of the `[Unreleased]` section:

```markdown
## [Unreleased]

### Added
- **Config-Delta navigation guard** — a `beforeunload` browser confirmation dialog now fires if the user tries to navigate away or close the tab while a bulk export is in progress.
- **Scheduled Config-Delta exports** — admin users can create weekly scheduled jobs (ADOM, day, time, format, email recipient) that run server-side and email the full diff report as an attachment with an HTML summary in the body.
- **Admin → Config-Diff sub-tab** — new admin panel for managing SMTP settings (host, port, TLS, optional auth) with a test-send button, and a scheduled-jobs table with add/edit/delete/run-now controls and per-job run history (30-day retention by default).
```

- [ ] **Step 2: Update `docs/features.md`**

In the **Config-Delta** section, append:

```markdown
### Bulk Export — Navigation Guard

While an "Export All" bulk export is running, the browser will prompt for confirmation before navigating away or closing the tab, preventing accidental cancellation of a long-running export.

### Scheduled Exports (Admin)

Admins can configure weekly scheduled Config-Delta exports in **Admin → Config-Diff**. Each job specifies an ADOM, day of week, time, export format (PDF/CSV/JSON), and an email recipient. Jobs run server-side via APScheduler and email the full diff report as an attachment with a summary in the email body. Run history (last 30 days by default) is visible per job.
```

- [ ] **Step 3: Update `docs/api-reference.md`**

In the **Config-Delta** API section, append a new sub-section:

```markdown
#### Admin — SMTP Config

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/api/smtp` | Get SMTP configuration (password masked) |
| PUT | `/admin/api/smtp` | Save SMTP configuration |
| POST | `/admin/api/smtp/test` | Send a test email; body: `{"to": "..."}` |

#### Admin — Scheduled Config-Diff Jobs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/api/config-diff/jobs` | List all jobs with run history |
| POST | `/admin/api/config-diff/jobs` | Create a job |
| PUT | `/admin/api/config-diff/jobs/<id>` | Update a job |
| DELETE | `/admin/api/config-diff/jobs/<id>` | Delete a job |
| POST | `/admin/api/config-diff/jobs/<id>/run` | Trigger immediate run (returns 202) |
| GET | `/admin/api/config-diff/jobs/<id>/status` | Poll run status: `{"running": bool, "last_run": {...}}` |
```

- [ ] **Step 4: Update `docs/configuration.md`**

Add a new section **SMTP / Scheduled Exports**:

```markdown
## SMTP / Scheduled Exports

SMTP settings are stored in `smtp_config.json` (gitignored; copy from `smtp_config.example.json`). All fields are configurable via **Admin → Config-Diff**.

| Field | Default | Description |
|-------|---------|-------------|
| `host` | `""` | SMTP server hostname or IP |
| `port` | `25` | SMTP port |
| `tls_mode` | `"none"` | `"none"`, `"starttls"`, or `"ssl"` |
| `username` | `""` | Optional — leave blank for unauthenticated relay |
| `password` | `""` | Optional — leave blank for unauthenticated relay |
| `from_address` | `""` | Optional sender address |
| `run_history_days` | `30` | Days of per-job run history to retain |
| `enabled` | `false` | Must be `true` for any scheduled export to send email |

Scheduled jobs are stored in `config_diff_jobs.json` (gitignored; copy from `config_diff_jobs.example.json`). Jobs are registered with APScheduler at startup and survive server restarts.
```

- [ ] **Step 5: Update `CLAUDE.md`**

Add a new section after the **Config-Delta tab** section:

```markdown
### Config-Diff Scheduled Exports

`app/config_diff_scheduler.py` — APScheduler-based weekly export engine. Persists jobs and run history in `config_diff_jobs.json` (project root, gitignored). Registered in `app/__init__.py` alongside other background schedulers. Reuses `bulk_preview_adom()` from `app/routes/pending_changes_routes.py` for the actual FMG diff fetching.

`app/smtp_client.py` — stdlib `smtplib` wrapper. Config in `smtp_config.json` (project root, gitignored). `send_email()` raises on failure; `test_connection()` always returns a dict.

**Admin UI:** Admin → Config-Diff sub-tab. SMTP form + jobs table. JS in `app/static/js/admin.js`.

**Persistence pattern:** Same as `app_settings.json` / `api_tokens.json` — atomic JSON writes via `app/atomic_io.py`, threading.Lock for concurrent access.

**Run history pruning:** On each successful job execution, records older than `run_history_days` (default 30) are removed from `runs[]` in `config_diff_jobs.json`.
```

- [ ] **Step 6: Run graphify update**

```bash
graphify update .
```

- [ ] **Step 7: Commit everything**

```bash
git add CHANGELOG.md docs/features.md docs/api-reference.md docs/configuration.md CLAUDE.md graphify-out/
git commit -m "docs: update CHANGELOG, features, api-reference, configuration, and CLAUDE.md for Config-Diff scheduled exports"
```

---

## Task 10: Final Push to GitLab

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All existing tests pass; new tests pass.

- [ ] **Step 2: Smoke-test the full flow manually**

1. Start server: `python wsgi.py`
2. Log in as admin, navigate to Admin → Config-Diff.
3. Enter SMTP settings, click Save → "Saved." message appears.
4. Click Test with a real email address → verify receipt or see a meaningful error.
5. Add a scheduled job for any ADOM, day MON, time 06:00, format PDF.
6. Click Run Now on the job → button disables, re-enables after completion.
7. Check Last Run column shows a timestamp and OK/ERROR badge.
8. Navigate to Config-Delta, start an Export All, try navigating away → browser prompt appears.

- [ ] **Step 3: Push to GitLab**

```bash
git push origin development
```

---

## Self-Review Notes

- **Spec coverage verified:** All 6 spec sections implemented across tasks 1–8.
- **No placeholders:** All code blocks are complete and concrete.
- **Type consistency:** `bulk_preview_adom` signature used consistently in Task 3 (definition) and Task 4 (consumption). `send_email` attachment dict shape defined in Task 2 and used in Task 4.
- **`getCSRF()` in admin.js:** Added as a helper that reads the existing `<meta name="csrf-token">` tag — verify this meta tag is present in `admin.html`; if not, check how other admin JS calls get the CSRF token and match that pattern.
- **`btn-sm` / `btn-danger` CSS classes:** Used in the jobs table — verify these exist in `style.css` or substitute with whatever small-button classes the codebase uses.
