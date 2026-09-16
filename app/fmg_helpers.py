"""Shared FortiManager client factory.

Import this instead of duplicating _make_client() in every blueprint::

    from app.fmg_helpers import make_client

    with make_client() as client:
        devices = client.get_devices("root")
"""

from app.fmg_client import FMGClient
from app.config import Config


def make_client() -> FMGClient:
    """Return a configured FMGClient for the primary FortiManager host.

    Uses bearer token auth when FMG_API_TOKEN is set; falls back to
    username/password otherwise.
    """
    return FMGClient(
        host=Config.FMG_PRIMARY_HOST,
        username=Config.FMG_USERNAME,
        password=Config.FMG_PASSWORD,
        token=Config.FMG_API_TOKEN,
        verify_ssl=Config.FMG_VERIFY_SSL,
        timeout=Config.FMG_TIMEOUT,
    )


def parse_license_payload(raw_payload) -> dict:
    """Parse FortiOS /api/v2/monitor/license/status results dict.

    Returns {"status": "licensed"|"expired"|"unknown", "expires": "YYYY-MM-DD"|None}.
    raw_payload is the `payload` value from `client._proxy()` — pass `raw.get('payload', {})`.
    """
    import time
    from datetime import datetime, timezone

    results = raw_payload if isinstance(raw_payload, dict) else {}
    forticare = results.get("forticare", {})
    enhanced = forticare.get("support", {}).get("enhanced", {})
    status = enhanced.get("status", "")
    expires_ts = enhanced.get("expires")
    if status == "licensed" and expires_ts:
        if expires_ts > time.time():
            exp_str = datetime.fromtimestamp(expires_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            return {"status": "licensed", "expires": exp_str}
        return {"status": "expired", "expires": None}
    return {"status": "unknown", "expires": None}
