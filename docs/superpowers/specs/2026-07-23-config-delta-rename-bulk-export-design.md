# Config-Delta Rename & Bulk ADOM Export — Design Spec

**Date:** 2026-07-23
**Branch:** development

## Summary

Two changes to the existing DIFF (Beta) tab:

1. **Rename** the tab display label from "DIFF (BETA)" to "Config-Delta".
2. **Add bulk ADOM export** — a single button that fetches every device's pending diff in the selected ADOM and exports the combined result as CSV, JSON, or PDF, with a live progress indicator and cancel support.

---

## Section 1 — Tab Rename

### What changes

| Location | Old | New |
|---|---|---|
| `registry.register()` call in `pending_changes_routes.py:51` | `"DIFF (BETA)"` | `"Config-Delta"` |
| Page `<title>` in `pending_changes.html` | `DIFF (Beta)` | `Config-Delta` |
| Page heading `<h5>` in `pending_changes.html` | `DIFF (Beta)` | `Config-Delta` |
| Export filenames in `pending_changes.js` (`exportCsv`, `exportJson`, `exportPdf`) | `diff-beta-*.csv/json/pdf` | `config-delta-*.csv/json/pdf` |
| `CLAUDE.md` section heading | `### DIFF tab (Beta)` | `### Config-Delta tab` |
| `docs/features.md` section heading | `## DIFF (Beta)` | `## Config-Delta` |
| `docs/api-reference.md` section heading | `## DIFF (Beta)` | `## Config-Delta` |

### What does NOT change

- Internal tab key: `pending_changes` (used in permissions, groups.json, decorators)
- URL: `/pending-changes`
- All API paths: `/api/pending-changes/*`
- Historical plan/spec files — left as written records

---

## Section 2 — Bulk ADOM Export

### UI placement

A new **"Export All Devices ▾"** split-button dropdown is added to the header row that already contains the ADOM selector and the existing "Pending only" toggle. The dropdown offers three options: CSV, JSON, PDF. It is only enabled when an ADOM is selected and the device list has loaded.

The existing per-device queue footer and its export buttons are unchanged and remain visible at all times except during a bulk run (see Progress below).

### Execution flow

All logic is client-side in `pending_changes.js`. No new backend endpoints.

1. User clicks "Export All Devices → CSV/JSON/PDF".
2. Button disables; a progress bar + status line appears below the ADOM selector: `Fetching 1 of 12 — FW-PROD-01…`
3. Existing per-device queue footer is hidden for the duration of the run.
4. For each device in the current device list (in order):
   a. POST `/api/pending-changes/adoms/<adom>/device/<device>/preview` → receive `task_id`.
   b. Poll `GET /api/pending-changes/task/<task_id>` every 2 s until `status` is `"done"` or `"error"` (inherits the existing 90 s FMG timeout from the server side).
   c. Collect result into a local array.
5. Once all devices are processed, trigger the download in the chosen format.
6. Progress bar and status line are removed; queue footer is restored.

### Result object shape per device

```
{
  device:    string,     // device name
  ip:        string,
  adom:      string,
  status:    "ok" | "no_changes" | "error",
  summary:   {...} | null,
  vdoms:     [...] | null,
  raw:       string | null,
  error:     string | null,   // set when status === "error"
  timestamp: string           // ISO-8601, stamped client-side at collection time
}
```

A device is `"no_changes"` when `status === "done"` and every VDOM in `vdoms` has zero change lines (or `vdoms` is empty).

### Cancel

A `× Cancel` link appears inline with the progress text. Clicking it:
- Sets a `bulkCancelled` flag read by the polling loop.
- Stops polling the current task (no API call to cancel it — the task expires naturally via the 10-minute TTL).
- Skips remaining devices.
- Re-enables the UI (restores button, hides progress, shows queue footer).
- Does not trigger a partial download.

### Export content

**CSV** — one row per VDOM change line. Header block at top (ADOM, timestamp, username, total devices, devices with changes). Devices with no changes get a single row with `result=no_changes` and blank change columns. Devices that errored get a row with `result=error` and the error message.

**JSON** — `{ adom, exported_at, exported_by, devices: [ ...result objects ] }`. `changes` key is `null` for no-changes devices.

**PDF** — one section per device. No-changes devices render a grey italic `"No pending changes"` line. Error devices render a red `"Export failed: <message>"` line. Uses the same jsPDF approach already used by the per-device queue export.

### Filename convention

`config-delta-<adom>-all-<YYYYMMDD>.csv/json/pdf`

---

## Section 3 — Docs & Graph

- `CLAUDE.md`, `docs/features.md`, `docs/api-reference.md` updated as per Section 1 table.
- Historical superpowers plan/spec files left unchanged.
- `graphify update .` run after all code changes.

---

## Section 4 — Testing

### Automated

```bash
pytest tests/test_pending_changes.py
```

Must remain green. No new Python tests required (no new backend endpoints).

### Manual smoke tests

| Test | Expected |
|---|---|
| Nav bar after rename | Tab shows "Config-Delta" |
| Per-device queue export | CSV/JSON/PDF filenames start with `config-delta-` |
| Export All button disabled state | Disabled when no ADOM selected |
| Export All — full run | Progress counter advances, download triggers at end |
| Export All — device with no changes | Included in export with no-changes indicator |
| Export All — device with FMG error | Included in export with error message, run continues |
| Export All — cancel mid-run | Run stops, no download, UI restores |
| Existing per-device queue | Unchanged behaviour throughout |

---

## Section 5 — Commit & Push

Single commit on `development` branch:

```
feat: rename DIFF tab to Config-Delta and add bulk ADOM export
```

Push to GitLab after manual smoke tests pass.
