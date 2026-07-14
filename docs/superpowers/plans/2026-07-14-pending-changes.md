# Pending Changes Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Pending Changes" tab to 4THealth that shows CLI-format install diffs from FortiManager, with an export queue for change records.

**Architecture:** A new Flask blueprint (`pending_changes_routes.py`) registers three API endpoints and one page route. Two new methods on `FMGClient` handle device listing with sync status and async install preview generation (trigger → poll task → fetch result). A vanilla-JS frontend manages a device list, diff viewer, and export queue — following the exact same patterns as the existing Device Review tab.

**Tech Stack:** Python/Flask, FortiManager JSON-RPC API, vanilla JS, Jinja2, pytest.

## Global Constraints

- Branch: `pending-change` (already checked out)
- All FortiManager access is **read-only** — no write or install calls; preview only
- `FMGClient` methods added to `app/fmg_client.py` using `self._post()` / existing `_get()` pattern
- New blueprint added to `_BLUEPRINT_MODULES` in `app/__init__.py`
- Tab key: `pending_changes` — registered via `registry.register()`
- ADOM access guard: `check_adom_access(adom)` first line of every ADOM-scoped route
- Error handling: `FMGError` → `upstream_api_error(...)`, `Exception` → `internal_api_error(...)`
- All ADOM lists strip names that start with `"forti"` (case-insensitive)
- `make_client()` from `app.fmg_helpers` — never instantiate `FMGClient` directly in routes
- Tests live in `tests/` and use `pytest`; run with `uv run pytest tests/ -v`
- Test before every commit; do not commit failing tests
- Push to GitLab only when all tests pass

---

## File Map

| Status | File | Purpose |
|--------|------|---------|
| Create | `app/routes/pending_changes_routes.py` | Blueprint + 3 API endpoints + 1 page route |
| Create | `app/templates/pending_changes.html` | Jinja2 page (extends base.html) |
| Create | `app/static/js/pending_changes.js` | Frontend: device list, diff render, export queue, exports |
| Create | `tests/test_pending_changes.py` | Unit + smoke tests for new routes and FMG methods |
| Modify | `app/fmg_client.py` | Add `get_devices_with_sync_status()` and `get_install_preview()` |
| Modify | `app/__init__.py` | Add `"app.routes.pending_changes_routes"` to `_BLUEPRINT_MODULES` |
| Modify | `CLAUDE.md` | Add Pending Changes tab documentation section |

---

## Task 1: Add FMGClient methods

**Files:**
- Modify: `app/fmg_client.py` (append after `get_devices()` at line 221)
- Test: `tests/test_pending_changes.py` (create)

**Interfaces:**
- Produces: `FMGClient.get_devices_with_sync_status(adom: str) -> list[dict]`
- Produces: `FMGClient.get_install_preview(adom: str, device: str) -> str`
- Produces: `parse_preview_diff(raw: str) -> dict` (module-level helper in `fmg_client.py`)

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pending_changes.py`:

```python
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

import time
from unittest.mock import patch, MagicMock, call
import pytest

from app.fmg_client import FMGClient, FMGError


# ── get_devices_with_sync_status ─────────────────────────────────────────────

def _make_client():
    return FMGClient(host="fmg.example.com", token="tok")


def test_get_devices_with_sync_status_returns_normalized_conf_status():
    client = _make_client()
    raw_devices = [
        {"name": "FW1", "ip": "10.0.0.1", "conf_status": 1, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT001"},
        {"name": "FW2", "ip": "10.0.0.2", "conf_status": 2, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT002"},
        {"name": "FW3", "ip": "10.0.0.3", "conf_status": 0, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT003"},
    ]
    with patch.object(client, "_get", return_value=raw_devices):
        result = client.get_devices_with_sync_status("MyADOM")
    assert len(result) == 3
    assert result[0]["conf_status"] == "insync"
    assert result[1]["conf_status"] == "outofsync"
    assert result[2]["conf_status"] == "unknown"


def test_get_devices_with_sync_status_empty_adom():
    client = _make_client()
    with patch.object(client, "_get", return_value=[]):
        result = client.get_devices_with_sync_status("EmptyADOM")
    assert result == []


# ── get_install_preview ───────────────────────────────────────────────────────

def _mock_post_sequence(client, responses):
    """Patch _post to return responses in order."""
    mock = MagicMock(side_effect=responses)
    client._post = mock
    return mock


def _task_response(percent, state=0):
    return {"result": [{"status": {"code": 0}, "data": [{"percent": percent, "state": state}]}]}


def _trigger_response(taskid=42):
    return {"result": [{"status": {"code": 0}, "data": {"task": taskid}}]}


def _preview_result_response(device_name, diff_text):
    return {
        "result": [{
            "status": {"code": 0},
            "data": [{"device": device_name, "content": diff_text}]
        }]
    }


def test_get_install_preview_returns_diff_text():
    client = _make_client()
    diff = "config firewall policy\n    edit 1\n        set action accept\n    next\nend\n"
    responses = [
        _trigger_response(taskid=99),       # POST securityconsole/install/preview
        _task_response(100),                 # GET task/task/99 → done
        _preview_result_response("FW1", diff),  # GET securityconsole/preview/result
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == diff


def test_get_install_preview_polls_until_complete():
    client = _make_client()
    diff = "config system global\nend\n"
    responses = [
        _trigger_response(taskid=5),
        _task_response(33),        # first poll — not done
        _task_response(66),        # second poll — still not done
        _task_response(100),       # third poll — done
        _preview_result_response("FW1", diff),
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == diff


def test_get_install_preview_raises_on_timeout(monkeypatch):
    client = _make_client()
    # Override PREVIEW_TIMEOUT_SECS to 0 so we time out immediately
    monkeypatch.setattr("app.fmg_client.PREVIEW_TIMEOUT_SECS", 0)

    def always_pending(*args, **kwargs):
        return _task_response(50)

    trigger = _trigger_response(taskid=7)
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return trigger
        return _task_response(50)

    with patch.object(client, "_post", side_effect=side_effect), \
         patch("time.sleep"):
        with pytest.raises(FMGError, match="timed out"):
            client.get_install_preview("MyADOM", "FW1")


def test_get_install_preview_returns_empty_string_when_no_changes():
    client = _make_client()
    responses = [
        _trigger_response(taskid=3),
        _task_response(100),
        # result list has no entry matching device name
        {"result": [{"status": {"code": 0}, "data": []}]},
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == ""


# ── parse_preview_diff ────────────────────────────────────────────────────────

def test_parse_preview_diff_empty():
    from app.fmg_client import parse_preview_diff
    result = parse_preview_diff("")
    assert result["summary"] == {"firewall_policy": 0, "routing": 0, "address": 0, "service": 0, "system": 0, "other": 0}
    assert result["vdoms"] == [{"name": "root", "changes": []}]


def test_parse_preview_diff_categorises_firewall_policy():
    from app.fmg_client import parse_preview_diff
    raw = "config firewall policy\n    edit 1\n        set action accept\n    next\nend\n"
    result = parse_preview_diff(raw)
    assert result["summary"]["firewall_policy"] == 1
    assert result["summary"]["routing"] == 0
    assert len(result["vdoms"]) == 1
    assert result["vdoms"][0]["name"] == "root"
    assert len(result["vdoms"][0]["changes"]) > 0


def test_parse_preview_diff_categorises_routing():
    from app.fmg_client import parse_preview_diff
    raw = "config router static\n    edit 1\n        set dst 10.0.0.0 255.0.0.0\n    next\nend\n"
    result = parse_preview_diff(raw)
    assert result["summary"]["routing"] == 1


def test_parse_preview_diff_splits_vdoms():
    from app.fmg_client import parse_preview_diff
    raw = (
        "vdom root\nconfig firewall policy\n    edit 1\nend\n"
        "vdom dmz\nconfig system global\nend\n"
    )
    result = parse_preview_diff(raw)
    names = [v["name"] for v in result["vdoms"]]
    assert "root" in names
    assert "dmz" in names


def test_parse_preview_diff_raw_preserved():
    from app.fmg_client import parse_preview_diff
    raw = "config firewall policy\nend\n"
    result = parse_preview_diff(raw)
    assert result["raw"] == raw
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alan.k.wodarski/Library/CloudStorage/OneDrive-previousemployer/code/gitlab-sites/4thealth
uv run pytest tests/test_pending_changes.py -v 2>&1 | head -40
```

Expected: ImportError or AttributeError — `get_devices_with_sync_status`, `get_install_preview`, `parse_preview_diff` don't exist yet.

- [ ] **Step 3: Add `PREVIEW_TIMEOUT_SECS`, `get_devices_with_sync_status`, `get_install_preview`, and `parse_preview_diff` to `app/fmg_client.py`**

After line 221 (`def get_devices(...)`) and before line 223 (`def _proxy(...)`), insert:

```python
PREVIEW_TIMEOUT_SECS = 90
_CONF_STATUS_MAP = {0: "unknown", 1: "insync", 2: "outofsync"}

_SUMMARY_KEYWORDS = [
    (["firewall policy", "firewall policy6"], "firewall_policy"),
    (["router static", "router policy", "router ospf", "router bgp", "router rip"], "routing"),
    (["firewall address", "firewall addrgrp", "firewall wildcard-fqdn"], "address"),
    (["firewall service"], "service"),
    (["system global", "system interface", "system settings", "system admin", "system dns"], "system"),
]


def parse_preview_diff(raw: str) -> dict:
    """Parse raw FMG install-preview CLI text into structured diff.

    Returns:
        {
          "summary": {"firewall_policy": int, "routing": int, ...},
          "vdoms": [{"name": str, "changes": [{"type": str, "line": str}]}],
          "raw": str,
        }
    """
    empty_summary = {"firewall_policy": 0, "routing": 0, "address": 0, "service": 0, "system": 0, "other": 0}
    if not raw or not raw.strip():
        return {"summary": empty_summary, "vdoms": [{"name": "root", "changes": []}], "raw": raw}

    # Split into VDOM blocks if multi-VDOM markers present
    import re as _re
    vdom_split = _re.split(r"^\s*vdom\s+(\S+)\s*$", raw, flags=_re.MULTILINE)

    if len(vdom_split) > 1:
        # Odd indices are vdom names, even indices ≥2 are their content
        vdom_blocks = []
        for i in range(1, len(vdom_split), 2):
            vname = vdom_split[i].strip()
            content = vdom_split[i + 1] if i + 1 < len(vdom_split) else ""
            vdom_blocks.append((vname, content))
    else:
        vdom_blocks = [("root", raw)]

    summary = dict(empty_summary)
    vdoms_out = []

    for vname, content in vdom_blocks:
        changes = _classify_lines(content)
        # Count config blocks per category
        for line_obj in changes:
            line = line_obj["line"].strip().lower()
            if line.startswith("config "):
            	block = line[len("config "):]
            	cat = "other"
            	for keywords, key in _SUMMARY_KEYWORDS:
            		if any(block.startswith(k) for k in keywords):
            			cat = key
            			break
            	summary[cat] += 1
        vdoms_out.append({"name": vname, "changes": changes})

    return {"summary": summary, "vdoms": vdoms_out, "raw": raw}


def _classify_lines(content: str) -> list:
    """Classify each line in a FortiOS CLI diff block as add/remove/modify."""
    changes = []
    in_delete = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("delete ") or stripped.startswith("unset "):
            changes.append({"type": "remove", "line": line})
            in_delete = True
        elif stripped.startswith("config ") or stripped.startswith("end"):
            changes.append({"type": "modify", "line": line})
            in_delete = False
        elif stripped.startswith("edit ") or stripped.startswith("next"):
            changes.append({"type": "modify", "line": line})
        elif stripped.startswith("set "):
            changes.append({"type": "add", "line": line})
        else:
            changes.append({"type": "modify", "line": line})
    return changes
```

Then add the two new methods to `FMGClient` class (append before `get_devices_with_sync_status` note: insert these after `get_devices` at line 221):

```python
    def get_devices_with_sync_status(self, adom: str) -> list:
        """Return devices in an ADOM with normalized conf_status string."""
        raw = self._get(f"/dvmdb/adom/{adom}/device") or []
        result = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            cs_int = d.get("conf_status", 0)
            try:
                cs_int = int(cs_int)
            except (TypeError, ValueError):
                cs_int = 0
            d["conf_status"] = _CONF_STATUS_MAP.get(cs_int, "unknown")
            result.append(d)
        return result

    def get_install_preview(self, adom: str, device: str) -> str:
        """Trigger FMG install preview for device, poll until done, return raw CLI diff text.

        Raises FMGError on task failure or timeout.
        Returns empty string if device has no pending changes.
        """
        import time as _time

        # Step 1: trigger
        trigger_body = {
            "id": self._next_id(),
            "method": "exec",
            "params": [{"url": "/securityconsole/install/preview",
                        "data": {"adom": adom, "device": {"name": device}}}],
        }
        if self.session:
            trigger_body["session"] = self.session
        trigger_resp = self._post(trigger_body)
        trigger_result = trigger_resp.get("result", [{}])[0]
        if trigger_result.get("status", {}).get("code", -1) != 0:
            raise FMGError(f"Preview trigger failed for {device}: {trigger_result.get('status')}")
        taskid = trigger_result.get("data", {}).get("task")
        if not taskid:
            raise FMGError(f"No task ID returned for preview of {device}")

        # Step 2: poll
        deadline = _time.time() + PREVIEW_TIMEOUT_SECS
        while _time.time() < deadline:
            poll_body = {
                "id": self._next_id(),
                "method": "get",
                "params": [{"url": f"/task/task/{taskid}"}],
            }
            if self.session:
                poll_body["session"] = self.session
            poll_resp = self._post(poll_body)
            poll_result = poll_resp.get("result", [{}])[0]
            task_data = poll_result.get("data", [])
            if isinstance(task_data, list) and task_data:
                task_data = task_data[0]
            if isinstance(task_data, dict):
                percent = task_data.get("percent", 0)
                state = task_data.get("state", 0)
                if state != 0 and state != 1:  # error states
                    raise FMGError(f"Preview task {taskid} failed with state {state}")
                if percent >= 100:
                    break
            _time.sleep(2)
        else:
            raise FMGError(f"Preview task {taskid} for {device} timed out after {PREVIEW_TIMEOUT_SECS}s")

        # Step 3: fetch result
        result_body = {
            "id": self._next_id(),
            "method": "get",
            "params": [{"url": f"/securityconsole/preview/result/{adom}"}],
        }
        if self.session:
            result_body["session"] = self.session
        result_resp = self._post(result_body)
        result_data = result_resp.get("result", [{}])[0].get("data", [])
        if not isinstance(result_data, list):
            return ""
        for entry in result_data:
            if isinstance(entry, dict) and entry.get("device", "").lower() == device.lower():
                return entry.get("content", "")
        return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_pending_changes.py -v
```

Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/fmg_client.py tests/test_pending_changes.py
git commit -m "feat: add get_devices_with_sync_status, get_install_preview, and parse_preview_diff to FMGClient"
```

---

## Task 2: Blueprint, routes, and app registration

**Files:**
- Create: `app/routes/pending_changes_routes.py`
- Modify: `app/__init__.py` (line 19 — add to `_BLUEPRINT_MODULES`)
- Test: `tests/test_pending_changes.py` (add route smoke tests)

**Interfaces:**
- Consumes: `FMGClient.get_devices_with_sync_status(adom)` → `list[dict]`
- Consumes: `FMGClient.get_install_preview(adom, device)` → `str`
- Consumes: `parse_preview_diff(raw)` → `dict` (imported from `app.fmg_client`)
- Produces: `GET /pending-changes` (page, `tab_required("pending_changes")`)
- Produces: `GET /api/pending-changes/adoms` → `[{name, desc}]`
- Produces: `GET /api/pending-changes/adoms/<adom>/devices` → `[{name, ip, platform, version, conf_status, serial}]`
- Produces: `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` → `{device, ip, conf_status, summary, vdoms, raw}`

---

- [ ] **Step 1: Add route smoke tests to `tests/test_pending_changes.py`**

Append to the existing file:

```python
# ── Route smoke tests ─────────────────────────────────────────────────────────

import pytest

@pytest.fixture
def app():
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app
    return create_app()

@pytest.fixture
def client(app):
    return app.test_client()

def test_pending_changes_page_redirects_unauthenticated(client):
    resp = client.get("/pending-changes")
    assert resp.status_code in (302, 401)

def test_pending_changes_adoms_redirects_unauthenticated(client):
    resp = client.get("/api/pending-changes/adoms")
    assert resp.status_code in (302, 401)

def test_pending_changes_devices_redirects_unauthenticated(client):
    resp = client.get("/api/pending-changes/adoms/MyADOM/devices")
    assert resp.status_code in (302, 401)
```

- [ ] **Step 2: Run tests to verify the new smoke tests fail** (route doesn't exist yet)

```bash
uv run pytest tests/test_pending_changes.py::test_pending_changes_page_redirects_unauthenticated -v
```

Expected: 404 (route not registered), not 302/401 — test FAILS.

- [ ] **Step 3: Create `app/routes/pending_changes_routes.py`**

```python
"""Pending Changes tab — shows FortiManager install-pending diffs per device.

Page:
  GET  /pending-changes

API (JSON, all read-only):
  GET  /api/pending-changes/adoms
       returns: [{name, desc}, ...]

  GET  /api/pending-changes/adoms/<adom>/devices
       returns: [{name, ip, platform, version, conf_status, serial}, ...]

  POST /api/pending-changes/adoms/<adom>/device/<device>/preview
       returns: {device, ip, conf_status, summary, vdoms, raw}
"""

from __future__ import annotations

from flask import Blueprint, render_template, session, jsonify

from app import registry
from app.decorators import tab_required, check_adom_access
from app.fmg_client import FMGError, parse_preview_diff
from app.fmg_helpers import make_client
from app.groups import get_allowed_adoms
from app.security import internal_api_error, upstream_api_error

bp = Blueprint("pending_changes", __name__)

registry.register("pending_changes", "Pending Changes", "pending_changes.pending_changes_page")


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/pending-changes")
@tab_required("pending_changes")
def pending_changes_page():
    return render_template("pending_changes.html", user=session["user"])


# ── API: ADOM list ────────────────────────────────────────────────────────────


@bp.route("/api/pending-changes/adoms")
@tab_required("pending_changes")
def pending_changes_adoms():
    try:
        with make_client() as client:
            raw = client.get_adoms()
        items = [
            {"name": a.get("name", a.get("adom", "")), "desc": a.get("desc", "")}
            for a in raw
            if isinstance(a, dict)
        ]
        items = [i for i in items if i["name"] and not i["name"].lower().startswith("forti")]
        allowed = get_allowed_adoms(
            session.get("user", ""), ad_groups=session.get("ad_groups", [])
        )
        if allowed is not None:
            items = [i for i in items if i["name"] in allowed]
        return jsonify(items)
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)


# ── API: device list with sync status ─────────────────────────────────────────


@bp.route("/api/pending-changes/adoms/<adom>/devices")
@tab_required("pending_changes")
def pending_changes_devices(adom: str):
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            raw = client.get_devices_with_sync_status(adom)
        seen: set[str] = set()
        devices = []
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
            if mr is not None and patch is not None and int(patch) >= 0:
                version = f"v{major}.{mr}.{patch}"
            elif mr is not None:
                version = f"v{major}.{mr}"
            else:
                version = ""
            devices.append({
                "name": name,
                "ip": d.get("ip", d.get("mgmt_ip", "")),
                "platform": d.get("platform_str", d.get("platform", "")),
                "version": version,
                "conf_status": d.get("conf_status", "unknown"),
                "serial": d.get("sn", d.get("serial", "")),
            })
        return jsonify(devices)
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)


# ── API: install preview ───────────────────────────────────────────────────────


@bp.route("/api/pending-changes/adoms/<adom>/device/<device>/preview", methods=["POST"])
@tab_required("pending_changes")
def pending_changes_preview(adom: str, device: str):
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            # Fetch device IP for response metadata
            raw_devices = client.get_devices_with_sync_status(adom)
            device_meta = next(
                (d for d in raw_devices if d.get("name", "").lower() == device.lower()),
                {}
            )
            raw = client.get_install_preview(adom, device)
        parsed = parse_preview_diff(raw)
        return jsonify({
            "device": device,
            "ip": device_meta.get("ip", device_meta.get("mgmt_ip", "")),
            "conf_status": device_meta.get("conf_status", "unknown"),
            "summary": parsed["summary"],
            "vdoms": parsed["vdoms"],
            "raw": parsed["raw"],
        })
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)
```

- [ ] **Step 4: Register blueprint in `app/__init__.py`**

In `app/__init__.py`, find `_BLUEPRINT_MODULES` list. After `"app.routes.map_routes"`, add:

```python
    "app.routes.pending_changes_routes",
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/test_pending_changes.py -v
```

Expected: All tests PASS (smoke tests now return 302/401 because route is registered).

- [ ] **Step 6: Commit**

```bash
git add app/routes/pending_changes_routes.py app/__init__.py tests/test_pending_changes.py
git commit -m "feat: add pending_changes blueprint with ADOM, device, and preview endpoints"
```

---

## Task 3: HTML template

**Files:**
- Create: `app/templates/pending_changes.html`

**Interfaces:**
- Consumes: `base.html` (extends it, same as all other tab templates)
- Consumes: `pending_changes.js` (loaded at end of block content via `{% block scripts %}`)
- Produces: DOM IDs consumed by `pending_changes.js` (listed in the template below)

---

- [ ] **Step 1: Create `app/templates/pending_changes.html`**

```html
{% extends "base.html" %}
{% block title %}Pending Changes — 4THealth{% endblock %}

{% block content %}
<div class="page-header">
  <div>
    <h2>Pending Changes</h2>
    <span class="last-updated" id="pcStatus"></span>
  </div>
</div>

<!-- Top controls -->
<div class="hygiene-selectors">
  <div class="hygiene-selector-row">
    <label for="pcAdom">ADOM</label>
    <select id="pcAdom" class="form-select" style="max-width:280px">
      <option value="">— select ADOM —</option>
    </select>
    <span id="pcAdomLoading" class="text-muted"
          style="display:none;font-style:italic;font-size:.88rem;margin-left:.5rem">Loading…</span>
  </div>
</div>

<!-- Two-column layout -->
<div style="display:flex;gap:1.25rem;margin-top:1.25rem;align-items:flex-start">

  <!-- Left: device list -->
  <div style="flex:0 0 420px;min-width:280px">
    <div style="display:flex;gap:.6rem;align-items:center;margin-bottom:.6rem;flex-wrap:wrap">
      <input type="text" id="pcSearch" class="form-control"
             placeholder="Search by name or IP…"
             style="max-width:220px;font-size:.88rem" />
      <label style="display:flex;align-items:center;gap:.3rem;font-size:.88rem;white-space:nowrap;cursor:pointer"
             title="Shows only devices where FortiManager has committed changes that have not yet been installed on the device.">
        <input type="checkbox" id="pcPendingOnly" />
        Pending only
        <span class="help-icon" title="Shows only devices where FortiManager has committed changes that have not yet been installed on the device.">?</span>
      </label>
    </div>

    <div id="pcDeviceError" class="alert alert-danger" style="display:none"></div>

    <table class="table table-sm" id="pcDeviceTable">
      <thead>
        <tr>
          <th>Name</th>
          <th>IP</th>
          <th>Platform</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="pcDeviceTbody">
        <tr><td colspan="4" style="text-align:center;color:var(--text-muted)">Select an ADOM to load devices.</td></tr>
      </tbody>
    </table>

    <!-- Pagination -->
    <div style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;margin-top:.5rem">
      <div id="pcPager" style="display:flex;gap:.25rem"></div>
      <span id="pcDeviceCount" class="text-muted" style="font-size:.82rem"></span>
      <div style="margin-left:auto;display:flex;align-items:center;gap:.4rem;font-size:.85rem">
        <label for="pcPageSize" style="white-space:nowrap">Show</label>
        <select id="pcPageSize" class="form-select form-select-sm" style="width:70px">
          <option value="10">10</option>
          <option value="25" selected>25</option>
          <option value="50">50</option>
        </select>
      </div>
    </div>
  </div>

  <!-- Right: diff panel -->
  <div style="flex:1;min-width:0">
    <div id="pcDiffPanel">
      <p style="color:var(--text-muted);font-style:italic">Select a device to view pending changes.</p>
    </div>
  </div>

</div>

<!-- Export queue footer (hidden until queue has items) -->
<div id="pcQueueFooter"
     style="display:none;position:sticky;bottom:0;background:var(--surface);border-top:1px solid var(--border);
            padding:.6rem 1rem;display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;z-index:100">
  <strong style="font-size:.85rem;white-space:nowrap">Export Queue:</strong>
  <div id="pcQueueChips" style="display:flex;gap:.4rem;flex-wrap:wrap;flex:1"></div>
  <div style="display:flex;gap:.4rem;margin-left:auto">
    <button class="btn btn-xs" id="pcExportCsv">CSV</button>
    <button class="btn btn-xs" id="pcExportJson">JSON</button>
    <button class="btn btn-xs" id="pcExportPdf">PDF</button>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>const PC_USER = {{ user | tojson }};</script>
<script src="{{ url_for('static', filename='js/pending_changes.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Verify template renders (manual check)**

Start the dev server:
```bash
uv run python wsgi.py
```

Log in, navigate to `/pending-changes` in the browser. You should see the page with the two-column layout — ADOM dropdown on the left, "Select a device…" placeholder on the right. No JS errors in the browser console. The tab will appear in the nav if `pending_changes` is added to your test user's allowed tabs (do this via Admin → Groups, or via `groups.json` directly — see step below).

To add the tab to a test user's group, edit `groups.json` and add `"pending_changes"` to the `"tabs"` array for their group. Restart the server.

- [ ] **Step 3: Run smoke tests to confirm template doesn't break app**

```bash
uv run pytest tests/test_smoke.py tests/test_pending_changes.py -v
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add app/templates/pending_changes.html
git commit -m "feat: add pending_changes.html template"
```

---

## Task 4: Frontend JavaScript

**Files:**
- Create: `app/static/js/pending_changes.js`

**Interfaces:**
- Consumes: `PC_USER` (injected by template — the logged-in username string)
- Consumes: `GET /api/pending-changes/adoms`
- Consumes: `GET /api/pending-changes/adoms/<adom>/devices`
- Consumes: `POST /api/pending-changes/adoms/<adom>/device/<device>/preview`
- Produces: CSV/JSON/PDF download via browser

---

- [ ] **Step 1: Create `app/static/js/pending_changes.js`**

```javascript
'use strict';

/* ── Utilities ─────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function download(filename, content, mime) {
  const a  = document.createElement('a');
  const bl = new Blob([content], { type: mime });
  a.href   = URL.createObjectURL(bl);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function csrfToken() {
  return document.cookie.split(';').map(c => c.trim())
    .find(c => c.startsWith('csrf_token='))?.split('=')[1] ?? '';
}

/* ── State ──────────────────────────────────────────────────────────────────── */
let allDevices     = [];
let filteredDevices = [];
let currentPage    = 1;
let pageSize       = 25;
let filterText     = '';
let pendingOnly    = false;
let currentAdom    = '';
let currentDevice  = null;
let currentDiff    = null;
let exportQueue    = [];  // [{device, ip, adom, summary, vdoms, raw, timestamp}]

/* ── Sync status badge ──────────────────────────────────────────────────────── */
function syncBadge(status) {
  switch (status) {
    case 'outofsync':
      return '<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:.75rem;font-weight:600;background:#fef3c7;color:#92400e;border:1px solid #fcd34d">Out of Sync</span>';
    case 'insync':
      return '<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:.75rem;font-weight:600;background:#dcfce7;color:#166534;border:1px solid #86efac">In Sync</span>';
    default:
      return '<span style="display:inline-block;padding:1px 7px;border-radius:3px;font-size:.75rem;font-weight:600;background:#f3f4f6;color:#6b7280;border:1px solid #d1d5db">Unknown</span>';
  }
}

/* ── ADOM loading ───────────────────────────────────────────────────────────── */
async function fetchAdoms() {
  const sel = document.getElementById('pcAdom');
  try {
    const resp = await fetch('/api/pending-changes/adoms');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const adoms = await resp.json();
    sel.innerHTML = '<option value="">— select ADOM —</option>';
    adoms.forEach(a => {
      const opt = document.createElement('option');
      opt.value = a.name;
      opt.textContent = a.name;
      sel.appendChild(opt);
    });
  } catch (e) {
    showDeviceError('Failed to load ADOM list: ' + e.message);
  }
}

/* ── Device loading ─────────────────────────────────────────────────────────── */
async function fetchDevices(adom) {
  currentAdom = adom;
  allDevices = [];
  filteredDevices = [];
  currentPage = 1;
  clearDiffPanel();
  if (!adom) { renderDeviceTable(); return; }

  const loading = document.getElementById('pcAdomLoading');
  loading.style.display = '';
  try {
    const resp = await fetch(`/api/pending-changes/adoms/${encodeURIComponent(adom)}/devices`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    allDevices = await resp.json();
    applyFilters();
  } catch (e) {
    showDeviceError('Failed to load devices: ' + e.message);
  } finally {
    loading.style.display = 'none';
  }
}

/* ── Filtering ──────────────────────────────────────────────────────────────── */
function applyFilters() {
  const q = filterText.toLowerCase();
  filteredDevices = allDevices.filter(d => {
    if (pendingOnly && d.conf_status !== 'outofsync') return false;
    if (!q) return true;
    return (d.name || '').toLowerCase().includes(q) ||
           (d.ip   || '').toLowerCase().includes(q);
  });
  currentPage = 1;
  renderDeviceTable();
}

/* ── Device table rendering ─────────────────────────────────────────────────── */
function renderDeviceTable() {
  const tbody = document.getElementById('pcDeviceTbody');
  const pager = document.getElementById('pcPager');
  const count = document.getElementById('pcDeviceCount');

  if (!filteredDevices.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted)">' +
      (currentAdom ? 'No devices match the current filter.' : 'Select an ADOM to load devices.') +
      '</td></tr>';
    pager.innerHTML = '';
    count.textContent = '';
    return;
  }

  const start = (currentPage - 1) * pageSize;
  const page  = filteredDevices.slice(start, start + pageSize);

  tbody.innerHTML = page.map(d => {
    const selected = currentDevice && currentDevice.name === d.name ? 'style="background:var(--surface-alt)"' : '';
    return `<tr ${selected} style="cursor:pointer" data-device="${esc(d.name)}"
              onclick="selectDevice(${JSON.stringify(d)})">
      <td><strong>${esc(d.name)}</strong></td>
      <td><code style="font-size:.82rem">${esc(d.ip || '—')}</code></td>
      <td style="font-size:.82rem">${esc(d.platform || '—')}</td>
      <td>${syncBadge(d.conf_status)}</td>
    </tr>`;
  }).join('');

  // Pagination
  const totalPages = Math.ceil(filteredDevices.length / pageSize);
  pager.innerHTML = buildPager(currentPage, totalPages);
  count.textContent = `${filteredDevices.length} device${filteredDevices.length !== 1 ? 's' : ''}`;
}

function buildPager(current, total) {
  if (total <= 1) return '';
  const btn = (label, page, disabled) =>
    `<button class="btn btn-xs" onclick="goPage(${page})" ${disabled ? 'disabled' : ''}>${label}</button>`;
  let html = btn('&laquo;', 1, current === 1) + btn('&lsaquo;', current - 1, current === 1);
  const start = Math.max(1, current - 2);
  const end   = Math.min(total, current + 2);
  if (start > 1) html += '<span style="padding:0 4px">…</span>';
  for (let p = start; p <= end; p++) {
    html += `<button class="btn btn-xs${p === current ? ' btn-primary' : ''}" onclick="goPage(${p})">${p}</button>`;
  }
  if (end < total) html += '<span style="padding:0 4px">…</span>';
  html += btn('&rsaquo;', current + 1, current === total) + btn('&raquo;', total, current === total);
  return html;
}

function goPage(p) {
  currentPage = p;
  renderDeviceTable();
}

/* ── Device selection + preview ─────────────────────────────────────────────── */
function selectDevice(device) {
  currentDevice = device;
  renderDeviceTable(); // re-render to highlight selected row
  loadPreview(currentAdom, device.name);
}

async function loadPreview(adom, deviceName) {
  currentDiff = null;
  showDiffSpinner(deviceName);

  try {
    const resp = await fetch(
      `/api/pending-changes/adoms/${encodeURIComponent(adom)}/device/${encodeURIComponent(deviceName)}/preview`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
        body: JSON.stringify({}),
      }
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }
    currentDiff = await resp.json();
    currentDiff.adom = adom;
    currentDiff.timestamp = new Date().toISOString();
    renderDiffPanel(currentDiff);
  } catch (e) {
    showDiffError(deviceName, e.message);
  }
}

/* ── Diff panel rendering ───────────────────────────────────────────────────── */
function clearDiffPanel() {
  currentDevice = null;
  currentDiff   = null;
  document.getElementById('pcDiffPanel').innerHTML =
    '<p style="color:var(--text-muted);font-style:italic">Select a device to view pending changes.</p>';
}

function showDiffSpinner(deviceName) {
  document.getElementById('pcDiffPanel').innerHTML = `
    <div style="padding:1.5rem;text-align:center">
      <div class="spinner" style="display:inline-block;width:28px;height:28px;border:3px solid var(--border);
           border-top-color:var(--primary,#3b82f6);border-radius:50%;animation:spin 0.8s linear infinite"></div>
      <p style="margin-top:.75rem;color:var(--text-muted);font-style:italic">
        FortiManager is generating diff for <strong>${esc(deviceName)}</strong>, please wait…
      </p>
    </div>
    <style>@keyframes spin{to{transform:rotate(360deg)}}</style>`;
}

function showDiffError(deviceName, msg) {
  document.getElementById('pcDiffPanel').innerHTML =
    `<div class="alert alert-danger"><strong>${esc(deviceName)}</strong>: ${esc(msg)}</div>`;
}

function renderDiffPanel(diff) {
  const hasChanges = diff.vdoms.some(v => v.changes.length > 0);

  // Summary tiles
  const summaryKeys = [
    ['firewall_policy', 'Firewall Policy'],
    ['routing',         'Routing'],
    ['address',         'Address'],
    ['service',         'Service'],
    ['system',          'System'],
    ['other',           'Other'],
  ];
  const tilesHtml = summaryKeys
    .filter(([k]) => diff.summary[k] > 0)
    .map(([k, label]) =>
      `<div style="display:inline-flex;flex-direction:column;align-items:center;
                   padding:.4rem .75rem;border-radius:6px;background:var(--surface-alt);
                   border:1px solid var(--border);margin:.2rem">
        <span style="font-size:1.2rem;font-weight:700">${diff.summary[k]}</span>
        <span style="font-size:.72rem;color:var(--text-muted)">${label}</span>
       </div>`
    ).join('');

  // VDOM diff blocks
  const vdomsHtml = diff.vdoms.map(vdom => {
    if (!vdom.changes.length) return '';
    const linesHtml = vdom.changes.map(c => {
      const cls = c.type === 'add' ? 'diff-add' : c.type === 'remove' ? 'diff-remove' : 'diff-modify';
      const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
      return `<span class="${cls}">${esc(prefix + ' ' + c.line)}</span>`;
    }).join('\n');
    return `<details open style="margin-top:.75rem">
      <summary style="cursor:pointer;font-weight:600;font-size:.9rem;padding:.3rem 0">
        vdom: ${esc(vdom.name)}
      </summary>
      <pre class="diff-block" style="background:var(--surface-alt);border:1px solid var(--border);
           border-radius:4px;padding:.75rem;overflow-x:auto;font-size:.8rem;margin:.4rem 0 0">${linesHtml}</pre>
    </details>`;
  }).join('');

  const alreadyQueued = exportQueue.some(q => q.device === diff.device && q.adom === diff.adom);
  const addBtnLabel   = alreadyQueued ? 'Already in Queue' : '+ Add to Export Queue';

  document.getElementById('pcDiffPanel').innerHTML = `
    <div style="display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap;margin-bottom:.75rem">
      <h4 style="margin:0">${esc(diff.device)}</h4>
      <code style="font-size:.85rem;color:var(--text-muted)">${esc(diff.ip || '')}</code>
      ${syncBadge(diff.conf_status)}
    </div>

    ${tilesHtml ? `<div style="display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:.75rem">${tilesHtml}</div>` : ''}

    <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.5rem;flex-wrap:wrap">
      <button class="btn btn-sm btn-secondary" id="pcAddToQueue" onclick="addToQueue()"
              ${alreadyQueued ? 'disabled' : ''}
              title="Accumulate multiple devices into a single export document for use in a change record.">
        ${addBtnLabel}
      </button>
      <span style="font-size:.78rem;color:var(--text-muted)"
            title="Changes are shown in CLI format. + added, - removed, ~ modified. Grouped by VDOM where applicable.">
        ? CLI format: <code style="font-size:.78rem">+</code> added &nbsp;
        <code style="font-size:.78rem">-</code> removed &nbsp;
        <code style="font-size:.78rem">~</code> modified
      </span>
    </div>

    ${hasChanges ? vdomsHtml : '<p style="color:var(--text-muted);font-style:italic">No pending changes found for this device.</p>'}

    <style>
      .diff-add    { color: #166534; display:block }
      .diff-remove { color: #b91c1c; display:block }
      .diff-modify { color: #92400e; display:block }
    </style>`;
}

/* ── Export queue ───────────────────────────────────────────────────────────── */
function addToQueue() {
  if (!currentDiff) return;
  if (exportQueue.some(q => q.device === currentDiff.device && q.adom === currentDiff.adom)) return;
  exportQueue.push({ ...currentDiff });
  renderDiffPanel(currentDiff); // refresh "Add to Queue" button state
  renderQueue();
}

function removeFromQueue(device) {
  exportQueue = exportQueue.filter(q => q.device !== device);
  renderQueue();
  if (currentDiff && currentDiff.device === device) renderDiffPanel(currentDiff);
}

function renderQueue() {
  const footer = document.getElementById('pcQueueFooter');
  const chips  = document.getElementById('pcQueueChips');
  if (!exportQueue.length) {
    footer.style.display = 'none';
    chips.innerHTML = '';
    return;
  }
  footer.style.display = 'flex';
  chips.innerHTML = exportQueue.map(q =>
    `<span style="display:inline-flex;align-items:center;gap:.3rem;padding:2px 8px;
                  border-radius:12px;background:var(--surface-alt);border:1px solid var(--border);
                  font-size:.82rem">
       ${esc(q.device)}
       <button onclick="removeFromQueue('${esc(q.device)}')"
               style="background:none;border:none;cursor:pointer;padding:0;line-height:1;color:var(--text-muted)">×</button>
     </span>`
  ).join('');
}

/* ── Exports ────────────────────────────────────────────────────────────────── */
function buildMetaHeader() {
  const ts      = new Date().toLocaleString();
  const adom    = exportQueue[0]?.adom || currentAdom || '';
  const devices = exportQueue.map(q => q.device).join(', ');
  return { ts, adom, devices, user: (typeof PC_USER !== 'undefined' ? PC_USER : '') };
}

function exportCsv() {
  if (!exportQueue.length) return;
  const { ts, adom, devices, user } = buildMetaHeader();
  let csv = `# Pending Changes Export\n# Generated: ${ts}\n# User: ${user}\n# ADOM: ${adom}\n# Devices: ${devices}\n`;
  csv += '# Summary\n';
  exportQueue.forEach(q => {
    const s = q.summary;
    csv += `# ${q.device}: firewall_policy=${s.firewall_policy} routing=${s.routing} address=${s.address} service=${s.service} system=${s.system} other=${s.other}\n`;
  });
  csv += '\ndevice,ip,vdom,change_type,line\n';
  exportQueue.forEach(q => {
    q.vdoms.forEach(v => {
      v.changes.forEach(c => {
        const line = c.line.replace(/"/g, '""');
        csv += `"${q.device}","${q.ip || ''}","${v.name}","${c.type}","${line}"\n`;
      });
    });
  });
  download(`pending-changes-${adom || 'export'}.csv`, csv, 'text/csv');
}

function exportJson() {
  if (!exportQueue.length) return;
  const { ts, adom, devices, user } = buildMetaHeader();
  const payload = {
    meta: { generated: ts, user, adom, devices },
    devices: exportQueue.map(q => ({
      device: q.device,
      ip: q.ip,
      conf_status: q.conf_status,
      summary: q.summary,
      vdoms: q.vdoms,
    })),
  };
  download(`pending-changes-${adom || 'export'}.json`, JSON.stringify(payload, null, 2), 'application/json');
}

function exportPdf() {
  if (!exportQueue.length) return;
  const { ts, adom, devices, user } = buildMetaHeader();
  const title = `Pending Changes — ADOM: ${adom}`;

  const deviceSections = exportQueue.map((q, idx) => {
    const s = q.summary;
    const summaryItems = Object.entries(s)
      .filter(([,v]) => v > 0)
      .map(([k, v]) => `<span style="margin-right:12px"><strong>${v}</strong> ${k.replace(/_/g,' ')}</span>`)
      .join('');

    const vdomBlocks = q.vdoms.map(v => {
      if (!v.changes.length) return '';
      const lines = v.changes.map(c => {
        const color = c.type === 'add' ? '#166534' : c.type === 'remove' ? '#b91c1c' : '#92400e';
        const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
        return `<span style="color:${color};display:block">${escHtml(prefix + ' ' + c.line)}</span>`;
      }).join('');
      return `<div style="margin-top:8px"><strong style="font-size:10px">vdom: ${escHtml(v.name)}</strong>
        <pre style="background:#f8f9fa;border:1px solid #e5e7eb;border-radius:3px;padding:8px;
                    font-size:9px;margin:4px 0;overflow-wrap:break-word;white-space:pre-wrap">${lines}</pre></div>`;
    }).join('');

    return `<div style="${idx > 0 ? 'page-break-before:always;' : ''}padding-top:${idx > 0 ? '1cm' : '0'}">
      <h2 style="font-size:14px;margin:0 0 4px">${escHtml(q.device)}</h2>
      <div style="font-size:10px;color:#6b7280;margin-bottom:6px">
        <code>${escHtml(q.ip || '')}</code> &nbsp;|&nbsp; ${escHtml(q.conf_status)}
      </div>
      ${summaryItems ? `<div style="margin-bottom:8px;font-size:10px">${summaryItems}</div>` : ''}
      ${vdomBlocks || '<p style="font-size:10px;color:#6b7280;font-style:italic">No pending changes found.</p>'}
    </div>`;
  }).join('');

  function escHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${escHtml(title)}</title>
<style>
  body{font-family:Arial,sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:16px;margin-bottom:6px}
  .meta{background:#f3f4f6;border-left:4px solid #3b82f6;padding:8px 12px;border-radius:3px;margin-bottom:14px;font-size:10px}
  code{font-family:monospace;font-size:10px}
  @media print{@page{margin:1.2cm}}
</style></head><body>
<h1>${escHtml(title)}</h1>
<div class="meta">
  Generated: ${escHtml(ts)}<br>User: ${escHtml(user)}<br>
  ADOM: ${escHtml(adom)}<br>Devices: ${escHtml(devices)}
</div>
${deviceSections}
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.print(); }
}

/* ── Error helpers ───────────────────────────────────────────────────────────── */
function showDeviceError(msg) {
  const el = document.getElementById('pcDeviceError');
  el.textContent = msg;
  el.style.display = '';
}
function clearDeviceError() {
  const el = document.getElementById('pcDeviceError');
  el.textContent = '';
  el.style.display = 'none';
}

/* ── ADOM change guard ──────────────────────────────────────────────────────── */
function handleAdomChange(adom) {
  if (exportQueue.length > 0) {
    const ok = confirm('Changing ADOM will clear your export queue. Continue?');
    if (!ok) {
      document.getElementById('pcAdom').value = currentAdom;
      return;
    }
    exportQueue = [];
    renderQueue();
  }
  clearDeviceError();
  fetchDevices(adom);
}

/* ── Init ───────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  fetchAdoms();

  document.getElementById('pcAdom').addEventListener('change', e => handleAdomChange(e.target.value));
  document.getElementById('pcPageSize').addEventListener('change', e => {
    pageSize = parseInt(e.target.value, 10);
    currentPage = 1;
    renderDeviceTable();
  });
  document.getElementById('pcSearch').addEventListener('input', e => {
    filterText = e.target.value.trim();
    applyFilters();
  });
  document.getElementById('pcPendingOnly').addEventListener('change', e => {
    pendingOnly = e.target.checked;
    applyFilters();
  });
  document.getElementById('pcExportCsv').addEventListener('click', exportCsv);
  document.getElementById('pcExportJson').addEventListener('click', exportJson);
  document.getElementById('pcExportPdf').addEventListener('click', exportPdf);
});
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS. No regressions in existing suites.

- [ ] **Step 3: Manual browser test**

Start the dev server: `uv run python wsgi.py`

Test the following scenarios:

1. **ADOM load**: Select an ADOM → device table populates with Name, IP, Platform, Status badge columns.
2. **Search**: Type part of a device name or IP → table filters client-side.
3. **Pending only toggle**: Check the toggle → only "Out of Sync" devices shown.
4. **Pagination**: If > 25 devices, pager arrows appear and work.
5. **Device click**: Click a device row → spinner appears in right panel → (waits for FMG) → diff panel renders with summary tiles and VDOM diff sections.
6. **No changes**: Click an in-sync device → "No pending changes found" message.
7. **Add to queue**: Click "Add to Export Queue" → device chip appears in the footer bar; button becomes "Already in Queue" (disabled).
8. **Second device**: Click another device → load its diff → add to queue → queue shows two chips.
9. **ADOM change with queue**: Try changing ADOM while queue is non-empty → confirmation dialog → cancel preserves ADOM and queue; confirm clears queue.
10. **CSV export**: Click CSV → file downloads; open it — metadata header rows present, then `device,ip,vdom,change_type,line` rows.
11. **JSON export**: Click JSON → file downloads; valid JSON with `meta` and `devices` array.
12. **PDF export**: Click PDF → new browser tab opens with formatted diff; browser print dialog appears.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "feat: add pending_changes.js with device list, diff viewer, export queue, and CSV/JSON/PDF exports"
```

---

## Task 5: CLAUDE.md documentation update

**Files:**
- Modify: `CLAUDE.md`

---

- [ ] **Step 1: Add Pending Changes tab section to CLAUDE.md**

Open `CLAUDE.md` and append the following section after the "External API" section:

```markdown
### Pending Changes tab

`GET /pending-changes` → `pending_changes.html` + `pending_changes.js`

Shows FortiManager install-pending changes — config committed in FortiManager but not yet pushed to physical FortiGate devices. Uses the FMG Install Preview API (async task-based diff generation).

**Tab key:** `pending_changes`

**Workflow:**
1. Select ADOM → device list loads with sync status badges.
2. Optionally filter via search (name or IP) or "Pending only" toggle.
3. Click a device → right panel shows spinner while FMG generates the diff (10–60s).
4. Diff renders as CLI-format lines grouped by VDOM (add/remove/modify).
5. "Add to Export Queue" → chip appears in sticky footer bar.
6. Export queue: CSV, JSON, or PDF covering all queued devices in one document.

**`conf_status` integer-to-string mapping** (from FMG dvmdb):
- `0` → `"unknown"`
- `1` → `"insync"`
- `2` → `"outofsync"`

The "Pending only" toggle filters the device list by `conf_status`. It does not gate the preview call — clicking any device always triggers a live preview because `conf_status` can lag behind actual state.

**New FMGClient methods** (`app/fmg_client.py`):

`get_devices_with_sync_status(adom)` — calls `/dvmdb/adom/{adom}/device`; normalises `conf_status` integer to string.

`get_install_preview(adom, device)` — async three-step:
1. POST `/securityconsole/install/preview` → `taskid`
2. Poll `/task/task/{taskid}` every 2s until `percent == 100` (timeout: `PREVIEW_TIMEOUT_SECS = 90`)
3. GET `/securityconsole/preview/result/{adom}` → raw CLI diff text

`parse_preview_diff(raw)` — module-level helper; parses CLI diff into `{summary, vdoms, raw}`. **Implementation note:** The FMG preview output format must be verified against a real FMG instance — the parser in `_classify_lines()` may need adjustment based on actual output. The `raw` field is always returned so the frontend has an unprocessed fallback.

**Export queue pattern:** Export queue is client-side only (`exportQueue` array in `pending_changes.js`). Queue clears on ADOM change (with confirmation dialog). CSV/JSON/PDF exports cover all queued devices in one document.

**API endpoints:**
- `GET  /api/pending-changes/adoms` — ADOM list (filtered by access)
- `GET  /api/pending-changes/adoms/<adom>/devices` — device list with `conf_status`
- `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` — trigger preview, return structured diff
```

- [ ] **Step 2: Run all tests once more**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Pending Changes tab section to CLAUDE.md"
```

---

## Task 6: Final verification and push

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS. Note any failures and fix before continuing.

- [ ] **Step 2: Full manual browser regression check**

Start the server: `uv run python wsgi.py`

Verify:
- All existing tabs still load without errors (Firewalls, Rule Review, Device Review, Zone Policy, Map).
- Pending Changes tab appears in the nav for users with the `pending_changes` tab permission.
- Tab does not appear for users without the permission.
- Admin tab → Groups → group editor shows `Pending Changes` as an available tab checkbox.

- [ ] **Step 3: Push branch to GitLab**

```bash
git push -u origin pending-change
```

Expected: Push succeeds. Open a merge request from `pending-change` → `main` in GitLab.
