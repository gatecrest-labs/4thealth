"""Device Review tab — read-only interface protocol analysis.

Page:
  GET  /device-review

API (JSON, all read-only):
  GET  /api/device-review/adoms/<adom>/devices
       returns: [{name, ip, platform, version, serial, status}, ...]

  POST /api/device-review/run/device
       body: { adom, device, checks: [str, ...] }
       Single-device run — used by the frontend to drive a per-device progress
       loop for large ADOMs.
       returns: { device, rows: [InterfaceRow, ...] }

  POST /api/device-review/run
       body: { adom, devices: [str, ...], checks: [str, ...] }
             devices: []  means all devices in the ADOM
             checks: absent/null means all registered checks
       returns: { adom, run_at, devices_reviewed, device_count,
                  checks_run, total, rows: [InterfaceRow, ...] }
"""

from __future__ import annotations
import datetime

from flask import Blueprint, render_template, session, jsonify, request
from app.decorators import tab_required, check_adom_access
from app.fmg_helpers import make_client
from app.fmg_client import FMGError
from app.device_review import run_checks, CHECKS_META
from app import registry
from app.security import internal_api_error, upstream_api_error

bp = Blueprint("device_review", __name__)

registry.register("device_review", "Device Review", "device_review.device_review_page")


# ── Page ──────────────────────────────────────────────────────────────────────

@bp.route("/device-review")
@tab_required("device_review")
def device_review_page():
    return render_template(
        "device_review.html",
        user=session["user"],
        checks=CHECKS_META,
    )


# ── API: list devices in an ADOM ──────────────────────────────────────────────

@bp.route("/api/device-review/adoms/<adom>/devices")
@tab_required("device_review")
def device_review_devices(adom: str):
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            raw = client.get_devices(adom)
        devices = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            name = d.get("name", "")
            if not name:
                continue
            # Assemble firmware version the same way api_routes does
            os_ver = d.get("os_ver", 0)
            mr     = d.get("mr")
            patch  = d.get("patch")
            major  = int(os_ver) // 100 if str(os_ver).isdigit() and int(os_ver) >= 100 else os_ver
            if mr is not None and patch is not None and int(patch) >= 0:
                version = f"v{major}.{mr}.{patch}"
            elif mr is not None:
                version = f"v{major}.{mr}"
            else:
                version = ""
            devices.append({
                "name":     name,
                "ip":       d.get("ip", d.get("mgmt_ip", "")),
                "platform": d.get("platform_str", d.get("platform", "")),
                "version":  version,
                "serial":   d.get("sn", d.get("serial", "")),
                "status":   d.get("conn_status", ""),
            })
        return jsonify(devices)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)


# ── API: single-device run (used by the per-device progress loop) ─────────────

@bp.route("/api/device-review/run/device", methods=["POST"])
@tab_required("device_review")
def device_review_run_one():
    data       = request.get_json(silent=True) or {}
    adom       = (data.get("adom") or "").strip()
    device     = (data.get("device") or "").strip()
    check_keys = data.get("checks")

    if not adom or not device:
        return jsonify({"error": "adom and device are required"}), 400
    if err := check_adom_access(adom):
        return err

    valid_keys = {c["key"] for c in CHECKS_META}
    if check_keys is not None:
        check_keys = [k for k in check_keys if k in valid_keys]

    try:
        with make_client() as client:
            ifaces = client.get_device_interfaces_all_vdoms(adom, device)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)

    rows = run_checks(device, ifaces, check_keys)
    return jsonify({"device": device, "rows": rows})


# ── API: bulk run checks ──────────────────────────────────────────────────────

@bp.route("/api/device-review/run", methods=["POST"])
@tab_required("device_review")
def device_review_run():
    data       = request.get_json(silent=True) or {}
    adom       = (data.get("adom") or "").strip()
    devices    = data.get("devices") or []   # [] means "all"
    check_keys = data.get("checks")          # None means "all"

    if not adom:
        return jsonify({"error": "adom is required"}), 400
    if err := check_adom_access(adom):
        return err

    valid_keys = {c["key"] for c in CHECKS_META}
    if check_keys is not None:
        check_keys = [k for k in check_keys if k in valid_keys]
        if not check_keys:
            return jsonify({"error": "No valid check keys provided"}), 400

    try:
        with make_client() as client:
            all_devices = client.get_devices(adom)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)

    # Filter to requested devices (empty list = all)
    if devices:
        device_set = {d.lower() for d in devices}
        all_devices = [
            d for d in all_devices
            if isinstance(d, dict) and d.get("name", "").lower() in device_set
        ]

    rows = []
    reviewed = []

    for dev in all_devices:
        if not isinstance(dev, dict):
            continue
        name = dev.get("name", "")
        if not name:
            continue
        reviewed.append(name)
        try:
            with make_client() as client:
                ifaces = client.get_device_interfaces_all_vdoms(adom, name)
        except Exception:
            ifaces = []

        rows.extend(run_checks(name, ifaces, check_keys))

    run_at     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    checks_run = check_keys if check_keys is not None else [c["key"] for c in CHECKS_META]

    return jsonify({
        "adom":             adom,
        "run_at":           run_at,
        "devices_reviewed": reviewed,
        "device_count":     len(reviewed),
        "checks_run":       checks_run,
        "total":            len(rows),
        "rows":             rows,
    })
