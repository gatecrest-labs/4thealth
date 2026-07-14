"""Pending Changes tab — shows FortiManager install-pending diffs per device.

Page:
  GET  /pending-changes

API (JSON, all read-only):
  GET  /api/pending-changes/adoms
       returns: [{name, desc}, ...]

  GET  /api/pending-changes/adoms/<adom>/devices
       returns: [{name, ip, platform, version, conf_status, serial}, ...]

  POST /api/pending-changes/adoms/<adom>/device/<device>/preview
       returns: {device, ip, conf_status, summary, vdoms, raw}
"""

from __future__ import annotations

from flask import Blueprint, render_template, session, jsonify

from app import registry
from app.decorators import tab_required, check_adom_access
from app.fmg_client import FMGError, parse_preview_diff
from app.fmg_helpers import make_client
from app.groups import get_allowed_adoms
from app.security import internal_api_error, upstream_api_error

bp = Blueprint("pending_changes", __name__)

registry.register("pending_changes", "Pending Changes", "pending_changes.pending_changes_page")


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
        items = [i for i in items if i["name"] and not i["name"].lower().startswith("forti")]
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
        with make_client() as client:
            raw = client.get_devices_with_sync_status(adom)
        seen: set[str] = set()
        devices = []
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
            devices.append({
                "name": name,
                "ip": d.get("ip", d.get("mgmt_ip", "")),
                "platform": d.get("platform_str", d.get("platform", "")),
                "version": version,
                "conf_status": d.get("conf_status", "unknown"),
                "serial": d.get("sn", d.get("serial", "")),
            })
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
    try:
        with make_client() as client:
            # Fetch device IP for response metadata
            raw_devices = client.get_devices_with_sync_status(adom)
            device_meta = next(
                (d for d in raw_devices if d.get("name", "").lower() == device.lower()),
                {}
            )
            raw = client.get_install_preview(adom, device)
        parsed = parse_preview_diff(raw)
        return jsonify({
            "device": device,
            "ip": device_meta.get("ip", device_meta.get("mgmt_ip", "")),
            "conf_status": device_meta.get("conf_status", "unknown"),
            "summary": parsed["summary"],
            "vdoms": parsed["vdoms"],
            "raw": parsed["raw"],
        })
    except FMGError as exc:
        return upstream_api_error("pending_changes", exc)
    except Exception as exc:
        return internal_api_error("pending_changes", exc)
