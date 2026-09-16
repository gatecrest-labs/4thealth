import time
import pytest
from app.fmg_helpers import parse_license_payload


def _make_payload(status, expires_offset=None):
    """Build a minimal forticare results dict."""
    d = {"forticare": {"support": {"enhanced": {"status": status}}}}
    if expires_offset is not None:
        d["forticare"]["support"]["enhanced"]["expires"] = (
            int(time.time()) + expires_offset
        )
    return d


def test_licensed_future():
    result = parse_license_payload(_make_payload("licensed", expires_offset=86400))
    assert result["status"] == "licensed"
    assert result["expires"] is not None


def test_licensed_expired():
    result = parse_license_payload(_make_payload("licensed", expires_offset=-1))
    assert result["status"] == "expired"
    assert result["expires"] is None


def test_unknown_no_status():
    result = parse_license_payload({})
    assert result["status"] == "unknown"
    assert result["expires"] is None


def test_unknown_wrong_status():
    result = parse_license_payload(_make_payload("no_license"))
    assert result["status"] == "unknown"


def test_non_dict_input():
    for bad in (None, []):
        result = parse_license_payload(bad)
        assert result["status"] == "unknown"
        assert result["expires"] is None
        assert "subscriptions" in result


import app.license_cache as lc


def test_get_cached_initial_state(monkeypatch):
    monkeypatch.setattr(lc, "_store", {
        "devices": [], "last_updated": None, "status": "pending", "error": None
    })
    cached = lc.get_cached()
    assert cached["status"] == "pending"
    assert cached["devices"] == []
    assert cached["last_updated"] is None


def test_get_cached_adom_empty():
    result = lc.get_cached_adom("NonExistentADOM")
    assert result == []


def test_get_cached_adom_filter(monkeypatch):
    monkeypatch.setattr(
        lc,
        "_store",
        {
            "devices": [
                {"name": "FW-A", "adom": "Corp", "status": "licensed",
                 "expires": "2026-12-31", "firmware": "v7.4.3"},
                {"name": "FW-B", "adom": "Dev", "status": "expired",
                 "expires": None, "firmware": "v7.2.1"},
            ],
            "last_updated": "2026-09-16T12:00:00+00:00",
            "status": "ok",
            "error": None,
        },
    )
    corp = lc.get_cached_adom("Corp")
    assert len(corp) == 1
    assert corp[0]["name"] == "FW-A"
    dev = lc.get_cached_adom("Dev")
    assert len(dev) == 1
    assert dev[0]["name"] == "FW-B"
