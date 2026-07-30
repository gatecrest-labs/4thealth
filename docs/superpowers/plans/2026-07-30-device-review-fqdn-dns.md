# Device Review FQDN/DNS Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow CIS check param fields to accept FQDNs alongside IPs, auto-resolve mismatches via DNS, show per-entry match detail, and populate the IP column for server-address checks.

**Architecture:** All changes are confined to `app/device_review.py`. Three new helpers (`_parse_host_list`, `_resolve_host`, `_match_host`) replace and extend the existing `_parse_ip_list`. Four check functions (`_run_ntp_config`, `_run_syslog_config`, `_run_log_faz`, `_run_dns`) are updated to use the new helpers, produce richer detail strings, and populate the `ip` row field. Placeholder text in the `CHECKS` registry is updated. No routes, templates, or frontend JS files change.

**Tech Stack:** Python 3.x stdlib only (`socket`). pytest for tests. No new dependencies.

## Global Constraints

- No new Python dependencies — use `socket` (stdlib) for DNS resolution.
- No changes to `device_review_routes.py`, `device_review.js`, or any template file.
- All existing tests must continue to pass.
- Run tests with: `python -m pytest tests/ -v`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/device_review.py` | Modify | All logic changes: new helpers, updated check functions, updated CHECKS registry |
| `tests/test_device_review.py` | Create | Unit tests for new helpers and updated check functions |

---

### Task 1: New host-parsing and DNS helpers

**Files:**
- Modify: `app/device_review.py:98-104` (replace `_parse_ip_list`)
- Create: `tests/test_device_review.py`

**Interfaces:**
- Produces:
  - `_parse_host_list(raw: Any) -> list[str]` — replaces `_parse_ip_list`
  - `_resolve_host(host: str) -> set[str]` — returns set of resolved IP strings; empty set on error
  - `_match_host(expected: str, configured: str) -> tuple[bool, str]` — `(matched, annotation)` where annotation is `""` on direct match or `"via DNS: {expected} → {ip}"` on DNS match

- [ ] **Step 1: Write the failing tests**

Create `tests/test_device_review.py`:

```python
"""Unit tests for device_review helpers and check functions."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.device_review import (
    _parse_host_list,
    _resolve_host,
    _match_host,
)


# ── _parse_host_list ──────────────────────────────────────────────────────────

def test_parse_host_list_ips():
    assert _parse_host_list("10.1.1.1, 10.1.1.2") == ["10.1.1.1", "10.1.1.2"]

def test_parse_host_list_fqdns():
    assert _parse_host_list("ntp.corp.com, syslog.corp.com") == ["ntp.corp.com", "syslog.corp.com"]

def test_parse_host_list_mixed():
    assert _parse_host_list("10.1.1.1, ntp.corp.com") == ["10.1.1.1", "ntp.corp.com"]

def test_parse_host_list_list_input():
    assert _parse_host_list(["10.1.1.1", "ntp.corp.com"]) == ["10.1.1.1", "ntp.corp.com"]

def test_parse_host_list_empty():
    assert _parse_host_list("") == []

def test_parse_host_list_spaces():
    assert _parse_host_list("  10.1.1.1  ,  10.1.1.2  ") == ["10.1.1.1", "10.1.1.2"]


# ── _resolve_host ─────────────────────────────────────────────────────────────

def test_resolve_host_ip_passthrough():
    # getaddrinfo returns the IP itself when given an IP
    import socket
    result = _resolve_host("127.0.0.1")
    assert "127.0.0.1" in result

def test_resolve_host_dns_error_returns_empty():
    with patch("socket.getaddrinfo", side_effect=Exception("DNS error")):
        result = _resolve_host("nonexistent.invalid")
    assert result == set()


# ── _match_host ───────────────────────────────────────────────────────────────

def test_match_host_direct_match():
    matched, annotation = _match_host("10.1.1.1", "10.1.1.1")
    assert matched is True
    assert annotation == ""

def test_match_host_direct_fqdn_match():
    matched, annotation = _match_host("ntp.corp.com", "ntp.corp.com")
    assert matched is True
    assert annotation == ""

def test_match_host_dns_match():
    # Both sides resolve to the same IP
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.1.1.1"} if h in ("ntp.corp.com", "10.1.1.1") else set()
        matched, annotation = _match_host("ntp.corp.com", "10.1.1.1")
    assert matched is True
    assert "via DNS" in annotation
    assert "ntp.corp.com" in annotation

def test_match_host_no_match():
    with patch("app.device_review._resolve_host", return_value=set()):
        matched, annotation = _match_host("10.1.1.1", "10.2.2.2")
    assert matched is False
    assert annotation == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: ImportError or AttributeError — `_parse_host_list`, `_resolve_host`, `_match_host` not yet defined.

- [ ] **Step 3: Implement the helpers in `app/device_review.py`**

Replace the existing `_parse_ip_list` function (lines 98–104) and add the two new helpers immediately after it:

```python
import socket  # add to top-of-file imports if not already present


def _parse_host_list(raw: Any) -> list[str]:
    """Normalise a param value into a list of stripped, non-empty host strings.

    Accepts IPs and FQDNs. Splits on commas or whitespace.
    """
    if isinstance(raw, list):
        return [s.strip() for s in raw if str(s).strip()]
    if isinstance(raw, str):
        return [s.strip() for s in raw.replace(",", " ").split() if s.strip()]
    return []


def _resolve_host(host: str) -> set[str]:
    """Return the set of IP addresses that host resolves to.

    Returns empty set on any DNS error.
    """
    try:
        results = socket.getaddrinfo(host, None)
        return {r[4][0] for r in results}
    except Exception:
        return set()


def _match_host(expected: str, configured: str) -> tuple[bool, str]:
    """Compare expected host against configured host.

    Tries direct string match first. On mismatch, resolves both via DNS
    and checks for IP intersection. Returns (matched, annotation) where
    annotation is '' on direct match or 'via DNS: expected → ip' on DNS match.
    """
    if expected == configured:
        return True, ""
    exp_ips = _resolve_host(expected)
    cfg_ips = _resolve_host(configured)
    common = exp_ips & cfg_ips
    if common:
        resolved_ip = next(iter(common))
        return True, f"via DNS: {expected} → {resolved_ip}"
    return False, ""
```

> Note: `_parse_ip_list` is called nowhere outside `device_review.py` itself — it is safe to remove. Delete the old function and replace with `_parse_host_list`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): add _parse_host_list, _resolve_host, _match_host helpers"
```

---

### Task 2: Update `_run_ntp_config`

**Files:**
- Modify: `app/device_review.py:165-222` (`_run_ntp_config`)
- Modify: `tests/test_device_review.py` (add tests)

**Interfaces:**
- Consumes: `_parse_host_list`, `_match_host` (Task 1)
- Produces: updated `_run_ntp_config` that:
  - Returns `ip = ", ".join(configured)` on all rows
  - Produces per-entry detail: `"10.1.1.1 ✓, ntp.corp.com ✓ (via DNS → 10.1.1.2), 10.1.1.3 ✗ (not found)"`
  - Result is PASS only if all expected entries matched; FAIL if any unmatched

- [ ] **Step 1: Add failing tests**

Append to `tests/test_device_review.py`:

```python
from app.device_review import _run_ntp_config


NTP_DEVICE_DATA = {
    "ntp": {
        "ntpsync": "enable",
        "ntpserver": [
            {"server": "10.1.1.1"},
            {"server": "10.1.1.2"},
        ],
    }
}


def test_ntp_pass_direct_ip():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "10.1.1.1, 10.1.1.2"})
    assert len(rows) == 1
    assert rows[0]["result"] == "PASS"
    assert "10.1.1.1 ✓" in rows[0]["detail"]
    assert "10.1.1.2 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_fail_missing_server():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "10.1.1.1, 10.1.1.3"})
    assert rows[0]["result"] == "FAIL"
    assert "10.1.1.1 ✓" in rows[0]["detail"]
    assert "10.1.1.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.1.1.1"} if h in ("ntp.corp.com", "10.1.1.1") else set()
        rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "ntp.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_config_missing_no_params():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_fail_sync_disabled():
    data = {"ntp": {"ntpsync": "disable"}}
    rows = _run_ntp_config("FW-01", data, {"expected_servers": "10.1.1.1"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_device_review.py::test_ntp_pass_direct_ip -v
```
Expected: FAIL — `ip` field is `""`, detail format doesn't match.

- [ ] **Step 3: Rewrite `_run_ntp_config`**

Replace the entire `_run_ntp_config` function in `app/device_review.py`:

```python
def _run_ntp_config(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify NTP is enabled and configured servers match expected hosts (IP or FQDN)."""
    ntp = device_data.get("ntp", {})
    expected = _parse_host_list(params.get("expected_servers", []))

    def _row(result: str, detail: str, ip: str = "") -> dict:
        return {
            "device": device_name,
            "interface": "system",
            "vdom": "",
            "ip": ip,
            "type": "system",
            "status": "",
            "check": "NTP Configuration (CIS)",
            "result": result,
            "detail": detail,
            "protocols": [],
            "has_insecure": False,
            "has_secure": False,
        }

    if not ntp:
        return [_row("FAIL", "NTP configuration could not be retrieved from device")]

    sync_enabled = str(ntp.get("ntpsync", "disable")).lower() == "enable"
    if not sync_enabled:
        return [_row("FAIL", "NTP sync is disabled (ntpsync=disable)")]

    raw_servers = ntp.get("ntpserver", [])
    if isinstance(raw_servers, dict):
        raw_servers = list(raw_servers.values())
    configured = [
        str(s.get("server", "")).strip()
        for s in raw_servers
        if isinstance(s, dict) and s.get("server")
    ]
    ip_str = ", ".join(configured)

    if not expected:
        detail = "NTP sync enabled. Configured: " + (", ".join(configured) if configured else "(none)")
        return [_row("CONFIG_MISSING", detail, ip_str)]

    parts = []
    any_fail = False
    for exp in expected:
        matched = False
        annotation = ""
        for conf in configured:
            ok, ann = _match_host(exp, conf)
            if ok:
                matched = True
                annotation = ann
                break
        if matched:
            entry = f"{exp} ✓" + (f" ({annotation})" if annotation else "")
        else:
            entry = f"{exp} ✗ (not found)"
            any_fail = True
        parts.append(entry)

    detail = ", ".join(parts)
    result = "FAIL" if any_fail else "PASS"
    return [_row(result, detail, ip_str)]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): update ntp_config check for FQDN/DNS and ip field"
```

---

### Task 3: Update `_run_syslog_config`

**Files:**
- Modify: `app/device_review.py:228-279` (`_run_syslog_config`)
- Modify: `tests/test_device_review.py` (add tests)

**Interfaces:**
- Consumes: `_parse_host_list`, `_match_host` (Task 1)
- Produces: updated `_run_syslog_config` — same pattern as NTP: per-entry detail, `ip = ", ".join(configured)`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_device_review.py`:

```python
from app.device_review import _run_syslog_config


SYSLOG_DEVICE_DATA = {
    "syslog": [
        {"server": "10.2.2.1"},
        {"server": "10.2.2.2"},
    ]
}


def test_syslog_pass_direct():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "10.2.2.1, 10.2.2.2"})
    assert rows[0]["result"] == "PASS"
    assert "10.2.2.1 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_fail_missing():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "10.2.2.1, 10.2.2.3"})
    assert rows[0]["result"] == "FAIL"
    assert "10.2.2.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.2.2.1"} if h in ("syslog.corp.com", "10.2.2.1") else set()
        rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "syslog.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_config_missing_no_params():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_device_review.py::test_syslog_pass_direct -v
```
Expected: FAIL.

- [ ] **Step 3: Rewrite `_run_syslog_config`**

Replace the entire `_run_syslog_config` function:

```python
def _run_syslog_config(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify syslog is enabled and sending to expected hosts (IP or FQDN)."""
    servers = device_data.get("syslog", [])
    expected = _parse_host_list(params.get("expected_servers", []))

    def _row(result: str, detail: str, ip: str = "") -> dict:
        return {
            "device": device_name,
            "interface": "system",
            "vdom": "",
            "ip": ip,
            "type": "system",
            "status": "",
            "check": "Syslog Configuration (CIS)",
            "result": result,
            "detail": detail,
            "protocols": [],
            "has_insecure": False,
            "has_secure": False,
        }

    configured = [
        str(s.get("server", "")).strip()
        for s in servers
        if isinstance(s, dict) and s.get("server")
    ]
    ip_str = ", ".join(configured)

    if not configured:
        if not expected:
            return [_row("CONFIG_MISSING", "No remote syslog servers enabled on device")]
        return [_row("FAIL", "No remote syslog servers enabled on device")]

    if not expected:
        return [_row("CONFIG_MISSING", "Syslog enabled. Configured: " + ip_str, ip_str)]

    parts = []
    any_fail = False
    for exp in expected:
        matched = False
        annotation = ""
        for conf in configured:
            ok, ann = _match_host(exp, conf)
            if ok:
                matched = True
                annotation = ann
                break
        if matched:
            entry = f"{exp} ✓" + (f" ({annotation})" if annotation else "")
        else:
            entry = f"{exp} ✗ (not found)"
            any_fail = True
        parts.append(entry)

    detail = ", ".join(parts)
    result = "FAIL" if any_fail else "PASS"
    return [_row(result, detail, ip_str)]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): update syslog_config check for FQDN/DNS and ip field"
```

---

### Task 4: Update `_run_log_faz`

**Files:**
- Modify: `app/device_review.py:716-761` (`_run_log_faz`)
- Modify: `tests/test_device_review.py` (add tests)

**Interfaces:**
- Consumes: `_parse_host_list`, `_match_host` (Task 1)
- Produces: updated `_run_log_faz`:
  - `ip = cfg.get("server", "")` on all rows
  - Iterates all expected entries against the single configured server
  - PASS if any expected entry matches the configured server; FAIL if none match

- [ ] **Step 1: Add failing tests**

Append to `tests/test_device_review.py`:

```python
from app.device_review import _run_log_faz


FAZ_DEVICE_DATA_ENABLED = {
    "log_faz": {"status": "enable", "server": "10.3.3.10"}
}
FAZ_DEVICE_DATA_DISABLED = {
    "log_faz": {"status": "disable", "server": ""}
}


def test_faz_pass_direct():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "10.3.3.10"})
    assert rows[0]["result"] == "PASS"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_fail_wrong_server():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "10.3.3.99"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.3.3.10"} if h in ("faz.corp.com", "10.3.3.10") else set()
        rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "faz.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_config_missing_no_params():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_fail_disabled():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_DISABLED, {"expected_servers": "10.3.3.10"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_device_review.py::test_faz_pass_direct -v
```
Expected: FAIL.

- [ ] **Step 3: Rewrite `_run_log_faz`**

Replace the entire `_run_log_faz` function:

```python
def _run_log_faz(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify FortiAnalyzer logging is enabled and server matches expected host (IP or FQDN)."""
    cfg = device_data.get("log_faz", {})
    if not cfg:
        return [_cis_row(device_name, _CHECK_LOG_FAZ, "FAIL", "log.fortianalyzer/setting could not be retrieved")]

    status = str(cfg.get("status", "disable")).lower()
    server = str(cfg.get("server", "")).strip()
    expected = _parse_host_list(params.get("expected_servers", []))

    if status != "enable":
        return [
            {
                **_cis_row(device_name, _CHECK_LOG_FAZ, "FAIL", "FortiAnalyzer logging is disabled"),
                "ip": "",
            }
        ]

    if not expected:
        detail = f"FortiAnalyzer logging enabled. Configured server: {server or '(none)'}"
        return [
            {
                **_cis_row(device_name, _CHECK_LOG_FAZ, "CONFIG_MISSING", detail),
                "ip": server,
            }
        ]

    parts = []
    any_match = False
    for exp in expected:
        ok, ann = _match_host(exp, server)
        if ok:
            any_match = True
            entry = f"{exp} ✓" + (f" ({ann})" if ann else "")
        else:
            entry = f"{exp} ✗ (not found)"
        parts.append(entry)

    detail = ", ".join(parts)
    result = "PASS" if any_match else "FAIL"
    return [
        {
            **_cis_row(device_name, _CHECK_LOG_FAZ, result, detail),
            "ip": server,
        }
    ]
```

> Note: `_cis_row` sets `ip: ""` — we override it by spreading and setting `ip` explicitly.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): update log_faz check for FQDN/DNS and ip field"
```

---

### Task 5: Update `_run_dns`

**Files:**
- Modify: `app/device_review.py:769-806` (`_run_dns`)
- Modify: `tests/test_device_review.py` (add tests)

**Interfaces:**
- Consumes: `_parse_host_list`, `_match_host` (Task 1)
- Produces: updated `_run_dns` — per-entry detail, `ip = ", ".join(configured)`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_device_review.py`:

```python
from app.device_review import _run_dns


DNS_DEVICE_DATA = {
    "dns": {"primary": "10.4.4.1", "secondary": "10.4.4.2"}
}


def test_dns_pass_direct():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "10.4.4.1, 10.4.4.2"})
    assert rows[0]["result"] == "PASS"
    assert "10.4.4.1 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_fail_missing():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "10.4.4.1, 10.4.4.9"})
    assert rows[0]["result"] == "FAIL"
    assert "10.4.4.9 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.4.4.1"} if h in ("dns.corp.com", "10.4.4.1") else set()
        rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "dns.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_config_missing_no_params():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_device_review.py::test_dns_pass_direct -v
```
Expected: FAIL.

- [ ] **Step 3: Rewrite `_run_dns`**

Replace the entire `_run_dns` function:

```python
def _run_dns(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify expected DNS servers (IP or FQDN) are configured on the device."""
    cfg = device_data.get("dns", {})
    if not cfg:
        return [_cis_row(device_name, _CHECK_DNS, "FAIL", "system/dns could not be retrieved")]

    primary = str(cfg.get("primary", "")).strip()
    secondary = str(cfg.get("secondary", "")).strip()
    configured = [s for s in [primary, secondary] if s and s != "0.0.0.0"]
    ip_str = ", ".join(configured)
    expected = _parse_host_list(params.get("expected_servers", []))

    if not expected:
        detail = "DNS configured: " + (ip_str if ip_str else "(none)")
        return [
            {
                **_cis_row(device_name, _CHECK_DNS, "CONFIG_MISSING", detail),
                "ip": ip_str,
            }
        ]

    parts = []
    any_fail = False
    for exp in expected:
        matched = False
        annotation = ""
        for conf in configured:
            ok, ann = _match_host(exp, conf)
            if ok:
                matched = True
                annotation = ann
                break
        if matched:
            entry = f"{exp} ✓" + (f" ({annotation})" if annotation else "")
        else:
            entry = f"{exp} ✗ (not found)"
            any_fail = True
        parts.append(entry)

    detail = ", ".join(parts)
    result = "FAIL" if any_fail else "PASS"
    return [
        {
            **_cis_row(device_name, _CHECK_DNS, result, detail),
            "ip": ip_str,
        }
    ]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_device_review.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): update dns_servers check for FQDN/DNS and ip field"
```

---

### Task 6: Update CHECKS registry labels/placeholders & full regression

**Files:**
- Modify: `app/device_review.py` — `CHECKS` list entries for `log_faz`, `ntp_config`, `syslog_config`, `dns_servers`

**Interfaces:**
- No new code interfaces — cosmetic changes to the `CHECKS` data structure consumed by the frontend params panel

- [ ] **Step 1: Update placeholders and label in the CHECKS registry**

In `app/device_review.py`, find the `CHECKS` list and make these four edits:

For `ntp_config` params_schema entry:
```python
"placeholder": "e.g. 10.1.1.1, ntp.corp.com",
```

For `syslog_config` params_schema entry:
```python
"placeholder": "e.g. 10.2.2.1, syslog.corp.com",
```

For `log_faz` params_schema entry:
```python
"label": "Expected FortiAnalyzer Servers",
"placeholder": "e.g. 10.2.2.10, faz.corp.com",
```

For `dns_servers` params_schema entry:
```python
"placeholder": "e.g. 10.3.3.1, dns.corp.com",
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all tests PASS, including pre-existing tests.

- [ ] **Step 3: Commit**

```bash
git add app/device_review.py
git commit -m "feat(device-review): update CHECKS registry labels and placeholders for FQDN support"
```

---

## Self-Review Notes

- All four spec requirements covered: FQDN input ✓, per-entry detail ✓, DNS auto-resolution ✓, IP column populated ✓.
- `_parse_ip_list` removed and replaced everywhere — no orphan references.
- `_cis_row` returns `ip: ""` by default; `_run_log_faz` and `_run_dns` override with spread pattern `{**_cis_row(...), "ip": value}` — consistent with how `_run_ntp_config` and `_run_syslog_config` use their own local `_row` helpers that accept `ip` directly.
- FAZ semantics clarified: PASS if *any* expected entry matches the single configured server (not all must match — you supply alternates).
- DNS timeout risk noted in spec — acceptable for now, no change needed.
