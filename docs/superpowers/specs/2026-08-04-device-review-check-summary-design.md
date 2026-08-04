# Device Review Report: Per-Check Summary Section

**Date:** 2026-08-04  
**Branch:** development  
**File:** `app/device_review_scheduler.py`

---

## Goal

Add a per-check summary section to every Device Review scheduled report format (email body, HTML/PDF attachment, CSV, JSON). The section appears above the existing Host Summary and shows which checks ran, their descriptions, and result counts broken down by all six result types.

---

## Background

The existing scheduler (`app/device_review_scheduler.py`) already computes a `by_check` dict in `_build_summary_html` and renders a 4-column table (PASS, FAIL+INSECURE combined, WARN+CONFIG_MISSING combined, INFO dropped). The attachment formats (HTML/PDF, CSV, JSON) have no per-check breakdown at all.

This change:
1. Replaces the collapsed 4-column email table with a full 6-column table.
2. Adds the same section to all attachment formats.
3. Moves the check summary above the host summary in every format.

---

## Check Summary Section

One row per check that was run, ordered by `CHECKS_META` declaration order.

### Columns

| Check | Description | PASS | INFO | WARN | CONFIG_MISSING | FAIL | INSECURE |
|---|---|---|---|---|---|---|---|

- **Check**: display name from `CHECKS_META` (e.g. "NTP Configuration")
- **Description**: one-liner description from `CHECKS_META`
- Result counts sourced from the flat `all_rows` list (already available in every builder)
- Checks that ran but produced zero rows appear with all-zero counts
- Checks not selected for this job run are excluded

---

## Shared Helper: `_build_check_summary`

```python
def _build_check_summary(results, checks_ran):
    """
    Returns a list of dicts, one per check in CHECKS_META order, filtered to checks_ran.
    Each dict: { "key", "name", "description", "PASS", "INFO", "WARN",
                 "CONFIG_MISSING", "FAIL", "INSECURE" }
    """
```

- `results`: the list of per-device dicts returned by `bulk_device_review_adom`
- `checks_ran`: list of check keys from the job record (`job["checks"]`, empty = all)
- Uses `CHECKS_META` (imported from `app.device_review`) for ordering, names, descriptions
- Called once in `_execute_job`; result passed to both email and attachment builders

---

## Per-Format Changes

### Email body (`_build_summary_html`)

- Remove existing `by_check` aggregation loop and 4-column table
- Accept `check_summary` as a parameter (pre-computed by `_build_check_summary`)
- Render the new 6-column Check Summary table **before** the Host Summary table
- Column order: PASS | INFO | WARN | CONFIG_MISSING | FAIL | INSECURE
- Color-code count cells using `_RESULT_COLOR` background tints (non-zero only, or light grey for zero)

### HTML/PDF attachment (`_build_pdf_html_dr`)

- Accept `check_summary` as a parameter
- Insert the 6-column Check Summary table **before** the Host Summary table
- Same column order and color treatment as the email

### CSV attachment (`_build_attachment_dr`)

- Add a `# Check Summary` comment block **before** the existing `# Host Summary` block
- Format: one `#`-prefixed row per check — `# <name> | <description> | PASS=n | INFO=n | WARN=n | CONFIG_MISSING=n | FAIL=n | INSECURE=n`

### JSON attachment

- Add a `check_summary` array **before** `host_summary` in the payload
- Each element: `{ "check": "<name>", "description": "...", "PASS": n, "INFO": n, "WARN": n, "CONFIG_MISSING": n, "FAIL": n, "INSECURE": n }`

---

## Call-Site Changes in `_execute_job`

```python
check_summary = _build_check_summary(results, job.get("checks") or [])
body_html = _build_summary_html(adom, results, generated_at, check_summary)
attachment = _build_attachment_dr(adom, fmt, results, generated_at, check_summary)
```

---

## Out of Scope

- No changes to the Admin UI scheduled-jobs form
- No changes to the per-device progress loop or API endpoints
- No changes to run-history persistence schema
- No changes to `bulk_device_review_adom` or `device_review.py`
