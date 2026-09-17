"""Per-device FortiCare license status cache.

Fetches /api/v2/monitor/license/status via FMG proxy for every device in
every non-system ADOM. Runs at startup and every LICENSE_CACHE_INTERVAL_MIN
minutes (default 60). Reads are instant — the background job writes while
callers read from the frozen snapshot.

State
-----
_store["devices"]      list[dict]  — one record per device
_store["last_updated"] str | None  — ISO-8601 UTC timestamp
_store["status"]       str         — "pending" | "running" | "ok" | "error"
_store["error"]        str | None  — last error message

Per-device record keys: name, adom, status, expires, firmware
"""

import logging
import os
import threading
import time as _time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_store: dict = {
    "devices": [],
    "last_updated": None,
    "status": "pending",
    "error": None,
}

_lock = threading.Lock()
_running = threading.Event()


def get_cached() -> dict:
    """Return a copy of the cache store — safe to read from any thread."""
    with _lock:
        return dict(_store)


def get_cached_adom(adom: str) -> list:
    """Return cached device records for a single ADOM."""
    with _lock:
        return [d for d in _store["devices"] if d.get("adom") == adom]


def _build_version(device: dict) -> str:
    os_ver = device.get("os_ver", 0)
    mr = device.get("mr")
    patch = device.get("patch")
    major = (
        int(os_ver) // 100 if str(os_ver).isdigit() and int(os_ver) >= 100 else os_ver
    )
    if mr is not None and patch is not None and int(patch) >= 0:
        return f"v{major}.{mr}.{patch}"
    if mr is not None:
        return f"v{major}.{mr}"
    return "n/a"


def _run_job(app):
    """Fetch all-ADOM license status and update the cache."""
    if _running.is_set():
        logger.info("license_cache: already running, skipping overlap")
        return

    _running.set()
    with _lock:
        _store["status"] = "running"
        _store["error"] = None

    logger.info("license_cache: starting refresh")
    t0 = _time.monotonic()

    try:
        from app.fmg_helpers import make_client, parse_license_payload

        result = []
        with make_client() as client:
            adoms_raw = client.get_adoms()
            adom_names = [
                a.get("name", "")
                for a in adoms_raw
                if isinstance(a, dict) and a.get("name")
            ]
            adom_names = [
                n for n in adom_names if n and not n.lower().startswith("forti")
            ]

            for adom in adom_names:
                try:
                    devices = client.get_devices(adom)
                except Exception as exc:
                    logger.warning(
                        "license_cache: get_devices(%s) failed: %s", adom, exc
                    )
                    continue

                for d in devices:
                    if not isinstance(d, dict):
                        continue
                    device_name = d.get("name", "")
                    if not device_name:
                        continue
                    try:
                        firmware = _build_version(d)
                        raw = client._proxy(
                            adom, device_name, "/api/v2/monitor/license/status"
                        )
                        # Retry with the management VDOM when the default
                        # (root) call fails — happens on multi-VDOM devices
                        # whose mgt_vdom is not root.
                        if not raw.get("payload"):
                            mgt_vdom = d.get("mgt_vdom", "").strip('"')
                            if mgt_vdom and mgt_vdom.lower() != "root":
                                raw = client._proxy(
                                    adom,
                                    device_name,
                                    f"/api/v2/monitor/license/status?vdom={mgt_vdom}",
                                )
                        lic = parse_license_payload(raw.get("payload", {}))
                        if lic["status"] == "unknown" and d.get("conn_status", 0) != 1:
                            lic["status"] = "offline"
                    except Exception as exc:
                        logger.warning(
                            "license_cache: proxy(%s/%s) failed: %s",
                            adom,
                            device_name,
                            exc,
                        )
                        firmware = "n/a"
                        lic = {
                            "status": "unknown",
                            "expires": None,
                            "subscriptions": {},
                        }
                    result.append(
                        {
                            "name": device_name,
                            "adom": adom,
                            "status": lic["status"],
                            "expires": lic["expires"],
                            "firmware": firmware,
                            "subscriptions": lic.get("subscriptions", {}),
                        }
                    )

        elapsed = round(_time.monotonic() - t0, 1)
        logger.info(
            "license_cache: done in %ss — %d devices across %d ADOMs",
            elapsed,
            len(result),
            len(adom_names),
        )

        with _lock:
            _store["devices"] = result
            _store["last_updated"] = datetime.now(timezone.utc).isoformat()
            _store["status"] = "ok"
            _store["error"] = None

    except Exception as exc:
        logger.exception("license_cache: unhandled error: %s", exc)
        with _lock:
            _store["status"] = "error"
            _store["error"] = str(exc)
    finally:
        _running.clear()


def refresh_now(app):
    """Trigger an immediate background refresh (non-blocking)."""
    t = threading.Thread(
        target=_run_job, args=[app], name="license_cache_refresh", daemon=True
    )
    t.start()


def init_scheduler(app):
    """Start the interval scheduler and fire an immediate warm-up."""
    from apscheduler.schedulers.background import BackgroundScheduler

    interval_min = int(os.environ.get("LICENSE_CACHE_INTERVAL_MIN", "60"))

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=_run_job,
        args=[app],
        trigger="interval",
        minutes=interval_min,
        id="license_cache_refresh",
        name="License cache refresh",
    )
    scheduler.start()
    logger.info("license_cache: scheduler started — every %d minutes", interval_min)

    t = threading.Thread(
        target=_run_job, args=[app], name="license_cache_startup", daemon=True
    )
    t.start()

    return scheduler
