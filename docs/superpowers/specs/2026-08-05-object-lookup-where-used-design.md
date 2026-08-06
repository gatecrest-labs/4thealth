# Object Lookup — "Where Used" Feature Design

**Date:** 2026-08-05
**Tab:** Rule Review → Object Lookup section
**Scope:** ADOM-scoped only (global objects excluded)

---

## Summary

Add a **"Where Used"** button to each row in the Object Lookup results table. Clicking it queries the backend for every group and policy rule in the ADOM that references that object — directly or indirectly through a group. Results are displayed in a modal within the page.

---

## Backend

### New endpoint

```
POST /api/hygiene/adoms/<adom>/objects/where-used
```

**Auth:** `@tab_required("rule_hygiene")` + `check_adom_access(adom)`

**Request body:**
```json
{ "name": "HOST-10.1.1.1", "category": "address" }
```

`category` is `"address"` or `"service"`.

**Logic:**
1. Fetch all policy packages in the ADOM (`get_policy_packages`).
2. For each package, fetch all policies (`get_policies`).
3. Depending on `category`:
   - `address`: scan each policy's `srcaddr` and `dstaddr` field lists for the object name
   - `service`: scan each policy's `service` field list for the object name
4. Record direct matches as `via: "direct"`.
5. Fetch all address groups or service groups (matching `category`). Find every group whose `member` list contains the object name — these are the **containing groups**.
6. For each containing group, scan all policies again for that group name in the same fields. Record matches as `via: "<group-name>"`.
7. Deduplicate: if a rule is matched both directly and via a group, keep both entries (different `via` values convey different information).

**Response shape:**
```json
{
  "name": "HOST-10.1.1.1",
  "category": "address",
  "groups": [
    { "name": "SERVERS" },
    { "name": "CORP-HOSTS" }
  ],
  "rules": [
    {
      "package": "Corp-Policy",
      "rule_id": "42",
      "rule_name": "permit-servers-web",
      "action": "accept",
      "via": "direct"
    },
    {
      "package": "Corp-Policy",
      "rule_id": "55",
      "rule_name": "block-outbound",
      "action": "deny",
      "via": "SERVERS"
    }
  ],
  "packages_scanned": 3
}
```

**Implementation location:** `app/routes/hygiene_routes.py` — new route function `hygiene_object_where_used()` added after `hygiene_object_lookup()`.

**No new FMG client methods required** — all data is available via existing `get_policy_packages()`, `get_policies()`, `get_address_groups()`, and `get_service_groups()`.

**Performance note:** For large ADOMs with many packages, this may take several seconds. The frontend shows a spinner and disables the button while loading.

---

## Frontend

### "Where Used" button

A new 6th column is added to the `renderOlTable` function in `hygiene.js`. Each row gets a small secondary button:

```html
<button class="btn btn-sm btn-secondary" onclick="openWhereUsed(...)">Where Used</button>
```

The button passes `name`, `category`, and `adom` (from `olMeta`) to `openWhereUsed()`.

### `openWhereUsed(name, category, adom)` function

1. Opens the modal immediately with a spinner.
2. POSTs to `/api/hygiene/adoms/<adom>/objects/where-used`.
3. On success, renders the two result sections.
4. On error, shows an inline error message inside the modal.

### Modal layout

Reuses existing modal CSS classes from the page (`modal-overlay`, `modal-box`, etc.).

```
┌─────────────────────────────────────────────────────┐
│ Where Used — HOST-10.1.1.1   [Address]          [×] │
├─────────────────────────────────────────────────────┤
│ Used in Groups                                       │
│  ┌─────────────┬───────────────┐                    │
│  │ Group Name  │ Type          │                    │
│  │ SERVERS     │ Addr Group    │                    │
│  │ CORP-HOSTS  │ Addr Group    │                    │
│  └─────────────┴───────────────┘                    │
│  (or: "Not a member of any group.")                 │
│                                                      │
│ Used in Policy Rules                                 │
│  ┌──────────────┬────┬──────────────┬────────┬─────┐│
│  │ Package      │ ID │ Rule Name    │ Action │ Via ││
│  │ Corp-Policy  │ 42 │ permit-srv   │ ACCEPT │direct│
│  │ Corp-Policy  │ 55 │ block-out    │ DENY   │SRVRS││
│  └──────────────┴────┴──────────────┴────────┴─────┘│
│  (or: "Not referenced in any policy rule.")         │
│                                                      │
│  3 packages scanned                    [Close]      │
└─────────────────────────────────────────────────────┘
```

- Action column uses existing badge classes: green `ACCEPT`, red `DENY`
- `Via` shows `"direct"` in muted text, or a group name in a subtle badge
- Modal ID: `#olWhereUsedModal`
- Modal HTML added to `hygiene.html`

### Table column update

Current `olTbody` has 5 columns: `#`, Name, Type, Category, Detail/Members.
After change: 6 columns — same 5 plus **Where Used** (right-aligned, fixed-width).

The `colspan="5"` empty state in `renderOlTable` updates to `colspan="6"`.

Export functions (CSV, JSON, PDF) are **not changed** — the "Where Used" action is interactive only and not part of static exports.

---

## Files Changed

| File | Change |
|------|--------|
| `app/routes/hygiene_routes.py` | Add `hygiene_object_where_used()` route |
| `app/static/js/hygiene.js` | Add 6th column to `renderOlTable`; add `openWhereUsed()` function and modal wiring |
| `app/templates/hygiene.html` | Add `#olWhereUsedModal` HTML |

No changes to `fmg_client.py`, `hygiene.py`, or any other file.

---

## Out of Scope

- Global object references (explicitly excluded)
- VIP and IP pool objects (not in current Object Lookup results)
- Exporting "where used" results
- Deep-linking to the matching policy rule in the Policy Rules section
