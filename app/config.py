"""Application configuration loaded from environment / .env file."""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = Path(__file__).parent.parent


def _load_infra_targets() -> list:
    path = _BASE_DIR / "infra_targets.json"
    if path.exists():
        with path.open() as f:
            return json.load(f)
    return []


def _require_secret_key() -> str:
    val = os.environ.get("SECRET_KEY", "")
    if not val or val == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is not set or is the insecure default. "
            "Generate one with: python manage_users.py secret"
        )
    return val


class Config:
    SECRET_KEY = _require_secret_key()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Auto-enable when SSL cert/key are present; can also be forced via .env
    _ssl_active = os.path.exists(os.environ.get("SSL_CERT", "certs/cert.pem")) and \
                  os.path.exists(os.environ.get("SSL_KEY",  "certs/key.pem"))
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto").lower() == "true" or \
                            (os.environ.get("COOKIE_SECURE", "auto").lower() == "auto" and _ssl_active)
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(4 * 1024 * 1024)))

    # Infrastructure dashboard targets — loaded from infra_targets.json
    INFRA_TARGETS: list = _load_infra_targets()

    # Primary FortiManager host — used for ADOM/device queries (fmg_helpers.py)
    FMG_PRIMARY_HOST = os.environ.get("FMG_PRIMARY_HOST", "")

    FMG_USERNAME  = os.environ.get("FMG_USERNAME", "")
    FMG_PASSWORD  = os.environ.get("FMG_PASSWORD", "")
    FMG_API_TOKEN = os.environ.get("FMG_API_TOKEN", "")

    FMG_VERIFY_SSL = os.environ.get("FMG_VERIFY_SSL", "true").lower() == "true"
    FMG_TIMEOUT    = int(os.environ.get("FMG_TIMEOUT", "30"))

    # Health thresholds (yellow / red)
    CPU_WARN  = int(os.environ.get("CPU_WARN",  "70"))
    CPU_CRIT  = int(os.environ.get("CPU_CRIT",  "90"))
    MEM_WARN  = int(os.environ.get("MEM_WARN",  "75"))
    MEM_CRIT  = int(os.environ.get("MEM_CRIT",  "90"))

    # RADIUS / FortiAuthenticator (optional)
    RADIUS_ENABLED      = os.environ.get("RADIUS_ENABLED",  "false").lower() == "true"
    RADIUS_HOST         = os.environ.get("RADIUS_HOST",     "")
    RADIUS_PORT         = int(os.environ.get("RADIUS_PORT", "1812"))
    # Secondary FAC for HA / maintenance failover — leave blank if not used
    RADIUS_HOST_2       = os.environ.get("RADIUS_HOST_2",   "")
    RADIUS_PORT_2       = int(os.environ.get("RADIUS_PORT_2", "1812"))
    RADIUS_SECRET       = os.environ.get("RADIUS_SECRET",   "")
    RADIUS_TIMEOUT      = int(os.environ.get("RADIUS_TIMEOUT", "10"))
    RADIUS_GROUP_ADMIN  = os.environ.get("RADIUS_GROUP_ADMIN",  "")
    RADIUS_GROUP_VIEWER = os.environ.get("RADIUS_GROUP_VIEWER", "")
