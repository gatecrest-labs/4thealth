"""Rule Validation analysis engine.

Takes a list of requested flows (src IPs, dst IPs, ports/services) and one or
more FortiGate policy packages, then determines:
  - Whether each flow is already permitted by existing rules
  - Whether an existing rule could be modified to permit it
  - Whether a new rule is needed, and where to insert it
  - What FortiOS CLI syntax to generate for each device
  - Zone policy segmentation verdict (via local policy_db.json)
  - Whether this firewall is actually in the traffic path (routing check)
"""

from __future__ import annotations

import ipaddress
import re as _re
from typing import Any, Optional


# ── Group name helpers ────────────────────────────────────────────────────────


def _looks_like_fgt_name(val: str) -> bool:
    """Return True if val looks like a FortiGate object/group name (not an IP, CIDR, or port spec)."""
    if not val or val.lower() == "any":
        return False
    if _re.match(r"^\d{1,3}(\.\d{1,3}){3}(/\d+)?$", val):
        return False
    if _re.match(r"^(tcp|udp|icmp|ip)/\d+", val, _re.I):
        return False
    if val.isdigit():
        return False
    return bool(_re.match(r"^[A-Za-z][A-Za-z0-9_\-\.]*$", val))


def _expand_addr_name(
    name: str, addr_objects: list, addr_groups: list
) -> list[str] | None:
    """Resolve a FortiGate address object or group name to a list of CIDR strings.

    Returns None if the name is not found in either list.
    Returns an empty list if the name is found but has no resolvable subnets.
    """
    norm = name.strip().lower()

    def _obj_to_cidr(obj: dict) -> str | None:
        subnet = obj.get("subnet") or ""
        if subnet:
            parts = str(subnet).split()
            return f"{parts[0]}/{parts[1]}" if len(parts) == 2 else str(subnet)
        fqdn = obj.get("fqdn") or ""
        return fqdn if fqdn else None

    obj_index = {
        o["name"].lower(): o
        for o in addr_objects
        if isinstance(o, dict) and o.get("name")
    }

    # Try addr_groups first
    for grp in addr_groups:
        if not isinstance(grp, dict) or grp.get("name", "").lower() != norm:
            continue
        cidrs = []
        for member in grp.get("member") or []:
            m_name = (
                member.get("name", "") if isinstance(member, dict) else str(member)
            ).lower()
            if m_name in obj_index:
                cidr = _obj_to_cidr(obj_index[m_name])
                if cidr:
                    cidrs.append(cidr)
        return cidrs  # found group (may be empty list)

    # Try addr_objects directly
    if norm in obj_index:
        cidr = _obj_to_cidr(obj_index[norm])
        return [cidr] if cidr else []

    return None  # not found


def _expand_svc_name(
    name: str, svc_objects: list, svc_groups: list
) -> list[str] | None:
    """Resolve a FortiGate service object or group name to a list of port-spec strings.

    Returns None if not found. Returns [] if found but no port ranges extracted.
    """
    norm = name.strip().lower()

    def _obj_to_specs(obj: dict) -> list[str]:
        specs = []
        tcp = obj.get("tcp-portrange") or ""
        udp = obj.get("udp-portrange") or ""
        for proto, raw in (("tcp", tcp), ("udp", udp)):
            first_range = str(raw).split()[0].split(":")[0] if raw else ""
            if first_range:
                specs.append(f"{proto}/{first_range}")
        return specs

    svc_index = {
        o["name"].lower(): o
        for o in svc_objects
        if isinstance(o, dict) and o.get("name")
    }

    for grp in svc_groups:
        if not isinstance(grp, dict) or grp.get("name", "").lower() != norm:
            continue
        specs = []
        for member in grp.get("member") or []:
            m_name = (
                member.get("name", "") if isinstance(member, dict) else str(member)
            ).lower()
            if m_name in svc_index:
                specs.extend(_obj_to_specs(svc_index[m_name]))
        return specs

    if norm in svc_index:
        return _obj_to_specs(svc_index[norm])

    return None


# ── FQDN helpers ──────────────────────────────────────────────────────────────


def _looks_like_fqdn(val: str) -> bool:
    """Return True if val looks like a fully-qualified domain name (not an IP or CIDR)."""
    if not val or "." not in val:
        return False
    parts = val.rstrip(".").split(".")
    if len(parts) < 2:
        return False
    tld = parts[-1]
    if not _re.match(r"^[A-Za-z]{2,6}$", tld):
        return False
    return any(parts[:-1])


def _resolve_fqdn(fqdn: str, timeout: float = 3.0) -> list[str]:
    """Resolve an FQDN to a list of IPv4 address strings.

    Returns an empty list on failure or timeout.
    """
    import socket
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout

    def _lookup() -> list[str]:
        try:
            results = socket.getaddrinfo(fqdn, None, socket.AF_INET)
            return list(dict.fromkeys(r[4][0] for r in results if r[4]))
        except (socket.gaierror, OSError):
            return []

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_lookup)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            return []


def _flow_error_result(flow: dict, adom: str, msg: str) -> dict:
    """Return a generic ERROR result dict for a flow with a custom message."""
    return {
        "src": flow.get("src", ""),
        "dst": flow.get("dst", ""),
        "service": flow.get("service", ""),
        "adom": adom,
        "pkg_name": "",
        "pkg_path": "",
        "device": "",
        "vdom": "root",
        "verdict": "ERROR",
        "error": msg,
        "matching_rules": [],
        "modifiable_rules": [],
        "notes": [msg],
        "fortios_cli": "",
        "object_plans": [],
        "approval": {},
        "alternative": None,
        "permissiveness_warnings": [],
        "zone_available": False,
        "zone_verdict": "UNAVAILABLE",
        "zone_src": [],
        "zone_dst": [],
        "zone_governing": [],
        "zone_all_policies": [],
        "path_in_path": None,
        "path_confidence": "low",
        "path_src_iface": None,
        "path_dst_iface": None,
        "path_src_route": None,
        "path_dst_route": None,
        "path_notes": [],
        "path_src_reachable": False,
        "path_dst_reachable": False,
    }


# ── Zone policy integration ───────────────────────────────────────────────────
# Uses app.zone_db — the embedded segmentation policy engine that reads
# policy_db.json directly from the project root. No external service required.


def zone_script_available() -> bool:
    import app.zone_db as zdb

    return zdb.db_available()


def _zone_unavailable() -> dict:
    return {
        "available": False,
        "source": "none",
        "verdict": "UNAVAILABLE",
        "src_zones": [],
        "dst_zones": [],
        "governing": [],
        "all_policies": [],
    }


def _group_error_result(flow: dict, field: str, name: str, adom: str) -> dict:
    """Return an ERROR result for an unresolved address or service group name."""
    field_label = {"src": "Source", "dst": "Destination", "service": "Service"}[field]
    obj_type = "service group" if field == "service" else "address group"
    msg = (
        f'{field_label} group "{name}" not found in ADOM "{adom}" — '
        f"check the Rule Review tab for valid {obj_type} names"
    )
    return {
        "src": flow.get("src", ""),
        "dst": flow.get("dst", ""),
        "service": flow.get("service", ""),
        "adom": adom,
        "pkg_name": "",
        "pkg_path": "",
        "device": "",
        "vdom": "root",
        "verdict": "ERROR",
        "error": msg,
        "matching_rules": [],
        "modifiable_rules": [],
        "notes": [msg],
        "fortios_cli": "",
        "object_plans": [],
        "approval": {},
        "alternative": None,
        "permissiveness_warnings": [],
        "zone_available": False,
        "zone_verdict": "UNAVAILABLE",
        "zone_src": [],
        "zone_dst": [],
        "zone_governing": [],
        "zone_all_policies": [],
        "path_in_path": None,
        "path_confidence": "low",
        "path_src_iface": None,
        "path_dst_iface": None,
        "path_src_route": None,
        "path_dst_route": None,
        "path_notes": [],
        "path_src_reachable": False,
        "path_dst_reachable": False,
    }


def query_zone_policy(src: str, dst: str, service: str) -> dict:
    """Run zone policy flow query using local policy_db.json."""
    import app.zone_db as zdb

    if not zdb.db_available():
        return _zone_unavailable()
    try:
        r = zdb.query_single(src, dst, service)
        if not r:
            return _zone_unavailable()
        return {
            "available": True,
            "source": "local",
            "verdict": r.get("verdict", "UNKNOWN"),
            "src_zones": r.get("src_zones", []),
            "dst_zones": r.get("dst_zones", []),
            "governing": r.get("governing", []),
            "all_policies": r.get("all_policies", []),
        }
    except Exception as exc:
        return {
            "available": True,
            "source": "local",
            "verdict": "ERROR",
            "src_zones": [],
            "dst_zones": [],
            "governing": [],
            "all_policies": [],
            "error": str(exc),
        }


# ── Address / subnet helpers ──────────────────────────────────────────────────


def _parse_addr(raw: str):
    raw = raw.strip()
    if not raw:
        return None
    try:
        if "/" in raw:
            return ipaddress.ip_network(raw, strict=False)
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def _ip_in_network(ip_str: str, net_str: str) -> bool:
    try:
        ip_part = ip_str.split("/")[0]
        ip = ipaddress.ip_address(ip_part)
        net = ipaddress.ip_network(net_str, strict=False)
        return ip in net
    except ValueError:
        return False


def _nets_overlap(a: str, b: str) -> bool:
    try:
        na = ipaddress.ip_network(a, strict=False)
        nb = ipaddress.ip_network(b, strict=False)
        return na.overlaps(nb)
    except ValueError:
        return False


def _addr_matches(query: str, net_str: str) -> bool:
    """True if query (IP or CIDR) overlaps with net_str."""
    if "/" in query:
        return _nets_overlap(query, net_str)
    return _ip_in_network(query, net_str)


# ── Routing / path-relevance check ───────────────────────────────────────────


def _cidr_prefix(net_str: str) -> int:
    try:
        return ipaddress.ip_network(net_str, strict=False).prefixlen
    except Exception:
        return -1


def check_path_relevance(
    src: str,
    dst: str,
    interfaces: list,
    routes: list,
) -> dict:
    """Determine whether a firewall is likely in the traffic path.

    Returns::
        {
            "in_path":       True | False | None,   # None = unknown (no data)
            "confidence":    "high" | "medium" | "low",
            "src_reachable": bool,
            "dst_reachable": bool,
            "src_iface":     str | None,
            "dst_iface":     str | None,
            "src_route":     dict | None,
            "dst_route":     dict | None,
            "notes":         [str, ...],
        }
    """
    result: dict = {
        "in_path": None,
        "confidence": "low",
        "src_reachable": False,
        "dst_reachable": False,
        "src_iface": None,
        "dst_iface": None,
        "src_route": None,
        "dst_route": None,
        "notes": [],
    }

    if not interfaces and not routes:
        result["notes"].append(
            "No interface or routing data available from this device."
        )
        return result

    # Build a list of (network, interface_name, ip) from interface data
    iface_nets: list[tuple[ipaddress.IPv4Network, str, str]] = []
    for iface in interfaces:
        if not isinstance(iface, dict):
            continue
        name = iface.get("name", "")
        ip_raw = iface.get("ip", iface.get("ipv4_address", ""))
        mask = iface.get("mask", iface.get("netmask", ""))
        link = iface.get("link", iface.get("status", ""))

        if not ip_raw or ip_raw in ("0.0.0.0", ""):
            continue
        if isinstance(link, int):
            link = "up" if link else "down"
        if str(link).lower() in ("down", "0", "false"):
            continue
        try:
            # CMDB returns ip as "A.B.C.D M.M.M.M" (space-separated) or "A.B.C.D/M.M.M.M"
            if isinstance(ip_raw, str) and " " in ip_raw:
                parts = ip_raw.split()
                ip_raw, mask = parts[0], parts[1]
            if ip_raw in ("0.0.0.0", ""):
                continue
            if mask and mask != "0.0.0.0":
                net = ipaddress.IPv4Network(f"{ip_raw}/{mask}", strict=False)
            elif "/" in ip_raw:
                net = ipaddress.IPv4Network(ip_raw, strict=False)
            else:
                continue
            iface_nets.append((net, name, ip_raw))
        except ValueError:
            continue

    def best_iface_match(addr: str):
        addr_part = addr.split("/")[0]
        try:
            ip = ipaddress.ip_address(addr_part)
        except ValueError:
            return None, None
        best_prefix = -1
        best_name = None
        for net, iface_name, _ in iface_nets:
            if ip in net and net.prefixlen > best_prefix:
                best_prefix = net.prefixlen
                best_name = iface_name
        return best_name, best_prefix

    src_iface, src_prefix = best_iface_match(src)
    dst_iface, dst_prefix = best_iface_match(dst)

    if src_iface:
        result["src_iface"] = src_iface
        result["src_reachable"] = True
    if dst_iface:
        result["dst_iface"] = dst_iface
        result["dst_reachable"] = True

    # Route table lookup
    def best_route(addr: str) -> Optional[dict]:
        addr_part = addr.split("/")[0]
        try:
            target_ip = ipaddress.ip_address(addr_part)
        except ValueError:
            return None
        best_pfx = -1
        best_entry = None
        for route in routes:
            if not isinstance(route, dict):
                continue
            pfx_raw = route.get(
                "ip_mask", route.get("network", route.get("prefix", ""))
            )
            gw = route.get("gateway", route.get("nexthop", ""))
            iface_r = route.get("interface", route.get("dev", route.get("ifname", "")))
            try:
                net = ipaddress.ip_network(pfx_raw, strict=False)
                if target_ip in net and net.prefixlen > best_pfx:
                    best_pfx = net.prefixlen
                    best_entry = {
                        "network": str(net),
                        "gateway": gw,
                        "interface": iface_r,
                        "prefix": net.prefixlen,
                    }
            except ValueError:
                continue
        return best_entry

    src_route = best_route(src)
    dst_route = best_route(dst)
    result["src_route"] = src_route
    result["dst_route"] = dst_route

    if src_route:
        result["src_reachable"] = True
        if not result["src_iface"]:
            result["src_iface"] = src_route.get("interface")
    if dst_route:
        result["dst_reachable"] = True
        if not result["dst_iface"]:
            result["dst_iface"] = dst_route.get("interface")

    src_ok = result["src_reachable"]
    dst_ok = result["dst_reachable"]

    if src_ok and dst_ok:
        same_iface = (
            result["src_iface"]
            and result["dst_iface"]
            and result["src_iface"] == result["dst_iface"]
        )
        if same_iface:
            result["in_path"] = False
            result["confidence"] = "medium"
            result["notes"].append(
                f"Both source and destination resolve to the same interface "
                f"({result['src_iface']}) — traffic may stay within one segment; "
                f"proceed with caution, rule may not be needed on this device."
            )
        else:
            result["in_path"] = True
            result["confidence"] = "high"
            result["notes"].append(
                f"Source routes via {result['src_iface'] or '?'}, "
                f"destination via {result['dst_iface'] or '?'} — "
                f"firewall appears to be in the traffic path."
            )
    elif src_ok and not dst_ok:
        result["in_path"] = False
        result["confidence"] = "medium"
        result["notes"].append(
            f"Source ({src}) is reachable via {result['src_iface'] or 'an interface'} "
            f"but destination ({dst}) has no route on this device — "
            f"this firewall may not be in the path for the destination; proceed with caution."
        )
    elif not src_ok and dst_ok:
        result["in_path"] = False
        result["confidence"] = "medium"
        result["notes"].append(
            f"Destination ({dst}) is reachable via {result['dst_iface'] or 'an interface'} "
            f"but source ({src}) has no route — "
            f"this firewall may not be in the path for the source; proceed with caution."
        )
    else:
        result["in_path"] = False
        result["confidence"] = "low"
        result["notes"].append(
            f"Neither source ({src}) nor destination ({dst}) resolve to "
            f"any interface or route on this device — "
            f"this firewall is likely NOT in the traffic path; proceed with caution."
        )

    return result


# ── Planner-based analysis ────────────────────────────────────────────────────

from app.planner.engine import plan_flow  # noqa: E402
from app.planner.fetch import build_snapshot  # noqa: E402


def analyze_flows(
    requested_flows: list[dict],
    packages: list[dict],
    policies_by_pkg: dict[str, list],
    addr_objects: list,
    addr_groups: list,
    svc_objects: list,
    svc_groups: list,
    routing_by_device: dict[str, dict] | None = None,
) -> list[dict]:
    """Analyse each requested flow against the selected policy packages.

    Signature identical to the old implementation — callers need no changes.
    Internals now use set-semantics matching, object planning, approval chain,
    and GroupAppendAlternative from app.planner.
    """
    routing = routing_by_device or {}
    results: list[dict] = []

    for flow in requested_flows:
        src_raw = flow.get("src", "").strip()
        dst_raw = flow.get("dst", "").strip()
        svc_raw = flow.get("service", "").strip()
        comment = flow.get("comment", "")

        # ── Group name expansion ──────────────────────────────────────────────
        srcs: list[str] = [src_raw]
        dsts: list[str] = [dst_raw]
        svcs: list[str] = [svc_raw] if svc_raw else [""]
        flow_warnings: list[str] = []  # propagated to every result for this flow

        if _looks_like_fgt_name(src_raw):
            expanded = _expand_addr_name(src_raw, addr_objects, addr_groups)
            if expanded is None:
                if _looks_like_fqdn(src_raw):
                    resolved = _resolve_fqdn(src_raw)
                    if resolved:
                        srcs = resolved
                        flow_warnings.append(
                            f'"{src_raw}" resolved via DNS to {", ".join(resolved)}; '
                            f"analysis uses these IPs (runtime resolution may differ)."
                        )
                    else:
                        adom = packages[0]["adom"] if packages else "unknown"
                        results.append(
                            _flow_error_result(
                                flow,
                                adom,
                                f'FQDN source "{src_raw}" was not found in ADOM "{adom}" '
                                f"and could not be resolved via DNS — verify the hostname is correct",
                            )
                        )
                        continue
                else:
                    adom = packages[0]["adom"] if packages else "unknown"
                    results.append(_group_error_result(flow, "src", src_raw, adom))
                    continue
            else:
                srcs = expanded or [src_raw]
                # Warn if any group members could not be resolved
                _norm = src_raw.strip().lower()
                for _grp in addr_groups:
                    if isinstance(_grp, dict) and _grp.get("name", "").lower() == _norm:
                        _total = len(_grp.get("member") or [])
                        if _total > len(expanded):
                            flow_warnings.append(
                                f'Address group "{src_raw}" has {_total - len(expanded)}'
                                f" unresolvable member(s) (nested groups or IP ranges);"
                                f" analysis may be incomplete."
                            )
                        break

        if _looks_like_fgt_name(dst_raw):
            expanded = _expand_addr_name(dst_raw, addr_objects, addr_groups)
            if expanded is None:
                if _looks_like_fqdn(dst_raw):
                    resolved = _resolve_fqdn(dst_raw)
                    if resolved:
                        dsts = resolved
                        flow_warnings.append(
                            f'"{dst_raw}" resolved via DNS to {", ".join(resolved)}; '
                            f"analysis uses these IPs (runtime resolution may differ)."
                        )
                    else:
                        adom = packages[0]["adom"] if packages else "unknown"
                        results.append(
                            _flow_error_result(
                                flow,
                                adom,
                                f'FQDN destination "{dst_raw}" was not found in ADOM "{adom}" '
                                f"and could not be resolved via DNS — verify the hostname is correct",
                            )
                        )
                        continue
                else:
                    adom = packages[0]["adom"] if packages else "unknown"
                    results.append(_group_error_result(flow, "dst", dst_raw, adom))
                    continue
            else:
                dsts = expanded or [dst_raw]
                # Warn if any group members could not be resolved
                _norm = dst_raw.strip().lower()
                for _grp in addr_groups:
                    if isinstance(_grp, dict) and _grp.get("name", "").lower() == _norm:
                        _total = len(_grp.get("member") or [])
                        if _total > len(expanded):
                            flow_warnings.append(
                                f'Address group "{dst_raw}" has {_total - len(expanded)}'
                                f" unresolvable member(s) (nested groups or IP ranges);"
                                f" analysis may be incomplete."
                            )
                        break

        if svc_raw and _looks_like_fgt_name(svc_raw):
            try:
                from app.planner.matching import parse_service_request

                parse_service_request(svc_raw)
                # parse succeeded — engine handles it natively
            except Exception:
                expanded_svc = _expand_svc_name(svc_raw, svc_objects, svc_groups)
                if expanded_svc is None:
                    adom = packages[0]["adom"] if packages else "unknown"
                    results.append(_group_error_result(flow, "service", svc_raw, adom))
                    continue
                svcs = expanded_svc or [svc_raw]

        # ── Zone verdict (once per original flow) ────────────────────────────
        zone_result = query_zone_policy(src_raw, dst_raw, svc_raw)

        # Build zone_domains from zone_db for risk classification
        zone_domains: dict = {}
        try:
            import app.zone_db as zdb

            if zdb.db_available():
                db = zdb.load_db()
                zone_domains = {
                    name: z.get("domain", "") for name, z in db.get("zones", {}).items()
                }
        except Exception:
            pass

        # ── Build snapshot cache per (package, device) — devices sharing the same
        # package each have their own interfaces and routing data. ──────────────
        snapshot_cache: dict[str, Any] = {}
        for _pkg in packages:
            _pkg_adom = _pkg["adom"]
            _pkg_path = _pkg["path"]
            _pkg_name = _pkg["name"]
            _pkg_device = _pkg.get("device", "")
            _pkg_key = f"{_pkg_adom}/{_pkg_path}"
            _pkg_dev_key = _pkg_device or _pkg_name
            _cache_key = f"{_pkg_key}||{_pkg_dev_key}"
            if _cache_key not in snapshot_cache:
                snapshot_cache[_cache_key] = build_snapshot(
                    adom=_pkg_adom,
                    device=_pkg_dev_key,
                    addr_objects=list(addr_objects),
                    addr_groups=list(addr_groups),
                    svc_objects=list(svc_objects),
                    svc_groups=list(svc_groups),
                    policies_by_package={_pkg_key: policies_by_pkg.get(_pkg_key, [])},
                    interfaces=routing.get(_pkg_dev_key, {}).get("interfaces", []),
                    routing_table=routing.get(_pkg_dev_key, {}).get("routes", []),
                )

        # ── Cartesian guard — cap src × dst × svc explosion ──────────────────
        COMBO_LIMIT = 20
        combinations = [(s, d, v) for s in srcs for d in dsts for v in svcs]
        truncated = len(combinations) > COMBO_LIMIT
        if truncated:
            combinations = combinations[:COMBO_LIMIT]

        # ── Run plan_flow for each expanded src × dst × svc combination ──────
        for src, dst, svc in combinations:
            for pkg in packages:
                adom = pkg["adom"]
                pkg_path = pkg["path"]
                pkg_name = pkg["name"]
                device = pkg.get("device", "")
                vdom = pkg.get("vdom", "root")
                pkg_key = f"{adom}/{pkg_path}"

                dev_key = device or pkg_name
                if dev_key in routing:
                    path_check = check_path_relevance(
                        src,
                        dst,
                        routing[dev_key].get("interfaces", []),
                        routing[dev_key].get("routes", []),
                    )
                else:
                    path_check = {
                        "in_path": None,
                        "confidence": "low",
                        "src_reachable": False,
                        "dst_reachable": False,
                        "src_iface": None,
                        "dst_iface": None,
                        "src_route": None,
                        "dst_route": None,
                        "notes": ["Routing data not available for this device."],
                    }

                dev_cache_key = f"{pkg_key}||{dev_key}"
                row = plan_flow(
                    src=src,
                    dst=dst,
                    service=svc,
                    snapshot=snapshot_cache[dev_cache_key],
                    zone_verdict=zone_result,
                    path_check=path_check,
                    pkg_key=pkg_key,
                    pkg_name=pkg_name,
                    pkg_path=pkg_path,
                    ticket_id=flow.get("ticket_id", ""),
                    zone_domains=zone_domains,
                )
                row["comment"] = comment
                row["device"] = device
                row["vdom"] = vdom
                if flow_warnings:
                    row["permissiveness_warnings"].extend(flow_warnings)
                if truncated:
                    row["permissiveness_warnings"].append(
                        f"Group expansion produced >{COMBO_LIMIT} src×dst×service"
                        f" combinations; truncated to {COMBO_LIMIT}."
                    )
                results.append(row)

    return results
