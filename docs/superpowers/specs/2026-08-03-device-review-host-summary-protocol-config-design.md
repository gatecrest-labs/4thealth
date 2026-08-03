# Design: Device Review Host Summary & Protocol Severity Config

**Date:** 2026-08-03
**Status:** Approved

## Summary

Two related improvements to the Device Review feature:

1. **Per-host summary** — add a host-by-host result breakdown to both the scheduled email body and the attached report (HTML/CSV/JSON formats).
2. **Protocol severity config** — fix the WARN/INFO inconsistency for the Interface Protocols check and introduce an optional `protocol_severity.json` override file so operators can reclassify protocols without touching code.

Both changes update `CHANGELOG.md` and relevant MD documentation upon completion.

---

## Change 1: Protocol Severity Classification Fix

### Problem

The Interface Protocols check currently produces inconsistent results:
- Interface with only `ping` → **WARN** (no secure protocol present)
- Interface with `ping + https` → **INFO** (secure protocol present)

`ping` is informational — it should not cause a downgrade to WARN when it is the only protocol present.

### Result Logic Fix

File: [app/device_review.py](../../app/device_review.py), lines 183–188.

**Current logic:**
```python
if has_insecure:
    result = "INSECURE"
elif not has_secure:
    result = "WARN"   # ← incorrectly catches ping-only
else:
    result = "INFO"
```

**New logic:**
```python
if has_insecure:
    result = "INSECURE"
elif has_secure or has_info_only:
    result = "INFO"
else:
    result = "WARN"   # safety net: no protocols of any known type
```

Where `has_info_only = any(p["secure"] is None for p in proto_list)`.

**Outcome:** `ping`-only → INFO; `http`-only → INSECURE; `https + ping` → INFO; no protocols → WARN (edge-case safety net only).

### Protocol Severity Config File

**File:** `protocol_severity.json` (project root, gitignored)
**Example file committed:** `protocol_severity.example.json`

Format:
```json
{
  "ping":        "info",
  "fgfm":        "info",
  "capwap":      "info",
  "speed-test":  "info",
  "ftm":         "info",
  "https":       "secure",
  "ssh":         "secure",
  "snmp":        "secure",
  "fabric":      "secure",
  "http":        "insecure",
  "telnet":      "insecure",
  "http-redirect": "insecure"
}
```

Valid values: `"secure"`, `"insecure"`, `"info"`, `null` (treated as `"info"`).

**Loading behaviour:**
- A module-level `_EFFECTIVE_PROTO_SECURE` dict is built at import time by merging `_PROTO_SECURE` defaults with overrides from `protocol_severity.json`.
- Missing file → silent skip; pure defaults apply.
- Unknown protocol keys in the file are accepted (allows operators to classify new protocols).
- Invalid values (not one of the four above) → logged as a warning and ignored; default for that key is preserved.
- `_classify_proto` uses `_EFFECTIVE_PROTO_SECURE` instead of `_PROTO_SECURE`.

**Default mapping (unchanged from current `_PROTO_SECURE`):**

| Protocol | Default | `secure` value |
|---|---|---|
| `https` | secure | `True` |
| `ssh` | secure | `True` |
| `snmp` | secure | `True` |
| `fabric` | secure | `True` |
| `http` | insecure | `False` |
| `telnet` | insecure | `False` |
| `http-redirect` | insecure | `False` |
| `ping` | info | `None` |
| `fgfm` | info | `None` |
| `capwap` | info | `None` |
| `speed-test` | info | `None` |
| `ftm` | info | `None` |

Internal mapping: `"secure"` → `True`, `"insecure"` → `False`, `"info"` / `null` → `None`.

---

## Change 2: Per-Host Summary in Email Body

### New function: `_build_host_summary_html(results)`

File: [app/device_review_scheduler.py](../../app/device_review_scheduler.py)

Takes the `results` list (`[{device, rows, error?}, ...]`) from `_execute_job`. Returns an HTML string containing an `<h3>` heading and a `<table>` with columns:

**Device | PASS | FAIL | INSECURE | WARN | CONFIG_MISSING | INFO | Total**

One row per device, sorted alphabetically by device name. A **Totals** footer row sums all numeric columns.

**Cell styling:**
- FAIL or INSECURE count > 0 → red background (`#fee2e2`)
- WARN or CONFIG_MISSING count > 0, no FAIL/INSECURE → amber background (`#fef3c7`)
- All counts 0 for negative results → no special style
- The Device column shows the device name; if the device errored, append ` (error)` in red.

### Integration into `_build_summary_html`

`_build_summary_html(adom, all_rows, generated_at, error_devices)` gains a `results` parameter.

The host summary table is inserted **above** the existing per-check summary table in the email body.

---

## Change 3: Per-Host Summary in Attachment

### HTML/PDF format

`_build_pdf_html_dr(adom, all_rows, generated_at)` gains a `results` parameter.

A per-host summary table is prepended at the top of the HTML document, before the detailed findings table. Same column structure as the email summary. Styled with inline CSS consistent with the rest of the report (uses `_RESULT_COLOR` palette for result columns, same font/table style).

### CSV format

Comment lines are prepended above the existing `# 4THealth Device Review` header block, one line per device:

```
# Host Summary
# Device,PASS,FAIL,INSECURE,WARN,CONFIG_MISSING,INFO,Total
# MNHQGOFWNPVS01,4,0,0,9,0,4,17
# COLOCFWNPVS01,3,0,0,8,0,5,16
```

These lines start with `#` so they are treated as comments by most CSV parsers but remain human-readable.

### JSON format

A `"host_summary"` key is added to the top-level JSON object, before `"rows"`:

```json
{
  "report_type": "device_review",
  "adom": "...",
  "exported_at": "...",
  "host_summary": [
    {
      "device": "MNHQGOFWNPVS01",
      "counts": {
        "PASS": 4, "FAIL": 0, "INSECURE": 0,
        "WARN": 9, "CONFIG_MISSING": 0, "INFO": 4
      },
      "total": 17
    }
  ],
  "rows": [...]
}
```

Devices are sorted alphabetically by name.

---

## Documentation Updates

The following files must be updated as part of this implementation:

1. **`CHANGELOG.md`** — add entries under a new version/date heading for:
   - Interface Protocols: fix WARN/INFO inconsistency; `ping`-only interfaces now report INFO
   - Interface Protocols: add `protocol_severity.json` config override support
   - Device Review scheduled reports: add per-host summary to email body and all attachment formats

2. **`CLAUDE.md`** — update the **Device Review tab** section:
   - Add a note about `protocol_severity.json` to the result values table or a new sub-section
   - Update the result values table to clarify INFO includes ping-only interfaces
   - Note the `protocol_severity.example.json` file

3. **`docs/features.md`** — update the Device Review section to document `protocol_severity.json`, the updated result values (INFO for ping-only), and the per-host summary in scheduled reports.

---

## Files Changed

| File | Change |
|---|---|
| `app/device_review.py` | Fix result logic; load `protocol_severity.json`; add `_EFFECTIVE_PROTO_SECURE` |
| `app/device_review_scheduler.py` | Add `_build_host_summary_html`; update `_build_summary_html`, `_build_pdf_html_dr`, CSV/JSON builders |
| `protocol_severity.example.json` | New committed example file |
| `.gitignore` | Add `protocol_severity.json` |
| `CLAUDE.md` | Document config file and result value change |
| `docs/features.md` | Update Device Review section with protocol config and per-host summary |
| `CHANGELOG.md` | Add entries for both changes |

---

## Out of Scope

- No Admin UI for editing protocol severity (operators edit the JSON file directly)
- No live reload of `protocol_severity.json` (app restart required for changes to take effect)
- No changes to the Device Review interactive tab (only the scheduler report output changes for the summary; the live tab UI is unchanged)
