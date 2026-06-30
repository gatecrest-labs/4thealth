# Interface Lookup & NAT Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Interface Lookup and NAT Lookup sections to the Rule Review tab (hygiene page), each following the existing Object Lookup pattern.

**Architecture:** Two new FMG client methods (`get_vip_objects`, `get_ippool_objects`) added to `fmg_client.py`. Two new POST endpoints added to `hygiene_routes.py`. Two new HTML sections added to `hygiene.html`. Two new sets of JS state/render/export functions added to `hygiene.js`. All four changes follow the existing Object Lookup pattern exactly.

**Tech Stack:** Python/Flask backend, Jinja2 templates, vanilla JS frontend, FortiManager JSON-RPC API.

## Global Constraints

- All changes on the `development` branch
- No new dependencies — use only existing libraries (`ipaddress` stdlib for IP validation/range checks)
- Follow existing Object Lookup pattern exactly: same HTML structure, same JS naming conventions (`<prefix>AllResults`, `<prefix>Filtered`, `<prefix>Page`, etc.), same export format
- IP validation must use Python's `ipaddress.ip_address()` — reject anything that raises `ValueError`
- All new FMG client methods must use `_get_paged()` (the existing paginator at `fmg_client.py:655`) and query both ADOM-specific and global paths
- Tab access guard: all new endpoints decorated with `@tab_required("rule_hygiene")` and `check_adom_access(adom)`
- Do not reformat or restructure any existing code outside the insertion points

---

### Task 1: Add `get_vip_objects` and `get_ippool_objects` to FMG client

**Files:**
- Modify: `app/fmg_client.py` — append two methods after `get_service_groups` (currently ends at line ~742)

**Interfaces:**
- Produces:
  - `get_vip_objects(adom: str) -> list` — returns list of VIP dicts from FortiManager
  - `get_ippool_objects(adom: str) -> list` — returns list of IP pool dicts from FortiManager
- These are consumed by Task 2 (the route endpoints)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fmg_client_nat.py`:

```python
"""Tests for get_vip_objects and get_ippool_objects FMG client methods."""
import pytest
from unittest.mock import patch, MagicMock
from app.fmg_client import FMGClient


def _make_client():
    c = FMGClient.__new__(FMGClient)
    c.base_url = "https://fmg.test/jsonrpc"
    c.token = "tok"
    c.session = None
    c.verify_ssl = False
    c._req_id = 0
    return c


def test_get_vip_objects_returns_merged_list():
    client = _make_client()
    adom_vips = [{"name": "vip1", "extip": "1.2.3.4", "mappedip": [{"range": "10.0.0.1-10.0.0.1"}]}]
    global_vips = [{"name": "vip_global", "extip": "5.6.7.8", "mappedip": [{"range": "10.0.0.2-10.0.0.2"}]}]

    call_count = {"n": 0}
    def fake_paged(url):
        call_count["n"] += 1
        if "global" in url:
            return global_vips
        return adom_vips

    with patch.object(client, "_get_paged", side_effect=fake_paged):
        result = client.get_vip_objects("TestADOM")

    assert len(result) == 2
    assert call_count["n"] == 2
    names = {r["name"] for r in result}
    assert "vip1" in names
    assert "vip_global" in names


def test_get_vip_objects_graceful_on_error():
    client = _make_client()

    def fake_paged(url):
        raise Exception("FMG unreachable")

    with patch.object(client, "_get_paged", side_effect=fake_paged):
        result = client.get_vip_objects("TestADOM")

    assert result == []


def test_get_ippool_objects_returns_merged_list():
    client = _make_client()
    adom_pools = [{"name": "pool1", "startip": "1.2.3.1", "endip": "1.2.3.10"}]
    global_pools = [{"name": "pool_global", "startip": "5.6.7.1", "endip": "5.6.7.20"}]

    def fake_paged(url):
        if "global" in url:
            return global_pools
        return adom_pools

    with patch.object(client, "_get_paged", side_effect=fake_paged):
        result = client.get_ippool_objects("TestADOM")

    assert len(result) == 2
    names = {r["name"] for r in result}
    assert "pool1" in names
    assert "pool_global" in names


def test_get_ippool_objects_graceful_on_error():
    client = _make_client()

    def fake_paged(url):
        raise Exception("FMG unreachable")

    with patch.object(client, "_get_paged", side_effect=fake_paged):
        result = client.get_ippool_objects("TestADOM")

    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/repo && python -m pytest tests/test_fmg_client_nat.py -v
```

Expected: 4 failures — `AttributeError: type object 'FMGClient' has no attribute 'get_vip_objects'`

- [ ] **Step 3: Add the two methods to `fmg_client.py`**

In `app/fmg_client.py`, after line 742 (the end of `get_service_groups`), insert:

```python
    def get_vip_objects(self, adom: str) -> list:
        """Return all firewall VIP objects in an ADOM plus the global database."""
        results: list = []
        for url in (
            f"/pm/config/adom/{adom}/obj/firewall/vip",
            "/pm/config/global/obj/firewall/vip",
        ):
            try:
                results.extend(self._get_paged(url))
            except Exception:
                pass
        return results

    def get_ippool_objects(self, adom: str) -> list:
        """Return all firewall IP pool objects in an ADOM plus the global database."""
        results: list = []
        for url in (
            f"/pm/config/adom/{adom}/obj/firewall/ippool",
            "/pm/config/global/obj/firewall/ippool",
        ):
            try:
                results.extend(self._get_paged(url))
            except Exception:
                pass
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_fmg_client_nat.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/fmg_client.py tests/test_fmg_client_nat.py
git commit -m "feat: add get_vip_objects and get_ippool_objects to FMG client"
```

---

### Task 2: Add Interface Lookup and NAT Lookup API endpoints

**Files:**
- Modify: `app/routes/hygiene_routes.py` — append two new endpoints after the existing object lookup endpoint (currently ends at line 541)

**Interfaces:**
- Consumes: `client.get_devices(adom)`, `client.get_device_interfaces_all_vdoms(adom, device_name)` (both already in `fmg_client.py`), `client.get_vip_objects(adom)`, `client.get_ippool_objects(adom)` (from Task 1)
- Produces:
  - `POST /api/hygiene/adoms/<adom>/interfaces/lookup` → `{ results, total, searched_ips, skipped_devices }`
  - `POST /api/hygiene/adoms/<adom>/nat/lookup` → `{ results, total, searched_ip }`
- Consumed by Task 4 (frontend JS)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hygiene_routes_lookup.py`:

```python
"""Tests for interface and NAT lookup endpoints."""
import json
import pytest
from unittest.mock import patch, MagicMock
from app import create_app


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False})
    return app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["username"] = "admin"
            sess["role"] = "admin"
        yield c


# ── Interface Lookup ──────────────────────────────────────────────────────────

def test_interface_lookup_returns_match(client):
    devices = [{"name": "FW-01"}]
    interfaces = [
        {"name": "port1", "ip": "10.1.2.3 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
        {"name": "port2", "ip": "192.168.1.1 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.return_value = interfaces
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/interfaces/lookup",
            json={"ips": ["10.1.2.3"]},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["interface"] == "port1"
    assert data["results"][0]["device"] == "FW-01"
    assert data["skipped_devices"] == []


def test_interface_lookup_not_found(client):
    devices = [{"name": "FW-01"}]
    interfaces = [
        {"name": "port1", "ip": "192.168.1.1 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.return_value = interfaces
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/interfaces/lookup",
            json={"ips": ["10.1.2.3"]},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 0
    assert data["results"] == []


def test_interface_lookup_skips_unreachable_device(client):
    devices = [{"name": "FW-01"}, {"name": "FW-02"}]

    def fake_ifaces(adom, device):
        if device == "FW-02":
            raise Exception("unreachable")
        return [{"name": "port1", "ip": "10.1.2.3 255.255.255.0", "vdom": "root", "type": "physical", "status": "up"}]

    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_devices.return_value = devices
        inst.get_device_interfaces_all_vdoms.side_effect = fake_ifaces
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/interfaces/lookup",
            json={"ips": ["10.1.2.3"]},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "FW-02" in data["skipped_devices"]


def test_interface_lookup_invalid_ip(client):
    resp = client.post(
        "/api/hygiene/adoms/TestADOM/interfaces/lookup",
        json={"ips": ["not-an-ip"]},
    )
    assert resp.status_code == 400
    assert "invalid" in resp.get_json()["error"].lower()


def test_interface_lookup_missing_ips(client):
    resp = client.post(
        "/api/hygiene/adoms/TestADOM/interfaces/lookup",
        json={},
    )
    assert resp.status_code == 400


# ── NAT Lookup ────────────────────────────────────────────────────────────────

def test_nat_lookup_matches_vip_extip(client):
    vips = [
        {
            "name": "vip_web",
            "extip": "203.0.113.10",
            "extintf": "wan1",
            "mappedip": [{"range": "10.0.0.1-10.0.0.1"}],
            "portforward": "disable",
            "protocol": "",
            "extport": "",
            "mappedport": "",
            "comment": "",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = vips
        inst.get_ippool_objects.return_value = []
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/nat/lookup",
            json={"ip": "203.0.113.10"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["nat_type"] == "VIP"
    assert data["results"][0]["name"] == "vip_web"


def test_nat_lookup_matches_vip_mapped_ip(client):
    vips = [
        {
            "name": "vip_web",
            "extip": "203.0.113.10",
            "extintf": "wan1",
            "mappedip": [{"range": "10.0.0.5-10.0.0.10"}],
            "portforward": "disable",
            "protocol": "",
            "extport": "",
            "mappedport": "",
            "comment": "",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = vips
        inst.get_ippool_objects.return_value = []
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/nat/lookup",
            json={"ip": "10.0.0.7"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["name"] == "vip_web"


def test_nat_lookup_matches_ippool(client):
    pools = [
        {
            "name": "outbound_pool",
            "startip": "203.0.113.1",
            "endip": "203.0.113.20",
            "type": "overload",
            "comments": "Corp PAT",
        }
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = []
        inst.get_ippool_objects.return_value = pools
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/nat/lookup",
            json={"ip": "203.0.113.10"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["results"][0]["nat_type"] == "IP Pool"
    assert data["results"][0]["name"] == "outbound_pool"


def test_nat_lookup_not_found(client):
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_vip_objects.return_value = []
        inst.get_ippool_objects.return_value = []
        resp = client.post(
            "/api/hygiene/adoms/TestADOM/nat/lookup",
            json={"ip": "1.2.3.4"},
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 0


def test_nat_lookup_invalid_ip(client):
    resp = client.post(
        "/api/hygiene/adoms/TestADOM/nat/lookup",
        json={"ip": "not-an-ip"},
    )
    assert resp.status_code == 400


def test_nat_lookup_missing_ip(client):
    resp = client.post(
        "/api/hygiene/adoms/TestADOM/nat/lookup",
        json={},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_hygiene_routes_lookup.py -v
```

Expected: failures — `404 NOT FOUND` for the new endpoints (they don't exist yet)

- [ ] **Step 3: Add the `import ipaddress` line and two helper functions at the top of `hygiene_routes.py`**

At the top of `app/routes/hygiene_routes.py`, find the existing imports block and add `import ipaddress` if it isn't already there:

```python
import ipaddress
```

Then add these two helpers anywhere before the new endpoints (e.g., after the existing `_addr_subnet` helper):

```python
def _ip_in_range(ip_str: str, start_str: str, end_str: str) -> bool:
    """Return True if ip_str falls between start_str and end_str (inclusive)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        start = ipaddress.ip_address(start_str)
        end = ipaddress.ip_address(end_str)
        return start <= ip <= end
    except ValueError:
        return False


def _cidr_from_mask(ip_mask: str) -> str:
    """Convert 'x.x.x.x y.y.y.y' to 'x.x.x.x/prefix' for display. Returns original on failure."""
    parts = ip_mask.strip().split()
    if len(parts) == 2:
        try:
            iface = ipaddress.IPv4Interface(f"{parts[0]}/{parts[1]}")
            return str(iface)
        except ValueError:
            pass
    return ip_mask
```

- [ ] **Step 4: Add the Interface Lookup endpoint to `hygiene_routes.py`**

Append after line 541 (after `return jsonify({"objects": results, "total": len(results)})`):

```python
# ── API: interface lookup ─────────────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/interfaces/lookup", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_interface_lookup(adom: str):
    """Search firewall interfaces across all devices in an ADOM by IP address.

    Body: { "ips": ["10.1.2.3", "10.1.2.4"] }
    Returns: { results, total, searched_ips, skipped_devices }
    """
    if err := check_adom_access(adom):
        return err

    data = request.get_json(silent=True) or {}
    raw_ips = data.get("ips") or []
    if not raw_ips:
        return jsonify({"error": "ips is required"}), 400

    # Validate each IP
    searched_ips = []
    for raw in raw_ips:
        s = str(raw).strip()
        try:
            ipaddress.ip_address(s)
            searched_ips.append(s)
        except ValueError:
            return jsonify({"error": f"Invalid IP address: {s!r}"}), 400

    if not searched_ips:
        return jsonify({"error": "ips is required"}), 400

    searched_set = set(searched_ips)
    results = []
    skipped_devices = []

    try:
        with make_client() as client:
            devices = client.get_devices(adom)
            for device in devices:
                device_name = device.get("name", "") if isinstance(device, dict) else str(device)
                if not device_name:
                    continue
                try:
                    interfaces = client.get_device_interfaces_all_vdoms(adom, device_name)
                except Exception:
                    skipped_devices.append(device_name)
                    continue

                for iface in interfaces:
                    if not isinstance(iface, dict):
                        continue
                    raw_ip = iface.get("ip", "")
                    if not raw_ip:
                        continue
                    # FortiGate format: "10.1.2.3 255.255.255.0" — extract IP part
                    ip_part = raw_ip.split()[0] if " " in raw_ip else raw_ip
                    if ip_part in searched_set:
                        results.append({
                            "device": device_name,
                            "interface": iface.get("name", ""),
                            "vdom": iface.get("vdom", "root"),
                            "ip": _cidr_from_mask(raw_ip),
                            "type": iface.get("type", ""),
                            "status": iface.get("status", ""),
                        })
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    results.sort(key=lambda r: (r["device"].lower(), r["interface"].lower()))
    return jsonify({
        "results": results,
        "total": len(results),
        "searched_ips": searched_ips,
        "skipped_devices": skipped_devices,
    })
```

- [ ] **Step 5: Add the NAT Lookup endpoint to `hygiene_routes.py`**

Append immediately after the interface lookup endpoint:

```python
# ── API: NAT lookup ───────────────────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/nat/lookup", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_nat_lookup(adom: str):
    """Search VIP and IP pool objects in an ADOM for a given IP address.

    Matches: VIP extip, VIP mappedip ranges, IP pool startip-endip ranges.
    Body: { "ip": "203.0.113.10" }
    Returns: { results, total, searched_ip }
    """
    if err := check_adom_access(adom):
        return err

    data = request.get_json(silent=True) or {}
    raw_ip = (data.get("ip") or "").strip()
    if not raw_ip:
        return jsonify({"error": "ip is required"}), 400
    try:
        searched_ip = str(ipaddress.ip_address(raw_ip))
    except ValueError:
        return jsonify({"error": f"Invalid IP address: {raw_ip!r}"}), 400

    results = []

    try:
        with make_client() as client:
            vips = client.get_vip_objects(adom)
            pools = client.get_ippool_objects(adom)
    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    for vip in vips:
        if not isinstance(vip, dict):
            continue
        name = vip.get("name", "")
        if not name:
            continue
        ext_ip = vip.get("extip", "")
        mapped_ranges = vip.get("mappedip", []) or []

        matched = False
        # Match on external IP (exact)
        if ext_ip == searched_ip:
            matched = True
        # Match on any mapped IP range
        if not matched:
            for entry in mapped_ranges:
                if not isinstance(entry, dict):
                    continue
                rng = entry.get("range", "")
                if "-" in rng:
                    start, _, end = rng.partition("-")
                    if _ip_in_range(searched_ip, start.strip(), end.strip()):
                        matched = True
                        break

        if not matched:
            continue

        # Build human-readable mapped IP string
        mapped_display = "; ".join(
            e.get("range", "") for e in mapped_ranges if isinstance(e, dict) and e.get("range")
        ) or "—"

        port_forward = vip.get("portforward", "disable") == "enable"
        results.append({
            "nat_type": "VIP",
            "name": name,
            "ext_ip": ext_ip,
            "ext_intf": vip.get("extintf", ""),
            "mapped_ip": mapped_display,
            "port_forward": port_forward,
            "protocol": vip.get("protocol", "") if port_forward else "",
            "ext_port": vip.get("extport", "") if port_forward else "",
            "mapped_port": vip.get("mappedport", "") if port_forward else "",
            "comments": vip.get("comment", "") or vip.get("comments", ""),
        })

    for pool in pools:
        if not isinstance(pool, dict):
            continue
        name = pool.get("name", "")
        start_ip = pool.get("startip", "")
        end_ip = pool.get("endip", "")
        if not name or not start_ip or not end_ip:
            continue
        if not _ip_in_range(searched_ip, start_ip, end_ip):
            continue
        results.append({
            "nat_type": "IP Pool",
            "name": name,
            "start_ip": start_ip,
            "end_ip": end_ip,
            "pool_type": pool.get("type", ""),
            "comments": pool.get("comments", "") or pool.get("comment", ""),
        })

    return jsonify({
        "results": results,
        "total": len(results),
        "searched_ip": searched_ip,
    })
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_hygiene_routes_lookup.py -v
```

Expected: all tests PASSED

- [ ] **Step 7: Commit**

```bash
git add app/routes/hygiene_routes.py tests/test_hygiene_routes_lookup.py
git commit -m "feat: add interface and NAT lookup API endpoints"
```

---

### Task 3: Add Interface Lookup and NAT Lookup HTML sections

**Files:**
- Modify: `app/templates/hygiene.html` — insert two new sections between line 179 (`</div>` after `olError`) and line 181 (`<!-- Section 4: Hygiene Analysis -->`)

**Interfaces:**
- Produces: HTML elements with IDs consumed by Task 4 JS event wiring
- Interface Lookup IDs: `ilAdom`, `ilQuery`, `ilSearchBtn`, `ilRunning`, `ilProgressWrap`, `ilResults`, `ilCloseBtn`, `ilSummary`, `ilExportCsv`, `ilExportJson`, `ilExportPdf`, `ilFilter`, `ilPageSize`, `ilCount`, `ilTable`, `ilTbody`, `ilPagination`, `ilError`, `ilSkippedWarn`
- NAT Lookup IDs: `nlAdom`, `nlQuery`, `nlSearchBtn`, `nlRunning`, `nlProgressWrap`, `nlResults`, `nlCloseBtn`, `nlSummary`, `nlExportCsv`, `nlExportJson`, `nlExportPdf`, `nlFilter`, `nlPageSize`, `nlCount`, `nlTable`, `nlTbody`, `nlPagination`, `nlError`

- [ ] **Step 1: Insert Interface Lookup HTML**

In `app/templates/hygiene.html`, after line 179 (`<div id="olError" class="alert alert-danger" style="display:none"></div>`), insert:

```html

<!-- ── Section 3: Interface Lookup ──────────────────────────────────────────── -->
<div class="rr-section-label" style="margin-top:2rem">Interface Lookup</div>
<div class="hygiene-selectors">
  <div class="hygiene-selector-row">
    <label for="ilAdom">ADOM</label>
    <select id="ilAdom" class="form-select">
      <option value="">— select ADOM —</option>
    </select>

    <label for="ilQuery" style="white-space:nowrap">IP Address(es)</label>
    <input type="text" id="ilQuery" class="form-control" placeholder="Enter one or more IPs, comma-separated…" style="max-width:360px" disabled />
    <button class="btn btn-primary" id="ilSearchBtn" disabled>Search</button>
    <span id="ilRunning" class="text-muted" style="display:none;font-style:italic">Searching…</span>
  </div>

  <div class="pv-progress-wrap" id="ilProgressWrap">
    <div class="pv-progress-track"><div class="pv-progress-bar"></div></div>
  </div>
</div>

<!-- Interface Lookup Results -->
<div id="ilResults" style="display:none;margin-top:1rem">
  <div id="ilSkippedWarn" class="alert alert-warning" style="display:none;margin-bottom:.5rem"></div>
  <div class="results-close-row">
    <button class="btn btn-sm btn-ghost" id="ilCloseBtn" title="Close interface lookup">&#10005; Close</button>
  </div>
  <div class="obj-lookup-result-header">
    <span id="ilSummary" class="obj-lookup-summary"></span>
    <div class="hygiene-export-row">
      <button class="btn btn-sm" id="ilExportCsv">&#8659; CSV</button>
      <button class="btn btn-sm" id="ilExportJson">&#8659; JSON</button>
      <button class="btn btn-sm" id="ilExportPdf">&#8659; PDF</button>
    </div>
  </div>

  <div class="route-controls" style="margin:.5rem 0 .5rem;flex-wrap:wrap;gap:.5rem">
    <input type="text" id="ilFilter" class="form-control" placeholder="Filter results…" style="max-width:320px" />
    <select id="ilPageSize" class="form-select-sm">
      <option value="10">10</option>
      <option value="25" selected>25</option>
      <option value="50">50</option>
      <option value="100">100</option>
    </select>
    <span class="text-muted" style="font-size:.8rem">per page</span>
  </div>

  <div class="table-wrapper">
    <div class="table-controls">
      <span id="ilCount"></span>
    </div>
    <table class="data-table" id="ilTable">
      <thead>
        <tr>
          <th style="width:3.5rem">#</th>
          <th>Device</th>
          <th>Interface</th>
          <th style="width:7rem">VDOM</th>
          <th>IP / Mask</th>
          <th style="width:7rem">Type</th>
          <th style="width:5rem">Status</th>
        </tr>
      </thead>
      <tbody id="ilTbody"></tbody>
    </table>
    <div class="pagination" id="ilPagination"></div>
  </div>
</div>

<div id="ilError" class="alert alert-danger" style="display:none"></div>
```

- [ ] **Step 2: Insert NAT Lookup HTML**

In `app/templates/hygiene.html`, immediately after the `ilError` div just inserted (before the `<!-- Section 4: Hygiene Analysis -->` comment), insert:

```html

<!-- ── Section 4: NAT Lookup ─────────────────────────────────────────────────── -->
<div class="rr-section-label" style="margin-top:2rem">NAT Lookup</div>
<div class="hygiene-selectors">
  <div class="hygiene-selector-row">
    <label for="nlAdom">ADOM</label>
    <select id="nlAdom" class="form-select">
      <option value="">— select ADOM —</option>
    </select>

    <label for="nlQuery" style="white-space:nowrap">IP Address</label>
    <input type="text" id="nlQuery" class="form-control" placeholder="Enter an IP to search VIPs and IP Pools…" style="max-width:360px" disabled />
    <button class="btn btn-primary" id="nlSearchBtn" disabled>Search</button>
    <span id="nlRunning" class="text-muted" style="display:none;font-style:italic">Searching…</span>
  </div>

  <div class="pv-progress-wrap" id="nlProgressWrap">
    <div class="pv-progress-track"><div class="pv-progress-bar"></div></div>
  </div>
</div>

<!-- NAT Lookup Results -->
<div id="nlResults" style="display:none;margin-top:1rem">
  <div class="results-close-row">
    <button class="btn btn-sm btn-ghost" id="nlCloseBtn" title="Close NAT lookup">&#10005; Close</button>
  </div>
  <div class="obj-lookup-result-header">
    <span id="nlSummary" class="obj-lookup-summary"></span>
    <div class="hygiene-export-row">
      <button class="btn btn-sm" id="nlExportCsv">&#8659; CSV</button>
      <button class="btn btn-sm" id="nlExportJson">&#8659; JSON</button>
      <button class="btn btn-sm" id="nlExportPdf">&#8659; PDF</button>
    </div>
  </div>

  <div class="route-controls" style="margin:.5rem 0 .5rem;flex-wrap:wrap;gap:.5rem">
    <input type="text" id="nlFilter" class="form-control" placeholder="Filter results…" style="max-width:320px" />
    <select id="nlPageSize" class="form-select-sm">
      <option value="10">10</option>
      <option value="25" selected>25</option>
      <option value="50">50</option>
      <option value="100">100</option>
    </select>
    <span class="text-muted" style="font-size:.8rem">per page</span>
  </div>

  <div class="table-wrapper">
    <div class="table-controls">
      <span id="nlCount"></span>
    </div>
    <table class="data-table" id="nlTable">
      <thead>
        <tr>
          <th style="width:3.5rem">#</th>
          <th style="width:6rem">Type</th>
          <th>Name</th>
          <th>External IP</th>
          <th>Mapped / Pool IP</th>
          <th style="width:6rem">Interface</th>
          <th>Protocol / Port</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody id="nlTbody"></tbody>
    </table>
    <div class="pagination" id="nlPagination"></div>
  </div>
</div>

<div id="nlError" class="alert alert-danger" style="display:none"></div>
```

Also update the existing Hygiene Analysis comment from `Section 4` to `Section 5` for consistency:

Find:
```html
<!-- ── Section 4: Hygiene Analysis ──────────────────────────────────────────── -->
```
Replace with:
```html
<!-- ── Section 5: Hygiene Analysis ──────────────────────────────────────────── -->
```

- [ ] **Step 3: Verify the HTML renders without errors**

```bash
python -c "from app import create_app; app = create_app(); print('OK')"
```

Expected: `OK` (no Jinja2 template errors)

- [ ] **Step 4: Commit**

```bash
git add app/templates/hygiene.html
git commit -m "feat: add Interface Lookup and NAT Lookup HTML sections"
```

---

### Task 4: Add Interface Lookup and NAT Lookup JavaScript

**Files:**
- Modify: `app/static/js/hygiene.js`
  - State variables: insert after the Object Lookup state block (after line 34)
  - Functions: append before the `debounce` helper (currently around line 1061)
  - Event wiring: append before the final `loadAdoms()` call (currently line 1421)

**Interfaces:**
- Consumes: API endpoints from Task 2, HTML element IDs from Task 3
- Produces: fully wired Interface Lookup and NAT Lookup sections (search, filter, paginate, export)

- [ ] **Step 1: Add state variables**

In `app/static/js/hygiene.js`, after line 34 (`let olMeta = null; // { adom, query }`), insert:

```javascript
/* ── Interface Lookup state ─────────────────────────────────────────────────── */
let ilAllResults  = [];
let ilFiltered    = [];
let ilPage        = 1;
let ilPageSize    = 25;
let ilFilter      = '';
let ilMeta        = null; // { adom, ips }

/* ── NAT Lookup state ───────────────────────────────────────────────────────── */
let nlAllResults  = [];
let nlFiltered    = [];
let nlPage        = 1;
let nlPageSize    = 25;
let nlFilter      = '';
let nlMeta        = null; // { adom, ip }
```

- [ ] **Step 2: Add Interface Lookup functions**

In `app/static/js/hygiene.js`, just before the `/* ── Debounce helper ── */` comment (currently around line 1061), insert:

```javascript
/* ═══════════════════════════════════════════════════════════════════════════════
   INTERFACE LOOKUP
   ═══════════════════════════════════════════════════════════════════════════════ */

async function runInterfaceLookup() {
  const adom  = document.getElementById('ilAdom').value;
  const query = document.getElementById('ilQuery').value.trim();
  if (!adom || !query) return;

  const ips = query.split(',').map(s => s.trim()).filter(Boolean);

  document.getElementById('ilError').style.display       = 'none';
  document.getElementById('ilResults').style.display     = 'none';
  document.getElementById('ilSkippedWarn').style.display = 'none';
  document.getElementById('ilSearchBtn').disabled        = true;
  document.getElementById('ilRunning').style.display     = '';
  document.getElementById('ilProgressWrap').style.display = 'block';

  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/interfaces/lookup`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ ips }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      document.getElementById('ilError').textContent  = data.error || 'Lookup failed.';
      document.getElementById('ilError').style.display = '';
      return;
    }
    ilAllResults = data.results || [];
    ilMeta       = { adom, ips: data.searched_ips || ips };
    ilPage       = 1;
    ilFilter     = '';
    document.getElementById('ilFilter').value = '';

    const skipped = data.skipped_devices || [];
    if (skipped.length) {
      const warn = document.getElementById('ilSkippedWarn');
      warn.textContent = `${skipped.length} device${skipped.length !== 1 ? 's' : ''} unreachable and skipped: ${skipped.join(', ')}`;
      warn.style.display = '';
    }

    applyIlFilter();
    renderIlTable();
    document.getElementById('ilResults').style.display = '';
  } catch (err) {
    document.getElementById('ilError').textContent  = err.message;
    document.getElementById('ilError').style.display = '';
  } finally {
    document.getElementById('ilSearchBtn').disabled     = false;
    document.getElementById('ilRunning').style.display  = 'none';
    document.getElementById('ilProgressWrap').style.display = 'none';
  }
}

function applyIlFilter() {
  if (!ilFilter) { ilFiltered = ilAllResults; return; }
  const q = ilFilter.toLowerCase();
  ilFiltered = ilAllResults.filter(r =>
    (r.device     || '').toLowerCase().includes(q) ||
    (r.interface  || '').toLowerCase().includes(q) ||
    (r.vdom       || '').toLowerCase().includes(q) ||
    (r.ip         || '').toLowerCase().includes(q) ||
    (r.type       || '').toLowerCase().includes(q) ||
    (r.status     || '').toLowerCase().includes(q)
  );
}

function renderIlTable() {
  const rows  = ilFiltered;
  const total = Math.ceil(rows.length / ilPageSize) || 1;
  ilPage      = Math.min(ilPage, total);
  const slice = rows.slice((ilPage - 1) * ilPageSize, ilPage * ilPageSize);
  const meta  = ilMeta || {};

  const ipsLabel = (meta.ips || []).join(', ');
  const shown = rows.length === ilAllResults.length
    ? `${ilAllResults.length} result${ilAllResults.length !== 1 ? 's' : ''}`
    : `${rows.length} of ${ilAllResults.length} result${ilAllResults.length !== 1 ? 's' : ''}`;
  document.getElementById('ilSummary').textContent =
    ilAllResults.length === 0
      ? `No interfaces found for ${ipsLabel} in ${meta.adom || ''}`
      : `${shown} for ${ipsLabel} in ${meta.adom || ''}`;
  document.getElementById('ilCount').textContent =
    `${shown} — page ${ilPage} of ${total}`;

  const statusBadge = s => {
    const cls = s === 'up' ? 'color:var(--status-green)' : s === 'down' ? 'color:var(--status-red)' : 'color:var(--text-muted)';
    return `<span style="${cls};font-weight:600">${esc(s || '—')}</span>`;
  };

  const tbody = document.getElementById('ilTbody');
  tbody.innerHTML = slice.map((r, i) => {
    const globalIdx = (ilPage - 1) * ilPageSize + i + 1;
    return `<tr>
      <td style="font-size:.8rem;color:var(--text-muted)">${globalIdx}</td>
      <td><strong>${esc(r.device)}</strong></td>
      <td>${esc(r.interface)}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(r.vdom)}</td>
      <td style="font-size:.8rem">${esc(r.ip)}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(r.type)}</td>
      <td>${statusBadge(r.status)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" class="empty-state" style="padding:.85rem 1rem">No interfaces match your filter.</td></tr>`;

  renderIlPagination(total);
}

function renderIlPagination(total) {
  const pg = document.getElementById('ilPagination');
  if (total <= 1) { pg.innerHTML = ''; return; }
  function btn(label, page, disabled, active) {
    return `<button class="pg-btn${active ? ' active' : ''}" data-ilpage="${page}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }
  let html = btn('&laquo;&laquo;', 1, ilPage === 1, false);
  html += btn('&lsaquo;', ilPage - 1, ilPage === 1, false);
  const s = Math.max(1, ilPage - 2), e = Math.min(total, s + 4);
  for (let i = s; i <= e; i++) html += btn(i, i, false, i === ilPage);
  html += btn('&rsaquo;', ilPage + 1, ilPage === total, false);
  html += btn('&raquo;&raquo;', total, ilPage === total, false);
  pg.innerHTML = html;
}

/* ── Interface Lookup exports ───────────────────────────────────────────────── */
function ilExportCsv() {
  const meta = ilMeta || {};
  const header = ['#', 'Device', 'Interface', 'VDOM', 'IP / Mask', 'Type', 'Status'];
  const fh = [
    `# ADOM: ${meta.adom || ''}`,
    `# IPs: ${(meta.ips || []).join(', ')}`,
    `# Generated: ${new Date().toLocaleString()}`,
    `# Total: ${ilAllResults.length}  Shown: ${ilFiltered.length}`,
  ];
  const lines = [...fh, header.join(',')];
  ilFiltered.forEach((r, i) => {
    const q = s => `"${String(s ?? '').replace(/"/g, '""')}"`;
    lines.push([i + 1, q(r.device), q(r.interface), q(r.vdom), q(r.ip), q(r.type), q(r.status)].join(','));
  });
  download('interface_lookup.csv', lines.join('\r\n'), 'text/csv');
}

function ilExportJson() {
  const meta = ilMeta || {};
  const payload = {
    adom:      meta.adom,
    ips:       meta.ips,
    generated: new Date().toISOString(),
    total:     ilAllResults.length,
    filtered:  ilFiltered.length,
    results:   ilFiltered,
  };
  download('interface_lookup.json', JSON.stringify(payload, null, 2), 'application/json');
}

function ilExportPdf() {
  const meta  = ilMeta || {};
  const ipsLabel = (meta.ips || []).join(', ');
  const title = `Interface Lookup — ${ipsLabel} in ${meta.adom || ''}`;
  const ts    = new Date().toLocaleString();
  const tableRows = ilFiltered.map((r, i) => `<tr>
    <td>${i + 1}</td>
    <td><strong>${esc(r.device)}</strong></td>
    <td>${esc(r.interface)}</td>
    <td>${esc(r.vdom)}</td>
    <td>${esc(r.ip)}</td>
    <td>${esc(r.type)}</td>
    <td>${esc(r.status)}</td>
  </tr>`).join('');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:15px;margin-bottom:4px}
  .meta{font-size:10px;color:#5a6478;margin-bottom:12px;border-left:3px solid #93c5fd;padding-left:6px}
  table{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:4px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}
  @media print{body{margin:1cm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">Generated ${ts} &bull; ${ilFiltered.length} of ${ilAllResults.length} results</div>
<table>
  <thead><tr><th>#</th><th>Device</th><th>Interface</th><th>VDOM</th><th>IP / Mask</th><th>Type</th><th>Status</th></tr></thead>
  <tbody>${tableRows}</tbody>
</table>
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.focus(); win.print(); }
}

/* ═══════════════════════════════════════════════════════════════════════════════
   NAT LOOKUP
   ═══════════════════════════════════════════════════════════════════════════════ */

async function runNatLookup() {
  const adom  = document.getElementById('nlAdom').value;
  const query = document.getElementById('nlQuery').value.trim();
  if (!adom || !query) return;

  document.getElementById('nlError').style.display      = 'none';
  document.getElementById('nlResults').style.display    = 'none';
  document.getElementById('nlSearchBtn').disabled       = true;
  document.getElementById('nlRunning').style.display    = '';
  document.getElementById('nlProgressWrap').style.display = 'block';

  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/nat/lookup`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ ip: query }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      document.getElementById('nlError').textContent  = data.error || 'Lookup failed.';
      document.getElementById('nlError').style.display = '';
      return;
    }
    nlAllResults = data.results || [];
    nlMeta       = { adom, ip: data.searched_ip || query };
    nlPage       = 1;
    nlFilter     = '';
    document.getElementById('nlFilter').value = '';
    applyNlFilter();
    renderNlTable();
    document.getElementById('nlResults').style.display = '';
  } catch (err) {
    document.getElementById('nlError').textContent  = err.message;
    document.getElementById('nlError').style.display = '';
  } finally {
    document.getElementById('nlSearchBtn').disabled     = false;
    document.getElementById('nlRunning').style.display  = 'none';
    document.getElementById('nlProgressWrap').style.display = 'none';
  }
}

function applyNlFilter() {
  if (!nlFilter) { nlFiltered = nlAllResults; return; }
  const q = nlFilter.toLowerCase();
  nlFiltered = nlAllResults.filter(r =>
    (r.name       || '').toLowerCase().includes(q) ||
    (r.nat_type   || '').toLowerCase().includes(q) ||
    (r.ext_ip     || '').toLowerCase().includes(q) ||
    (r.mapped_ip  || '').toLowerCase().includes(q) ||
    (r.start_ip   || '').toLowerCase().includes(q) ||
    (r.end_ip     || '').toLowerCase().includes(q) ||
    (r.ext_intf   || '').toLowerCase().includes(q) ||
    (r.comments   || '').toLowerCase().includes(q)
  );
}

function renderNlTable() {
  const rows  = nlFiltered;
  const total = Math.ceil(rows.length / nlPageSize) || 1;
  nlPage      = Math.min(nlPage, total);
  const slice = rows.slice((nlPage - 1) * nlPageSize, nlPage * nlPageSize);
  const meta  = nlMeta || {};

  const shown = rows.length === nlAllResults.length
    ? `${nlAllResults.length} result${nlAllResults.length !== 1 ? 's' : ''}`
    : `${rows.length} of ${nlAllResults.length} result${nlAllResults.length !== 1 ? 's' : ''}`;
  document.getElementById('nlSummary').textContent =
    nlAllResults.length === 0
      ? `No NAT entries found for ${meta.ip || ''} in ${meta.adom || ''}`
      : `${shown} for ${meta.ip || ''} in ${meta.adom || ''}`;
  document.getElementById('nlCount').textContent =
    `${shown} — page ${nlPage} of ${total}`;

  const typeBadge = t => t === 'VIP'
    ? `<span class="obj-type-badge obj-type-object">VIP</span>`
    : `<span class="obj-type-badge obj-type-group">IP Pool</span>`;

  const tbody = document.getElementById('nlTbody');
  tbody.innerHTML = slice.map((r, i) => {
    const globalIdx = (nlPage - 1) * nlPageSize + i + 1;
    let extIp, mappedIp, extIntf, protPort, notes;

    if (r.nat_type === 'VIP') {
      extIp    = esc(r.ext_ip || '—');
      mappedIp = esc(r.mapped_ip || '—');
      extIntf  = esc(r.ext_intf || '—');
      protPort = r.port_forward && r.protocol
        ? esc(`${r.protocol}:${r.ext_port}→${r.mapped_port}`)
        : '—';
      notes    = esc(r.comments || '—');
    } else {
      extIp    = esc(`${r.start_ip}–${r.end_ip}`);
      mappedIp = '—';
      extIntf  = '—';
      protPort = esc(r.pool_type || '—');
      notes    = esc(r.comments || '—');
    }

    return `<tr>
      <td style="font-size:.8rem;color:var(--text-muted)">${globalIdx}</td>
      <td>${typeBadge(r.nat_type)}</td>
      <td><strong>${esc(r.name)}</strong></td>
      <td style="font-size:.8rem">${extIp}</td>
      <td style="font-size:.8rem">${mappedIp}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${extIntf}</td>
      <td style="font-size:.8rem">${protPort}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${notes}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="8" class="empty-state" style="padding:.85rem 1rem">No NAT entries match your filter.</td></tr>`;

  renderNlPagination(total);
}

function renderNlPagination(total) {
  const pg = document.getElementById('nlPagination');
  if (total <= 1) { pg.innerHTML = ''; return; }
  function btn(label, page, disabled, active) {
    return `<button class="pg-btn${active ? ' active' : ''}" data-nlpage="${page}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }
  let html = btn('&laquo;&laquo;', 1, nlPage === 1, false);
  html += btn('&lsaquo;', nlPage - 1, nlPage === 1, false);
  const s = Math.max(1, nlPage - 2), e = Math.min(total, s + 4);
  for (let i = s; i <= e; i++) html += btn(i, i, false, i === nlPage);
  html += btn('&rsaquo;', nlPage + 1, nlPage === total, false);
  html += btn('&raquo;&raquo;', total, nlPage === total, false);
  pg.innerHTML = html;
}

/* ── NAT Lookup exports ─────────────────────────────────────────────────────── */
function nlExportCsv() {
  const meta = nlMeta || {};
  const header = ['#', 'Type', 'Name', 'External IP', 'Mapped / Pool IP', 'Interface', 'Protocol / Port', 'Notes'];
  const fh = [
    `# ADOM: ${meta.adom || ''}`,
    `# IP: ${meta.ip || ''}`,
    `# Generated: ${new Date().toLocaleString()}`,
    `# Total: ${nlAllResults.length}  Shown: ${nlFiltered.length}`,
  ];
  const lines = [...fh, header.join(',')];
  nlFiltered.forEach((r, i) => {
    const q = s => `"${String(s ?? '').replace(/"/g, '""')}"`;
    const extIp   = r.nat_type === 'VIP' ? r.ext_ip : `${r.start_ip}-${r.end_ip}`;
    const mapped  = r.nat_type === 'VIP' ? r.mapped_ip : '';
    const intf    = r.nat_type === 'VIP' ? r.ext_intf : '';
    const pport   = r.nat_type === 'VIP' && r.port_forward && r.protocol
      ? `${r.protocol}:${r.ext_port}->${r.mapped_port}` : (r.pool_type || '');
    lines.push([i + 1, q(r.nat_type), q(r.name), q(extIp), q(mapped), q(intf), q(pport), q(r.comments || '')].join(','));
  });
  download('nat_lookup.csv', lines.join('\r\n'), 'text/csv');
}

function nlExportJson() {
  const meta = nlMeta || {};
  const payload = {
    adom:      meta.adom,
    ip:        meta.ip,
    generated: new Date().toISOString(),
    total:     nlAllResults.length,
    filtered:  nlFiltered.length,
    results:   nlFiltered,
  };
  download('nat_lookup.json', JSON.stringify(payload, null, 2), 'application/json');
}

function nlExportPdf() {
  const meta  = nlMeta || {};
  const title = `NAT Lookup — ${meta.ip || ''} in ${meta.adom || ''}`;
  const ts    = new Date().toLocaleString();
  const tableRows = nlFiltered.map((r, i) => {
    const extIp   = r.nat_type === 'VIP' ? r.ext_ip : `${r.start_ip}–${r.end_ip}`;
    const mapped  = r.nat_type === 'VIP' ? (r.mapped_ip || '—') : '—';
    const intf    = r.nat_type === 'VIP' ? (r.ext_intf || '—') : '—';
    const pport   = r.nat_type === 'VIP' && r.port_forward && r.protocol
      ? `${r.protocol}:${r.ext_port}→${r.mapped_port}` : (r.pool_type || '—');
    return `<tr>
      <td>${i + 1}</td>
      <td>${esc(r.nat_type)}</td>
      <td><strong>${esc(r.name)}</strong></td>
      <td>${esc(extIp)}</td>
      <td>${esc(mapped)}</td>
      <td>${esc(intf)}</td>
      <td>${esc(pport)}</td>
      <td>${esc(r.comments || '—')}</td>
    </tr>`;
  }).join('');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:15px;margin-bottom:4px}
  .meta{font-size:10px;color:#5a6478;margin-bottom:12px;border-left:3px solid #93c5fd;padding-left:6px}
  table{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:4px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}
  @media print{body{margin:1cm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">Generated ${ts} &bull; ${nlFiltered.length} of ${nlAllResults.length} results</div>
<table>
  <thead><tr><th>#</th><th>Type</th><th>Name</th><th>External IP</th><th>Mapped / Pool IP</th><th>Interface</th><th>Protocol / Port</th><th>Notes</th></tr></thead>
  <tbody>${tableRows}</tbody>
</table>
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.focus(); win.print(); }
}
```

- [ ] **Step 3: Add event wiring for both lookups**

In `app/static/js/hygiene.js`, just before the final `loadAdoms();` call (currently line 1421), insert:

```javascript
/* ── Interface Lookup wiring ────────────────────────────────────────────────── */
document.getElementById('ilCloseBtn').addEventListener('click', () => {
  ilAllResults = []; ilFiltered = [];
  document.getElementById('ilResults').style.display     = 'none';
  document.getElementById('ilSkippedWarn').style.display = 'none';
  document.getElementById('ilFilter').value  = '';
  document.getElementById('ilAdom').value    = '';
  document.getElementById('ilQuery').value   = '';
  document.getElementById('ilSearchBtn').disabled = true;
});

document.getElementById('ilAdom').addEventListener('change', function () {
  const hasAdom = !!this.value;
  document.getElementById('ilQuery').disabled = !hasAdom;
  document.getElementById('ilSearchBtn').disabled = !hasAdom || !document.getElementById('ilQuery').value.trim();
  if (!hasAdom) {
    ilAllResults = []; ilFiltered = [];
    document.getElementById('ilResults').style.display = 'none';
    document.getElementById('ilSkippedWarn').style.display = 'none';
  }
});

document.getElementById('ilQuery').addEventListener('input', function () {
  const adom = document.getElementById('ilAdom').value;
  document.getElementById('ilSearchBtn').disabled = !adom || !this.value.trim();
});

document.getElementById('ilQuery').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('ilSearchBtn').click();
});

document.getElementById('ilSearchBtn').addEventListener('click', runInterfaceLookup);

document.getElementById('ilFilter').addEventListener('input', debounce(function () {
  ilFilter = this.value;
  ilPage   = 1;
  applyIlFilter();
  renderIlTable();
}, 200));

document.getElementById('ilPageSize').addEventListener('change', function () {
  ilPageSize = parseInt(this.value, 10);
  ilPage     = 1;
  renderIlTable();
});

document.getElementById('ilPagination').addEventListener('click', e => {
  const pg = e.target.closest('[data-ilpage]');
  if (!pg) return;
  const total = Math.ceil(ilFiltered.length / ilPageSize) || 1;
  ilPage = Math.max(1, Math.min(total, parseInt(pg.dataset.ilpage, 10)));
  renderIlTable();
});

document.getElementById('ilExportCsv').addEventListener('click', ilExportCsv);
document.getElementById('ilExportJson').addEventListener('click', ilExportJson);
document.getElementById('ilExportPdf').addEventListener('click', ilExportPdf);

/* ── NAT Lookup wiring ──────────────────────────────────────────────────────── */
document.getElementById('nlCloseBtn').addEventListener('click', () => {
  nlAllResults = []; nlFiltered = [];
  document.getElementById('nlResults').style.display = 'none';
  document.getElementById('nlFilter').value  = '';
  document.getElementById('nlAdom').value    = '';
  document.getElementById('nlQuery').value   = '';
  document.getElementById('nlSearchBtn').disabled = true;
});

document.getElementById('nlAdom').addEventListener('change', function () {
  const hasAdom = !!this.value;
  document.getElementById('nlQuery').disabled = !hasAdom;
  document.getElementById('nlSearchBtn').disabled = !hasAdom || !document.getElementById('nlQuery').value.trim();
  if (!hasAdom) {
    nlAllResults = []; nlFiltered = [];
    document.getElementById('nlResults').style.display = 'none';
  }
});

document.getElementById('nlQuery').addEventListener('input', function () {
  const adom = document.getElementById('nlAdom').value;
  document.getElementById('nlSearchBtn').disabled = !adom || !this.value.trim();
});

document.getElementById('nlQuery').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('nlSearchBtn').click();
});

document.getElementById('nlSearchBtn').addEventListener('click', runNatLookup);

document.getElementById('nlFilter').addEventListener('input', debounce(function () {
  nlFilter = this.value;
  nlPage   = 1;
  applyNlFilter();
  renderNlTable();
}, 200));

document.getElementById('nlPageSize').addEventListener('change', function () {
  nlPageSize = parseInt(this.value, 10);
  nlPage     = 1;
  renderNlTable();
});

document.getElementById('nlPagination').addEventListener('click', e => {
  const pg = e.target.closest('[data-nlpage]');
  if (!pg) return;
  const total = Math.ceil(nlFiltered.length / nlPageSize) || 1;
  nlPage = Math.max(1, Math.min(total, parseInt(pg.dataset.nlpage, 10)));
  renderNlTable();
});

document.getElementById('nlExportCsv').addEventListener('click', nlExportCsv);
document.getElementById('nlExportJson').addEventListener('click', nlExportJson);
document.getElementById('nlExportPdf').addEventListener('click', nlExportPdf);
```

Also update `loadAdoms()` to populate the new ADOM selectors. Find the existing `loadAdoms` function and check where it populates ADOM selectors — it should already iterate over all selectors. If the existing implementation uses a querySelectorAll or a hardcoded list, add `ilAdom` and `nlAdom` to that list.

Find in `hygiene.js` the `loadAdoms` function (around line 37). Look for where it populates ADOM `<select>` elements. It likely contains something like:
```javascript
['hygieneAdom', 'olAdom', 'pvAdom'].forEach(id => { ... })
```
Add `'ilAdom'` and `'nlAdom'` to that array.

- [ ] **Step 4: Verify the JS loads without syntax errors**

```bash
node --check app/static/js/hygiene.js
```

Expected: no output (syntax OK)

- [ ] **Step 5: Commit**

```bash
git add app/static/js/hygiene.js
git commit -m "feat: add Interface Lookup and NAT Lookup JavaScript"
```

---

### Task 5: Wire ADOM selectors and final integration check

**Files:**
- Modify: `app/static/js/hygiene.js` — update `loadAdoms()` to include `ilAdom` and `nlAdom`

**Note:** This task may already be done in Task 4 Step 3 if the existing `loadAdoms` uses a loop. Verify first before making changes.

- [ ] **Step 1: Check existing `loadAdoms` implementation**

Read `app/static/js/hygiene.js` lines 37–80 and identify exactly how ADOM selectors are populated.

- [ ] **Step 2: Add `ilAdom` and `nlAdom` to the selector list**

If `loadAdoms` populates selectors via an array like:
```javascript
['hygieneAdom', 'olAdom', 'pvAdom'].forEach(id => {
```
Change it to:
```javascript
['hygieneAdom', 'olAdom', 'pvAdom', 'ilAdom', 'nlAdom'].forEach(id => {
```

If it uses a different mechanism (e.g., `querySelectorAll`), adapt accordingly — the goal is that `ilAdom` and `nlAdom` get populated with the same ADOM list as the other selectors.

- [ ] **Step 3: Run a full app smoke test**

```bash
python -c "
from app import create_app
app = create_app()
with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['username'] = 'admin'
        sess['role'] = 'admin'
    resp = c.get('/hygiene')
    assert resp.status_code == 200, f'Got {resp.status_code}'
    body = resp.data.decode()
    assert 'ilAdom' in body, 'ilAdom not found in template'
    assert 'nlAdom' in body, 'nlAdom not found in template'
    assert 'Interface Lookup' in body, 'Interface Lookup section missing'
    assert 'NAT Lookup' in body, 'NAT Lookup section missing'
    print('All assertions passed')
"
```

Expected: `All assertions passed`

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_fmg_client_nat.py tests/test_hygiene_routes_lookup.py -v
```

Expected: all tests PASSED

- [ ] **Step 5: Final commit and push**

```bash
git add app/static/js/hygiene.js
git commit -m "feat: wire ADOM selectors for Interface and NAT Lookup sections"
git push origin development
```
