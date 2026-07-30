# ADOM Access Control Design

**Date:** 2026-07-27
**Project:** 4tAnalyst — FortiManager MCP
**Status:** Approved

## Problem

The FortiManager MCP server currently accepts any ADOM name from any authenticated caller. A single shared bearer token grants full access to all ADOMs on the FortiManager. The goal is to restrict specific engineers to a subset of ADOMs while allowing admins and testers full access.

## Scope

Read-query restriction only. `plan_change` is out of scope for this change (Phase 4 will address it with AD/Entra identity). The enforcement boundary is: any `fortimanager_mcp` tool that accepts an `adom` parameter.

## Approach

Multiple bearer tokens, each mapped to an allowed ADOM set in `credentials.yaml`. The existing single `auth_token` remains as a legacy full-access token. A ContextVar carries the resolved ADOM set from the auth middleware to each tool call. A `_require_adom()` helper at the top of each ADOM-taking tool enforces the boundary. Designed to slot into Phase 4 (AD/Entra) by replacing ContextVar population with group membership lookup — enforcement point unchanged.

---

## Section 1 — `credentials.yaml` Schema

```yaml
server:
  adom_restriction: true      # false = disable filtering entirely, all tokens get ["*"]
  auth_token: "CHANGEME"      # legacy admin token — full access, unchanged

  tokens:
    - token: "tok_abc123..."
      label: "alice"          # human-readable, for logs only
      adoms: ["OT-ADOM", "GAS-ADOM"]

    - token: "tok_def456..."
      label: "bob-admin"
      adoms: ["*"]            # unrestricted

  allowed_hosts: []
```

**Precedence rules:**
1. If `adom_restriction: false` → every token gets `{"*"}`, no per-token lookup performed.
2. If token matches an entry in `tokens` → that entry's `adoms` list governs.
3. If token matches legacy `auth_token` (and not in `tokens`) → `{"*"}`.
4. If token matches neither → 401 (unchanged behavior).

`"*"` in an `adoms` list means unrestricted access to all ADOMs.

---

## Section 2 — Auth Middleware (`fwanalyst_server/auth.py`)

Add a module-level `ContextVar` and a token resolution function:

```python
from contextvars import ContextVar

allowed_adoms_var: ContextVar[set[str]] = ContextVar("allowed_adoms")

def _resolve_allowed_adoms(token: str, creds: dict) -> set[str] | None:
    """Returns allowed ADOM set for a token, or None if unrecognized."""
    server_cfg = creds.get("server", {})

    restriction_enabled = server_cfg.get("adom_restriction", True)

    for entry in server_cfg.get("tokens", []):
        if constant_time_compare(token, entry.get("token", "")):
            if not restriction_enabled:
                return {"*"}
            adoms = entry.get("adoms", [])
            return {"*"} if "*" in adoms else set(adoms)

    if constant_time_compare(token, server_cfg.get("auth_token", "")):
        return {"*"}

    return None
```

The ASGI middleware calls `_resolve_allowed_adoms` after validating the token is non-empty:
- Returns 401 if result is `None` (unrecognized token).
- Calls `allowed_adoms_var.set(resolved_set)` before passing to the next handler.

---

## Section 3 — Enforcement (`fortimanager_mcp/server.py`)

### `_require_adom()` helper

`allowed_adoms_var` must live in a module that neither `fwanalyst_server` nor `fortimanager_mcp` imports transitively — otherwise there is a circular import (`fwanalyst_server` → `fortimanager_mcp` → `fwanalyst_server`). It belongs in a new thin module `fwanalyst_server/context.py` (no imports from either package), which both packages import independently.

```python
# fwanalyst_server/context.py  (new thin module — no other imports)
from contextvars import ContextVar
allowed_adoms_var: ContextVar[set[str]] = ContextVar("allowed_adoms")
```

```python
# fortimanager_mcp/server.py
from fwanalyst_server.context import allowed_adoms_var

def _require_adom(adom: str) -> dict | None:
    """
    Returns error dict if caller cannot access this ADOM, else None.
    Default is {"*"} (full access) when no ContextVar is set — preserves
    behavior in stdio/dev mode where no auth middleware is running.
    """
    allowed = allowed_adoms_var.get({"*"})
    if "*" in allowed or adom in allowed:
        return None
    return {"error": f"ADOM '{adom}' is not in your allowed list."}
```

### Per-tool enforcement

Every tool that accepts an `adom` parameter calls `_require_adom` as its first line:

```python
@mcp.tool()
def get_devices(adom: str) -> list[dict[str, Any]]:
    if err := _require_adom(adom):
        return err
    with _fortimanager_client() as c:
        return _query.list_devices(c, adom)
```

Affected tools (all ADOM-taking tools in `fortimanager_mcp/server.py`):
- `get_devices`
- `search_devices`
- `search_policies`
- `get_address_object`
- `search_address_objects`
- `get_service_object`
- `get_policy`
- `get_interface_map`
- `get_routing_table`
- `list_device_vdoms`

### `get_adoms()` — silent filter (special case)

`get_adoms` has no `adom` argument, so it cannot hard-error. Instead it silently filters the returned list:

```python
@mcp.tool()
def get_adoms() -> list[dict[str, Any]]:
    allowed = allowed_adoms_var.get({"*"})
    with _fortimanager_client() as c:
        adoms = _query.list_adoms(c)
    if "*" in allowed:
        return adoms
    return [a for a in adoms if a["name"] in allowed]
```

---

## Section 4 — Testing

### `tests/test_fwanalyst_auth.py` (additions)

- Token in `tokens` list with restricted set → `allowed_adoms_var` gets the correct restricted set
- Legacy `auth_token` → `allowed_adoms_var` gets `{"*"}`
- `adom_restriction: false` in config → any token gets `{"*"}` regardless of `tokens` list

### `tests/test_fortimanager_adom_guard.py` (new file)

- `_require_adom("OT-ADOM")` with `allowed = {"OT-ADOM"}` → `None` (permitted)
- `_require_adom("IT-ADOM")` with `allowed = {"OT-ADOM"}` → error dict
- `_require_adom("anything")` with `allowed = {"*"}` → `None`
- `get_adoms()` with restricted set → only allowed ADOMs in result
- `get_adoms()` with `{"*"}` → all ADOMs returned
- stdio dev mode (no ContextVar set) → defaults to full access

---

## Phase 4 Migration Path

When AD/Entra identity lands, the `_resolve_allowed_adoms` function is replaced with a function that maps an engineer's AD group membership to an ADOM set. The `ContextVar` injection point in the middleware and all `_require_adom()` call sites remain unchanged. The `tokens` block in `credentials.yaml` becomes unused and can be removed.

---

## Files Changed

| File | Change |
|---|---|
| `credentials.yaml.example` | Add `adom_restriction`, `server.tokens` schema |
| `fwanalyst_server/context.py` | New thin module — `allowed_adoms_var` ContextVar only (no other imports, avoids circular dependency) |
| `fwanalyst_server/auth.py` | Add `_resolve_allowed_adoms`, import `allowed_adoms_var` from `context.py`, ContextVar injection in middleware |
| `fortimanager_mcp/server.py` | Add `_require_adom()` helper; add guard to 10 tools; filter `get_adoms()` |
| `tests/test_fwanalyst_auth.py` | Add 3 new token-resolution test cases |
| `tests/test_fortimanager_adom_guard.py` | New file, 6 test cases |
