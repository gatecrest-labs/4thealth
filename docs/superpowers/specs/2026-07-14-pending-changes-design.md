---
name: pending-changes-tab
description: Design spec for the Pending Changes tab — ADOM/device list, FortiManager install preview diff, export queue
metadata:
  type: project
---

# Pending Changes Tab — Design Spec

**Date:** 2026-07-14  
**Branch:** pending-change  
**Tab key:** `pending_changes`  
**Route:** `/pending-changes`

---

## Summary

A new read-only tab that surfaces FortiManager install-pending changes — changes committed in FortiManager that have not yet been pushed/installed to the physical FortiGate devices. Users can view CLI-formatted diffs per device, accumulate multiple devices into an export queue, and download a combined change record in CSV, JSON, or PDF format.

FortiManager workspace mode is **not** in use. The data source is exclusively the FMG Install Preview API (async task-based diff generation).

---

## Decisions Made

| Question | Decision |
|---|---|
| Pending change scope | Install delta only (FMG committed vs. device running config) — no workspace pre-commit layer |
| FMG API approach | Install Preview (`securityconsole/install/preview` → poll task → `securityconsole/preview/result`) |
| Diff output format | CLI-format diff text, grouped by VDOM where applicable |
| Detail level | Summary count tiles by category + full CLI diff lines (add/remove/modify) |
| Device list default | All devices in ADOM; "Pending only" toggle to filter to out-of-sync |
| VDOM support | Mixed — group by VDOM when present, flat when not |
| Async wait UX | Inline spinner with status message; right panel populates when preview is ready |
| Multi-device export | Export queue — view one device at a time, "Add to Export Queue" accumulates; single export covers all queued devices |

---

## Architecture

### New Files

| File | Purpose |
|---|---|
| `app/routes/pending_changes_routes.py` | Blueprint: page route + 3 API endpoints |
| `app/templates/pending_changes.html` | Jinja2 page template |
| `app/static/js/pending_changes.js` | Frontend logic: device list, diff render, export queue |

### Modified Files

| File | Change |
|---|---|
| `app/fmg_client.py` | Add `get_devices_with_sync_status()` and `get_install_preview()` |
| `app/__init__.py` | Add `pending_changes_routes` to `_BLUEPRINT_MODULES` |
| `CLAUDE.md` | Add Pending Changes tab section |

---

## Backend

### FMGClient — New Methods

#### `get_devices_with_sync_status(adom: str) -> list[dict]`

Calls `/dvmdb/adom/{adom}/device` requesting fields: `name`, `ip`, `mgmt_ip`, `platform_str`, `os_ver`, `mr`, `patch`, `conf_status`, `sn`.

Returns list of device dicts. `conf_status` values:
- `0` → unknown
- `1` → insync
- `2` → outofsync

#### `get_install_preview(adom: str, device: str) -> str`

Async three-step operation:

1. **Trigger**: `POST securityconsole/install/preview` with body `{"adom": adom, "device": {"name": device}}` → receives `taskid`
2. **Poll**: `GET task/task/{taskid}` every 2 seconds; continue until `percent == 100` or error state; timeout after 90 seconds
3. **Fetch**: `GET securityconsole/preview/result/{adom}` filtered to the requested device → returns raw CLI diff text string

Raises `FMGError` on task failure or timeout. Returns empty string if device has no pending changes.

---

### API Endpoints

All endpoints are under the `pending_changes` blueprint. All ADOM-scoped endpoints call `check_adom_access(adom)` as their first action.

#### `GET /pending-changes`
Page route. Requires `tab_required("pending_changes")`. Renders `pending_changes.html`.

#### `GET /api/pending-changes/adoms`
Returns ADOM list filtered by user access (same as all other tabs — strips names starting with `forti`).

#### `GET /api/pending-changes/adoms/<adom>/devices`
Returns device list for the ADOM with sync status.

Response:
```json
[
  {
    "name": "FW-PROD-01",
    "ip": "10.1.1.1",
    "platform": "FortiGate-100F",
    "version": "v7.4.1",
    "conf_status": "outofsync",
    "serial": "FGT1234567890"
  }
]
```

`conf_status` is normalized to string: `"insync"`, `"outofsync"`, or `"unknown"`.

#### `POST /api/pending-changes/adoms/<adom>/device/<device>/preview`
Triggers install preview for a single device, polls until complete, parses and returns structured diff.

Response:
```json
{
  "device": "FW-PROD-01",
  "ip": "10.1.1.1",
  "conf_status": "outofsync",
  "summary": {
    "firewall_policy": 3,
    "routing": 1,
    "address": 0,
    "service": 0,
    "system": 1,
    "other": 0
  },
  "vdoms": [
    {
      "name": "root",
      "changes": [
        {"type": "add", "line": "config firewall policy"},
        {"type": "modify", "line": "    edit 42"},
        {"type": "remove", "line": "        set comments \"old comment\""}
      ]
    }
  ],
  "raw": "config firewall policy\n    edit 42\n..."
}
```

**Summary computation**: Server-side scan of raw diff text. `config` block header lines are matched against a keyword map:

| Keyword in header | Summary key |
|---|---|
| `firewall policy` / `firewall policy6` | `firewall_policy` |
| `router static` / `router policy` / `router ospf` / `router bgp` | `routing` |
| `firewall address` / `firewall addrgrp` | `address` |
| `firewall service` | `service` |
| `system global` / `system interface` / `system settings` | `system` |
| anything else | `other` |

**VDOM detection**: If the raw diff contains `vdom {name}` block delimiters, changes are split and grouped per VDOM. Otherwise, a single implicit `root` VDOM is used.

**`conf_status` as a UI filter only**: The "Pending only" toggle uses `conf_status` to filter the device list. It does not gate the preview call — clicking any device (including `insync` ones) always triggers a preview, because `conf_status` can lag behind actual state. A device showing `insync` may return an empty diff; a device showing `outofsync` is expected to return changes.

**Change type detection**: FMG install preview output is FortiOS CLI commands (not a git-style diff). The server-side parser must classify lines based on CLI block context:
- A `config` block present in the preview but absent from the running config → `add`
- A `delete N` or `unset` line → `remove`  
- An `edit N` block with `set` lines → `modify`
- Lines with no clear add/remove indicator → `modify` (default)

**Implementation note**: The exact format of `securityconsole/preview/result` output must be verified against a real FMG instance during development. The parser may need adjustment based on actual output. The `raw` field is always included in the response so the frontend can display the unprocessed text as a fallback.

---

## Frontend

### `pending_changes.js` — State

```js
let allDevices = [], filteredDevices = []
let currentPage = 1, pageSize = 25
let filterText = '', pendingOnly = false
let currentDevice = null, currentDiff = null
let exportQueue = []   // [{device, ip, adom, summary, vdoms, raw, timestamp}]
```

### Page Lifecycle

1. **On load** → `fetchAdoms()` → populate ADOM `<select>`
2. **On ADOM change** → `fetchDevices(adom)` → populate device table, clear right panel
3. **On search input / pending-only toggle** → `applyFilters()` → client-side re-render (no fetch)
4. **On device row click** → `loadPreview(adom, device)`:
   - Show spinner + "FortiManager is generating diff, please wait…" in right panel
   - POST to preview endpoint (can take 10–60s)
   - On success: render summary tiles + VDOM diff sections
   - On error: show error message in right panel
5. **"Add to Export Queue"** → push `currentDiff` to `exportQueue`, update footer
6. **Export buttons** → `exportCsv()` / `exportJson()` / `exportPdf()` over full queue

### Device Table

Columns: Name, Management IP, Platform, Sync Status badge.

Sync status badges:
- `insync` → green "In Sync"
- `outofsync` → amber "Out of Sync"
- `unknown` → grey "Unknown"

Pagination: page size selector (10 / 25 / 50), `<< < … > >>` controls — identical pattern to Device Review tab.

### Diff Viewer

Each VDOM rendered as a collapsible `<details><summary>vdom: {name}</summary>` block.

Change lines inside a `<pre class="diff-block">` with per-line spans:
- `diff-add` → green, prefixed `+`
- `diff-remove` → red, prefixed `-`
- `diff-modify` → amber, prefixed `~`

Summary tiles shown above the diff — only tiles with count > 0 are rendered.

### Export Queue Footer

- `position: sticky; bottom: 0` bar, hidden when `exportQueue.length === 0`
- Each queued device as a chip: `{device name} ×`
- Right side: CSV | JSON | PDF buttons

**ADOM change + non-empty queue**: If the user switches ADOM while the export queue contains items, a confirmation dialog asks "Changing ADOM will clear your export queue. Continue?" — proceed clears the queue and loads the new ADOM; cancel leaves the current ADOM selected.

### Export Formats

All three include a metadata header:

```
Pending Changes Export
Generated: {timestamp}
User: {username}
ADOM: {adom}
Devices: FW-PROD-01, FW-PROD-02
```

**CSV**: One row per change line.  
Columns: `device, ip, vdom, change_type, line`  
Summary counts in comment rows above the data rows.

**JSON**:
```json
{
  "meta": {"generated": "...", "user": "...", "adom": "..."},
  "devices": [
    {
      "device": "FW-PROD-01",
      "ip": "10.1.1.1",
      "summary": {...},
      "vdoms": [{"name": "root", "changes": [...]}]
    }
  ]
}
```

**PDF**: Print-to-new-window pattern (same as Device Review). Inline HTML with styled `<pre>` per device, color-coded diff lines, `page-break-before: always` between devices.

---

## Inline Help (Tooltip Text)

| Location | Text |
|---|---|
| "Pending only" toggle | "Shows only devices where FortiManager has committed changes that have not yet been installed on the device." |
| Diff viewer header | "Changes are shown in CLI format. `+` added, `-` removed, `~` modified. Grouped by VDOM where applicable." |
| "Add to Export Queue" button | "Accumulate multiple devices into a single export document for use in a change record." |

---

## CLAUDE.md Addition

A new **Pending Changes tab** section to be added to CLAUDE.md, covering:
- Tab key `pending_changes`, route `/pending-changes`
- The two new `FMGClient` methods and FMG API paths
- The async preview flow: trigger → poll task → fetch result
- `conf_status` integer-to-string mapping
- Export queue pattern
- `conf_status` filtering ("pending only" toggle)

---

## Access Control

- Tab registered as `pending_changes` in the tab registry
- `tab_required("pending_changes")` on page route and all API endpoints
- `check_adom_access(adom)` on all ADOM-scoped endpoints
- Admin users are always unrestricted (all ADOMs)
- Non-admin access follows the same group/ADOM rules as all other tabs

---

## Error States

| Scenario | Behavior |
|---|---|
| FMG unreachable | Device list shows error banner; right panel shows "Unable to connect to FortiManager" |
| Preview task times out (>90s) | Right panel shows "Diff generation timed out. FortiManager may be busy — try again." |
| Preview task fails on FMG side | Right panel shows FMG error message |
| Device is in sync | Right panel shows "No pending changes found for this device." (not an error) |
| ADOM access denied | 403 JSON response; JS shows "You do not have access to this ADOM." |
