# Security Fix — P1 Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address all P1 security and efficiency findings from the `todo.md` code review, plus the one high-impact P2 item (`zone_db.save_db` atomicity), on the `security-fix` branch.

**Architecture:** Four targeted, independent changes: (1) per-request role/permission revalidation + absolute session cap, (2) ProxyFix gated by an env var, (3) rate-limiter username normalisation + memory bound, (4) `requests.Session` reuse in `FMGClient` + hoist `make_client()` out of the device-review loop. A fifth micro-change fixes `zone_db.save_db` atomicity. No new dependencies (werkzeug's `ProxyFix` is already bundled).

**Tech Stack:** Python 3.11+, Flask, Werkzeug, `requests`, `uv` for dependency management, `pytest` for tests.

## Global Constraints

- All changes go on branch `security-fix` (branch from current `main` HEAD).
- Run the full test suite (`pytest tests/ -v`) before each commit; it must pass.
- Do **not** introduce new pip dependencies — Werkzeug's `ProxyFix` is already available; `requests.Session` is already imported.
- Do not break the existing CSRF, CSP, or cookie config.
- Do not modify `CLAUDE.md` or `todo.md` (docs-only fixes are a separate task for a human).

---

## Task 1: Create `security-fix` branch

**Files:**
- No code changes — branch creation only.

- [ ] **Step 1: Create and switch to the branch**

```bash
git checkout -b security-fix
```

Expected: `Switched to a new branch 'security-fix'`

- [ ] **Step 2: Verify clean state**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Task 2: Per-request role/permission revalidation + absolute session cap

**Files:**
- Modify: `app/decorators.py` — add `_revalidate_session()` helper; call it inside `login_required`, `tab_required`, and `admin_required`.
- Modify: `app/config.py` — add `SESSION_ABSOLUTE_LIFETIME` config constant.
- Modify: `app/routes/auth_routes.py` — stamp `login_at` into the session at login.
- Test: `tests/test_session_revalidation.py`

**Interfaces:**
- Produces: `_revalidate_session()` in `app/decorators.py` — called at the top of every decorator's inner function; returns a Flask response (redirect or JSON 401/403) if session is stale or user is demoted, else `None`.

**Why this matters (from todo.md):** `role` and `allowed_tabs` are snapshotted at login and never re-checked. Deleting or demoting a user has no effect on their live session. The sliding `PERMANENT_SESSION_LIFETIME` means an active session never expires.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_revalidation.py`:

```python
import os, json, time, pytest
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

from unittest.mock import patch, MagicMock
from flask import session as flask_session


def _make_app(users):
    """Return a test Flask app with a minimal users.json mock."""
    with patch("app.auth.USERS_FILE") as mock_path:
        mock_path.exists.return_value = True
        mock_path.open.return_value.__enter__ = lambda s: s
        mock_path.open.return_value.__exit__ = MagicMock(return_value=False)
        mock_path.open.return_value.read = lambda: json.dumps(users)
        from app import create_app
        app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture()
def client(tmp_path):
    users = {"alice": {"password_hash": "$2b$12$placeholder", "role": "viewer"}}
    users_path = tmp_path / "users.json"
    users_path.write_text(json.dumps(users))

    with patch("app.auth.USERS_FILE", users_path), \
         patch("app.groups.GROUPS_FILE", tmp_path / "groups.json"):
        (tmp_path / "groups.json").write_text("{}")
        from app import create_app
        app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, tmp_path


def test_expired_session_is_rejected(client):
    """A session older than SESSION_ABSOLUTE_LIFETIME should be rejected."""
    c, tmp_path = client
    with c.session_transaction() as sess:
        sess["user"] = "alice"
        sess["role"] = "viewer"
        sess["allowed_tabs"] = []
        sess["login_at"] = 0  # epoch — definitely expired

    resp = c.get("/")
    assert resp.status_code in (302, 401, 403)


def test_fresh_session_is_accepted(client):
    """A session stamped right now should pass the absolute cap check."""
    c, tmp_path = client
    with c.session_transaction() as sess:
        sess["user"] = "alice"
        sess["role"] = "viewer"
        sess["allowed_tabs"] = []
        sess["login_at"] = int(time.time())

    resp = c.get("/")
    # A viewer with no tabs gets redirected (302), not 401/403
    assert resp.status_code in (200, 302)


def test_deleted_user_session_is_rejected(client):
    """If the user is removed from users.json, their session should be invalidated."""
    c, tmp_path = client
    with c.session_transaction() as sess:
        sess["user"] = "gone_user"
        sess["role"] = "viewer"
        sess["allowed_tabs"] = []
        sess["login_at"] = int(time.time())

    resp = c.get("/")
    assert resp.status_code in (302, 401, 403)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_session_revalidation.py -v
```

Expected: FAIL (no `login_at` check exists yet)

- [ ] **Step 3: Add `SESSION_ABSOLUTE_LIFETIME` to `app/config.py`**

After the existing `PERMANENT_SESSION_LIFETIME = 3600` line, add:

```python
    # Absolute session cap — no matter how active, sessions expire after this many seconds.
    SESSION_ABSOLUTE_LIFETIME = int(os.environ.get("SESSION_ABSOLUTE_LIFETIME", str(10 * 3600)))  # 10 h
```

- [ ] **Step 4: Stamp `login_at` in `app/routes/auth_routes.py`**

In the `login()` route, inside the `if auth_result is not None:` block, after `session["allowed_tabs"] = allowed`, add:

```python
            import time as _time
            session["login_at"] = int(_time.time())
```

- [ ] **Step 5: Add `_revalidate_session()` to `app/decorators.py`**

Add the following near the top of `app/decorators.py`, after the existing imports:

```python
import time as _time
from flask import current_app


def _revalidate_session() -> "tuple | None":
    """Re-check that the session is still valid on every request.

    Returns a Flask response tuple (to be returned immediately) if the
    session is stale or the user no longer exists, else None.
    """
    # --- Absolute session cap ---
    login_at = flask_session.get("login_at")
    if login_at is None:
        # Session pre-dates this feature — force re-login.
        flask_session.clear()
        return redirect(url_for("auth.login")), 302

    lifetime = current_app.config.get("SESSION_ABSOLUTE_LIFETIME", 36000)
    if _time.time() - login_at > lifetime:
        flask_session.clear()
        if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
            return jsonify({"error": "Session expired"}), 401
        return redirect(url_for("auth.login")), 302

    # --- User still exists + role unchanged ---
    username = flask_session.get("user", "")
    if username:
        from app.auth import _load_users
        from app.groups import get_allowed_tabs
        users = _load_users()
        entry = users.get(username)
        if entry is None:
            flask_session.clear()
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.login")), 302
        # Re-sync role and tabs from disk
        flask_session["role"] = entry.get("role", "viewer")
        ad_groups = flask_session.get("ad_groups", [])
        flask_session["allowed_tabs"] = list(
            get_allowed_tabs(username, ad_groups=ad_groups)
        )

    return None
```

**Note:** `flask_session` is the Flask `session` proxy; `redirect`, `url_for`, `request`, `jsonify` are already imported at the top of the file. Rename the import alias for `session` to avoid shadowing:

At the top of `app/decorators.py`, replace:
```python
from flask import session, redirect, url_for, abort, jsonify, request
```
with:
```python
from flask import session as flask_session, redirect, url_for, abort, jsonify, request
```

Then update all existing `session.get(` references in the file to `flask_session.get(`.

- [ ] **Step 6: Call `_revalidate_session()` in each decorator**

In `login_required`, inside the `decorated` function body, after the `"user" not in session` check and before `return f(*args, **kwargs)`, add:

```python
        err = _revalidate_session()
        if err is not None:
            return err
```

Do the same inside `tab_required`'s `decorated` function and inside `admin_required`'s `decorated` function (after the existing `"user" not in session` guard in each).

- [ ] **Step 7: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass, including the three new `test_session_revalidation` tests.

- [ ] **Step 8: Commit**

```bash
git add app/config.py app/decorators.py app/routes/auth_routes.py tests/test_session_revalidation.py
git commit -m "security: revalidate role/permissions per-request; add absolute session cap"
```

---

## Task 3: ProxyFix — fix IP detection behind a reverse proxy

**Files:**
- Modify: `wsgi.py` — conditionally apply `ProxyFix` based on `TRUSTED_PROXY_COUNT` env var.
- Modify: `.env.example` (if it exists) — document the new variable.
- Test: `tests/test_proxy_fix.py`

**Why this matters (from todo.md):** Behind a reverse proxy, `request.remote_addr` is the proxy's IP, so all users share one rate-limit bucket (lockout DoS). HSTS is also emitted on a blindly-trusted `X-Forwarded-Proto` header.

**Interfaces:**
- Produces: `wsgi.py` wraps `app` with `ProxyFix(app, x_for=N, x_proto=N, x_host=N)` when `TRUSTED_PROXY_COUNT` is a positive integer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_proxy_fix.py`:

```python
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")


def test_proxy_fix_applied_when_env_set(monkeypatch):
    """When TRUSTED_PROXY_COUNT is set, the wsgi app should be wrapped with ProxyFix."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    # Re-import wsgi to pick up the env var change
    import importlib
    import wsgi as wsgi_mod
    importlib.reload(wsgi_mod)
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(wsgi_mod.app, ProxyFix)


def test_proxy_fix_not_applied_by_default(monkeypatch):
    """Without TRUSTED_PROXY_COUNT, wsgi app should NOT be wrapped with ProxyFix."""
    monkeypatch.delenv("TRUSTED_PROXY_COUNT", raising=False)
    import importlib
    import wsgi as wsgi_mod
    importlib.reload(wsgi_mod)
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert not isinstance(wsgi_mod.app, ProxyFix)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_proxy_fix.py -v
```

Expected: FAIL (ProxyFix not wired yet)

- [ ] **Step 3: Read current `wsgi.py`**

Read the full file before editing.

- [ ] **Step 4: Apply ProxyFix in `wsgi.py`**

After the line that creates `app = create_app()`, add:

```python
import os as _os
_proxy_count = int(_os.environ.get("TRUSTED_PROXY_COUNT", "0"))
if _proxy_count > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app = ProxyFix(app, x_for=_proxy_count, x_proto=_proxy_count, x_host=_proxy_count)
```

- [ ] **Step 5: Document in `.env.example`**

Find `TRUSTED_PROXY_COUNT` is not yet present. Add to the end of `.env.example` (if the file exists):

```
# Set to the number of trusted reverse proxies in front of this app (e.g. 1 for nginx/caddy).
# Enables X-Forwarded-For IP detection for rate limiting and HSTS.
# TRUSTED_PROXY_COUNT=1
```

If `.env.example` does not exist, skip this step.

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add wsgi.py
git commit -m "security: apply ProxyFix when TRUSTED_PROXY_COUNT is set"
```

---

## Task 4: Rate-limiter hardening — username normalisation + memory bound

**Files:**
- Modify: `app/routes/auth_routes.py` — normalise usernames; cap `_user_failures` dict size.
- Test: `tests/test_rate_limiter.py`

**Why this matters (from todo.md):** `Admin`/`admin`/` admin` are distinct rate-limit buckets, trivially evading the per-username limit. An attacker can also grow `_user_failures` without bound.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rate_limiter.py`:

```python
import os, time
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

from unittest.mock import patch
import importlib


def _fresh_module():
    """Import auth_routes with a clean rate-limiter state."""
    import app.routes.auth_routes as m
    importlib.reload(m)
    return m


def test_username_case_normalisation():
    """'Admin' and 'admin' should share the same rate-limit bucket."""
    m = _fresh_module()
    now = time.monotonic()
    # Inject failures under 'admin' (lowercase)
    with m._lock:
        m._user_failures["admin"] = [now] * m._USER_MAX

    # Checking 'Admin' (mixed case) should see those failures
    assert m._is_rate_limited("1.2.3.4", "Admin") is True


def test_username_strip_normalisation():
    """' admin ' (with spaces) should be normalised to 'admin'."""
    m = _fresh_module()
    now = time.monotonic()
    with m._lock:
        m._user_failures["admin"] = [now] * m._USER_MAX

    assert m._is_rate_limited("1.2.3.4", " admin ") is True


def test_user_failures_memory_bound():
    """_user_failures dict should not exceed _USER_FAILURES_MAX_KEYS entries."""
    m = _fresh_module()
    for i in range(m._USER_FAILURES_MAX_KEYS + 50):
        m._record_failure("1.2.3.4", f"attacker_{i}")

    assert len(m._user_failures) <= m._USER_FAILURES_MAX_KEYS
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_rate_limiter.py -v
```

Expected: FAIL (no normalisation or size cap yet)

- [ ] **Step 3: Add `_USER_FAILURES_MAX_KEYS` constant and normalisation to `app/routes/auth_routes.py`**

After the existing constants block (`_WINDOW_SECONDS`, `_IP_MAX`, `_USER_MAX`), add:

```python
_USER_FAILURES_MAX_KEYS = 10_000  # memory bound on the attacker-controlled key space
```

Create a normalisation helper after `_lock`:

```python
def _norm_username(username: str) -> str:
    return username.strip().lower()
```

In `_is_rate_limited`, replace the `_user_failures[username]` references with `_user_failures[_norm_username(username)]`:

```python
def _is_rate_limited(ip: str, username: str) -> bool:
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    norm = _norm_username(username)
    with _lock:
        _ip_failures[ip] = [t for t in _ip_failures[ip] if t > cutoff]
        _user_failures[norm] = [t for t in _user_failures[norm] if t > cutoff]
        return (
            len(_ip_failures[ip]) >= _IP_MAX
            or len(_user_failures[norm]) >= _USER_MAX
        )
```

In `_record_failure`, apply normalisation and add the size cap:

```python
def _record_failure(ip: str, username: str) -> None:
    now = time.monotonic()
    norm = _norm_username(username)
    with _lock:
        _ip_failures[ip].append(now)
        # Evict oldest key if at capacity (FIFO approximation using dict ordering)
        if len(_user_failures) >= _USER_FAILURES_MAX_KEYS and norm not in _user_failures:
            oldest_key = next(iter(_user_failures))
            del _user_failures[oldest_key]
        _user_failures[norm].append(now)
```

In `_clear_failures`, normalise:

```python
def _clear_failures(ip: str, username: str) -> None:
    norm = _norm_username(username)
    with _lock:
        _ip_failures.pop(ip, None)
        _user_failures.pop(norm, None)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes/auth_routes.py tests/test_rate_limiter.py
git commit -m "security: normalise usernames in rate limiter; bound _user_failures dict size"
```

---

## Task 5: Reuse HTTP connections in `FMGClient` (`requests.Session`)

**Files:**
- Modify: `app/fmg_client.py` — `__init__` creates `self._http = requests.Session()`; `_post` and `_get_paged` use it; `__exit__` closes it.
- Test: `tests/test_fmg_client_session.py`

**Why this matters (from todo.md):** Every JSON-RPC call opens a fresh TCP+TLS connection. A single device-review run issues ~16 proxy calls, each paying a full TLS handshake. One `requests.Session` reuses the connection pool for free.

**Interfaces:**
- Consumes: existing `FMGClient.__init__` signature (no change to callers).
- Produces: `self._http` (`requests.Session`) set in `__init__`; used in `_post` and `_get_paged`; closed in `__exit__`.

- [ ] **Step 1: Locate `FMGClient.__init__` and `__exit__`**

Read `app/fmg_client.py` lines around `__init__` to confirm the attribute list and `__exit__` body.

```bash
grep -n "__init__\|__exit__\|self\." app/fmg_client.py | head -30
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_fmg_client_session.py`:

```python
import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

from unittest.mock import patch, MagicMock
import requests


def test_fmg_client_uses_requests_session():
    """FMGClient._post must use self._http (a requests.Session), not module-level requests.post."""
    from app.fmg_client import FMGClient
    client = FMGClient(host="fmg.example.com", token="tok")
    assert hasattr(client, "_http"), "FMGClient must have a _http attribute"
    import requests as req_mod
    assert isinstance(client._http, req_mod.Session)


def test_fmg_client_http_session_closed_on_exit():
    """Exiting the context manager must close the underlying requests.Session."""
    from app.fmg_client import FMGClient
    client = FMGClient(host="fmg.example.com", token="tok")
    mock_session = MagicMock()
    client._http = mock_session
    client.__exit__(None, None, None)
    mock_session.close.assert_called_once()
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest tests/test_fmg_client_session.py -v
```

Expected: FAIL (`_http` attribute does not exist)

- [ ] **Step 4: Add `self._http = requests.Session()` to `FMGClient.__init__`**

Read the `__init__` body first, then add `self._http = requests.Session()` as the last line of `__init__`.

- [ ] **Step 5: Replace `requests.post(...)` in `_post` with `self._http.post(...)`**

In `_post` (around line 127), change:
```python
        resp = requests.post(
            self.base_url,
            json=body,
            verify=self.verify_ssl,
            timeout=self.timeout,
            headers=headers,
        )
```
to:
```python
        resp = self._http.post(
            self.base_url,
            json=body,
            verify=self.verify_ssl,
            timeout=self.timeout,
            headers=headers,
        )
```

- [ ] **Step 6: Replace `_req.post(...)` in `_get_paged` with `self._http.post(...)`**

In `_get_paged` (around line 672–683), remove the `import requests as _req` inline import and change:
```python
            resp = _req.post(
```
to:
```python
            resp = self._http.post(
```

- [ ] **Step 7: Close the session in `__exit__`**

Find `__exit__` in `fmg_client.py`. After the `self.logout()` call, add:

```python
        self._http.close()
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add app/fmg_client.py tests/test_fmg_client_session.py
git commit -m "efficiency: reuse HTTP connections in FMGClient via requests.Session"
```

---

## Task 6: Hoist `make_client()` out of the device-review per-device loop

**Files:**
- Modify: `app/routes/device_review_routes.py` — move `make_client()` outside the `for dev in all_devices:` loop.
- Test: No new test file needed — the existing smoke test + manual inspection confirm the loop structure.

**Why this matters (from todo.md):** Under password auth, the current code opens one login/logout FMG round-trip *per device*. Moving `make_client()` outside the loop reduces it to one login for the entire bulk run.

- [ ] **Step 1: Read the bulk-run route to understand the loop**

Read `app/routes/device_review_routes.py` lines 260–310 to confirm the loop structure before editing.

- [ ] **Step 2: Restructure the loop**

The current pattern is:
```python
for dev in all_devices:
    ...
    try:
        with make_client() as client:
            device_data = _fetch_device_data(client, adom, name, needed, dev)
    except Exception:
        device_data = {}
```

Replace with a single client for the whole loop:
```python
try:
    _client_ctx = make_client()
    client = _client_ctx.__enter__()
except Exception:
    client = None
    _client_ctx = None

try:
    for dev in all_devices:
        if not isinstance(dev, dict):
            continue
        name = dev.get("name", "")
        if not name:
            continue
        reviewed.append(name)
        try:
            device_data = _fetch_device_data(client, adom, name, needed, dev) if client else {}
        except Exception:
            device_data = {}
        rows.extend(run_checks(name, device_data, check_keys, check_params))
finally:
    if _client_ctx is not None:
        _client_ctx.__exit__(None, None, None)
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add app/routes/device_review_routes.py
git commit -m "efficiency: hoist make_client() outside device-review per-device loop"
```

---

## Task 7: Atomic `zone_db.save_db` write

**Files:**
- Modify: `app/zone_db.py` — use `tmp + os.replace` pattern.
- Test: `tests/test_zone_db_atomic.py`

**Why this matters (from todo.md):** A crash mid-write corrupts `policy_db.json`. `api_tokens.py` and `app_settings.py` already use the atomic pattern.

- [ ] **Step 1: Write the failing test**

Create `tests/test_zone_db_atomic.py`:

```python
import os, json, inspect
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")


def test_save_db_is_atomic(tmp_path, monkeypatch):
    """save_db should write to a temp file and rename, not write in-place."""
    import app.zone_db as zdb
    monkeypatch.setattr(zdb, "DB_PATH", tmp_path / "policy_db.json")

    db = {"zones": {}, "policies": []}
    zdb.save_db(db)

    assert (tmp_path / "policy_db.json").exists()
    with open(tmp_path / "policy_db.json") as f:
        result = json.load(f)
    assert result == db


def test_save_db_uses_replace(tmp_path, monkeypatch):
    """Verify os.replace is used (not a plain open write) by inspecting source."""
    import app.zone_db as zdb
    src = inspect.getsource(zdb.save_db)
    assert "os.replace" in src or "replace(" in src, \
        "save_db must use os.replace for atomic writes"
```

- [ ] **Step 2: Run to verify second test fails**

```bash
pytest tests/test_zone_db_atomic.py -v
```

Expected: `test_save_db_uses_replace` FAIL (currently uses plain `open`)

- [ ] **Step 3: Update `save_db` in `app/zone_db.py`**

Add `import os` near the top if not already present (check the import block), then replace:

```python
def save_db(db: dict) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
```

with:

```python
def save_db(db: dict) -> None:
    tmp = DB_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, DB_PATH)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/zone_db.py tests/test_zone_db_atomic.py
git commit -m "fix: make zone_db.save_db atomic using tmp + os.replace"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run the full test suite one last time**

```bash
pytest tests/ -v
```

Expected: All tests pass, no regressions.

- [ ] **Step 2: Review the branch diff against main**

```bash
git diff main..security-fix --stat
```

Expected: Only the files listed in Tasks 2–7 appear.

- [ ] **Step 3: Cross-check todo.md P1 items**

Confirm each P1 item is addressed:
- [x] Revalidate role/permissions per request; add absolute session cap → Task 2
- [x] ProxyFix behind a trusted-proxy env var → Task 3
- [x] Rate-limiter hardening (username normalisation + memory bound) → Task 4
- [x] FMGClient HTTP session reuse → Task 5
- [x] Hoist make_client() out of device-review loop → Task 6
- [x] zone_db.save_db atomic write (P2 but trivial, included) → Task 7

**Note:** `'unsafe-inline'` CSP drop (P1 todo item 3) is intentionally excluded from this plan — it requires auditing and refactoring every inline `<script>` block in multiple templates, which is a larger, separate task.

---

## Out of scope (separate tasks)

- Drop `'unsafe-inline'` from `script-src` — requires template refactor (multiple HTML files).
- P2+ items (token lifecycle, external API hardening, RADIUS Message-Authenticator, audit log, cache headers, compression, static asset caching).
- CLAUDE.md docs-only fixes.
