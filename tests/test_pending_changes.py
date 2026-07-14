import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")

from unittest.mock import patch, MagicMock
import pytest

from app.fmg_client import FMGClient, FMGError


# ── get_devices_with_sync_status ─────────────────────────────────────────────

def _make_client():
    return FMGClient(host="fmg.example.com", token="tok")


def test_get_devices_with_sync_status_returns_normalized_conf_status():
    client = _make_client()
    raw_devices = [
        {"name": "FW1", "ip": "10.0.0.1", "conf_status": 1, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT001"},
        {"name": "FW2", "ip": "10.0.0.2", "conf_status": 2, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT002"},
        {"name": "FW3", "ip": "10.0.0.3", "conf_status": 0, "platform_str": "FGT", "os_ver": 700, "mr": 4, "patch": 1, "sn": "FGT003"},
    ]
    with patch.object(client, "_get", return_value=raw_devices):
        result = client.get_devices_with_sync_status("MyADOM")
    assert len(result) == 3
    assert result[0]["conf_status"] == "insync"
    assert result[1]["conf_status"] == "outofsync"
    assert result[2]["conf_status"] == "unknown"


def test_get_devices_with_sync_status_empty_adom():
    client = _make_client()
    with patch.object(client, "_get", return_value=[]):
        result = client.get_devices_with_sync_status("EmptyADOM")
    assert result == []


# ── get_install_preview ───────────────────────────────────────────────────────

def _task_response(percent, state=0, num_err=0):
    return {"result": [{"status": {"code": 0}, "data": [{"percent": percent, "state": state, "num_err": num_err}]}]}


def _trigger_response(taskid=42):
    return {"result": [{"status": {"code": 0}, "data": {"task": taskid}}]}


def _adom_info_response(oid=1):
    return {"result": [{"status": {"code": 0}, "data": {"oid": oid}}]}


def _device_info_response(oid=101, vdom_oid=1, vdom_name="root"):
    return {
        "result": [{
            "status": {"code": 0},
            "data": {"oid": oid, "vdom": [{"oid": vdom_oid, "name": vdom_name}]},
        }]
    }


def _preview_result_response(device_name, diff_text):
    import json as _json
    return {
        "result": [{
            "status": {"code": 0},
            "data": {"message": _json.dumps([{"name": device_name, "result": diff_text}])}
        }]
    }


def test_get_install_preview_returns_diff_text():
    client = _make_client()
    diff = "config firewall policy\n    edit 1\n        set action accept\n    next\nend\n"
    responses = [
        _adom_info_response(),               # GET dvmdb/adom/MyADOM
        _device_info_response(),             # GET dvmdb/adom/MyADOM/device/FW1
        _trigger_response(taskid=99),        # POST securityconsole/install/preview
        _task_response(100),                 # GET task/task/99 → done
        _preview_result_response("FW1", diff),  # GET securityconsole/preview/result
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == diff


def test_get_install_preview_polls_until_complete():
    client = _make_client()
    diff = "config system global\nend\n"
    responses = [
        _adom_info_response(),
        _device_info_response(),
        _trigger_response(taskid=5),
        _task_response(33),        # first poll — not done
        _task_response(66),        # second poll — still not done
        _task_response(100),       # third poll — done
        _preview_result_response("FW1", diff),
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == diff


def test_get_install_preview_raises_on_timeout(monkeypatch):
    client = _make_client()
    # Override PREVIEW_TIMEOUT_SECS to 0 so we time out immediately
    monkeypatch.setattr("app.fmg_client.PREVIEW_TIMEOUT_SECS", 0)

    adom_info = _adom_info_response()
    device_info = _device_info_response()
    trigger = _trigger_response(taskid=7)
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return adom_info
        if call_count[0] == 2:
            return device_info
        if call_count[0] == 3:
            return trigger
        return _task_response(50)

    with patch.object(client, "_post", side_effect=side_effect), \
         patch("time.sleep"):
        with pytest.raises(FMGError, match="timed out"):
            client.get_install_preview("MyADOM", "FW1")


def test_get_install_preview_returns_empty_string_when_no_changes():
    client = _make_client()
    responses = [
        _adom_info_response(),
        _device_info_response(),
        _trigger_response(taskid=3),
        _task_response(100),
        # result message has no entry matching device name
        {"result": [{"status": {"code": 0}, "data": {"message": "[]"}}]},
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        result = client.get_install_preview("MyADOM", "FW1")
    assert result == ""


def test_get_install_preview_raises_on_trigger_failure():
    client = _make_client()
    trigger_failure = {"result": [{"status": {"code": -6}, "data": {}}]}
    responses = [
        _adom_info_response(),
        _device_info_response(),
        trigger_failure,
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        with pytest.raises(FMGError):
            client.get_install_preview("MyADOM", "FW1")


def test_get_install_preview_raises_on_task_error_state():
    client = _make_client()
    responses = [
        _adom_info_response(),
        _device_info_response(),
        _trigger_response(taskid=10),
        _task_response(100, num_err=1),  # num_err > 0 signals task failure
    ]
    with patch.object(client, "_post", side_effect=responses), \
         patch("time.sleep"):
        with pytest.raises(FMGError):
            client.get_install_preview("MyADOM", "FW1")


# ── parse_preview_diff ────────────────────────────────────────────────────────

def test_parse_preview_diff_empty():
    from app.fmg_client import parse_preview_diff
    result = parse_preview_diff("")
    assert result["summary"] == {"firewall_policy": 0, "routing": 0, "address": 0, "service": 0, "system": 0, "other": 0}
    assert result["vdoms"] == [{"name": "root", "changes": []}]


def test_parse_preview_diff_categorises_firewall_policy():
    from app.fmg_client import parse_preview_diff
    raw = "config firewall policy\n    edit 1\n        set action accept\n    next\nend\n"
    result = parse_preview_diff(raw)
    assert result["summary"]["firewall_policy"] == 1
    assert result["summary"]["routing"] == 0
    assert len(result["vdoms"]) == 1
    assert result["vdoms"][0]["name"] == "root"
    assert len(result["vdoms"][0]["changes"]) > 0


def test_parse_preview_diff_categorises_routing():
    from app.fmg_client import parse_preview_diff
    raw = "config router static\n    edit 1\n        set dst 10.0.0.0 255.0.0.0\n    next\nend\n"
    result = parse_preview_diff(raw)
    assert result["summary"]["routing"] == 1


def test_parse_preview_diff_splits_vdoms():
    from app.fmg_client import parse_preview_diff
    raw = (
        "vdom root\nconfig firewall policy\n    edit 1\nend\n"
        "vdom dmz\nconfig system global\nend\n"
    )
    result = parse_preview_diff(raw)
    names = [v["name"] for v in result["vdoms"]]
    assert "root" in names
    assert "dmz" in names


def test_parse_preview_diff_raw_preserved():
    from app.fmg_client import parse_preview_diff
    raw = "config firewall policy\nend\n"
    result = parse_preview_diff(raw)
    assert result["raw"] == raw


# ── Route smoke tests ─────────────────────────────────────────────────────────

@pytest.fixture
def app():
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app
    return create_app()

@pytest.fixture
def client(app):
    return app.test_client()

def test_pending_changes_page_redirects_unauthenticated(client):
    resp = client.get("/pending-changes")
    assert resp.status_code in (302, 401)

def test_pending_changes_adoms_redirects_unauthenticated(client):
    resp = client.get("/api/pending-changes/adoms")
    assert resp.status_code in (302, 401)

def test_pending_changes_devices_redirects_unauthenticated(client):
    resp = client.get("/api/pending-changes/adoms/MyADOM/devices")
    assert resp.status_code in (302, 401)
