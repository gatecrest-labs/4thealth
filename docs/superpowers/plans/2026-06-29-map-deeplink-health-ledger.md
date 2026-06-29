# Map Deep-link to Firewalls + Health Status Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "View Details →" link in map device popups that deep-links to the Firewalls tab with the device pre-selected, and add a fixed health status ledger overlay on the map page.

**Architecture:** Pure frontend changes across three JS files, one HTML template, and one CSS file. The deep-link uses a URL query param (`/firewalls?device=NAME&adom=ADOM`) read by `firewalls.js` on page load. The health ledger is a fixed-position `<div>` updated once when map data loads, counting device statuses from the in-memory `allDevices` array.

**Tech Stack:** Vanilla JS (ES6), Jinja2 templates, CSS custom properties (`var(--surface)` etc.), Leaflet.js popups (HTML string injection), Flask session/`allowed_tabs` context variable.

## Global Constraints

- No backend Python changes — all changes are frontend only.
- Existing CSS custom properties (`var(--surface)`, `var(--border)`, `var(--text)`, `var(--text-muted)`) must be used for theming so dark mode works automatically.
- Use `.status-dot` CSS class (not `.map-popup-dot`) for colored dots — `.map-popup-dot` only has `green` and `offline` variants; `.status-dot` has all four (`green`, `yellow`, `red`, `offline`).
- The "View Details →" link must be hidden entirely (not grayed out) for users without `firewalls` in `allowed_tabs`.
- The deep-link must clean the URL with `history.replaceState()` immediately after reading params so a page refresh doesn't re-trigger the auto-open.
- All user-provided values rendered into HTML must go through the existing `esc()` / `escHtml()` helper in the respective file.
- `encodeURIComponent()` must wrap both `device.name` and `device.adom` in the popup link `href`.

---

## File Map

| File | What changes |
|---|---|
| `app/templates/map.html` | Add `window._canSeeFirewalls` script block; add `#mapHealthLedger` div |
| `app/static/js/map.js` | `makeMarker()` — conditional Details link in popup; new `updateHealthLedger()` function called from `loadDevices()` |
| `app/static/js/firewalls.js` | New `checkDeepLink()` async function; call it from the init block |
| `app/static/css/style.css` | Add `.map-health-ledger` and `.ledger-item` CSS rules; add `.map-popup-footer` and `.map-popup-details-link` rules |
| `app/static/js/help.js` | Add "Device Details" and "Health Status Ledger" subsections to the Map section; add Map cross-reference note to Firewalls section |
| `CLAUDE.md` | Update Map section with `window._canSeeFirewalls`, deep-link URL pattern, `updateHealthLedger()`, new CSS classes |

---

## Task 1: CSS — Add map popup footer and health ledger styles

**Files:**
- Modify: `app/static/css/style.css` (after the `.map-popup-adom-dot` block, around line 2285)

**Interfaces:**
- Produces: `.map-popup-footer`, `.map-popup-details-link`, `.map-health-ledger`, `.ledger-item` — used by Tasks 2 and 3

- [ ] **Step 1: Locate the insertion point**

Open `app/static/css/style.css`. Find the `.map-popup-adom-dot` block (around line 2279). The new CSS goes directly after it, before `.leaflet-popup-content-wrapper`.

- [ ] **Step 2: Insert the new CSS rules**

Add the following block after `.map-popup-adom-dot { ... }`:

```css
.map-popup-footer {
  margin-top: .55rem;
  padding-top: .45rem;
  border-top: 1px solid var(--border);
  text-align: right;
}
.map-popup-details-link {
  font-size: .78rem;
  font-weight: 600;
  color: var(--accent, #2563eb);
  text-decoration: none;
}
.map-popup-details-link:hover {
  text-decoration: underline;
}

/* ── Map health ledger (fixed overlay, bottom-right) ─────────────────── */
.map-health-ledger {
  position: fixed;
  bottom: 1.5rem;
  right: 1rem;
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 12px;
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: .8rem;
  font-weight: 600;
  color: var(--text);
  box-shadow: 0 2px 8px rgba(0,0,0,.15);
}
.ledger-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
```

- [ ] **Step 3: Verify no syntax errors**

```bash
grep -n 'map-popup-footer\|map-popup-details-link\|map-health-ledger\|ledger-item' app/static/css/style.css
```

Expected: 4 matches (one for each class definition line).

- [ ] **Step 4: Commit**

```bash
git add app/static/css/style.css
git commit -m "style: add map popup footer and health ledger CSS"
```

---

## Task 2: Map template — inject permission flag and ledger element

**Files:**
- Modify: `app/templates/map.html`

**Interfaces:**
- Consumes: `allowed_tabs` Jinja2 context variable (always present — injected by `app/__init__.py` context processor for all logged-in pages)
- Produces:
  - `window._canSeeFirewalls` (boolean) — consumed by `map.js` in Task 3
  - `#mapHealthLedger` DOM element — consumed by `map.js` in Task 3

- [ ] **Step 1: Add the permission flag script block**

In `app/templates/map.html`, the `{% block scripts %}` currently starts with:

```html
{% block scripts %}
<script src="{{ url_for('static', filename='vendor/leaflet/leaflet.js') }}?v=1.9.4"></script>
<script src="{{ url_for('static', filename='vendor/markercluster/leaflet.markercluster.js') }}?v=1.5.3"></script>
<script>window._isAdmin = {{ (current_role == 'admin') | tojson }};</script>
<script src="{{ url_for('static', filename='js/map.js') }}?v=3"></script>
{% endblock %}
```

Change it to:

```html
{% block scripts %}
<script src="{{ url_for('static', filename='vendor/leaflet/leaflet.js') }}?v=1.9.4"></script>
<script src="{{ url_for('static', filename='vendor/markercluster/leaflet.markercluster.js') }}?v=1.5.3"></script>
<script>
  window._isAdmin = {{ (current_role == 'admin') | tojson }};
  window._canSeeFirewalls = {{ ('firewalls' in allowed_tabs) | tojson }};
</script>
<script src="{{ url_for('static', filename='js/map.js') }}?v=4"></script>
{% endblock %}
```

Note the version bump on `map.js` from `v=3` to `v=4` to bust the browser cache.

- [ ] **Step 2: Add the health ledger div**

In `app/templates/map.html`, find the `<!-- Map container -->` comment block:

```html
<!-- Map container -->
<div id="mapContainer" class="map-container">
```

Add the ledger div directly before it:

```html
<!-- Health status ledger (fixed overlay) -->
<div id="mapHealthLedger" class="map-health-ledger" style="display:none"></div>

<!-- Map container -->
<div id="mapContainer" class="map-container">
```

- [ ] **Step 3: Verify the template**

```bash
grep -n '_canSeeFirewalls\|mapHealthLedger' app/templates/map.html
```

Expected output:
```
N:  window._canSeeFirewalls = ...
N:  <div id="mapHealthLedger" ...
```

- [ ] **Step 4: Commit**

```bash
git add app/templates/map.html
git commit -m "feat: inject canSeeFirewalls flag and health ledger element in map template"
```

---

## Task 3: map.js — Details link in popup + health ledger update

**Files:**
- Modify: `app/static/js/map.js`

**Interfaces:**
- Consumes: `window._canSeeFirewalls` (boolean, from Task 2); `allDevices` array (module-scope, each element has `.name`, `.adom`, `.status`); `#mapHealthLedger` DOM element (from Task 2); existing `esc()` helper (line 113)
- Produces: nothing consumed by other tasks

- [ ] **Step 1: Add the Details link to makeMarker()**

In `map.js`, find `makeMarker()` (line 167). The function currently ends with:

```js
  marker.bindPopup(`
<div class="map-popup">
  <div class="map-popup-name">${statusDot}${esc(device.name)}</div>
  <table class="map-popup-table">
    <tr><th>Region</th><td><span class="map-popup-adom-dot" style="background:${esc(color)}"></span>${esc(regionLabel)}</td></tr>
    <tr><th>ADOM</th><td>${esc(device.adom)}</td></tr>
    <tr><th>Platform</th><td>${esc(device.platform)}</td></tr>
    <tr><th>Version</th><td>${esc(device.version)}</td></tr>
    ${device.desc ? `<tr><th>Desc</th><td>${esc(device.desc)}</td></tr>` : ''}
    <tr><th>Status</th><td>${esc(device.status)}</td></tr>
    <tr><th>Coords</th><td>${device.lat.toFixed(5)}, ${device.lon.toFixed(5)}</td></tr>
  </table>
</div>`, { maxWidth: 300 });
```

Replace it with:

```js
  const detailsLink = window._canSeeFirewalls
    ? `<div class="map-popup-footer">
         <a href="/firewalls?device=${encodeURIComponent(device.name)}&adom=${encodeURIComponent(device.adom)}"
            class="map-popup-details-link">View Details &#x2192;</a>
       </div>`
    : '';

  marker.bindPopup(`
<div class="map-popup">
  <div class="map-popup-name">${statusDot}${esc(device.name)}</div>
  <table class="map-popup-table">
    <tr><th>Region</th><td><span class="map-popup-adom-dot" style="background:${esc(color)}"></span>${esc(regionLabel)}</td></tr>
    <tr><th>ADOM</th><td>${esc(device.adom)}</td></tr>
    <tr><th>Platform</th><td>${esc(device.platform)}</td></tr>
    <tr><th>Version</th><td>${esc(device.version)}</td></tr>
    ${device.desc ? `<tr><th>Desc</th><td>${esc(device.desc)}</td></tr>` : ''}
    <tr><th>Status</th><td>${esc(device.status)}</td></tr>
    <tr><th>Coords</th><td>${device.lat.toFixed(5)}, ${device.lon.toFixed(5)}</td></tr>
  </table>
  ${detailsLink}
</div>`, { maxWidth: 300 });
```

- [ ] **Step 2: Add the updateHealthLedger() function**

Add this function immediately after the `renderMarkers()` function (around line 215 currently):

```js
// ── Health ledger ────────────────────────────────────────────────────────────

function updateHealthLedger() {
  const el = document.getElementById('mapHealthLedger');
  if (!el || !allDevices.length) return;
  const counts = { green: 0, yellow: 0, red: 0, offline: 0 };
  allDevices.forEach(d => {
    const s = d.status || 'offline';
    if (Object.prototype.hasOwnProperty.call(counts, s)) counts[s]++;
    else counts.offline++;
  });
  el.innerHTML =
    `<span class="ledger-item"><span class="status-dot green"></span>${counts.green}</span>` +
    `<span class="ledger-item"><span class="status-dot yellow"></span>${counts.yellow}</span>` +
    `<span class="ledger-item"><span class="status-dot red"></span>${counts.red}</span>` +
    `<span class="ledger-item"><span class="status-dot offline"></span>${counts.offline}</span>`;
  el.style.display = '';
}
```

- [ ] **Step 3: Call updateHealthLedger() from loadDevices()**

In `loadDevices()`, find the line `renderMarkers();` near the bottom of the function (around line 345). Add the call directly after it:

```js
    renderMarkers();
    updateHealthLedger();
```

- [ ] **Step 4: Verify the JS changes**

```bash
grep -n 'detailsLink\|updateHealthLedger\|_canSeeFirewalls' app/static/js/map.js
```

Expected: at least 4 lines — `_canSeeFirewalls` check, `detailsLink` declaration, `detailsLink` use in template literal, `updateHealthLedger` function definition, `updateHealthLedger()` call.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/map.js
git commit -m "feat: add Details deep-link in map popup and health ledger update"
```

---

## Task 4: firewalls.js — deep-link handler

**Files:**
- Modify: `app/static/js/firewalls.js`

**Interfaces:**
- Consumes: `URLSearchParams(location.search)` for `device` and `adom` params; `doSearch()` async function (module-scope, already exists at line 814); `#searchInput` element; `[data-device][data-adom]` buttons rendered by `doSearch()` results and `renderTable()`
- Produces: nothing consumed by other tasks

- [ ] **Step 1: Add the checkDeepLink() function**

In `firewalls.js`, find the `/* ── Init ──── */` comment at the very bottom of the file (around line 906). Insert the new function immediately before it:

```js
/* ── Deep-link handler ─────────────────────────────────────────────────── */
async function checkDeepLink() {
  const params = new URLSearchParams(location.search);
  const device = params.get('device');
  const adom   = params.get('adom');
  if (!device || !adom) return;

  // Clean URL immediately — prevents re-trigger on refresh
  history.replaceState({}, '', '/firewalls');

  // Pre-fill search and execute it
  document.getElementById('searchInput').value = device;
  await doSearch();

  // Find and click the matching Details button
  const btn = [...document.querySelectorAll('[data-device]')]
    .find(b => b.dataset.device === device && b.dataset.adom === adom);
  if (btn) btn.click();
}
```

- [ ] **Step 2: Call checkDeepLink() in the init block**

At the very bottom of `firewalls.js`, the init block currently reads:

```js
/* ── Init ──────────────────────────────────────────────────────────────── */
loadAdoms();
scheduleRefresh(parseInt(document.getElementById('autoRefresh').value, 10));
```

Change it to:

```js
/* ── Init ──────────────────────────────────────────────────────────────── */
loadAdoms();
scheduleRefresh(parseInt(document.getElementById('autoRefresh').value, 10));
checkDeepLink();
```

- [ ] **Step 3: Bump the firewalls.js cache-bust version in firewalls.html**

In `app/templates/firewalls.html`, find:

```html
<script src="{{ url_for('static', filename='js/firewalls.js') }}?v=22"></script>
```

Change to:

```html
<script src="{{ url_for('static', filename='js/firewalls.js') }}?v=23"></script>
```

- [ ] **Step 4: Verify the changes**

```bash
grep -n 'checkDeepLink\|replaceState' app/static/js/firewalls.js
```

Expected: 3 lines — function definition, `history.replaceState` call inside it, `checkDeepLink()` call in init block.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/firewalls.js app/templates/firewalls.html
git commit -m "feat: add deep-link handler to firewalls tab"
```

---

## Task 5: help.js — documentation updates

**Files:**
- Modify: `app/static/js/help.js`

**Interfaces:**
- No code interfaces — documentation only

- [ ] **Step 1: Update the Map (Beta) help section**

In `help.js`, find the `map_view` section (around line 329). The current `html` property ends with this FAQ entry:

```js
<h3>Missing Devices</h3>
<p>Devices are only shown if their latitude and longitude are set to a non-zero value in FortiManager (<strong>Device Manager → device properties → Location</strong>). Devices showing <code>0.0 / 0.0</code> are silently excluded. If a device you expect to see is missing, check its location in FortiManager.</p>
`
```

Replace the closing backtick with two new subsections appended before it:

```js
<h3>Device Details</h3>
<p>When you click a device pin, the popup includes a <strong>View Details →</strong> link (visible only if you have access to the Firewalls tab). Clicking it takes you directly to the Firewalls tab with that device's search pre-filled and its detail panel opened automatically. Users without Firewalls tab access will not see the link.</p>

<h3>Health Status Ledger</h3>
<p>A compact overlay in the bottom-right corner of the screen shows the total device count by health status:</p>
<ul>
  <li><span class="status-dot green" style="display:inline-block;vertical-align:middle"></span> <strong>Green</strong> — healthy devices</li>
  <li><span class="status-dot yellow" style="display:inline-block;vertical-align:middle"></span> <strong>Yellow</strong> — warning (CPU or memory elevated)</li>
  <li><span class="status-dot red" style="display:inline-block;vertical-align:middle"></span> <strong>Red</strong> — critical or unreachable</li>
  <li><span class="status-dot offline" style="display:inline-block;vertical-align:middle"></span> <strong>Grey</strong> — offline or status unknown</li>
</ul>
<p>The counts reflect the full fleet regardless of which ADOMs are currently shown via the filter checkboxes. The ledger appears once map data has loaded and remains visible as you scroll or zoom.</p>
`
```

- [ ] **Step 2: Update the Firewalls help section**

In `help.js`, find the `firewalls` section's `<h3>Search</h3>` paragraph (around line 73):

```js
<h3>Search</h3>
<p>Type a device name or IP address in the search bar at the top and press <strong>Enter</strong> or click <strong>Search</strong>. Results are returned across <em>all</em> ADOMs simultaneously. Click <strong>Details</strong> in the result row to open the device detail panel.</p>
```

Replace it with:

```js
<h3>Search</h3>
<p>Type a device name or IP address in the search bar at the top and press <strong>Enter</strong> or click <strong>Search</strong>. Results are returned across <em>all</em> ADOMs simultaneously. Click <strong>Details</strong> in the result row to open the device detail panel.</p>
<p>You can also reach this tab directly from the Map — clicking <strong>View Details →</strong> on a device popup pre-fills the search and opens the device detail panel automatically.</p>
```

- [ ] **Step 3: Bump the help.js cache-bust version in base.html**

In `app/templates/base.html`, find:

```html
<script src="{{ url_for('static', filename='js/help.js') }}?v=7"></script>
```

Change to:

```html
<script src="{{ url_for('static', filename='js/help.js') }}?v=8"></script>
```

- [ ] **Step 4: Verify**

```bash
grep -n 'View Details\|Health Status Ledger\|Device Details' app/static/js/help.js
```

Expected: at least 3 lines — one in the map section, one in the firewalls section, one heading.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/help.js app/templates/base.html
git commit -m "docs: update help text for map deep-link and health ledger"
```

---

## Task 6: CLAUDE.md — update Map section documentation

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- No code interfaces — documentation only

- [ ] **Step 1: Locate the Map section in CLAUDE.md**

```bash
grep -n 'Map\|map_view\|map_cache\|map.js' CLAUDE.md | head -20
```

Find the paragraph that describes the Map tab.

- [ ] **Step 2: Add deep-link and ledger documentation**

In the Map (Beta) section of `CLAUDE.md` (inside the `### Map tab` or equivalent section), append the following after the existing description:

```markdown
#### Map → Firewalls deep-link

`map.html` injects `window._canSeeFirewalls = {{ ('firewalls' in allowed_tabs) | tojson }}` before `map.js` loads. When `true`, each device popup includes a **View Details →** anchor linking to:

```
/firewalls?device=<encodeURIComponent(device.name)>&adom=<encodeURIComponent(device.adom)>
```

`firewalls.js` reads these params in `checkDeepLink()` at page load, pre-fills `#searchInput`, calls `doSearch()`, then auto-clicks the matching `[data-device]` button to open the detail modal. The URL is cleaned with `history.replaceState()` immediately after reading params.

#### Health status ledger

`#mapHealthLedger` is a `position:fixed` overlay (bottom-right, `z-index:1000`) populated by `updateHealthLedger()` in `map.js`. It counts `.status` values from the `allDevices` array and displays four `.ledger-item` spans using `.status-dot` color classes (`green`, `yellow`, `red`, `offline`). Called once from `loadDevices()` after `renderMarkers()`. Fleet-wide counts — not affected by ADOM filter.

New CSS classes added to `style.css`: `.map-health-ledger`, `.ledger-item`, `.map-popup-footer`, `.map-popup-details-link`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document map deep-link and health ledger in CLAUDE.md"
```

---

## Testing Checklist

After all tasks are complete, verify the following manually in the browser:

**Deep-link — user WITH Firewalls access:**
- [ ] Open `/map`, click any device pin → popup shows "View Details →" link
- [ ] Click the link → lands on `/firewalls`, search box pre-filled with device name, search results visible, device detail modal is open
- [ ] URL bar shows `/firewalls` (no query params)
- [ ] Press browser Back → returns to `/map`

**Deep-link — user WITHOUT Firewalls access:**
- [ ] Log in as a viewer without `firewalls` in their group's allowed tabs
- [ ] Open `/map`, click any device pin → popup does **not** show "View Details →"

**Deep-link edge cases:**
- [ ] Navigate manually to `/firewalls?device=DOESNOTEXIST&adom=ANYTHING` → search runs, shows "No devices matched", no JS error in console, URL cleaned to `/firewalls`
- [ ] Navigate manually to `/firewalls?device=NAME` (no adom param) → normal page load, no auto-search triggered

**Health ledger:**
- [ ] Load `/map` → after devices load, a small overlay appears bottom-right with four colored dots and counts
- [ ] Toggle ADOM filter checkboxes (hide some ADOMs) → ledger counts do **not** change
- [ ] Zoom and scroll the map in all directions → ledger stays fixed bottom-right
- [ ] Switch to dark theme (`☽` button) → ledger background and text adapt correctly (uses CSS vars)

**Help panel:**
- [ ] Open help on the Map page → "Device Details" and "Health Status Ledger" subsections present in the Map (Beta) tab
- [ ] Open help on the Firewalls page → Map cross-reference paragraph visible under the Search heading
