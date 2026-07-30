# Device Review — FQDN/IP Param Input & DNS Resolution

**Date:** 2026-07-30  
**Branch:** development  
**Status:** Approved

## Problem

Three issues with the Device Review CIS checks that compare server addresses:

1. **FQDN mismatch** — Fortinet devices often store server addresses as FQDNs (e.g., `ntp.corp.com`) rather than IPs. If a user enters an IP in the params panel, the direct string comparison fails even when the IP and FQDN resolve to the same host.
2. **Empty IP column** — CIS checks return `ip: ""`, so the IP Address column shows `—` for all CIS rows. For server-address checks (NTP, Syslog, FAZ, DNS), it would be useful to show what the device actually has configured.
3. **Multi-entry detail** — When multiple expected servers are entered, the result detail does not show per-entry match status, making it hard to tell which specific server failed.

## Scope

Affected checks: `ntp_config`, `syslog_config`, `log_faz`, `dns_servers`.  
All other checks are unaffected.

## Design

### 1. Host list parsing (`app/device_review.py`)

**`_parse_host_list(raw) -> list[str]`** replaces `_parse_ip_list()`.  
Accepts a comma- or space-separated string, or a list. Returns stripped, non-empty strings. Both IPs and FQDNs are valid — no format validation.

All four call sites (`_run_ntp_config`, `_run_syslog_config`, `_run_log_faz`, `_run_dns`) updated to call `_parse_host_list` instead of `_parse_ip_list`.

> Note: `_parse_ip_list` is only used internally in `device_review.py` — renaming is safe.

### 2. DNS resolution helper (`app/device_review.py`)

**`_resolve_host(host: str) -> set[str]`**  
Uses `socket.getaddrinfo(host, None)` (stdlib — no new dependencies). Returns the set of IPv4/IPv6 address strings that `host` resolves to. Returns empty set on any error (NXDOMAIN, timeout, socket error). Only called on mismatch — zero latency overhead on passing devices.

**`_match_host(expected: str, configured: str) -> tuple[bool, str]`**  
Shared comparison helper used by all four affected checks.

1. Direct string match → `(True, "")` immediately — no DNS call.
2. On mismatch, resolve both `expected` and `configured`.
3. If their resolved IP sets intersect → `(True, "via DNS: {expected} → {resolved_ip}")`.
4. Otherwise → `(False, "")`.

### 3. Per-entry detail string

Checks that compare server lists iterate expected entries individually and build a summary string.

Format example:
```
10.1.1.1 ✓, ntp.corp.com ✓ (via DNS → 10.1.1.2), 10.1.1.3 ✗ (not found)
```

- Overall result is `FAIL` if any expected entry has no match.
- Overall result is `PASS` if all entries matched (direct or via DNS).
- `CONFIG_MISSING` behaviour is unchanged — triggered only when no expected servers were supplied at all.
- `_run_log_faz` stores only a single server address on the device. It uses `_match_host` once (expected[0] vs configured server). If multiple entries are supplied by the user, all are checked against that single configured value — a PASS requires at least one match.

### 4. Populated `ip` field for CIS server checks

The `ip` row field is populated from the device's actual configured value for the four affected checks:

| Check | `ip` value |
|---|---|
| `_run_log_faz` | `cfg.get("server", "")` |
| `_run_ntp_config` | `", ".join(configured)` |
| `_run_syslog_config` | `", ".join(configured)` |
| `_run_dns` | `", ".join(configured)` |

All other CIS checks continue returning `ip = ""`.

The frontend already renders `row.ip` in the IP Address column — no frontend changes required for this.

### 5. Frontend label & placeholder updates

**`app/device_review.py` — `CHECKS` registry**  
Update `params_schema` for the four affected checks:

| Check | `label` before | `label` after |
|---|---|---|
| `ntp_config` | `"Expected NTP Servers"` | `"Expected NTP Servers"` *(unchanged)* |
| `syslog_config` | `"Expected Syslog Servers"` | `"Expected Syslog Servers"` *(unchanged)* |
| `log_faz` | `"Expected FortiAnalyzer IPs"` | `"Expected FortiAnalyzer Servers"` |
| `dns_servers` | `"Expected DNS Servers"` | `"Expected DNS Servers"` *(unchanged)* |

Update `placeholder` for all four to show an FQDN example alongside an IP:

```
"e.g. 10.1.1.1, ntp.corp.com"
```

No changes to `device_review.js` input handling — `collectCheckParams()` already splits on commas/spaces and passes raw strings through. FQDNs will flow through naturally.

## Files Changed

| File | Change |
|---|---|
| `app/device_review.py` | Rename `_parse_ip_list` → `_parse_host_list`; add `_resolve_host`, `_match_host`; update four check functions; populate `ip` field; update labels/placeholders in `CHECKS` |
| `app/static/js/device_review.js` | None required |
| `app/templates/device_review.html` | None required |
| `app/routes/device_review_routes.py` | None required |

## Non-Goals

- No new API endpoints.
- No new Python dependencies (`socket` is stdlib).
- No changes to export (CSV/JSON/PDF) — `ip` and `detail` fields already included.
- No changes to any check other than the four listed above.

## DNS Behaviour Notes

- DNS calls use the Flask server's configured resolver — assumed reachable in production.
- `socket.getaddrinfo` has no explicit timeout. If DNS is unreachable, calls may block for several seconds per mismatch. If this becomes a problem in production, a `concurrent.futures.ThreadPoolExecutor` with a timeout wrapper can be added without changing the interface.
- Both forward (FQDN→IP) and reverse (IP→FQDN) lookups are implicitly covered: `_resolve_host("ntp.corp.com")` returns IPs; `_resolve_host("10.1.1.1")` returns IPs (via `getaddrinfo`, which accepts IPs and returns them as-is). The intersection check handles all four combinations: IP vs IP, FQDN vs FQDN, IP vs FQDN, FQDN vs IP.
