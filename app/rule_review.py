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

    src_iface, _src_prefix = best_iface_match(src)
    dst_iface, _dst_prefix = best_iface_match(dst)

    if src_iface:
        result["src_iface"] = src_iface
        result["src_reachable"] = True
    if dst_iface:
        result["dst_iface"] = dst_iface
        result["dst_reachable"] = True

    # Route table lookup
    def best_route(addr: str) -> dict | None:
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

from app.planner.engine import plan_flow
from app.planner.fetch import build_snapshot


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

        # Zone verdict — once per flow, shared across all packages
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

        for pkg in packages:
            adom = pkg["adom"]
            pkg_path = pkg["path"]
            pkg_name = pkg["name"]
            device = pkg.get("device", "")
            pkg_key = f"{adom}/{pkg_path}"

            # Path-relevance check for this device
            dev_key = device or pkg_name
            if dev_key in routing:
                path_check = check_path_relevance(
                    src_raw,
                    dst_raw,
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

            snapshot = build_snapshot(
                adom=adom,
                device=device or pkg_name,
                addr_objects=list(addr_objects),
                addr_groups=list(addr_groups),
                svc_objects=list(svc_objects),
                svc_groups=list(svc_groups),
                policies_by_package={pkg_key: policies_by_pkg.get(pkg_key, [])},
                interfaces=routing.get(dev_key, {}).get("interfaces", []),
                routing_table=routing.get(dev_key, {}).get("routes", []),
            )

            row = plan_flow(
                src=src_raw,
                dst=dst_raw,
                service=svc_raw,
                snapshot=snapshot,
                zone_verdict=zone_result,
                path_check=path_check,
                pkg_key=pkg_key,
                pkg_name=pkg_name,
                pkg_path=pkg_path,
                ticket_id=flow.get("ticket_id", ""),
                zone_domains=zone_domains,
            )
            row["comment"] = comment
            results.append(row)

    return results
