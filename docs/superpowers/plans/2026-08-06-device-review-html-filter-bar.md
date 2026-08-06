# Device Review HTML Report — Findings Filter Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sticky filter bar above the Findings table in Device Review HTML reports so users can isolate results by type (FAIL, INSECURE, etc.) and/or by host with a single click.

**Architecture:** All changes are confined to `app/device_review_scheduler.py`. Two new module-level string constants (`_REPORT_CSS`, `_REPORT_JS`) hold the filter bar styles and vanilla JS logic. `_build_pdf_html_dr()` is updated to inject those constants, add `data-result`/`data-device` attributes to finding `<tr>` tags, and render the filter bar HTML above the Findings section. No other files change.

**Tech Stack:** Python f-strings, vanilla JS (ES5-compatible), inline CSS — zero new dependencies.

## Global Constraints

- Branch: `development`
- Only `app/device_review_scheduler.py` and `tests/test_device_review_scheduler.py` change.
- No external JS/CSS libraries. The HTML file must be fully self-contained (no CDN links).
- All user-supplied strings inserted into HTML must pass through `_esc()`.
- Run tests with: `uv run pytest tests/test_device_review_scheduler.py -v`

---

### Task 1: Add `data-result` and `data-device` attributes to Findings rows

**Files:**
- Modify: `app/device_review_scheduler.py:672-686` (the `rows_html` loop inside `_build_pdf_html_dr`)
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: existing `_build_pdf_html_dr(adom, results, generated_at, check_summary)` — no signature change
- Produces: HTML `<tr>` tags now carry `data-result="<RESULT>"` and `data-device="<device name>"` attributes; consumed by Task 2's JS

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_device_review_scheduler.py`:

```python
def test_findings_rows_have_data_attributes():
    """Each findings <tr> has data-result and data-device attributes."""
    from app.device_review_scheduler import _build_pdf_html_dr
    results = [
        {"device": "fw-01", "rows": [
            {"device": "fw-01", "check": "NTP", "result": "FAIL",
             "interface": "system", "vdom": "root", "ip": "", "detail": "no ntp",
             "protocols": [], "has_insecure": False, "has_secure": False},
        ], "error": None},
        {"device": "fw-02", "rows": [
            {"device": "fw-02", "check": "Interface Protocols", "result": "INSECURE",
             "interface": "mgmt", "vdom": "root", "ip": "10.0.0.1/24", "detail": "",
             "protocols": [{"name": "http", "secure": False}],
             "has_insecure": True, "has_secure": False},
        ], "error": None},
    ]
    html = _build_pdf_html_dr("Corp", results, "2026-08-06T00:00:00Z", [])
    assert 'data-result="FAIL"' in html
    assert 'data-result="INSECURE"' in html
    assert 'data-device="fw-01"' in html
    assert 'data-device="fw-02"' in html
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_findings_rows_have_data_attributes -v
```

Expected: FAIL — `data-result` and `data-device` not yet present in HTML output.

- [ ] **Step 3: Update the findings row loop in `_build_pdf_html_dr`**

In `app/device_review_scheduler.py`, find the `rows_html` loop (lines ~673–686) and change the `<tr>` opening tag:

Old:
```python
    rows_html = ""
    for row in all_rows:
        color = _RESULT_COLOR.get(row.get("result", ""), "#374151")
        rows_html += (
            f"<tr>"
```

New:
```python
    rows_html = ""
    for row in all_rows:
        color = _RESULT_COLOR.get(row.get("result", ""), "#374151")
        result_val = _esc(row.get("result", ""))
        device_val = _esc(row.get("device", ""))
        rows_html += (
            f'<tr data-result="{result_val}" data-device="{device_val}">'
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_findings_rows_have_data_attributes -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat: add data-result and data-device attributes to HTML findings rows"
```

---

### Task 2: Add `_REPORT_CSS` and `_REPORT_JS` module-level constants

**Files:**
- Modify: `app/device_review_scheduler.py` — add two new module-level string constants after the `_CHECK_SUMMARY_RESULTS` line (~line 354)
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Produces:
  - `_REPORT_CSS: str` — CSS for the filter bar (sticky positioning, button styles, active state, host select, row counter span)
  - `_REPORT_JS: str` — JS defining `filterFindings()` and wiring click/change events on `DOMContentLoaded`
  - Both are injected into `_build_pdf_html_dr()` in Task 3

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_device_review_scheduler.py`:

```python
def test_report_css_constant_exists():
    """_REPORT_CSS module constant is a non-empty string."""
    import app.device_review_scheduler as sched
    assert isinstance(sched._REPORT_CSS, str)
    assert len(sched._REPORT_CSS) > 0


def test_report_js_constant_exists():
    """_REPORT_JS module constant is a non-empty string."""
    import app.device_review_scheduler as sched
    assert isinstance(sched._REPORT_JS, str)
    assert len(sched._REPORT_JS) > 0


def test_report_js_defines_filter_function():
    """_REPORT_JS contains the filterFindings function definition."""
    import app.device_review_scheduler as sched
    assert "filterFindings" in sched._REPORT_JS


def test_report_js_handles_all_result_filter():
    """_REPORT_JS contains logic to handle the ALL result filter."""
    import app.device_review_scheduler as sched
    assert "ALL" in sched._REPORT_JS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_report_css_constant_exists tests/test_device_review_scheduler.py::test_report_js_constant_exists tests/test_device_review_scheduler.py::test_report_js_defines_filter_function tests/test_device_review_scheduler.py::test_report_js_handles_all_result_filter -v
```

Expected: all four FAIL — constants don't exist yet.

- [ ] **Step 3: Add the constants to `device_review_scheduler.py`**

Insert after the `_CHECK_SUMMARY_RESULTS = (...)` line (around line 354):

```python
_REPORT_CSS = """
#dr-filter-bar {
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 10;
  padding: 8px 0 10px 0;
  border-bottom: 1px solid #e5e7eb;
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.dr-result-btn {
  border: 1px solid #d1d5db;
  background: #f9fafb;
  border-radius: 4px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  color: #374151;
}
.dr-result-btn.active {
  border-color: #6b7280;
  background: #e5e7eb;
  color: #111827;
}
.dr-result-btn[data-result="FAIL"].active,
.dr-result-btn[data-result="INSECURE"].active { background:#fee2e2; border-color:#991b1b; color:#991b1b; }
.dr-result-btn[data-result="WARN"].active,
.dr-result-btn[data-result="CONFIG_MISSING"].active { background:#fef3c7; border-color:#92400e; color:#92400e; }
.dr-result-btn[data-result="PASS"].active { background:#dcfce7; border-color:#166534; color:#166534; }
.dr-result-btn[data-result="INFO"].active { background:#dbeafe; border-color:#1e40af; color:#1e40af; }
#dr-host-select {
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11px;
  background: #f9fafb;
  color: #374151;
  cursor: pointer;
}
#dr-row-count {
  font-size: 11px;
  color: #6b7280;
  margin-left: 8px;
}
"""

_REPORT_JS = """
(function() {
  var activeResult = 'ALL';

  function filterFindings() {
    var hostSelect = document.getElementById('dr-host-select');
    var activeHost = hostSelect ? hostSelect.value : 'ALL';
    var rows = document.querySelectorAll('#dr-findings-tbody tr');
    var shown = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var resultMatch = (activeResult === 'ALL') || (r.getAttribute('data-result') === activeResult);
      var hostMatch = (activeHost === 'ALL') || (r.getAttribute('data-device') === activeHost);
      if (resultMatch && hostMatch) {
        r.style.display = '';
        shown++;
      } else {
        r.style.display = 'none';
      }
    }
    var counter = document.getElementById('dr-row-count');
    if (counter) {
      counter.textContent = 'Showing ' + shown + ' of ' + rows.length + ' findings';
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    var buttons = document.querySelectorAll('.dr-result-btn');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function() {
        for (var j = 0; j < buttons.length; j++) {
          buttons[j].classList.remove('active');
        }
        this.classList.add('active');
        activeResult = this.getAttribute('data-result');
        var hostSelect = document.getElementById('dr-host-select');
        if (hostSelect) hostSelect.value = 'ALL';
        filterFindings();
      });
    }
    var hostSelect = document.getElementById('dr-host-select');
    if (hostSelect) {
      hostSelect.addEventListener('change', filterFindings);
    }
    filterFindings();
  });
})();
"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_report_css_constant_exists tests/test_device_review_scheduler.py::test_report_js_constant_exists tests/test_device_review_scheduler.py::test_report_js_defines_filter_function tests/test_device_review_scheduler.py::test_report_js_handles_all_result_filter -v
```

Expected: all four PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat: add _REPORT_CSS and _REPORT_JS constants for HTML filter bar"
```

---

### Task 3: Inject filter bar into `_build_pdf_html_dr` and wire into HTML output

**Files:**
- Modify: `app/device_review_scheduler.py:667-799` (`_build_pdf_html_dr` function)
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: `_REPORT_CSS` and `_REPORT_JS` from Task 2; `data-result`/`data-device` `<tr>` attributes from Task 1
- Produces: `_build_pdf_html_dr()` returns HTML that includes:
  - `_REPORT_CSS` injected into the `<style>` block
  - `_REPORT_JS` injected as a `<script>` block before `</body>`
  - A filter bar `<div id="dr-filter-bar">` with result buttons and host dropdown immediately before the `<h2>Findings</h2>` heading
  - `id="dr-findings-tbody"` on the findings `<tbody>`
  - Host dropdown `<option>` entries auto-generated from the unique device names in `all_rows`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_device_review_scheduler.py`:

```python
def _make_multi_host_results():
    return [
        {"device": "fw-alpha", "rows": [
            {"device": "fw-alpha", "check": "NTP", "result": "FAIL",
             "interface": "system", "vdom": "root", "ip": "", "detail": "no ntp",
             "protocols": [], "has_insecure": False, "has_secure": False},
            {"device": "fw-alpha", "check": "Interface Protocols", "result": "PASS",
             "interface": "mgmt", "vdom": "root", "ip": "10.0.0.1/24", "detail": "",
             "protocols": [], "has_insecure": False, "has_secure": True},
        ], "error": None},
        {"device": "fw-beta", "rows": [
            {"device": "fw-beta", "check": "NTP", "result": "INSECURE",
             "interface": "system", "vdom": "root", "ip": "", "detail": "bad ntp",
             "protocols": [], "has_insecure": True, "has_secure": False},
        ], "error": None},
    ]


def test_html_report_has_filter_bar():
    """HTML report contains the filter bar div."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert 'id="dr-filter-bar"' in html


def test_html_report_filter_bar_has_result_buttons():
    """Filter bar contains a button for each result type plus ALL."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    for result in ("ALL", "FAIL", "INSECURE", "WARN", "CONFIG_MISSING", "PASS", "INFO"):
        assert f'data-result="{result}"' in html


def test_html_report_filter_bar_has_host_dropdown():
    """Filter bar contains a host dropdown with device names as options."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert 'id="dr-host-select"' in html
    assert 'value="fw-alpha"' in html
    assert 'value="fw-beta"' in html


def test_html_report_filter_bar_has_all_hosts_option():
    """Host dropdown includes an 'All Hosts' default option."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert "All Hosts" in html


def test_html_report_findings_tbody_has_id():
    """Findings tbody has id='dr-findings-tbody' for JS targeting."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert 'id="dr-findings-tbody"' in html


def test_html_report_has_row_count_span():
    """HTML report contains the row count indicator span."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert 'id="dr-row-count"' in html


def test_html_report_filter_bar_before_findings():
    """Filter bar appears in the HTML before the Findings table."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert html.index('id="dr-filter-bar"') < html.index(">Findings<")


def test_html_report_css_injected():
    """_REPORT_CSS content is present in the <style> block."""
    from app.device_review_scheduler import _build_pdf_html_dr, _REPORT_CSS
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert "dr-filter-bar" in html
    assert "dr-result-btn" in html


def test_html_report_js_injected():
    """_REPORT_JS content is present in the output HTML."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert "filterFindings" in html


def test_html_report_host_options_sorted_alphabetically():
    """Host dropdown options are sorted alphabetically."""
    from app.device_review_scheduler import _build_pdf_html_dr
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert html.index('value="fw-alpha"') < html.index('value="fw-beta"')


def test_html_report_no_duplicate_host_options():
    """Each device appears exactly once in the host dropdown even if it has multiple rows."""
    from app.device_review_scheduler import _build_pdf_html_dr
    # fw-alpha has 2 rows — should still appear once in the dropdown
    html = _build_pdf_html_dr("Corp", _make_multi_host_results(), "2026-08-06T00:00:00Z", [])
    assert html.count('value="fw-alpha"') == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_html_report_has_filter_bar tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_result_buttons tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_host_dropdown tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_all_hosts_option tests/test_device_review_scheduler.py::test_html_report_findings_tbody_has_id tests/test_device_review_scheduler.py::test_html_report_has_row_count_span tests/test_device_review_scheduler.py::test_html_report_filter_bar_before_findings tests/test_device_review_scheduler.py::test_html_report_css_injected tests/test_device_review_scheduler.py::test_html_report_js_injected tests/test_device_review_scheduler.py::test_html_report_host_options_sorted_alphabetically tests/test_device_review_scheduler.py::test_html_report_no_duplicate_host_options -v
```

Expected: all FAIL.

- [ ] **Step 3: Update `_build_pdf_html_dr` to inject filter bar, CSS, JS**

In `app/device_review_scheduler.py`, update `_build_pdf_html_dr` as follows:

**3a.** Build the host dropdown options from `all_rows` (add after the `all_rows` assignment):

```python
    # Build sorted unique device list for host dropdown
    unique_devices = sorted({row.get("device", "") for row in all_rows if row.get("device")})
    host_options = '<option value="ALL">All Hosts</option>\n'
    for dev in unique_devices:
        host_options += f'<option value="{_esc(dev)}">{_esc(dev)}</option>\n'
```

**3b.** Build the result filter buttons:

```python
    result_buttons = '<button class="dr-result-btn active" data-result="ALL">ALL</button>\n'
    for res in ("FAIL", "INSECURE", "WARN", "CONFIG_MISSING", "PASS", "INFO"):
        result_buttons += f'<button class="dr-result-btn" data-result="{res}">{res}</button>\n'
```

**3c.** In the returned f-string, add `{_REPORT_CSS}` inside the `<style>` block:

```python
<style>
  body{{font-family:sans-serif;font-size:12px;color:#111}}
  h1{{font-size:18px;margin-bottom:4px}}
  h2{{font-size:14px;margin-top:24px;margin-bottom:6px}}
  .meta{{color:#6b7280;margin-bottom:16px;font-size:11px}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
  th,td{{border:1px solid #e5e7eb;padding:4px 8px;text-align:left}}
  th{{background:#f3f4f6;font-weight:600}}
  tr:nth-child(even){{background:#fafafa}}
  {_REPORT_CSS}
</style>
```

**3d.** Replace the `<h2>Findings</h2>` block with the filter bar + heading:

```python
<div id="dr-filter-bar">
  {result_buttons}
  <select id="dr-host-select">{host_options}</select>
  <span id="dr-row-count"></span>
</div>
<h2>Findings</h2>
```

**3e.** Add `id="dr-findings-tbody"` to the findings `<tbody>`:

```python
  <tbody id="dr-findings-tbody">{rows_html}</tbody>
```

**3f.** Add the script block before `</body>`:

```python
<script>{_REPORT_JS}</script>
</body>
</html>
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_html_report_has_filter_bar tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_result_buttons tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_host_dropdown tests/test_device_review_scheduler.py::test_html_report_filter_bar_has_all_hosts_option tests/test_device_review_scheduler.py::test_html_report_findings_tbody_has_id tests/test_device_review_scheduler.py::test_html_report_has_row_count_span tests/test_device_review_scheduler.py::test_html_report_filter_bar_before_findings tests/test_device_review_scheduler.py::test_html_report_css_injected tests/test_device_review_scheduler.py::test_html_report_js_injected tests/test_device_review_scheduler.py::test_html_report_host_options_sorted_alphabetically tests/test_device_review_scheduler.py::test_html_report_no_duplicate_host_options -v
```

Expected: all PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat: inject filter bar into Device Review HTML report"
```
