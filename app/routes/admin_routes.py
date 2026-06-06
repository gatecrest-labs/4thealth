"""Admin-only routes.

Page:  GET  /admin
Groups API (JSON):
  GET    /admin/api/groups
  POST   /admin/api/groups           {"name": str, "members": [...], "allowed_tabs": [...],
                                      "adom_restrict": bool, "allowed_adoms": [...]}
  PUT    /admin/api/groups/<name>    {"members": [...], "allowed_tabs": [...],
                                      "adom_restrict": bool, "allowed_adoms": [...]}
  DELETE /admin/api/groups/<name>
  GET    /admin/api/users            list of {username, role} for member picker

ADOM cache (JSON):
  GET    /admin/api/adoms            known ADOM names from the background cache

Logs API (JSON):
  GET    /admin/api/logs?level=INFO&component=auth&limit=500
  POST   /admin/api/logs/level       {"level": "DEBUG"}
  DELETE /admin/api/logs             clears the buffer

Tab registry:
  GET    /admin/api/tabs             known tab keys + display names
"""

from flask import Blueprint, render_template, session, jsonify, request
from app.decorators import admin_required as _admin_required
from app.groups import list_groups, get_group, create_group, update_group, delete_group
from app import registry
from app.auth import list_users
from app.app_logger import (
    app_log, get_log_entries, get_log_level, get_log_levels, set_log_level, clear_log_entries,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ── Page ─────────────────────────────────────────────────────────────────────

@bp.route("/")
@_admin_required
def admin_page():
    app_log("DEBUG", "admin", "Admin page accessed", username=session["user"])
    return render_template("admin.html", user=session["user"])


# ── Groups API ────────────────────────────────────────────────────────────────

@bp.route("/api/groups")
@_admin_required
def api_groups_list():
    return jsonify(list_groups())


@bp.route("/api/groups", methods=["POST"])
@_admin_required
def api_groups_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    members       = data.get("members", [])
    allowed_tabs  = data.get("allowed_tabs", [])
    adom_restrict = bool(data.get("adom_restrict", False))
    allowed_adoms = data.get("allowed_adoms", [])
    try:
        ok = create_group(name, members, allowed_tabs, adom_restrict, allowed_adoms)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not ok:
        return jsonify({"error": f"Group '{name}' already exists"}), 409
    app_log("INFO", "admin", "Group created", by=session["user"], group=name)
    return jsonify(get_group(name)), 201


@bp.route("/api/groups/<name>", methods=["PUT"])
@_admin_required
def api_groups_update(name: str):
    data = request.get_json(silent=True) or {}
    members       = data.get("members", [])
    allowed_tabs  = data.get("allowed_tabs", [])
    adom_restrict = bool(data.get("adom_restrict", False))
    allowed_adoms = data.get("allowed_adoms", [])
    if not update_group(name, members, allowed_tabs, adom_restrict, allowed_adoms):
        return jsonify({"error": f"Group '{name}' not found"}), 404
    app_log("INFO", "admin", "Group updated", by=session["user"], group=name)
    return jsonify(get_group(name))


@bp.route("/api/groups/<name>", methods=["DELETE"])
@_admin_required
def api_groups_delete(name: str):
    if not delete_group(name):
        return jsonify({"error": f"Group '{name}' not found"}), 404
    app_log("INFO", "admin", "Group deleted", by=session["user"], group=name)
    return jsonify({"deleted": name})


# ── ADOM cache (for ADOM access picker) ──────────────────────────────────────

@bp.route("/api/adoms")
@_admin_required
def api_adoms_list():
    """Return the cached list of known ADOMs (used by the group editor)."""
    from app.adom_cache import get_cached
    cached = get_cached()
    return jsonify({
        "adoms":        cached["adoms"],
        "last_updated": cached["last_updated"],
        "status":       cached["status"],
    })


# ── Users API (for member picker) ─────────────────────────────────────────────

@bp.route("/api/users")
@_admin_required
def api_users_list():
    return jsonify(list_users())


# ── Tabs registry ─────────────────────────────────────────────────────────────

@bp.route("/api/tabs")
@_admin_required
def api_tabs_list():
    return jsonify([{"key": k, "name": v} for k, v in registry.known_tabs().items()])


# ── Logs API ──────────────────────────────────────────────────────────────────

@bp.route("/api/logs")
@_admin_required
def api_logs_get():
    level = request.args.get("level") or None
    component = request.args.get("component") or None
    try:
        limit = int(request.args.get("limit", 500))
    except ValueError:
        limit = 500
    entries = get_log_entries(level=level, component=component, limit=limit)
    return jsonify({
        "current_level": get_log_level(),
        "levels": get_log_levels(),
        "count": len(entries),
        "entries": entries,
    })


@bp.route("/api/logs/level", methods=["POST"])
@_admin_required
def api_logs_set_level():
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "").upper()
    try:
        set_log_level(level)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    app_log("INFO", "admin", "Log level changed", by=session["user"], new_level=level)
    return jsonify({"current_level": get_log_level()})


@bp.route("/api/logs", methods=["DELETE"])
@_admin_required
def api_logs_clear():
    clear_log_entries()
    app_log("INFO", "admin", "Log buffer cleared", by=session["user"])
    return jsonify({"cleared": True})
