"""Tests for interface and NAT lookup endpoints."""
import os
import json
import pytest
from unittest.mock import patch


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret")
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "admin"
            sess["_csrf_token"] = "test-csrf"
        yield c


def _post(client, url, payload):
    """POST with JSON body and CSRF header to bypass CSRF validation."""
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        headers={"X-CSRF-Token": "test-csrf"},
    )


# ── Interface Lookup ──────────────────────────────────────────────────────────

def test_interface_lookup_returns_match(client):
    devices = [{"name": "FW-01"}]
    interfaces = [
        {"name": "port1", "ip": "10.1.2.3 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
        {"name": "port2", "ip": "192.168.1.1 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.return_value = interfaces
        resp = _post(client, "/api/hygiene/adoms/TestADOM/interfaces/lookup", {"ips": ["10.1.2.3"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["interface"] == "port1"
    assert data["results"][0]["device"] == "FW-01"
    assert data["skipped_devices"] == []


def test_interface_lookup_not_found(client):
    devices = [{"name": "FW-01"}]
    interfaces = [
        {"name": "port1", "ip": "192.168.1.1 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.return_value = interfaces
        resp = _post(client, "/api/hygiene/adoms/TestADOM/interfaces/lookup", {"ips": ["10.1.2.3"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 0
    assert data["results"] == []


def test_interface_lookup_skips_unreachable_device(client):
    devices = [{"name": "FW-01"}, {"name": "FW-02"}]

    def fake_ifaces(adom, device):
        if device == "FW-02":
            raise Exception("unreachable")
        return [{"name": "port1", "ip": "10.1.2.3 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"}]

    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.side_effect = fake_ifaces
        resp = _post(client, "/api/hygiene/adoms/TestADOM/interfaces/lookup", {"ips": ["10.1.2.3"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "FW-02" in data["skipped_devices"]


def test_interface_lookup_invalid_ip(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/interfaces/lookup", {"ips": ["not-an-ip"]})
    assert resp.status_code == 400
    assert "invalid" in resp.get_json()["error"].lower()


def test_interface_lookup_missing_ips(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/interfaces/lookup", {})
    assert resp.status_code == 400


# ── NAT Lookup ────────────────────────────────────────────────────────────────

def test_nat_lookup_matches_vip_extip(client):
    vips = [
        {
            "name": "vip_web",
            "extip": "203.0.113.10",
            "extintf": "wan1",
            "mappedip": [{"range": "10.0.0.1-10.0.0.1"}],
            "portforward": "disable",
            "protocol": "",
            "extport": "",
            "mappedport": "",
            "comment": "",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = vips
        inst.get_ippool_objects.return_value = []
        resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {"ip": "203.0.113.10"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["nat_type"] == "VIP"
    assert data["results"][0]["name"] == "vip_web"


def test_nat_lookup_matches_vip_mapped_ip(client):
    vips = [
        {
            "name": "vip_web",
            "extip": "203.0.113.10",
            "extintf": "wan1",
            "mappedip": [{"range": "10.0.0.5-10.0.0.10"}],
            "portforward": "disable",
            "protocol": "",
            "extport": "",
            "mappedport": "",
            "comment": "",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = vips
        inst.get_ippool_objects.return_value = []
        resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {"ip": "10.0.0.7"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["name"] == "vip_web"


def test_nat_lookup_matches_ippool(client):
    pools = [
        {
            "name": "outbound_pool",
            "startip": "203.0.113.1",
            "endip": "203.0.113.20",
            "type": "overload",
            "comments": "Corp PAT",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = []
        inst.get_ippool_objects.return_value = pools
        resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {"ip": "203.0.113.10"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["nat_type"] == "IP Pool"
    assert data["results"][0]["name"] == "outbound_pool"


def test_nat_lookup_not_found(client):
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = []
        inst.get_ippool_objects.return_value = []
        resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {"ip": "1.2.3.4"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 0


def test_nat_lookup_invalid_ip(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {"ip": "not-an-ip"})
    assert resp.status_code == 400


def test_nat_lookup_missing_ip(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/nat/lookup", {})
    assert resp.status_code == 400
