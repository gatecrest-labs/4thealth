"""Unit tests for device_review helpers and check functions."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.device_review import (
    _parse_host_list,
    _resolve_host,
    _match_host,
    _run_ntp_config,
    _run_syslog_config,
    _run_log_faz,
    _run_dns,
)


# ── _parse_host_list ──────────────────────────────────────────────────────────

def test_parse_host_list_ips():
    assert _parse_host_list("10.1.1.1, 10.1.1.2") == ["10.1.1.1", "10.1.1.2"]

def test_parse_host_list_fqdns():
    assert _parse_host_list("ntp.corp.com, syslog.corp.com") == ["ntp.corp.com", "syslog.corp.com"]

def test_parse_host_list_mixed():
    assert _parse_host_list("10.1.1.1, ntp.corp.com") == ["10.1.1.1", "ntp.corp.com"]

def test_parse_host_list_list_input():
    assert _parse_host_list(["10.1.1.1", "ntp.corp.com"]) == ["10.1.1.1", "ntp.corp.com"]

def test_parse_host_list_empty():
    assert _parse_host_list("") == []

def test_parse_host_list_spaces():
    assert _parse_host_list("  10.1.1.1  ,  10.1.1.2  ") == ["10.1.1.1", "10.1.1.2"]


# ── _resolve_host ─────────────────────────────────────────────────────────────

def test_resolve_host_ip_passthrough():
    # Routable IPs pass through the filter unchanged
    _resolve_host.cache_clear()
    result = _resolve_host("10.1.1.1")
    assert "10.1.1.1" in result


def test_resolve_host_filters_loopback():
    # Loopback addresses (including DNS sinkholes like 127.0.53.53) must be
    # filtered out so two FQDNs that both resolve to a sinkhole IP don't
    # produce a false-positive match.
    _resolve_host.cache_clear()
    result = _resolve_host("127.0.0.1")
    assert result == frozenset()
    assert "127.0.0.1" not in result


def test_resolve_host_dns_error_returns_empty():
    _resolve_host.cache_clear()
    with patch("app.device_review.socket.getaddrinfo", side_effect=Exception("DNS error")):
        result = _resolve_host("nonexistent.invalid.test")
    assert result == frozenset()


# ── _match_host ───────────────────────────────────────────────────────────────

def test_match_host_direct_match():
    matched, annotation = _match_host("10.1.1.1", "10.1.1.1")
    assert matched is True
    assert annotation == ""

def test_match_host_direct_fqdn_match():
    matched, annotation = _match_host("ntp.corp.com", "ntp.corp.com")
    assert matched is True
    assert annotation == ""

def test_match_host_dns_match():
    # Both sides resolve to the same IP
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.1.1.1"} if h in ("ntp.corp.com", "10.1.1.1") else set()
        matched, annotation = _match_host("ntp.corp.com", "10.1.1.1")
    assert matched is True
    assert "via DNS" in annotation
    assert "ntp.corp.com" in annotation

def test_match_host_no_match():
    with patch("app.device_review._resolve_host", return_value=set()):
        matched, annotation = _match_host("10.1.1.1", "10.2.2.2")
    assert matched is False
    assert annotation == ""


# ── _run_ntp_config ───────────────────────────────────────────────────────────


NTP_DEVICE_DATA = {
    "ntp": {
        "ntpsync": "enable",
        "ntpserver": [
            {"server": "10.1.1.1"},
            {"server": "10.1.1.2"},
        ],
    }
}


def test_ntp_pass_direct_ip():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "10.1.1.1, 10.1.1.2"})
    assert len(rows) == 1
    assert rows[0]["result"] == "PASS"
    assert "10.1.1.1 ✓" in rows[0]["detail"]
    assert "10.1.1.2 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_fail_missing_server():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "10.1.1.1, 10.1.1.3"})
    assert rows[0]["result"] == "FAIL"
    assert "10.1.1.1 ✓" in rows[0]["detail"]
    assert "10.1.1.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.1.1.1"} if h in ("ntp.corp.com", "10.1.1.1") else set()
        rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {"expected_servers": "ntp.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_config_missing_no_params():
    rows = _run_ntp_config("FW-01", NTP_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.1.1.1, 10.1.1.2"


def test_ntp_fail_sync_disabled():
    data = {"ntp": {"ntpsync": "disable"}}
    rows = _run_ntp_config("FW-01", data, {"expected_servers": "10.1.1.1"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == ""


# ── _run_syslog_config ────────────────────────────────────────────────────────


SYSLOG_DEVICE_DATA = {
    "syslog": [
        {"server": "10.2.2.1"},
        {"server": "10.2.2.2"},
    ]
}


def test_syslog_pass_direct():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "10.2.2.1, 10.2.2.2"})
    assert rows[0]["result"] == "PASS"
    assert "10.2.2.1 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_fail_missing():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "10.2.2.1, 10.2.2.3"})
    assert rows[0]["result"] == "FAIL"
    assert "10.2.2.3 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.2.2.1"} if h in ("syslog.corp.com", "10.2.2.1") else set()
        rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {"expected_servers": "syslog.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


def test_syslog_config_missing_no_params():
    rows = _run_syslog_config("FW-01", SYSLOG_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.2.2.1, 10.2.2.2"


# ── _run_log_faz ──────────────────────────────────────────────────────────────


FAZ_DEVICE_DATA_ENABLED = {
    "log_faz": {"status": "enable", "server": "10.3.3.10"}
}
FAZ_DEVICE_DATA_DISABLED = {
    "log_faz": {"status": "disable", "server": ""}
}


def test_faz_pass_direct():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "10.3.3.10"})
    assert rows[0]["result"] == "PASS"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_fail_wrong_server():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "10.3.3.99"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.3.3.10"} if h in ("faz.corp.com", "10.3.3.10") else set()
        rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {"expected_servers": "faz.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_config_missing_no_params():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_ENABLED, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.3.3.10"


def test_faz_fail_disabled():
    rows = _run_log_faz("FW-01", FAZ_DEVICE_DATA_DISABLED, {"expected_servers": "10.3.3.10"})
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["ip"] == ""


# ── _run_dns ──────────────────────────────────────────────────────────────────


DNS_DEVICE_DATA = {
    "dns": {"primary": "10.4.4.1", "secondary": "10.4.4.2"}
}


def test_dns_pass_direct():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "10.4.4.1, 10.4.4.2"})
    assert rows[0]["result"] == "PASS"
    assert "10.4.4.1 ✓" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_fail_missing():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "10.4.4.1, 10.4.4.9"})
    assert rows[0]["result"] == "FAIL"
    assert "10.4.4.9 ✗" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_pass_via_dns():
    with patch("app.device_review._resolve_host") as mock_resolve:
        mock_resolve.side_effect = lambda h: {"10.4.4.1"} if h in ("dns.corp.com", "10.4.4.1") else set()
        rows = _run_dns("FW-01", DNS_DEVICE_DATA, {"expected_servers": "dns.corp.com"})
    assert rows[0]["result"] == "PASS"
    assert "via DNS" in rows[0]["detail"]
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"


def test_dns_config_missing_no_params():
    rows = _run_dns("FW-01", DNS_DEVICE_DATA, {})
    assert rows[0]["result"] == "CONFIG_MISSING"
    assert rows[0]["ip"] == "10.4.4.1, 10.4.4.2"
