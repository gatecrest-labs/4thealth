"""Unit tests for app.infra_health_cache — SNMP polling and cache."""

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

import pytest

from app import infra_health_cache as cache_mod


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with a clean in-memory cache."""
    with cache_mod._lock:
        cache_mod._cache.clear()
    yield
    with cache_mod._lock:
        cache_mod._cache.clear()


@pytest.fixture
def snmp_targets(monkeypatch):
    monkeypatch.setattr(
        cache_mod.Config,
        "INFRA_TARGETS",
        [
            {"label": "FMG-01", "host": "10.0.0.1", "type": "FortiManager"},
            {"label": "FAZ-01", "host": "10.0.0.2", "type": "FortiAnalyzer"},
            {"label": "FAC-01", "host": "10.0.0.3", "type": "FortiAuthenticator"},
            {"label": "FCT-01", "host": "10.0.0.4", "type": "FortiCollector"},
        ],
    )
    monkeypatch.setattr(cache_mod.Config, "SNMP_ENABLED", True)


def test_poll_all_targets_populates_cache_for_supported_types(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[12.5, 34.0])
    ):
        cache_mod.poll_all_targets()

    assert cache_mod.get_cached("10.0.0.1") == {
        "cpu": 12.5,
        "mem": 34.0,
        "snmp_status": "ok",
        "last_updated": cache_mod.get_cached("10.0.0.1")["last_updated"],
    }
    assert cache_mod.get_cached("10.0.0.2")["snmp_status"] == "ok"
    assert cache_mod.get_cached("10.0.0.3")["snmp_status"] == "ok"


def test_poll_all_targets_skips_unsupported_type(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[1.0, 2.0])
    ):
        cache_mod.poll_all_targets()

    assert cache_mod.get_cached("10.0.0.4") is None


def test_poll_all_targets_marks_timeout(snmp_targets):
    with patch.object(
        cache_mod,
        "_snmp_get",
        new=AsyncMock(side_effect=cache_mod.SnmpTimeout("no response")),
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    assert entry["snmp_status"] == "timeout"
    assert entry["cpu"] is None
    assert entry["mem"] is None


def test_poll_all_targets_marks_error_on_other_exceptions(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    assert entry["snmp_status"] == "error"
    assert entry["cpu"] is None


def test_poll_all_targets_noop_when_snmp_disabled(snmp_targets, monkeypatch):
    monkeypatch.setattr(cache_mod.Config, "SNMP_ENABLED", False)
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[1.0, 2.0])
    ) as mocked:
        cache_mod.poll_all_targets()
    mocked.assert_not_called()
    assert cache_mod.get_cached("10.0.0.1") is None


def test_get_cached_returns_copy_not_reference(snmp_targets):
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[5.0, 6.0])
    ):
        cache_mod.poll_all_targets()

    entry = cache_mod.get_cached("10.0.0.1")
    entry["cpu"] = 999
    assert cache_mod.get_cached("10.0.0.1")["cpu"] == 5.0


def test_resolve_snmp_creds_per_device_override(monkeypatch):
    monkeypatch.setattr(cache_mod.Config, "SNMP_USER", "default-user")
    monkeypatch.setattr(cache_mod.Config, "SNMP_AUTH_KEY", "default-auth")
    monkeypatch.setattr(cache_mod.Config, "SNMP_PRIV_KEY", "default-priv")
    monkeypatch.setattr(cache_mod.Config, "SNMP_AUTH_PROTOCOL", "SHA")
    monkeypatch.setattr(cache_mod.Config, "SNMP_PRIV_PROTOCOL", "AES")

    target = {"host": "10.0.0.9", "type": "FortiAuthenticator", "snmp_user": "override-user"}
    creds = cache_mod._resolve_snmp_creds(target)

    assert creds["user"] == "override-user"
    assert creds["auth_key"] == "default-auth"  # not overridden, falls back
    assert creds["priv_key"] == "default-priv"


def test_poll_all_targets_skips_target_missing_host(snmp_targets, monkeypatch):
    """Target missing 'host' key should be skipped without raising; other targets still polled."""
    monkeypatch.setattr(
        cache_mod.Config,
        "INFRA_TARGETS",
        [
            {"label": "Bad Entry", "type": "FortiManager"},  # no "host" key
            {"label": "FMG-01", "host": "10.0.0.1", "type": "FortiManager"},
        ],
    )
    with patch.object(
        cache_mod, "_snmp_get", new=AsyncMock(return_value=[1.0, 2.0])
    ):
        cache_mod.poll_all_targets()  # must not raise

    # Good target was polled successfully
    assert cache_mod.get_cached("10.0.0.1")["snmp_status"] == "ok"
