"""Persistent store for map region configuration.

Region state assignments are defined here as defaults and are read-only from
the admin UI.  Only per-region colours and the catch-all "other" colour are
user-configurable and are written back to map_regions.json in the project root.
"""

import copy
import json
import os
import re
import tempfile
import threading

_LOCK = threading.Lock()

_DEFAULT: dict = {
    "regions": [
        {
            "name": "Upper Midwest",
            "color": "#1976d2",
            "states": ["Minnesota", "Wisconsin", "North Dakota", "South Dakota"],
        },
        {
            "name": "Colorado",
            "color": "#e53935",
            "states": ["Colorado"],
        },
        {
            "name": "Southwest",
            "color": "#43a047",
            "states": ["Texas", "New Mexico"],
        },
    ],
    "other_color": "#333333",
}

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "map_regions.json")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def load() -> dict:
    """Return current region config, merging persisted colors with default state assignments."""
    with _LOCK:
        if os.path.exists(_PATH):
            try:
                with open(_PATH) as f:
                    saved = json.load(f)
                # Re-apply saved colors onto the canonical region list so state
                # assignments always reflect the defaults even if the file is stale.
                out = copy.deepcopy(_DEFAULT)
                color_map = {r["name"]: r["color"] for r in saved.get("regions", [])}
                for region in out["regions"]:
                    if region["name"] in color_map:
                        region["color"] = color_map[region["name"]]
                out["other_color"] = saved.get("other_color", _DEFAULT["other_color"])
                return out
            except Exception:
                pass
        return copy.deepcopy(_DEFAULT)


def save(data: dict) -> None:
    """Write region config to disk atomically."""
    out = copy.deepcopy(data)
    with _LOCK:
        dir_ = os.path.dirname(_PATH)
        with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as tmp:
            json.dump(out, tmp, indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path, _PATH)


def is_valid_color(color: str) -> bool:
    return bool(_HEX_RE.match(color or ""))
