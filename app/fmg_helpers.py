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


_FORTIGUARD_SUBS = [
    "antivirus",
    "ips",
    "web_filtering",
    "appctrl",
    "antispam",
    "outbreak_prevention",
    "firmware_updates",
    "forticloud_sandbox",
    "ai_malware_detection",
    "blacklisted_certificates",
]


def parse_license_payload(raw_payload) -> dict:
    """Parse FortiOS /api/v2/monitor/license/status results dict.

    Returns {
        "status": "licensed"|"expired"|"unknown",
        "expires": "YYYY-MM-DD"|None,
        "subscriptions": {key: {"status": "licensed"|"expired"|"none"|"unknown", "expires": str|None}, ...}
    }.
    raw_payload is the `payload` value from `client._proxy()` — pass `raw.get('payload', {})`.
    """
    import time
    from datetime import datetime, timezone

    now = time.time()
    results = raw_payload if isinstance(raw_payload, dict) else {}

    # FortiCare support contract (primary license health indicator)
    forticare = results.get("forticare", {})
    enhanced = forticare.get("support", {}).get("enhanced", {})
    status = enhanced.get("status", "")
    expires_ts = enhanced.get("expires")
    if status in ("licensed", "expires_soon") and expires_ts:
        if expires_ts > now:
            exp_str = datetime.fromtimestamp(expires_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            lic_status, lic_expires = "licensed", exp_str
        else:
            lic_status, lic_expires = "expired", None
    else:
        lic_status, lic_expires = "unknown", None

    # FortiGuard subscription statuses
    subs = {}
    for key in _FORTIGUARD_SUBS:
        entry = results.get(key, {})
        s = entry.get("status", "")
        exp_ts = entry.get("expires")
        if s in ("licensed", "expires_soon"):
            if exp_ts and exp_ts <= now:
                subs[key] = {"status": "expired", "expires": None}
            elif exp_ts:
                subs[key] = {
                    "status": "licensed",
                    "expires": datetime.fromtimestamp(exp_ts, tz=timezone.utc).strftime(
                        "%Y-%m-%d"
                    ),
                }
            else:
                subs[key] = {"status": "licensed", "expires": None}
        elif s in ("no_license", "free_license"):
            subs[key] = {"status": "none", "expires": None}
        else:
            subs[key] = {"status": "unknown", "expires": None}

    return {"status": lic_status, "expires": lic_expires, "subscriptions": subs}
