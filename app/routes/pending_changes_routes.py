"""DIFF (BETA) tab — shows FortiManager install-pending diffs per device.

Page:
  GET  /pending-changes

API (JSON, all read-only):
  GET  /api/pending-changes/adoms
       returns: [{name, desc}, ...]

  GET  /api/pending-changes/adoms/<adom>/devices
       returns: [{name, ip, platform, version, conf_status, db_status, pkg_status, serial}, ...]
       Served from pending_status_cache (30-min background refresh); falls back to live
       FMG fetch on cold start.

  POST /api/pending-changes/adoms/<adom>/device/<device>/preview
       returns: {task_id: str}  — starts async FMG chain, poll GET /task/<task_id> for result

  GET  /api/pending-changes/task/<task_id>
       returns: {status: "running"|"done"|"error", step: str, result: dict|null, error: str|null}
       Task entries are evicted after 10 minutes.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, render_template, session, jsonify

from app import registry
from app.decorators import tab_required, check_adom_access
from app.fmg_client import FMGError, parse_preview_diff
from app.fmg_helpers import make_client
from app.groups import get_allowed_adoms
from app.security import internal_api_error, upstream_api_error

bp = Blueprint("pending_changes", __name__)

registry.register(
    "pending_changes", "DIFF (BETA)", "pending_changes.pending_changes_page"
)

# ── Async preview task store ──────────────────────────────────────────────────
# Keyed by task_id (UUID str) → {status, step, result, error, created_at}
_PREVIEW_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()
_TASK_TTL_SECS = 600  # evict completed/failed entries after 10 minutes


def _evict_old_tasks() -> None:
    now = time.monotonic()
    with _TASKS_LOCK:
        expired = [
            k
            for k, v in _PREVIEW_TASKS.items()
            if now - v["created_at"] > _TASK_TTL_SECS
        ]
        for k in expired:
            del _PREVIEW_TASKS[k]


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/pending-changes")
@tab_required("pending_changes")
def pending_changes_page():
    return render_template("pending_changes.html", user=session["user"])


# ── API: ADOM list ────────────────────────────────────────────────────────────


@bp.route("/api/pending-changes/adoms")
@tab_required("pending_changes")
def pending_changes_adoms():
    try:
        with make_client() as client:
            raw = client.get_adoms()
        items = [
            {"name": a.get("name", a.get("adom", "")), "desc": a.get("desc", "")}
            for a in raw
            if isinstance(a, dict)
        ]
        items = [
            i for i in items if i["name"] and not i["name"].lower().startswith("forti")
        ]
        allowed = get_allowed_adoms(
            session.get("user", ""), ad_groups=session.get("ad_groups", [])
        )
        if allowed is not None:
            items = [i for i in items if i["name"] in allowed]
        return jsonify(items)
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)


# ── API: device list with sync status ─────────────────────────────────────────


@bp.route("/api/pending-changes/adoms/<adom>/devices")
@tab_required("pending_changes")
def pending_changes_devices(adom: str):
    if err := check_adom_access(adom):
        return err
    try:
        from app.pending_status_cache import get_cached_devices

        cached = get_cached_devices(adom)
        if cached is not None:
            return jsonify(cached)

        # Cache cold (first startup) — fall back to live fetch
        with make_client() as client:
            raw = client.get_devices_with_sync_status(adom)

            seen: set[str] = set()
            base_devices = []
            for d in raw:
                if not isinstance(d, dict):
                    continue
                name = d.get("name", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                os_ver = d.get("os_ver", 0)
                mr = d.get("mr")
                patch = d.get("patch")
                major = (
                    int(os_ver) // 100
                    if str(os_ver).isdigit() and int(os_ver) >= 100
                    else os_ver
                )
                if mr is not None and patch is not None:
                    version = f"v{major}.{mr}.{patch}"
                elif mr is not None:
                    version = f"v{major}.{mr}"
                else:
                    version = "n/a"
                embedded_vdoms = d.get("vdom") or []
                vdom_list = (
                    [
                        v.get("name", "root")
                        for v in embedded_vdoms
                        if isinstance(v, dict) and v.get("name")
                    ]
                    if embedded_vdoms
                    else ["root"]
                )
                base_devices.append(
                    {
                        "name": name,
                        "ip": d.get("ip", d.get("mgmt_ip", "")),
                        "platform": d.get("platform_str", d.get("platform", "")),
                        "version": version,
                        "conf_status": d.get("conf_status", "unknown"),
                        "db_status": d.get("db_status", "unknown"),
                        "serial": d.get("sn", d.get("serial", "")),
                        "_vdom_list": vdom_list,
                    }
                )

            def _fetch_pkg(entry: dict) -> tuple[str, str]:
                try:
                    return entry["name"], client.get_device_pkg_status(
                        adom, entry["name"], entry["_vdom_list"]
                    )
                except Exception:
                    return entry["name"], ""

            pkg_map: dict[str, str] = {}
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(_fetch_pkg, e): e["name"] for e in base_devices}
                for fut in as_completed(futures):
                    name, status = fut.result()
                    pkg_map[name] = status

        devices = [
            {k: v for k, v in d.items() if k != "_vdom_list"}
            | {"pkg_status": pkg_map.get(d["name"], "")}
            for d in base_devices
        ]
        return jsonify(devices)
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)


# ── API: install preview ───────────────────────────────────────────────────────


@bp.route("/api/pending-changes/adoms/<adom>/device/<device>/preview", methods=["POST"])
@tab_required("pending_changes")
def pending_changes_preview(adom: str, device: str):
    if err := check_adom_access(adom):
        return err

    _evict_old_tasks()
    task_id = str(uuid.uuid4())
    with _TASKS_LOCK:
        _PREVIEW_TASKS[task_id] = {
            "status": "running",
            "step": "Starting…",
            "result": None,
            "error": None,
            "created_at": time.monotonic(),
        }

    def _run(task_id=task_id, adom=adom, device=device):
        def _set_step(msg: str) -> None:
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id]["step"] = msg

        try:
            _set_step("Fetching device info…")
            with make_client() as client:
                raw_devices = client.get_devices_with_sync_status(adom)
                device_meta = next(
                    (
                        d
                        for d in raw_devices
                        if d.get("name", "").lower() == device.lower()
                    ),
                    {},
                )
                _set_step("Checking package status…")
                pkg_status = client.get_package_status(adom, device)
                _set_step("Staging policy package…")
                raw = client.get_install_preview(adom, device)

            _set_step("Parsing diff…")
            parsed = parse_preview_diff(raw)
            result = {
                "device": device,
                "ip": device_meta.get("ip", device_meta.get("mgmt_ip", "")),
                "conf_status": device_meta.get("conf_status", "unknown"),
                "db_status": device_meta.get("db_status", "unknown"),
                "pkg_status": pkg_status,
                "summary": parsed["summary"],
                "vdoms": parsed["vdoms"],
                "raw": parsed["raw"],
            }
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id].update(
                        {"status": "done", "step": "Done", "result": result}
                    )
        except Exception as exc:
            with _TASKS_LOCK:
                if task_id in _PREVIEW_TASKS:
                    _PREVIEW_TASKS[task_id].update(
                        {"status": "error", "step": "Failed", "error": str(exc)}
                    )

    t = threading.Thread(target=_run, name=f"preview_{task_id[:8]}", daemon=True)
    t.start()
    return jsonify({"task_id": task_id})


@bp.route("/api/pending-changes/task/<task_id>")
@tab_required("pending_changes")
def pending_changes_task_status(task_id: str):
    _evict_old_tasks()
    with _TASKS_LOCK:
        entry = _PREVIEW_TASKS.get(task_id)
    if entry is None:
        return jsonify({"error": "Task not found or expired"}), 404
    return jsonify(
        {
            "status": entry["status"],
            "step": entry["step"],
            "result": entry["result"],
            "error": entry["error"],
        }
    )
