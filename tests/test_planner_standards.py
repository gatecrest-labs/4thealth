import pytest
from app.planner.standards import (
    risk_level, permissiveness_warnings, review_requirements,
    object_name, policy_name,
)
from app.planner.matching import parse_service_request


def test_risk_level_critical_internet():
    domains = {"OT_Zone": "OT", "Internet": "Internet"}
    assert risk_level(["OT_Zone"], ["Internet"], domains) == "critical"


def test_risk_level_high_cross_domain():
    domains = {"Corp": "Corporate", "DMZ": "DMZ"}
    assert risk_level(["Corp"], ["DMZ"], domains) == "high"


def test_risk_level_medium_same_domain():
    domains = {"ZoneA": "Corporate", "ZoneB": "Corporate"}
    assert risk_level(["ZoneA"], ["ZoneB"], domains) == "medium"


def test_risk_level_unknown_zone_is_critical():
    # Unresolvable zone → fail safe → critical
    domains = {"KnownZone": "Corporate"}
    result = risk_level(["KnownZone"], ["UnknownZone"], domains)
    assert result == "critical"


def test_permissiveness_any_source():
    warnings = permissiveness_warnings(["0.0.0.0/0"], ["10.1.2.3"], [])
    assert any("source" in w.lower() or "any" in w.lower() for w in warnings)


def test_permissiveness_wide_cidr():
    svc = parse_service_request("tcp/443")
    warnings = permissiveness_warnings(["10.0.0.0/8"], ["192.168.1.1"], svc)
    assert any("/8" in w or "wide" in w.lower() or "broad" in w.lower() for w in warnings)


def test_object_name_host():
    assert object_name("host", ip="10.1.2.3/32") == "H_10.1.2.3"


def test_object_name_network():
    assert object_name("network", ip="10.1.0.0/16") == "N_10.1.0.0_16"


def test_object_name_service():
    assert object_name("service", proto="tcp", port="443") == "SVC_TCP_443"


def test_policy_name():
    name = policy_name("CHG001", "lan", "wan")
    assert "CHG001" in name
    assert "LAN" in name
    assert "WAN" in name


def test_review_requirements_returns_dict():
    req = review_requirements("high")
    assert "approvers" in req
    assert "sla_hours" in req
