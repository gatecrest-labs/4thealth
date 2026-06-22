"""Diagnostic script — query FMG directly and dump a specific policy's raw fields.

Usage:
    python debug_policy.py                        # shows policy 110198
    python debug_policy.py 110198 110199 110200   # shows multiple policy IDs
    python debug_policy.py --all-blank            # shows every policy with empty srcaddr/dstaddr/service
"""

import os
import sys
import warnings

import requests
import urllib3
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

# ── Config from .env ──────────────────────────────────────────────────────────

load_dotenv()

HOST       = os.environ["FMG_PRIMARY_HOST"]
TOKEN      = os.environ.get("FMG_API_TOKEN", "")
USERNAME   = os.environ.get("FMG_USERNAME", "")
PASSWORD   = os.environ.get("FMG_PASSWORD", "")
VERIFY_SSL = os.environ.get("FMG_VERIFY_SSL", "false").lower() == "true"

ADOM    = "ENTERPRISE-SERVICES"
PKG     = "PRODUCTION/Perimeter/Extranet/COLOCXFWEXEX01"
BASE    = f"https://{HOST}/jsonrpc"

TARGET_IDS = {110198}  # default — override via CLI args

# ── Parse CLI args ────────────────────────────────────────────────────────────

show_all_blank    = "--all-blank" in sys.argv
list_packages     = "--list-pkgs" in sys.argv
list_adoms        = "--list-adoms" in sys.argv
list_global_pkgs  = "--list-global-pkgs" in sys.argv
if not show_all_blank and not list_packages and not list_adoms and not list_global_pkgs:
    ids_from_args = [a for a in sys.argv[1:] if a.isdigit()]
    if ids_from_args:
        TARGET_IDS = set(int(x) for x in ids_from_args)

# ── FMG helpers ───────────────────────────────────────────────────────────────

session = None
req_id  = 0

def _next_id():
    global req_id
    req_id += 1
    return req_id

def _post(body):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    r = requests.post(BASE, json=body, verify=VERIFY_SSL, timeout=30, headers=headers)
    r.raise_for_status()
    return r.json()

def login():
    global session
    if TOKEN:
        return
    data = _post({"id": _next_id(), "method": "exec",
                  "params": [{"url": "/sys/login/user",
                               "data": {"user": USERNAME, "passwd": PASSWORD}}]})
    result = data.get("result", [{}])[0]
    if result.get("status", {}).get("code", -1) != 0:
        raise SystemExit(f"Login failed: {result.get('status')}")
    session = data["session"]

def logout():
    if TOKEN or not session:
        return
    try:
        _post({"id": _next_id(), "method": "exec", "session": session,
               "params": [{"url": "/sys/logout"}]})
    except Exception:
        pass

def fmg_get(url):
    body = {"id": _next_id(), "method": "get", "params": [{"url": url}]}
    if session:
        body["session"] = session
    data = _post(body)
    result = data.get("result", [{}])[0]
    if result.get("status", {}).get("code", -1) != 0:
        raise SystemExit(f"FMG error on {url}: {result.get('status')}")
    return result.get("data", [])

def get_packages():
    body = {"id": _next_id(), "method": "get",
            "params": [{"url": f"/pm/pkg/adom/{ADOM}"}]}
    if session:
        body["session"] = session
    data = _post(body)
    result = data.get("result", [{}])[0]
    if result.get("status", {}).get("code", -1) != 0:
        raise SystemExit(f"FMG error listing packages: {result.get('status')}")
    items = result.get("data", [])

    def _flatten(items, prefix=""):
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            pkg_type = (item.get("type") or "").lower()
            if pkg_type == "folder":
                sub = item.get("subobj") or []
                out.extend(_flatten(sub, f"{prefix}{name}/"))
            else:
                out.append(f"{prefix}{name}")
        return out

    return _flatten(items)

def get_policies():
    url = f"/pm/config/adom/{ADOM}/pkg/{PKG}/firewall/policy"
    all_policies = []
    offset, page_size = 0, 1000
    while True:
        body = {"id": _next_id(), "method": "get",
                "params": [{"url": url, "range": [offset, page_size]}]}
        if session:
            body["session"] = session
        data = _post(body)
        result = data.get("result", [{}])[0]
        if result.get("status", {}).get("code", -1) != 0:
            raise SystemExit(f"FMG error fetching policies: {result.get('status')}")
        page = result.get("data", [])
        if not isinstance(page, list):
            break
        all_policies.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return all_policies

# ── Main ──────────────────────────────────────────────────────────────────────

def _names(val):
    if not val:
        return []
    if isinstance(val, str):
        return [val]
    return [(i.get("name", str(i)) if isinstance(i, dict) else str(i)) for i in val]

def print_policy(p):
    pid = p.get("policyid")
    print(f"\n{'='*60}")
    print(f"  Policy ID   : {pid}")
    print(f"  Name        : {p.get('name') or '(none)'}")
    print(f"  Status      : {p.get('status')}")
    print(f"  Action      : {p.get('action')}")
    print(f"  _policy_block: {p.get('_policy_block') or '(not set)'}")
    print(f"  type        : {p.get('type')}")
    print(f"  srcaddr     : {_names(p.get('srcaddr') or p.get('src_addr'))}")
    print(f"  dstaddr     : {_names(p.get('dstaddr') or p.get('dst_addr'))}")
    print(f"  service     : {_names(p.get('service') or p.get('services'))}")
    print(f"  srcintf     : {_names(p.get('srcintf'))}")
    print(f"  dstintf     : {_names(p.get('dstintf'))}")
    print(f"  fsso-groups : {_names(p.get('fsso-groups'))}")
    print(f"  groups      : {_names(p.get('groups'))}")
    print(f"  users       : {_names(p.get('users'))}")
    print(f"  comments    : {p.get('comments') or p.get('comment') or '(none)'}")
    print()
    print("  --- RAW KEYS ---")
    for k, v in sorted(p.items()):
        if k not in ("srcaddr","dstaddr","service","srcintf","dstintf",
                     "fsso-groups","groups","users","name","status","action",
                     "policyid","comments","comment","_policy_block","type"):
            print(f"  {k}: {v}")
    print(f"{'='*60}")

login()
try:
    if list_adoms:
        data = fmg_get("/dvmdb/adom")
        adoms = [a.get("name") for a in data if isinstance(a, dict) and a.get("name")]
        print("ADOMs on FMG:")
        for a in sorted(adoms):
            print(f"  {a}")
        sys.exit(0)

    if list_packages:
        print(f"Policy packages in ADOM={ADOM}:")
        for p in get_packages():
            print(f"  {p}")
        sys.exit(0)

    if list_global_pkgs:
        body = {"id": _next_id(), "method": "get",
                "params": [{"url": "/pm/pkg/global"}]}
        if session:
            body["session"] = session
        data = _post(body)
        result = data.get("result", [{}])[0]
        items = result.get("data", []) or []

        def _flatten_global(items, prefix=""):
            out = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "")
                pkg_type = (item.get("type") or "").lower()
                if pkg_type == "folder":
                    sub = item.get("subobj") or []
                    out.extend(_flatten_global(sub, f"{prefix}{name}/"))
                else:
                    out.append(f"{prefix}{name}")
            return out

        print("Global policy packages on FMG:")
        for p in _flatten_global(items):
            print(f"  {p}")
        sys.exit(0)

    print(f"Fetching policies from ADOM={ADOM}, PKG={PKG} ...")
    policies = get_policies()
    print(f"Total policies fetched: {len(policies)}")

    found = 0
    for p in policies:
        if not isinstance(p, dict):
            continue

        pid = p.get("policyid")

        if show_all_blank:
            src = _names(p.get("srcaddr") or p.get("src_addr"))
            dst = _names(p.get("dstaddr") or p.get("dst_addr"))
            svc = _names(p.get("service") or p.get("services"))
            if not src and not dst and not svc:
                print_policy(p)
                found += 1
        else:
            if pid in TARGET_IDS:
                print_policy(p)
                found += 1

    if found == 0:
        if show_all_blank:
            print("No policies with all-empty src/dst/service found.")
        else:
            print(f"Policy IDs {TARGET_IDS} not found in package.")
finally:
    logout()
