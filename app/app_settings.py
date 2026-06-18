"""Application settings — persistent key/value store backed by app_settings.json."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

_SETTINGS_PATH = Path(__file__).parent.parent / "app_settings.json"
_DEFAULTS: dict = {
    "external_api_enabled": False,
}
_lock = threading.Lock()


def _load() -> dict:
    if not _SETTINGS_PATH.exists():
        return dict(_DEFAULTS)
    try:
        with open(_SETTINGS_PATH) as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except Exception:
        return dict(_DEFAULTS)


def _save(data: dict) -> None:
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _SETTINGS_PATH)


def get_setting(key: str, default=None):
    with _lock:
        data = _load()
    return data.get(key, default)


def set_setting(key: str, value) -> None:
    with _lock:
        data = _load()
        data[key] = value
        _save(data)


def get_all() -> dict:
    with _lock:
        return _load()
