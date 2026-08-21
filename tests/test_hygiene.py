"""Tests for hygiene checks."""

import pytest
from app.hygiene import check_security_profile_gap, find_unused_objects


def test_security_profile_utm_disabled_accept_flagged():
    policies = [{"policyid": 1, "name": "allow-all", "action": 1, "utm-status": "disable"}]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 1
    assert findings[0]["check"] == "missing_security_profile"


def test_security_profile_utm_enabled_no_profiles_flagged():
    policies = [{
        "policyid": 2, "name": "allow-web", "action": 1,
        "utm-status": "enable",
        "ips-sensor": "", "av-profile": "", "webfilter-profile": "",
        "dnsfilter-profile": "", "application-list": "",
    }]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 1


def test_security_profile_utm_enabled_with_ips_passes():
    policies = [{
        "policyid": 3, "name": "allow-web", "action": 1,
        "utm-status": "enable", "ips-sensor": "default",
        "av-profile": "", "webfilter-profile": "", "dnsfilter-profile": "", "application-list": "",
    }]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


def test_security_profile_deny_action_skipped():
    policies = [{"policyid": 4, "name": "deny-all", "action": 0, "utm-status": "disable"}]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


def test_security_profile_policy_block_skipped():
    policies = [{
        "policyid": 5, "name": "block", "action": 1,
        "utm-status": "disable", "_policy_block": "ThreatFeeds-VDOMs",
    }]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


# ── Unused object detection ────────────────────────────────────────────────────

def test_unused_address_detected():
    policies = [{"policyid": 1, "action": 1,
                 "srcaddr": [{"name": "USED-SRC"}],
                 "dstaddr": [{"name": "USED-DST"}],
                 "service": [{"name": "all"}]}]
    addresses = [{"name": "USED-SRC"}, {"name": "USED-DST"}, {"name": "ORPHAN"}]
    result = find_unused_objects(policies, addresses, [], [], [])
    names = [o["name"] for o in result["unused_addresses"]]
    assert "ORPHAN" in names
    assert "USED-SRC" not in names
    assert "USED-DST" not in names


def test_builtin_all_excluded():
    policies = []
    addresses = [{"name": "all"}, {"name": "ALL"}, {"name": "REAL-ADDR"}]
    result = find_unused_objects(policies, addresses, [], [], [])
    names = [o["name"] for o in result["unused_addresses"]]
    assert "all" not in names
    assert "ALL" not in names
    assert "REAL-ADDR" in names


def test_unused_service_detected():
    policies = [{"policyid": 1, "action": 1, "srcaddr": [], "dstaddr": [],
                 "service": [{"name": "HTTP"}]}]
    services = [{"name": "HTTP"}, {"name": "ORPHAN-SVC"}]
    result = find_unused_objects(policies, [], [], services, [])
    names = [o["name"] for o in result["unused_services"]]
    assert "ORPHAN-SVC" in names
    assert "HTTP" not in names


def test_addr_group_member_not_orphaned():
    # MEMBER-ADDR is only used inside GROUP-A, which IS referenced by a policy — not an orphan
    policies = [{"policyid": 1, "action": 1,
                 "srcaddr": [{"name": "GROUP-A"}],
                 "dstaddr": [{"name": "all"}],
                 "service": [{"name": "all"}]}]
    addresses = [{"name": "MEMBER-ADDR"}]
    addr_groups = [{"name": "GROUP-A", "member": [{"name": "MEMBER-ADDR"}]}]
    result = find_unused_objects(policies, addresses, addr_groups, [], [])
    names = [o["name"] for o in result["unused_addresses"]]
    assert "MEMBER-ADDR" not in names


def test_empty_policies_all_objects_unused():
    addresses = [{"name": "ADDR1"}]
    services = [{"name": "SVC1"}]
    result = find_unused_objects([], addresses, [], services, [])
    assert any(o["name"] == "ADDR1" for o in result["unused_addresses"])
    assert any(o["name"] == "SVC1" for o in result["unused_services"])
