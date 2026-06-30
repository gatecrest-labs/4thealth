"""FortiManager JSON-RPC client — read-only, no device changes."""

import os
import warnings

import requests
import urllib3

if os.environ.get("FMG_SUPPRESS_INSECURE_WARNING", "true").lower() == "true":
    warnings.filterwarnings(
        "ignore", category=urllib3.exceptions.InsecureRequestWarning
    )

PROXY_ENDPOINTS = [
    {
        "key": "system_status",
        "label": "System status",
        "resource": "/api/v2/monitor/system/status?vdom=root",
        "required": True,
    },
    {
        "key": "cpu",
        "label": "CPU usage",
        "resource": "/api/v2/monitor/system/resource/usage?resource=cpu&interval=1-min&vdom=root",
        "required": True,
    },
    {
        "key": "mem",
        "label": "Memory usage",
        "resource": "/api/v2/monitor/system/resource/usage?resource=mem&interval=1-min&vdom=root",
        "required": True,
    },
    {
        "key": "interfaces",
        "label": "Interfaces",
        "resource": "/api/v2/monitor/system/interface?vdom=root",
        "required": False,
    },
    {
        "key": "interfaces_cfg",
        "label": "Interface config",
        "resource": "/api/v2/cmdb/system/interface?vdom=root",
        "required": False,
    },
    {
        "key": "performance",
        "label": "Performance",
        "resource": "/api/v2/monitor/system/performance/status?vdom=root",
        "required": False,
    },
    {
        "key": "ha_status",
        "label": "HA status",
        "resource": "/api/v2/monitor/system/ha-status?vdom=root",
        "required": False,
    },
    {
        "key": "ipv4_routes",
        "label": "IPv4 routes",
        "resource": "/api/v2/monitor/router/ipv4?vdom=*",
        "required": False,
    },
    {
        "key": "ipv6_routes",
        "label": "IPv6 routes",
        "resource": "/api/v2/monitor/router/ipv6?vdom=*",
        "required": False,
    },
    {
        "key": "bgp_neighbors",
        "label": "BGP neighbors",
        "resource": "/api/v2/monitor/router/bgp/neighbors?vdom=*",
        "required": False,
    },
    {
        "key": "bgp_paths",
        "label": "BGP paths",
        "resource": "/api/v2/monitor/router/bgp/paths?vdom=*",
        "required": False,
    },
    {
        "key": "ospf_neighbors",
        "label": "OSPF neighbors",
        "resource": "/api/v2/monitor/router/ospf/neighbors?vdom=*",
        "required": False,
    },
    {
        "key": "ipsec",
        "label": "IPsec tunnels",
        "resource": "/api/v2/monitor/vpn/ipsec?vdom=root",
        "required": False,
    },
]


class FMGError(Exception):
    pass


class FMGClient:
    def __init__(
        self,
        host: str,
        username: str = "",
        password: str = "",
        token: str = "",
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        self.base_url = f"https://{host}/jsonrpc"
        self.username = username
        self.password = password
        self.token = token
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = None
        self._req_id = 0

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = requests.post(
            self.base_url,
            json=body,
            verify=self.verify_ssl,
            timeout=self.timeout,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    def login(self):
        # Bearer token auth — no login call needed
        if self.token:
            return
        body = {
            "id": self._next_id(),
            "method": "exec",
            "params": [
                {
                    "url": "/sys/login/user",
                    "data": {"user": self.username, "passwd": self.password},
                }
            ],
        }
        data = self._post(body)
        result = data.get("result", [{}])[0]
        if result.get("status", {}).get("code", -1) != 0:
            raise FMGError("Authentication failed")
        self.session = data["session"]

    def logout(self):
        # Bearer token auth — no logout call needed
        if self.token:
            return
        if not self.session:
            return
        try:
            self._post(
                {
                    "id": self._next_id(),
                    "method": "exec",
                    "session": self.session,
                    "params": [{"url": "/sys/logout"}],
                }
            )
        except Exception:
            pass
        self.session = None

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *_):
        self.logout()

    def _get(self, url: str) -> dict:
        body = {
            "id": self._next_id(),
            "method": "get",
            "params": [{"url": url}],
        }
        if self.session:
            body["session"] = self.session
        data = self._post(body)
        result = data.get("result", [{}])[0]
        if result.get("status", {}).get("code", -1) != 0:
            raise FMGError(f"FMG error on {url}: {result.get('status')}")
        return result.get("data", {})

    def get_system_status(self) -> dict:
        """Return FortiManager /sys/status."""
        return self._get("/sys/status")

    def get_performance(self) -> dict:
        """Return FortiManager /sys/resource/performance (CPU, memory)."""
        try:
            return self._get("/sys/resource/performance")
        except Exception:
            return {}

    def get_resource_usage(self) -> dict:
        """Alternative CPU/mem endpoint used on some FMG versions."""
        try:
            return self._get("/sys/resource/usage")
        except Exception:
            return {}

    def get_adoms(self) -> list:
        return self._get("/dvmdb/adom") or []

    def get_devices(self, adom: str) -> list:
        return self._get(f"/dvmdb/adom/{adom}/device") or []

    def _proxy(self, adom: str, device: str, resource: str) -> dict:
        body = {
            "id": self._next_id(),
            "method": "exec",
            "params": [
                {
                    "url": "/sys/proxy/json",
                    "data": {
                        "action": "get",
                        "resource": resource,
                        "target": [f"adom/{adom}/device/{device}"],
                    },
                }
            ],
        }
        if self.session:
            body["session"] = self.session
        data = self._post(body)
        result = data.get("result", [{}])[0]
        rpc_code = result.get("status", {}).get("code", -1)
        raw = result.get("data", {})

        # FMG proxy envelope:
        #   result[0].data → list of per-device dicts
        #   each dict has: { "response": { "http_status": 200, "results": <actual data> }, ... }
        # We need to unwrap two layers: data[0] → .response → .results
        http_status = 200
        payload = {}

        # Step 1: get the per-device dict (first element of the list, or the dict itself)
        if isinstance(raw, list) and raw:
            device_wrapper = raw[0] if isinstance(raw[0], dict) else {}
        elif isinstance(raw, dict):
            device_wrapper = raw
        else:
            device_wrapper = {}

        # Step 2: pull http_status from the wrapper (before diving into response)
        http_status = int(
            device_wrapper.get(
                "http_status", device_wrapper.get("http_status_code", 200)
            )
        )

        # Step 3: unwrap .response — may be a dict or a JSON-encoded string
        response = device_wrapper.get("response", device_wrapper)
        if isinstance(response, str):
            try:
                import json as _json

                response = _json.loads(response)
            except Exception:
                response = {}
        if isinstance(response, dict):
            http_status = int(response.get("http_status", http_status))
            payload = response.get("results", response)
        else:
            payload = response

        return {"rpc_code": rpc_code, "http_status": http_status, "payload": payload}

    def get_device(self, adom: str, device_name: str) -> dict:
        """Fetch a single device record from FMG's dvmdb — authoritative for inventory fields."""
        data = self._get(f"/dvmdb/adom/{adom}/device/{device_name}")
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return {}

    def get_device_vdoms(self, adom: str, device_name: str) -> list:
        """Return the list of VDOMs for a device from dvmdb (empty list when not in VDOM mode)."""
        try:
            data = self._get(f"/dvmdb/adom/{adom}/device/{device_name}/vdom")
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def get_policy_packages(self, adom: str) -> list:
        """Return all policy packages in an ADOM, recursing into folder subobj lists.

        Each returned dict has 'name' (display name) and 'path' (the slash-joined
        folder/package string needed for API calls, e.g. 'MyFolder/MyPackage').
        """
        try:
            data = self._get(f"/pm/pkg/adom/{adom}")
            if not isinstance(data, list):
                return []
            return self._flatten_packages(data, prefix="")
        except Exception:
            return []

    @staticmethod
    def _flatten_packages(items: list, prefix: str) -> list:
        """Recursively collect pkg-type entries, tracking the folder path."""
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            pkg_type = (item.get("type") or "").lower()
            if pkg_type == "folder":
                sub = item.get("subobj") or []
                if isinstance(sub, list):
                    folder_prefix = f"{prefix}{name}/" if name else prefix
                    result.extend(FMGClient._flatten_packages(sub, folder_prefix))
            else:
                result.append({**item, "path": f"{prefix}{name}"})
        return result

    def get_pkg_settings(self, adom: str, pkg_path: str) -> dict:
        """Return the 'package settings' dict for a policy package.

        The last component of pkg_path is the package name; the leading parts
        are folder names.  The API path for the package object itself is:
          /pm/pkg/adom/<adom>/<folder1>/<folder2>/.../<pkg_name>
        Returns {} on any error.
        """
        try:
            data = self._get(f"/pm/pkg/adom/{adom}/{pkg_path}")
            if isinstance(data, dict):
                return data.get("package settings") or {}
            if isinstance(data, list) and data:
                return data[0].get("package settings") or {}
        except Exception:
            pass
        return {}

    def get_policies(self, adom: str, pkg_path: str) -> list:
        """Return all firewall policies in a package.

        pkg_path is the slash-joined folder/package path as returned by
        get_policy_packages(), e.g. 'MyFolder/MyPackage' or just 'MyPackage'.

        FMG JSON-RPC caps un-ranged results at 500. We paginate with 1000-row
        windows until we get a short page, guaranteeing all rules are returned
        regardless of package size.
        """
        url = f"/pm/config/adom/{adom}/pkg/{pkg_path}/firewall/policy"
        all_policies: list = []
        page_size = 1000
        offset = 0
        while True:
            body = {
                "id": self._next_id(),
                "method": "get",
                "params": [{"url": url, "range": [offset, page_size]}],
            }
            if self.session:
                body["session"] = self.session
            data = self._post(body)
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", -1) != 0:
                raise FMGError(f"FMG error on {url}: {result.get('status')}")
            page = result.get("data", [])
            if not isinstance(page, list):
                break
            all_policies.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return all_policies

    def get_pblock_policies(self, adom: str, block_name: str) -> list:
        """Return firewall policies from a policy block (pblock) in an ADOM.

        FMG 7.2+ stores policy blocks under:
          /pm/config/adom/<adom>/pblock/<block_name>/firewall/policy

        Returns [] if the block doesn't exist or is inaccessible.
        """
        url = f"/pm/config/adom/{adom}/pblock/{block_name}/firewall/policy"
        all_policies: list = []
        page_size = 1000
        offset = 0
        while True:
            body = {
                "id": self._next_id(),
                "method": "get",
                "params": [{"url": url, "range": [offset, page_size]}],
            }
            if self.session:
                body["session"] = self.session
            data = self._post(body)
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", -1) != 0:
                return []
            page = result.get("data", [])
            if not isinstance(page, list):
                break
            all_policies.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return all_policies

    def get_live_policy_hits(
        self, adom: str, device_name: str, vdom: str = "root"
    ) -> dict:
        """Return live per-policy hit counts from the device via FMG proxy.

        FMG's stored _hitcount is updated only when FMG syncs stats from the
        device (which may be infrequent or never).  This method queries the
        FortiGate's monitor API directly through FMG's proxy so hit counts are
        always current regardless of FMG sync state.

        Returns {policyid (int): hit_count (int)}.  Returns {} on any error so
        callers can fall back to FMG-cached values gracefully.
        """
        try:
            r = self._proxy(
                adom, device_name, f"/api/v2/monitor/firewall/policy?vdom={vdom}"
            )
            payload = r.get("payload", [])
            if not isinstance(payload, list):
                return {}
            result: dict = {}
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                pid = entry.get("policyid") or entry.get("id")
                if pid is None:
                    continue
                # FortiOS REST API uses "hit_count" on the monitor endpoint
                hit = entry.get("hit_count")
                if hit is None:
                    hit = entry.get("hitcount", 0)
                result[int(pid)] = int(hit) if hit is not None else 0
            return result
        except Exception:
            return {}

    def get_policy_count(self, adom: str, pkg_path: str) -> int:
        """Return the number of firewall policies in a package without fetching full objects."""
        try:
            # Use fields param to minimise payload — we only need the count
            body = {
                "id": self._next_id(),
                "method": "get",
                "params": [
                    {
                        "url": f"/pm/config/adom/{adom}/pkg/{pkg_path}/firewall/policy",
                        "fields": ["policyid"],
                    }
                ],
            }
            if self.session:
                body["session"] = self.session
            data = self._post(body)
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", -1) != 0:
                return 0
            policies = result.get("data", [])
            return len(policies) if isinstance(policies, list) else 0
        except Exception:
            return 0

    def get_pkg_scope_members(self, adom: str, pkg_path: str) -> list:
        """Return the list of devices/groups this policy package is installed on.

        Each entry is typically {"name": "FW01", "vdom": "root"}.
        Returns [] on error or when the package has no explicit scope.
        """
        try:
            data = self._get(f"/pm/pkg/adom/{adom}/{pkg_path}")
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                return []
            scope = data.get("scope member") or data.get("scope_member") or []
            if isinstance(scope, list):
                return scope
            return []
        except Exception:
            return []

    def get_device_policy_package(self, adom: str, device_name: str) -> list[dict]:
        """Return policy packages installed on a device.

        Uses the scope member list already embedded in each package dict returned by
        get_policy_packages() — no additional API calls are made.
        Returns a list of {"name": pkg_name, "vdom": vdom} dicts (usually one entry);
        [] if none found or on error.
        """
        try:
            packages = self.get_policy_packages(adom)
            matched = []
            for pkg in packages:
                scope = pkg.get("scope member") or pkg.get("scope_member") or []
                if not isinstance(scope, list):
                    continue
                for m in scope:
                    if (
                        isinstance(m, dict)
                        and m.get("name", "").lower() == device_name.lower()
                    ):
                        matched.append({"name": pkg["name"], "vdom": m.get("vdom", "")})
            return matched
        except Exception:
            return []

    def get_device_interfaces(self, adom: str, device_name: str) -> list:
        """Return interface list from live device via FMG proxy (root VDOM only)."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/monitor/system/interface?vdom=root"
            )
            payload = r.get("payload", {})
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return list(payload.values())
            return []
        except Exception:
            return []

    def get_device_interfaces_all_vdoms(self, adom: str, device_name: str) -> list:
        """Return all interfaces across every VDOM using the CMDB endpoint (vdom=*).

        CMDB returns a flat list; each entry has 'vdom', 'name', 'ip', 'type',
        'allowaccess' (space-separated string), and 'status'.  VLAN and
        sub-interfaces are included because the CMDB covers all interface types.
        """
        try:
            r = self._proxy(adom, device_name, "/api/v2/cmdb/system/interface?vdom=*")
            payload = r.get("payload", {})
            # vdom=* wraps each vdom's results in [{vdom: ..., results: [...]}, ...]
            if isinstance(payload, list):
                # Could be either the flat list or the vdom-envelope list
                if payload and isinstance(payload[0], dict) and "results" in payload[0]:
                    flat = []
                    seen: set[str] = set()
                    for item in payload:
                        vname = item.get("vdom", "root")
                        results = item.get("results", [])
                        if isinstance(results, list):
                            for iface in results:
                                if isinstance(iface, dict):
                                    iface.setdefault("vdom", vname)
                                    # Physical/global interfaces appear once per VDOM;
                                    # deduplicate by name so each interface is listed once.
                                    iname = iface.get("name", "")
                                    if iname and iname not in seen:
                                        seen.add(iname)
                                        flat.append(iface)
                    return flat
                return [i for i in payload if isinstance(i, dict)]
            if isinstance(payload, dict):
                return list(payload.values())
            return []
        except Exception:
            return []

    def get_device_routes(self, adom: str, device_name: str) -> list:
        """Return IPv4 routing table from live device via FMG proxy."""
        try:
            r = self._proxy(adom, device_name, "/api/v2/monitor/router/ipv4?vdom=root")
            payload = r.get("payload", [])
            return payload if isinstance(payload, list) else []
        except Exception:
            return []

    def get_device_routes_all_vdoms(self, adom: str, device_name: str) -> list:
        """Return IPv4 routing table across all VDOMs via FMG proxy.

        The vdom=* envelope returns [{vdom: ..., results: [...]}, ...]; we
        flatten it so callers get a single list of route dicts identical to
        what get_device_routes() returns for the root VDOM.
        """
        try:
            r = self._proxy(adom, device_name, "/api/v2/monitor/router/ipv4?vdom=*")
            payload = r.get("payload", [])
            if isinstance(payload, list):
                if payload and isinstance(payload[0], dict) and "results" in payload[0]:
                    flat = []
                    for item in payload:
                        results = item.get("results", [])
                        if isinstance(results, list):
                            flat.extend(r for r in results if isinstance(r, dict))
                    return flat
                return [r for r in payload if isinstance(r, dict)]
            return []
        except Exception:
            return []

    def get_device_ntp(self, adom: str, device_name: str) -> dict:
        """Return NTP configuration from the device via FMG proxy.

        Returns the raw CMDB dict for system/ntp (keys: ntpsync, type,
        ntpserver list, etc.), or an empty dict on failure.
        """
        try:
            r = self._proxy(adom, device_name, "/api/v2/cmdb/system/ntp?vdom=root")
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_syslog(self, adom: str, device_name: str) -> list:
        """Return all enabled remote syslog servers configured on the device.

        FortiOS supports up to 4 syslog profiles (syslogd … syslogd4).  Each
        enabled profile is returned as a dict with at least ``server`` and
        ``status`` keys.  Disabled or unreachable profiles are omitted.
        """
        profiles = [
            "/api/v2/cmdb/log.syslogd/setting?vdom=root",
            "/api/v2/cmdb/log.syslogd2/setting?vdom=root",
            "/api/v2/cmdb/log.syslogd3/setting?vdom=root",
            "/api/v2/cmdb/log.syslogd4/setting?vdom=root",
        ]
        servers: list[dict] = []
        for resource in profiles:
            try:
                r = self._proxy(adom, device_name, resource)
                payload = r.get("payload", {})
                if isinstance(payload, list) and payload:
                    cfg = payload[0] if isinstance(payload[0], dict) else {}
                elif isinstance(payload, dict):
                    cfg = payload
                else:
                    continue
                if cfg.get("status") == "enable" and cfg.get("server"):
                    servers.append(cfg)
            except Exception:
                continue
        return servers

    def _get_paged(self, url: str, page_size: int = 1000) -> list:
        """Paginated GET for endpoints that may return large lists.

        Sends range=[offset, page_size] until a short page is returned.
        Uses a per-request timeout of 120 s to handle large ADOM object lists
        that exceed the default 30 s window.
        """
        all_items: list = []
        offset = 0
        while True:
            body = {
                "id": self._next_id(),
                "method": "get",
                "params": [{"url": url, "range": [offset, page_size]}],
            }
            if self.session:
                body["session"] = self.session
            import requests as _req

            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            resp = _req.post(
                self.base_url,
                json=body,
                verify=self.verify_ssl,
                timeout=120,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", -1) != 0:
                raise FMGError(f"FMG error on {url}: {result.get('status')}")
            page = result.get("data", [])
            if not isinstance(page, list):
                break
            all_items.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return all_items

    def get_address_objects(self, adom: str) -> list:
        """Return all firewall address objects in an ADOM plus the global database.

        FMG stores shared objects under /pm/config/global/obj when they are
        defined in the Global ADOM.  We fetch both and merge so the caller always
        gets the full resolved set regardless of where objects live.
        Paginates to avoid the 30 s timeout on large ADOM object lists.
        """
        results: list = []
        for url in (
            f"/pm/config/adom/{adom}/obj/firewall/address",
            "/pm/config/global/obj/firewall/address",
        ):
            try:
                results.extend(self._get_paged(url))
            except Exception:
                pass
        return results

    def get_address_groups(self, adom: str) -> list:
        """Return all firewall address groups in an ADOM plus the global database."""
        results: list = []
        for url in (
            f"/pm/config/adom/{adom}/obj/firewall/addrgrp",
            "/pm/config/global/obj/firewall/addrgrp",
        ):
            try:
                results.extend(self._get_paged(url))
            except Exception:
                pass
        return results

    def get_service_objects(self, adom: str) -> list:
        """Return all custom service objects in an ADOM."""
        try:
            data = self._get(f"/pm/config/adom/{adom}/obj/firewall/service/custom")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_service_groups(self, adom: str) -> list:
        """Return all service groups in an ADOM."""
        try:
            data = self._get(f"/pm/config/adom/{adom}/obj/firewall/service/group")
            return data if isinstance(data, list) else []
        except Exception:
            return []

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

    def get_audit_log(self, hours: int = 24) -> list:
        """Return FortiManager audit log entries from the last ``hours`` hours.

        Returns a list of log entry dicts.  Returns an empty list on any error
        so callers can degrade gracefully if the FMG version doesn't support
        this endpoint.
        """
        import time as _time

        since = int(_time.time()) - (hours * 3600)
        try:
            body = {
                "id": self._next_id(),
                "method": "get",
                "params": [
                    {
                        "url": "/sys/audit-log",
                        "filter": [["timestamp", ">=", since]],
                        "sortings": [{"timestamp": -1}],
                        "range": [0, 5000],
                    }
                ],
            }
            if self.session:
                body["session"] = self.session
            data = self._post(body)
            result = data.get("result", [{}])[0]
            if result.get("status", {}).get("code", -1) != 0:
                return []
            entries = result.get("data", [])
            return entries if isinstance(entries, list) else []
        except Exception:
            return []

    def get_device_health(self, adom: str, device_name: str) -> dict:
        results = {}
        for ep in PROXY_ENDPOINTS:
            key = ep["key"]
            try:
                r = self._proxy(adom, device_name, ep["resource"])
                results[key] = r
            except Exception as exc:
                results[key] = {
                    "rpc_code": -1,
                    "http_status": 500,
                    "payload": {},
                    "error": str(exc),
                }
        return results

    def stream_device_health(self, adom: str, device_name: str):
        """Yield (index, total, label, key, result) for each proxy endpoint as it completes."""
        total = len(PROXY_ENDPOINTS)
        for i, ep in enumerate(PROXY_ENDPOINTS):
            key = ep["key"]
            label = ep.get("label", key)
            try:
                r = self._proxy(adom, device_name, ep["resource"])
            except Exception as exc:
                r = {
                    "rpc_code": -1,
                    "http_status": 500,
                    "payload": {},
                    "error": str(exc),
                }
            yield i + 1, total, label, key, r

    # ── CIS hardening data fetchers ───────────────────────────────────────────

    def get_device_admins(self, adom: str, device_name: str) -> list:
        """Return admin account list from the device via FMG proxy."""
        try:
            r = self._proxy(adom, device_name, "/api/v2/cmdb/system/admin?vdom=root")
            payload = r.get("payload", [])
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return list(payload.values())
            return []
        except Exception:
            return []

    def get_device_system_global(self, adom: str, device_name: str) -> dict:
        """Return system/global config from the device via FMG proxy."""
        try:
            r = self._proxy(adom, device_name, "/api/v2/cmdb/system/global?vdom=root")
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_password_policy(self, adom: str, device_name: str) -> dict:
        """Return system/password-policy config from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/cmdb/system/password-policy?vdom=root"
            )
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_log_disk(self, adom: str, device_name: str) -> dict:
        """Return log.disk/setting config from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/cmdb/log.disk/setting?vdom=root"
            )
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_log_faz(self, adom: str, device_name: str) -> dict:
        """Return log.fortianalyzer/setting config from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom,
                device_name,
                "/api/v2/cmdb/log.fortianalyzer/setting?vdom=root",
            )
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_dns(self, adom: str, device_name: str) -> dict:
        """Return system/dns config from the device via FMG proxy."""
        try:
            r = self._proxy(adom, device_name, "/api/v2/cmdb/system/dns?vdom=root")
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_snmp_community(self, adom: str, device_name: str) -> list:
        """Return SNMP community list (v1/v2c) from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/cmdb/system/snmp/community?vdom=root"
            )
            payload = r.get("payload", [])
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return list(payload.values())
            return []
        except Exception:
            return []

    def get_device_snmp_sysinfo(self, adom: str, device_name: str) -> dict:
        """Return SNMP system info (enabled flag) from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/cmdb/system/snmp/sysinfo?vdom=root"
            )
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}

    def get_device_snmp_users(self, adom: str, device_name: str) -> list:
        """Return SNMPv3 user list from the device via FMG proxy."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/cmdb/system/snmp/user?vdom=root"
            )
            payload = r.get("payload", [])
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return list(payload.values())
            return []
        except Exception:
            return []

    def get_device_ha_status(self, adom: str, device_name: str) -> dict:
        """Return HA status from the device via FMG proxy (monitor endpoint)."""
        try:
            r = self._proxy(
                adom, device_name, "/api/v2/monitor/system/ha-status?vdom=root"
            )
            payload = r.get("payload", {})
            if isinstance(payload, list) and payload:
                return payload[0] if isinstance(payload[0], dict) else {}
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception:
            return {}
