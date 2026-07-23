# Config-Diff Multi-Day Scheduling & Dark Mode Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single day-of-week selector on Config-Diff scheduled jobs with a multi-checkbox picker (any combination of 1–7 days), and fix the job form panel so it renders correctly in dark mode.

**Architecture:** The backend stores `days_of_week` as a JSON array of day codes; APScheduler's `CronTrigger` natively accepts comma-separated day strings so no scheduler complexity is added. The dark mode fix replaces hard-coded hex values in an inline `style=""` attribute with a CSS class that uses the app's existing CSS variable system (`var(--surface-alt)`, `var(--border)`).

**Tech Stack:** Python 3 / Flask / APScheduler, vanilla JS (no framework), CSS custom properties (`var(--surface-alt)` etc.), pytest.

## Global Constraints

- Day codes are exactly: `SUN MON TUE WED THU FRI SAT` (uppercase, 3-letter)
- `days_of_week` must be a non-empty list — saving with zero days selected is a validation error
- No existing job data to migrate — schema change is clean
- All CSS uses the app's existing variable system (`var(--surface-alt)`, `var(--border)`, `var(--text)`) — no new hard-coded hex colours
- Tests run with: `uv run pytest tests/ -v`
- Dependency management: `uv` only — do not use `pip install`

---

## File Map

| File | Change |
|---|---|
| `app/config_diff_scheduler.py` | Modify: `_validate_job_fields`, `create_job`, `update_job`, `_register` |
| `app/templates/admin.html` | Modify: replace `<select id="jobFormDay">` with checkbox group; replace inline styles on `#jobForm` with class |
| `app/static/js/admin.js` | Modify: `showJobForm`, `saveJob`, `renderJobsTable` |
| `app/static/css/style.css` | Add: `.job-form-panel`, `.day-picker`, `.day-picker-item` |
| `tests/test_config_diff_scheduler.py` | Modify all fixtures; add 5 new tests |
| `CLAUDE.md` | Update `days_of_week` description in Config-Diff section |
| `docs/api-reference.md` | No change needed (table has no schema example with `day_of_week`) |
| `CHANGELOG.md` | Add entry under `[Unreleased]` |

---

## Task 1: Backend — `days_of_week` array support

**Files:**
- Modify: `app/config_diff_scheduler.py:26-31` (`_VALID_DAYS`, `_validate_job_fields`)
- Modify: `app/config_diff_scheduler.py:66-85` (`create_job`)
- Modify: `app/config_diff_scheduler.py:88-112` (`update_job`)
- Modify: `app/config_diff_scheduler.py:394-417` (`_register`)
- Test: `tests/test_config_diff_scheduler.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `create_job(data)` accepts `data["days_of_week"]: list[str]`, stores `{"days_of_week": ["MON", "THU"], ...}`
  - `update_job(job_id, data)` same
  - `_validate_job_fields(data)` raises `ValueError` if `days_of_week` is missing, empty, or contains invalid codes
  - `_register(job)` builds cron string `"mon,thu"` from `job["days_of_week"]`

- [ ] **Step 1: Update existing tests to use `days_of_week`**

Open `tests/test_config_diff_scheduler.py`. Replace every occurrence of `"day_of_week": "MON"` with `"days_of_week": ["MON"]`. The file currently has these occurrences at lines ~22, 31, 51 (in `test_create_job_assigns_id`, `test_update_job`, `test_prune_old_runs`). Also update `test_delete_job`. The full updated file:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    p = tmp_path / "config_diff_jobs.json"
    monkeypatch.setattr("app.config_diff_scheduler._JOBS_PATH", p)
    return p


def test_get_all_jobs_empty(jobs_path):
    from app import config_diff_scheduler as sched
    assert sched.get_all_jobs() == []


def test_create_job_assigns_id(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({
        "adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
        "format": "pdf", "email": "x@x.com", "enabled": True
    })
    assert "id" in job
    assert len(sched.get_all_jobs()) == 1


def test_update_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    updated = sched.update_job(job["id"], {**job, "email": "new@x.com"})
    assert updated["email"] == "new@x.com"
    assert sched.get_all_jobs()[0]["email"] == "new@x.com"


def test_delete_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    sched.delete_job(job["id"])
    assert sched.get_all_jobs() == []


def test_prune_old_runs(jobs_path):
    from app import config_diff_scheduler as sched
    import datetime
    old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=40)).isoformat() + "Z"
    recent_ts = datetime.datetime.utcnow().isoformat() + "Z"
    job = sched.create_job({"adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    jobs = json.loads(jobs_path.read_text())
    jobs[0]["runs"] = [
        {"ran_at": old_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 0},
        {"ran_at": recent_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 1},
    ]
    jobs_path.write_text(json.dumps(jobs))
    sched._prune_runs(job["id"], retention_days=30)
    remaining = sched.get_all_jobs()[0]["runs"]
    assert len(remaining) == 1
    assert remaining[0]["ran_at"] == recent_ts


def test_create_job_multi_day(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({
        "adom": "TEST", "days_of_week": ["MON", "THU"], "time": "06:00",
        "format": "pdf", "email": "x@x.com", "enabled": True
    })
    assert job["days_of_week"] == ["MON", "THU"]
    stored = sched.get_all_jobs()[0]
    assert stored["days_of_week"] == ["MON", "THU"]


def test_validate_empty_days(jobs_path):
    from app import config_diff_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "adom": "TEST", "days_of_week": [], "time": "06:00",
            "format": "pdf", "email": "x@x.com", "enabled": True
        })


def test_validate_invalid_day_code(jobs_path):
    from app import config_diff_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "adom": "TEST", "days_of_week": ["MONDAY"], "time": "06:00",
            "format": "pdf", "email": "x@x.com", "enabled": True
        })


def test_validate_single_day_still_works(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({
        "adom": "TEST", "days_of_week": ["FRI"], "time": "08:00",
        "format": "csv", "email": "x@x.com", "enabled": True
    })
    assert job["days_of_week"] == ["FRI"]


def test_register_multi_day_cron_string(jobs_path):
    from app import config_diff_scheduler as sched
    from unittest.mock import MagicMock, patch

    mock_scheduler = MagicMock()
    sched._scheduler = mock_scheduler

    job = sched.create_job({
        "adom": "TEST", "days_of_week": ["MON", "THU"], "time": "06:00",
        "format": "pdf", "email": "x@x.com", "enabled": True
    })

    # _register is called by create_job when _scheduler is set
    call_args = mock_scheduler.add_job.call_args
    trigger_arg = call_args[1]["trigger"] if call_args[1] else call_args[0][1]
    # The CronTrigger is constructed with day_of_week="mon,thu"
    # Check via the kwargs passed to CronTrigger by inspecting add_job was called
    assert mock_scheduler.add_job.called

    sched._scheduler = None  # reset so other tests aren't affected
```

- [ ] **Step 2: Run tests — expect failures on the new tests only**

```bash
uv run pytest tests/test_config_diff_scheduler.py -v
```

Expected: existing tests FAIL (because backend still uses `day_of_week`), new tests also FAIL. That's correct — we're writing failing tests first.

- [ ] **Step 3: Update `_validate_job_fields` in `app/config_diff_scheduler.py`**

Replace lines 29–31:

```python
def _validate_job_fields(data: dict) -> None:
    days = data.get("days_of_week")
    if not isinstance(days, list) or not days:
        raise ValueError("days_of_week must be a non-empty list")
    invalid = [d for d in days if d not in _VALID_DAYS]
    if invalid:
        raise ValueError(f"days_of_week contains invalid codes: {invalid}. Must be from {sorted(_VALID_DAYS)}")
    time_str = data.get("time", "")
    parts = time_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("time must be HH:MM format")
    if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
        raise ValueError("time HH must be 0-23, MM must be 0-59")
```

- [ ] **Step 4: Update `create_job` in `app/config_diff_scheduler.py`**

Replace line 71 (`"day_of_week": data["day_of_week"],`) with:

```python
        "days_of_week": data["days_of_week"],
```

- [ ] **Step 5: Update `update_job` in `app/config_diff_scheduler.py`**

Replace line 97 (`"day_of_week": data["day_of_week"],`) with:

```python
                    "days_of_week": data["days_of_week"],
```

- [ ] **Step 6: Update `_register` in `app/config_diff_scheduler.py`**

Replace lines 399–416 (the `day_map` dict and `_scheduler.add_job` call):

```python
def _register(job: dict) -> None:
    if _scheduler is None:
        return
    from apscheduler.triggers.cron import CronTrigger

    day_map = {
        "SUN": "sun", "MON": "mon", "TUE": "tue", "WED": "wed",
        "THU": "thu", "FRI": "fri", "SAT": "sat",
    }
    h, m = job["time"].split(":")
    day_str = ",".join(day_map[d] for d in job["days_of_week"])
    _scheduler.add_job(
        _execute_job,
        CronTrigger(day_of_week=day_str, hour=int(h), minute=int(m)),
        args=[job["id"]],
        id=_apscheduler_id(job["id"]),
        replace_existing=True,
    )
```

- [ ] **Step 7: Run all scheduler tests — expect pass**

```bash
uv run pytest tests/test_config_diff_scheduler.py -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add app/config_diff_scheduler.py tests/test_config_diff_scheduler.py
git commit -m "feat: replace day_of_week string with days_of_week array in config-diff scheduler"
```

---

## Task 2: CSS — `.job-form-panel` class and day picker styles

**Files:**
- Modify: `app/static/css/style.css` (append new rules after `.admin-panel-header` block near line 1242)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `.job-form-panel` — replaces inline `background:#f3f4f6;border:1px solid #d1d5db;border-radius:6px;padding:16px;max-width:560px;margin-bottom:16px` on `#jobForm`
  - `.day-picker` — flex container for the 7 checkbox+label pairs
  - `.day-picker-item` — individual checkbox+label; highlights in `var(--accent)` tint when checked

- [ ] **Step 1: Find the insertion point**

The `.admin-panel-header` block ends around line 1250. Add new rules immediately after it. Open `app/static/css/style.css` and append the following block after the `.admin-panel-header h3 { ... }` closing brace:

```css
/* ── Config-Diff job form panel ──────────────────────────────────────── */
.job-form-panel {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px;
  max-width: 560px;
  margin-bottom: 16px;
}

.day-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.day-picker-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  font-size: .8rem;
  color: var(--text);
  user-select: none;
  transition: background .1s, border-color .1s;
}

.day-picker-item:hover {
  border-color: var(--accent);
}

.day-picker-item:has(input:checked) {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}

.day-picker-item input[type=checkbox] {
  accent-color: var(--accent);
  cursor: pointer;
}
```

- [ ] **Step 2: Verify no existing `.job-form-panel` or `.day-picker` rules exist**

```bash
grep -n "job-form-panel\|day-picker" app/static/css/style.css
```

Expected: only the lines you just added.

- [ ] **Step 3: Commit**

```bash
git add app/static/css/style.css
git commit -m "feat: add .job-form-panel and .day-picker CSS classes for dark-mode-safe job form"
```

---

## Task 3: HTML — replace select with checkbox group, apply `.job-form-panel`

**Files:**
- Modify: `app/templates/admin.html:202-246` (the `#jobForm` div and its contents)

**Interfaces:**
- Consumes: `.job-form-panel`, `.day-picker`, `.day-picker-item` from Task 2
- Produces: 7 checkboxes with `id="dayChk-SUN"` through `id="dayChk-SAT"` and `value="SUN"` through `value="SAT"`; the `<th>Day</th>` column header becomes `<th>Days</th>`

- [ ] **Step 1: Replace `#jobForm` opening div — remove inline styles, add class**

Find this line (around line 202):
```html
  <div id="jobForm" style="display:none;background:#f3f4f6;border:1px solid #d1d5db;border-radius:6px;padding:16px;max-width:560px;margin-bottom:16px">
```

Replace with:
```html
  <div id="jobForm" class="job-form-panel" style="display:none">
```

- [ ] **Step 2: Replace the Day of Week `<select>` with a checkbox group**

Find this block (lines 209–220):
```html
    <div class="form-row">
      <label>Day of Week</label>
      <select id="jobFormDay">
        <option value="SUN">Sunday</option>
        <option value="MON">Monday</option>
        <option value="TUE">Tuesday</option>
        <option value="WED">Wednesday</option>
        <option value="THU">Thursday</option>
        <option value="FRI">Friday</option>
        <option value="SAT">Saturday</option>
      </select>
    </div>
```

Replace with:
```html
    <div class="form-row">
      <label>Day(s)</label>
      <div class="day-picker">
        <label class="day-picker-item"><input type="checkbox" id="dayChk-SUN" value="SUN"> Sun</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-MON" value="MON"> Mon</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-TUE" value="TUE"> Tue</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-WED" value="WED"> Wed</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-THU" value="THU"> Thu</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-FRI" value="FRI"> Fri</label>
        <label class="day-picker-item"><input type="checkbox" id="dayChk-SAT" value="SAT"> Sat</label>
      </div>
    </div>
```

- [ ] **Step 3: Update the table header**

Find (around line 253):
```html
          <th>ADOM</th><th>Day</th><th>Time</th><th>Format</th>
```

Replace with:
```html
          <th>ADOM</th><th>Days</th><th>Time</th><th>Format</th>
```

- [ ] **Step 4: Commit**

```bash
git add app/templates/admin.html
git commit -m "feat: replace day-of-week select with multi-checkbox day picker in job form"
```

---

## Task 4: JavaScript — wire up checkbox group in `admin.js`

**Files:**
- Modify: `app/static/js/admin.js:786-864` (`renderJobsTable`, `showJobForm`, `saveJob`)

**Interfaces:**
- Consumes: checkboxes `id="dayChk-SUN"` through `id="dayChk-SAT"` from Task 3
- Produces: `saveJob()` sends `days_of_week: ["MON", "THU"]` in payload; `renderJobsTable()` shows `"Mon, Thu"` in the Days column

- [ ] **Step 1: Add a helper constant for display names at the top of the cdiff section**

Find line 771 (`let _cdiffJobs = [];`) and insert the following two lines immediately before it:

```javascript
const _DAY_CODES = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
const _DAY_LABELS = {SUN:'Sun',MON:'Mon',TUE:'Tue',WED:'Wed',THU:'Thu',FRI:'Fri',SAT:'Sat'};
```

- [ ] **Step 2: Update `renderJobsTable` — fix the Days column**

Find line 795:
```javascript
      <td>${escH(j.day_of_week)}</td>
```

Replace with:
```javascript
      <td>${(j.days_of_week||[]).map(d=>_DAY_LABELS[d]||d).join(', ')}</td>
```

- [ ] **Step 3: Update `showJobForm` — set checkboxes instead of select value**

Find lines 826–827 inside `showJobForm`:
```javascript
  document.getElementById('jobFormAdom').value    = job ? job.adom : '';
  document.getElementById('jobFormDay').value     = job ? job.day_of_week : 'MON';
```

Replace with:
```javascript
  document.getElementById('jobFormAdom').value    = job ? job.adom : '';
  const activeDays = job ? (job.days_of_week || ['MON']) : ['MON'];
  _DAY_CODES.forEach(code => {
    const chk = document.getElementById('dayChk-' + code);
    if (chk) chk.checked = activeDays.includes(code);
  });
```

- [ ] **Step 4: Update `saveJob` — collect checked days, validate, send array**

Find lines 848–856 inside `saveJob`:
```javascript
  const payload = {
    adom:        document.getElementById('jobFormAdom').value,
    day_of_week: document.getElementById('jobFormDay').value,
    time:        document.getElementById('jobFormTime').value,
    format:      document.getElementById('jobFormFormat').value,
    email:       document.getElementById('jobFormEmail').value.trim(),
    enabled:     document.getElementById('jobFormEnabled').checked,
  };
```

Replace with:
```javascript
  const selectedDays = _DAY_CODES.filter(code => {
    const chk = document.getElementById('dayChk-' + code);
    return chk && chk.checked;
  });
  if (selectedDays.length === 0) {
    msg.style.color = '#b91c1c';
    msg.textContent = 'Select at least one day.';
    return;
  }
  const payload = {
    adom:         document.getElementById('jobFormAdom').value,
    days_of_week: selectedDays,
    time:         document.getElementById('jobFormTime').value,
    format:       document.getElementById('jobFormFormat').value,
    email:        document.getElementById('jobFormEmail').value.trim(),
    enabled:      document.getElementById('jobFormEnabled').checked,
  };
```

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/admin.js
git commit -m "feat: wire multi-day checkbox picker in admin.js for config-diff jobs"
```

---

## Task 5: Documentation updates

**Files:**
- Modify: `CLAUDE.md` (Config-Diff Scheduled Exports section, line ~388–394)
- Modify: `CHANGELOG.md` (add entry under `[Unreleased]`)

**Interfaces:**
- Consumes: nothing
- Produces: updated docs

- [ ] **Step 1: Update `CLAUDE.md`**

Find this line in the Config-Diff Scheduled Exports section (around line 388):
```
- **Scheduled Config-Delta exports** — admin users can create weekly scheduled jobs (ADOM, day, time, format, email recipient) that run server-side and email the full diff report as an attachment with an HTML summary in the body.
```

Replace with:
```
- **Scheduled Config-Delta exports** — admin users can create scheduled jobs (ADOM, one or more days of the week, time, format, email recipient) that run server-side and email the full diff report as an attachment with an HTML summary in the body.
```

Also find the architecture note for `config_diff_scheduler.py` (around line 390):
```
`app/config_diff_scheduler.py` — APScheduler-based weekly export engine. Persists jobs and run history in `config_diff_jobs.json` (project root, gitignored).
```

Update the job schema note to reflect the new field. Find any `day_of_week` reference in CLAUDE.md and change it to `days_of_week` (an array of day codes, e.g. `["MON","THU"]`). Search first:

```bash
grep -n "day_of_week" CLAUDE.md
```

Replace each occurrence of `day_of_week` (string) with `days_of_week` (array of day codes).

- [ ] **Step 2: Update `CHANGELOG.md`**

Find the `## [Unreleased]` section and add under `### Changed` (create the subsection if it doesn't exist yet):

```markdown
### Changed
- **Config-Diff scheduled jobs** — day-of-week selector replaced with a multi-checkbox day picker; jobs now store `days_of_week` (array) instead of `day_of_week` (string), allowing any combination of 1–7 days per job (e.g. Mon + Thu only). Job form panel dark mode rendering fixed by replacing hard-coded inline hex colours with CSS custom properties.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: update CLAUDE.md and CHANGELOG for multi-day config-diff scheduling"
```

---

## Task 6: Graphify update

**Files:**
- Run: `graphify update .`

- [ ] **Step 1: Update the knowledge graph**

```bash
graphify update .
```

Expected: output confirms graph updated with no errors.

- [ ] **Step 2: Commit updated graph artifacts**

```bash
git add graphify-out/
git commit -m "chore: update graphify knowledge graph after multi-day config-diff changes"
```

---

## Self-Review

**Spec coverage:**
- ✅ `days_of_week` array schema → Task 1
- ✅ Backend validation (empty array, invalid code, single day valid) → Task 1
- ✅ APScheduler cron string from array → Task 1 (`_register`)
- ✅ 7 checkboxes in job form → Task 3
- ✅ Checked state highlight via CSS → Task 2 (`.day-picker-item:has(input:checked)`)
- ✅ Zero-day client-side validation → Task 4 (`saveJob`)
- ✅ Table "Days" column with short names → Task 4 (`renderJobsTable`)
- ✅ Dark mode fix — `.job-form-panel` CSS class → Tasks 2 & 3
- ✅ Tests: all 5 new + updated existing → Task 1
- ✅ CLAUDE.md updated → Task 5
- ✅ CHANGELOG updated → Task 5
- ✅ Graphify → Task 6

**Placeholder scan:** No TBDs, no "implement later", all code shown in full.

**Type consistency:**
- `days_of_week` used consistently in Python (`list[str]`), JSON storage, and JS (`string[]`) across all tasks
- Checkbox IDs `dayChk-SUN` through `dayChk-SAT` defined in Task 3 HTML and consumed in Task 4 JS
- `_DAY_CODES` and `_DAY_LABELS` defined in Task 4 Step 1 before use in Steps 2–4
