import os
import time
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret")
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app

    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def authed(client):
    with client.session_transaction() as s:
        s["user"] = "testuser"
        s["role"] = "admin"
        s["allowed_tabs"] = ["rule_review"]
        s["ad_groups"] = []
        s["login_at"] = int(time.time())
        s["_csrf_token"] = "test-csrf"
    return client


def _post(client, url, payload):
    """POST with JSON body and CSRF header."""
    return client.post(
        url,
        json=payload,
        headers={"X-CSRF-Token": "test-csrf"},
    )


def _mock_client_ctx(devices=None, vdoms=None):
    """Return a context manager mock for make_client()."""
    cm = MagicMock()
    inst = MagicMock()
    inst.get_devices.return_value = devices or []
    inst.get_device_vdoms.return_value = vdoms or []
    cm.__enter__ = MagicMock(return_value=inst)
    cm.__exit__ = MagicMock(return_value=False)
    cm.return_value = cm
    return cm


def test_devices_returns_name_and_ip(authed):
    raw = [
        {"name": "FW-CORP1", "ip": "10.0.0.1"},
        {"name": "FW-EDGE2", "ip": "10.0.0.2"},
    ]
    cm = _mock_client_ctx(devices=raw)
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = authed.get("/api/rule-review/adoms/Enterprise/devices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert any(d["name"] == "FW-CORP1" for d in data)


def test_devices_returns_empty_on_fmg_error(authed):
    cm = MagicMock()
    cm.__enter__ = MagicMock(side_effect=Exception("FMG down"))
    cm.__exit__ = MagicMock(return_value=False)
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = authed.get("/api/rule-review/adoms/Enterprise/devices")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_vdoms_returns_list(authed):
    raw = [{"name": "VDOM-Corp"}, {"name": "root"}]
    cm = _mock_client_ctx(vdoms=raw)
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = authed.get("/api/rule-review/adoms/Enterprise/devices/FW-CORP1/vdoms")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "root" in data
    assert "VDOM-Corp" in data


def test_vdoms_returns_root_only_when_empty(authed):
    cm = _mock_client_ctx(vdoms=[])
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = authed.get("/api/rule-review/adoms/Enterprise/devices/FW-SIMPLE/vdoms")
    assert resp.status_code == 200
    assert resp.get_json() == ["root"]


def test_vdoms_returns_root_only_when_single_root(authed):
    cm = _mock_client_ctx(vdoms=[{"name": "root"}])
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = authed.get("/api/rule-review/adoms/Enterprise/devices/FW-SIMPLE/vdoms")
    assert resp.status_code == 200
    assert resp.get_json() == ["root"]


def test_devices_requires_auth(client):
    resp = client.get("/api/rule-review/adoms/Enterprise/devices")
    assert resp.status_code in (302, 401, 403)


def _mock_full_client(
    packages=None, policies=None, devices=None, vdoms=None, scope_members=None
):
    """Full mock supporting analyze path."""
    cm = MagicMock()
    inst = MagicMock()
    inst.get_devices.return_value = devices or []
    inst.get_device_vdoms.return_value = vdoms or []
    inst.get_policy_packages.return_value = packages or []
    inst.get_policies.return_value = policies or []
    inst.get_address_objects.return_value = []
    inst.get_address_groups.return_value = []
    inst.get_service_objects.return_value = []
    inst.get_service_groups.return_value = []
    inst.get_pkg_scope_members.return_value = scope_members or []
    inst.get_device_interfaces_all_vdoms.return_value = []
    inst.get_device_routes_all_vdoms.return_value = []
    cm.__enter__ = MagicMock(return_value=inst)
    cm.__exit__ = MagicMock(return_value=False)
    cm.return_value = cm
    return cm


def test_analyze_rejects_old_packages_payload(authed):
    """rr_analyze must return 400 when 'selections' key is missing."""
    resp = _post(
        authed,
        "/api/rule-review/analyze",
        {
            "flows": [{"src": "10.1.1.1", "dst": "10.2.2.2", "service": "tcp/443"}],
            "packages": [
                {"adom": "Ent", "name": "pkg", "path": "pkg", "device": "FW1"}
            ],
        },
    )
    assert resp.status_code == 400
    assert "selections" in resp.get_json().get("error", "").lower()


def test_analyze_no_package_found_returns_error_result(authed):
    """When device/VDOM has no installed package, result verdict must be ERROR."""
    pkgs = []  # no packages installed on device
    cm = _mock_full_client(packages=pkgs)
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = _post(
            authed,
            "/api/rule-review/analyze",
            {
                "flows": [{"src": "10.1.1.1", "dst": "10.2.2.2", "service": "tcp/443"}],
                "selections": [
                    {"adom": "Enterprise", "device": "FW-CORP1", "vdoms": ["root"]}
                ],
                "metadata": {
                    "change_number": "CHG-001",
                    "owner": "Test",
                    "justification": "",
                },
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(r["verdict"] == "ERROR" for r in data["results"])


def test_analyze_metadata_echoed_in_response(authed):
    """metadata block from request must appear in response."""
    pkgs = [
        {
            "name": "PKG-CORP",
            "path": "PKG-CORP",
            "scope member": [{"name": "FW-CORP1", "vdom": "root"}],
        }
    ]
    cm = _mock_full_client(packages=pkgs)
    with patch("app.routes.rule_review_routes.make_client", return_value=cm):
        resp = _post(
            authed,
            "/api/rule-review/analyze",
            {
                "flows": [{"src": "10.1.1.1", "dst": "10.2.2.2", "service": "tcp/443"}],
                "selections": [
                    {"adom": "Enterprise", "device": "FW-CORP1", "vdoms": ["root"]}
                ],
                "metadata": {
                    "change_number": "CHG-9999",
                    "owner": "Alice",
                    "justification": "x",
                },
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["metadata"]["change_number"] == "CHG-9999"
    assert data["metadata"]["owner"] == "Alice"
