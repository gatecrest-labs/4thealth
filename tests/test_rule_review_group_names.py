# tests/test_rule_review_group_names.py
from app.rule_review import _looks_like_fgt_name, _expand_addr_name, _expand_svc_name


def test_looks_like_fgt_name_detects_names():
    assert _looks_like_fgt_name("CORP-SERVERS") is True
    assert _looks_like_fgt_name("GRP-WEB-01") is True


def test_looks_like_fgt_name_rejects_ips():
    assert _looks_like_fgt_name("10.1.2.3") is False
    assert _looks_like_fgt_name("192.168.0.0/24") is False


def test_looks_like_fgt_name_rejects_port_specs():
    assert _looks_like_fgt_name("tcp/443") is False
    assert _looks_like_fgt_name("443") is False


def test_looks_like_fgt_name_rejects_any():
    assert _looks_like_fgt_name("any") is False
    assert _looks_like_fgt_name("") is False


def test_expand_addr_name_finds_group():
    addr_objects = [
        {"name": "HOST-10-1-1-1", "subnet": "10.1.1.1 255.255.255.255"},
        {"name": "NET-10-2-0-0", "subnet": "10.2.0.0 255.255.0.0"},
    ]
    addr_groups = [
        {
            "name": "CORP-SERVERS",
            "member": [{"name": "HOST-10-1-1-1"}, {"name": "NET-10-2-0-0"}],
        }
    ]
    result = _expand_addr_name("CORP-SERVERS", addr_objects, addr_groups)
    assert result is not None
    assert "10.1.1.1/255.255.255.255" in result
    assert "10.2.0.0/255.255.0.0" in result


def test_expand_addr_name_returns_none_when_not_found():
    result = _expand_addr_name("NONEXISTENT", [], [])
    assert result is None


def test_expand_addr_name_finds_direct_object():
    addr_objects = [{"name": "HOST-ABC", "subnet": "10.0.0.1 255.255.255.255"}]
    result = _expand_addr_name("HOST-ABC", addr_objects, [])
    assert result == ["10.0.0.1/255.255.255.255"]


def test_expand_svc_name_finds_group():
    svc_objects = [
        {"name": "HTTP", "tcp-portrange": "80"},
        {"name": "HTTPS", "tcp-portrange": "443"},
    ]
    svc_groups = [
        {"name": "WEB-PORTS", "member": [{"name": "HTTP"}, {"name": "HTTPS"}]}
    ]
    result = _expand_svc_name("WEB-PORTS", svc_objects, svc_groups)
    assert result is not None
    assert "tcp/80" in result
    assert "tcp/443" in result


def test_expand_svc_name_returns_none_when_not_found():
    result = _expand_svc_name("NONEXISTENT", [], [])
    assert result is None
