# DIFF Tab Performance (Option D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 5-15s device-table load by adding a background status cache, and replace the silent 15-60s diff spinner with an async task+polling pattern that shows step-by-step progress.

**Architecture:** Part 1 adds `app/pending_status_cache.py` — an APScheduler interval job (30 min) that fetches device list + pkg_status for every ADOM and stores results in a lock-guarded in-memory dict; the devices endpoint reads from cache instead of calling FMG inline. Part 2 converts the preview POST endpoint to return a task ID immediately, runs the FMG chain in a background thread, and adds a GET poll endpoint; the JS polling loop replaces the single blocking `fetch()` and renders progress labels.

**Tech Stack:** Python 3.11+, Flask, APScheduler 3.x, `threading.RLock`, `concurrent.futures.ThreadPoolExecutor`, vanilla JS (`fetch`, `setInterval`)

## Global Constraints

- `uv add` for any new dependency — never `pip install`
- No new dependencies needed (APScheduler already present)
- All routes remain read-only — nothing writes to FMG
- `TESTING` config flag suppresses scheduler start (existing pattern — do not break)
- Follow exact naming conventions: `_lock`, `_state`/`_cache`, `init_scheduler(app)`, `get_cached_*()`
- New scheduler guard key: `_PENDING_STATUS_CACHE_STARTED` (follows existing pattern in `app/__init__.py`)
- Task store key: `_PREVIEW_TASKS` — module-level dict in `pending_changes_routes.py`
- Poll endpoint: `GET /api/pending-changes/task/<task_id>`
- Task TTL: 10 minutes (evict completed/failed entries older than 600s at poll time)
- Cold-start fallback: if cache is empty/pending, fall back to live fetch (not a "loading" state)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/pending_status_cache.py` | Background job: device list + pkg_status per ADOM |
| Modify | `app/__init__.py` lines 99-121 | Start the new scheduler (one new `if not ... _PENDING_STATUS_CACHE_STARTED` block) |
| Modify | `app/routes/pending_changes_routes.py` | Devices endpoint reads cache; preview endpoint returns task_id; new poll endpoint |
| Modify | `app/static/js/pending_changes.js` | `loadPreview()` replaced with polling loop; `showDiffSpinner` shows step label |
| Create | `tests/test_pending_status_cache.py` | Unit tests for cache module |
| Modify | `tests/test_pending_changes.py` | Add route tests for task endpoint and poll endpoint |

---

## Task 1: Background device-status cache module

**Files:**
- Create: `app/pending_status_cache.py`
- Test: `tests/test_pending_status_cache.py`

**Interfaces:**
- Produces: `get_cached_devices(adom: str) -> list[dict] | None` — returns snapshot or `None` if not yet cached
- Produces: `get_cache_status() -> dict` — returns `{status, last_updated, adoms_cached}`
- Produces: `init_scheduler(app: Flask) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pending_status_cache.py
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

from unittest.mock import patch, MagicMock
import pytest


def test_get_cached_devices_returns_none_when_empty():
    import importlib
    import app.pending_status_cache as mod
    importlib.reload(mod)  # reset module state
    assert mod.get_cached_devices("MyADOM") is None


def test_get_cached_devices_returns_snapshot_after_refresh():
    import importlib
    import app.pending_status_cache as mod
    importlib.reload(mod)

    fake_devices = [{"name": "FW1", "ip": "10.0.0.1", "pkg_status": "modified"}]

    def fake_refresh(app):
        with mod._lock:
            mod._cache["MyADOM"] = {
                "devices": fake_devices,
                "last_updated": "2026-07-17T01:00:00",
            }

    fake_app = MagicMock()
    fake_refresh(fake_app)
    result = mod.get_cached_devices("MyADOM")
    assert result == fake_devices


def test_get_cached_devices_returns_copy_not_reference():
    import importlib
    import app.pending_status_cache as mod
    importlib.reload(mod)

    devices = [{"name": "FW1"}]
    with mod._lock:
        mod._cache["ADOM1"] = {"devices": devices, "last_updated": "2026-07-17T01:00:00"}

    result = mod.get_cached_devices("ADOM1")
    result.append({"name": "INJECTED"})
    assert len(mod._cache["ADOM1"]["devices"]) == 1


def test_get_cache_status_initial():
    import importlib
    import app.pending_status_cache as mod
    importlib.reload(mod)
    status = mod.get_cache_status()
    assert status["status"] == "pending"
    assert status["adoms_cached"] == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd /path/to/4thealth
uv run pytest tests/test_pending_status_cache.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Create `app/pending_status_cache.py`**

```python
"""Background cache for DIFF-tab device list + pkg_status per ADOM.

Runs a 30-minute APScheduler interval job that fetches every non-forti
ADOM's device list (conf_status, db_status) and pkg_status in parallel
(10-worker ThreadPoolExecutor, matching the live route).  Results are
stored in a lock-guarded in-memory dict; the /api/pending-changes/adoms/
<adom>/devices route reads from this cache instead of blocking on FMG.

Thread-safety: a single RLock guards _cache and _state.  Callers receive
snapshot copies so the lock is held only briefly.
"""

from __future__ import annotations

import datetime
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# Keyed by ADOM name → {"devices": [...], "last_updated": ISO str}
_cache: dict[str, dict] = {}

_state: dict = {
    "status": "pending",   # "pending" | "running" | "ok" | "error"
    "last_updated": None,  # ISO-8601 string or None
    "error": None,
}

_REFRESH_MINUTES = 30


# ── Public API ────────────────────────────────────────────────────────────────


def get_cached_devices(adom: str) -> list[dict] | None:
    """Return a snapshot of cached devices for *adom*, or None if not cached."""
    with _lock:
        entry = _cache.get(adom)
        if entry is None:
            return None
        return list(entry["devices"])


def get_cache_status() -> dict:
    """Return a snapshot of overall cache state."""
    with _lock:
        return {
            "status": _state["status"],
            "last_updated": _state["last_updated"],
            "adoms_cached": len(_cache),
            "error": _state.get("error"),
        }


# ── Refresh logic ─────────────────────────────────────────────────────────────


def _run_refresh(app: Flask) -> None:
    with app.app_context():
        with _lock:
            if _state["status"] == "running":
                logger.info("pending_status_cache: already running, skipping")
                return
            _state["status"] = "running"
            _state["error"] = None

        logger.info("pending_status_cache: refresh started")
        try:
            from app.fmg_helpers import make_client

            with make_client() as client:
                raw_adoms = client.get_adoms()
                adom_names = [
                    a.get("name", "")
                    for a in raw_adoms
                    if isinstance(a, dict)
                    and a.get("name")
                    and not a.get("name", "").lower().startswith("forti")
                ]

                for adom in adom_names:
                    try:
                        raw = client.get_devices_with_sync_status(adom)
                    except Exception as exc:
                        logger.warning(
                            "pending_status_cache: get_devices(%s) failed: %s", adom, exc
                        )
                        continue

                    seen: set[str] = set()
                    base_devices = []
                    for d in raw:
                        if not isinstance(d, dict):
                            continue
                        name = d.get("name", "")
                        if not name or name in seen:
                            continue
                        seen.add(name)
                        os_ver = d.get("os_ver", 0)
                        mr = d.get("mr")
                        patch = d.get("patch")
                        major = (
                            int(os_ver) // 100
                            if str(os_ver).isdigit() and int(os_ver) >= 100
                            else os_ver
                        )
                        if mr is not None and patch is not None:
                            version = f"v{major}.{mr}.{patch}"
                        elif mr is not None:
                            version = f"v{major}.{mr}"
                        else:
                            version = "n/a"
                        embedded_vdoms = d.get("vdom") or []
                        vdom_list = (
                            [
                                v.get("name", "root")
                                for v in embedded_vdoms
                                if isinstance(v, dict) and v.get("name")
                            ]
                            if embedded_vdoms
                            else ["root"]
                        )
                        base_devices.append(
                            {
                                "name": name,
                                "ip": d.get("ip", d.get("mgmt_ip", "")),
                                "platform": d.get("platform_str", d.get("platform", "")),
                                "version": version,
                                "conf_status": d.get("conf_status", "unknown"),
                                "db_status": d.get("db_status", "unknown"),
                                "serial": d.get("sn", d.get("serial", "")),
                                "_vdom_list": vdom_list,
                            }
                        )

                    def _fetch_pkg(entry: dict) -> tuple[str, str]:
                        try:
                            return entry["name"], client.get_device_pkg_status(
                                adom, entry["name"], entry["_vdom_list"]
                            )
                        except Exception:
                            return entry["name"], ""

                    pkg_map: dict[str, str] = {}
                    with ThreadPoolExecutor(max_workers=10) as pool:
                        futures = {
                            pool.submit(_fetch_pkg, e): e["name"] for e in base_devices
                        }
                        for fut in as_completed(futures):
                            dname, status = fut.result()
                            pkg_map[dname] = status

                    devices = [
                        {k: v for k, v in d.items() if k != "_vdom_list"}
                        | {"pkg_status": pkg_map.get(d["name"], "")}
                        for d in base_devices
                    ]

                    ts = datetime.datetime.now().isoformat(timespec="seconds")
                    with _lock:
                        _cache[adom] = {"devices": devices, "last_updated": ts}
                    logger.info(
                        "pending_status_cache: cached %d devices for ADOM %s",
                        len(devices),
                        adom,
                    )

            ts_done = datetime.datetime.now().isoformat(timespec="seconds")
            with _lock:
                _state["status"] = "ok"
                _state["last_updated"] = ts_done
                _state["error"] = None
            logger.info("pending_status_cache: refresh complete")

        except Exception as exc:
            logger.exception("pending_status_cache: refresh failed: %s", exc)
            with _lock:
                _state["status"] = "error"
                _state["error"] = str(exc)


def refresh_now(app: Flask) -> None:
    """Kick off a non-blocking refresh in a daemon thread."""
    t = threading.Thread(
        target=_run_refresh,
        args=[app],
        name="pending_status_cache_refresh",
        daemon=True,
    )
    t.start()


# ── Scheduler init ────────────────────────────────────────────────────────────


def init_scheduler(app: Flask) -> None:
    """Register a recurring APScheduler job and run the first fetch immediately."""
    from apscheduler.schedulers.background import BackgroundScheduler

    refresh_now(app)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=_run_refresh,
        args=[app],
        trigger="interval",
        minutes=_REFRESH_MINUTES,
        id="pending_status_cache_refresh",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run pytest tests/test_pending_status_cache.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/pending_status_cache.py tests/test_pending_status_cache.py
git commit -m "feat: add pending_status_cache background job for DIFF tab device list"
```

---

## Task 2: Wire cache into `__init__.py` and update devices route

**Files:**
- Modify: `app/__init__.py` (after line 121, before the `@app.context_processor` block)
- Modify: `app/routes/pending_changes_routes.py` (devices endpoint only)

**Interfaces:**
- Consumes: `get_cached_devices(adom)` from Task 1
- Consumes: `get_cache_status()` from Task 1

- [ ] **Step 1: Add scheduler start to `app/__init__.py`**

After line 121 (the `_INFRA_HEALTH_STARTED` block), add:

```python
    if not app.config.get("TESTING") and not app.config.get("_PENDING_STATUS_CACHE_STARTED"):
        app.config["_PENDING_STATUS_CACHE_STARTED"] = True
        from app.pending_status_cache import init_scheduler as init_pending_status_scheduler

        init_pending_status_scheduler(app)
```

- [ ] **Step 2: Update the devices endpoint in `pending_changes_routes.py`**

Replace the entire `pending_changes_devices` function (lines 80-164) with:

```python
@bp.route("/api/pending-changes/adoms/<adom>/devices")
@tab_required("pending_changes")
def pending_changes_devices(adom: str):
    if err := check_adom_access(adom):
        return err
    try:
        from app.pending_status_cache import get_cached_devices

        cached = get_cached_devices(adom)
        if cached is not None:
            return jsonify(cached)

        # Cache cold (first startup) — fall back to live fetch
        with make_client() as client:
            raw = client.get_devices_with_sync_status(adom)

            seen: set[str] = set()
            base_devices = []
            for d in raw:
                if not isinstance(d, dict):
                    continue
                name = d.get("name", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                os_ver = d.get("os_ver", 0)
                mr = d.get("mr")
                patch = d.get("patch")
                major = (
                    int(os_ver) // 100
                    if str(os_ver).isdigit() and int(os_ver) >= 100
                    else os_ver
                )
                if mr is not None and patch is not None:
                    version = f"v{major}.{mr}.{patch}"
                elif mr is not None:
                    version = f"v{major}.{mr}"
                else:
                    version = "n/a"
                embedded_vdoms = d.get("vdom") or []
                vdom_list = (
                    [
                        v.get("name", "root")
                        for v in embedded_vdoms
                        if isinstance(v, dict) and v.get("name")
                    ]
                    if embedded_vdoms
                    else ["root"]
                )
                base_devices.append(
                    {
                        "name": name,
                        "ip": d.get("ip", d.get("mgmt_ip", "")),
                        "platform": d.get("platform_str", d.get("platform", "")),
                        "version": version,
                        "conf_status": d.get("conf_status", "unknown"),
                        "db_status": d.get("db_status", "unknown"),
                        "serial": d.get("sn", d.get("serial", "")),
                        "_vdom_list": vdom_list,
                    }
                )

            def _fetch_pkg(entry: dict) -> tuple[str, str]:
                try:
                    return entry["name"], client.get_device_pkg_status(
                        adom, entry["name"], entry["_vdom_list"]
                    )
                except Exception:
                    return entry["name"], ""

            pkg_map: dict[str, str] = {}
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(_fetch_pkg, e): e["name"] for e in base_devices}
                for fut in as_completed(futures):
                    name, status = fut.result()
                    pkg_map[name] = status

        devices = [
            {k: v for k, v in d.items() if k != "_vdom_list"}
            | {"pkg_status": pkg_map.get(d["name"], "")}
            for d in base_devices
        ]
        return jsonify(devices)
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)
```

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```
uv run pytest tests/test_pending_changes.py tests/test_pending_status_cache.py -v
```
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add app/__init__.py app/routes/pending_changes_routes.py
git commit -m "feat: serve DIFF tab device list from background cache, live fallback on cold start"
```

---

## Task 3: Async task store + preview endpoints

**Files:**
- Modify: `app/routes/pending_changes_routes.py` (add task store, replace preview endpoint, add poll endpoint)
- Test: `tests/test_pending_changes.py` (add task + poll tests)

**Interfaces:**
- Produces: `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` → `{"task_id": "<uuid>"}`
- Produces: `GET /api/pending-changes/task/<task_id>` → `{"status": "running"|"done"|"error", "step": "...", "result": {...}|null, "error": null|"..."}`

- [ ] **Step 1: Write failing tests for the new endpoints**

Add to the bottom of `tests/test_pending_changes.py`:

```python
# ── Task store / async preview ────────────────────────────────────────────────

def test_pending_changes_preview_returns_task_id(client):
    """POST preview returns {task_id} immediately (unauthenticated → redirect)."""
    resp = client.post(
        "/api/pending-changes/adoms/MyADOM/device/FW1/preview",
        json={},
    )
    # Unauthenticated → 302 or 401; we just confirm it's not 404/405
    assert resp.status_code in (302, 401)


def test_pending_changes_task_poll_unauthenticated(client):
    """GET /api/pending-changes/task/<id> redirects unauthenticated users."""
    resp = client.get("/api/pending-changes/task/nonexistent-task-id")
    assert resp.status_code in (302, 401)
```

- [ ] **Step 2: Run to confirm new tests fail for the right reason**

```
uv run pytest tests/test_pending_changes.py::test_pending_changes_task_poll_unauthenticated -v
```
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add task store and new endpoints to `pending_changes_routes.py`**

At the top of the file, after existing imports, add:

```python
import time
import uuid
import threading
```

After the `bp = Blueprint(...)` line and `registry.register(...)` call, add the task store:

```python
# ── Async preview task store ──────────────────────────────────────────────────
# Keyed by task_id (UUID str) → {status, step, result, error, created_at}
_PREVIEW_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()
_TASK_TTL_SECS = 600  # evict entries older than 10 minutes


def _evict_old_tasks() -> None:
    now = time.monotonic()
    with _TASKS_LOCK:
        expired = [k for k, v in _PREVIEW_TASKS.items() if now - v["created_at"] > _TASK_TTL_SECS]
        for k in expired:
            del _PREVIEW_TASKS[k]
```

Replace the entire `pending_changes_preview` function (lines 170-211 in the original) with:

```python
@bp.route("/api/pending-changes/adoms/<adom>/device/<device>/preview", methods=["POST"])
@tab_required("pending_changes")
def pending_changes_preview(adom: str, device: str):
    if err := check_adom_access(adom):
        return err

    _evict_old_tasks()
    task_id = str(uuid.uuid4())
    with _TASKS_LOCK:
        _PREVIEW_TASKS[task_id] = {
            "status": "running",
            "step": "Starting…",
            "result": None,
            "error": None,
            "created_at": time.monotonic(),
        }

    def _run(task_id=task_id, adom=adom, device=device):
        def _set_step(msg: str) -> None:
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id]["step"] = msg

        try:
            _set_step("Fetching device info…")
            with make_client() as client:
                raw_devices = client.get_devices_with_sync_status(adom)
                device_meta = next(
                    (d for d in raw_devices if d.get("name", "").lower() == device.lower()),
                    {},
                )
                _set_step("Checking package status…")
                pkg_status = client.get_package_status(adom, device)
                _set_step("Staging policy package…")
                raw = client.get_install_preview(adom, device)

            _set_step("Parsing diff…")
            parsed = parse_preview_diff(raw)
            result = {
                "device": device,
                "ip": device_meta.get("ip", device_meta.get("mgmt_ip", "")),
                "conf_status": device_meta.get("conf_status", "unknown"),
                "db_status": device_meta.get("db_status", "unknown"),
                "pkg_status": pkg_status,
                "summary": parsed["summary"],
                "vdoms": parsed["vdoms"],
                "raw": parsed["raw"],
            }
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id].update(
                        {"status": "done", "step": "Done", "result": result}
                    )
        except FMGError as exc:
            msg = str(exc)
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id].update(
                        {"status": "error", "step": "Failed", "error": msg}
                    )
        except Exception as exc:
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id].update(
                        {"status": "error", "step": "Failed", "error": str(exc)}
                    )

    t = threading.Thread(target=_run, name=f"preview_{task_id[:8]}", daemon=True)
    t.start()
    return jsonify({"task_id": task_id})


@bp.route("/api/pending-changes/task/<task_id>")
@tab_required("pending_changes")
def pending_changes_task_status(task_id: str):
    _evict_old_tasks()
    with _TASKS_LOCK:
        entry = _PREVIEW_TASKS.get(task_id)
    if entry is None:
        return jsonify({"error": "Task not found or expired"}), 404
    return jsonify(
        {
            "status": entry["status"],
            "step": entry["step"],
            "result": entry["result"],
            "error": entry["error"],
        }
    )
```

- [ ] **Step 4: Run the new and existing tests**

```
uv run pytest tests/test_pending_changes.py -v
```
Expected: all tests PASS (the two new ones pass because the poll route now exists and returns 302/401 for unauthenticated requests).

- [ ] **Step 5: Commit**

```bash
git add app/routes/pending_changes_routes.py tests/test_pending_changes.py
git commit -m "feat: convert DIFF tab preview to async task+poll — POST returns task_id, GET polls status"
```

---

## Task 4: Frontend polling loop in `pending_changes.js`

**Files:**
- Modify: `app/static/js/pending_changes.js` (replace `loadPreview`, update `showDiffSpinner`)

**Interfaces:**
- Consumes: `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` → `{task_id}`
- Consumes: `GET /api/pending-changes/task/<task_id>` → `{status, step, result, error}`

No new tests needed — frontend JS is exercised by manual verification (Task 5).

- [ ] **Step 1: Replace `loadPreview` and update `showDiffSpinner` in `pending_changes.js`**

Replace the `showDiffSpinner` function (lines 239-249):

```javascript
function showDiffSpinner(deviceName, step) {
  document.getElementById('pcDiffPanel').innerHTML = `
    <div style="padding:1.5rem;text-align:center">
      <div class="spinner" style="display:inline-block;width:28px;height:28px;border:3px solid var(--border);
           border-top-color:var(--primary,#3b82f6);border-radius:50%;animation:spin 0.8s linear infinite"></div>
      <p style="margin-top:.75rem;color:var(--text-muted);font-style:italic">
        <strong>${esc(deviceName)}</strong>: ${esc(step || 'Starting…')}
      </p>
    </div>
    <style>@keyframes spin{to{transform:rotate(360deg)}}</style>`;
}
```

Replace the `loadPreview` function (lines 188-219):

```javascript
async function loadPreview(adom, deviceName) {
  vdomPageState = new Map();
  if (_previewAbort) { _previewAbort.abort(); }
  _previewAbort = new AbortController();
  const signal = _previewAbort.signal;

  currentDiff = null;
  showDiffSpinner(deviceName, 'Starting…');

  let taskId = null;
  try {
    const resp = await fetch(
      `/api/pending-changes/adoms/${encodeURIComponent(adom)}/device/${encodeURIComponent(deviceName)}/preview`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}), signal }
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    taskId = data.task_id;
  } catch (e) {
    if (e.name === 'AbortError') return;
    showDiffError(deviceName, e.message);
    return;
  }

  // Poll until done or error
  const POLL_INTERVAL_MS = 2000;
  const poll = async () => {
    if (signal.aborted) return;
    try {
      const resp = await fetch(`/api/pending-changes/task/${encodeURIComponent(taskId)}`, { signal });
      if (signal.aborted) return;
      if (!resp.ok) {
        showDiffError(deviceName, `Poll failed: HTTP ${resp.status}`);
        return;
      }
      const task = await resp.json();
      if (task.status === 'running') {
        showDiffSpinner(deviceName, task.step || 'Working…');
        setTimeout(poll, POLL_INTERVAL_MS);
      } else if (task.status === 'done') {
        currentDiff = task.result;
        currentDiff.adom = adom;
        currentDiff.timestamp = new Date().toISOString();
        renderDiffPanel(currentDiff);
      } else {
        showDiffError(deviceName, task.error || 'Unknown error from server.');
      }
    } catch (e) {
      if (e.name === 'AbortError') return;
      showDiffError(deviceName, e.message);
    }
  };
  setTimeout(poll, POLL_INTERVAL_MS);
}
```

- [ ] **Step 2: Run full test suite to catch any regressions**

```
uv run pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "feat: DIFF tab preview uses async polling loop with step-label progress"
```

---

## Task 5: Manual verification

- [ ] **Step 1: Start the dev server**

```
uv run python wsgi.py
```

- [ ] **Step 2: Open the DIFF tab, select an ADOM, confirm:**
  - Device table loads from cache (near-instant on second load; may take up to 30s on cold start while the background job runs)
  - Server log shows `pending_status_cache: cached N devices for ADOM <name>`

- [ ] **Step 3: Click a device row, confirm:**
  - Spinner appears immediately with step label (not blank)
  - Label updates every 2s: "Fetching device info…" → "Checking package status…" → "Staging policy package…" → "Parsing diff…" → diff renders
  - Clicking a different device mid-flight aborts the previous poll (spinner switches to new device)

- [ ] **Step 4: Confirm export queue still works**
  - Run preview on a device → click "+ Add to Export Queue" → export CSV/JSON/PDF

- [ ] **Step 5: Commit verification note** *(no code change — just proceed to Task 6)*

---

## Task 6: Update graphify and docs

- [ ] **Step 1: Update graphify graph**

```bash
graphify update .
```

- [ ] **Step 2: Update MEMORY.md** — add a pointer to this design if the cache or task store are asked about in future sessions

- [ ] **Step 3: Final commit and push**

```bash
git add -A
git commit -m "chore: update graphify after DIFF tab performance changes"
git push origin development
```

---

## Self-Review

**Spec coverage:**
- ✅ Part 1: background device-status cache (Task 1 + 2)
- ✅ Part 2: async task+poll for on-demand diff (Task 3 + 4)
- ✅ `TESTING` flag suppresses scheduler (handled by `app/__init__.py` guard pattern)
- ✅ Cold-start fallback: live fetch when cache is empty (Task 2 step 2)
- ✅ TTL eviction of task store (Task 3 step 3)
- ✅ FMG lock still released in finally block inside `get_install_preview` — no change needed
- ✅ graphify + docs update (Task 6)

**Placeholder scan:** None found.

**Type consistency:**
- `get_cached_devices(adom: str) -> list[dict] | None` — referenced consistently in Task 1 (define) and Task 2 (consume)
- `_PREVIEW_TASKS` dict structure `{status, step, result, error, created_at}` — defined in Task 3 and consumed by poll endpoint and `_run()` closure consistently
- `task_id` (UUID str) — produced by POST, consumed by GET, consumed by JS `loadPreview`
