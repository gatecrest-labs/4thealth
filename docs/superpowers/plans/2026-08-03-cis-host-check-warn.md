# CIS Host Check WARN for Misconfigured Servers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the four CIS host-comparison checks (NTP, Syslog, FortiAnalyzer, DNS) so that "service active but wrong servers configured" produces WARN instead of FAIL — FAIL is reserved for when the service is completely absent or disabled.

**Architecture:** All four check functions live in `app/device_review.py`. Each has a single result-assignment line at the end of its host-matching loop that is changed from a binary FAIL/PASS to a three-way FAIL/WARN/PASS based on whether the service is active. The `_match_host()` DNS-resolution helper is unchanged. Four existing tests that assert FAIL for "wrong server" cases are updated to assert WARN; new tests cover the edge cases introduced by the third branch.

**Tech Stack:** Python 3.11+, pytest. No new dependencies.

## Global Constraints

- Python 3.11+ — `bool | None` union syntax, no `Optional`
- No new packages
- Tests live in `tests/test_device_review.py`; run with `pytest tests/ -v`
- Test style: no classes, flat functions, `unittest.mock.patch` for external calls
- All four checks: "feature disabled / no servers" → FAIL (unchanged); "configured but wrong" → WARN (new); "matches expected" → PASS (unchanged); "no expected param" → CONFIG_MISSING (unchanged)
- `_match_host()` logic is unchanged — FQDN→IP DNS resolution still works for all result tiers
- Commit after every task

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `app/device_review.py` | Modify lines 330, 394, 905, 963 | Result assignment in each of the 4 check functions |
| `tests/test_device_review.py` | Modify + extend | Update 4 existing FAIL assertions to WARN; add new edge-case tests |
| `CLAUDE.md` | Modify | Update WARN result description |
| `docs/features.md` | Modify | Update Device Review section |
| `CHANGELOG.md` | Modify | Add changelog entry |

---

## Task 1: Update NTP and Syslog result logic + tests

**Files:**
- Modify: `app/device_review.py:330` (`_run_ntp_config` result line)
- Modify: `app/device_review.py:394` (`_run_syslog_config` result line)
- Test: `tests/test_device_review.py`

**Interfaces:**
- Produces: `_run_ntp_config` — returns WARN when `any_fail` is True but `configured` is non-empty
- Produces: `_run_syslog_config` — returns WARN when `any_fail` is True (configured is already guaranteed non-empty at that point)

- [ ] **Step 1: Update existing NTP test that will break**

In `tests/test_device_review.py`, find `test_ntp_fail_missing_server` (around line 122). The fixture (`NTP_DEVICE_DATA`) has servers `10.1.1.1` and `10.1.1.2` configured, so a missing expected server now produces WARN, not FAIL. Update the assertion and rename the test:

```python
def test_ntp_warn_wrong_server():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "10.1.1.1, 10.1.1.3"})
    assert rows[0]["result"] == "WARN"
    assert "10.1.1.1 ✓" in rows[0]["detail"]
    assert "10.1.1.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"
```

- [ ] **Step 2: Add new NTP WARN via DNS test**

```python
def test_ntp_warn_fqdn_not_found():
    """FQDN expected but doesn't resolve to any configured server → WARN (servers exist)."""
    with patch("app.device_review._resolve_host", return_value=frozenset()):
        rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "ntp.corp.com"})
    assert rows[0]["result"] == "WARN"
    assert "ntp.corp.com ✗" in rows[0]["detail"]
```

- [ ] **Step 3: Add NTP FAIL edge case — sync enabled but no servers configured**

```python
def test_ntp_fail_sync_enabled_no_servers():
    """NTP sync enabled but no servers in config → FAIL (nothing configured to compare)."""
    data = {"ntp": {"ntpsync": "enable", "ntpserver": []}}
    rows = _run_ntp_config("FW-01", data, {"expected_servers": "10.1.1.1"})
    assert rows[0]["result"] == "FAIL"
    assert "10.1.1.1 ✗" in rows[0]["detail"]
```

- [ ] **Step 4: Update existing Syslog test that will break**

Find `test_syslog_fail_missing` (around line 170). The fixture has servers `10.2.2.1` and `10.2.2.2` configured. Update:

```python
def test_syslog_warn_wrong_server():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "10.2.2.1, 10.2.2.3"})
    assert rows[0]["result"] == "WARN"
    assert "10.2.2.1 ✓" in rows[0]["detail"]
    assert "10.2.2.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"
```

- [ ] **Step 5: Run tests to confirm these new tests fail**

```bash
pytest tests/test_device_review.py::test_ntp_warn_wrong_server tests/test_device_review.py::test_syslog_warn_wrong_server -v
```

Expected: FAIL — both return `"FAIL"` not `"WARN"` yet.

- [ ] **Step 6: Fix NTP result logic**

In `app/device_review.py`, find line 330:

```python
    result = "FAIL" if any_fail else "PASS"
```

Replace with:

```python
    if any_fail:
        result = "WARN" if configured else "FAIL"
    else:
        result = "PASS"
```

`configured` is the list built at lines 298–302 (`[str(s.get("server", "")).strip() for s in raw_servers ...]`). If NTP sync is enabled but the server list is empty, `configured` is `[]` (falsy) → FAIL.

- [ ] **Step 7: Fix Syslog result logic**

In `app/device_review.py`, find line 394:

```python
    result = "FAIL" if any_fail else "PASS"
```

Replace with:

```python
    result = "WARN" if any_fail else "PASS"
```

Note: `configured` is guaranteed non-empty here — the `if not configured:` guard at line 365 returns FAIL before reaching this point, so no extra check is needed.

- [ ] **Step 8: Run all NTP and Syslog tests**

```bash
pytest tests/test_device_review.py -v -k "ntp or syslog"
```

Expected: all pass (including the pre-existing PASS, CONFIG_MISSING, and sync-disabled FAIL tests).

- [ ] **Step 9: Run full suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): NTP and Syslog return WARN when servers configured but wrong"
```

---

## Task 2: Update FortiAnalyzer and DNS result logic + tests

**Files:**
- Modify: `app/device_review.py:905` (`_run_log_faz` result line)
- Modify: `app/device_review.py:963` (`_run_dns` result line)
- Test: `tests/test_device_review.py`

**Interfaces:**
- Produces: `_run_log_faz` — returns WARN when `any_match` is False but `enabled_servers` is non-empty
- Produces: `_run_dns` — returns WARN when `any_fail` is True but `configured` is non-empty

- [ ] **Step 1: Update existing FAZ test that will break**

Find `test_faz_fail_wrong_server` (around line 215). The fixture has server `10.3.3.10` enabled. Update:

```python
def test_faz_warn_wrong_server():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "10.3.3.99"})
    assert rows[0]["result"] == "WARN"
    assert "10.3.3.99 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.3.3.10"
```

- [ ] **Step 2: Add FAZ FAIL edge case — enabled but no server addresses**

```python
def test_faz_fail_enabled_no_server_addresses():
    """FAZ logging enabled but slot has no server address → FAIL (nothing to compare)."""
    data = {"log_faz": [{"status": "enable", "server": ""}]}
    rows = _run_log_faz("FW-01", data, {"expected_servers": "10.3.3.10"})
    assert rows[0]["result"] == "FAIL"
    assert "10.3.3.10 ✗" in rows[0]["detail"]
```

- [ ] **Step 3: Add FAZ WARN via DNS test**

```python
def test_faz_warn_fqdn_not_found():
    """FAZ enabled with server, FQDN expected but doesn't resolve → WARN."""
    with patch("app.device_review._resolve_host", return_value=frozenset()):
        rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "faz.corp.com"})
    assert rows[0]["result"] == "WARN"
    assert "faz.corp.com ✗" in rows[0]["detail"]
```

- [ ] **Step 4: Update existing DNS test that will break**

Find `test_dns_fail_missing` (around line 274). The fixture has primary `10.4.4.1` and secondary `10.4.4.2`. Update:

```python
def test_dns_warn_wrong_server():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "10.4.4.1, 10.4.4.9"})
    assert rows[0]["result"] == "WARN"
    assert "10.4.4.1 ✓" in rows[0]["detail"]
    assert "10.4.4.9 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"
```

- [ ] **Step 5: Add DNS FAIL edge case — data retrieved but both addresses are 0.0.0.0**

```python
def test_dns_fail_no_configured_addresses():
    """DNS data retrieved but both addresses are 0.0.0.0 (unconfigured) → FAIL."""
    data = {"dns": {"primary": "0.0.0.0", "secondary": "0.0.0.0"}}
    rows = _run_dns("FW-01", data, {"expected_servers": "10.4.4.1"})
    assert rows[0]["result"] == "FAIL"
    assert "10.4.4.1 ✗" in rows[0]["detail"]
```

- [ ] **Step 6: Run tests to confirm new tests fail**

```bash
pytest tests/test_device_review.py::test_faz_warn_wrong_server tests/test_device_review.py::test_dns_warn_wrong_server -v
```

Expected: FAIL — both still return `"FAIL"` not `"WARN"`.

- [ ] **Step 7: Fix FortiAnalyzer result logic**

In `app/device_review.py`, find line 905:

```python
    result = "PASS" if any_match else "FAIL"
```

Replace with:

```python
    if any_match:
        result = "PASS"
    elif enabled_servers:
        result = "WARN"
    else:
        result = "FAIL"
```

`enabled_servers` is built at lines 849–857 — it contains only the server addresses of slots with `status == "enable"` that also have a non-empty `server` field. Empty string server values are excluded, so if all enabled slots have blank server fields, `enabled_servers` is `[]` → FAIL.

- [ ] **Step 8: Fix DNS result logic**

In `app/device_review.py`, find line 963:

```python
    result = "FAIL" if any_fail else "PASS"
```

Replace with:

```python
    if any_fail:
        result = "WARN" if configured else "FAIL"
    else:
        result = "PASS"
```

`configured` is built at line 931 (`[s for s in [primary, secondary] if s and s != "0.0.0.0"]`). If both DNS addresses are `0.0.0.0` or absent, `configured` is `[]` → FAIL.

- [ ] **Step 9: Run all FAZ and DNS tests**

```bash
pytest tests/test_device_review.py -v -k "faz or dns"
```

Expected: all pass.

- [ ] **Step 10: Run full suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add app/device_review.py tests/test_device_review.py
git commit -m "feat(device-review): FortiAnalyzer and DNS return WARN when servers configured but wrong"
```

---

## Task 3: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/features.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update WARN description in `CLAUDE.md`**

Find the result values table in the Device Review tab section. The current WARN entry reads:

```
- `WARN` — yellow: effectively unused for Interface Protocols — unknown protocols classify as None (informational), so this result is unreachable in practice; may appear for non-interface CIS checks
```

Replace with:

```
- `WARN` — yellow: CIS host check — service is active but configured servers do not match expected (NTP, Syslog, FortiAnalyzer, DNS); effectively unreachable for Interface Protocols (unknown protocols default to informational)
```

- [ ] **Step 2: Update Device Review section in `docs/features.md`**

Find the Device Review section. Locate the result values list and update the WARN entry to match the CLAUDE.md change above. Then find the text describing the Interface Protocols WARN behavior and update it to clarify WARN is now also used by the four CIS host checks.

Add a sentence (or update an existing one) near the parameterised checks description:

```
CIS host checks (NTP, Syslog, FortiAnalyzer, DNS) return **WARN** when the service is active but the configured servers do not exactly match the expected addresses. **FAIL** is reserved for when the service is completely disabled or unconfigured. IP addresses and FQDNs are both matched via DNS resolution.
```

- [ ] **Step 3: Update `CHANGELOG.md`**

Read the file first to match the existing format. Add a new entry under `[Unreleased]` → `### Changed`:

```markdown
- **Device Review — CIS Host Checks (NTP, Syslog, FortiAnalyzer, DNS):** Checks that compare expected server addresses now return `WARN` (amber) when the service is active but servers do not match, instead of `FAIL`. `FAIL` is reserved for when the service is disabled or completely unconfigured. IP addresses and FQDNs are both handled via DNS resolution.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/features.md CHANGELOG.md
git commit -m "docs: document WARN result for CIS host checks with misconfigured servers"
```
