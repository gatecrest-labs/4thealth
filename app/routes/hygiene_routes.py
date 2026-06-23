"""Rule Review tab — read-only policy analysis routes.

Page:
  GET  /hygiene

API (JSON, all read-only):
  GET  /api/hygiene/adoms/<adom>/packages        list policy packages
  POST /api/hygiene/run
       body: { adom, package, checks: [str, ...] }
       returns: { findings: [...], total: int, policy_count: int }
"""

from flask import Blueprint, render_template, session, jsonify, request
from app.decorators import tab_required, check_adom_access
from app.fmg_helpers import make_client
from app.fmg_client import FMGError
from app.hygiene import run_checks, CHECKS, _status, _action
from app import registry
from app.security import internal_api_error, upstream_api_error

bp = Blueprint("hygiene", __name__)

registry.register("rule_hygiene", "Rule Review", "hygiene.hygiene_page")


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/hygiene")
@tab_required("rule_hygiene")
def hygiene_page():
    return render_template("hygiene.html", user=session["user"], checks=CHECKS)


# ── API: list packages ────────────────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/packages")
@tab_required("rule_hygiene")
def hygiene_packages(adom: str):
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            raw = client.get_policy_packages(adom)
        packages = []
        for pkg in raw:
            if not isinstance(pkg, dict):
                continue
            name = pkg.get("name", "")
            path = pkg.get("path", name)
            pkg_type = (pkg.get("type") or "").lower()
            if pkg_type != "folder" and name:
                packages.append({"name": name, "path": path})
        return jsonify(packages)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)


# ── API: raw package list (debug) ────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/packages/raw")
@tab_required("rule_hygiene")
def hygiene_packages_raw(adom: str):
    """Return the unfiltered FMG response — useful for diagnosing missing packages."""
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            raw = client._get(f"/pm/pkg/adom/{adom}")
        return jsonify(raw)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)


def _pkg_path(data: dict) -> str:
    """Extract the folder-qualified package path from a request body."""
    return (data.get("path") or data.get("package") or "").strip()


def _addr_subnet(ao: dict) -> str:
    """Return the best subnet string for an address object.

    Regular objects carry 'subnet' or 'ip-range' at the top level.
    FortiGate device-type objects (managed devices) store their management IP
    in dynamic_mapping[0]['subnet'] — fall back to that when the top-level
    field is absent or empty.
    """
    subnet = ao.get("subnet") or ao.get("ip-range") or ""
    if isinstance(subnet, list):
        subnet = " ".join(str(x) for x in subnet)
    subnet = str(subnet).strip()
    if subnet:
        return subnet
    # FortiGate / dynamic objects — first mapping holds the mgmt IP
    mappings = ao.get("dynamic_mapping") or []
    if isinstance(mappings, list) and mappings:
        first = mappings[0] if isinstance(mappings[0], dict) else {}
        fallback = first.get("subnet") or first.get("ip-range") or ""
        if isinstance(fallback, list):
            fallback = " ".join(str(x) for x in fallback)
        fallback = str(fallback).strip()
        if fallback:
            return fallback
    return ""


# ── API: raw policy list (debug) ─────────────────────────────────────────────


@bp.route("/api/hygiene/policies/raw", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_policies_raw():
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    path = _pkg_path(data)
    if not adom or not path:
        return jsonify({"error": "adom and package/path are required"}), 400
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            raw = client._get(f"/pm/config/adom/{adom}/pkg/{path}/firewall/policy")
        return jsonify({"adom": adom, "path": path, "data": raw})
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)


# ── API: policy list ─────────────────────────────────────────────────────────


@bp.route("/api/hygiene/policies", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_policies():
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    path = _pkg_path(data)
    if not adom or not path:
        return jsonify({"error": "adom and package/path are required"}), 400
    if err := check_adom_access(adom):
        return err
    # Phase 1: fetch ONLY the flat policy list — no pblock rules, no objects.
    # Both are deferred to separate requests so this call stays fast even for
    # large ADOMs like OT-SERVICES with many/large policy blocks.
    try:
        with make_client() as client:
            raw = client.get_policies(adom, path)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    def _names(val):
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [(i.get("name", str(i)) if isinstance(i, dict) else str(i)) for i in val]

    def _build_rule(p, idx):
        srcaddr = _names(p.get("srcaddr") or p.get("src_addr"))
        dstaddr = _names(p.get("dstaddr") or p.get("dst_addr"))
        service = _names(p.get("service") or p.get("services"))
        return {
            "seq": p.get("policyid", idx + 1),
            "id": str(p.get("policyid", idx + 1)),
            "name": p.get("name") or "",
            "status": _status(p),
            "action": _action(p),
            "srcaddr": srcaddr,
            "dstaddr": dstaddr,
            "service": service,
            "fsso_groups": _names(p.get("fsso-groups")),
            "comment": p.get("comments") or p.get("comment") or "",
            "srcintf": _names(p.get("srcintf")),
            "dstintf": _names(p.get("dstintf")),
        }

    try:
        policies = []
        pblock_names = []
        for idx, p in enumerate(raw):
            if not isinstance(p, dict):
                continue

            block_name = p.get("_policy_block")
            if block_name and str(block_name).strip():
                block_name = str(block_name).strip()
                # Emit a placeholder — rules are populated by the /pblocks request
                if block_name not in pblock_names:
                    pblock_names.append(block_name)
                policies.append(
                    {
                        "policy_block": block_name,
                        "assigned": None,  # unknown until pblocks load
                        "rules": [],  # populated by deferred /pblocks fetch
                    }
                )
                continue

            policies.append(_build_rule(p, idx))

        # FortiGate always has an implicit deny-all at the bottom of every policy package.
        # It is not returned by the FMG API, so we append it synthetically.
        policies.append(
            {
                "seq": "implicit",
                "id": "implicit",
                "name": "Implicit Deny",
                "status": "enable",
                "action": "deny",
                "srcaddr": ["all"],
                "dstaddr": ["all"],
                "service": ["ALL"],
                "fsso_groups": [],
                "comment": "Default implicit deny — all unmatched traffic is dropped",
                "srcintf": ["any"],
                "dstintf": ["any"],
                "implicit": True,
            }
        )

        return jsonify(
            {"policies": policies, "total": len(policies), "pblock_names": pblock_names}
        )
    except Exception as exc:
        return internal_api_error("hygiene", exc)


# ── API: pblock rules (deferred, called after policy table renders) ───────────


@bp.route("/api/hygiene/policies/pblocks", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_policy_pblocks():
    """Return rules for a list of pblock names in a given ADOM.

    Called after the policy table is already visible so large pblock sets
    don't block the initial load.  Returns:
      pblocks – {block_name: [{rule}, ...]}
    """
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    names = data.get("names") or []
    if not adom:
        return jsonify({"error": "adom is required"}), 400
    if not isinstance(names, list):
        return jsonify({"error": "names must be a list"}), 400
    if err := check_adom_access(adom):
        return err

    def _names(val):
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [(i.get("name", str(i)) if isinstance(i, dict) else str(i)) for i in val]

    def _build_rule(p, idx):
        srcaddr = _names(p.get("srcaddr") or p.get("src_addr"))
        dstaddr = _names(p.get("dstaddr") or p.get("dst_addr"))
        service = _names(p.get("service") or p.get("services"))
        return {
            "seq": p.get("policyid", idx + 1),
            "id": str(p.get("policyid", idx + 1)),
            "name": p.get("name") or "",
            "status": _status(p),
            "action": _action(p),
            "srcaddr": srcaddr,
            "dstaddr": dstaddr,
            "service": service,
            "fsso_groups": _names(p.get("fsso-groups")),
            "comment": p.get("comments") or p.get("comment") or "",
            "srcintf": _names(p.get("srcintf")),
            "dstintf": _names(p.get("dstintf")),
        }

    try:
        pblocks: dict[str, list] = {}
        with make_client() as client:
            for block_name in names:
                block_name = str(block_name).strip()
                if not block_name:
                    continue
                try:
                    raw = client.get_pblock_policies(adom, block_name)
                    pblocks[block_name] = [
                        _build_rule(r, i)
                        for i, r in enumerate(raw)
                        if isinstance(r, dict)
                    ]
                except Exception:
                    pblocks[block_name] = []
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    return jsonify({"pblocks": pblocks})


# ── API: object expansion maps (deferred, called after policy table renders) ──


@bp.route("/api/hygiene/policies/objects", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_policy_objects():
    """Return addr/svc group and subnet maps for a given ADOM.

    Called after the policy table is already visible so large ADOMs don't
    block the initial load.  Returns:
      addr_grp_map   – {name: [member, ...]}
      svc_grp_map    – {name: [member, ...]}
      addr_detail_map – {name: "subnet/range"}
    """
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    if not adom:
        return jsonify({"error": "adom is required"}), 400
    if err := check_adom_access(adom):
        return err
    try:
        with make_client() as client:
            addr_objects = client.get_address_objects(adom)
            addr_groups = client.get_address_groups(adom)
            svc_groups = client.get_service_groups(adom)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    addr_grp_map: dict[str, list[str]] = {}
    for ag in addr_groups:
        if not isinstance(ag, dict):
            continue
        gname = ag.get("name", "")
        members = ag.get("member", []) or []
        if isinstance(members, list):
            addr_grp_map[gname] = [
                (m.get("name") if isinstance(m, dict) else str(m)) for m in members
            ]

    svc_grp_map: dict[str, list[str]] = {}
    for sg in svc_groups:
        if not isinstance(sg, dict):
            continue
        gname = sg.get("name", "")
        members = sg.get("member", []) or []
        if isinstance(members, list):
            svc_grp_map[gname] = [
                (m.get("name") if isinstance(m, dict) else str(m)) for m in members
            ]

    addr_detail_map: dict[str, str] = {}
    for ao in addr_objects:
        if not isinstance(ao, dict):
            continue
        n = ao.get("name", "")
        subnet = _addr_subnet(ao)
        if n and subnet:
            addr_detail_map[n] = subnet

    return jsonify(
        {
            "addr_grp_map": addr_grp_map,
            "svc_grp_map": svc_grp_map,
            "addr_detail_map": addr_detail_map,
        }
    )


# ── API: object lookup ───────────────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/objects/lookup", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_object_lookup(adom: str):
    """Search address objects, address groups, service objects, and service groups.

    Body: { "query": "search string" }
    Returns: { "objects": [ { name, type, category, detail, members } ] }
    """
    if err := check_adom_access(adom):
        return err

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip().lower()
    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        with make_client() as client:
            addr_objects = client.get_address_objects(adom)
            addr_groups = client.get_address_groups(adom)
            svc_objects = client.get_service_objects(adom)
            svc_groups = client.get_service_groups(adom)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    # Build address detail map so group members can show their IPs
    addr_detail_map: dict[str, str] = {}
    for ao in addr_objects:
        if not isinstance(ao, dict):
            continue
        n = ao.get("name", "")
        subnet = _addr_subnet(ao)
        if n and subnet:
            addr_detail_map[n] = subnet

    # Build service detail map so service-group members can show port info
    svc_detail_map: dict[str, str] = {}
    for so in svc_objects:
        if not isinstance(so, dict):
            continue
        n = so.get("name", "")
        proto = so.get("protocol", "")
        tcp_port = so.get("tcp-portrange", "")
        udp_port = so.get("udp-portrange", "")
        parts = []
        if proto:
            parts.append(str(proto))
        if tcp_port:
            parts.append(f"TCP {tcp_port}")
        if udp_port:
            parts.append(f"UDP {udp_port}")
        if n and parts:
            svc_detail_map[n] = ", ".join(parts)

    results = []

    for ao in addr_objects:
        if not isinstance(ao, dict):
            continue
        name = ao.get("name", "")
        if not name or query not in name.lower():
            continue
        subnet = _addr_subnet(ao)
        obj_type = ao.get("type", "ipmask")
        results.append(
            {
                "name": name,
                "type": "object",
                "category": "address",
                "detail": subnet,
                "subtype": str(obj_type),
                "members": [],
            }
        )

    for ag in addr_groups:
        if not isinstance(ag, dict):
            continue
        name = ag.get("name", "")
        if not name or query not in name.lower():
            continue
        raw_members = ag.get("member", []) or []
        members = [
            {
                "name": (m.get("name") if isinstance(m, dict) else str(m)),
                "detail": addr_detail_map.get(
                    m.get("name") if isinstance(m, dict) else str(m), ""
                ),
            }
            for m in raw_members
        ]
        results.append(
            {
                "name": name,
                "type": "group",
                "category": "address",
                "detail": f"{len(members)} member{'s' if len(members) != 1 else ''}",
                "subtype": "addrgrp",
                "members": members,
            }
        )

    for so in svc_objects:
        if not isinstance(so, dict):
            continue
        name = so.get("name", "")
        if not name or query not in name.lower():
            continue
        proto = so.get("protocol", "")
        tcp_port = so.get("tcp-portrange", "")
        udp_port = so.get("udp-portrange", "")
        detail_parts = []
        if proto:
            detail_parts.append(str(proto))
        if tcp_port:
            detail_parts.append(f"TCP {tcp_port}")
        if udp_port:
            detail_parts.append(f"UDP {udp_port}")
        results.append(
            {
                "name": name,
                "type": "object",
                "category": "service",
                "detail": ", ".join(detail_parts) or "—",
                "subtype": "service",
                "members": [],
            }
        )

    for sg in svc_groups:
        if not isinstance(sg, dict):
            continue
        name = sg.get("name", "")
        if not name or query not in name.lower():
            continue
        raw_members = sg.get("member", []) or []
        members = [
            {
                "name": (m.get("name") if isinstance(m, dict) else str(m)),
                "detail": svc_detail_map.get(
                    m.get("name") if isinstance(m, dict) else str(m), ""
                ),
            }
            for m in raw_members
        ]
        results.append(
            {
                "name": name,
                "type": "group",
                "category": "service",
                "detail": f"{len(members)} member{'s' if len(members) != 1 else ''}",
                "subtype": "svcgrp",
                "members": members,
            }
        )

    results.sort(key=lambda r: r["name"].lower())
    return jsonify({"objects": results, "total": len(results)})


# ── API: run checks ───────────────────────────────────────────────────────────


@bp.route("/api/hygiene/run", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_run():
    data = request.get_json(silent=True) or {}
    adom = (data.get("adom") or "").strip()
    path = _pkg_path(data)
    checks = data.get("checks", list(CHECKS.keys()))

    if not adom or not path:
        return jsonify({"error": "adom and package are required"}), 400
    if err := check_adom_access(adom):
        return err

    valid_checks = [c for c in checks if c in CHECKS]
    if not valid_checks:
        return jsonify({"error": "No valid check keys provided"}), 400

    try:
        with make_client() as client:
            policies = client.get_policies(adom, path)
            pkg_settings = client.get_pkg_settings(adom, path)

            # For the unhit check, FMG's stored _hitcount is only updated when
            # FMG syncs stats from the device — which may be stale or never run.
            # Fetch live hit counts from each device in scope and overlay them so
            # the check always reflects what the device actually sees.
            if "unhit" in valid_checks:
                scope = client.get_pkg_scope_members(adom, path)
                live_hits: dict[int, int] = {}
                for member in scope[:10]:
                    dev = (
                        member.get("name", "")
                        if isinstance(member, dict)
                        else str(member)
                    )
                    vdom = (
                        member.get("vdom", "root")
                        if isinstance(member, dict)
                        else "root"
                    )
                    if not dev:
                        continue
                    for pid, count in client.get_live_policy_hits(
                        adom, dev, vdom
                    ).items():
                        live_hits[pid] = live_hits.get(pid, 0) + count
                if live_hits:
                    for p in policies:
                        pid = p.get("policyid")
                        if pid is not None:
                            p["_hitcount"] = live_hits.get(
                                int(pid), p.get("_hitcount") or 0
                            )
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    findings = run_checks(policies, valid_checks, pkg_settings=pkg_settings)

    # Build a lookup so each finding can carry its rule's detail fields.
    # Shadow findings already carry shadow_rule/shadowing_rule; all others get rule_detail.
    _policy_by_id: dict[str, dict] = {}
    for p in policies:
        if isinstance(p, dict):
            pid = str(p.get("policyid", ""))
            if pid:
                _policy_by_id[pid] = p

    def _names(val) -> list[str]:
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [(i.get("name", str(i)) if isinstance(i, dict) else str(i)) for i in val]

    for f in findings:
        if "shadow_rule" in f or "rule_detail" in f:
            continue
        p = _policy_by_id.get(f["policy_id"])
        if not p:
            continue
        f["rule_detail"] = {
            "id": str(p.get("policyid", "?")),
            "name": str(p.get("name") or ""),
            "status": _status(p),
            "action": _action(p),
            "srcaddr": _names(p.get("srcaddr") or p.get("src_addr")),
            "dstaddr": _names(p.get("dstaddr") or p.get("dst_addr")),
            "service": _names(p.get("service") or p.get("services")),
            "srcintf": _names(p.get("srcintf")),
            "dstintf": _names(p.get("dstintf")),
            "fsso_groups": _names(p.get("fsso-groups")),
            "comment": str(p.get("comments") or p.get("comment") or ""),
        }

    pkg_display = path.rsplit("/", 1)[-1]
    return jsonify(
        {
            "adom": adom,
            "package": pkg_display,
            "checks_run": valid_checks,
            "policy_count": len(policies),
            "total": len(findings),
            "findings": findings,
        }
    )
