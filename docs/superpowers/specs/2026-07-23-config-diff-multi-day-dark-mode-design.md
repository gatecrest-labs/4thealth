# Config-Diff: Multi-Day Scheduling & Dark Mode Fix

**Date:** 2026-07-23  
**Status:** Approved

## Summary

Two improvements to the Admin → Config-Diff tab:

1. **Multi-day scheduling** — replace the single day-of-week selector with seven checkboxes so a job can run on any combination of days (e.g. Monday and Thursday only, or every weekday).
2. **Dark mode fix** — the job form panel uses hard-coded light-grey hex colours in inline `style=""` attributes that render badly in dark mode; replace with a CSS class that uses the app's existing CSS variable system.

No changes to SMTP logic, email delivery, or any other tab.

---

## 1. Data Model

The persisted job schema changes one field:

| Before | After |
|--------|-------|
| `"day_of_week": "MON"` (string) | `"days_of_week": ["MON", "THU"]` (array) |

- Valid day codes: `SUN MON TUE WED THU FRI SAT`
- Array must contain at least one element; all 7 is valid
- No backward-compat migration needed — no existing jobs in production

Example stored job:

```json
{
  "id": "...",
  "adom": "Enterprise",
  "days_of_week": ["MON", "THU"],
  "time": "06:00",
  "format": "pdf",
  "email": "ops@example.com",
  "enabled": true,
  "created_at": "...",
  "runs": []
}
```

---

## 2. UI Changes

### Day-of-week picker

Replace `<select id="jobFormDay">` with a row of 7 labelled checkboxes inside a `<div class="day-picker">`:

```
Day(s)   [ ] Sun  [x] Mon  [ ] Tue  [ ] Wed  [x] Thu  [ ] Fri  [ ] Sat
```

- `div.day-picker` — `display: flex; flex-wrap: wrap; gap: 8px`
- Each item: `<label class="day-picker-item"><input type="checkbox" value="MON"> Mon</label>`
- Checked state: `var(--accent)` background tint so selected days are visually distinct
- Save validation: if zero checkboxes are checked, show inline error in `#jobFormMsg` and abort submit

### Jobs table

The "Day" column changes from a single code to a short-name comma list:

- `["MON", "THU"]` → `Mon, Thu`
- `["MON","TUE","WED","THU","FRI"]` → `Mon, Tue, Wed, Thu, Fri`

### Dark mode fix

`#jobForm` currently has `style="background:#f3f4f6;border:1px solid #d1d5db;..."` baked in.

- Remove those inline styles
- Add `class="job-form-panel"` to the element
- Add `.job-form-panel` to `style.css`:

```css
.job-form-panel {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px;
  max-width: 560px;
  margin-bottom: 16px;
}
```

This uses the same CSS variable system as the rest of the app and adapts automatically to both light and dark themes.

---

## 3. Backend Changes

### `app/config_diff_scheduler.py`

- `_validate_job_fields(data)` — validate `data["days_of_week"]` is a non-empty list; each element must be in `_VALID_DAYS`; raise `ValueError` otherwise
- `create_job()` — store `days_of_week` list; remove `day_of_week` string
- `update_job()` — same as create
- `_register(job)` — build the cron day string: `",".join(day_map[d] for d in job["days_of_week"])`; pass to `CronTrigger(day_of_week=...)`

APScheduler's `CronTrigger` natively accepts comma-separated day strings, so no extra complexity is needed.

### `app/routes/admin_routes.py`

No logic changes needed — the field passes through as-is from request JSON to scheduler and back.

### `app/static/js/admin.js`

- `showJobForm(job)` — iterate the 7 checkboxes and set `checked` based on `job.days_of_week` (or default to `["MON"]` for new jobs)
- `saveJob()` — collect all checked day values into an array; if length is 0, show error and return; send `days_of_week` in the POST/PUT payload
- Table render (`loadJobs`) — map each code to a short display name and join with `, `

### `app/templates/admin.html`

- Replace `<select id="jobFormDay">` with `div.day-picker` containing 7 checkbox+label pairs
- Replace `style="background:#f3f4f6;border:1px solid #d1d5db;..."` on `#jobForm` with `class="job-form-panel"`
- Update the jobs table `<th>Day</th>` header to `<th>Days</th>`

---

## 4. Testing

**File: `tests/test_config_diff_scheduler.py`**

- Update all existing fixtures: `day_of_week: "MON"` → `days_of_week: ["MON"]`
- Add `test_create_job_multi_day` — creates job with `["MON", "THU"]`, confirms both stored correctly
- Add `test_validate_empty_days` — `days_of_week: []` raises `ValueError`
- Add `test_validate_invalid_day_code` — `days_of_week: ["MONDAY"]` raises `ValueError`
- Add `test_validate_single_day_still_works` — `days_of_week: ["FRI"]` is valid
- Add `test_register_multi_day_cron_string` — mock APScheduler and confirm `CronTrigger` receives `"mon,thu"` for `["MON", "THU"]`

---

## 5. Documentation

- **`CLAUDE.md`** — update Config-Diff Scheduled Exports section: change `day_of_week` to `days_of_week`, note it is an array of day codes
- **`docs/api-reference.md`** — update job schema example if it shows `day_of_week`
- **`config_diff_jobs.example.json`** — already an empty array `[]`; no change needed
- **`CHANGELOG.md`** — add entry: multi-day scheduling support and dark mode fix for job form
- **Graphify** — run `graphify update .` after all code changes

---

## 6. Out of Scope

- No changes to SMTP client, email delivery, or attachment generation
- No changes to any other admin sub-tab
- No modal dialog refactor of the job form
- No audit of other inline styles in the Config-Diff panel beyond `#jobForm`
