"""Tests for hygiene checks."""

from app.hygiene import (
    check_security_profile_gap,
    find_unused_objects,
    check_redundant_rules,
    check_over_permissive,
)


def test_security_profile_utm_disabled_accept_flagged():
    policies = [
        {"policyid": 1, "name": "allow-all", "action": 1, "utm-status": "disable"}
    ]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 1
    assert findings[0]["check"] == "missing_security_profile"


def test_security_profile_utm_enabled_no_profiles_flagged():
    policies = [
        {
            "policyid": 2,
            "name": "allow-web",
            "action": 1,
            "utm-status": "enable",
            "ips-sensor": "",
            "av-profile": "",
            "webfilter-profile": "",
            "dnsfilter-profile": "",
            "application-list": "",
        }
    ]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 1


def test_security_profile_utm_enabled_with_ips_passes():
    policies = [
        {
            "policyid": 3,
            "name": "allow-web",
            "action": 1,
            "utm-status": "enable",
            "ips-sensor": "default",
            "av-profile": "",
            "webfilter-profile": "",
            "dnsfilter-profile": "",
            "application-list": "",
        }
    ]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


def test_security_profile_deny_action_skipped():
    policies = [
        {"policyid": 4, "name": "deny-all", "action": 0, "utm-status": "disable"}
    ]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


def test_security_profile_policy_block_skipped():
    policies = [
        {
            "policyid": 5,
            "name": "block",
            "action": 1,
            "utm-status": "disable",
            "_policy_block": "ThreatFeeds-VDOMs",
        }
    ]
    findings = check_security_profile_gap(policies)
    assert len(findings) == 0


# ── Unused object detection ────────────────────────────────────────────────────


def test_unused_address_detected():
    policies = [
        {
            "policyid": 1,
            "action": 1,
            "srcaddr": [{"name": "USED-SRC"}],
            "dstaddr": [{"name": "USED-DST"}],
            "service": [{"name": "all"}],
        }
    ]
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
    policies = [
        {
            "policyid": 1,
            "action": 1,
            "srcaddr": [],
            "dstaddr": [],
            "service": [{"name": "HTTP"}],
        }
    ]
    services = [{"name": "HTTP"}, {"name": "ORPHAN-SVC"}]
    result = find_unused_objects(policies, [], [], services, [])
    names = [o["name"] for o in result["unused_services"]]
    assert "ORPHAN-SVC" in names
    assert "HTTP" not in names


def test_addr_group_member_not_orphaned():
    # MEMBER-ADDR is only used inside GROUP-A, which IS referenced by a policy — not an orphan
    policies = [
        {
            "policyid": 1,
            "action": 1,
            "srcaddr": [{"name": "GROUP-A"}],
            "dstaddr": [{"name": "all"}],
            "service": [{"name": "all"}],
        }
    ]
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


# ── Redundant rule detection ───────────────────────────────────────────────────


def _p(pid, name, src, dst, svc, action=1, status="enable"):
    return {
        "policyid": pid,
        "name": name,
        "action": action,
        "status": status,
        "srcaddr": [{"name": s} for s in src],
        "dstaddr": [{"name": d} for d in dst],
        "service": [{"name": sv} for sv in svc],
    }


def test_redundant_exact_match_flagged():
    """Two identical enabled rules — later one is flagged."""
    a = _p(1, "rule-a", ["SrcA"], ["DstA"], ["HTTP"])
    b = _p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"])
    findings = check_redundant_rules([a, b])
    assert len(findings) == 1
    assert findings[0]["policy_id"] == "2"
    assert findings[0]["check"] == "redundant"
    assert "rule-a" in findings[0]["detail"]


def test_redundant_different_action_not_flagged():
    """Same traffic scope but different actions — not redundant."""
    a = _p(1, "rule-a", ["SrcA"], ["DstA"], ["HTTP"], action=1)
    b = _p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"], action=0)
    findings = check_redundant_rules([a, b])
    assert findings == []


def test_redundant_superset_not_flagged():
    """A covers B but B does not cover A — this is shadowing, not redundancy."""
    a = _p(1, "rule-a", ["all"], ["DstA"], ["HTTP"])
    b = _p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"])
    findings = check_redundant_rules([a, b])
    assert findings == []


def test_redundant_disabled_rule_skipped():
    """Disabled rules are not evaluated."""
    a = _p(1, "rule-a", ["SrcA"], ["DstA"], ["HTTP"], status="disable")
    b = _p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"])
    findings = check_redundant_rules([a, b])
    assert findings == []


def test_redundant_policy_block_skipped():
    """Policy-block entries are skipped."""
    a = _p(1, "rule-a", ["SrcA"], ["DstA"], ["HTTP"])
    b = {
        **_p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"]),
        "_policy_block": "ThreatBlock",
    }
    findings = check_redundant_rules([a, b])
    assert findings == []


def test_redundant_each_rule_flagged_once():
    """Three identical rules — only the 2nd and 3rd are flagged, each once."""
    a = _p(1, "rule-a", ["SrcA"], ["DstA"], ["HTTP"])
    b = _p(2, "rule-b", ["SrcA"], ["DstA"], ["HTTP"])
    c = _p(3, "rule-c", ["SrcA"], ["DstA"], ["HTTP"])
    findings = check_redundant_rules([a, b, c])
    flagged_ids = {f["policy_id"] for f in findings}
    assert "2" in flagged_ids
    assert "3" in flagged_ids
    assert "1" not in flagged_ids


# ── Over-permissive rules ──────────────────────────────────────────────────────


def _op(policyid, srcaddr, dstaddr, service, action=1, status=1):
    return {
        "policyid": policyid,
        "name": f"rule-{policyid}",
        "action": action,
        "status": status,
        "srcaddr": srcaddr,
        "dstaddr": dstaddr,
        "service": service,
    }


def test_over_permissive_all_three_is_critical():
    p = _op(1, ["all"], ["all"], ["ALL"])
    findings = check_over_permissive([p])
    assert len(findings) == 1
    assert findings[0]["check"] == "over_permissive"
    assert findings[0]["severity"] == "critical"
    assert "Fully open" in findings[0]["detail"]


def test_over_permissive_src_and_svc_is_high():
    p = _op(1, ["all"], ["10.0.0.0/8"], ["ALL"])
    findings = check_over_permissive([p])
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert "source" in findings[0]["detail"]
    assert "service" in findings[0]["detail"]


def test_over_permissive_dst_and_svc_is_high():
    p = _op(1, ["10.0.0.1"], ["all"], ["ANY"])
    findings = check_over_permissive([p])
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_over_permissive_src_and_dst_is_high():
    p = _op(1, ["any"], ["any"], ["HTTP"])
    findings = check_over_permissive([p])
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_over_permissive_only_one_dimension_not_flagged():
    p = _op(1, ["all"], ["10.0.0.1"], ["HTTP"])
    findings = check_over_permissive([p])
    assert len(findings) == 0


def test_over_permissive_deny_action_skipped():
    p = _op(1, ["all"], ["all"], ["ALL"], action=0)
    findings = check_over_permissive([p])
    assert len(findings) == 0


def test_over_permissive_disabled_rule_skipped():
    p = _op(1, ["all"], ["all"], ["ALL"], status=0)
    findings = check_over_permissive([p])
    assert len(findings) == 0


def test_over_permissive_policy_block_skipped():
    p = {**_op(1, ["all"], ["all"], ["ALL"]), "_policy_block": "ThreatFeeds-VDOMs"}
    findings = check_over_permissive([p])
    assert len(findings) == 0
