"""Shared route decorators — import these instead of redefining in every blueprint.

Usage::

    from app.decorators import login_required, tab_required, admin_required

    @bp.route("/my-page")
    @tab_required("my_tab")
    def my_page():
        ...

    @bp.route("/admin-only")
    @admin_required
    def admin_only():
        ...
"""
from __future__ import annotations
from functools import wraps
from flask import session, redirect, url_for, abort, jsonify, request


def login_required(f):
    """Redirect to /login when no session exists."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def tab_required(tab_key: str):
    """Allow only users who have permission for ``tab_key`` (or admin role)."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Not authenticated"}), 401
                return redirect(url_for("auth.login", next=request.path))
            if session.get("role") != "admin" and tab_key not in set(session.get("allowed_tabs", [])):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Access denied"}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    """Allow only users with role == 'admin'; return 403 or redirect otherwise."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.login", next=request.path))
        if session.get("role") != "admin":
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Admin role required"}), 403
            abort(403)
        return f(*args, **kwargs)
    return decorated


def check_adom_access(adom: str) -> "tuple | None":
    """Return a 403 JSON response tuple if the current user cannot access ``adom``.

    Returns None when access is permitted (caller should proceed normally).
    Always permits admin users.  For non-admins, delegates to groups.user_can_access_adom.

    Usage inside a route::

        if err := check_adom_access(adom):
            return err
    """
    if session.get("role") == "admin":
        return None
    from app.groups import user_can_access_adom
    if not user_can_access_adom(session.get("user", ""), adom):
        return jsonify({"error": f"Access to ADOM '{adom}' is not permitted for your account"}), 403
    return None
