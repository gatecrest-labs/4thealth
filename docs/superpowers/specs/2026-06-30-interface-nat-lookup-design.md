# Interface Lookup & NAT Lookup — Design Spec

**Date:** 2026-06-30
**Branch:** development
**Tab:** Rule Review (hygiene page)

---

## Overview

Add two new lookup sections to the Rule Review tab, modelled after the existing Object Lookup section. Both allow an engineer to select an ADOM, enter an IP address, and search for matching firewall interfaces or NAT entries across the ADOM's devices/policy objects.

---

## Approach

Option A: mirror the Object Lookup pattern exactly. Each new lookup is an independent section with its own ADOM selector, IP input, Search button, paginated results table, and CSV/JSON/PDF export. No shared state between sections.

---

## 1. Interface Lookup

### Purpose
Given one or more IP addresses, find which firewall interface(s) in an ADOM are assigned that IP.

### UI
- Section label: "Interface Lookup" (inserted between Object Lookup and Hygiene Analysis sections)
- Controls:
  - ADOM selector (`<select id="ilAdom">`)
  - Text input: label "IP Address(es)", placeholder "Enter one or more IPs, comma-separated…" (`<input id="ilQuery">`)
  - Search button (`<button id="ilSearchBtn">`)
  - Indeterminate progress bar + "Searching…" spinner (same as Object Lookup)
- Results table columns: `# | Device | Interface | VDOM | IP / Mask | Type | Status`
  - Status rendered as a color-coded badge: `up` = green, `down` = red, other = grey
- "Not found" message when `total === 0`
- Close button, filter input, page-size selector (10/25/50/100), pagination
- Export buttons: CSV, JSON, PDF
- Warning banner above results if any devices were unreachable: "X device(s) unreachable and skipped"
- JS state variable prefix: `il` (e.g., `ilAllResults`, `ilFiltered`, `ilPage`, `ilPageSize`, `ilFilter`, `ilMeta`)

### API Endpoint
```
POST /api/hygiene/adoms/<adom>/interfaces/lookup
```

**Request body:**
```json
{ "ips": ["10.1.2.3", "10.1.2.4"] }
```

**Response:**
```json
{
  "results": [
    {
      "device": "FW-01",
      "interface": "port1",
      "vdom": "root",
      "ip": "10.1.2.1/24",
      "type": "physical",
      "status": "up"
    }
  ],
  "total": 1,
  "searched_ips": ["10.1.2.3"],
  "skipped_devices": ["FW-03"]
}
```

### Backend Logic
1. Validate input: split on comma, strip whitespace, validate each is a valid IPv4 address. Return 400 with message if any are invalid.
2. Fetch device list for the ADOM via `fmg_client.get_devices(adom)`.
3. For each device, call `fmg_client.get_device_interfaces_all_vdoms(adom, device_name)`.
   - On exception/empty response, add device to `skipped_devices` and continue.
4. For each interface, extract the IP portion (FortiGate format: `"10.1.2.1 255.255.255.0"` — split on space, take index 0). Compare exact string match against each searched IP.
5. On match, record: device name, interface name, vdom, full IP/mask (reformatted as CIDR where possible), interface type, status.
6. Return combined results sorted by device then interface name.

### FMG Client
No new methods required. Uses existing `get_devices(adom)` and `get_device_interfaces_all_vdoms(adom, device_name)`.

---

## 2. NAT Lookup

### Purpose
Given an IP address, find matching VIP (Virtual IP / inbound NAT) and IP Pool (outbound NAT/PAT) objects in an ADOM. Searches both external and internal/mapped IPs.

### UI
- Section label: "NAT Lookup" (inserted after Interface Lookup, before Hygiene Analysis)
- Controls:
  - ADOM selector (`<select id="nlAdom">`)
  - Text input: label "IP Address", placeholder "Enter an IP to search VIPs and IP Pools…" (`<input id="nlQuery">`)
  - Search button (`<button id="nlSearchBtn">`)
  - Indeterminate progress bar + "Searching…" spinner
- Results table columns: `# | Type | Name | External IP | Mapped / Pool IP | Interface | Protocol / Port | Notes`
  - VIP rows: `VIP` badge | name | extip | mappedip | ext_intf | `tcp:443→8443` if port-forward, else `—` | `—`
  - IP Pool rows: `IP Pool` badge | name | startip–endip (shown as range in External IP col) | `—` | `—` | pool type (overload/one-to-one/fixed-port-range) | comments
- "No NAT entries found for `<ip>`" message when `total === 0`
- Close button, filter input, page-size selector, pagination
- Export buttons: CSV, JSON, PDF
- JS state variable prefix: `nl` (e.g., `nlAllResults`, `nlFiltered`, `nlPage`, `nlPageSize`, `nlFilter`, `nlMeta`)

### API Endpoint
```
POST /api/hygiene/adoms/<adom>/nat/lookup
```

**Request body:**
```json
{ "ip": "203.0.113.10" }
```

**Response:**
```json
{
  "results": [
    {
      "nat_type": "VIP",
      "name": "vip_web_server",
      "ext_ip": "203.0.113.10",
      "ext_intf": "wan1",
      "mapped_ip": "192.168.1.10-192.168.1.10",
      "port_forward": true,
      "protocol": "tcp",
      "ext_port": "443",
      "mapped_port": "8443",
      "comments": ""
    },
    {
      "nat_type": "IP Pool",
      "name": "outbound_pool",
      "start_ip": "203.0.113.1",
      "end_ip": "203.0.113.20",
      "pool_type": "overload",
      "comments": "Corporate outbound PAT"
    }
  ],
  "total": 2,
  "searched_ip": "203.0.113.10"
}
```

### Backend Logic
1. Validate input: single IPv4 address. Return 400 if invalid.
2. Fetch VIP objects via `fmg_client.get_vip_objects(adom)` (new method).
3. For each VIP, match if:
   - `extip` == searched IP, **or**
   - searched IP falls within any range in `mappedip` list (format: `{"range": "192.168.1.10-192.168.1.20"}` — split on `-`, check `start <= ip <= end`).
4. Fetch IP Pool objects via `fmg_client.get_ippool_objects(adom)` (new method).
5. For each pool, match if searched IP falls between `startip` and `endip` (inclusive).
6. Combine VIP matches + pool matches into single results list. VIPs first, then pools.
7. Return results.

### FMG Client — New Methods

**`get_vip_objects(adom: str) -> list`**
```python
# Queries: /pm/config/adom/{adom}/obj/firewall/vip
# Same pagination pattern as get_address_objects()
# Also queries /pm/config/global/obj/firewall/vip for global objects
```

**`get_ippool_objects(adom: str) -> list`**
```python
# Queries: /pm/config/adom/{adom}/obj/firewall/ippool
# Same pagination pattern as get_address_objects()
# Also queries /pm/config/global/obj/firewall/ippool
```

Both methods use `_paginated_get()` (the existing helper at line ~656 in fmg_client.py) and merge ADOM-specific + global results, deduplicating by name.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `app/fmg_client.py` | Add `get_vip_objects()` and `get_ippool_objects()` |
| `app/routes/hygiene_routes.py` | Add `POST /api/hygiene/adoms/<adom>/interfaces/lookup` and `POST /api/hygiene/adoms/<adom>/nat/lookup` endpoints |
| `app/templates/hygiene.html` | Add Interface Lookup section and NAT Lookup section HTML |
| `app/static/js/hygiene.js` | Add Interface Lookup and NAT Lookup JS state, event handlers, render functions, and export functions |

---

## 4. Out of Scope

- Per-policy NAT (inline SNAT/DNAT within firewall policies) — this is separate from VIP/pool objects and would require per-package policy scanning. Not included.
- IPv6 address matching.
- Interface lookup by interface name (name search already covered by Object Lookup for address objects; interface name search is a separate future feature).
