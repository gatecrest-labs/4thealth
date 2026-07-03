# SNMP-based Infrastructure Health Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the currently-broken FMG-JSON-RPC-based CPU/memory sourcing for FortiManager, FortiAnalyzer, and FortiAuthenticator dashboard cards with SNMPv3 polling, via a background cache poller.

**Architecture:** A new `app/infra_health_cache.py` module polls all `infra_targets.json` entries of type `fortimanager`/`fortianalyzer`/`fortiauthenticator` over SNMPv3 on an APScheduler timer (default 60s), storing `{cpu, mem, snmp_status, last_updated}` per host in an in-memory dict guarded by a lock — the same pattern as `app/adom_cache.py`. `/api/infrastructure` reads from this cache instantly instead of making live SNMP/JSON-RPC calls per request. `dashboard.js` renders the returned `cpu`/`mem` fields, which it currently receives but never displays.

**Tech Stack:** Flask, APScheduler (already a dependency), `pysnmp` 7.x (`pysnmp.hlapi.v3arch.asyncio` — verified working API, see Task 1), pytest + `unittest.mock.AsyncMock` for tests.

## Global Constraints

- SNMPv3 only (auth + privacy) — no SNMPv1/v2c community-string support.
- Applies only to `infra_targets.json` entries of type `fortimanager`, `fortianalyzer`, `fortiauthenticator` (case-insensitive match against existing capitalized `"FortiManager"`/`"FortiAnalyzer"`/`"FortiAuthenticator"` type values). FortiGate firewall CPU/mem (elsewhere in the app) is untouched.
- Background poll interval defaults to 60s (`SNMP_POLL_INTERVAL` env var).
- Health status reuses existing `CPU_WARN`/`CPU_CRIT`/`MEM_WARN`/`MEM_CRIT` thresholds from `app/config.py:61-64` — no new thresholds.
- Per-device SNMP credential overrides in `infra_targets.json` follow the same override-over-default pattern as the existing `"token"` field (`api_routes.py:218`).
- This project is strictly read-only — no SNMP SET operations, ever.
- Follow `uv add <package>` for dependency changes per `CLAUDE.md`'s "Dependency management" section — never edit `pyproject.toml`/`uv.lock` by hand.

---

## File Structure

- **Create** `app/infra_health_cache.py` — SNMP poller, in-memory cache, scheduler init (mirrors `app/adom_cache.py`).
- **Create** `tests/test_infra_health_cache.py` — unit tests for the poller/cache using mocked SNMP calls.
- **Modify** `app/config.py` — add `SNMP_*` config block.
- **Modify** `app/__init__.py` — register `infra_health_cache.init_scheduler` alongside the other background jobs.
- **Modify** `app/routes/api_routes.py` — `infrastructure()` route reads CPU/mem from the new cache for the three supported types instead of FMG JSON-RPC.
- **Modify** `app/static/js/dashboard.js` — `renderCard()` gains a CPU/mem row.
- **Modify** `infra_targets.example.json` — add example `snmp_user`/`snmp_auth_key`/`snmp_priv_key` override fields on one entry.
- **Modify** `pyproject.toml` / `uv.lock` — add `pysnmp` dependency (via `uv add`).
- **Modify** `CLAUDE.md` — document the new env vars, `infra_targets.json` fields, and module.

---

### Task 1: Add `pysnmp` dependency and `SNMP_*` config block

**Files:**
- Modify: `pyproject.toml` (via `uv add`, do not hand-edit)
- Modify: `app/config.py:66` (insert new block after the RADIUS block, before end of class)

**Interfaces:**
- Produces: `Config.SNMP_ENABLED: bool`, `Config.SNMP_PORT: int`, `Config.SNMP_TIMEOUT: int`, `Config.SNMP_RETRIES: int`, `Config.SNMP_POLL_INTERVAL: int`, `Config.SNMP_USER: str`, `Config.SNMP_AUTH_PROTOCOL: str`, `Config.SNMP_AUTH_KEY: str`, `Config.SNMP_PRIV_PROTOCOL: str`, `Config.SNMP_PRIV_KEY: str` — consumed by Task 2.

- [ ] **Step 1: Add the pysnmp dependency**

Run: `uv add pysnmp`

Expected: `pyproject.toml` gains `"pysnmp>=7.1"` (or whatever the resolved floor is) under `[project].dependencies`, and `uv.lock` is updated. Verify with:

```bash
grep pysnmp pyproject.toml
```

Expected output: a line containing `"pysnmp>=7.1...`

- [ ] **Step 2: Verify the pysnmp v3arch asyncio API is importable**

```bash
uv run python -c "
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd,
    USM_AUTH_HMAC96_SHA, USM_AUTH_HMAC192_SHA256,
    USM_PRIV_CFB128_AES, USM_PRIV_CFB192_AES, USM_PRIV_CFB256_AES,
)
print('pysnmp v3arch.asyncio import OK')
"
```

Expected: `pysnmp v3arch.asyncio import OK` — if this fails with `ImportError`, the installed pysnmp version has a different module layout than the one this plan was written against (verified working with `pysnmp==7.1.27`); check `pip show pysnmp` / release notes before proceeding, since every later task's imports depend on this exact path.

- [ ] **Step 3: Add the config block**

Edit `app/config.py`, inserting after line 76 (`RADIUS_GROUP_VIEWER = ...`) and before the final blank line / end of class:

```python
    # SNMP (FortiManager / FortiAnalyzer / FortiAuthenticator CPU & memory polling)
    SNMP_ENABLED = os.environ.get("SNMP_ENABLED", "false").lower() == "true"
    SNMP_PORT = int(os.environ.get("SNMP_PORT", "161"))
    SNMP_TIMEOUT = int(os.environ.get("SNMP_TIMEOUT", "5"))
    SNMP_RETRIES = int(os.environ.get("SNMP_RETRIES", "1"))
    SNMP_POLL_INTERVAL = int(os.environ.get("SNMP_POLL_INTERVAL", "60"))
    SNMP_USER = os.environ.get("SNMP_USER", "")
    SNMP_AUTH_PROTOCOL = os.environ.get("SNMP_AUTH_PROTOCOL", "SHA")
    SNMP_AUTH_KEY = os.environ.get("SNMP_AUTH_KEY", "")
    SNMP_PRIV_PROTOCOL = os.environ.get("SNMP_PRIV_PROTOCOL", "AES")
    SNMP_PRIV_KEY = os.environ.get("SNMP_PRIV_KEY", "")
```

- [ ] **Step 4: Verify config loads without error**

```bash
SECRET_KEY=test-secret uv run python -c "
from app.config import Config
print(Config.SNMP_ENABLED, Config.SNMP_PORT, Config.SNMP_POLL_INTERVAL)
"
```

Expected: `False 161 60`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock app/config.py
git commit -m "feat: add pysnmp dependency and SNMP config block"
```

---

### Task 2: `infra_health_cache.py` — SNMP poller and in-memory cache

**Files:**
- Create: `app/infra_health_cache.py`
- Test: `tests/test_infra_health_cache.py`

**Interfaces:**
- Consumes: `Config.SNMP_ENABLED`, `Config.SNMP_PORT`, `Config.SNMP_TIMEOUT`, `Config.SNMP_RETRIES`, `Config.SNMP_POLL_INTERVAL`, `Config.SNMP_USER`, `Config.SNMP_AUTH_PROTOCOL`, `Config.SNMP_AUTH_KEY`, `Config.SNMP_PRIV_PROTOCOL`, `Config.SNMP_PRIV_KEY`, `Config.INFRA_TARGETS` (from Task 1 / existing `config.py`).
- Produces: `poll_all_targets() -> None`, `get_cached(host: str) -> dict | None` (dict shape `{"cpu": float | None, "mem": float | None, "snmp_status": "ok"|"timeout"|"error", "last_updated": str}`), `init_scheduler(app: Flask) -> None` — consumed by Task 3 (scheduler registration) and Task 4 (`/api/infrastructure` route).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_infra_health_cache.py`:

```python
"""Unit tests for app.infra_health_cache — SNMP polling and cache."""

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

import pytest

from app import infra_health_cache as cache_mod


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with a clean in-memory cache."""
    with cache_mod._lock:
        cache_mod._cache.clear()
    yield
    with cache_mod._lock:
        cache_mod._cache.clear()


@pytest.fixture
def snmp_targets(monkeypatch):
    monkeypatch.setattr(
        cache_mod.Config,
        "INFRA_TARGETS",
        [
            {"label": "FMG-01", "host": "10.0.0.1", "type": "FortiManager"},
            {"label": "FAZ-01", "host": "10.0.0.2", "type": "FortiAnalyzer"},
            {"label": "FAC-01", "host": "10.0.0.3", "type": "FortiAuthenticator"},
            {"label": "FCT-01", "host": "10.0.0.4", "type": "FortiCollector"},
        ],
    )
    monkeypatch.setattr(cache_mod.Config, "SNMP_ENABLED", True)


def test_poll_all_targets_populates_cache_for_supported_types(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[12.5, 34.0])
    ):
        cache_mod.poll_all_targets()

    assert cache_mod.get_cached("10.0.0.1") == {
        "cpu": 12.5,
        "mem": 34.0,
        "snmp_status": "ok",
        "last_updated": cache_mod.get_cached("10.0.0.1")["last_updated"],
    }
    assert cache_mod.get_cached("10.0.0.2")["snmp_status"] == "ok"
    assert cache_mod.get_cached("10.0.0.3")["snmp_status"] == "ok"


def test_poll_all_targets_skips_unsupported_type(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[1.0, 2.0])
    ):
        cache_mod.poll_all_targets()

    assert cache_mod.get_cached("10.0.0.4") is None


def test_poll_all_targets_marks_timeout(snmp_targets):
    with patch.object(
        cache_mod,
        "_snmp_get",
        new=AsyncMock(side_effect=cache_mod.SnmpTimeout("no response")),
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    assert entry["snmp_status"] == "timeout"
    assert entry["cpu"] is None
    assert entry["mem"] is None


def test_poll_all_targets_marks_error_on_other_exceptions(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    assert entry["snmp_status"] == "error"
    assert entry["cpu"] is None


def test_poll_all_targets_noop_when_snmp_disabled(snmp_targets, monkeypatch):
    monkeypatch.setattr(cache_mod.Config, "SNMP_ENABLED", False)
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[1.0, 2.0])
    ) as mocked:
        cache_mod.poll_all_targets()
    mocked.assert_not_called()
    assert cache_mod.get_cached("10.0.0.1") is None


def test_get_cached_returns_copy_not_reference(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[5.0, 6.0])
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    entry["cpu"] = 999
    assert cache_mod.get_cached("10.0.0.1")["cpu"] == 5.0


def test_resolve_snmp_creds_per_device_override(monkeypatch):
    monkeypatch.setattr(cache_mod.Config, "SNMP_USER", "default-user")
    monkeypatch.setattr(cache_mod.Config, "SNMP_AUTH_KEY", "default-auth")
    monkeypatch.setattr(cache_mod.Config, "SNMP_PRIV_KEY", "default-priv")
    monkeypatch.setattr(cache_mod.Config, "SNMP_AUTH_PROTOCOL", "SHA")
    monkeypatch.setattr(cache_mod.Config, "SNMP_PRIV_PROTOCOL", "AES")

    target = {"host": "10.0.0.9", "type": "FortiAuthenticator", "snmp_user": "override-user"}
    creds = cache_mod._resolve_snmp_creds(target)

    assert creds["user"] == "override-user"
    assert creds["auth_key"] == "default-auth"  # not overridden, falls back
    assert creds["priv_key"] == "default-priv"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_infra_health_cache.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.infra_health_cache'` (or collection error) — the module doesn't exist yet.

- [ ] **Step 3: Write `app/infra_health_cache.py`**

```python
"""Background cache for SNMPv3-polled CPU/memory of infra dashboard targets.

Polls FortiManager, FortiAnalyzer, and FortiAuthenticator entries from
Config.INFRA_TARGETS over SNMPv3 on a timer, storing results in an
in-memory dict keyed by host.  Mirrors the adom_cache.py pattern: a
BackgroundScheduler job feeds a lock-guarded dict, and callers get an
instant snapshot instead of blocking on a live device query.

FortiGate firewall CPU/mem (handled elsewhere, via the FMG proxy) is out
of scope here.
"""

from __future__ import annotations

import asyncio
import datetime
import threading

from flask import Flask

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    USM_AUTH_HMAC96_SHA,
    USM_AUTH_HMAC192_SHA256,
    USM_PRIV_CFB128_AES,
    USM_PRIV_CFB192_AES,
    USM_PRIV_CFB256_AES,
)

from app.config import Config

_lock = threading.RLock()
_cache: dict = {}

_SUPPORTED_TYPES = {"fortimanager", "fortianalyzer", "fortiauthenticator"}

# CPU/mem OIDs per device type, under Fortinet's proprietary FORTINET-CORE-MIB
# (fnSysCpuUsage / fnSysMemUsage) for FortiOS-family products. FortiManager and
# FortiAnalyzer share this MIB. FortiAuthenticator's OID below is NOT yet
# confirmed against a real device or Fortinet's official
# FORTINET-FORTIAUTHENTICATOR-MIB — see Task 5 for the verification step
# required before relying on this in production.
OID_MAP = {
    "fortimanager": {
        "cpu": "1.3.6.1.4.1.12356.101.4.1.3.0",
        "mem": "1.3.6.1.4.1.12356.101.4.1.4.0",
    },
    "fortianalyzer": {
        "cpu": "1.3.6.1.4.1.12356.101.4.1.3.0",
        "mem": "1.3.6.1.4.1.12356.101.4.1.4.0",
    },
    "fortiauthenticator": {
        "cpu": "1.3.6.1.4.1.12356.113.1.2.0",
        "mem": "1.3.6.1.4.1.12356.113.1.3.0",
    },
}

_AUTH_PROTOCOLS = {
    "SHA": USM_AUTH_HMAC96_SHA,
    "SHA256": USM_AUTH_HMAC192_SHA256,
}
_PRIV_PROTOCOLS = {
    "AES": USM_PRIV_CFB128_AES,
    "AES192": USM_PRIV_CFB192_AES,
    "AES256": USM_PRIV_CFB256_AES,
}


class SnmpTimeout(Exception):
    """Raised when an SNMP GET does not receive a response before timeout."""


class SnmpQueryError(Exception):
    """Raised for any other SNMP failure (auth failure, bad OID, etc.)."""


def _resolve_snmp_creds(target: dict) -> dict:
    """Per-device snmp_* fields override the global Config.SNMP_* defaults."""
    return {
        "user": target.get("snmp_user", Config.SNMP_USER),
        "auth_key": target.get("snmp_auth_key", Config.SNMP_AUTH_KEY),
        "priv_key": target.get("snmp_priv_key", Config.SNMP_PRIV_KEY),
        "auth_protocol": target.get("snmp_auth_protocol", Config.SNMP_AUTH_PROTOCOL),
        "priv_protocol": target.get("snmp_priv_protocol", Config.SNMP_PRIV_PROTOCOL),
    }


async def _snmp_get(host: str, oids: list[str], creds: dict) -> list[float]:
    """Perform a single SNMPv3 GET for the given OIDs. Raises SnmpTimeout / SnmpQueryError."""
    engine = SnmpEngine()
    auth_data = UsmUserData(
        creds["user"],
        authKey=creds["auth_key"],
        privKey=creds["priv_key"],
        authProtocol=_AUTH_PROTOCOLS.get(creds["auth_protocol"], USM_AUTH_HMAC96_SHA),
        privProtocol=_PRIV_PROTOCOLS.get(creds["priv_protocol"], USM_PRIV_CFB128_AES),
    )
    target = await UdpTransportTarget.create(
        (host, Config.SNMP_PORT),
        timeout=Config.SNMP_TIMEOUT,
        retries=Config.SNMP_RETRIES,
    )
    error_indication, error_status, _error_index, var_binds = await get_cmd(
        engine,
        auth_data,
        target,
        ContextData(),
        *(ObjectType(ObjectIdentity(oid)) for oid in oids),
    )
    if error_indication:
        message = str(error_indication)
        if "timeout" in message.lower():
            raise SnmpTimeout(message)
        raise SnmpQueryError(message)
    if error_status:
        raise SnmpQueryError(str(error_status))
    return [float(var_bind[1]) for var_bind in var_binds]


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _poll_target(target: dict) -> dict | None:
    """Poll a single target. Returns None if its type isn't SNMP-supported."""
    device_type = target.get("type", "").lower()
    oids = OID_MAP.get(device_type)
    if not oids:
        return None
    creds = _resolve_snmp_creds(target)
    try:
        cpu, mem = asyncio.run(
            _snmp_get(target["host"], [oids["cpu"], oids["mem"]], creds)
        )
        return {"cpu": cpu, "mem": mem, "snmp_status": "ok", "last_updated": _now()}
    except SnmpTimeout:
        return {"cpu": None, "mem": None, "snmp_status": "timeout", "last_updated": _now()}
    except Exception:
        return {"cpu": None, "mem": None, "snmp_status": "error", "last_updated": _now()}


def poll_all_targets() -> None:
    """Poll every SNMP-supported target in Config.INFRA_TARGETS and update the cache."""
    if not Config.SNMP_ENABLED:
        return
    for target in Config.INFRA_TARGETS:
        if target.get("type", "").lower() not in _SUPPORTED_TYPES:
            continue
        result = _poll_target(target)
        if result is None:
            continue
        with _lock:
            _cache[target["host"]] = result


def get_cached(host: str) -> dict | None:
    """Return a shallow copy of the cached entry for host, or None if not cached."""
    with _lock:
        entry = _cache.get(host)
        return dict(entry) if entry is not None else None


def init_scheduler(app: Flask) -> None:
    """Register a recurring APScheduler job and run the first poll immediately."""
    from apscheduler.schedulers.background import BackgroundScheduler

    poll_all_targets()  # initial poll at startup

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=poll_all_targets,
        trigger="interval",
        seconds=Config.SNMP_POLL_INTERVAL,
        id="infra_health_snmp_poll",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_infra_health_cache.py -v
```

Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add app/infra_health_cache.py tests/test_infra_health_cache.py
git commit -m "feat: add SNMPv3 background poller and cache for infra health CPU/mem"
```

---

### Task 3: Register the scheduler in the app factory

**Files:**
- Modify: `app/__init__.py:110-114` (insert new guarded block after the `_MAP_CACHE_STARTED` block)

**Interfaces:**
- Consumes: `app.infra_health_cache.init_scheduler(app: Flask) -> None` (Task 2).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke.py` (append at end of file):

```python
def test_infra_health_scheduler_starts(app):
    assert app.config.get("_INFRA_HEALTH_STARTED") is not True  # not started under TESTING
```

Note: `create_app()` guards all background jobs with `not app.config.get("TESTING")`, and the `app` fixture doesn't set `TESTING`, but the real assertion we care about is that the app factory *doesn't crash* when the new block is added — the existing `test_app_creates` test already covers that. Skip adding a redundant scheduler-specific test; instead confirm behavior manually in Step 3 below.

- [ ] **Step 2: Modify `app/__init__.py`**

Insert after line 114 (the closing of the `_MAP_CACHE_STARTED` block, right before `@app.context_processor`):

```python
    if not app.config.get("TESTING") and not app.config.get("_INFRA_HEALTH_STARTED"):
        app.config["_INFRA_HEALTH_STARTED"] = True
        from app.infra_health_cache import init_scheduler as init_infra_health_scheduler

        init_infra_health_scheduler(app)
```

- [ ] **Step 3: Verify the app still starts cleanly**

```bash
SECRET_KEY=test-secret FMG_PRIMARY_HOST=127.0.0.1 uv run python -c "
from app import create_app
app = create_app()
print('app created OK, SNMP scheduler guard:', app.config.get('_INFRA_HEALTH_STARTED'))
"
```

Expected: `app created OK, SNMP scheduler guard: True` and no exceptions (with `SNMP_ENABLED` defaulting to `false`, `poll_all_targets()` is a fast no-op at startup).

- [ ] **Step 4: Run the full existing test suite to confirm no regression**

```bash
uv run pytest tests/ -v
```

Expected: all tests `PASS` (including the pre-existing `test_smoke.py` tests).

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py
git commit -m "feat: start the SNMP infra health poller at app startup"
```

---

### Task 4: Wire `/api/infrastructure` to read CPU/mem from the cache

**Files:**
- Modify: `app/routes/api_routes.py:192-316` (the `infrastructure()` view)
- Test: `tests/test_api_infrastructure_snmp.py` (new)

**Interfaces:**
- Consumes: `app.infra_health_cache.get_cached(host: str) -> dict | None` (Task 2), existing `_health_status(cpu, mem)` (`api_routes.py:16-21`).
- Produces: `/api/infrastructure` JSON response gains `snmp_status` field (`"ok"|"timeout"|"error"|None`) for SNMP-sourced entries; `status` computed as `"gray"` when `snmp_status` is `"timeout"` or `"error"` (new tier, distinct from the existing green/yellow/red, used by Task 5's frontend to show an explicit "SNMP unreachable" state rather than a false red/crit reading).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_infrastructure_snmp.py`:

```python
"""Tests for /api/infrastructure sourcing CPU/mem from the SNMP cache."""

import os
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

import pytest

from app import create_app
from app.config import Config


@pytest.fixture
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_admin(client):
    with client.session_transaction() as sess:
        sess["user"] = "test-admin"
        sess["role"] = "admin"
        sess["allowed_tabs"] = ["dashboard"]
    return client


def test_infrastructure_uses_snmp_cache_for_fortimanager(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FMG-01", "host": "10.0.0.1", "type": "FortiManager", "token": "x"}],
    )
    with patch(
        "app.infra_health_cache.get_cached",
        return_value={"cpu": 41.0, "mem": 62.0, "snmp_status": "ok", "last_updated": "2026-07-03T00:00:00"},
    ):
        resp = logged_in_admin.get("/api/infrastructure")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["cpu"] == 41.0
    assert data[0]["mem"] == 62.0
    assert data[0]["snmp_status"] == "ok"
    # cpu=41 < CPU_WARN(70), mem=62 < MEM_WARN(75) -> green
    assert data[0]["status"] == "green"


def test_infrastructure_shows_gray_on_snmp_timeout(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FAC-01", "host": "10.0.0.3", "type": "FortiAuthenticator", "token": "x"}],
    )
    with patch(
        "app.infra_health_cache.get_cached",
        return_value={"cpu": None, "mem": None, "snmp_status": "timeout", "last_updated": "2026-07-03T00:00:00"},
    ):
        resp = logged_in_admin.get("/api/infrastructure")
    data = resp.get_json()
    assert data[0]["status"] == "gray"
    assert data[0]["cpu"] is None
    assert data[0]["snmp_status"] == "timeout"


def test_infrastructure_no_cache_entry_yet(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FAZ-01", "host": "10.0.0.2", "type": "FortiAnalyzer", "token": "x"}],
    )
    with patch("app.infra_health_cache.get_cached", return_value=None):
        resp = logged_in_admin.get("/api/infrastructure")
    data = resp.get_json()
    assert data[0]["status"] == "gray"
    assert data[0]["snmp_status"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_api_infrastructure_snmp.py -v
```

Expected: FAIL — `data[0]["snmp_status"]` raises `KeyError` (field doesn't exist yet), since the route still tries the FMG JSON-RPC path unconditionally.

- [ ] **Step 3: Modify `_health_status` and the `infrastructure()` view**

In `app/routes/api_routes.py`, replace the `_health_status` function at lines 16-21:

```python
def _health_status(cpu: float, mem: float) -> str:
    if cpu >= Config.CPU_CRIT or mem >= Config.MEM_CRIT:
        return "red"
    if cpu >= Config.CPU_WARN or mem >= Config.MEM_WARN:
        return "yellow"
    return "green"


_SNMP_POLLED_TYPES = {"fortimanager", "fortianalyzer", "fortiauthenticator"}
```

Replace the body of `infrastructure()` (lines 194-316) with:

```python
@bp.route("/infrastructure")
@tab_required("dashboard")
def infrastructure():
    from app import infra_health_cache

    devices = []
    for target in Config.INFRA_TARGETS:
        entry = {
            "label": target["label"],
            "host": target["host"],
            "type": target["type"],
            "status": "unknown",
            "version": "n/a",
            "hostname": "n/a",
            "serial": "n/a",
            "uptime": "n/a",
            "cpu": None,
            "mem": None,
            "snmp_status": None,
            "ha_mode": "n/a",
            "ha_role": "n/a",
            "disk_used": "n/a",
        }

        is_snmp_type = target.get("type", "").lower() in _SNMP_POLLED_TYPES

        try:
            # Per-device token takes priority, then global token, then username/password
            client = FMGClient(
                host=target["host"],
                username=Config.FMG_USERNAME,
                password=Config.FMG_PASSWORD,
                token=target.get("token", Config.FMG_API_TOKEN),
                verify_ssl=Config.FMG_VERIFY_SSL,
                timeout=Config.FMG_TIMEOUT,
            )
            with client:
                sys_status = client.get_system_status()

            # /sys/status may return a list or dict depending on FMG version
            if isinstance(sys_status, list) and sys_status:
                sys_status = sys_status[0]
            if not isinstance(sys_status, dict):
                sys_status = {}

            # ── Hostname ──────────────────────────────────────────────────
            entry["hostname"] = (
                sys_status.get("Hostname") or sys_status.get("hostname") or "n/a"
            )

            # ── Version — FMG returns "v7.4.0 build2778 260120 (GA)"
            #    Extract just the vX.Y.Z prefix
            raw_ver = sys_status.get("Version") or sys_status.get("version") or "n/a"
            m = re.match(r"(v?\d+\.\d+[\.\d]*)", str(raw_ver))
            entry["version"] = m.group(1) if m else raw_ver

            # ── Serial ────────────────────────────────────────────────────
            entry["serial"] = (
                sys_status.get("Serial Number")
                or sys_status.get("serial_number")
                or sys_status.get("serial")
                or "n/a"
            )

            # ── Uptime ────────────────────────────────────────────────────
            entry["uptime"] = (
                sys_status.get("System time") or sys_status.get("uptime") or "n/a"
            )

            # ── HA — FMG /sys/status returns flat keys "HA Mode" / "HA Role"
            #    (not a nested {"HA": {"Mode": ...}} dict)
            entry["ha_mode"] = (
                sys_status.get("HA Mode")
                or sys_status.get("ha_mode")
                or (sys_status.get("HA") or {}).get("Mode")
                or "n/a"
            )
            entry["ha_role"] = (
                sys_status.get("HA Role")
                or sys_status.get("ha_role")
                or (sys_status.get("HA") or {}).get("Role")
                or "n/a"
            )

            # ── Disk ──────────────────────────────────────────────────────
            disk_info = sys_status.get("disk info") or sys_status.get("Disk info") or {}
            if disk_info and isinstance(disk_info, dict):
                used = disk_info.get("used", disk_info.get("Used", "n/a"))
                total = disk_info.get("total", disk_info.get("Total", "n/a"))
                entry["disk_used"] = f"{used}/{total}" if used != "n/a" else "n/a"

            if is_snmp_type:
                # ── CPU & Memory — sourced from the SNMP background cache ──
                cached = infra_health_cache.get_cached(target["host"])
                if cached is None:
                    entry["status"] = "gray"
                elif cached["snmp_status"] == "ok":
                    entry["cpu"] = cached["cpu"]
                    entry["mem"] = cached["mem"]
                    entry["snmp_status"] = "ok"
                    entry["status"] = _health_status(cached["cpu"], cached["mem"])
                else:
                    entry["snmp_status"] = cached["snmp_status"]
                    entry["status"] = "gray"
            else:
                # ── CPU & Memory — legacy FMG JSON-RPC path (FortiCollector, etc.) ──
                perf = client.get_performance()
                usage = client.get_resource_usage()
                if isinstance(perf, list) and perf:
                    perf = perf[0]
                if not isinstance(perf, dict):
                    perf = {}
                if isinstance(usage, list) and usage:
                    usage = usage[0]
                if not isinstance(usage, dict):
                    usage = {}

                no_resource_data = not perf and not usage
                cpu_val = _parse_cpu(perf, usage, sys_status)
                mem_val = _parse_mem(perf, usage, sys_status)

                if no_resource_data and cpu_val == 0.0 and mem_val == 0.0:
                    entry["cpu"] = None
                    entry["mem"] = None
                else:
                    entry["cpu"] = round(cpu_val, 1)
                    entry["mem"] = round(mem_val, 1)
                entry["status"] = _health_status(cpu_val, mem_val)

        except Exception:
            entry["status"] = "red"
            entry["error"] = "Unable to query target"
        devices.append(entry)
    return jsonify(devices)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_api_infrastructure_snmp.py -v
```

Expected: all tests `PASS`.

- [ ] **Step 5: Run the full test suite to confirm no regression**

```bash
uv run pytest tests/ -v
```

Expected: all tests `PASS`.

- [ ] **Step 6: Commit**

```bash
git add app/routes/api_routes.py tests/test_api_infrastructure_snmp.py
git commit -m "feat: source FortiManager/FortiAnalyzer/FortiAuthenticator CPU/mem from SNMP cache"
```

---

### Task 5: Frontend — render CPU/mem and a "gray" SNMP-unreachable state

**Files:**
- Modify: `app/static/js/dashboard.js:94-127` (`renderCard()`)
- Modify: `app/static/css/style.css` (add `.status-gray` stripe/dot rules alongside the existing green/yellow/red rules)

**Interfaces:**
- Consumes: `/api/infrastructure` response fields `cpu: number|null`, `mem: number|null`, `status: "green"|"yellow"|"red"|"gray"|"unknown"`, `snmp_status: "ok"|"timeout"|"error"|null` (Task 4).

- [ ] **Step 1: Add `.status-gray` CSS rules**

In `app/static/css/style.css`, find the existing block (around line 252-254):

```css
.infra-card.status-green  .infra-card-stripe { background: var(--status-green); }
.infra-card.status-yellow .infra-card-stripe { background: var(--status-yellow); }
.infra-card.status-red    .infra-card-stripe { background: var(--status-red); }
```

Add a `gray` variant immediately after:

```css
.infra-card.status-gray   .infra-card-stripe { background: #9ca3af; }
```

- [ ] **Step 2: Update `renderCard()` in `dashboard.js`**

Replace the function body (lines 94-127) with:

```javascript
function renderCard(d) {
  const statusClass = `status-${d.status || 'unknown'}`;

  const diskRow = d.disk_used && d.disk_used !== 'n/a'
    ? `<div class="card-row"><span class="card-row-label">Disk</span><span class="card-row-value">${escHtml(d.disk_used)}</span></div>`
    : '';

  let cpuMemRow;
  if (d.snmp_status && d.snmp_status !== 'ok') {
    const label = d.snmp_status === 'timeout' ? 'SNMP timeout' : 'SNMP unreachable';
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value text-muted">${escHtml(label)}</span></div>`;
  } else if (d.cpu !== null && d.cpu !== undefined && d.mem !== null && d.mem !== undefined) {
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value">${d.cpu}% / ${d.mem}%</span></div>`;
  } else {
    cpuMemRow = '';
  }

  const errorRow = d.error
    ? `<div class="card-row card-row-error"><span class="card-row-value text-danger">${escHtml(d.error)}</span></div>`
    : '';

  return `
<div class="infra-card ${statusClass}">
  <div class="infra-card-stripe"></div>
  <div class="infra-card-body">
    <div class="card-name-block">
      <div class="card-title">${escHtml(d.label)}</div>
      <div class="card-subtitle">${escHtml(d.host)} &bull; ${escHtml(d.type)}</div>
    </div>
    <div class="card-detail-block">
      <div class="card-col card-col-hostname">
        <div class="card-row"><span class="card-row-label">Hostname</span><span class="card-row-value">${escHtml(d.hostname)}</span></div>
      </div>
      <div class="card-col card-col-meta">
        <div class="card-row"><span class="card-row-label">Version</span><span class="card-row-value">${escHtml(d.version)}</span></div>
        <div class="card-row"><span class="card-row-label">Serial</span><span class="card-row-value">${escHtml(d.serial)}</span></div>
        <div class="card-row"><span class="card-row-label">HA Mode / Role</span><span class="card-row-value">${escHtml(d.ha_mode)} / ${escHtml(d.ha_role)}</span></div>
        ${cpuMemRow}
        ${diskRow}
      </div>
      ${errorRow}
    </div>
  </div>
</div>`;
}
```

- [ ] **Step 3: Manually verify in a browser**

```bash
python wsgi.py
```

Navigate to `https://localhost:5443/`, log in, and confirm the Infrastructure Health cards render without console errors. Since `SNMP_ENABLED=false` by default (Task 1), every SNMP-typed card should show the gray-stripe / "SNMP unreachable" state (no `snmp_status` key or `snmp_status: null` before any poll — verify the "no cache entry yet" branch from Task 4 also degrades to the same gray "CPU / Mem" text, not a JS error).

- [ ] **Step 4: Commit**

```bash
git add app/static/js/dashboard.js app/static/css/style.css
git commit -m "feat: render CPU/mem and SNMP-unreachable state on infra health cards"
```

---

### Task 6: `infra_targets.json` schema docs + CLAUDE.md documentation

**Files:**
- Modify: `infra_targets.example.json`
- Modify: `CLAUDE.md:32-43` (env var block + infra targets section)

**Interfaces:** None (documentation-only task).

- [ ] **Step 1: Add SNMP override fields to `infra_targets.example.json`**

Replace the full file content with:

```json
[
  { "label": "FortiManager Primary",    "host": "10.0.0.1",   "type": "FortiManager",      "token": "fmg-primary-bearer-token" },
  { "label": "FortiManager Backup",     "host": "10.0.0.2",   "type": "FortiManager",      "token": "fmg-backup-bearer-token" },
  { "label": "FortiAnalyzer Primary",   "host": "10.0.0.3",   "type": "FortiAnalyzer",     "token": "faz-primary-bearer-token" },
  { "label": "FortiAnalyzer Backup",    "host": "10.0.0.4",   "type": "FortiAnalyzer",     "token": "faz-backup-bearer-token" },
  { "label": "FortiCollector #1",       "host": "10.0.0.5",   "type": "FortiCollector",    "token": "fct-1-bearer-token" },
  { "label": "FortiCollector #2",       "host": "10.0.0.6",   "type": "FortiCollector",    "token": "fct-2-bearer-token" },
  { "label": "FortiAuthenticator #1",   "host": "10.0.0.7",   "type": "FortiAuthenticator","token": "fac-1-bearer-token",
    "snmp_user": "monitor2", "snmp_auth_key": "example-auth-key", "snmp_priv_key": "example-priv-key" },
  { "label": "FortiAuthenticator #2",   "host": "10.0.0.8",   "type": "FortiAuthenticator","token": "fac-2-bearer-token" }
]
```

- [ ] **Step 2: Verify it's valid JSON**

```bash
python -c "import json; json.load(open('infra_targets.example.json')); print('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 3: Update `CLAUDE.md`'s env var block**

In `CLAUDE.md`, find the config block (lines 32-36):

```
FMG_VERIFY_SSL=false
CPU_WARN=70  CPU_CRIT=90
MEM_WARN=75  MEM_CRIT=90
SUMMARY_REFRESH_HOUR=1   # nightly summary recalculation hour (default 01:00)
SUMMARY_REFRESH_MINUTE=0
```

Replace with:

```
FMG_VERIFY_SSL=false
CPU_WARN=70  CPU_CRIT=90
MEM_WARN=75  MEM_CRIT=90
SUMMARY_REFRESH_HOUR=1   # nightly summary recalculation hour (default 01:00)
SUMMARY_REFRESH_MINUTE=0
SNMP_ENABLED=false       # enable SNMPv3 polling for FortiManager/FortiAnalyzer/FortiAuthenticator CPU/mem
SNMP_PORT=161
SNMP_TIMEOUT=5
SNMP_RETRIES=1
SNMP_POLL_INTERVAL=60    # seconds between background poll cycles
SNMP_USER=monitor
SNMP_AUTH_PROTOCOL=SHA   # SHA | SHA256
SNMP_AUTH_KEY=
SNMP_PRIV_PROTOCOL=AES   # AES | AES192 | AES256
SNMP_PRIV_KEY=
```

- [ ] **Step 4: Update the "Infrastructure dashboard targets" section**

In `CLAUDE.md`, find (lines 39-43):

```
Infrastructure dashboard targets (FortiManager, FortiAnalyzer, FortiCollector, FortiAuthenticator, etc.)
are defined in `infra_targets.json` (gitignored). Copy `infra_targets.example.json` to get started.
Each entry is `{ "label": "...", "host": "...", "type": "..." }`. Add or remove entries freely.
An optional `"token"` field on any entry sets a per-device bearer token (each Fortinet appliance
type generates its own token). Token priority: per-device `"token"` → `FMG_API_TOKEN` → username/password.
```

Append immediately after (still within the same section, before the next `##` heading):

```

CPU/memory for `FortiManager`, `FortiAnalyzer`, and `FortiAuthenticator` entries is sourced via
SNMPv3 polling (see `app/infra_health_cache.py`), not FMG JSON-RPC — FortiAuthenticator in
particular has no JSON-RPC status/resource API. A background poller
(`app/infra_health_cache.py`, `SNMP_POLL_INTERVAL` seconds, default 60) queries each target and
caches `{cpu, mem, snmp_status}`; `/api/infrastructure` reads instantly from this cache. Optional
per-device `"snmp_user"` / `"snmp_auth_key"` / `"snmp_priv_key"` / `"snmp_auth_protocol"` /
`"snmp_priv_protocol"` fields override the global `SNMP_*` `.env` defaults, following the same
override-over-default pattern as `"token"`. `FortiCollector` entries (and any other type) continue
to use the legacy FMG JSON-RPC CPU/mem path unchanged.

CPU/mem OIDs live in `OID_MAP` in `app/infra_health_cache.py`. FortiManager/FortiAnalyzer OIDs are
under Fortinet's shared `FORTINET-CORE-MIB`. The FortiAuthenticator OID has not been confirmed
against a real device — verify with `snmpwalk` or Fortinet's official
`FORTINET-FORTIAUTHENTICATOR-MIB` before enabling `SNMP_ENABLED=true` in an environment with
FortiAuthenticator targets.
```

- [ ] **Step 5: Commit**

```bash
git add infra_targets.example.json CLAUDE.md
git commit -m "docs: document SNMP infra health polling config and infra_targets.json fields"
```

---

## Post-Plan Manual Verification (not a task — required before production rollout)

The plan above ships working, tested code with `SNMP_ENABLED=false` by default, so it's safe to merge without live devices. Before setting `SNMP_ENABLED=true` against real FortiManager/FortiAnalyzer/FortiAuthenticator devices:

1. Enable SNMPv3 on each device (FortiManager/FortiAnalyzer: `config system snmp user` CLI or GUI; FortiAuthenticator: System → SNMP).
2. Run `snmpwalk -v3 -l authPriv -u <user> -a <authProto> -A <authKey> -x <privProto> -X <privKey> <host> 1.3.6.1.4.1.12356` against one device of each type and compare against `OID_MAP` in `app/infra_health_cache.py` — correct the FortiAuthenticator OIDs (and any others that don't match) before relying on this in production.
3. Set the real `.env` `SNMP_*` values and `SNMP_ENABLED=true`, restart the app, and confirm `/api/infrastructure` returns non-null `cpu`/`mem` with `snmp_status: "ok"` for each target.
