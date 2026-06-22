# CIS Hardening Checks — Future Implementation List

The NTP and Syslog checks (already implemented) established the pattern.
Each new check needs:
1. A proxy method in `fmg_client.py` if new device data is required
2. A `_run_<name>` function in `device_review.py`
3. One new entry in the `CHECKS` list (with `data_keys`, `params_schema`, `run`)

Binary checks (no user input) are the simplest — `params_schema: []` and no
new client method if the data_key is already fetched for another check.

---

## Admin Account Hardening

### 1. Trusted hosts on admin accounts
- **Type:** Binary
- **CIS Level:** 1
- **What to check:** Query `GET /api/v2/cmdb/system/admin?vdom=root` — flag any
  admin account whose `trusthost1`–`trusthost10` are all `0.0.0.0/0` or
  `0.0.0.0 0.0.0.0` (unrestricted management access from any IP).
- **Result:** FAIL if any admin has no trusted-host restriction; PASS otherwise.
- **data_keys:** `["admins"]`
- **New client method:** `get_device_admins(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/system/admin?vdom=root")`

### 2. Default `admin` account renamed or disabled
- **Type:** Binary
- **CIS Level:** 1
- **What to check:** Same admin list — flag if an account named exactly `admin`
  exists and is not disabled (`status != "disable"`).
- **Result:** FAIL if the built-in `admin` account is still active; PASS otherwise.
- **data_keys:** `["admins"]`  (reuses same fetch as check #1)
- **New client method:** none (shares `admins` data_key)

### 3. Admin idle timeout
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/system/global?vdom=root` — compare
  `admintimeout` (minutes) against the user-supplied maximum (e.g. 10).
- **Result:** FAIL if configured value exceeds expected max; PASS otherwise.
- **data_keys:** `["system_global"]`
- **params_schema:** `[{key: "max_timeout_minutes", label: "Max idle timeout (minutes)", type: "number", placeholder: "e.g. 10"}]`
- **New client method:** `get_device_system_global(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/system/global?vdom=root")`

### 4. Admin lockout threshold
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** Same `system/global` — compare `admin-lockout-threshold`
  against the user-supplied maximum (e.g. 5 failed attempts).
- **Result:** FAIL if threshold exceeds expected max; PASS otherwise.
- **data_keys:** `["system_global"]`  (reuses same fetch as check #3)
- **params_schema:** `[{key: "max_attempts", label: "Max failed login attempts", type: "number", placeholder: "e.g. 5"}]`
- **New client method:** none (shares `system_global` data_key)

### 5. Password minimum length
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/system/password-policy` — compare
  `minimum-length` against the user-supplied minimum (e.g. 12).
- **Result:** FAIL if configured minimum is less than expected; PASS otherwise.
- **data_keys:** `["password_policy"]`
- **params_schema:** `[{key: "min_length", label: "Min password length", type: "number", placeholder: "e.g. 12"}]`
- **New client method:** `get_device_password_policy(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/system/password-policy?vdom=root")`

---

## Logging

### 6. Local disk logging enabled
- **Type:** Binary
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/log.disk/setting?vdom=root` — verify
  `status == "enable"`.
- **Result:** FAIL if disk logging is disabled; PASS otherwise.
- **data_keys:** `["log_disk"]`
- **New client method:** `get_device_log_disk(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/log.disk/setting?vdom=root")`

### 7. Log severity level
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** Same `log.disk/setting` — compare `severity` against the
  user-supplied expected level. FortiOS severity order (lowest → highest):
  emergency, alert, critical, error, warning, notification, information, debug.
  Flag if configured severity is coarser (higher) than expected.
- **Result:** FAIL if severity threshold is too high (missing low-level events);
  PASS if equal or finer.
- **data_keys:** `["log_disk"]`  (reuses same fetch as check #6)
- **params_schema:** `[{key: "max_severity", label: "Maximum severity threshold", type: "text", placeholder: "e.g. information"}]`
- **New client method:** none (shares `log_disk` data_key)

### 8. FortiAnalyzer logging configured
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/log.fortianalyzer/setting?vdom=root` —
  verify `status == "enable"` and configured `server` matches expected FAZ IP.
- **Result:** FAIL if disabled or wrong IP; CONFIG_MISSING if no expected IP
  supplied but FAZ is configured; PASS if correct.
- **data_keys:** `["log_faz"]`
- **params_schema:** `[{key: "expected_servers", label: "Expected FortiAnalyzer IPs", type: "ip_list", placeholder: "e.g. 10.2.2.10"}]`
- **New client method:** `get_device_log_faz(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/log.fortianalyzer/setting?vdom=root")`

---

## Network Services

### 9. DNS servers configured
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/system/dns?vdom=root` — compare
  `primary` and `secondary` against expected IP list.
- **Result:** FAIL if any expected DNS IP is missing; CONFIG_MISSING if no
  expected IPs supplied; PASS if all present.
- **data_keys:** `["dns"]`
- **params_schema:** `[{key: "expected_servers", label: "Expected DNS Servers", type: "ip_list", placeholder: "e.g. 10.3.3.1, 10.3.3.2"}]`
- **New client method:** `get_device_dns(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/system/dns?vdom=root")`

### 10. SNMP version enforcement
- **Type:** Binary
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/system/snmp/community` — flag if any
  SNMPv1 or SNMPv2c communities exist with `status == "enable"`.
  Also check `GET /api/v2/cmdb/system/snmp/sysinfo` to see if SNMP is enabled
  at all — if disabled entirely, result is PASS.
- **Result:** FAIL if v1/v2c communities are active; PASS if SNMP is off or
  only SNMPv3 is configured.
- **data_keys:** `["snmp_community", "snmp_sysinfo"]`
- **New client methods:**
  - `get_device_snmp_community(adom, device)` → `/api/v2/cmdb/system/snmp/community`
  - `get_device_snmp_sysinfo(adom, device)` → `/api/v2/cmdb/system/snmp/sysinfo`

### 11. SNMP read-only
- **Type:** Binary
- **CIS Level:** 2
- **What to check:** Same SNMPv3 user list (`/api/v2/cmdb/system/snmp/user`) —
  flag if any user has `write-access == "enable"`.
- **Result:** FAIL if any SNMP write access found; PASS otherwise.
- **data_keys:** `["snmp_users"]`
- **New client method:** `get_device_snmp_users(adom, device)`
  → `_proxy(adom, device, "/api/v2/cmdb/system/snmp/user?vdom=root")`

---

## Protocol Security

### 12. Minimum TLS version
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** `GET /api/v2/cmdb/system/global` — check
  `admin-https-ssl-versions` (or `ssl-min-proto-version` depending on FortiOS
  version). Flag if TLS 1.0 or 1.1 are allowed.
- **Result:** FAIL if weak TLS versions are permitted; PASS if TLS 1.2+ only.
- **data_keys:** `["system_global"]`  (reuses same fetch as checks #3, #4)
- **params_schema:** `[{key: "min_tls", label: "Minimum TLS version", type: "text", placeholder: "e.g. tlsv1-2"}]`
- **New client method:** none (shares `system_global` data_key)

### 13. SSH strong ciphers
- **Type:** Binary
- **CIS Level:** 2
- **What to check:** `GET /api/v2/cmdb/system/global` — inspect
  `ssh-enc-algo` and `ssh-mac-algo`. Flag if CBC-mode or MD5 ciphers are
  present in the allowed list.
- **Result:** FAIL if weak ciphers present; PASS otherwise.
- **data_keys:** `["system_global"]`  (reuses fetch)
- **New client method:** none

---

## Fortinet-Specific

### 14. Firmware version compliance
- **Type:** Parameterised
- **CIS Level:** 1
- **What to check:** Use device metadata already returned by `get_devices()`
  (os_ver, mr, patch fields) — compare against user-supplied minimum version.
  No extra proxy call needed; version is in the device list response.
- **Result:** FAIL if running firmware older than expected minimum; PASS otherwise.
- **data_keys:** `["device_meta"]`  (populated from the devices list, no proxy needed)
- **params_schema:** `[{key: "min_version", label: "Minimum firmware version", type: "text", placeholder: "e.g. 7.4.3"}]`
- **New client method:** none (version already in device record from `get_devices()`)

### 15. HA sync status
- **Type:** Binary
- **CIS Level:** 2
- **What to check:** `GET /api/v2/monitor/system/ha-status?vdom=root` — if HA
  is configured (`mode != "standalone"`), verify all members show
  `sync_status == "synchronized"`.
- **Result:** FAIL if HA is configured but members are out of sync; PASS if
  standalone or all members synchronized; INFO if HA not configured.
- **data_keys:** `["ha_status"]`
- **New client method:** `get_device_ha_status(adom, device)`
  → `_proxy(adom, device, "/api/v2/monitor/system/ha-status?vdom=root")`

---

## Implementation notes

- Checks #3, #4, #12, #13 all share `data_keys: ["system_global"]` — once that
  fetch is implemented, all four checks come for free per device.
- Check #14 (firmware) does not need a proxy call at all — the version is
  already in the device record from `get_devices()`. The route just needs to
  pass `device_meta` through `device_data` when that check is selected.
- Add checks in priority order: admin hardening (1–5) first, then logging
  (6–8), then network services (9–11), then protocol security (12–13), then
  Fortinet-specific (14–15).
