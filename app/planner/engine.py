# app/planner/engine.py
"""
Analysis engine for the Rule Validation tab.

plan_flow() replaces the per-package analysis loop in rule_review.py's
analyze_flows(). It uses the typed catalog objects from DeviceSnapshot
for set-semantics matching, adds object planning, GroupAppendAlternative
detection, and risk/approval chain.
"""

from __future__ import annotations

import ipaddress

from app.planner import cli_gen, standards
from app.planner.fetch import DeviceSnapshot
from app.planner.insertion import _intf_scoped, plan_insertion
from app.planner.matching import (
    WILDCARD_RANGE,
    PolicyMatcher,
    PortRange,
    _names,
    parse_service_request,
)
from app.planner.models import GroupAppendAlternative, InsertionPlan, ObjectPlan

# ---------------------------------------------------------------------------
# Object planning helpers
# ---------------------------------------------------------------------------


def _normalize_cidr(ip: str) -> str:
    return str(ipaddress.ip_network(ip, strict=False))


def _address_object_plan(role: str, ip: str, snapshot: DeviceSnapshot) -> ObjectPlan:
    cidr = _normalize_cidr(ip)
    existing = snapshot.addr_catalog.exact_match_name(cidr)
    if existing:
        return ObjectPlan(
            role=role,
            action="reuse",
            name=existing,
            obj_type="host" if cidr.endswith("/32") else "network",
            value=cidr,
        )
    if cidr.endswith("/32"):
        name = standards.object_name("host", ip=cidr)
        obj_type = "host"
    else:
        name = standards.object_name("network", ip=cidr)
        obj_type = "network"
    return ObjectPlan(
        role=role,
        action="create",
        name=name,
        obj_type=obj_type,
        value=cidr,
        cli=cli_gen.address_object_cli(name, cidr),
    )


def _service_object_plan(token: str, snapshot: DeviceSnapshot) -> list[ObjectPlan]:
    try:
        ranges = parse_service_request(token)
    except ValueError:
        return [
            ObjectPlan(
                role="service",
                action="reuse",
                name="ALL",
                obj_type="service",
                value=token,
            )
        ]
    if not ranges or any(r.protocol == "ip" for r in ranges):
        return [
            ObjectPlan(
                role="service",
                action="reuse",
                name="ALL",
                obj_type="service",
                value=token,
            )
        ]
    existing = snapshot.svc_catalog.exact_match_name(ranges)
    if existing:
        return [
            ObjectPlan(
                role="service",
                action="reuse",
                name=existing,
                obj_type="service",
                value=token,
            )
        ]
    plans: list[ObjectPlan] = []
    for r in ranges:
        port_expr = str(r.start) if r.start == r.end else f"{r.start}-{r.end}"
        name = standards.object_name("service", proto=r.protocol, port=port_expr)
        try:
            cli = cli_gen.service_object_cli(name, r.protocol, port_expr)
        except ValueError:
            cli = ""
        plans.append(
            ObjectPlan(
                role="service",
                action="create",
                name=name,
                obj_type="service",
                value=f"{r.protocol}/{port_expr}",
                cli=cli,
            )
        )
    return plans


def _dedupe(objs: list[ObjectPlan]) -> list[ObjectPlan]:
    seen: set[str] = set()
    out = []
    for o in objs:
        if o.name not in seen:
            seen.add(o.name)
            out.append(o)
    return out


# ---------------------------------------------------------------------------
# GroupAppendAlternative detection (simplified: scans snapshot packages only)
# ---------------------------------------------------------------------------


def _find_alternative(
    snapshot: DeviceSnapshot,
    matcher: PolicyMatcher,
    src: str,
    dst: str,
    service_ranges: list[PortRange],
    srcintf: str,
    dstintf: str,
) -> GroupAppendAlternative | None:
    """Find a near-miss rule where only one address side is missing.

    Scans packages already in the snapshot — no additional FMG calls.
    Blast-radius count is limited to the same packages (conservative).
    """
    candidates: list[tuple[tuple[int, int, int], GroupAppendAlternative]] = []

    for pkg, policies in snapshot.policies_by_package.items():
        for pol in policies:
            r = matcher.evaluate(pol, src, dst, service_ranges)
            if r.disabled or r.conditional_schedule or r.action != "accept":
                continue
            if r.unknown_refs or r.full_cover:
                continue
            if not _intf_scoped(pol, srcintf, dstintf):
                continue
            _, svc_full = matcher.svc_side(pol, service_ranges)
            if not svc_full:
                continue
            _, src_full = matcher.addr_side(pol, "srcaddr", src)
            _, dst_full = matcher.addr_side(pol, "dstaddr", dst)
            # Check each side independently
            for side, key, failing_full, ok_full, missing_ip in (
                ("destination", "dstaddr", dst_full, src_full, dst),
                ("source", "srcaddr", src_full, dst_full, src),
            ):
                if ok_full and not failing_full:
                    if pol.get(f"{key}-negate", "disable") in ("enable", 1, True):
                        continue
                    other_refs = list(
                        _names(
                            pol.get("srcaddr" if key == "dstaddr" else "dstaddr", [])
                        )
                    )
                    non_all = sum(1 for ref in other_refs if ref.lower() != "all")
                    has_specific = 1 if non_all > 0 else 0
                    group = next(
                        (
                            n
                            for n in _names(pol.get(key, []))
                            if snapshot.addr_catalog.is_group(n)
                        ),
                        None,
                    )
                    member = _address_object_plan(side, missing_ip, snapshot)
                    if group is not None:
                        score: tuple[int, int, int] = (has_specific, -non_all, 0)
                        candidates.append(
                            (
                                score,
                                GroupAppendAlternative(
                                    package=pkg,
                                    policy_id=pol.get("policyid", 0),
                                    policy_name=pol.get("name", ""),
                                    side=side,
                                    group=group,
                                    members=[member],
                                    group_cli=cli_gen.addrgrp_append_cli(
                                        group, [member.name]
                                    ),
                                ),
                            )
                        )
                    else:
                        failing_refs = list(_names(pol.get(key, [])))
                        if not failing_refs or failing_refs == ["all"]:
                            continue
                        score = (has_specific, -non_all, 1)
                        candidates.append(
                            (
                                score,
                                GroupAppendAlternative(
                                    package=pkg,
                                    policy_id=pol.get("policyid", 0),
                                    policy_name=pol.get("name", ""),
                                    side=side,
                                    group=None,
                                    members=[member],
                                    direct_cli=cli_gen.policy_addr_append_cli(
                                        pol.get("policyid", 0), key, [member.name]
                                    ),
                                ),
                            )
                        )

    if not candidates:
        return None
    winner = max(candidates, key=lambda c: c[0])[1]
    # Simplified blast-radius: count other policies in snapshot referencing the group
    if winner.group:
        affected_count = sum(
            1
            for _pkg, pols in snapshot.policies_by_package.items()
            for p in pols
            if p.get("policyid", 0) != winner.policy_id
            and any(
                winner.group in _names(p.get(k, [])) for k in ("srcaddr", "dstaddr")
            )
        )
        winner.affected_policies = [{"count": affected_count}]
        if affected_count:
            winner.warnings.append(
                f"Appending to group {winner.group!r} also affects "
                f"{affected_count} other rule(s) in these packages — review before choosing this option."
            )
    return winner


# ---------------------------------------------------------------------------
# Interface resolution (simple: first interface whose subnet contains the IP)
# ---------------------------------------------------------------------------


def _resolve_interface(ip: str, interfaces: list[dict]) -> str:
    try:
        target = ipaddress.ip_address(ip.split("/")[0])
    except ValueError:
        return ""
    best_prefix = -1
    best_name = ""
    for iface in interfaces:
        if not isinstance(iface, dict):
            continue
        ip_raw = iface.get("ip", iface.get("ipv4_address", ""))
        mask = iface.get("mask", iface.get("netmask", ""))
        if not ip_raw or ip_raw == "0.0.0.0":
            continue
        try:
            if isinstance(ip_raw, str) and " " in ip_raw:
                ip_raw, mask = ip_raw.split(None, 1)
            if mask and mask != "0.0.0.0":
                net = ipaddress.IPv4Network(f"{ip_raw}/{mask}", strict=False)
            elif "/" in ip_raw:
                net = ipaddress.IPv4Network(ip_raw, strict=False)
            else:
                continue
            if target in net and net.prefixlen > best_prefix:
                best_prefix = net.prefixlen
                best_name = iface.get("name", "")
        except ValueError:
            continue
    return best_name


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def plan_flow(
    src: str,
    dst: str,
    service: str,
    snapshot: DeviceSnapshot,
    zone_verdict: dict,
    path_check: dict,
    *,
    pkg_key: str,
    pkg_name: str,
    pkg_path: str,
    ticket_id: str = "",
    zone_domains: dict | None = None,
) -> dict:
    """Analyse one flow against one policy package using set-semantics matching.

    Returns a result dict that is a superset of the old analyze_flows() row
    shape — new keys added, none removed.
    """

    def _err(msg: str) -> dict:
        return {
            "src": src,
            "dst": dst,
            "service": service,
            "adom": snapshot.adom,
            "pkg_path": pkg_path,
            "pkg_name": pkg_name,
            "device": snapshot.device,
            "verdict": "ERROR",
            "notes": [msg],
            "matching_rules": [],
            "modifiable_rules": [],
            "partial_matches": [],
            "suggested_position": None,
            "fortios_cli": "",
            "zone_verdict": zone_verdict.get("verdict", "UNAVAILABLE"),
            "zone_source": zone_verdict.get("source", "none"),
            "zone_src": zone_verdict.get("src_zones", []),
            "zone_dst": zone_verdict.get("dst_zones", []),
            "zone_governing": zone_verdict.get("governing", []),
            "zone_all_policies": zone_verdict.get("all_policies", []),
            "zone_available": zone_verdict.get("available", False),
            "path_in_path": path_check.get("in_path"),
            "path_confidence": path_check.get("confidence", "low"),
            "path_src_iface": path_check.get("src_iface"),
            "path_dst_iface": path_check.get("dst_iface"),
            "path_src_route": path_check.get("src_route"),
            "path_dst_route": path_check.get("dst_route"),
            "path_notes": path_check.get("notes", []),
            "object_plans": [],
            "approval": {},
            "permissiveness_warnings": [],
            "alternative": None,
        }

    try:
        service_ranges = parse_service_request(service) if service else [WILDCARD_RANGE]
    except ValueError as exc:
        return _err(f"Cannot parse service {service!r}: {exc}")

    for _label, _addr in (("src", src), ("dst", dst)):
        if not _addr or not _addr.strip():
            return _err(f"Empty {_label} address")
        try:
            _normalize_cidr(_addr)
        except ValueError as exc:
            return _err(f"Invalid {_label} address {_addr!r}: {exc}")

    policies = snapshot.policies_by_package.get(pkg_key, [])
    matcher = PolicyMatcher(snapshot.addr_catalog, snapshot.svc_catalog)

    srcintf = _resolve_interface(src, snapshot.interfaces)
    dstintf = _resolve_interface(dst, snapshot.interfaces)

    matching: list[dict] = []
    partial: list[dict] = []
    last_permit_seq: int | None = None

    for idx, pol in enumerate(policies):
        if not isinstance(pol, dict):
            continue
        pol_id = pol.get("policyid", idx + 1)
        pol_name = pol.get("name", "")
        r = matcher.evaluate(pol, src, dst, service_ranges)
        if r.action == "accept" and not r.disabled:
            last_permit_seq = pol_id
        if not r.matched:
            continue
        entry = {
            "id": pol_id,
            "name": pol_name,
            "action": r.action,
            "seq": idx + 1,
            "package": pkg_key,
        }
        if r.full_cover and not r.disabled:
            matching.append(entry)
        elif r.action == "accept" and not r.disabled:
            svc_gap = matcher.uncovered_services(pol, service_ranges)
            entry["svc_gap"] = [
                f"{pr.protocol}/{pr.start}"
                if pr.start == pr.end
                else f"{pr.protocol}/{pr.start}-{pr.end}"
                for pr in svc_gap
            ]
            if svc_gap:
                entry["suggestion"] = (
                    f"Add service '{service}' to this rule's service list"
                )
            else:
                entry["suggestion"] = (
                    "Expand source or destination address to include the requested endpoint"
                )
            partial.append(entry)

    permit_rules = [r for r in matching if r["action"] == "accept"]
    deny_rules = [r for r in matching if r["action"] == "deny"]

    if permit_rules:
        verdict = "PERMITTED"
    elif deny_rules:
        verdict = "EXPLICITLY_DENIED"
    elif partial:
        verdict = "MODIFIABLE"
    else:
        verdict = "NEW_RULE_NEEDED"

    notes: list[str] = []
    if permit_rules:
        notes.append(
            f"Flow already permitted by rule ID {permit_rules[0]['id']} ({permit_rules[0]['name'] or 'unnamed'})"
        )
    elif deny_rules:
        notes.append(
            f"Flow explicitly denied by rule ID {deny_rules[0]['id']} ({deny_rules[0]['name'] or 'unnamed'})"
        )
    elif partial:
        notes.append(
            f"Rule ID {partial[0]['id']} covers src/dst — add service to permit"
        )

    # Insertion analysis
    insertion: InsertionPlan | None = None
    suggested_position: int | None = None
    if verdict in ("NEW_RULE_NEEDED", "EXPLICITLY_DENIED"):
        if policies:
            try:
                insertion = plan_insertion(
                    pkg_key,
                    policies,
                    matcher,
                    [src],
                    [dst],
                    service_ranges,
                    srcintf,
                    dstintf,
                )
                suggested_position = insertion.insert_before_policy_id
                if insertion.rationale:
                    notes.append(f"Placement: {insertion.rationale}")
            except Exception:
                if last_permit_seq:
                    suggested_position = last_permit_seq
                    notes.append(
                        f"Suggest inserting new rule after ID {last_permit_seq}"
                    )
        elif last_permit_seq:
            suggested_position = last_permit_seq
            notes.append(f"Suggest inserting new rule after ID {last_permit_seq}")

    # Object plans
    src_obj = _address_object_plan("source", src, snapshot)
    dst_obj = _address_object_plan("destination", dst, snapshot)
    svc_objs: list[ObjectPlan] = (
        _service_object_plan(service, snapshot)
        if service
        else [
            ObjectPlan(
                role="service",
                action="reuse",
                name="ALL",
                obj_type="service",
                value="any",
            ),
        ]
    )
    object_plans = _dedupe([src_obj, dst_obj] + svc_objs)

    # FortiOS CLI
    fortios_cli = ""
    if verdict in ("NEW_RULE_NEEDED", "EXPLICITLY_DENIED"):
        policy_name = standards.policy_name(
            ticket_id,
            srcintf or "any",
            dstintf or "any",
        )
        blocked = zone_verdict.get("verdict") == "BLOCKED"
        comments = (
            cli_gen.exception_comment(ticket_id)
            if blocked
            else f"Ticket {ticket_id or '<TICKET_ID>'}"
        )
        fortios_cli = cli_gen.policy_cli(
            name=policy_name,
            srcintf=srcintf or "any",
            dstintf=dstintf or "any",
            srcaddr=[src_obj.name],
            dstaddr=[dst_obj.name],
            service=[o.name for o in svc_objs],
            logtraffic="all",
            logtraffic_start=False,
            comments=comments,
            insert_before=insertion.insert_before_policy_id if insertion else None,
        )

    # Risk / approval chain
    src_zones = zone_verdict.get("src_zones", [])
    dst_zones = zone_verdict.get("dst_zones", [])
    zone_doms = zone_domains or {}
    risk = standards.risk_level(src_zones, dst_zones, zone_doms)
    approval_raw = standards.review_requirements(risk)
    approval = {
        "risk_level": risk,
        "approvers": approval_raw.get("approvers", []),
        "peer_review": approval_raw.get("peer_review", ""),
        "security_review": approval_raw.get("security_review", ""),
        "change_window": str(approval_raw.get("change_window", "")).strip(),
        "sla_hours": approval_raw.get("sla_hours", ""),
    }

    # Permissiveness warnings
    permissiveness_warnings = standards.permissiveness_warnings(
        [src], [dst], service_ranges
    )

    # GroupAppendAlternative
    alternative_raw: GroupAppendAlternative | None = None
    alternative: dict | None = None
    if verdict == "NEW_RULE_NEEDED":
        alternative_raw = _find_alternative(
            snapshot,
            matcher,
            src,
            dst,
            service_ranges,
            srcintf,
            dstintf,
        )
    if alternative_raw is not None:
        alt = alternative_raw
        member_names = [m.name for m in alt.members]
        alternative = {
            "policy_id": alt.policy_id,
            "policy_name": alt.policy_name,
            "package": alt.package,
            "side": alt.side,
            "group": alt.group,
            "member_names": member_names,
            "group_cli": alt.group_cli,
            "direct_cli": alt.direct_cli,
            "affected_count": alt.affected_policies[0]["count"]
            if alt.affected_policies
            else 0,
            "warnings": alt.warnings,
            "summary": (
                f"Rule #{alt.policy_id} {alt.policy_name!r} covers everything "
                f"except the {alt.side} — "
                + (
                    f"append {', '.join(member_names)} to group {alt.group!r}"
                    if alt.group
                    else f"add {', '.join(member_names)} directly to rule's {alt.side} address list"
                )
                + " instead of creating a new policy."
            ),
        }

    # Zone policy notes
    if zone_verdict.get("available"):
        zv = zone_verdict.get("verdict", "")
        if zv == "BLOCKED":
            notes.append(
                f"⚠ ZONE POLICY BLOCKED: "
                f"{', '.join(zone_verdict.get('src_zones', [])) or '(no zone)'} → "
                f"{', '.join(zone_verdict.get('dst_zones', [])) or '(no zone)'} "
                "is blocked by segmentation policy"
            )
        elif zv == "UNKNOWN":
            notes.append(
                "Zone policy: no rule covers this zone pair — treat as implicit deny"
            )

    # Path notes
    if path_check.get("in_path") is False:
        notes.append(
            f"⚠ PATH CHECK: {path_check['notes'][0] if path_check.get('notes') else 'Device may not be in traffic path'}"
        )
    elif path_check.get("in_path") is True:
        notes.append(
            f"✓ PATH CHECK: {path_check['notes'][0] if path_check.get('notes') else 'Device appears in traffic path'}"
        )

    return {
        # Core
        "src": src,
        "dst": dst,
        "service": service,
        "adom": snapshot.adom,
        "pkg_path": pkg_path,
        "pkg_name": pkg_name,
        "device": snapshot.device,
        # Verdict
        "verdict": verdict,
        "matching_rules": matching,
        "modifiable_rules": [p for p in partial if "suggestion" in p],
        "partial_matches": partial,
        "suggested_position": suggested_position,
        "fortios_cli": fortios_cli,
        "notes": notes,
        # Zone (caller injects, passed through)
        "zone_verdict": zone_verdict.get("verdict", "UNAVAILABLE"),
        "zone_source": zone_verdict.get("source", "none"),
        "zone_src": zone_verdict.get("src_zones", []),
        "zone_dst": zone_verdict.get("dst_zones", []),
        "zone_governing": zone_verdict.get("governing", []),
        "zone_all_policies": zone_verdict.get("all_policies", []),
        "zone_available": zone_verdict.get("available", False),
        # Path (caller injects, passed through)
        "path_in_path": path_check.get("in_path"),
        "path_confidence": path_check.get("confidence", "low"),
        "path_src_iface": path_check.get("src_iface"),
        "path_dst_iface": path_check.get("dst_iface"),
        "path_src_route": path_check.get("src_route"),
        "path_dst_route": path_check.get("dst_route"),
        "path_notes": path_check.get("notes", []),
        # New fields
        "object_plans": [
            {
                "role": o.role,
                "action": o.action,
                "name": o.name,
                "obj_type": o.obj_type,
                "value": o.value,
                "cli": o.cli,
            }
            for o in object_plans
        ],
        "approval": approval,
        "permissiveness_warnings": permissiveness_warnings,
        "alternative": alternative,
    }
