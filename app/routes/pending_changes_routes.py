"""DIFF (BETA) tab — shows FortiManager install-pending diffs per device.

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
        with make_client() as client:
            raw = client.get_devices_with_sync_status(adom)

            # Build base device records first (no extra API calls)
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
                # Extract vdom names from the device record already returned by
                # get_devices_with_sync_status — avoids a separate API call per device
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

            # Fetch pkg_status for all devices in parallel — each call is an
            # independent FMG GET, safe to fan out (read-only, no state mutation)
            def _fetch_pkg_status(entry):
                try:
                    return entry["name"], client.get_device_pkg_status(
                        adom, entry["name"], entry["_vdom_list"]
                    )
                except Exception:
                    return entry["name"], ""

            pkg_map: dict[str, str] = {}
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {
                    pool.submit(_fetch_pkg_status, e): e["name"] for e in base_devices
                }
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
    try:
        with make_client() as client:
            # Fetch device IP/status for response metadata
            raw_devices = client.get_devices_with_sync_status(adom)
            device_meta = next(
                (d for d in raw_devices if d.get("name", "").lower() == device.lower()),
                {},
            )
            pkg_status = client.get_package_status(adom, device)
            raw = client.get_install_preview(adom, device)
        parsed = parse_preview_diff(raw)
        return jsonify(
            {
                "device": device,
                "ip": device_meta.get("ip", device_meta.get("mgmt_ip", "")),
                "conf_status": device_meta.get("conf_status", "unknown"),
                "db_status": device_meta.get("db_status", "unknown"),
                "pkg_status": pkg_status,
                "summary": parsed["summary"],
                "vdoms": parsed["vdoms"],
                "raw": parsed["raw"],
            }
        )
    except FMGError as exc:
        msg = str(exc)
        if "timed out" in msg:
            return jsonify(
                {
                    "error": f"Preview timed out for {device} — FMG could not reach the device in time."
                }
            ), 504
        # Surface the raw FMG error in the UI (BETA tab) so operators can diagnose
        # without needing server log access
        upstream_api_error("pending_changes", exc)
        return jsonify({"error": msg}), 502
    except Exception as exc:
        return internal_api_error("pending_changes", exc)
