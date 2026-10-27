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


def expand_ha_members(d: dict, version: str, adom: str, conn_status: int):
    """Yield one device-record dict per physical unit in an HA cluster (or one for standalone).

    FortiManager stores HA clusters as a single logical record whose ``ha_slave``
    list contains ALL physical members (the cluster record itself is not a unit).
    Standalone devices (no ha_slave entries) yield their own record unchanged.

    Each yielded dict has the same keys as the versions-cache records:
        name, ip, serial, platform, version, adom, status, ha_role

    ``ha_role`` is "Primary" / "Secondary" (derived from the ``prio`` field — higher
    priority = primary; first entry wins on a tie).  Standalone devices get "".
    """
    platform = str(d.get("platform_str") or d.get("platform") or "n/a").strip() or "n/a"
    try:
        ha_mode = int(d.get("ha_mode", 0))
    except (TypeError, ValueError):
        ha_mode = 0

    slaves = [s for s in (d.get("ha_slave") or []) if isinstance(s, dict)]

    # Standalone device — yield the record as-is
    if ha_mode == 0 or not slaves:
        yield {
            "name": d.get("name", ""),
            "ip": str(d.get("ip") or d.get("mgmt_ip") or "n/a"),
            "serial": str(d.get("sn") or d.get("serial") or "n/a"),
            "platform": platform,
            "version": version,
            "adom": adom,
            "status": "green" if conn_status == 1 else "offline",
            "ha_role": "",
        }
        return

    # HA cluster — the cluster record is logical; physical units are in ha_slave.
    # Determine which member is primary using HA priority (higher prio = primary).
    def _prio(s):
        try:
            return int(s.get("prio", 0))
        except (TypeError, ValueError):
            return 0

    slaves_sorted = sorted(slaves, key=_prio, reverse=True)
    for idx, slave in enumerate(slaves_sorted):
        try:
            sc = int(slave.get("conn_status", conn_status))
        except (TypeError, ValueError):
            sc = conn_status
        yield {
            "name": str(slave.get("name") or d.get("name") or ""),
            # Members rarely report their own IP; fall back to the cluster's
            "ip": str(
                slave.get("ip")
                or slave.get("mgmt_ip")
                or d.get("ip")
                or d.get("mgmt_ip")
                or "n/a"
            ),
            "serial": str(slave.get("sn") or slave.get("serial") or "n/a"),
            "platform": platform,
            "version": version,
            "adom": adom,
            "status": "green" if sc == 1 else "offline",
            "ha_role": "Primary" if idx == 0 else "Secondary",
        }


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
    elif results:
        # Payload returned but no valid FortiCare status — device not registered
        lic_status, lic_expires = "unregistered", None
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
