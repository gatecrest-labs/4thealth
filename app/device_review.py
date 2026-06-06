"""Device Review check engine.

Each CHECK entry in CHECKS describes one analysis that can be run against a
device's interfaces.  To add a new check:

  1. Write a function  run_<name>(device_name, interfaces) -> list[InterfaceRow]
  2. Append an entry to CHECKS (key, name, description, run).

An InterfaceRow is a dict:
  device      — device name
  interface   — interface name
  vdom        — VDOM name (or "" / "root" for non-VDOM devices)
  ip          — IP/prefix of the interface (or "")
  type        — interface type (e.g. "vlan", "physical", "aggregate")
  protocols   — list of dicts: [{name, secure}]
                  secure=True  → HTTPS, SSH, SNMP
                  secure=False → HTTP, Telnet
                  secure=None  → informational (PING, FMG-access, …)
  has_insecure — bool convenience flag
  has_secure   — bool convenience flag

No findings are "skipped" — every interface with any management access protocol
is returned so the user can see a complete inventory and decide what to export.
"""

from __future__ import annotations
from typing import Any


# ── Protocol security classification ─────────────────────────────────────────

_PROTO_SECURE: dict[str, bool | None] = {
    "https":      True,
    "ssh":        True,
    "snmp":       True,
    "fabric":     True,   # Fortinet Security Fabric (management-plane)
    "http":       False,
    "telnet":     False,
    "http-redirect": False,
    "ping":       None,   # informational
    "fgfm":       None,   # FortiGate-to-FortiManager
    "capwap":     None,   # wireless controller
    "speed-test": None,
    "ftm":        None,   # FortiToken Mobile
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


# ── Check: Interface Protocols ────────────────────────────────────────────────

def _run_interface_protocols(
    device_name: str, interfaces: list[dict]
) -> list[dict]:
    """Return every interface that has an IP address and any management access.

    Each row carries a full protocol inventory so the UI can render badges
    colour-coded by security classification.
    """
    rows: list[dict] = []
    for iface in interfaces:
        if not isinstance(iface, dict):
            continue
        if not _has_ip(iface):
            continue
        protos = _allowed_protos(iface)
        if not protos:
            continue  # no management access at all — skip

        proto_list = [
            {"name": p, "secure": _classify_proto(p)}
            for p in sorted(protos)
        ]
        has_insecure = any(p["secure"] is False for p in proto_list)
        has_secure   = any(p["secure"] is True  for p in proto_list)

        rows.append({
            "device":       device_name,
            "interface":    iface.get("name", ""),
            "vdom":         iface.get("vdom", ""),
            "ip":           _ip_str(iface),
            "type":         (iface.get("type") or "").lower(),
            "status":       (iface.get("status") or "").lower(),
            "protocols":    proto_list,
            "has_insecure": has_insecure,
            "has_secure":   has_secure,
        })

    return rows


# ── Check registry ────────────────────────────────────────────────────────────

CHECKS: list[dict[str, Any]] = [
    {
        "key":         "interface_protocols",
        "name":        "Interface Protocols",
        "description": "Shows all interfaces with management access — highlights insecure protocols (HTTP, Telnet)",
        "run":         _run_interface_protocols,
    },
]

# Serialisable metadata (no "run" key) — used by page template and API
CHECKS_META: list[dict[str, str]] = [
    {k: v for k, v in c.items() if k != "run"}
    for c in CHECKS
]

_CHECKS_BY_KEY: dict[str, dict] = {c["key"]: c for c in CHECKS}


# ── Public entry point ────────────────────────────────────────────────────────

def run_checks(
    device_name: str,
    interfaces: list[dict],
    check_keys: list[str] | None = None,
) -> list[dict]:
    """Run the requested checks and return combined rows.

    *check_keys* defaults to all registered checks.
    """
    keys = check_keys if check_keys is not None else [c["key"] for c in CHECKS]
    rows: list[dict] = []
    for key in keys:
        entry = _CHECKS_BY_KEY.get(key)
        if entry:
            rows.extend(entry["run"](device_name, interfaces))
    return rows
