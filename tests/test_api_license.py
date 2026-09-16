import os
import time

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

import json
import pytest
from unittest.mock import patch


@pytest.fixture
def app():
    from app import create_app

    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in(client, app):
    """Log in as admin."""
    with client.session_transaction() as sess:
        sess["user"] = "admin"
        sess["role"] = "admin"
        sess["allowed_tabs"] = ["versions", "firewalls"]
        sess["login_at"] = int(time.time())
        sess["_csrf_token"] = "test-csrf"
    return client


def test_all_license_returns_cache(logged_in):
    fake_cache = {
        "devices": [
            {
                "name": "FW-A",
                "adom": "Corp",
                "status": "licensed",
                "expires": "2026-12-31",
                "firmware": "v7.4.3",
            }
        ],
        "last_updated": "2026-09-16T12:00:00+00:00",
        "status": "ok",
        "error": None,
    }
    with patch("app.routes.api_routes.license_cache.get_cached", return_value=fake_cache):
        rv = logged_in.get("/api/devices/all/license")
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert data["status"] == "ok"
    assert len(data["devices"]) == 1


def test_all_license_refresh(logged_in):
    with patch("app.routes.api_routes.license_cache.refresh_now") as mock_refresh:
        rv = logged_in.post(
            "/api/devices/all/license/refresh",
            headers={"X-CSRF-Token": "test-csrf"},
        )
    assert rv.status_code == 200
    assert json.loads(rv.data)["queued"] is True
    mock_refresh.assert_called_once()


def test_adom_license_returns_filtered(logged_in):
    fake_devices = [
        {
            "name": "FW-A",
            "adom": "Corp",
            "status": "licensed",
            "expires": "2026-12-31",
            "firmware": "v7.4.3",
        }
    ]
    with patch(
        "app.routes.api_routes.license_cache.get_cached_adom",
        return_value=fake_devices,
    ):
        rv = logged_in.get("/api/adoms/Corp/license")
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert len(data["devices"]) == 1
    assert data["devices"][0]["name"] == "FW-A"


def test_all_license_requires_login(client):
    rv = client.get("/api/devices/all/license")
    assert rv.status_code in (302, 401, 403)
