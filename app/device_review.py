"""Device Review check engine.

Each CHECK entry in CHECKS describes one analysis that can be run against a
device.  To add a new check:

  1. Write a function  _run_<name>(device_name, device_data, params) -> list[Row]
  2. Append an entry to CHECKS (key, name, description, severity, data_keys,
     params_schema, run).

Row fields
----------
device      — device name
interface   — interface name, or "system" for device-level checks
vdom        — VDOM name (or "" / "root")
ip          — IP/prefix of the interface, or "" for system checks
type        — interface type, or "system"
status      — interface status, or "" for system checks
check       — display name of the check that produced this row
result      — "INSECURE" | "WARN" | "INFO"  (interface check)
              "PASS" | "FAIL" | "CONFIG_MISSING"  (CIS checks)
detail      — human-readable finding detail
protocols   — list of {name, secure} dicts (interface check only; [] for CIS)
has_insecure — bool convenience flag (interface check; False for CIS rows)
has_secure   — bool convenience flag (interface check; False for CIS rows)

data_keys / params_schema
-------------------------
data_keys    — list of device_data keys this check needs fetched
               ("interfaces", "ntp", "syslog").  Routes fetch only what is
               required by the selected checks.
params_schema — list of input descriptors that the UI should render before a
               run.  Each entry:
                 { key, label, type ("ip_list"), placeholder, required (bool) }
               Empty list means no user input needed (binary check).
"""

from __future__ import annotations
from typing import Any


# ── Protocol security classification ─────────────────────────────────────────

_PROTO_SECURE: dict[str, bool | None] = {
    "https": True,
    "ssh": True,
    "snmp": True,
    "fabric": True,  # Fortinet Security Fabric (management-plane)
    "http": False,
    "telnet": False,
    "http-redirect": False,
    "ping": None,  # informational
    "fgfm": None,  # FortiGate-to-FortiManager
    "capwap": None,  # wireless controller
    "speed-test": None,
    "ftm": None,  # FortiToken Mobile
}


def _classify_proto(name: str) -> bool | None:
    """Return True=secure, False=insecure, None=informational."""
    return _PROTO_SECURE.get(name.lower(), None)


# ── Interface helpers ─────────────────────────────────────────────────────────


def _ip_str(iface: dict) -> str:
    raw = iface.get("ip") or iface.get("ipv4") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        raw = raw.get("ip", "")
    s = str(raw).strip()
    # CMDB returns "A.B.C.D M.M.M.M" — normalise to "A.B.C.D/M.M.M.M"
    if " " in s:
        s = s.replace(" ", "/", 1)
    return s


def _has_ip(iface: dict) -> bool:
    addr = _ip_str(iface)
    return bool(addr) and addr.split("/")[0] not in ("", "0.0.0.0")


def _allowed_protos(iface: dict) -> list[str]:
    """Return list of lower-cased allowed-access protocol tokens."""
    raw = iface.get("allowaccess") or iface.get("allow-access") or ""
    if isinstance(raw, list):
        tokens = [str(t).lower().strip() for t in raw if t]
    else:
        tokens = str(raw).replace(",", " ").lower().split()
    return [t for t in tokens if t]


# ── CIS param helpers ─────────────────────────────────────────────────────────


def _parse_ip_list(raw: Any) -> list[str]:
    """Normalise a param value into a list of stripped, non-empty IP strings."""
    if isinstance(raw, list):
        return [s.strip() for s in raw if str(s).strip()]
    if isinstance(raw, str):
        return [s.strip() for s in raw.replace(",", " ").split() if s.strip()]
    return []


# ── Check: Interface Protocols ────────────────────────────────────────────────


def _run_interface_protocols(
    device_name: str, device_data: dict, params: dict
) -> list[dict]:
    """Return every interface that has an IP address and any management access."""
    rows: list[dict] = []
    for iface in device_data.get("interfaces", []):
        if not isinstance(iface, dict):
            continue
        if not _has_ip(iface):
            continue
        protos = _allowed_protos(iface)
        if not protos:
            continue

        proto_list = [{"name": p, "secure": _classify_proto(p)} for p in sorted(protos)]
        has_insecure = any(p["secure"] is False for p in proto_list)
        has_secure = any(p["secure"] is True for p in proto_list)

        if has_insecure:
            result = "INSECURE"
        elif not has_secure:
            result = "WARN"
        else:
            result = "INFO"

        rows.append(
            {
                "device": device_name,
                "interface": iface.get("name", ""),
                "vdom": iface.get("vdom", ""),
                "ip": _ip_str(iface),
                "type": (iface.get("type") or "").lower(),
                "status": (iface.get("status") or "").lower(),
                "check": "Interface Protocols",
                "result": result,
                "detail": "",
                "protocols": proto_list,
                "has_insecure": has_insecure,
                "has_secure": has_secure,
            }
        )

    return rows


# ── Check: NTP Configuration (CIS) ───────────────────────────────────────────


def _run_ntp_config(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify NTP is enabled and configured servers match expected IPs."""
    ntp = device_data.get("ntp", {})
    expected = _parse_ip_list(params.get("expected_servers", []))

    def _row(result: str, detail: str) -> dict:
        return {
            "device": device_name,
            "interface": "system",
            "vdom": "",
            "ip": "",
            "type": "system",
            "status": "",
            "check": "NTP Configuration (CIS)",
            "result": result,
            "detail": detail,
            "protocols": [],
            "has_insecure": False,
            "has_secure": False,
        }

    if not ntp:
        return [_row("FAIL", "NTP configuration could not be retrieved from device")]

    sync_enabled = str(ntp.get("ntpsync", "disable")).lower() == "enable"
    if not sync_enabled:
        return [_row("FAIL", "NTP sync is disabled (ntpsync=disable)")]

    # Extract configured server addresses
    raw_servers = ntp.get("ntpserver", [])
    if isinstance(raw_servers, dict):
        raw_servers = list(raw_servers.values())
    configured = [
        str(s.get("server", "")).strip()
        for s in raw_servers
        if isinstance(s, dict) and s.get("server")
    ]

    if not expected:
        detail = "NTP sync enabled. Configured: " + (
            ", ".join(configured) if configured else "(none)"
        )
        return [_row("CONFIG_MISSING", detail)]

    missing = [ip for ip in expected if ip not in configured]
    extra = [ip for ip in configured if ip not in expected]

    if missing:
        detail = (
            f"Missing expected server(s): {', '.join(missing)}. "
            f"Configured: {', '.join(configured) or '(none)'}"
        )
        return [_row("FAIL", detail)]

    detail = "Configured: " + ", ".join(configured)
    if extra:
        detail += f". Additional (unlisted) servers: {', '.join(extra)}"
    return [_row("PASS", detail)]


# ── Check: Syslog Configuration (CIS) ────────────────────────────────────────


def _run_syslog_config(device_name: str, device_data: dict, params: dict) -> list[dict]:
    """CIS: verify syslog is enabled and sending to expected server IPs."""
    servers = device_data.get("syslog", [])
    expected = _parse_ip_list(params.get("expected_servers", []))

    def _row(result: str, detail: str) -> dict:
        return {
            "device": device_name,
            "interface": "system",
            "vdom": "",
            "ip": "",
            "type": "system",
            "status": "",
            "check": "Syslog Configuration (CIS)",
            "result": result,
            "detail": detail,
            "protocols": [],
            "has_insecure": False,
            "has_secure": False,
        }

    configured = [
        str(s.get("server", "")).strip()
        for s in servers
        if isinstance(s, dict) and s.get("server")
    ]

    if not configured:
        if not expected:
            return [
                _row("CONFIG_MISSING", "No remote syslog servers enabled on device")
            ]
        return [_row("FAIL", "No remote syslog servers enabled on device")]

    if not expected:
        detail = "Syslog enabled. Configured: " + ", ".join(configured)
        return [_row("CONFIG_MISSING", detail)]

    missing = [ip for ip in expected if ip not in configured]
    extra = [ip for ip in configured if ip not in expected]

    if missing:
        detail = (
            f"Missing expected server(s): {', '.join(missing)}. "
            f"Configured: {', '.join(configured)}"
        )
        return [_row("FAIL", detail)]

    detail = "Configured: " + ", ".join(configured)
    if extra:
        detail += f". Additional (unlisted) servers: {', '.join(extra)}"
    return [_row("PASS", detail)]


# ── Check registry ────────────────────────────────────────────────────────────

CHECKS: list[dict[str, Any]] = [
    {
        "key": "interface_protocols",
        "name": "Interface Protocols",
        "description": "Shows all interfaces with management access — highlights insecure protocols (HTTP, Telnet)",
        "data_keys": ["interfaces"],
        "params_schema": [],
        "run": _run_interface_protocols,
    },
    {
        "key": "ntp_config",
        "name": "NTP Configuration (CIS)",
        "description": "CIS: verify NTP sync is enabled and configured servers match expected IPs",
        "data_keys": ["ntp"],
        "params_schema": [
            {
                "key": "expected_servers",
                "label": "Expected NTP Servers",
                "type": "ip_list",
                "placeholder": "e.g. 10.1.1.1, 10.1.1.2",
                "required": False,
            }
        ],
        "run": _run_ntp_config,
    },
    {
        "key": "syslog_config",
        "name": "Syslog Configuration (CIS)",
        "description": "CIS: verify remote syslog is enabled and sending to expected server IPs",
        "data_keys": ["syslog"],
        "params_schema": [
            {
                "key": "expected_servers",
                "label": "Expected Syslog Servers",
                "type": "ip_list",
                "placeholder": "e.g. 10.2.2.1, 10.2.2.2",
                "required": False,
            }
        ],
        "run": _run_syslog_config,
    },
]

# Serialisable metadata (no "run" key) — used by page template and API
CHECKS_META: list[dict[str, Any]] = [
    {k: v for k, v in c.items() if k != "run"} for c in CHECKS
]

_CHECKS_BY_KEY: dict[str, dict] = {c["key"]: c for c in CHECKS}


# ── Public entry point ────────────────────────────────────────────────────────


def run_checks(
    device_name: str,
    device_data: dict,
    check_keys: list[str] | None = None,
    check_params: dict | None = None,
) -> list[dict]:
    """Run the requested checks and return combined rows.

    *check_keys* defaults to all registered checks.
    *check_params* maps check key → dict of user-supplied parameter values.
    *device_data* must contain all keys required by the selected checks
    (interfaces, ntp, syslog) — callers are responsible for fetching them.
    """
    keys = check_keys if check_keys is not None else [c["key"] for c in CHECKS]
    params_map = check_params or {}
    rows: list[dict] = []
    for key in keys:
        entry = _CHECKS_BY_KEY.get(key)
        if entry:
            params = params_map.get(key, {})
            rows.extend(entry["run"](device_name, device_data, params))
    return rows
