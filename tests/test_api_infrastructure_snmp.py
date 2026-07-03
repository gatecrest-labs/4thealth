"""Tests for /api/infrastructure sourcing CPU/mem from the SNMP cache."""

import os
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

import pytest

from app import create_app
from app.config import Config


@pytest.fixture
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_admin(client):
    with client.session_transaction() as sess:
        sess["user"] = "test-admin"
        sess["role"] = "admin"
        sess["allowed_tabs"] = ["dashboard"]
    return client


def test_infrastructure_uses_snmp_cache_for_fortimanager(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FMG-01", "host": "10.0.0.1", "type": "FortiManager", "token": "x"}],
    )
    with patch(
        "app.infra_health_cache.get_cached",
        return_value={"cpu": 41.0, "mem": 62.0, "snmp_status": "ok", "last_updated": "2026-07-03T00:00:00"},
    ):
        resp = logged_in_admin.get("/api/infrastructure")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["cpu"] == 41.0
    assert data[0]["mem"] == 62.0
    assert data[0]["snmp_status"] == "ok"
    # cpu=41 < CPU_WARN(70), mem=62 < MEM_WARN(75) -> green
    assert data[0]["status"] == "green"


def test_infrastructure_shows_gray_on_snmp_timeout(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FAC-01", "host": "10.0.0.3", "type": "FortiAuthenticator", "token": "x"}],
    )
    with patch(
        "app.infra_health_cache.get_cached",
        return_value={"cpu": None, "mem": None, "snmp_status": "timeout", "last_updated": "2026-07-03T00:00:00"},
    ):
        resp = logged_in_admin.get("/api/infrastructure")
    data = resp.get_json()
    assert data[0]["status"] == "gray"
    assert data[0]["cpu"] is None
    assert data[0]["snmp_status"] == "timeout"


def test_infrastructure_no_cache_entry_yet(monkeypatch, logged_in_admin):
    monkeypatch.setattr(
        Config,
        "INFRA_TARGETS",
        [{"label": "FAZ-01", "host": "10.0.0.2", "type": "FortiAnalyzer", "token": "x"}],
    )
    with patch("app.infra_health_cache.get_cached", return_value=None):
        resp = logged_in_admin.get("/api/infrastructure")
    data = resp.get_json()
    assert data[0]["status"] == "gray"
    assert data[0]["snmp_status"] is None
