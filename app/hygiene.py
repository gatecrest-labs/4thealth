"""Rule hygiene checks — all logic is purely local; no writes to FortiManager or devices.

Each check function receives the full policy list and returns a list of finding dicts:
  {
    "policy_id":   str,
    "policy_name": str,
    "seq":         int,    # sequence number / index (1-based)
    "check":       str,    # check key
    "detail":      str,    # human-readable explanation
  }

CHECKS maps key -> display name.  Order here controls the dropdown order in the UI.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone


# ── Check registry ────────────────────────────────────────────────────────────

CHECKS: dict[str, str] = {
    "unnamed":        "Unnamed Rules (no comment/name)",
    "unlogged":       "Unlogged Rules (logging disabled)",
    "shadow":         "Shadow Rules (hidden by broader rule above)",
    "disabled":       "Disabled / Inactive Rules",
    "expired":        "Expired Rules (past schedule end-date)",
    "unhit":          "Unused / Un-Hit Rules (zero hit count)",
    "no_deny_all":    "Missing Deny-All Default Rule",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

# FMG returns many policy fields as integers rather than strings.
_STATUS_MAP    = {0: "disable",  1: "enable"}
_ACTION_MAP    = {0: "deny",     1: "accept",  2: "ipsec"}
_LOGTRAFFIC_MAP = {0: "disable", 1: "utm",     2: "all"}


def _fstr(val, default: str = "") -> str:
    """Safely convert any FMG field value to a lower-cased string."""
    if val is None:
        return default.lower()
    if isinstance(val, int):
        return str(val)
    return str(val).lower()


def _status(p: dict) -> str:
    """Return 'enable' or 'disable' regardless of whether FMG sent int or str."""
    v = p.get("status")
    if isinstance(v, int):
        return _STATUS_MAP.get(v, "enable")
    return (v or "enable").lower()


def _action(p: dict) -> str:
    """Return canonical action string regardless of whether FMG sent int or str."""
    v = p.get("action")
    if isinstance(v, int):
        return _ACTION_MAP.get(v, "accept")
    return (v or "accept").lower()


def _logtraffic(p: dict) -> str:
    """Return canonical logtraffic string regardless of whether FMG sent int or str."""
    v = p.get("logtraffic")
    if isinstance(v, int):
        return _LOGTRAFFIC_MAP.get(v, "disable")
    return (v or "").lower()


def _name(p: dict) -> str:
    return str(p.get("name") or p.get("policyid") or p.get("policyid", ""))


def _seq(p: dict, idx: int) -> int:
    return p.get("policyid", idx + 1)


def _addr_list(val) -> list[str]:
    """Normalize address fields: may be list of strings or list of dicts."""
    if not val:
        return []
    if isinstance(val, str):
        return [val]
    result = []
    for item in val:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            result.append(item.get("name", str(item)))
    return result


def _is_any(val) -> bool:
    names = _addr_list(val)
    return any(n.lower() == "all" or n.lower() == "any" for n in names)


def _svc_is_any(val) -> bool:
    names = _addr_list(val)
    return any(n.lower() in ("all", "any") for n in names)


def _is_policy_block(p: dict) -> bool:
    """Return True if this entry is a global policy-block, not a regular rule.

    FMG marks these with a non-empty '_policy_block' field (e.g. 'ThreatFeeds-VDOMs').
    They have empty src/dst/service and should not be evaluated by any hygiene check.
    """
    val = p.get("_policy_block")
    return bool(val and str(val).strip())


def _identity_set(p: dict) -> frozenset:
    """Return a frozenset of identity-match strings from fsso-groups, groups, users."""
    result: set[str] = set()
    for field in ("fsso-groups", "groups", "users"):
        val = p.get(field) or []
        if isinstance(val, str):
            result.add(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    result.add(item)
                elif isinstance(item, dict):
                    result.add(item.get("name", str(item)))
    return frozenset(result)


def _rule_summary(p: dict) -> dict:
    """Return a compact summary of a policy for use in shadow-finding detail payloads."""
    return {
        "id":          str(p.get("policyid", "?")),
        "name":        str(p.get("name") or ""),
        "status":      _status(p),
        "action":      _action(p),
        "srcaddr":     _addr_list(p.get("srcaddr") or p.get("src_addr")),
        "dstaddr":     _addr_list(p.get("dstaddr") or p.get("dst_addr")),
        "service":     _addr_list(p.get("service") or p.get("services")),
        "fsso_groups": _addr_list(p.get("fsso-groups")),
        "comment":     str(p.get("comments") or p.get("comment") or ""),
    }


def _covers(a_names: set[str], b_names: set[str]) -> bool:
    """Return True if address/service set A fully covers set B.

    True when A contains a wildcard name ('any'/'all'), or every name in B is
    also present in A (A is an exact superset of B by object name).
    Note: this cannot detect IP-range containment without expanding address
    objects, so it conservatively misses cases where A's subnets contain B's.
    """
    if not b_names:
        return True
    if any(n.lower() in ("any", "all") for n in a_names):
        return True
    return b_names <= a_names


# ── Individual check functions ────────────────────────────────────────────────

def check_unnamed(policies: list[dict]) -> list[dict]:
    """Rules that lack a name, a comment/description, or both."""
    findings = []
    for idx, p in enumerate(policies):
        if _is_policy_block(p):
            continue
        name    = str(p.get("name") or "").strip()
        comment = str(p.get("comments") or p.get("comment") or "").strip()
        pid     = p.get("policyid", idx + 1)
        if not name and not comment:
            findings.append({
                "policy_id":   str(pid),
                "policy_name": f"Policy #{pid}",
                "seq":         _seq(p, idx),
                "check":       "unnamed",
                "detail":      "Rule has no name and no comment.",
            })
        elif not name:
            findings.append({
                "policy_id":   str(pid),
                "policy_name": f"Policy #{pid}",
                "seq":         _seq(p, idx),
                "check":       "unnamed",
                "detail":      f"Rule has no name (only a comment: '{comment[:80]}').",
            })
        elif not comment:
            findings.append({
                "policy_id":   str(pid),
                "policy_name": name,
                "seq":         _seq(p, idx),
                "check":       "unnamed",
                "detail":      "Rule has a name but no comment/description.",
            })
    return findings


def check_unlogged(policies: list[dict]) -> list[dict]:
    """Rules where logtraffic is 'disable' or missing."""
    findings = []
    for idx, p in enumerate(policies):
        if _is_policy_block(p):
            continue
        log = _logtraffic(p)
        # FortiOS values: "all", "utm", "disable" (or int 0/1/2)
        if log in ("disable", "disabled", "") or not log:
            findings.append({
                "policy_id":   str(p.get("policyid", idx + 1)),
                "policy_name": _name(p),
                "seq":         _seq(p, idx),
                "check":       "unlogged",
                "detail":      f"logtraffic = '{log or 'not set'}' — no traffic logging.",
            })
    return findings


def check_shadow(policies: list[dict]) -> list[dict]:
    """Flag rules that will never be hit because an earlier rule already matches
    every connection that could reach them.

    Rule B (later) is fully shadowed by rule A (earlier) when all three traffic
    dimensions are covered:
      - A's source addresses cover all of B's source addresses
      - A's destination addresses cover all of B's destination addresses
      - A's services cover all of B's services

    Coverage means either: A uses 'any'/'all', or every named object in B is
    also present in A.  Action is intentionally NOT required to match — when A
    fully covers B's traffic scope, B is unreachable regardless of action.
    A difference in action (e.g. A=accept vs B=deny) is called out in the
    detail message as it often signals a policy ordering mistake.

    Only enabled rules are evaluated. Each shadowed rule is reported once,
    against the first shadowing rule found above it.

    Limitation: IP-range containment (e.g. 10.0.0.0/8 covering 10.1.0.0/24) is
    not detected without expanding address objects. Only exact name matches and
    'any'/'all' wildcards are checked.
    """
    findings = []
    enabled = [p for p in policies if _status(p) != "disable" and not _is_policy_block(p)]

    for j, b in enumerate(enabled):
        b_src  = set(_addr_list(b.get("srcaddr") or b.get("src_addr")))
        b_dst  = set(_addr_list(b.get("dstaddr") or b.get("dst_addr")))
        b_svc  = set(_addr_list(b.get("service") or b.get("services")))
        b_action  = _action(b)
        b_identity = _identity_set(b)

        for a in enabled[:j]:
            a_src  = set(_addr_list(a.get("srcaddr") or a.get("src_addr")))
            a_dst  = set(_addr_list(a.get("dstaddr") or a.get("dst_addr")))
            a_svc  = set(_addr_list(a.get("service") or a.get("services")))
            a_action  = _action(a)
            a_identity = _identity_set(a)

            if not (_covers(a_src, b_src) and _covers(a_dst, b_dst) and _covers(a_svc, b_svc)):
                continue

            # Identity mismatch: if either rule restricts to specific AD/FSSO groups
            # and they don't match, the rules are NOT functionally equivalent.
            if a_identity != b_identity:
                continue

            action_note = (
                f" Note: actions differ (shadowing={a_action}, shadowed={b_action}) — possible policy ordering mistake."
                if a_action != b_action else ""
            )
            findings.append({
                "policy_id":       str(b.get("policyid", j + 1)),
                "policy_name":     _name(b),
                "seq":             _seq(b, j),
                "check":           "shadow",
                "detail":          (
                    f"Fully shadowed by rule '{_name(a)}' (id {a.get('policyid', '?')}) "
                    f"which appears earlier and covers the same src/dst/service scope.{action_note}"
                ),
                "shadow_rule":     _rule_summary(b),
                "shadowing_rule":  _rule_summary(a),
            })
            break  # report only the first shadowing rule
    return findings


def check_disabled(policies: list[dict]) -> list[dict]:
    """Rules where status == 'disable'."""
    findings = []
    for idx, p in enumerate(policies):
        if _is_policy_block(p):
            continue
        if _status(p) == "disable":
            findings.append({
                "policy_id":   str(p.get("policyid", idx + 1)),
                "policy_name": _name(p),
                "seq":         _seq(p, idx),
                "check":       "disabled",
                "detail":      f"Rule status = '{_status(p)}'.",
            })
    return findings


def check_expired(policies: list[dict]) -> list[dict]:
    """Rules whose schedule has an end date in the past.

    FortiOS stores schedule as a string name reference; we can only inspect if
    the policy carries inline schedule-stop fields (schedule-timeout, expiry,
    or a 'schedule' field that looks like an end-date).  If the policy references
    a named schedule object we report it as 'has a time-based schedule — verify
    expiry' since we don't pull schedule objects here.
    """
    findings = []
    now = datetime.now(timezone.utc)

    for idx, p in enumerate(policies):
        if _is_policy_block(p):
            continue
        sched = p.get("schedule") or p.get("schedule_timeout") or ""
        if isinstance(sched, list) and sched:
            sched = sched[0] if isinstance(sched[0], str) else (sched[0].get("name", "") if isinstance(sched[0], dict) else "")

        sched_str = str(sched).strip().lower()
        if not sched_str or sched_str in ("always", "", "none"):
            continue

        # Try to parse as a date (FMG may return "YYYY/MM/DD HH:MM:SS" or "YYYY-MM-DD")
        parsed = None
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(sched_str, fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        if parsed:
            if parsed < now:
                findings.append({
                    "policy_id":   str(p.get("policyid", idx + 1)),
                    "policy_name": _name(p),
                    "seq":         _seq(p, idx),
                    "check":       "expired",
                    "detail":      f"Schedule end-date '{sched_str}' is in the past.",
                })
        else:
            # Named schedule — flag for manual review
            findings.append({
                "policy_id":   str(p.get("policyid", idx + 1)),
                "policy_name": _name(p),
                "seq":         _seq(p, idx),
                "check":       "expired",
                "detail":      f"References time-based schedule '{sched}' — verify it has not expired.",
            })
    return findings


def check_unhit(policies: list[dict]) -> list[dict]:
    """Rules with a hit count of zero.

    FMG stores hit counters with a leading underscore: _hitcount, _pkts, _bytes.
    Plain names (hitcount, hit_count, pkts) are also checked for compatibility.
    If no hit-count field is present the rule is skipped silently.
    """
    findings = []
    for idx, p in enumerate(policies):
        if _is_policy_block(p):
            continue
        # FMG uses underscore-prefixed names; also check plain names for safety
        hit = (
            p.get("_hitcount") if p.get("_hitcount") is not None else
            p.get("_pkts")     if p.get("_pkts")     is not None else
            p.get("hitcount")  if p.get("hitcount")  is not None else
            p.get("hit_count") if p.get("hit_count") is not None else
            p.get("pkts")      if p.get("pkts")       is not None else
            p.get("bytes")
        )
        if hit is None:
            continue
        try:
            if int(hit) == 0:
                findings.append({
                    "policy_id":   str(p.get("policyid", idx + 1)),
                    "policy_name": _name(p),
                    "seq":         _seq(p, idx),
                    "check":       "unhit",
                    "detail":      "Hit count is 0 — rule has never matched traffic.",
                })
        except (TypeError, ValueError):
            pass
    return findings


def check_no_deny_all(
    policies: list[dict],
    has_implicit_deny: bool = False,
) -> list[dict]:
    """Checks whether the package has a terminal deny-all rule.

    A proper deny-all rule requires: src=any, dst=any, svc=ALL/any, action=deny/block.
    Global policy-block entries (_policy_block) are excluded — they are not regular rules.

    has_implicit_deny — set True when the package settings confirm the device has a
    firmware-level implicit deny (FortiOS always has one; detectable via the
    'package settings' object containing 'fwpolicy-implicit-log').  When True and no
    explicit deny-all rule is found, the finding message notes the implicit deny exists
    but warns that it is not visible in the policy list.
    Returns at most one finding (package-level, not per-rule).
    """
    has_explicit_deny_all = False
    for p in policies:
        if _is_policy_block(p):
            continue
        if _status(p) == "disable":
            continue
        action = _action(p)
        if action not in ("deny", "block", "drop"):
            continue
        if (_is_any(p.get("srcaddr") or p.get("src_addr")) and
                _is_any(p.get("dstaddr") or p.get("dst_addr")) and
                _svc_is_any(p.get("service") or p.get("services"))):
            has_explicit_deny_all = True
            break

    if has_explicit_deny_all:
        return []

    if has_implicit_deny:
        # FortiOS firmware implicit deny exists — not a policy gap, but worth noting
        return [{
            "policy_id":   "—",
            "policy_name": "(package-level)",
            "seq":         0,
            "check":       "no_deny_all",
            "detail":      (
                "No explicit deny-all rule in the policy list. "
                "The FortiOS firmware implicit deny (src=any, dst=any, svc=ALL) "
                "is active but is not visible as a policy object. "
                "Consider adding an explicit deny-all to make intent clear and enable logging."
            ),
        }]

    return [{
        "policy_id":   "—",
        "policy_name": "(package-level)",
        "seq":         0,
        "check":       "no_deny_all",
        "detail":      (
            "No enabled deny-all rule found "
            "(src=any, dst=any, svc=ALL, action=deny). "
            "Traffic not matched by any rule may be implicitly permitted "
            "depending on device configuration."
        ),
    }]


# ── Dispatcher ────────────────────────────────────────────────────────────────

_CHECK_FNS = {
    "unnamed":     check_unnamed,
    "unlogged":    check_unlogged,
    "shadow":      check_shadow,
    "disabled":    check_disabled,
    "expired":     check_expired,
    "unhit":       check_unhit,
    "no_deny_all": check_no_deny_all,
}


def run_checks(
    policies: list[dict],
    checks: list[str],
    pkg_settings: dict | None = None,
) -> list[dict]:
    """Run the requested checks against the policy list.  Returns combined findings.

    pkg_settings — the 'package settings' dict from FMG for this package.
    Used by check_no_deny_all to detect the firmware implicit deny.
    """
    settings = pkg_settings or {}
    # FortiOS always has an implicit deny; detectable by the presence of
    # 'fwpolicy-implicit-log' in package settings (key exists even when value is 0).
    has_implicit_deny = "fwpolicy-implicit-log" in settings

    results = []
    for key in checks:
        fn = _CHECK_FNS.get(key)
        if not fn:
            continue
        if key == "no_deny_all":
            results.extend(check_no_deny_all(policies, has_implicit_deny=has_implicit_deny))
        else:
            results.extend(fn(policies))
    return results
