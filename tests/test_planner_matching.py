import ipaddress
import pytest
from app.planner.matching import (
    AddressCatalog, ServiceCatalog, PolicyMatcher,
    PortRange, parse_service_request,
)

def test_port_range_contains():
    wide = PortRange("tcp", 80, 8080)
    point = PortRange("tcp", 443, 443)
    assert wide.contains(point)
    assert not point.contains(wide)

def test_parse_service_request_tcp():
    ranges = parse_service_request("tcp/8443")
    assert ranges == [PortRange("tcp", 8443, 8443)]

def test_parse_service_request_wellknown():
    ranges = parse_service_request("ssh")
    assert PortRange("tcp", 22, 22) in ranges

def test_parse_service_request_wildcard():
    from app.planner.matching import WILDCARD_RANGE
    assert parse_service_request("any") == [WILDCARD_RANGE]

def test_service_catalog_resolves_object():
    objs = [{"name": "MY_SVC", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "8443"}]
    catalog = ServiceCatalog(objs, [])
    result = catalog.ranges_for_ref("MY_SVC")
    assert result is not None
    assert PortRange("tcp", 8443, 8443) in result

def test_service_catalog_resolves_group():
    objs = [{"name": "HTTP", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "80"}]
    groups = [{"name": "WEB", "member": [{"name": "HTTP"}]}]
    catalog = ServiceCatalog(objs, groups)
    result = catalog.ranges_for_ref("WEB")
    assert result is not None
    assert PortRange("tcp", 80, 80) in result

def test_service_catalog_unknown_returns_none():
    catalog = ServiceCatalog([], [])
    assert catalog.ranges_for_ref("UNKNOWN_SVC") is None

def test_address_catalog_resolves_ipmask():
    objs = [{"name": "HOST_A", "type": "ipmask", "subnet": ["10.1.2.3", "255.255.255.255"]}]
    catalog = AddressCatalog(objs, [])
    nets = catalog.networks_for_ref("HOST_A")
    assert nets is not None
    assert ipaddress.ip_network("10.1.2.3/32") in nets

def test_address_catalog_all_wildcard():
    catalog = AddressCatalog([], [])
    nets = catalog.networks_for_ref("all")
    assert nets == [ipaddress.ip_network("0.0.0.0/0")]

def test_policy_matcher_full_cover():
    addr_objs = [{"name": "SRC", "type": "ipmask", "subnet": ["10.0.0.0", "255.0.0.0"]}]
    svc_objs = [{"name": "HTTP", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "80"}]
    addr_cat = AddressCatalog(addr_objs, [])
    svc_cat = ServiceCatalog(svc_objs, [])
    matcher = PolicyMatcher(addr_cat, svc_cat)
    policy = {
        "policyid": 1, "name": "PERMIT_WEB", "action": "accept", "status": "enable",
        "srcaddr": [{"name": "SRC"}], "dstaddr": [{"name": "all"}],
        "service": [{"name": "HTTP"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    svc_ranges = parse_service_request("tcp/80")
    result = matcher.evaluate(policy, "10.1.2.3", "192.168.1.1", svc_ranges)
    assert result.matched
    assert result.full_cover
    assert result.action == "accept"

def test_policy_matcher_no_match_wrong_service():
    addr_objs = [{"name": "SRC", "type": "ipmask", "subnet": ["10.0.0.0", "255.0.0.0"]}]
    svc_objs = [{"name": "HTTP", "protocol": "TCP/UDP/SCTP", "tcp-portrange": "80"}]
    addr_cat = AddressCatalog(addr_objs, [])
    svc_cat = ServiceCatalog(svc_objs, [])
    matcher = PolicyMatcher(addr_cat, svc_cat)
    policy = {
        "policyid": 1, "name": "PERMIT_WEB", "action": "accept", "status": "enable",
        "srcaddr": [{"name": "SRC"}], "dstaddr": [{"name": "all"}],
        "service": [{"name": "HTTP"}],
        "srcintf": [{"name": "any"}], "dstintf": [{"name": "any"}],
    }
    svc_ranges = parse_service_request("tcp/443")
    result = matcher.evaluate(policy, "10.1.2.3", "192.168.1.1", svc_ranges)
    assert not result.full_cover
