# tests/test_planner_engine.py
import pytest
from app.planner.fetch import build_snapshot
from app.planner.engine import plan_flow
from app.planner.matching import parse_service_request


def _snapshot(policies=None, addr_objects=None, addr_groups=None,
              svc_objects=None, svc_groups=None):
    pkg_key = "TestADOM/pkg/TestPkg"
    return build_snapshot(
        adom="TestADOM", device="FW01",
        addr_objects=addr_objects or [],
        addr_groups=addr_groups or [],
        svc_objects=svc_objects or [],
        svc_groups=svc_groups or [],
        policies_by_package={pkg_key: policies or []},
        interfaces=[],
    )

_ZONE_RESULT = {"available": False, "verdict": "UNAVAILABLE",
                "src_zones": [], "dst_zones": [], "governing": [], "all_policies": []}
_PATH_RESULT = {"in_path": None, "confidence": "low",
                "src_reachable": False, "dst_reachable": False,
                "src_iface": None, "dst_iface": None,
                "src_route": None, "dst_route": None, "notes": []}


def test_plan_flow_new_rule_when_no_policies():
    snap = _snapshot()
    result = plan_flow("10.1.2.3", "192.168.1.1", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001")
    assert result["verdict"] == "NEW_RULE_NEEDED"
    assert result["fortios_cli"] != ""
    assert "object_plans" in result
    assert "approval" in result
    assert "permissiveness_warnings" in result


def test_plan_flow_permitted_by_existing_rule():
    permit_policy = {
        "policyid": 10, "name": "ALLOW_HTTPS", "action": "accept", "status": "enable",
        "srcaddr": [{"name": "all"}], "dstaddr": [{"name": "all"}],
        "service": [{"name": "all"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    snap = _snapshot(policies=[permit_policy])
    result = plan_flow("10.1.2.3", "192.168.1.1", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001")
    assert result["verdict"] == "PERMITTED"
    assert any(r["id"] == 10 for r in result["matching_rules"])


def test_plan_flow_explicitly_denied():
    deny_policy = {
        "policyid": 5, "name": "DENY_ALL", "action": "deny", "status": "enable",
        "srcaddr": [{"name": "all"}], "dstaddr": [{"name": "all"}],
        "service": [{"name": "all"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    snap = _snapshot(policies=[deny_policy])
    result = plan_flow("10.1.2.3", "192.168.1.1", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001")
    assert result["verdict"] == "EXPLICITLY_DENIED"


def test_plan_flow_new_rule_has_object_plans():
    snap = _snapshot()
    result = plan_flow("10.1.2.3", "192.168.1.1", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001")
    # Should propose host object for 10.1.2.3, host for 192.168.1.1, service tcp/443
    roles = {o["role"] for o in result["object_plans"]}
    assert "source" in roles
    assert "destination" in roles
    assert "service" in roles


def test_plan_flow_new_rule_has_approval():
    snap = _snapshot()
    result = plan_flow("10.1.2.3", "192.168.1.1", "tcp/443", snap,
                       zone_verdict={"available": True, "verdict": "ALLOWED",
                                     "src_zones": ["ZoneA"], "dst_zones": ["ZoneB"],
                                     "governing": [], "all_policies": []},
                       path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001",
                       zone_domains={"ZoneA": "Corporate", "ZoneB": "Corporate"})
    assert result["approval"]["risk_level"] in ("critical", "high", "medium")
    assert "sla_hours" in result["approval"]


def test_plan_flow_permissiveness_warning_for_any_source():
    snap = _snapshot()
    result = plan_flow("0.0.0.0/0", "192.168.1.1", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg", ticket_id="CHG001")
    assert len(result["permissiveness_warnings"]) > 0


def test_plan_flow_modifiable_address_gap():
    """Partial address match (subnet flow vs. single-host policy) with no service gap
    should suggest expanding the address, not adding a service."""
    # Policy covers only HOST-192-168-0-1 (/32); flow asks about 192.168.0.0/24 (larger subnet).
    # addr_dim: 192.168.0.0/24 overlaps 192.168.0.1/32 but is not contained → (matched=True, full=False).
    # Service is "all" → svc_full=True; svc_gap will be empty.
    partial_policy = {
        "policyid": 20, "name": "ALLOW_HTTPS_PARTIAL", "action": "accept",
        "status": "enable",
        "srcaddr": [{"name": "all"}],
        "dstaddr": [{"name": "HOST-192-168-0-1"}],
        "service": [{"name": "all"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    addr_objects = [{"name": "HOST-192-168-0-1", "subnet": "192.168.0.1 255.255.255.255",
                     "type": "ipmask"}]
    snap = _snapshot(policies=[partial_policy], addr_objects=addr_objects)
    result = plan_flow("10.1.2.3", "192.168.0.0/24", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg")
    assert result["verdict"] == "MODIFIABLE", f"Got {result['verdict']}"
    assert len(result["modifiable_rules"]) > 0
    suggestion = result["modifiable_rules"][0]["suggestion"]
    assert "address" in suggestion.lower(), f"Expected address suggestion, got: {suggestion!r}"
    assert "service" not in suggestion.lower(), f"Suggestion wrongly mentions service: {suggestion!r}"


def test_plan_flow_blank_service_permits_all():
    """An empty service field should match any service (WILDCARD), not fail."""
    permit_policy = {
        "policyid": 10, "name": "ALLOW_ALL", "action": "accept", "status": "enable",
        "srcaddr": [{"name": "all"}], "dstaddr": [{"name": "all"}],
        "service": [{"name": "all"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    snap = _snapshot(policies=[permit_policy])
    result = plan_flow("10.1.2.3", "192.168.1.1", "", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg")
    assert result["verdict"] == "PERMITTED", (
        f"Empty service should match any-service rule, got {result['verdict']}")


def test_plan_flow_unparseable_service_returns_error():
    """An unparseable service token should return verdict=ERROR, not raise."""
    snap = _snapshot()
    result = plan_flow("10.1.2.3", "192.168.1.1", "myapp-xyz", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg")
    assert result["verdict"] == "ERROR"
    assert result["notes"]


def test_plan_flow_dns_produces_two_service_objects():
    """service='dns' parses to tcp/53 + udp/53 — both must appear in object_plans."""
    snap = _snapshot()
    result = plan_flow("10.1.2.3", "192.168.1.1", "dns", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg")
    svc_plans = [o for o in result["object_plans"] if o["role"] == "service"]
    assert len(svc_plans) == 2, (
        f"Expected 2 service object plans for 'dns' (tcp/53 + udp/53), got {svc_plans}")
    protos = {o["value"].split("/")[0] for o in svc_plans}
    assert "tcp" in protos and "udp" in protos


def test_plan_flow_alternative_affected_count_zero_not_one():
    """When only one policy references the address group, affected_count must be 0
    (no other rules affected), not 1 (the always-1 bug from using len() on a list
    that stores the count as a dict value)."""
    shared_group = "GRP-SERVERS"
    # Only ONE policy; it IS the near-miss candidate. No other rules reference the group.
    policy_with_group = {
        "policyid": 30, "name": "RULE_WITH_GROUP", "action": "accept", "status": "enable",
        "srcaddr": [{"name": "all"}],
        "dstaddr": [{"name": shared_group}],
        "service": [{"name": "all"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    member_obj = {"name": "HOST-10-0-0-1", "subnet": "10.0.0.1 255.255.255.255",
                  "type": "ipmask"}
    addr_groups = [{"name": shared_group, "member": [{"name": "HOST-10-0-0-1"}]}]
    snap = _snapshot(
        policies=[policy_with_group],
        addr_objects=[member_obj], addr_groups=addr_groups,
    )
    # 192.168.9.9 is not in the group → triggers GroupAppendAlternative
    result = plan_flow("10.1.2.3", "192.168.9.9", "tcp/443", snap,
                       zone_verdict=_ZONE_RESULT, path_check=_PATH_RESULT,
                       pkg_key="TestADOM/pkg/TestPkg", pkg_name="TestPkg",
                       pkg_path="pkg/TestPkg")
    assert result.get("alternative") is not None, "Expected GroupAppendAlternative to be found"
    assert result["alternative"]["affected_count"] == 0, (
        f"Only one policy references GRP-SERVERS; expected affected_count=0, "
        f"got {result['alternative']['affected_count']}"
    )


def test_analyze_flows_backward_compatible():
    """analyze_flows() must return list with all existing keys present."""
    from app.rule_review import analyze_flows
    flows = [{"src": "10.1.2.3", "dst": "192.168.1.1", "service": "tcp/443"}]
    packages = [{"adom": "TestADOM", "name": "TestPkg", "path": "pkg/TestPkg", "device": "FW01"}]
    result = analyze_flows(flows, packages, {}, [], [], [], [])
    assert len(result) == 1
    row = result[0]
    for key in ("src", "dst", "service", "verdict", "fortios_cli", "notes",
                "zone_verdict", "matching_rules", "modifiable_rules"):
        assert key in row, f"missing key: {key}"
    # New fields must also be present
    for key in ("object_plans", "approval", "alternative", "permissiveness_warnings"):
        assert key in row, f"missing new key: {key}"
