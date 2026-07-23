# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions use the date the change merged to `main` (YYYY-MM-DD).

---

## [Unreleased]

---

## [2026-07-23] — Config-Delta rename and bulk ADOM export

### Changed
- DIFF (BETA) tab renamed to **Config-Delta** across the nav bar, page title, heading, and export filenames. Internal tab key (`pending_changes`), URL (`/pending-changes`), and all API paths are unchanged — no permission migration required.

### Added
- **Export All Devices** control on the Config-Delta tab: a format selector (CSV / JSON / PDF) paired with an **Export All** button. Clicking the button sequentially fetches the pending diff for every device in the selected ADOM, shows a live progress indicator (`Fetching N of M — <device>…`), and downloads a single combined file when complete.
  - Devices with no pending changes are included in the export with a `no_changes` status rather than being silently omitted.
  - Devices that error during preview are included with their error message; the run continues to the next device.
  - A **× Cancel** link aborts the run mid-flight with no partial download.
  - The existing per-device export queue is unaffected and works alongside the new bulk export.

---

## [2026-07-17] — DIFF tab performance (Option D)

### Added
- `app/pending_status_cache.py` — background APScheduler job (30-minute interval) that pre-fetches device list + `pkg_status` for every ADOM. The DIFF tab device table now loads from this cache (sub-50 ms) instead of blocking on N parallel FMG API calls (previously 5–15 s on large ADOMs). Falls back to a live FMG fetch on cold start before the first cache cycle completes.
- Async task+poll pattern for per-device diff preview: `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` now returns `{"task_id": "<uuid>"}` immediately instead of blocking. `GET /api/pending-changes/task/<task_id>` returns `{status, step, result, error}`. Task entries are evicted after 10 minutes.
- Step-label spinner in the DIFF panel: the browser polls every 2 s and shows the current step label ("Fetching device info…", "Staging policy package…", "Parsing diff…") so operators can see forward progress during the 15–60 s FMG chain instead of a silent spinner.

### Changed
- `pending_changes_routes.py`: devices endpoint reads from `pending_status_cache`; preview endpoint spawns a daemon thread and returns a task ID; new poll endpoint added.
- `pending_changes.js`: `loadPreview()` replaced with a two-step fetch (POST → task_id, then `setTimeout` poll loop); `showDiffSpinner()` now accepts and displays a step-label argument.

---

## [2026-07-15] — DIFF (Beta) fix for FortiManager 7.6.x

### Fixed
- `get_package_info()` didn't recognize FMG 7.6.x's `"conflict"` package status (previously only `"modified"`/`"installed"` were handled), so a device with a modified-but-conflicted package was treated as unassigned and its package was never staged for preview — the DIFF tab reported "No pending changes found" even when a real diff existed.
- `get_install_preview()` now links the staged package's task ID through to `install/preview` and `preview/result` via `preview_taskid`. FMG 7.6.7 requires this linkage to return diff content; without it, `install/preview` reports `status=OK` but `preview/result` always returns `"=== No preview result ==="` for the device.
- The result lookup tries the previously-working key first (the `install/preview` call's own task ID, confirmed against FMG 7.4.10 in production) and only falls back to the stage task's ID when that returns no diff, so 7.4.x behavior is unchanged.

---

## [2026-07-15] — DIFF (Beta) tab polish

### Changed
- Device table now shows a single compact badge per row (highest-priority state: Out of Sync → Pending → Pkg Pending → In Sync) so rows remain single-line at all viewport widths.
- Diff panel header reorganised: device name + IP + badges on one line; export button and help icon pushed right with `margin-left:auto`.
- CLI legend moved into the `?` tooltip — removes noisy inline text from the diff panel.
- VDOM section headers reduced in visual weight (uppercase muted small-caps) so CLI diff content has more visual prominence.

---

## [2026-07-15] — DIFF (Beta) performance

### Fixed
- `pkg_status` lookups now execute in parallel (10-worker `ThreadPoolExecutor`) so the device-list endpoint no longer times out (HTTP 504) on large ADOMs.

---

## [2026-07-15] — DIFF (Beta) bug fixes

### Fixed
- Staging an already-installed package clears the install-preview result; the route now only stages packages whose status is `modified`.
- `_package/status` field names corrected; multi-VDOM package staging now iterates all VDOMs.
- Install/package step is skipped entirely when no package name can be resolved for the device.
- Package name is passed correctly to `install/package` to resolve "Invalid package oid/name" errors from FMG.
- Devices that are in-sync with FMG are now handled gracefully instead of producing an error; raw FMG error text is surfaced in the UI for out-of-sync or unreachable devices.
- Install preview repaired for FMG 7.4.4+ by chaining trigger + task-poll workflow before reading diff output.

---

## [2026-07-14] — DIFF (Beta) tab — initial release

### Added
- **DIFF (Beta)** tab (`/pending-changes`) — per-device install-pending diff viewer.
  - Two-column layout: ADOM selector + device table on the left, diff panel on the right.
  - Device table shows `conf_status`, `db_status`, and `pkg_status` per device; full-text search and **Pending only** filter.
  - Diff panel renders colour-coded per-VDOM CLI diffs (`+` green additions, `-` red deletions, `~` amber modifications) with category summary tiles.
  - Export queue — stage multiple devices, then export as **CSV**, **JSON**, or **PDF** (each export includes ADOM, device list, timestamp, and username).
  - AbortController cancels in-flight preview requests when the user clicks a different device.
  - XSS-safe rendering via `esc()` helper on all interpolated values.
- `GET /api/pending-changes/adoms` — ADOM list (forti-prefix filtered, ADOM-access filtered).
- `GET /api/pending-changes/adoms/<adom>/devices` — device list with sync-status fields.
- `POST /api/pending-changes/adoms/<adom>/device/<device>/preview` — trigger + return parsed CLI diff.
- `parse_preview_diff()` in `app/fmg_client.py` — chains FMG trigger + task-poll and parses raw CLI text into structured `{type, line}` objects grouped by VDOM.
- `get_devices_with_sync_status()` and `get_install_preview()` added to `FMGClient`.
- `tests/test_pending_changes.py` — unit tests for parser and route behaviour.

---

## [2026-07] — CIS Hardening checks (Device Review)

### Added
- 15 CIS Level 1/2 hardening checks added to the Device Review tab (NTP, Syslog, Trusted Hosts, Default Admin, Idle Timeout, Lockout Threshold, Password Length, Disk Logging, Log Severity, FortiAnalyzer Logging, DNS Servers, SNMP Version, SNMP Read-Only, TLS Version, SSH Ciphers, Firmware Version, HA Sync).
- Parameterised checks display a **Check Parameters** panel before the run — operators enter expected IPs, timeouts, and thresholds without redeploying.
- Result values expanded: `PASS`, `FAIL`, `CONFIG_MISSING`, `INSECURE`, `WARN`, `INFO`.
- `device_data` dict pattern — only data blobs required by selected checks are fetched per device.

### Changed
- Device Review check registry (`CHECKS` list in `app/device_review.py`) generalised to support `data_keys` and `params_schema` — adding a new binary check requires no template or frontend changes.

---

## [2026-07] — Global policy block inlining (Rule Review)

### Added
- Global policy block rules (header and footer sections) are inlined into the Policy Rules viewer alongside local package rules.

### Fixed
- Policy package lookup no longer blocks the SSE `done` event.
- Per-package API calls eliminated from policy package lookup (single bulk call).

---

## [2026-07] — Security hardening

### Fixed
- XSS in `onclick` handlers and CSV quoting in the pending-changes frontend.
- CSRF token injection broken by explicit empty header — resolved.
- Open-redirect protection enforced on login `?next=` parameter.

---

## [2026-06] — SNMPv3 infrastructure polling

### Added
- Background SNMPv3 poller (`app/infra_health_cache.py`) for FortiManager, FortiAnalyzer, and FortiAuthenticator CPU/memory — replaces JSON-RPC polling for those device types.
- Per-device SNMP credential overrides in `infra_targets.json` (`snmp_user`, `snmp_auth_key`, `snmp_priv_key`, `snmp_auth_protocol`, `snmp_priv_protocol`).
- `SNMP_ENABLED`, `SNMP_PORT`, `SNMP_TIMEOUT`, `SNMP_RETRIES`, `SNMP_POLL_INTERVAL` env vars.

---

## [2026-06] — Map (Beta) tab

### Added
- **Map (Beta)** tab (`/map`) — interactive Leaflet map of all managed FortiGate devices, coloured by configurable US geographic region.
- Device markers clustered at low zoom; click a pin for a popup with device details.
- ADOM filter checkboxes — no server round-trip.
- Health status ledger overlay (bottom-right) showing fleet-wide green/yellow/red/offline counts.
- Map → Firewalls deep-link: device popups link to `/firewalls?device=…&adom=…`.
- Admin region editor (`Admin → Map Region Colors`) — add/rename/recolour regions, assign states; writes `map_regions.json`.
- `app/map_cache.py` — background daily refresh of device lat/lon from FortiManager.
- `app/map_regions.py` — region config load/save with state validation.

---

## [2026-05] — ADOM access control

### Added
- Per-group ADOM restriction (`adom_restrict`, `allowed_adoms` in `groups.json`).
- `check_adom_access()` decorator enforces ADOM access on every ADOM-scoped API route.
- ADOM list endpoints silently filter out inaccessible ADOMs for restricted users.
- Background ADOM cache (`app/adom_cache.py`) refreshed every 30 minutes.
- `GET /admin/api/adoms` — returns cached ADOM list for the Admin group editor.

---

## [2026-05] — External API

### Added
- Bearer-token External API (`/external/api/`) for programmatic zone-policy access (e.g. FW-Analyst integration).
- Feature-gated via `Admin → External API → External API enabled`.
- Token management in Admin UI — create, list, revoke; plaintext shown once, SHA-256 hash stored.
- Endpoints: `POST /external/api/zone/query`, `GET /external/api/zone/zones`, `GET /external/api/zone/policies`.
- `app/app_settings.py` — atomic read/write of `app_settings.json` feature flags.
- `app/api_tokens.py` — token CRUD; tokens stored as SHA-256 hashes in `api_tokens.json`.

---

## [2026-04] — RADIUS / AD authentication

### Added
- RADIUS/FortiAuthenticator authentication (`RADIUS_ENABLED=true` in `.env`).
- AD group membership via `Filter-Id` / `Class` RADIUS reply attributes for automatic group assignment.
- Local `users.json` accounts serve as emergency fallback when RADIUS is enabled.
- `docs/authentication.md` — RBAC, AD/LDAP setup, RADIUS setup, migration guide.

---

## [2026-04] — Zone Policy tab

### Added
- **Zone Policy** tab (`/zone-policy`) — self-contained network segmentation policy browser; no FortiManager connection required.
- Sub-tabs: Query Flow, Browse, Validate, Edit Database (admin only).
- `app/zone_db.py` — query engine, schema validation, and atomic CRUD mutations against `policy_db.json`.
- Zone evaluation precedence: block all → block only → allow only → allow all → implicit UNKNOWN.
- Zone hierarchy via `parents[]` and zone name expansion.

---

## [2026-03] — Rule Validation tab

### Added
- **Rule Validation** tab (`/rule-review`) — pre-change flow analysis with per-flow verdicts (PERMITTED / EXPLICITLY_DENIED / MODIFIABLE / NEW_RULE_NEEDED).
- CSV/XLSX flow import with case-insensitive column aliases.
- Path-relevance check using live routing and interface data from FortiManager proxy.
- Zone policy integration — independent segmentation-layer verdict alongside firewall policy verdict.
- FortiOS CLI snippet generation for new/modified rules.

---

## [2026-02] — Device Review tab

### Added
- **Device Review** tab (`/device-review`) — management-interface security audit.
- Interface protocol checks: INSECURE (cleartext HTTP/Telnet enabled), WARN (no secure alternative), INFO (PING).
- Extensible check registry in `app/device_review.py`.
- Per-ADOM device grid with search; export findings as CSV, JSON, or PDF.

---

## [2026-01] — Rule Review tab

### Added
- **Rule Review** tab (`/hygiene`) — two-section layout: Policy Rules viewer and Hygiene Analysis.
- Full-text regex search with field-scope filter; address/service group inline expansion; pagination.
- Hygiene checks: `unnamed`, `unlogged`, `shadow`, `disabled`, `expired`, `unhit`.
- Export findings as CSV, JSON, or PDF with filter-context header block.

---

## [2025] — Initial release

### Added
- Flask web dashboard for FortiManager, FortiAnalyzer, FortiAuthenticator, and managed FortiGate devices.
- Dashboard infrastructure health cards (CPU, memory, disk, HA mode, version) via `infra_targets.json`.
- Firewalls tab — per-ADOM device list with health indicator; Device Detail modal (interfaces, routing, BGP/OSPF, IPsec).
- Device Versions tab — per-ADOM firmware distribution chart; CSV and JSON export.
- Managed Network Summary bar — nightly background job counts total firewalls and policy rules.
- Group-based RBAC with per-tab permissions (`groups.json`).
- Local bcrypt authentication (`users.json`); `manage_users.py` CLI.
- Session-based auth with `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE=Lax`, automatic `SESSION_COOKIE_SECURE` when TLS active.
- HTTPS auto-enabled when `certs/cert.pem` + `certs/key.pem` exist.
- Docker + Docker Compose deployment support.
- Ansible health-check playbook with HTML email reports.
