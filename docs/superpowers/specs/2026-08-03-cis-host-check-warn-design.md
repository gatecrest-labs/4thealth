# Design: CIS Host Check WARN for Misconfigured Servers

**Date:** 2026-08-03
**Status:** Approved

## Summary

The four CIS checks that verify expected host addresses (NTP, Syslog, FortiAnalyzer, DNS) currently produce FAIL when the expected servers are not found — regardless of whether the service is completely unconfigured or is running but pointing to the wrong servers. This change introduces a third outcome: **WARN** when the service is active but the configured servers do not match the expected ones.

---

## Problem

Today's two-tier result for host checks (when expected params are supplied):

| Condition | Current result |
|---|---|
| Service disabled / no servers configured | FAIL |
| Service active, expected server not found | FAIL |
| Service active, all expected servers found | PASS |

"Service is running but wrong NTP servers" and "NTP is completely disabled" both produce FAIL, which overstates severity for partial misconfigurations.

---

## New Three-Tier Logic

The same rule applies to all four checks:

| Condition | New result |
|---|---|
| No expected param supplied | CONFIG_MISSING (unchanged) |
| Service disabled / no servers configured (feature absent) | **FAIL** (unchanged) |
| Service active, all expected servers found (IP or FQDN match) | **PASS** (unchanged) |
| Service active, but expected servers not found | **WARN** (new) |

The per-server detail string (e.g. `10.1.1.1 ✓, 10.1.1.2 ✗ (not found)`) is identical for both WARN and the old FAIL — the operator still sees exactly which servers are missing. The `_match_host()` DNS-resolution fallback (FQDN→IP matching) is unchanged.

---

## Per-Check Specifics

### NTP Configuration (`_run_ntp_config`, `app/device_review.py:267`)

"Feature absent" conditions that remain FAIL (unchanged):
- `ntp` data empty → `"NTP configuration could not be retrieved"`
- `ntpsync != "enable"` → `"NTP sync is disabled (ntpsync=disable)"`

New WARN condition (line ~330):
```python
# Before:
result = "FAIL" if any_fail else "PASS"

# After:
if any_fail:
    result = "WARN" if configured else "FAIL"
else:
    result = "PASS"
```
- `configured` is the list of servers currently set on the device (built at lines 295–303)
- If NTP sync is enabled but no servers are in the config at all → `configured` is empty → FAIL
- If NTP sync is enabled and servers exist but don't match expected → WARN

---

### Syslog Configuration (`_run_syslog_config`, `app/device_review.py:337`)

"Feature absent" conditions that remain FAIL (unchanged):
- `configured` is empty (no active syslog servers) and `expected` is provided → `"No remote syslog servers enabled on device"`

New WARN condition (line ~394):
```python
# Before:
result = "FAIL" if any_fail else "PASS"

# After:
result = "WARN" if any_fail else "PASS"
```
- `configured` is already guaranteed non-empty at this point (the `if not configured` guard above fires FAIL first)
- So the "something configured but wrong" condition simply becomes WARN

---

### FortiAnalyzer Logging (`_run_log_faz`, `app/device_review.py:832`)

"Feature absent" conditions that remain FAIL (unchanged):
- `slots` empty → `"log.fortianalyzer/setting could not be retrieved"`
- `any_enabled` is False → `"FortiAnalyzer logging is disabled"`

FAZ uses OR logic (PASS if *any* expected server matches). New WARN condition (line ~905):
```python
# Before:
result = "PASS" if any_match else "FAIL"

# After:
if any_match:
    result = "PASS"
elif enabled_servers:
    result = "WARN"
else:
    result = "FAIL"
```
- `enabled_servers` is the list of server addresses from enabled FAZ slots
- If logging is enabled but no servers have addresses (`enabled_servers` empty) → FAIL (nothing to compare against)
- If logging is enabled with servers but none match expected → WARN

---

### DNS Servers (`_run_dns`, `app/device_review.py:919`)

"Feature absent" conditions that remain FAIL (unchanged):
- `cfg` data empty → `"system/dns could not be retrieved"`

New WARN condition (line ~960–965):
```python
# Before:
result = "FAIL" if any_fail else "PASS"

# After:
if any_fail:
    result = "WARN" if configured else "FAIL"
else:
    result = "PASS"
```
- `configured` is the list of non-zero DNS addresses (primary/secondary minus 0.0.0.0)
- If DNS data was retrieved but both primary and secondary are 0.0.0.0 → `configured` is empty → FAIL
- If DNS addresses exist but don't match expected → WARN

---

## Result Values Table Update

The `WARN` description in `CLAUDE.md` currently reads:

> "yellow: effectively unused for Interface Protocols — unknown protocols classify as None (informational), so this result is unreachable in practice; may appear for non-interface CIS checks"

Update to reflect that WARN is now actively produced by the four host checks:

> "yellow: CIS host check — service is active but configured servers do not match expected (NTP, Syslog, FortiAnalyzer, DNS); effectively unreachable for Interface Protocols"

---

## CLAUDE.md Device Review Tab — Result Values

Update the WARN row in the result values table and add a note under the four affected checks in the implemented checks table.

---

## Documentation Updates

1. **`CLAUDE.md`** — update WARN description in result values table
2. **`docs/features.md`** — update Device Review section to describe WARN for host checks
3. **`CHANGELOG.md`** — add `### Changed` entry

---

## Files Changed

| File | Change |
|---|---|
| `app/device_review.py` | Modify `_run_ntp_config`, `_run_syslog_config`, `_run_log_faz`, `_run_dns` |
| `tests/test_device_review.py` | Add tests for WARN cases in all 4 checks |
| `CLAUDE.md` | Update WARN result value description |
| `docs/features.md` | Update Device Review section |
| `CHANGELOG.md` | Add changelog entry |

---

## Out of Scope

- No changes to scalar/numeric checks (idle timeout, firmware, password length, etc.)
- No changes to `_match_host()` or DNS resolution logic
- No UI changes — WARN already renders in amber in the Device Review tab and scheduled reports
