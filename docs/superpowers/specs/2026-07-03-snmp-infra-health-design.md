# SNMP-based Infrastructure Health Polling

Date: 2026-07-03

## Problem

The main dashboard's "Infrastructure Health" section (`/api/infrastructure`) currently sources CPU/memory for every `infra_targets.json` entry via FortiManager JSON-RPC calls (`get_performance()` / `get_resource_usage()` in `fmg_client.py`), regardless of device type. This works for FortiManager itself, only partially for FortiAnalyzer, and **not at all for FortiAuthenticator**, which has no equivalent JSON-RPC status/resource API. Those entries silently end up with `cpu=None, mem=None` or fall into the generic `except Exception: status="red"` path. Additionally, CPU/mem is fetched synchronously on every dashboard load, adding per-request latency and load on the target devices.

## Scope

Applies to `infra_targets.json` entries of type `fortimanager` (7.4.x+), `fortianalyzer` (7.4.x+), and `fortiauthenticator`. FortiGate firewall CPU/mem (elsewhere in the app, sourced via the FMG proxy) is out of scope and unaffected.

## Architecture

Replace the live per-request FMG JSON-RPC CPU/mem fetch for these three types with a background SNMP poller feeding an in-memory cache, following the existing `adom_cache.py` pattern (APScheduler-driven, in-memory dict, instant reads).

```
app/infra_health_cache.py          (new)
  - APScheduler job every SNMP_POLL_INTERVAL seconds (default 60)
  - SNMPv3 GET per target -> cpu %, mem %
  - in-memory dict keyed by host: {cpu, mem, snmp_status, last_updated}
  - init_scheduler(app) called from app factory, mirroring adom_cache.py

app/routes/api_routes.py (/api/infrastructure)
  - for type in {fortimanager, fortianalyzer, fortiauthenticator}:
      skip FMG JSON-RPC CPU/mem calls, read from infra_health_cache.get_cached(host)
  - get_system_status() (version/serial/HA) calls unaffected
```

## SNMP protocol details

- **Version:** SNMPv3 only (auth + privacy) — community-string-based v2c is not used, since it's effectively cleartext and this is a security-monitoring product.
- **Library:** `pysnmp` (lextudio-maintained fork), pure Python, no system-level net-snmp dependency. Added via `uv add pysnmp`.
- **OIDs:** Fortinet FortiOS-family devices (FortiGate/FortiManager/FortiAnalyzer) expose CPU/mem under the proprietary `FORTINET-CORE-MIB` (`fnSysCpuUsage` / `fnSysMemUsage`, enterprise OID `1.3.6.1.4.1.12356.101...`). FortiAuthenticator runs a different OS lineage and may require a different vendor MIB or standard `HOST-RESOURCES-MIB` (`hrProcessorLoad`, `hrStorageUsed`/`hrStorageSize`). Exact OIDs per device type/firmware are **not hardcoded from memory in this spec** — they must be confirmed during implementation against Fortinet's official MIB documentation (and ideally verified with `snmpwalk` against real lab devices of each type, if available) before being encoded into a per-type `OID_MAP` in `infra_health_cache.py`.

## Configuration

### New `.env` variables (documented in `CLAUDE.md`)

```
SNMP_ENABLED=true
SNMP_PORT=161
SNMP_TIMEOUT=5
SNMP_RETRIES=1
SNMP_POLL_INTERVAL=60
SNMP_USER=monitor
SNMP_AUTH_PROTOCOL=SHA
SNMP_AUTH_KEY=changeme
SNMP_PRIV_PROTOCOL=AES
SNMP_PRIV_KEY=changeme
```

These act as defaults for any target of the three supported types. If `SNMP_ENABLED=false`, the poller does not start and cards show CPU/mem as not-applicable, same as today's gap.

### `infra_targets.json` / `infra_targets.example.json` — optional per-device overrides

```json
{
  "label": "FAC-01",
  "host": "10.1.1.5",
  "type": "fortiauthenticator",
  "snmp_user": "monitor2",
  "snmp_auth_key": "example-auth-key",
  "snmp_priv_key": "example-priv-key"
}
```

Resolution order mirrors the existing per-device `token` pattern for FMG API auth: per-device `snmp_*` fields → global `.env` `SNMP_*` defaults.

## Error handling

`infra_health_cache.poll_all_targets()` catches per-target failures individually so one unreachable device doesn't block others:

- SNMP timeout → `snmp_status: "timeout"`, `cpu`/`mem`: `None`
- Other SNMP errors (auth failure, wrong OID, etc.) → `snmp_status: "error"`, `cpu`/`mem`: `None`
- Success → `snmp_status: "ok"`, `cpu`/`mem` populated

`/api/infrastructure` and the existing `_health_status(cpu, mem)` three-tier logic (reusing existing `CPU_WARN/CRIT`, `MEM_WARN/CRIT` thresholds) must handle `snmp_status != "ok"` explicitly — render as yellow/gray "SNMP unreachable" rather than crashing on `None` inputs.

## Frontend

`dashboard.js` / `dashboard.html` currently render `.infra-card` without a CPU/mem row at all, even though the API has returned `cpu`/`mem` fields for a while. This design adds that row (reusing the existing green/yellow/red status stripe convention) now that real SNMP-sourced values will be present for all three device types.

## Dependencies

- Add `pysnmp` to `pyproject.toml` via `uv add pysnmp`; `uv.lock` updated accordingly.

## Documentation updates

- `CLAUDE.md`: new subsection describing `infra_health_cache.py`, the `SNMP_*` env block, and per-device override fields, in the style of the existing ADOM cache / summary job sections.
- `infra_targets.example.json`: add example `snmp_user`/`snmp_auth_key`/`snmp_priv_key` fields on one sample entry (placeholder values only).
- No `.env.example` currently exists in the repo per CLAUDE.md's variable documentation convention — new vars are documented in CLAUDE.md's config block instead.

## Testing

- Unit tests for `infra_health_cache.py`: mock `pysnmp` GET calls; verify cache population, timeout handling, error handling, and correct per-type OID selection.
- Unit test for `/api/infrastructure`'s handling of `snmp_status != "ok"` (no crash on `None` cpu/mem, correct status rendering).
- Manual verification: enable `SNMP_ENABLED=true` against a real (or SNMP-simulated) device of each type, confirm the dashboard card shows live CPU/mem values and updates on the poll interval.

## Out of scope

- FortiGate firewall CPU/mem (unaffected, different code path via FMG proxy).
- SNMPv1/v2c support (explicitly rejected in favor of SNMPv3-only).
- Any write/config-push SNMP operations (this project is strictly read-only).
