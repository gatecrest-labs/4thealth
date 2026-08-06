# Device Review HTML Report — Findings Filter Bar

**Date:** 2026-08-06
**Branch:** development
**Scope:** `app/device_review_scheduler.py` only — no other files change

---

## Goal

Add interactive filtering to the Findings table in Device Review scheduled-job HTML reports. Users can quickly isolate failures (e.g., show only `FAIL`) or scope results to a single host, without leaving the email attachment.

---

## What Changes

### 1. Data attributes on Findings rows

Each `<tr>` in the Findings table gains two HTML attributes at generation time:

```html
<tr data-result="FAIL" data-device="fw-hostname">
```

- `data-result` — the result code (FAIL, INSECURE, WARN, CONFIG_MISSING, PASS, INFO)
- `data-device` — the device name, passed through `_esc()` before insertion

No other changes to the table structure or columns.

---

### 2. Filter bar UI

A sticky bar is rendered immediately above the Findings `<h2>` heading. It contains:

**Result filter — quick-filter buttons**
- Buttons: ALL · FAIL · INSECURE · WARN · CONFIG_MISSING · PASS · INFO
- Colors match `_RESULT_COLOR` (FAIL/INSECURE = red, WARN/CONFIG_MISSING = amber, PASS = green, INFO = blue, ALL = grey)
- Single-select: only one result type active at a time; ALL is active by default
- Active button is visually depressed/highlighted

**Host filter — dropdown**
- `<select>` with "All Hosts" default plus one `<option>` per unique device in the findings, sorted alphabetically, generated at render time
- Resets to "All Hosts" whenever a result button is clicked

**Row count indicator**
- A `<span>` showing `Showing X of Y findings` — updates live on every filter change

---

### 3. JavaScript filter logic

A single `filterFindings()` function:

1. Reads the active result button value (or `"ALL"`)
2. Reads the selected host from the dropdown (or `"ALL"`)
3. Iterates all finding `<tr>` rows, toggling `display: none` based on whether both `data-result` and `data-device` match
4. Updates the row count `<span>`

Event wiring:
- Each result button: `onclick` calls `filterFindings()` (after setting itself as active)
- Host dropdown: `onchange` calls `filterFindings()`

---

## Implementation Approach

**Option C** — module-level string constants, keep f-string generation.

- `_REPORT_JS` — new module-level constant; contains the full filter JS block
- `_REPORT_CSS` — new module-level constant; contains filter bar and button styles
- `_build_pdf_html_dr()` — injects `{_REPORT_CSS}` into the `<style>` block and `{_REPORT_JS}` into the `<script>` block; adds filter bar HTML above the Findings section; adds `data-result`/`data-device` attributes to finding row `<tr>` tags

No other functions change. No new files. No new dependencies.

---

## Out of Scope

- Host Summary table filtering (deferred — aggregate counts, not individual rows)
- Check Summary table filtering
- PDF format (already generates HTML; no true PDF renderer in scope)
- CSV / JSON formats (no DOM, filtering not applicable)
- Email body HTML (only the attachment gets the filter bar)
