"""Device Review tab — read-only interface protocol and CIS hardening analysis.

Page:
  GET  /device-review

API (JSON, all read-only):
  GET  /api/device-review/adoms/<adom>/devices
       returns: [{name, ip, platform, version, serial, status}, ...]

  POST /api/device-review/run/device
       body: { adom, device, checks: [str, ...], check_params: {key: {…}} }
       Single-device run — used by the frontend to drive a per-device progress
       loop for large ADOMs.
       returns: { device, rows: [Row, ...] }

  POST /api/device-review/run
       body: { adom, devices: [str, ...], checks: [str, ...],
               check_params: {key: {…}} }
             devices: []  means all devices in the ADOM
             checks: absent/null means all registered checks
             check_params: optional per-check user-supplied values
               e.g. { "ntp_config":    { "expected_servers": ["10.1.1.1"] },
                      "syslog_config": { "expected_servers": ["10.2.2.1"] } }
       returns: { adom, run_at, devices_reviewed, device_count,
                  checks_run, total, rows: [Row, ...] }
"""

from __future__ import annotations
import datetime

from flask import Blueprint, render_template, session, jsonify, request
from app.decorators import tab_required, check_adom_access
from app.fmg_helpers import make_client
from app.fmg_client import FMGError
from app.device_review import run_checks, CHECKS_META, _CHECKS_BY_KEY
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
            os_ver = d.get("os_ver", 0)
            mr = d.get("mr")
            patch = d.get("patch")
            major = (
                int(os_ver) // 100
                if str(os_ver).isdigit() and int(os_ver) >= 100
                else os_ver
            )
            if mr is not None and patch is not None and int(patch) >= 0:
                version = f"v{major}.{mr}.{patch}"
            elif mr is not None:
                version = f"v{major}.{mr}"
            else:
                version = ""
            devices.append(
                {
                    "name": name,
                    "ip": d.get("ip", d.get("mgmt_ip", "")),
                    "platform": d.get("platform_str", d.get("platform", "")),
                    "version": version,
                    "serial": d.get("sn", d.get("serial", "")),
                    "status": d.get("conn_status", ""),
                }
            )
        return jsonify(devices)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _needed_data_keys(check_keys: list[str] | None) -> set[str]:
    """Return the union of data_keys for the selected checks."""
    keys = check_keys if check_keys is not None else [c["key"] for c in CHECKS_META]
    needed: set[str] = set()
    for key in keys:
        entry = _CHECKS_BY_KEY.get(key)
        if entry:
            needed.update(entry.get("data_keys", []))
    return needed


def _fetch_device_data(client, adom: str, device: str, data_keys: set[str]) -> dict:
    """Fetch only the device data blobs required by the selected checks."""
    data: dict = {}
    if "interfaces" in data_keys:
        try:
            data["interfaces"] = client.get_device_interfaces_all_vdoms(adom, device)
        except Exception:
            data["interfaces"] = []
    if "ntp" in data_keys:
        try:
            data["ntp"] = client.get_device_ntp(adom, device)
        except Exception:
            data["ntp"] = {}
    if "syslog" in data_keys:
        try:
            data["syslog"] = client.get_device_syslog(adom, device)
        except Exception:
            data["syslog"] = []
    return data


# ── API: single-device run (used by the per-device progress loop) ─────────────


@bp.route("/api/device-review/run/device", methods=["POST"])
@tab_required("device_review")
def device_review_run_one():
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    device = (data.get("device") or "").strip()
    check_keys = data.get("checks")
    check_params = data.get("check_params") or {}

    if not adom or not device:
        return jsonify({"error": "adom and device are required"}), 400
    if err := check_adom_access(adom):
        return err

    valid_keys = {c["key"] for c in CHECKS_META}
    if check_keys is not None:
        check_keys = [k for k in check_keys if k in valid_keys]

    needed = _needed_data_keys(check_keys)

    try:
        with make_client() as client:
            device_data = _fetch_device_data(client, adom, device, needed)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)

    rows = run_checks(device, device_data, check_keys, check_params)
    return jsonify({"device": device, "rows": rows})


# ── API: bulk run checks ──────────────────────────────────────────────────────


@bp.route("/api/device-review/run", methods=["POST"])
@tab_required("device_review")
def device_review_run():
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    devices = data.get("devices") or []
    check_keys = data.get("checks")
    check_params = data.get("check_params") or {}

    if not adom:
        return jsonify({"error": "adom is required"}), 400
    if err := check_adom_access(adom):
        return err

    valid_keys = {c["key"] for c in CHECKS_META}
    if check_keys is not None:
        check_keys = [k for k in check_keys if k in valid_keys]
        if not check_keys:
            return jsonify({"error": "No valid check keys provided"}), 400

    needed = _needed_data_keys(check_keys)

    try:
        with make_client() as client:
            all_devices = client.get_devices(adom)
    except FMGError as exc:
        return upstream_api_error("device_review", exc)
    except Exception as exc:
        return internal_api_error("device_review", exc)

    if devices:
        device_set = {d.lower() for d in devices}
        all_devices = [
            d
            for d in all_devices
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
                device_data = _fetch_device_data(client, adom, name, needed)
        except Exception:
            device_data = {}

        rows.extend(run_checks(name, device_data, check_keys, check_params))

    run_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    checks_run = (
        check_keys if check_keys is not None else [c["key"] for c in CHECKS_META]
    )

    return jsonify(
        {
            "adom": adom,
            "run_at": run_at,
            "devices_reviewed": reviewed,
            "device_count": len(reviewed),
            "checks_run": checks_run,
            "total": len(rows),
            "rows": rows,
        }
    )
