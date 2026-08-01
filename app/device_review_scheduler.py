"""Scheduled Device Review email export engine.

Jobs and run history are persisted in device_review_jobs.json (project root).
Each enabled job is registered as an APScheduler CronTrigger at startup.
"""

from __future__ import annotations

import csv
import datetime
import fcntl
import io
import json
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from app.atomic_io import atomic_write_json
from app.app_logger import app_log

_JOBS_PATH = Path(__file__).parent.parent / "device_review_jobs.json"
_lock = threading.Lock()
_scheduler = None  # BackgroundScheduler instance, set by init_scheduler
_running_jobs: set[str] = set()

_VALID_DAYS = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}


# ── Indirection points (monkeypatched in tests) ───────────────────────────────


def _bulk_device_review_adom(adom, checks, check_params, max_workers=4):
    from app.routes.device_review_routes import bulk_device_review_adom

    return bulk_device_review_adom(adom, checks, check_params, max_workers)


def _send_email(to, subject, body_html, attachments):
    from app.smtp_client import send_email

    send_email(to, subject, body_html, attachments)


# ── Validation ────────────────────────────────────────────────────────────────


def _validate_job_fields(data: dict) -> None:
    days = data.get("days_of_week")
    if not isinstance(days, list) or not days:
        raise ValueError("days_of_week must be a non-empty list")
    invalid = [d for d in days if d not in _VALID_DAYS]
    if invalid:
        raise ValueError(
            f"days_of_week contains invalid codes: {invalid}. Must be from {sorted(_VALID_DAYS)}"
        )
    time_str = data.get("time", "")
    parts = time_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("time must be HH:MM format")
    if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
        raise ValueError("time HH must be 0-23, MM must be 0-59")


# ── Persistence ───────────────────────────────────────────────────────────────


def _load() -> list[dict]:
    if not _JOBS_PATH.exists():
        return []
    try:
        with open(_JOBS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(jobs: list[dict]) -> None:
    atomic_write_json(_JOBS_PATH, jobs)


# ── Public CRUD ───────────────────────────────────────────────────────────────


def get_all_jobs() -> list[dict]:
    with _lock:
        return _load()


def create_job(data: dict) -> dict:
    _validate_job_fields(data)
    job: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", "").strip(),
        "adom": data.get("adom", ""),
        "days_of_week": data["days_of_week"],
        "time": data["time"],
        "checks": data.get("checks") or [],
        "check_params": data.get("check_params") or {},
        "format": data.get("format", "pdf"),
        "email": data.get("email", ""),
        "enabled": bool(data.get("enabled", True)),
        "runs": [],
    }
    with _lock:
        jobs = _load()
        jobs.append(job)
        _save(jobs)
    if job["enabled"]:
        _register(job)
    return job


def update_job(job_id: str, data: dict) -> dict:
    _validate_job_fields(data)
    with _lock:
        jobs = _load()
        idx = next((i for i, j in enumerate(jobs) if j["id"] == job_id), None)
        if idx is None:
            raise KeyError(f"Job {job_id} not found")
        existing = jobs[idx]
        existing.update(
            {
                "name": data.get("name", existing.get("name", "")).strip(),
                "adom": data.get("adom", existing["adom"]),
                "days_of_week": data["days_of_week"],
                "time": data["time"],
                "checks": data.get("checks") or [],
                "check_params": data.get("check_params") or {},
                "format": data.get("format", existing.get("format", "pdf")),
                "email": data.get("email", existing["email"]),
                "enabled": bool(data.get("enabled", True)),
            }
        )
        jobs[idx] = existing
        _save(jobs)
    _unregister(job_id)
    if existing["enabled"]:
        _register(existing)
    return existing


def delete_job(job_id: str) -> None:
    with _lock:
        jobs = _load()
        new_jobs = [j for j in jobs if j["id"] != job_id]
        if len(new_jobs) == len(jobs):
            raise KeyError(f"Job {job_id} not found")
        _save(new_jobs)
    _unregister(job_id)


def run_job_now(job_id: str) -> None:
    t = threading.Thread(target=_execute_job, args=[job_id], daemon=True)
    t.start()


def is_job_running(job_id: str) -> bool:
    return job_id in _running_jobs


# ── Run history ───────────────────────────────────────────────────────────────


def _prune_runs(job_id: str, retention_days: int = 30) -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
    with _lock:
        jobs = _load()
        for job in jobs:
            if job["id"] != job_id:
                continue
            job["runs"] = [
                r
                for r in job.get("runs", [])
                if datetime.datetime.fromisoformat(r["ran_at"].rstrip("Z")) >= cutoff
            ]
        _save(jobs)


def _append_run(job_id: str, record: dict) -> None:
    with _lock:
        jobs = _load()
        for job in jobs:
            if job["id"] == job_id:
                job.setdefault("runs", []).insert(0, record)
        _save(jobs)


# ── Lock helper ───────────────────────────────────────────────────────────────


def _try_acquire_job_lock(job_id: str):
    lock_path = Path(tempfile.gettempdir()) / f"4thealth_dr_{job_id}.lock"
    try:
        fh = open(lock_path, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return None


# ── Core execution ────────────────────────────────────────────────────────────


def _execute_job(job_id: str) -> None:
    lock_fh = _try_acquire_job_lock(job_id)
    if lock_fh is None:
        app_log(
            "INFO",
            "device_review_scheduler",
            f"Job {job_id} already running — skipping",
        )
        return
    _running_jobs.add(job_id)
    try:
        with _lock:
            jobs = _load()
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            app_log("ERROR", "device_review_scheduler", f"Job {job_id} not found")
            return

        adom = job["adom"]
        fmt = job.get("format", "pdf")
        email = job["email"]
        checks = job.get("checks") or []
        check_params = job.get("check_params") or {}

        app_log(
            "INFO",
            "device_review_scheduler",
            f"Running scheduled Device Review: adom={adom} format={fmt} to={email}",
        )

        results = _bulk_device_review_adom(adom, checks, check_params, max_workers=4)

        all_rows = [r for dev in results for r in dev.get("rows", [])]
        fail_count = sum(1 for r in all_rows if r.get("result") in ("FAIL", "INSECURE"))

        record: dict[str, Any] = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "ok",
            "devices_total": len(results),
            "devices_reviewed": sum(1 for d in results if not d.get("error")),
            "total_findings": len(all_rows),
            "fail_count": fail_count,
        }

        generated_at = record["ran_at"]
        subject = f"4THealth Device Review — {adom} — {generated_at[:10]}"
        body_html = _build_summary_html(adom, results, generated_at)
        attachment = _build_attachment_dr(adom, fmt, results, generated_at)

        _send_email(email, subject, body_html, [attachment])
        _append_run(job_id, record)
        from app.smtp_client import load_smtp_config as _load_smtp_cfg

        retention = _load_smtp_cfg().get("run_history_days", 30)
        _prune_runs(job_id, retention_days=retention)
        app_log(
            "INFO",
            "device_review_scheduler",
            f"Device Review report sent: adom={adom} devices={len(results)} "
            f"findings={len(all_rows)} fails={fail_count} to={email}",
        )

    except Exception as exc:
        record = {
            "ran_at": datetime.datetime.utcnow().isoformat() + "Z",
            "status": "error",
            "error": str(exc),
        }
        _append_run(job_id, record)
        app_log(
            "ERROR",
            "device_review_scheduler",
            f"Device Review scheduled job {job_id} failed: {exc}",
        )
    finally:
        _running_jobs.discard(job_id)
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()
        except Exception:
            pass


# ── Email builders ────────────────────────────────────────────────────────────


def _fmt_detail(row: dict) -> str:
    """Return display text for the Detail column.

    Most checks populate `detail` directly. Interface Protocols leaves `detail`
    empty and puts protocol info in the `protocols` list instead — fall back to
    formatting that list so the report is not blank for those rows.
    """
    detail = row.get("detail", "")
    if detail:
        return detail
    protocols = row.get("protocols") or []
    if not protocols:
        return ""
    parts = []
    for p in protocols:
        name = p.get("name", "")
        secure = p.get("secure")
        if secure is False:
            parts.append(f"{name} (insecure)")
        else:
            parts.append(name)
    return ", ".join(parts)


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_RESULT_COLOR = {
    "PASS": "#166534",
    "FAIL": "#991b1b",
    "INSECURE": "#991b1b",
    "WARN": "#92400e",
    "CONFIG_MISSING": "#92400e",
    "INFO": "#1e40af",
}


def _build_summary_html(adom: str, results: list[dict], generated_at: str) -> str:
    all_rows = [r for dev in results for r in dev.get("rows", [])]
    by_check: dict[str, dict] = {}
    for row in all_rows:
        check = row.get("check", "Unknown")
        if check not in by_check:
            by_check[check] = {
                "PASS": 0,
                "FAIL": 0,
                "INSECURE": 0,
                "WARN": 0,
                "CONFIG_MISSING": 0,
                "INFO": 0,
            }
        result = row.get("result", "")
        if result in by_check[check]:
            by_check[check][result] += 1

    rows_html = ""
    for check, counts in sorted(by_check.items()):
        fail = counts["FAIL"] + counts["INSECURE"]
        warn = counts["WARN"] + counts["CONFIG_MISSING"]
        rows_html += (
            f"<tr><td style='padding:4px 8px'>{check}</td>"
            f"<td style='padding:4px 8px;color:#166534'>{counts['PASS']}</td>"
            f"<td style='padding:4px 8px;color:#991b1b'>{fail}</td>"
            f"<td style='padding:4px 8px;color:#92400e'>{warn}</td></tr>\n"
        )

    errors = [d.get("device", "unknown") for d in results if d.get("error")]
    error_note = ""
    if errors:
        error_note = (
            f"<p style='color:#991b1b'>Errors on devices: {', '.join(errors)}</p>"
        )

    return f"""
<h2 style="font-family:sans-serif">4THealth Device Review — {adom}</h2>
<p style="font-family:sans-serif;color:#6b7280">Generated: {generated_at}</p>
<p style="font-family:sans-serif">Devices scanned: {len(results)}</p>
{error_note}
<table style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
  <thead>
    <tr style="background:#f3f4f6">
      <th style="padding:4px 8px;text-align:left">Check</th>
      <th style="padding:4px 8px">Pass</th>
      <th style="padding:4px 8px">Fail/Insecure</th>
      <th style="padding:4px 8px">Warn</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
<p style="font-family:sans-serif;font-size:11px;color:#9ca3af;margin-top:16px">
  See attached report for full findings detail.
</p>"""


def _build_attachment_dr(
    adom: str, fmt: str, results: list[dict], generated_at: str
) -> dict:
    all_rows = [r for dev in results for r in dev.get("rows", [])]
    safe_adom = adom.replace(" ", "_")
    date_str = generated_at[:10]

    if fmt == "json":
        payload = json.dumps(
            {
                "report_type": "device_review",
                "adom": adom,
                "exported_at": generated_at,
                "rows": all_rows,
            },
            indent=2,
        ).encode()
        return {
            "filename": f"device_review_{safe_adom}_{date_str}.json",
            "data": payload,
            "mimetype": "application/json",
        }

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["# 4THealth Device Review"])
        w.writerow([f"# ADOM: {adom}"])
        w.writerow([f"# Generated: {generated_at}"])
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

    # pdf → styled HTML
    html = _build_pdf_html_dr(adom, all_rows, generated_at)
    return {
        "filename": f"device_review_{safe_adom}_{date_str}.html",
        "data": html.encode(),
        "mimetype": "text/html",
    }


def _build_pdf_html_dr(adom: str, rows: list[dict], generated_at: str) -> str:
    rows_html = ""
    for row in rows:
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
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body{{font-family:sans-serif;font-size:12px;color:#111}}
  h1{{font-size:18px;margin-bottom:4px}}
  .meta{{color:#6b7280;margin-bottom:16px;font-size:11px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #e5e7eb;padding:4px 8px;text-align:left}}
  th{{background:#f3f4f6;font-weight:600}}
  tr:nth-child(even){{background:#fafafa}}
</style>
</head>
<body>
<h1>4THealth Device Review Scheduler</h1>
<div class="meta">
  ADOM: {adom} &nbsp;|&nbsp;
  Devices scanned: {len({r.get("device") for r in rows})} &nbsp;|&nbsp;
  Total findings: {len(rows)} &nbsp;|&nbsp;
  Generated: {generated_at}
</div>
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


# ── APScheduler integration ───────────────────────────────────────────────────


def _apscheduler_id(job_id: str) -> str:
    return f"dr_{job_id}"


def _register(job: dict) -> None:
    if _scheduler is None:
        return
    from apscheduler.triggers.cron import CronTrigger

    day_map = {
        "SUN": "sun",
        "MON": "mon",
        "TUE": "tue",
        "WED": "wed",
        "THU": "thu",
        "FRI": "fri",
        "SAT": "sat",
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


def _unregister(job_id: str) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_apscheduler_id(job_id))
    except Exception:
        pass


def init_scheduler(app) -> None:
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    _scheduler = BackgroundScheduler(daemon=True)
    jobs = _load()
    for job in jobs:
        if job.get("enabled"):
            try:
                _register(job)
            except Exception as exc:
                app_log(
                    "ERROR",
                    "device_review_scheduler",
                    f"Failed to register job {job.get('id', '?')}: {exc}",
                )
    _scheduler.start()
    app_log(
        "INFO",
        "device_review_scheduler",
        f"Device Review scheduler started with "
        f"{sum(1 for j in jobs if j.get('enabled'))} active jobs",
    )
