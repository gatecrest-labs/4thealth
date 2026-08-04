# Device Review Check Summary Section — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-check summary section (check name, description, PASS/INFO/WARN/CONFIG_MISSING/FAIL/INSECURE counts) above the host summary in every Device Review scheduled report format.

**Architecture:** A new `_build_check_summary` helper computes the aggregation once in `_execute_job` and its result is threaded through to all four report builders (email body, HTML/PDF attachment, CSV, JSON). The existing 4-column collapsed check table in the email body is replaced with the full 6-column version.

**Tech Stack:** Python 3, `app/device_review_scheduler.py`, `app/device_review.py` (source of `CHECKS_META`), pytest.

## Global Constraints

- All changes on the `development` branch.
- Only `app/device_review_scheduler.py` and `tests/test_device_review_scheduler.py` are modified.
- No changes to templates, routes, or any other file.
- Column order throughout: PASS | INFO | WARN | CONFIG_MISSING | FAIL | INSECURE.
- `checks_ran = []` means all checks were run (matches the existing convention in `_execute_job`).
- Use `uv run pytest` to run tests.

---

## File Map

| File | Change |
|---|---|
| `app/device_review_scheduler.py` | Add `_build_check_summary`; update `_build_summary_html`, `_build_pdf_html_dr`, `_build_attachment_dr`, `_execute_job` |
| `tests/test_device_review_scheduler.py` | Add new tests; update existing tests that call the modified functions |

---

## Task 1: Add `_build_check_summary` helper

**Files:**
- Modify: `app/device_review_scheduler.py` — add helper after `_build_host_summary_html`
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Produces: `_build_check_summary(results: list[dict], checks_ran: list[str]) -> list[dict]`
  - Each returned dict: `{"key": str, "name": str, "description": str, "PASS": int, "INFO": int, "WARN": int, "CONFIG_MISSING": int, "FAIL": int, "INSECURE": int}`
  - Ordered by `CHECKS_META` declaration order
  - Filtered to `checks_ran`; if `checks_ran` is empty, all checks are included
  - Checks in `checks_ran` that are absent from results still appear with all-zero counts

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_device_review_scheduler.py`:

```python
# ── _build_check_summary ──────────────────────────────────────────────────────

def test_check_summary_counts_all_result_types(monkeypatch):
    """Each result type gets its own count; no collapsing."""
    import app.device_review_scheduler as sched
    fake_meta = [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP servers"},
        {"key": "syslog_config", "name": "Syslog Configuration", "description": "Check syslog"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)
    results = [{"device": "FW1", "rows": [
        {"check": "NTP Configuration", "result": "PASS"},
        {"check": "NTP Configuration", "result": "FAIL"},
        {"check": "NTP Configuration", "result": "INSECURE"},
        {"check": "NTP Configuration", "result": "WARN"},
        {"check": "NTP Configuration", "result": "CONFIG_MISSING"},
        {"check": "NTP Configuration", "result": "INFO"},
        {"check": "Syslog Configuration", "result": "PASS"},
    ]}]
    summary = sched._build_check_summary(results, [])
    ntp = next(c for c in summary if c["key"] == "ntp_config")
    assert ntp["PASS"] == 1
    assert ntp["FAIL"] == 1
    assert ntp["INSECURE"] == 1
    assert ntp["WARN"] == 1
    assert ntp["CONFIG_MISSING"] == 1
    assert ntp["INFO"] == 1
    syslog = next(c for c in summary if c["key"] == "syslog_config")
    assert syslog["PASS"] == 1


def test_check_summary_filters_to_checks_ran(monkeypatch):
    """Only checks in checks_ran appear when checks_ran is non-empty."""
    import app.device_review_scheduler as sched
    fake_meta = [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP"},
        {"key": "syslog_config", "name": "Syslog Configuration", "description": "Check syslog"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)
    results = [{"device": "FW1", "rows": [
        {"check": "NTP Configuration", "result": "PASS"},
        {"check": "Syslog Configuration", "result": "FAIL"},
    ]}]
    summary = sched._build_check_summary(results, ["ntp_config"])
    assert len(summary) == 1
    assert summary[0]["key"] == "ntp_config"


def test_check_summary_empty_checks_ran_means_all(monkeypatch):
    """Empty checks_ran includes all checks from CHECKS_META."""
    import app.device_review_scheduler as sched
    fake_meta = [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP"},
        {"key": "syslog_config", "name": "Syslog Configuration", "description": "Check syslog"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)
    results = []
    summary = sched._build_check_summary(results, [])
    assert len(summary) == 2


def test_check_summary_zero_counts_for_unmatched_check(monkeypatch):
    """A check that ran but produced no rows still appears with all-zero counts."""
    import app.device_review_scheduler as sched
    fake_meta = [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)
    results = [{"device": "FW1", "rows": []}]
    summary = sched._build_check_summary(results, ["ntp_config"])
    assert summary[0]["PASS"] == 0
    assert summary[0]["FAIL"] == 0


def test_check_summary_preserves_checks_meta_order(monkeypatch):
    """Output order matches CHECKS_META declaration order, not row order."""
    import app.device_review_scheduler as sched
    fake_meta = [
        {"key": "aaa", "name": "AAA Check", "description": "first"},
        {"key": "bbb", "name": "BBB Check", "description": "second"},
        {"key": "ccc", "name": "CCC Check", "description": "third"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)
    results = [{"device": "FW1", "rows": [
        {"check": "CCC Check", "result": "PASS"},
        {"check": "AAA Check", "result": "PASS"},
    ]}]
    summary = sched._build_check_summary(results, [])
    assert [c["key"] for c in summary] == ["aaa", "bbb", "ccc"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_check_summary_counts_all_result_types tests/test_device_review_scheduler.py::test_check_summary_filters_to_checks_ran tests/test_device_review_scheduler.py::test_check_summary_empty_checks_ran_means_all tests/test_device_review_scheduler.py::test_check_summary_zero_counts_for_unmatched_check tests/test_device_review_scheduler.py::test_check_summary_preserves_checks_meta_order -v
```

Expected: all FAIL with `AttributeError: module has no attribute '_build_check_summary'` or similar.

- [ ] **Step 3: Add module-level `_CHECKS_META` alias and implement `_build_check_summary`**

In `app/device_review_scheduler.py`, add after the existing `_SUMMARY_RESULTS` line (line 340):

```python
# Lazy alias — avoids a top-level circular import while still being monkeypatchable in tests.
def _get_checks_meta():
    from app.device_review import CHECKS_META
    return CHECKS_META
```

And after `_build_host_summary_html` (before `_build_summary_html`), add:

```python
_CHECK_SUMMARY_RESULTS = ("PASS", "INFO", "WARN", "CONFIG_MISSING", "FAIL", "INSECURE")


def _build_check_summary(results: list[dict], checks_ran: list[str]) -> list[dict]:
    """Return per-check result counts ordered by CHECKS_META declaration order.

    checks_ran: list of check keys that were run; empty means all checks.
    Each entry: {key, name, description, PASS, INFO, WARN, CONFIG_MISSING, FAIL, INSECURE}
    """
    checks_meta = _CHECKS_META if _CHECKS_META is not None else _get_checks_meta()
    active_keys = set(checks_ran) if checks_ran else {c["key"] for c in checks_meta}
    # Build name→key lookup for matching row["check"] (display name) back to key
    name_to_key = {c["name"]: c["key"] for c in checks_meta}
    # Aggregate by check key
    by_key: dict[str, dict] = {}
    for dev in results:
        for row in dev.get("rows", []):
            check_name = row.get("check", "")
            key = name_to_key.get(check_name)
            if key is None or key not in active_keys:
                continue
            if key not in by_key:
                by_key[key] = {r: 0 for r in _CHECK_SUMMARY_RESULTS}
            result = row.get("result", "")
            if result in by_key[key]:
                by_key[key][result] += 1
    # Build output in CHECKS_META order, filtered to active_keys
    output = []
    for c in checks_meta:
        if c["key"] not in active_keys:
            continue
        counts = by_key.get(c["key"], {r: 0 for r in _CHECK_SUMMARY_RESULTS})
        output.append({
            "key": c["key"],
            "name": c["name"],
            "description": c.get("description", ""),
            **counts,
        })
    return output
```

Also add this near the top of the module (after `_SUMMARY_RESULTS`), so monkeypatching works:

```python
_CHECKS_META = None  # populated lazily; tests may monkeypatch this directly
```

> **Note:** The monkeypatch in tests sets `app.device_review_scheduler._CHECKS_META` to a fake list. The implementation checks `if _CHECKS_META is not None` first, then falls back to the lazy import.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_check_summary_counts_all_result_types tests/test_device_review_scheduler.py::test_check_summary_filters_to_checks_ran tests/test_device_review_scheduler.py::test_check_summary_empty_checks_ran_means_all tests/test_device_review_scheduler.py::test_check_summary_zero_counts_for_unmatched_check tests/test_device_review_scheduler.py::test_check_summary_preserves_checks_meta_order -v
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review): add _build_check_summary helper with per-check result counts"
```

---

## Task 2: Update email body — `_build_summary_html`

**Files:**
- Modify: `app/device_review_scheduler.py:410-466`
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: `_build_check_summary(results, checks_ran) -> list[dict]` (from Task 1)
- Produces: `_build_summary_html(adom, results, generated_at, check_summary)` — new `check_summary` parameter; check summary table rendered above host summary; 6 columns

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_device_review_scheduler.py`:

```python
# ── _build_summary_html check summary section ─────────────────────────────────

def _make_check_summary_fixture():
    return [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP servers",
         "PASS": 3, "INFO": 0, "WARN": 1, "CONFIG_MISSING": 0, "FAIL": 1, "INSECURE": 0},
        {"key": "interface_protocols", "name": "Interface Protocols", "description": "Cleartext check",
         "PASS": 0, "INFO": 2, "WARN": 0, "CONFIG_MISSING": 0, "FAIL": 0, "INSECURE": 1},
    ]


def test_summary_html_check_summary_above_host_summary():
    """Check Summary section appears before Host Summary in email body."""
    from app.device_review_scheduler import _build_summary_html
    results = [{"device": "FW1", "rows": [{"result": "PASS", "check": "NTP Configuration"}]}]
    html = _build_summary_html("ADOM", results, "2026-08-04T00:00:00Z", _make_check_summary_fixture())
    assert "Check Summary" in html
    assert "Host Summary" in html
    assert html.index("Check Summary") < html.index("Host Summary")


def test_summary_html_check_summary_has_6_columns():
    """Check summary table has all 6 result-type columns."""
    from app.device_review_scheduler import _build_summary_html
    results = []
    html = _build_summary_html("ADOM", results, "2026-08-04T00:00:00Z", _make_check_summary_fixture())
    for col in ("PASS", "INFO", "WARN", "CONFIG_MISSING", "FAIL", "INSECURE"):
        assert col in html


def test_summary_html_check_summary_shows_description():
    """Check summary table includes the check description."""
    from app.device_review_scheduler import _build_summary_html
    results = []
    html = _build_summary_html("ADOM", results, "2026-08-04T00:00:00Z", _make_check_summary_fixture())
    assert "Check NTP servers" in html
    assert "Cleartext check" in html


def test_summary_html_check_summary_shows_counts():
    """Check summary table renders non-zero counts."""
    from app.device_review_scheduler import _build_summary_html
    results = []
    html = _build_summary_html("ADOM", results, "2026-08-04T00:00:00Z", _make_check_summary_fixture())
    # NTP row: PASS=3, WARN=1, FAIL=1
    assert ">3<" in html
    # Interface Protocols: INSECURE=1, INFO=2
    assert ">2<" in html
    assert ">1<" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_summary_html_check_summary_above_host_summary tests/test_device_review_scheduler.py::test_summary_html_check_summary_has_6_columns tests/test_device_review_scheduler.py::test_summary_html_check_summary_shows_description tests/test_device_review_scheduler.py::test_summary_html_check_summary_shows_counts -v
```

Expected: FAIL — `_build_summary_html` does not yet accept a `check_summary` parameter.

- [ ] **Step 3: Rewrite `_build_summary_html`**

Replace the entire `_build_summary_html` function (lines 410–466) with:

```python
def _build_summary_html(
    adom: str,
    results: list[dict],
    generated_at: str,
    check_summary: list[dict],
) -> str:
    errors = [d.get("device", "unknown") for d in results if d.get("error")]
    error_note = ""
    if errors:
        error_note = (
            f"<p style='font-family:sans-serif;color:#991b1b'>"
            f"Errors on devices: {', '.join(_esc(e) for e in errors)}</p>"
        )

    # ── Check Summary table ───────────────────────────────────────────────────
    check_rows_html = ""
    for entry in check_summary:
        cells = "".join(
            "<td style='padding:4px 8px;text-align:center;color:{c}'>{v}</td>".format(
                c=_RESULT_COLOR.get(r, "#374151"), v=entry[r]
            )
            for r in _CHECK_SUMMARY_RESULTS
        )
        check_rows_html += (
            f"<tr>"
            f"<td style='padding:4px 8px'>{_esc(entry['name'])}</td>"
            f"<td style='padding:4px 8px;color:#6b7280;font-size:12px'>{_esc(entry['description'])}</td>"
            f"{cells}"
            f"</tr>\n"
        )
    check_header_cells = "".join(
        f"<th style='padding:4px 8px'>{r}</th>" for r in _CHECK_SUMMARY_RESULTS
    )
    check_summary_html = (
        f"<h3 style='font-family:sans-serif;margin-top:24px'>Check Summary</h3>"
        f"<table style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
        f"<thead><tr style='background:#f3f4f6'>"
        f"<th style='padding:4px 8px;text-align:left'>Check</th>"
        f"<th style='padding:4px 8px;text-align:left'>Description</th>"
        f"{check_header_cells}"
        f"</tr></thead>"
        f"<tbody>{check_rows_html}</tbody>"
        f"</table>"
    )

    host_summary_html = _build_host_summary_html(results)

    return f"""
<h2 style="font-family:sans-serif">4THealth Device Review — {_esc(adom)}</h2>
<p style="font-family:sans-serif;color:#6b7280">Generated: {generated_at}</p>
<p style="font-family:sans-serif">Devices scanned: {len(results)}</p>
{error_note}
{check_summary_html}
{host_summary_html}
<p style="font-family:sans-serif;font-size:11px;color:#9ca3af;margin-top:16px">
  See attached report for full findings detail.
</p>"""
```

- [ ] **Step 4: Update the existing test that calls `_build_summary_html` without the new parameter**

Find `test_build_summary_html_includes_host_section` in the test file and update its call to pass an empty `check_summary`:

```python
def test_build_summary_html_includes_host_section():
    """_build_summary_html output contains both check summary and host summary sections."""
    from app.device_review_scheduler import _build_summary_html
    results = _make_results({"FW1": [
        {"result": "PASS", "check": "NTP Configuration"},
    ]})
    html = _build_summary_html("TESTADOM", results, "2026-08-03T01:00:00Z", [])
    assert "Host Summary" in html
    assert "Check Summary" in html
```

- [ ] **Step 5: Run all new and updated tests**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_summary_html_check_summary_above_host_summary tests/test_device_review_scheduler.py::test_summary_html_check_summary_has_6_columns tests/test_device_review_scheduler.py::test_summary_html_check_summary_shows_description tests/test_device_review_scheduler.py::test_summary_html_check_summary_shows_counts tests/test_device_review_scheduler.py::test_build_summary_html_includes_host_section -v
```

Expected: all PASS.

- [ ] **Step 6: Run full suite**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review): update email body with 6-column check summary above host summary"
```

---

## Task 3: Update attachment builders — HTML/PDF, CSV, JSON

**Files:**
- Modify: `app/device_review_scheduler.py` — `_build_pdf_html_dr`, `_build_attachment_dr`
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: `_build_check_summary` output (from Task 1) — same `list[dict]` shape
- Produces:
  - `_build_pdf_html_dr(adom, results, generated_at, check_summary)` — check summary table before host summary
  - `_build_attachment_dr(adom, fmt, results, generated_at, check_summary)` — passes through to pdf builder; adds `check_summary` key to JSON; adds `# Check Summary` block to CSV

- [ ] **Step 1: Write failing tests**

Add to `tests/test_device_review_scheduler.py`:

```python
# ── Attachment check summary ───────────────────────────────────────────────────

def _make_check_summary_for_attachments():
    return [
        {"key": "ntp_config", "name": "NTP Configuration", "description": "Check NTP",
         "PASS": 2, "INFO": 0, "WARN": 1, "CONFIG_MISSING": 0, "FAIL": 1, "INSECURE": 0},
    ]


def test_json_attachment_has_check_summary_before_host_summary():
    """JSON attachment includes 'check_summary' key before 'host_summary'."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "json", _make_results_with_rows(), "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    data = json.loads(att["data"])
    assert "check_summary" in data
    raw = att["data"].decode()
    assert raw.index("check_summary") < raw.index('"host_summary"')


def test_json_attachment_check_summary_structure():
    """check_summary entries have name, description, and all 6 result counts."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "json", [], "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    data = json.loads(att["data"])
    entry = data["check_summary"][0]
    assert entry["name"] == "NTP Configuration"
    assert entry["description"] == "Check NTP"
    for col in ("PASS", "INFO", "WARN", "CONFIG_MISSING", "FAIL", "INSECURE"):
        assert col in entry


def test_csv_attachment_has_check_summary_before_host_summary():
    """CSV attachment has # Check Summary comment block before # Host Summary."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "csv", _make_results_with_rows(), "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    text = att["data"].decode()
    assert "# Check Summary" in text
    assert "# Host Summary" in text
    assert text.index("# Check Summary") < text.index("# Host Summary")


def test_csv_attachment_check_summary_contains_check_name():
    """CSV check summary comment rows include the check name."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "csv", [], "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    text = att["data"].decode()
    assert "NTP Configuration" in text


def test_html_attachment_has_check_summary_before_host_summary():
    """HTML attachment has Check Summary heading before Host Summary heading."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "pdf", _make_results_with_rows(), "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    html = att["data"].decode()
    assert "Check Summary" in html
    assert "Host Summary" in html
    assert html.index("Check Summary") < html.index("Host Summary")


def test_html_attachment_check_summary_shows_description():
    """HTML attachment check summary table includes check description text."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr(
        "TESTADOM", "pdf", [], "2026-08-04T00:00:00Z",
        _make_check_summary_for_attachments()
    )
    html = att["data"].decode()
    assert "Check NTP" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_json_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_json_attachment_check_summary_structure tests/test_device_review_scheduler.py::test_csv_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_csv_attachment_check_summary_contains_check_name tests/test_device_review_scheduler.py::test_html_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_html_attachment_check_summary_shows_description -v
```

Expected: FAIL — functions don't yet accept `check_summary` parameter.

- [ ] **Step 3: Update `_build_pdf_html_dr`**

Change the function signature and insert the check summary table before the host summary table. Replace the function definition line and add the check summary block:

```python
def _build_pdf_html_dr(
    adom: str, results: list[dict], generated_at: str, check_summary: list[dict]
) -> str:
    all_rows = [r for dev in results for r in dev.get("rows", [])]

    # ── Findings rows ─────────────────────────────────────────────────────────
    rows_html = ""
    for row in all_rows:
        color = _RESULT_COLOR.get(row.get("result", ""), "#374151")
        rows_html += (
            f"<tr>"
            f"<td>{_esc(row.get('device', ''))}</td>"
            f"<td>{_esc(row.get('check', ''))}</td>"
            f"<td style='color:{color};font-weight:600'>{_esc(row.get('result', ''))}</td>"
            f"<td>{_esc(row.get('interface', ''))}</td>"
            f"<td>{_esc(row.get('vdom', ''))}</td>"
            f"<td>{_esc(row.get('ip', ''))}</td>"
            f"<td>{_esc(_fmt_detail(row))}</td>"
            f"</tr>\n"
        )

    # ── Check Summary table ───────────────────────────────────────────────────
    cs_header = "".join(
        f"<th style='background:#f3f4f6;padding:4px 8px'>{r}</th>"
        for r in _CHECK_SUMMARY_RESULTS
    )
    cs_rows = ""
    for entry in check_summary:
        cells = "".join(
            f"<td style='padding:4px 8px;text-align:center;color:{_RESULT_COLOR.get(r, \"#374151\")}'>{entry[r]}</td>"
            for r in _CHECK_SUMMARY_RESULTS
        )
        cs_rows += (
            f"<tr>"
            f"<td style='padding:4px 8px'>{_esc(entry['name'])}</td>"
            f"<td style='padding:4px 8px;color:#6b7280'>{_esc(entry['description'])}</td>"
            f"{cells}"
            f"</tr>\n"
        )

    # ── Host Summary table ────────────────────────────────────────────────────
    summary_header = "".join(
        f"<th style='background:#f3f4f6;padding:4px 8px'>{r}</th>"
        for r in _SUMMARY_RESULTS
    )
    summary_rows = ""
    totals = {r: 0 for r in _SUMMARY_RESULTS}
    for dev in sorted(results, key=lambda d: d.get("device", "")):
        counts = {r: 0 for r in _SUMMARY_RESULTS}
        for row in dev.get("rows", []):
            res = row.get("result", "")
            if res in counts:
                counts[res] += 1
                totals[res] += 1
        total = sum(counts.values())
        cells = "".join(
            f"<td style='padding:4px 8px;text-align:center;color:{_RESULT_COLOR.get(r, '#374151')}'>{counts[r]}</td>"
            for r in _SUMMARY_RESULTS
        )
        error_note = " (error)" if dev.get("error") else ""
        dev_name = _esc(dev.get("device", ""))
        summary_rows += (
            f"<tr><td style='padding:4px 8px'>{dev_name}{error_note}</td>"
            f"{cells}"
            f"<td style='padding:4px 8px;text-align:center'>{total}</td></tr>\n"
        )
    total_cells = "".join(
        f"<td style='padding:4px 8px;text-align:center;font-weight:600;color:{_RESULT_COLOR.get(r, '#374151')}'>{totals[r]}</td>"
        for r in _SUMMARY_RESULTS
    )
    grand_total = sum(totals.values())
    summary_rows += (
        f"<tr style='background:#f3f4f6;font-weight:600'>"
        f"<td style='padding:4px 8px'>Totals</td>{total_cells}"
        f"<td style='padding:4px 8px;text-align:center'>{grand_total}</td></tr>\n"
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body{{font-family:sans-serif;font-size:12px;color:#111}}
  h1{{font-size:18px;margin-bottom:4px}}
  h2{{font-size:14px;margin-top:24px;margin-bottom:6px}}
  .meta{{color:#6b7280;margin-bottom:16px;font-size:11px}}
  table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
  th,td{{border:1px solid #e5e7eb;padding:4px 8px;text-align:left}}
  th{{background:#f3f4f6;font-weight:600}}
  tr:nth-child(even){{background:#fafafa}}
</style>
</head>
<body>
<h1>4THealth Device Review Scheduler</h1>
<div class="meta">
  ADOM: {_esc(adom)} &nbsp;|&nbsp;
  Devices scanned: {len(results)} &nbsp;|&nbsp;
  Total findings: {len(all_rows)} &nbsp;|&nbsp;
  Generated: {generated_at}
</div>
<h2>Check Summary</h2>
<table>
  <thead>
    <tr>
      <th style='background:#f3f4f6;padding:4px 8px'>Check</th>
      <th style='background:#f3f4f6;padding:4px 8px'>Description</th>
      {cs_header}
    </tr>
  </thead>
  <tbody>{cs_rows}</tbody>
</table>
<h2>Host Summary</h2>
<table>
  <thead>
    <tr>
      <th style='background:#f3f4f6;padding:4px 8px'>Device</th>
      {summary_header}
      <th style='background:#f3f4f6;padding:4px 8px'>Total</th>
    </tr>
  </thead>
  <tbody>{summary_rows}</tbody>
</table>
<h2>Findings</h2>
<table>
  <thead>
    <tr>
      <th>Device</th><th>Check</th><th>Result</th>
      <th>Interface</th><th>VDOM</th><th>IP</th><th>Detail</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</body>
</html>"""
```

- [ ] **Step 4: Update `_build_attachment_dr` signature and body**

Change the signature to accept `check_summary` and thread it through:

```python
def _build_attachment_dr(
    adom: str, fmt: str, results: list[dict], generated_at: str, check_summary: list[dict]
) -> dict:
```

**JSON branch** — add `check_summary` key before `host_summary`. Replace the `payload = json.dumps(...)` call:

```python
        payload = json.dumps(
            {
                "report_type": "device_review",
                "adom": adom,
                "exported_at": generated_at,
                "check_summary": [
                    {
                        "name": e["name"],
                        "description": e["description"],
                        **{r: e[r] for r in _CHECK_SUMMARY_RESULTS},
                    }
                    for e in check_summary
                ],
                "host_summary": host_summary,
                "rows": all_rows,
            },
            indent=2,
        ).encode()
```

**CSV branch** — add `# Check Summary` block before the existing `# Host Summary` block. After the three header comment rows and empty row, insert:

```python
        w.writerow(["# Check Summary"])
        w.writerow(["# Check", "Description", "PASS", "INFO", "WARN", "CONFIG_MISSING", "FAIL", "INSECURE"])
        for entry in check_summary:
            w.writerow([
                f"# {entry['name']}",
                entry["description"],
                entry["PASS"],
                entry["INFO"],
                entry["WARN"],
                entry["CONFIG_MISSING"],
                entry["FAIL"],
                entry["INSECURE"],
            ])
        w.writerow([])
```

**PDF branch** — pass `check_summary` to `_build_pdf_html_dr`:

```python
    html = _build_pdf_html_dr(adom, results, generated_at, check_summary)
```

- [ ] **Step 5: Update existing attachment tests that call `_build_attachment_dr` without `check_summary`**

The existing tests `test_build_attachment_json`, `test_build_attachment_csv`, `test_build_attachment_pdf_html`, `test_json_attachment_has_host_summary`, `test_json_attachment_host_summary_before_rows`, `test_csv_attachment_has_host_summary_comments`, `test_html_attachment_has_host_summary_table` all call `_build_attachment_dr` or `_build_pdf_html_dr` without the new parameter. Add `[]` as the last argument to each call. For example:

```python
# test_build_attachment_json
att = sched._build_attachment_dr("Corp", "json", results, "2026-08-01T00:00:00Z", [])

# test_build_attachment_csv
att = sched._build_attachment_dr("Corp", "csv", results, "2026-08-01T00:00:00Z", [])

# test_build_attachment_pdf_html
att = sched._build_attachment_dr("Corp", "pdf", results, "2026-08-01T00:00:00Z", [])

# test_json_attachment_has_host_summary
att = _build_attachment_dr("TESTADOM", "json", _make_results_with_rows(), "2026-08-03T01:00:00Z", [])

# test_json_attachment_host_summary_before_rows
att = _build_attachment_dr("TESTADOM", "json", _make_results_with_rows(), "2026-08-03T01:00:00Z", [])

# test_csv_attachment_has_host_summary_comments
att = _build_attachment_dr("TESTADOM", "csv", _make_results_with_rows(), "2026-08-03T01:00:00Z", [])

# test_html_attachment_has_host_summary_table
att = _build_attachment_dr("TESTADOM", "pdf", _make_results_with_rows(), "2026-08-03T01:00:00Z", [])
```

- [ ] **Step 6: Run all new and updated tests**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_json_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_json_attachment_check_summary_structure tests/test_device_review_scheduler.py::test_csv_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_csv_attachment_check_summary_contains_check_name tests/test_device_review_scheduler.py::test_html_attachment_has_check_summary_before_host_summary tests/test_device_review_scheduler.py::test_html_attachment_check_summary_shows_description -v
```

Expected: all PASS.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review): add check summary section to all attachment formats"
```

---

## Task 4: Wire `_execute_job` and update integration test

**Files:**
- Modify: `app/device_review_scheduler.py:211-291` — `_execute_job`
- Test: `tests/test_device_review_scheduler.py` — `test_execute_job_sends_email`

**Interfaces:**
- Consumes: `_build_check_summary(results, checks_ran) -> list[dict]` (Task 1)
- Consumes: `_build_summary_html(adom, results, generated_at, check_summary)` (Task 2)
- Consumes: `_build_attachment_dr(adom, fmt, results, generated_at, check_summary)` (Task 3)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_device_review_scheduler.py`:

```python
def test_execute_job_check_summary_in_email_body(jobs_path, monkeypatch):
    """_execute_job passes check_summary to the email body builder."""
    import app.device_review_scheduler as sched

    fake_meta = [
        {"key": "trusted_hosts", "name": "Trusted Hosts on Admin Accounts (CIS)",
         "description": "Check trusted hosts"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": ["trusted_hosts"], "check_params": {},
        "format": "pdf", "email": "test@corp.com", "enabled": True,
    })

    fake_results = [
        {"device": "fw-01", "ip": "10.0.0.1",
         "rows": [{"device": "fw-01",
                   "check": "Trusted Hosts on Admin Accounts (CIS)",
                   "result": "PASS", "interface": "system", "vdom": "root",
                   "ip": "", "detail": "ok", "protocols": [],
                   "has_insecure": False, "has_secure": False}],
         "error": None},
    ]

    sent = {}

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom",
        lambda *a, **kw: fake_results,
    )
    monkeypatch.setattr(
        "app.device_review_scheduler._send_email",
        lambda to, subject, body_html, attachments: sent.update({"body": body_html}),
    )

    sched._execute_job(job["id"])

    assert "Check Summary" in sent["body"]
    assert "Trusted Hosts on Admin Accounts (CIS)" in sent["body"]
    assert "Check trusted hosts" in sent["body"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_execute_job_check_summary_in_email_body -v
```

Expected: FAIL — `_execute_job` calls `_build_summary_html` without `check_summary`.

- [ ] **Step 3: Update `_execute_job` to call `_build_check_summary` and pass result to builders**

In `_execute_job`, replace:

```python
        body_html = _build_summary_html(adom, results, generated_at)
        attachment = _build_attachment_dr(adom, fmt, results, generated_at)
```

with:

```python
        check_summary = _build_check_summary(results, checks)
        body_html = _build_summary_html(adom, results, generated_at, check_summary)
        attachment = _build_attachment_dr(adom, fmt, results, generated_at, check_summary)
```

- [ ] **Step 4: Update `test_execute_job_sends_email` to supply the `_CHECKS_META` patch**

The existing test uses a row with `check = "Trusted Hosts on Admin Accounts (CIS)"`. After this change, `_build_check_summary` will look up `CHECKS_META` via the lazy import. To keep the test self-contained, monkeypatch `_CHECKS_META`:

```python
def test_execute_job_sends_email(jobs_path, monkeypatch):
    from app import device_review_scheduler as sched

    fake_meta = [
        {"key": "trusted_hosts", "name": "Trusted Hosts on Admin Accounts (CIS)",
         "description": "Check trusted hosts"},
    ]
    monkeypatch.setattr("app.device_review_scheduler._CHECKS_META", fake_meta)

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": ["trusted_hosts"], "check_params": {},
        "format": "pdf", "email": "test@corp.com", "enabled": True,
    })

    fake_results = [
        {"device": "fw-01", "ip": "10.0.0.1",
         "rows": [{"device": "fw-01", "check": "Trusted Hosts on Admin Accounts (CIS)",
                   "result": "PASS", "interface": "system", "vdom": "root",
                   "ip": "", "detail": "All admins have trusted hosts",
                   "protocols": [], "has_insecure": False, "has_secure": False}],
         "error": None},
    ]

    sent = {}

    def fake_bulk(adom, checks, check_params, max_workers=4):
        return fake_results

    def fake_send(to, subject, body_html, attachments):
        sent["to"] = to
        sent["subject"] = subject
        sent["attachments"] = attachments

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom", fake_bulk
    )
    monkeypatch.setattr("app.device_review_scheduler._send_email", fake_send)

    sched._execute_job(job["id"])

    assert sent["to"] == "test@corp.com"
    assert "CorpADOM" in sent["subject"]
    assert len(sent["attachments"]) == 1
```

- [ ] **Step 5: Run all new and affected tests**

```bash
uv run pytest tests/test_device_review_scheduler.py::test_execute_job_check_summary_in_email_body tests/test_device_review_scheduler.py::test_execute_job_sends_email tests/test_device_review_scheduler.py::test_execute_job_appends_run_record -v
```

Expected: all PASS.

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest tests/test_device_review_scheduler.py -v
```

Expected: all PASS.

- [ ] **Step 7: Final commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review): wire check summary through _execute_job to all report formats"
```
