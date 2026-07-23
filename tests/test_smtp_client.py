import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_load_smtp_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    cfg = smtp_client.load_smtp_config()
    assert cfg["port"] == 25
    assert cfg["tls_mode"] == "none"
    assert cfg["run_history_days"] == 30
    assert cfg["enabled"] is False


def test_save_and_reload_smtp_config(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "mail.internal", "port": 587, "tls_mode": "starttls",
                                   "username": "", "password": "", "from_address": "noreply@x.com",
                                   "run_history_days": 14, "enabled": True})
    cfg = smtp_client.load_smtp_config()
    assert cfg["host"] == "mail.internal"
    assert cfg["port"] == 587
    assert cfg["run_history_days"] == 14


def test_test_connection_returns_error_when_smtp_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "127.0.0.1", "port": 19999, "tls_mode": "none",
                                   "username": "", "password": "", "from_address": "test@x.com",
                                   "run_history_days": 30, "enabled": True})
    result = smtp_client.test_connection("dest@x.com")
    assert result["ok"] is False
    assert "error" in result


def test_send_email_raises_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("app.smtp_client._CONFIG_PATH", tmp_path / "smtp_config.json")
    from app import smtp_client
    smtp_client.save_smtp_config({"host": "mail.internal", "port": 25, "tls_mode": "none",
                                   "username": "", "password": "", "from_address": "",
                                   "run_history_days": 30, "enabled": False})
    with pytest.raises(RuntimeError, match="SMTP not enabled"):
        smtp_client.send_email("x@x.com", "Test", "<p>hi</p>")
