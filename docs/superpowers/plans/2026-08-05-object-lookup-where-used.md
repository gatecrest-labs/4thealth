# Object Lookup — "Where Used" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Where Used" button to each Object Lookup result row that opens a modal showing every group and policy rule (direct + indirect) that references that object within the ADOM.

**Architecture:** New `POST /api/hygiene/adoms/<adom>/objects/where-used` route in `hygiene_routes.py` performs a server-side scan of all packages/policies using existing FMG client methods. Frontend adds a 6th column button to `renderOlTable` and a new modal (`#olWhereUsedModal`) in `hygiene.html` wired via `openWhereUsed()` in `hygiene.js`.

**Tech Stack:** Python/Flask (backend), vanilla JS (frontend), Jinja2 templates, pytest with `unittest.mock`.

## Global Constraints

- No new FMG client methods — use `get_policy_packages()`, `get_policies()`, `get_address_groups()`, `get_service_groups()` only
- Global objects are excluded (ADOM-scoped only)
- Modal pattern: `class="modal-overlay hidden"` → `modal-dialog` → `modal-header` + `modal-body` (matches existing admin/firewalls modals)
- All route guards: `@tab_required("rule_hygiene")` + `check_adom_access(adom)`
- `category` must be `"address"` or `"service"` — reject anything else with 400
- Export functions (CSV/JSON/PDF) are unchanged — "Where Used" is interactive only
- Branch: `development`

---

## File Map

| File | Change |
|------|--------|
| `app/routes/hygiene_routes.py` | Add `hygiene_object_where_used()` after `hygiene_object_lookup()` |
| `app/templates/hygiene.html` | Add `#olWhereUsedModal` HTML; add 6th `<th>` to `#olTable` |
| `app/static/js/hygiene.js` | Add `openWhereUsed()`, modal wiring, 6th column in `renderOlTable` |
| `tests/test_hygiene_routes_lookup.py` | Add where-used tests |
| `app/static/js/help.js` | Update Object Lookup section description |
| `CHANGELOG.md` | Add entry under `[Unreleased] → Added` |
| `CLAUDE.md` | No changes needed — Object Lookup section already documented |

---

### Task 1: Backend route — `hygiene_object_where_used()`

**Files:**
- Modify: `app/routes/hygiene_routes.py` (after line ~785, after `hygiene_object_lookup`)
- Test: `tests/test_hygiene_routes_lookup.py`

**Interfaces:**
- Produces: `POST /api/hygiene/adoms/<adom>/objects/where-used`
- Request body: `{ "name": str, "category": "address" | "service" }`
- Response: `{ "name": str, "category": str, "groups": [{"name": str}], "rules": [{"package": str, "rule_id": str, "rule_name": str, "action": str, "via": str}], "packages_scanned": int }`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_hygiene_routes_lookup.py`:

```python
# ── Where Used ────────────────────────────────────────────────────────────────

def test_where_used_direct_address_match(client):
    packages = [{"name": "Corp-Policy", "obj ver": 0}]
    policies = [
        {"policyid": 42, "name": "permit-srv", "action": "accept",
         "srcaddr": [{"name": "HOST-10.1.1.1"}], "dstaddr": [{"name": "any"}], "service": []},
        {"policyid": 99, "name": "other-rule", "action": "accept",
         "srcaddr": [{"name": "other-obj"}], "dstaddr": [{"name": "any"}], "service": []},
    ]
    addr_groups = []
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_policy_packages.return_value = packages
        inst.get_policies.return_value = policies
        inst.get_address_groups.return_value = addr_groups
        resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                     {"name": "HOST-10.1.1.1", "category": "address"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "HOST-10.1.1.1"
    assert data["groups"] == []
    assert data["packages_scanned"] == 1
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_id"] == "42"
    assert data["rules"][0]["rule_name"] == "permit-srv"
    assert data["rules"][0]["via"] == "direct"
    assert data["rules"][0]["package"] == "Corp-Policy"


def test_where_used_indirect_via_group(client):
    packages = [{"name": "Corp-Policy", "obj ver": 0}]
    policies = [
        {"policyid": 55, "name": "block-out", "action": "deny",
         "srcaddr": [{"name": "SERVERS"}], "dstaddr": [{"name": "any"}], "service": []},
    ]
    addr_groups = [
        {"name": "SERVERS", "member": [{"name": "HOST-10.1.1.1"}, {"name": "HOST-10.1.1.2"}]},
        {"name": "OTHER-GROUP", "member": [{"name": "HOST-10.2.2.2"}]},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_policy_packages.return_value = packages
        inst.get_policies.return_value = policies
        inst.get_address_groups.return_value = addr_groups
        resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                     {"name": "HOST-10.1.1.1", "category": "address"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["groups"]) == 1
    assert data["groups"][0]["name"] == "SERVERS"
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_id"] == "55"
    assert data["rules"][0]["via"] == "SERVERS"


def test_where_used_not_referenced(client):
    packages = [{"name": "Corp-Policy", "obj ver": 0}]
    policies = [
        {"policyid": 1, "name": "some-rule", "action": "accept",
         "srcaddr": [{"name": "other-obj"}], "dstaddr": [{"name": "any"}], "service": []},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_policy_packages.return_value = packages
        inst.get_policies.return_value = policies
        inst.get_address_groups.return_value = []
        resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                     {"name": "UNUSED-OBJ", "category": "address"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["groups"] == []
    assert data["rules"] == []
    assert data["packages_scanned"] == 1


def test_where_used_service_category(client):
    packages = [{"name": "Corp-Policy", "obj ver": 0}]
    policies = [
        {"policyid": 10, "name": "web-rule", "action": "accept",
         "srcaddr": [{"name": "any"}], "dstaddr": [{"name": "any"}],
         "service": [{"name": "HTTPS-8443"}]},
    ]
    with patch("app.routes.hygiene_routes.make_client") as mc:
        inst = mc.return_value.__enter__.return_value
        inst.get_policy_packages.return_value = packages
        inst.get_policies.return_value = policies
        inst.get_service_groups.return_value = []
        resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                     {"name": "HTTPS-8443", "category": "service"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["rules"]) == 1
    assert data["rules"][0]["rule_id"] == "10"
    assert data["rules"][0]["via"] == "direct"


def test_where_used_missing_name_returns_400(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                 {"category": "address"})
    assert resp.status_code == 400


def test_where_used_invalid_category_returns_400(client):
    resp = _post(client, "/api/hygiene/adoms/TestADOM/objects/where-used",
                 {"name": "HOST-10.1.1.1", "category": "vip"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alan.k.wodarski/Library/CloudStorage/OneDrive-previousemployer/code/gitlab-sites/4thealth
uv run pytest tests/test_hygiene_routes_lookup.py -k "where_used" -v
```

Expected: all 6 tests FAIL with 404 (route does not exist yet).

- [ ] **Step 3: Implement the route**

Open `app/routes/hygiene_routes.py`. After the closing line of `hygiene_object_lookup` (around line 785), add:

```python
# ── API: object where-used ────────────────────────────────────────────────────


@bp.route("/api/hygiene/adoms/<adom>/objects/where-used", methods=["POST"])
@tab_required("rule_hygiene")
def hygiene_object_where_used(adom: str):
    """Find all groups and policy rules that reference a named object.

    Body: { "name": "OBJECT-NAME", "category": "address" | "service" }
    Returns: { name, category, groups, rules, packages_scanned }
    """
    if err := check_adom_access(adom):
        return err

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip().lower()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if category not in ("address", "service"):
        return jsonify({"error": "category must be 'address' or 'service'"}), 400

    try:
        with make_client() as client:
            packages = client.get_policy_packages(adom)
            if category == "address":
                groups_raw = client.get_address_groups(adom)
            else:
                groups_raw = client.get_service_groups(adom)

            # Find groups that directly contain this object
            containing_groups: list[str] = []
            for grp in groups_raw:
                if not isinstance(grp, dict):
                    continue
                members = grp.get("member") or []
                member_names = {
                    (m.get("name") if isinstance(m, dict) else str(m))
                    for m in members
                }
                if name in member_names:
                    containing_groups.append(grp.get("name", ""))

            # Scan all policies across all packages
            matched_rules: list[dict] = []
            packages_scanned = 0
            for pkg in packages:
                pkg_name = pkg.get("name", "")
                if not pkg_name:
                    continue
                try:
                    policies = client.get_policies(adom, pkg_name)
                except Exception:
                    continue
                packages_scanned += 1

                for pol in policies:
                    if not isinstance(pol, dict):
                        continue
                    pol_id = str(pol.get("policyid", ""))
                    pol_name = pol.get("name", "")
                    action = pol.get("action", "")

                    if category == "address":
                        fields = list(pol.get("srcaddr") or []) + list(pol.get("dstaddr") or [])
                    else:
                        fields = list(pol.get("service") or [])

                    field_names = {
                        (f.get("name") if isinstance(f, dict) else str(f))
                        for f in fields
                    }

                    # Direct reference
                    if name in field_names:
                        matched_rules.append({
                            "package":   pkg_name,
                            "rule_id":   pol_id,
                            "rule_name": pol_name,
                            "action":    action,
                            "via":       "direct",
                        })

                    # Indirect reference (via a containing group)
                    for grp_name in containing_groups:
                        if grp_name in field_names:
                            matched_rules.append({
                                "package":   pkg_name,
                                "rule_id":   pol_id,
                                "rule_name": pol_name,
                                "action":    action,
                                "via":       grp_name,
                            })

    except FMGError as exc:
        return upstream_api_error("hygiene", exc)
    except Exception as exc:
        return internal_api_error("hygiene", exc)

    return jsonify({
        "name":             name,
        "category":         category,
        "groups":           [{"name": g} for g in containing_groups if g],
        "rules":            matched_rules,
        "packages_scanned": packages_scanned,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_hygiene_routes_lookup.py -k "where_used" -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full lookup test suite to check for regressions**

```bash
uv run pytest tests/test_hygiene_routes_lookup.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routes/hygiene_routes.py tests/test_hygiene_routes_lookup.py
git commit -m "feat: add where-used API endpoint for object lookup"
```

---

### Task 2: Modal HTML in `hygiene.html`

**Files:**
- Modify: `app/templates/hygiene.html` (add modal after line ~179, and add 6th `<th>`)

**Interfaces:**
- Consumes: existing modal CSS classes (`modal-overlay hidden`, `modal-dialog`, `modal-header`, `modal-body`, `modal-close`)
- Produces: `#olWhereUsedModal`, `#olWhereUsedTitle`, `#olWhereUsedBody`, `#olWhereUsedClose` — consumed by Task 3

- [ ] **Step 1: Add the 6th `<th>` to `#olTable` header**

In `hygiene.html`, find the `<thead>` block inside `#olTable` (around line 164–171):
```html
      <thead>
        <tr>
          <th style="width:3.5rem">#</th>
          <th>Name</th>
          <th style="width:7rem">Type</th>
          <th style="width:7rem">Category</th>
          <th>Detail / Members</th>
        </tr>
      </thead>
```

Replace it with:
```html
      <thead>
        <tr>
          <th style="width:3.5rem">#</th>
          <th>Name</th>
          <th style="width:7rem">Type</th>
          <th style="width:7rem">Category</th>
          <th>Detail / Members</th>
          <th style="width:7.5rem"></th>
        </tr>
      </thead>
```

- [ ] **Step 2: Add `#olWhereUsedModal` after the `#olError` div**

Find this line in `hygiene.html` (around line 179):
```html
<div id="olError" class="alert alert-danger" style="display:none"></div>
```

Insert the modal immediately after it:
```html
<!-- Where Used Modal -->
<div class="modal-overlay hidden" id="olWhereUsedModal" role="dialog" aria-modal="true">
  <div class="modal-dialog" style="max-width:780px">
    <div class="modal-header">
      <span id="olWhereUsedTitle">Where Used</span>
      <button class="modal-close" id="olWhereUsedClose" aria-label="Close">&times;</button>
    </div>
    <div class="modal-body" id="olWhereUsedBody">
      <div id="olWhereUsedSpinner" style="text-align:center;padding:2rem">
        <span class="spinner"></span> Loading…
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Verify template renders without error**

```bash
uv run python -c "
from app import create_app
app = create_app()
with app.test_request_context():
    from flask import render_template
    html = render_template('hygiene.html',
        allowed_tabs=['rule_hygiene'],
        username='test',
        role='admin',
        CHECK_DEFS=[],
        csrf_token='x')
    assert 'olWhereUsedModal' in html
    assert 'olWhereUsedClose' in html
    print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add app/templates/hygiene.html
git commit -m "feat: add where-used modal HTML to object lookup table"
```

---

### Task 3: Frontend JS — button + modal logic in `hygiene.js`

**Files:**
- Modify: `app/static/js/hygiene.js`

**Interfaces:**
- Consumes: `#olWhereUsedModal`, `#olWhereUsedTitle`, `#olWhereUsedBody`, `#olWhereUsedClose` (from Task 2); `olMeta` state variable; `esc()` helper
- Produces: `openWhereUsed(name, category, adom)` — called inline from rendered table rows

- [ ] **Step 1: Add the `openWhereUsed` function**

Find the `/* ── Object Lookup exports ──` comment block (around line 1082). Insert the new function **before** it:

```javascript
/* ── Object Lookup — Where Used ─────────────────────────────────────────────── */
async function openWhereUsed(name, category, adom) {
  const modal = document.getElementById('olWhereUsedModal');
  const title = document.getElementById('olWhereUsedTitle');
  const body  = document.getElementById('olWhereUsedBody');

  const catLabel = category === 'service' ? 'Service' : 'Address';
  title.innerHTML = `Where Used &mdash; <strong>${esc(name)}</strong> <span class="obj-type-badge obj-type-${category === 'service' ? 'svc' : 'object'}">${esc(catLabel)}</span>`;
  body.innerHTML  = `<div style="text-align:center;padding:2rem"><span class="spinner"></span> Loading&hellip;</div>`;
  modal.classList.remove('hidden');

  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/objects/where-used`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name, category }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      body.innerHTML = `<div class="alert alert-danger">${esc(data.error || 'Request failed.')}</div>`;
      return;
    }

    // Groups section
    let groupsHtml;
    if (data.groups && data.groups.length) {
      const rows = data.groups.map(g => `<tr><td><strong>${esc(g.name)}</strong></td><td>${esc(category === 'service' ? 'SVC Group' : 'Addr Group')}</td></tr>`).join('');
      groupsHtml = `<table class="data-table" style="margin-bottom:1.5rem">
        <thead><tr><th>Group Name</th><th style="width:9rem">Type</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    } else {
      groupsHtml = `<p class="text-muted" style="font-size:.85rem">Not a member of any group.</p>`;
    }

    // Rules section
    let rulesHtml;
    if (data.rules && data.rules.length) {
      const rows = data.rules.map(r => {
        const actionClass = (r.action || '').toLowerCase() === 'deny' ? 'badge-red' : 'badge-green';
        const actionLabel = (r.action || '').toUpperCase() || '—';
        const viaHtml = r.via === 'direct'
          ? `<span style="color:var(--text-muted);font-size:.8rem">direct</span>`
          : `<span class="obj-type-badge obj-type-group" style="font-size:.75rem">${esc(r.via)}</span>`;
        return `<tr>
          <td style="font-size:.82rem">${esc(r.package)}</td>
          <td style="font-size:.82rem;color:var(--text-muted)">${esc(r.rule_id)}</td>
          <td>${esc(r.rule_name || '—')}</td>
          <td><span class="status-badge ${actionClass}">${esc(actionLabel)}</span></td>
          <td>${viaHtml}</td>
        </tr>`;
      }).join('');
      rulesHtml = `<table class="data-table">
        <thead><tr><th>Package</th><th style="width:4rem">ID</th><th>Rule Name</th><th style="width:6rem">Action</th><th style="width:8rem">Via</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    } else {
      rulesHtml = `<p class="text-muted" style="font-size:.85rem">Not referenced in any policy rule.</p>`;
    }

    const scanned = data.packages_scanned != null ? data.packages_scanned : '?';
    body.innerHTML = `
      <h4 style="margin:0 0 .5rem;font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)">Used in Groups</h4>
      ${groupsHtml}
      <h4 style="margin:0 0 .5rem;font-size:.9rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)">Used in Policy Rules</h4>
      ${rulesHtml}
      <p style="margin-top:1rem;font-size:.78rem;color:var(--text-muted)">${scanned} package${scanned !== 1 ? 's' : ''} scanned</p>`;
  } catch (err) {
    body.innerHTML = `<div class="alert alert-danger">${esc(err.message)}</div>`;
  }
}
```

- [ ] **Step 2: Add modal close wiring**

Find the `/* ── Object Lookup events ───` section (around line 1794). Add after the existing `olExportPdf` listener:

```javascript
/* ── Where Used modal close ─────────────────────────────────────────────────── */
document.getElementById('olWhereUsedClose').addEventListener('click', () => {
  document.getElementById('olWhereUsedModal').classList.add('hidden');
});
document.getElementById('olWhereUsedModal').addEventListener('click', e => {
  if (e.target === e.currentTarget) e.currentTarget.classList.add('hidden');
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('olWhereUsedModal').classList.add('hidden');
});
```

- [ ] **Step 3: Add the 6th column button to `renderOlTable`**

Find the `return` template literal inside `renderOlTable` (around line 1055):
```javascript
    return `<tr>
      <td style="font-size:.8rem;color:var(--text-muted)">${globalIdx}</td>
      <td><strong>${esc(o.name)}</strong></td>
      <td>${typeBadge}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(catLabel)}</td>
      <td style="font-size:.8rem">${detailHtml}</td>
    </tr>`;
```

Replace with:
```javascript
    const adom = (olMeta || {}).adom || '';
    return `<tr>
      <td style="font-size:.8rem;color:var(--text-muted)">${globalIdx}</td>
      <td><strong>${esc(o.name)}</strong></td>
      <td>${typeBadge}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(catLabel)}</td>
      <td style="font-size:.8rem">${detailHtml}</td>
      <td style="text-align:right"><button class="btn btn-sm btn-secondary" onclick="openWhereUsed(${JSON.stringify(o.name)},${JSON.stringify(o.category)},${JSON.stringify(adom)})">Where Used</button></td>
    </tr>`;
```

- [ ] **Step 4: Update the empty-state colspan from 5 to 6**

Find (around line 1062):
```javascript
  }).join('') || `<tr><td colspan="5" class="empty-state" style="padding:.85rem 1rem">No objects match your filter.</td></tr>`;
```

Replace with:
```javascript
  }).join('') || `<tr><td colspan="6" class="empty-state" style="padding:.85rem 1rem">No objects match your filter.</td></tr>`;
```

- [ ] **Step 5: Verify JS has no syntax errors**

```bash
node --check /Users/alan.k.wodarski/Library/CloudStorage/OneDrive-previousemployer/code/gitlab-sites/4thealth/app/static/js/hygiene.js
```

Expected: no output (exit 0).

- [ ] **Step 6: Commit**

```bash
git add app/static/js/hygiene.js
git commit -m "feat: add where-used button and modal to object lookup results"
```

---

### Task 4: Documentation updates

**Files:**
- Modify: `app/static/js/help.js` (update Object Lookup section)
- Modify: `CHANGELOG.md` (add Unreleased entry)

- [ ] **Step 1: Update `help.js` Object Lookup description**

Find this block in `app/static/js/help.js` (around line 149–150):
```html
<h3>Object Lookup</h3>
<p>Search for address objects, address groups, service objects, and service groups by name across the selected ADOM. Partial name matching supported. Group members are shown inline with their subnet or port details.</p>
```

Replace with:
```html
<h3>Object Lookup</h3>
<p>Search for address objects, address groups, service objects, and service groups by name across the selected ADOM. Partial name matching supported. Group members are shown inline with their subnet or port details.</p>
<ul>
  <li><strong>Where Used</strong> — click the button on any result row to see which groups contain that object, and which policy rules (across all packages in the ADOM) reference it — directly by name or indirectly through a group. The <em>Via</em> column shows <em>direct</em> or the group name for indirect matches.</li>
  <li><strong>Exports</strong> — CSV, JSON, and PDF of the search results.</li>
</ul>
```

- [ ] **Step 2: Add CHANGELOG entry**

Find the `### Added` section under `## [Unreleased]` in `CHANGELOG.md`. Add this as the first bullet:

```markdown
- **Object Lookup — Where Used:** Each object lookup result now has a **Where Used** button that opens a modal showing every address/service group that contains the object, and every policy rule across all packages in the ADOM that references it — directly by name or indirectly through a group. The modal's *Via* column identifies direct references vs. the specific group name for indirect ones.
```

- [ ] **Step 3: Commit**

```bash
git add app/static/js/help.js CHANGELOG.md
git commit -m "docs: update help text and changelog for where-used feature"
```

---

### Task 5: Update graphify knowledge graph

**Files:** None (graphify reads the source tree)

- [ ] **Step 1: Run graphify update**

```bash
cd /Users/alan.k.wodarski/Library/CloudStorage/OneDrive-previousemployer/code/gitlab-sites/4thealth
graphify update .
```

Expected: graph updates without errors, new node for `hygiene_object_where_used()` visible.

- [ ] **Step 2: Commit the updated graph**

```bash
git add graphify-out/
git commit -m "chore: update graphify graph for where-used feature"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Backend route ✓ | Groups scan ✓ | Direct rule scan ✓ | Indirect rule scan ✓ | Modal HTML ✓ | Button in table ✓ | 6th `<th>` + colspan update ✓ | help.js ✓ | CHANGELOG ✓ | graphify ✓ | CLAUDE.md — no changes needed (Object Lookup already documented; route conventions already documented)
- [x] **No placeholders:** All steps have concrete code
- [x] **Type consistency:** `openWhereUsed(name, category, adom)` defined in Task 3 Step 1, called in Task 3 Step 3 with matching signature; `#olWhereUsedModal`/`#olWhereUsedClose`/`#olWhereUsedBody`/`#olWhereUsedTitle` defined in Task 2, consumed in Task 3
- [x] **Global exclusion:** Only `get_address_groups(adom)` / `get_service_groups(adom)` called — no global variants
- [x] **category validation:** 400 returned for anything other than `"address"` / `"service"`
