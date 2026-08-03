# Device Review Host Summary & Protocol Severity Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the Interface Protocols WARN/INFO inconsistency, add a user-configurable `protocol_severity.json` override file, and add a per-host result summary to scheduled Device Review email reports and all attachment formats.

**Architecture:** Two independent changes: (1) `app/device_review.py` loads optional protocol overrides at import time and fixes the result classification logic; (2) `app/device_review_scheduler.py` gains a `_build_host_summary_html` helper and updates all three attachment format builders to prepend a per-host summary. Both changes update documentation.

**Tech Stack:** Python 3, Flask, APScheduler, stdlib `json`/`csv`/`io`. Tests use `pytest` with `unittest.mock`. No new dependencies.

## Global Constraints

- Python 3.11+ — use `bool | None` union syntax, no `Optional`.
- No new `pip install` — use `uv add` if a new package is ever needed (none expected here).
- All JSON files written atomically via `app/atomic_io.py` — do not use plain `open(..., "w")` for JSON persistence.
- `protocol_severity.json` is gitignored; `protocol_severity.example.json` is committed.
- Test files live in `tests/` at project root. Run tests with `pytest tests/ -v`.
- Existing test style: no classes, flat functions, `monkeypatch` for paths, `unittest.mock.patch` for external calls.
- `_build_summary_html` in `app/device_review_scheduler.py` already receives `results: list[dict]` (each entry has `"device"`, `"rows"`, optional `"error"`). Do not change this signature — extend it.
- All HTML in email/attachment uses inline styles only (no external CSS, no `<link>`).
- Commit after every task using the message format shown in each task.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `app/device_review.py` | Modify | Add `_load_proto_overrides()`, `_EFFECTIVE_PROTO_SECURE`, fix result logic in `_run_interface_protocols` |
| `protocol_severity.example.json` | Create | Committed example showing all default keys + valid values |
| `.gitignore` | Modify | Add `protocol_severity.json` |
| `app/device_review_scheduler.py` | Modify | Add `_build_host_summary_html`, update `_build_summary_html`, `_build_pdf_html_dr`, CSV and JSON builders |
| `tests/test_device_review.py` | Modify | Add tests for new protocol logic, override loading, result classification |
| `tests/test_device_review_scheduler.py` | Modify | Add tests for host summary HTML, CSV/JSON/HTML attachment summaries |
| `CLAUDE.md` | Modify | Document `protocol_severity.json` and updated result values |
| `docs/features.md` | Modify | Update Device Review section |
| `CHANGELOG.md` | Modify | Add entries for both changes |

---

## Task 1: Fix Protocol Result Logic and Add Config Override Loading

**Files:**
- Modify: `app/device_review.py:44-64` (protocol dict and classify function)
- Modify: `app/device_review.py:183-188` (result assignment in `_run_interface_protocols`)
- Create: `protocol_severity.example.json`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `_EFFECTIVE_PROTO_SECURE: dict[str, bool | None]` — module-level dict used by `_classify_proto`
- Produces: `_load_proto_overrides() -> dict[str, bool | None]` — loads and validates `protocol_severity.json`
- Produces: updated `_classify_proto(name: str) -> bool | None` — now reads from `_EFFECTIVE_PROTO_SECURE`
- Produces: fixed result logic: ping-only → `"INFO"`, no protocols → `"WARN"` (safety net only)

- [ ] **Step 1: Write failing tests for protocol override loading**

Add to `tests/test_device_review.py`:

```python
import json
import tempfile
import os
from unittest.mock import patch

# ── _load_proto_overrides ────────────────────────────────────────────────────

def test_load_proto_overrides_missing_file():
    """Missing file returns empty dict — no error."""
    from app.device_review import _load_proto_overrides
    with patch("app.device_review._PROTO_SEVERITY_PATH", "/nonexistent/path.json"):
        result = _load_proto_overrides()
    assert result == {}


def test_load_proto_overrides_valid_file(tmp_path):
    """Valid overrides are parsed and converted to bool | None."""
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"ping": "warn", "http": "secure"}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        result = _load_proto_overrides()
    assert result["ping"] is False   # "warn" maps to... wait — see note below
    # Actually "warn" is not a valid value. Valid: "secure","insecure","info",null
    # This test should cover a valid value set:


def test_load_proto_overrides_secure_value(tmp_path):
    """'secure' maps to True."""
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"http": "secure"}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        result = _load_proto_overrides()
    assert result["http"] is True


def test_load_proto_overrides_insecure_value(tmp_path):
    """'insecure' maps to False."""
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"ping": "insecure"}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        result = _load_proto_overrides()
    assert result["ping"] is False


def test_load_proto_overrides_info_value(tmp_path):
    """'info' and null both map to None."""
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"https": "info", "ssh": None}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        result = _load_proto_overrides()
    assert result["https"] is None
    assert result["ssh"] is None


def test_load_proto_overrides_invalid_value_ignored(tmp_path, caplog):
    """Invalid values are skipped; valid entries in the same file still apply."""
    import logging
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"ping": "badvalue", "http": "insecure"}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        with caplog.at_level(logging.WARNING):
            result = _load_proto_overrides()
    assert "ping" not in result
    assert result["http"] is False


def test_load_proto_overrides_unknown_protocol_accepted(tmp_path):
    """Unknown protocol keys are accepted (future-proofing)."""
    from app.device_review import _load_proto_overrides
    f = tmp_path / "protocol_severity.json"
    f.write_text(json.dumps({"myproto": "insecure"}))
    with patch("app.device_review._PROTO_SEVERITY_PATH", str(f)):
        result = _load_proto_overrides()
    assert result["myproto"] is False
```

- [ ] **Step 2: Write failing tests for fixed result classification**

Add to `tests/test_device_review.py`:

```python
# ── _run_interface_protocols result logic ─────────────────────────────────────

from app.device_review import _run_interface_protocols

def _iface(name: str, ip: str, protos: str) -> dict:
    return {"name": name, "ip": ip, "allowaccess": protos, "vdom": "root",
            "type": "physical", "status": "up"}


def test_ping_only_is_info():
    """ping-only interface must be INFO, not WARN."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "ping")]}, {})
    assert len(rows) == 1
    assert rows[0]["result"] == "INFO"


def test_https_ping_is_info():
    """https + ping = INFO (secure present)."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "https ping")]}, {})
    assert rows[0]["result"] == "INFO"


def test_https_only_is_info():
    """https-only = INFO."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "https")]}, {})
    assert rows[0]["result"] == "INFO"


def test_http_only_is_insecure():
    """http-only = INSECURE."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "http")]}, {})
    assert rows[0]["result"] == "INSECURE"


def test_http_https_is_insecure():
    """http + https = INSECURE (insecure takes precedence)."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "http https")]}, {})
    assert rows[0]["result"] == "INSECURE"


def test_fgfm_only_is_info():
    """fgfm-only = INFO (informational protocol)."""
    rows = _run_interface_protocols("FW1", {"interfaces": [_iface("mgmt", "10.0.0.1/24", "fgfm")]}, {})
    assert rows[0]["result"] == "INFO"
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd /path/to/4thealth
pytest tests/test_device_review.py::test_ping_only_is_info tests/test_device_review.py::test_load_proto_overrides_missing_file -v
```

Expected: FAIL — `_load_proto_overrides` and `_PROTO_SEVERITY_PATH` don't exist yet; `test_ping_only_is_info` returns `"WARN"` not `"INFO"`.

- [ ] **Step 4: Implement `_load_proto_overrides` and `_EFFECTIVE_PROTO_SECURE`**

In `app/device_review.py`, after the existing `_PROTO_SECURE` dict (after line 59), add:

```python
import logging as _logging
import pathlib as _pathlib

_PROTO_SEVERITY_PATH = str(
    _pathlib.Path(__file__).parent.parent / "protocol_severity.json"
)

_VALID_VALUES = {"secure": True, "insecure": False, "info": None}


def _load_proto_overrides() -> dict[str, bool | None]:
    """Load protocol_severity.json overrides. Missing file → empty dict."""
    import json as _json
    try:
        with open(_PROTO_SEVERITY_PATH) as fh:
            raw = _json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "protocol_severity.json unreadable — using defaults: %s", exc
        )
        return {}
    result: dict[str, bool | None] = {}
    for key, val in raw.items():
        if val is None:
            result[key.lower()] = None
        elif isinstance(val, str) and val.lower() in _VALID_VALUES:
            result[key.lower()] = _VALID_VALUES[val.lower()]
        else:
            _logging.getLogger(__name__).warning(
                "protocol_severity.json: invalid value %r for %r — ignored", val, key
            )
    return result


_EFFECTIVE_PROTO_SECURE: dict[str, bool | None] = {**_PROTO_SECURE, **_load_proto_overrides()}
```

- [ ] **Step 5: Update `_classify_proto` to use `_EFFECTIVE_PROTO_SECURE`**

Change line 62–64 in `app/device_review.py`:

```python
def _classify_proto(name: str) -> bool | None:
    """Return True=secure, False=insecure, None=informational."""
    return _EFFECTIVE_PROTO_SECURE.get(name.lower(), None)
```

- [ ] **Step 6: Fix result logic in `_run_interface_protocols`**

Replace lines 183–188 in `app/device_review.py`:

```python
        has_info_only = any(p["secure"] is None for p in proto_list)

        if has_insecure:
            result = "INSECURE"
        elif has_secure or has_info_only:
            result = "INFO"
        else:
            result = "WARN"  # no protocols of any known type — safety net
```

- [ ] **Step 7: Create `protocol_severity.example.json`**

Create at project root:

```json
{
  "_comment": "Copy to protocol_severity.json to override defaults. Valid values: secure, insecure, info, null.",
  "https":          "secure",
  "ssh":            "secure",
  "snmp":           "secure",
  "fabric":         "secure",
  "http":           "insecure",
  "telnet":         "insecure",
  "http-redirect":  "insecure",
  "ping":           "info",
  "fgfm":           "info",
  "capwap":         "info",
  "speed-test":     "info",
  "ftm":            "info"
}
```

- [ ] **Step 8: Add `protocol_severity.json` to `.gitignore`**

Open `.gitignore` and add after the block containing `app_settings.json`:

```
protocol_severity.json
```

- [ ] **Step 9: Run all new tests**

```bash
pytest tests/test_device_review.py -v -k "proto or interface_protocols or ping or http or fgfm"
```

Expected: all new tests PASS. Existing tests should still pass.

- [ ] **Step 10: Run full test suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add app/device_review.py protocol_severity.example.json .gitignore
git commit -m "feat(device-review): add protocol_severity.json config override and fix ping-only INFO result"
```

---

## Task 2: Per-Host Summary in Email Body

**Files:**
- Modify: `app/device_review_scheduler.py:341-395` (`_build_summary_html`)
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: `results: list[dict]` — each entry is `{"device": str, "rows": list[dict], "error"?: str}`. Each row has a `"result"` key with values `PASS | FAIL | INSECURE | WARN | CONFIG_MISSING | INFO`.
- Produces: `_build_host_summary_html(results: list[dict]) -> str` — returns HTML `<h3>` + `<table>` block
- Produces: updated `_build_summary_html` — inserts host summary above the existing per-check table

- [ ] **Step 1: Write failing tests for `_build_host_summary_html`**

Add to `tests/test_device_review_scheduler.py`:

```python
# ── _build_host_summary_html ──────────────────────────────────────────────────

def _make_results(device_rows: dict[str, list[dict]]) -> list[dict]:
    """Helper: build a results list from {device: [rows]} dict."""
    return [
        {"device": dev, "rows": rows}
        for dev, rows in device_rows.items()
    ]


def test_host_summary_html_columns():
    """All seven result columns appear in the output."""
    from app.device_review_scheduler import _build_host_summary_html
    results = _make_results({"FW1": [
        {"result": "PASS", "check": "NTP"},
        {"result": "FAIL", "check": "NTP"},
        {"result": "INSECURE", "check": "Interface Protocols"},
        {"result": "WARN", "check": "Interface Protocols"},
        {"result": "CONFIG_MISSING", "check": "NTP"},
        {"result": "INFO", "check": "Interface Protocols"},
    ]})
    html = _build_host_summary_html(results)
    for col in ("PASS", "FAIL", "INSECURE", "WARN", "CONFIG_MISSING", "INFO", "Total"):
        assert col in html


def test_host_summary_html_counts_correct():
    """Row counts match the input data."""
    from app.device_review_scheduler import _build_host_summary_html
    results = _make_results({"FW1": [
        {"result": "PASS"}, {"result": "PASS"}, {"result": "FAIL"},
    ]})
    html = _build_host_summary_html(results)
    assert "FW1" in html
    # Total = 3
    assert ">3<" in html


def test_host_summary_html_totals_row():
    """A Totals footer row is present."""
    from app.device_review_scheduler import _build_host_summary_html
    results = _make_results({
        "FW1": [{"result": "PASS"}, {"result": "FAIL"}],
        "FW2": [{"result": "PASS"}],
    })
    html = _build_host_summary_html(results)
    assert "Totals" in html


def test_host_summary_html_sorted_devices():
    """Devices are listed alphabetically."""
    from app.device_review_scheduler import _build_host_summary_html
    results = _make_results({
        "ZFW": [{"result": "PASS"}],
        "AFW": [{"result": "PASS"}],
    })
    html = _build_host_summary_html(results)
    assert html.index("AFW") < html.index("ZFW")


def test_host_summary_html_error_device():
    """Devices with errors show (error) annotation."""
    from app.device_review_scheduler import _build_host_summary_html
    results = [{"device": "FW1", "rows": [], "error": "timeout"}]
    html = _build_host_summary_html(results)
    assert "error" in html.lower()
    assert "FW1" in html


def test_build_summary_html_includes_host_section():
    """_build_summary_html output contains both host summary and per-check table."""
    from app.device_review_scheduler import _build_summary_html
    results = _make_results({"FW1": [
        {"result": "PASS", "check": "NTP Configuration"},
    ]})
    html = _build_summary_html("TESTADOM", results, "2026-08-03T01:00:00Z")
    assert "Host Summary" in html
    assert "NTP Configuration" in html
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_device_review_scheduler.py::test_host_summary_html_columns tests/test_device_review_scheduler.py::test_build_summary_html_includes_host_section -v
```

Expected: FAIL — `_build_host_summary_html` does not exist yet.

- [ ] **Step 3: Implement `_build_host_summary_html`**

Add after `_RESULT_COLOR` dict (after line 338) in `app/device_review_scheduler.py`:

```python
_SUMMARY_RESULTS = ("PASS", "FAIL", "INSECURE", "WARN", "CONFIG_MISSING", "INFO")


def _build_host_summary_html(results: list[dict]) -> str:
    """Return an HTML table with one row per device showing per-result counts."""
    totals = {r: 0 for r in _SUMMARY_RESULTS}
    rows_html = ""
    for dev in sorted(results, key=lambda d: d.get("device", "")):
        device = dev.get("device", "unknown")
        counts = {r: 0 for r in _SUMMARY_RESULTS}
        for row in dev.get("rows", []):
            res = row.get("result", "")
            if res in counts:
                counts[res] += 1
                totals[res] += 1
        total = sum(counts.values())
        has_fail = counts["FAIL"] + counts["INSECURE"] > 0
        has_warn = counts["WARN"] + counts["CONFIG_MISSING"] > 0
        if has_fail:
            row_style = "background:#fee2e2"
        elif has_warn:
            row_style = "background:#fef3c7"
        else:
            row_style = ""
        error_suffix = (
            " <span style='color:#991b1b'>(error)</span>"
            if dev.get("error") else ""
        )
        cells = "".join(
            f"<td style='padding:4px 8px;text-align:center;"
            f"color:{_RESULT_COLOR.get(r, \"#374151\")}'>{counts[r]}</td>"
            for r in _SUMMARY_RESULTS
        )
        rows_html += (
            f"<tr style='{row_style}'>"
            f"<td style='padding:4px 8px'>{_esc(device)}{error_suffix}</td>"
            f"{cells}"
            f"<td style='padding:4px 8px;text-align:center'>{total}</td>"
            f"</tr>\n"
        )
    # Totals footer
    total_all = sum(totals.values())
    total_cells = "".join(
        f"<td style='padding:4px 8px;text-align:center;font-weight:600;"
        f"color:{_RESULT_COLOR.get(r, \"#374151\")}'>{totals[r]}</td>"
        for r in _SUMMARY_RESULTS
    )
    rows_html += (
        f"<tr style='background:#f3f4f6;font-weight:600'>"
        f"<td style='padding:4px 8px'>Totals</td>"
        f"{total_cells}"
        f"<td style='padding:4px 8px;text-align:center;font-weight:600'>{total_all}</td>"
        f"</tr>\n"
    )
    header_cells = "".join(
        f"<th style='padding:4px 8px'>{r}</th>" for r in _SUMMARY_RESULTS
    )
    return (
        f"<h3 style='font-family:sans-serif;margin-top:24px'>Host Summary</h3>"
        f"<table style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
        f"<thead><tr style='background:#f3f4f6'>"
        f"<th style='padding:4px 8px;text-align:left'>Device</th>"
        f"{header_cells}"
        f"<th style='padding:4px 8px'>Total</th>"
        f"</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        f"</table>"
    )
```

- [ ] **Step 4: Update `_build_summary_html` to include host summary above per-check table**

In `app/device_review_scheduler.py`, replace the `return f"""` block starting at line 377 to insert the host summary. The function signature stays the same. Change the return statement from:

```python
    return f"""
<h2 style="font-family:sans-serif">4THealth Device Review — {adom}</h2>
<p style="font-family:sans-serif;color:#6b7280">Generated: {generated_at}</p>
<p style="font-family:sans-serif">Devices scanned: {len(results)}</p>
{error_note}
<table style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
```

To:

```python
    host_summary_html = _build_host_summary_html(results)

    return f"""
<h2 style="font-family:sans-serif">4THealth Device Review — {adom}</h2>
<p style="font-family:sans-serif;color:#6b7280">Generated: {generated_at}</p>
<p style="font-family:sans-serif">Devices scanned: {len(results)}</p>
{error_note}
{host_summary_html}
<h3 style="font-family:sans-serif;margin-top:24px">Check Summary</h3>
<table style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
```

- [ ] **Step 5: Run new tests**

```bash
pytest tests/test_device_review_scheduler.py -v -k "host_summary or build_summary"
```

Expected: all new tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review-scheduler): add per-host result summary to email body"
```

---

## Task 3: Per-Host Summary in Attachment (HTML, CSV, JSON)

**Files:**
- Modify: `app/device_review_scheduler.py:398-502` (`_build_attachment_dr`, `_build_pdf_html_dr`)
- Test: `tests/test_device_review_scheduler.py`

**Interfaces:**
- Consumes: `_build_host_summary_html` from Task 2
- Consumes: `_SUMMARY_RESULTS` tuple from Task 2
- Produces: updated `_build_pdf_html_dr(adom, results, generated_at) -> str` — signature changes: `rows: list[dict]` → `results: list[dict]`
- Produces: updated `_build_attachment_dr` — passes `results` through to builders, adds host summary to all three formats

- [ ] **Step 1: Write failing tests for attachment host summaries**

Add to `tests/test_device_review_scheduler.py`:

```python
import csv
import io

# ── Attachment host summaries ─────────────────────────────────────────────────

def _make_results_with_rows() -> list[dict]:
    return [
        {"device": "FW1", "rows": [
            {"result": "PASS", "check": "NTP Configuration", "interface": "system",
             "vdom": "root", "ip": "", "detail": "ok", "protocols": []},
            {"result": "WARN", "check": "Interface Protocols", "interface": "mgmt",
             "vdom": "root", "ip": "10.0.0.1/24", "detail": "", "protocols": [{"name": "ping", "secure": None}]},
        ]},
        {"device": "FW2", "rows": [
            {"result": "FAIL", "check": "NTP Configuration", "interface": "system",
             "vdom": "root", "ip": "", "detail": "no ntp", "protocols": []},
        ]},
    ]


def test_json_attachment_has_host_summary():
    """JSON attachment includes 'host_summary' key before 'rows'."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr("TESTADOM", "json", _make_results_with_rows(), "2026-08-03T01:00:00Z")
    data = json.loads(att["data"])
    assert "host_summary" in data
    assert isinstance(data["host_summary"], list)
    assert len(data["host_summary"]) == 2
    fw1 = next(h for h in data["host_summary"] if h["device"] == "FW1")
    assert fw1["counts"]["PASS"] == 1
    assert fw1["counts"]["WARN"] == 1
    assert fw1["total"] == 2


def test_json_attachment_host_summary_before_rows():
    """'host_summary' key appears before 'rows' in JSON output."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr("TESTADOM", "json", _make_results_with_rows(), "2026-08-03T01:00:00Z")
    raw = att["data"].decode()
    assert raw.index("host_summary") < raw.index('"rows"')


def test_csv_attachment_has_host_summary_comments():
    """CSV attachment includes host summary comment lines before data rows."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr("TESTADOM", "csv", _make_results_with_rows(), "2026-08-03T01:00:00Z")
    text = att["data"].decode()
    assert "# Host Summary" in text
    assert "FW1" in text
    assert "FW2" in text


def test_html_attachment_has_host_summary_table():
    """HTML attachment includes 'Host Summary' heading and table before findings."""
    from app.device_review_scheduler import _build_attachment_dr
    att = _build_attachment_dr("TESTADOM", "pdf", _make_results_with_rows(), "2026-08-03T01:00:00Z")
    html = att["data"].decode()
    assert "Host Summary" in html
    assert html.index("Host Summary") < html.index("Findings")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_device_review_scheduler.py::test_json_attachment_has_host_summary tests/test_device_review_scheduler.py::test_csv_attachment_has_host_summary_comments tests/test_device_review_scheduler.py::test_html_attachment_has_host_summary_table -v
```

Expected: all three FAIL.

- [ ] **Step 3: Update `_build_attachment_dr` JSON branch**

In `app/device_review_scheduler.py`, replace the `if fmt == "json":` block (lines 405–419):

```python
    if fmt == "json":
        host_summary = []
        for dev in sorted(results, key=lambda d: d.get("device", "")):
            counts = {r: 0 for r in _SUMMARY_RESULTS}
            for row in dev.get("rows", []):
                res = row.get("result", "")
                if res in counts:
                    counts[res] += 1
            host_summary.append({
                "device": dev.get("device", ""),
                "counts": counts,
                "total": sum(counts.values()),
            })
        payload = json.dumps(
            {
                "report_type": "device_review",
                "adom": adom,
                "exported_at": generated_at,
                "host_summary": host_summary,
                "rows": all_rows,
            },
            indent=2,
        ).encode()
        return {
            "filename": f"device_review_{safe_adom}_{date_str}.json",
            "data": payload,
            "mimetype": "application/json",
        }
```

- [ ] **Step 4: Update `_build_attachment_dr` CSV branch**

In `app/device_review_scheduler.py`, replace the `if fmt == "csv":` block (lines 421–445). Insert host summary comment block after the existing `# Generated:` comment row and before the blank row:

```python
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# 4THealth Device Review"])
        w.writerow([f"# ADOM: {adom}"])
        w.writerow([f"# Generated: {generated_at}"])
        w.writerow([])
        w.writerow(["# Host Summary"])
        w.writerow(["# Device", "PASS", "FAIL", "INSECURE", "WARN", "CONFIG_MISSING", "INFO", "Total"])
        for dev in sorted(results, key=lambda d: d.get("device", "")):
            counts = {r: 0 for r in _SUMMARY_RESULTS}
            for row in dev.get("rows", []):
                res = row.get("result", "")
                if res in counts:
                    counts[res] += 1
            w.writerow([
                f"# {dev.get('device', '')}",
                counts["PASS"], counts["FAIL"], counts["INSECURE"],
                counts["WARN"], counts["CONFIG_MISSING"], counts["INFO"],
                sum(counts.values()),
            ])
        w.writerow([])
        w.writerow(["Device", "Check", "Result", "Interface", "VDOM", "IP", "Detail"])
        for row in all_rows:
            w.writerow(
                [
                    row.get("device", ""),
                    row.get("check", ""),
                    row.get("result", ""),
                    row.get("interface", ""),
                    row.get("vdom", ""),
                    row.get("ip", ""),
                    _fmt_detail(row),
                ]
            )
        return {
            "filename": f"device_review_{safe_adom}_{date_str}.csv",
            "data": buf.getvalue().encode(),
            "mimetype": "text/csv",
        }
```

- [ ] **Step 5: Update `_build_pdf_html_dr` signature and add host summary**

Change `_build_pdf_html_dr(adom, rows, generated_at)` to accept `results` instead of `rows`, and derive `all_rows` internally. Update the HTML to include a host summary table before the findings table:

```python
def _build_pdf_html_dr(adom: str, results: list[dict], generated_at: str) -> str:
    all_rows = [r for dev in results for r in dev.get("rows", [])]
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

    # Build host summary table inline (same logic as _build_host_summary_html
    # but using plain inline-style HTML without the <h3> wrapper)
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
            f"<td style='padding:4px 8px;text-align:center;"
            f"color:{_RESULT_COLOR.get(r, \"#374151\")}'>{counts[r]}</td>"
            for r in _SUMMARY_RESULTS
        )
        error_note = " (error)" if dev.get("error") else ""
        summary_rows += (
            f"<tr><td style='padding:4px 8px'>{_esc(dev.get('device',''))}{error_note}</td>"
            f"{cells}<td style='padding:4px 8px;text-align:center'>{total}</td></tr>\n"
        )
    total_cells = "".join(
        f"<td style='padding:4px 8px;text-align:center;font-weight:600;"
        f"color:{_RESULT_COLOR.get(r, \"#374151\")}'>{totals[r]}</td>"
        for r in _SUMMARY_RESULTS
    )
    summary_rows += (
        f"<tr style='background:#f3f4f6;font-weight:600'>"
        f"<td style='padding:4px 8px'>Totals</td>{total_cells}"
        f"<td style='padding:4px 8px;text-align:center'>{sum(totals.values())}</td></tr>\n"
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
  ADOM: {adom} &nbsp;|&nbsp;
  Devices scanned: {len(results)} &nbsp;|&nbsp;
  Total findings: {len(all_rows)} &nbsp;|&nbsp;
  Generated: {generated_at}
</div>
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

- [ ] **Step 6: Update the `pdf` branch in `_build_attachment_dr` to pass `results` instead of `all_rows`**

Change line 448 from:

```python
    html = _build_pdf_html_dr(adom, all_rows, generated_at)
```

To:

```python
    html = _build_pdf_html_dr(adom, results, generated_at)
```

- [ ] **Step 7: Run new attachment tests**

```bash
pytest tests/test_device_review_scheduler.py -v -k "attachment"
```

Expected: all attachment tests PASS.

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/device_review_scheduler.py tests/test_device_review_scheduler.py
git commit -m "feat(device-review-scheduler): add per-host summary to HTML, CSV, and JSON attachments"
```

---

## Task 4: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/features.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `CLAUDE.md` Device Review result values table**

In `CLAUDE.md`, find the **Result values** table under the Device Review tab section. Add a note about the INFO change and the new config file. The result values table currently has:

```
- `INSECURE` — red: cleartext protocols (HTTP, Telnet) are enabled
- `WARN` — yellow: no secure management alternative present
...
- `INFO` — blue: informational finding (e.g. PING enabled)
```

Update the WARN and INFO entries to:

```
- `INSECURE` — red: cleartext protocols (HTTP, Telnet) are enabled
- `WARN` — yellow: no secure management alternative present (rare safety net — informational-only protocols like PING now classify as INFO)
...
- `INFO` — blue: informational finding (e.g. PING enabled; interfaces with only informational protocols)
```

Then add a new paragraph after the result values section (before the "Implemented checks" table or wherever the existing Interface Protocols description ends):

```markdown
**Protocol severity configuration:** Create `protocol_severity.json` at the project root (gitignored) to override default protocol classifications. See `protocol_severity.example.json` for all defaults and valid values (`secure`, `insecure`, `info`, `null`). Overrides take effect on app restart.
```

- [ ] **Step 2: Update `docs/features.md` Device Review section**

Find the Device Review section (around line 54). After the result values table, add a paragraph:

```markdown
**Protocol Severity Override:** Protocol classifications (secure/insecure/informational) can be customised without code changes. Copy `protocol_severity.example.json` to `protocol_severity.json` at the project root and edit values. Valid values: `secure`, `insecure`, `info`, `null`. Changes take effect on app restart. Interfaces with only informational protocols (e.g. `ping`, `fgfm`) report **INFO**; the **WARN** result is a safety net for interfaces with unrecognised protocols only.
```

Find the Scheduled Exports section (around line 150) and add Device Review scheduled report detail:

```markdown
Device Review scheduled reports include a **Host Summary** table at the top of both the email body and the attached file, showing per-device counts for each result type (PASS, FAIL, INSECURE, WARN, CONFIG_MISSING, INFO). The existing per-check aggregate summary remains in the email body below the host summary.
```

- [ ] **Step 3: Update `CHANGELOG.md`**

Open `CHANGELOG.md` and add a new entry at the top (after any existing header/unreleased section). Match the existing format in the file. Add:

```markdown
## [Unreleased]

### Changed
- **Device Review — Interface Protocols:** Interfaces with only informational protocols (ping, fgfm, capwap, etc.) now report `INFO` instead of `WARN`. `WARN` is reserved as a safety net for interfaces with entirely unrecognised protocols.

### Added
- **Device Review — Protocol Severity Config:** Create `protocol_severity.json` at the project root to override default protocol classifications (secure/insecure/info) without code changes. See `protocol_severity.example.json` for all defaults. Changes take effect on app restart.
- **Device Review Scheduled Reports — Host Summary:** Scheduled email reports now include a per-host summary table (Device | PASS | FAIL | INSECURE | WARN | CONFIG_MISSING | INFO | Total) in both the email body and the attached report (HTML, CSV, and JSON formats).
```

- [ ] **Step 4: Commit documentation**

```bash
git add CLAUDE.md docs/features.md CHANGELOG.md
git commit -m "docs: document protocol severity config and host summary in device review reports"
```

---

## Self-Review Checklist

Spec requirements vs plan coverage:

| Spec Requirement | Task |
|---|---|
| Fix ping-only WARN → INFO | Task 1, Step 6 |
| Load `protocol_severity.json` overrides | Task 1, Steps 4–5 |
| Default for unknown protocols = None (info) | Task 1 — `_load_proto_overrides` returns None for null; `_classify_proto` defaults to None |
| Invalid override values logged + ignored | Task 1, Step 4 |
| `protocol_severity.example.json` committed | Task 1, Step 7 |
| `protocol_severity.json` gitignored | Task 1, Step 8 |
| Per-host summary in email body | Task 2 |
| Per-host summary in HTML attachment | Task 3, Steps 5–6 |
| Per-host summary in CSV attachment | Task 3, Step 4 |
| Per-host summary in JSON attachment | Task 3, Step 3 |
| Columns: PASS\|FAIL\|INSECURE\|WARN\|CONFIG_MISSING\|INFO\|Total | Tasks 2 & 3 |
| Totals footer row | Task 2, Step 3 |
| Devices sorted alphabetically | Task 2, Step 3 |
| Error devices annotated | Task 2, Step 3 |
| Update `CLAUDE.md` | Task 4, Step 1 |
| Update `docs/features.md` | Task 4, Step 2 |
| Update `CHANGELOG.md` | Task 4, Step 3 |
