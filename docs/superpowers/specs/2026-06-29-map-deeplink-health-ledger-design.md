# Design: Map Deep-link to Firewalls + Health Status Ledger

**Date:** 2026-06-29
**Status:** Approved

---

## Problem

Users viewing the Map tab can see device pins but have no direct path to full device health details without leaving the map, navigating to Firewalls, selecting an ADOM, finding the device, and clicking Details. Two gaps:

1. No shortcut from a map popup to the Firewalls device detail view.
2. No at-a-glance health summary while browsing the map.

---

## Solution Overview

Two independent features, no backend changes required:

1. **Deep-link:** Add a "View Details →" link to each map popup that navigates to `/firewalls?device=NAME&adom=ADOM`. The Firewalls tab reads those params on load, pre-fills the search, runs it, and auto-opens the device detail modal.
2. **Health ledger:** A fixed-position overlay (bottom-right, always visible) showing green/yellow/red/offline device counts sourced from the in-memory `allDevices` array.

---

## Section 1 — Map Popup "Details" Link

### Permission gate

`map.html` injects a boolean into the page before `map.js` loads:

```html
<script>
  window._canSeeFirewalls = {{ ('firewalls' in allowed_tabs) | tojson }};
</script>
```

- Admin users: always `true`
- Non-admin users: `true` only if `"firewalls"` is in their `allowed_tabs`
- Users without access: link is **omitted entirely** from the popup — no grayed-out state, no tooltip, no 403 redirect

### Popup change (`map.js → makeMarker()`)

The popup HTML string gains a conditional footer:

```js
const detailsLink = window._canSeeFirewalls
  ? `<div class="map-popup-footer">
       <a href="/firewalls?device=${encodeURIComponent(device.name)}&adom=${encodeURIComponent(device.adom)}"
          class="map-popup-details-link">View Details →</a>
     </div>`
  : '';
```

Appended inside the `<div class="map-popup">` after the table.

---

## Section 2 — Firewalls Tab Deep-link Handler

### URL contract

```
/firewalls?device=<device-name>&adom=<adom-name>
```

Both params must be present for the deep-link to activate. Either param absent = normal page load, no side effects.

### Handler (`firewalls.js`)

Added to the init block after `loadAdoms()`:

```js
async function checkDeepLink() {
  const params = new URLSearchParams(location.search);
  const device = params.get('device');
  const adom   = params.get('adom');
  if (!device || !adom) return;

  // Clean URL immediately so refresh doesn't re-trigger
  history.replaceState({}, '', '/firewalls');

  // Pre-fill search and run it
  document.getElementById('searchInput').value = device;
  await doSearch();

  // Find and click the matching Details button
  const btn = [...document.querySelectorAll('[data-device]')]
    .find(b => b.dataset.device === device && b.dataset.adom === adom);
  if (btn) btn.click();
}
```

`checkDeepLink()` is called after `loadAdoms()` in the init block (both are async; `checkDeepLink` awaits `doSearch` internally so the modal opens only after results render).

### Behavior

| Scenario | Result |
|---|---|
| Device found in search results | Modal opens automatically |
| Device not found (ADOM mismatch, device deleted) | Search results shown with "No devices matched" — silent, no error |
| User lacks Firewalls tab access | Page never loads (403 before JS runs) |

---

## Section 3 — Health Status Ledger

### HTML (`map.html`)

```html
<div id="mapHealthLedger" class="map-health-ledger" style="display:none"></div>
```

Placed inside `{% block content %}`, outside `#mapContainer`.

### Rendering (`map.js → updateHealthLedger()`)

Counts sourced from `allDevices` (all devices, not filtered — ledger always reflects total fleet):

```js
function updateHealthLedger() {
  const el = document.getElementById('mapHealthLedger');
  if (!el || !allDevices.length) return;
  const counts = { green: 0, yellow: 0, red: 0, offline: 0 };
  allDevices.forEach(d => {
    const s = d.status || 'offline';
    if (s in counts) counts[s]++; else counts.offline++;
  });
  el.innerHTML = `
    <span class="ledger-item"><span class="status-dot green"></span>${counts.green}</span>
    <span class="ledger-item"><span class="status-dot yellow"></span>${counts.yellow}</span>
    <span class="ledger-item"><span class="status-dot red"></span>${counts.red}</span>
    <span class="ledger-item"><span class="status-dot offline"></span>${counts.offline}</span>
  `;
  el.style.display = '';
}
```

Called at the end of `loadDevices()` (after `renderMarkers()`). Not called from `renderMarkers()` itself since counts are fleet-wide and don't change with ADOM filter toggles.

### Styling

```css
.map-health-ledger {
  position: fixed;
  bottom: 1.5rem;
  right: 1rem;
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 0.8rem;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}
.ledger-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
```

Uses existing `.status-dot` classes (already defined with `green`, `yellow`, `red`, and `offline` variants across the app) for the colored indicators. Note: `.map-popup-dot` only has `green` and `offline` variants — use `.status-dot` instead.

---

## Section 4 — Documentation

### `help.js` — Map (Beta) section additions

**New "Device Details" subsection:**
- Explains the "View Details →" link appears in popups when the user has Firewalls tab access
- States it navigates to the Firewalls tab with the device pre-selected and the detail panel open
- Notes that users without Firewalls tab access will not see the link

**New "Health Status Ledger" subsection:**
- Describes the fixed bottom-right overlay
- Explains the four colored dots: green = healthy, yellow = warning, red = critical, grey = offline/unknown
- Notes counts reflect the full fleet (all ADOMs), not the current ADOM filter

### `help.js` — Firewalls section addition

Adds a note to the Search subsection: "You can also reach this tab directly from the Map — clicking **View Details →** on a device popup pre-fills the search and opens the device detail panel automatically."

### `CLAUDE.md` — Map section additions

- Documents `window._canSeeFirewalls` boolean injected by `map.html`
- Documents deep-link URL pattern: `/firewalls?device=<name>&adom=<adom>`
- Documents `updateHealthLedger()` function and `#mapHealthLedger` element
- Documents new CSS classes: `.map-health-ledger`, `.ledger-item`

---

## Files Changed

| File | Change |
|---|---|
| `app/templates/map.html` | Add `window._canSeeFirewalls`, add `#mapHealthLedger` div |
| `app/static/js/map.js` | `makeMarker()` popup link, `updateHealthLedger()` function |
| `app/templates/firewalls.html` | No changes |
| `app/static/js/firewalls.js` | `checkDeepLink()` function, init block call |
| `app/static/css/style.css` | `.map-health-ledger`, `.ledger-item` styles |
| `app/static/js/help.js` | Map and Firewalls section updates |
| `CLAUDE.md` | Map section documentation updates |

No backend Python changes required.

---

## Testing Checklist

1. **Deep-link (with Firewalls access):**
   - Open the map, click a device pin
   - Verify "View Details →" link is present
   - Click the link → Firewalls tab loads, search box is pre-filled with device name, search results appear, device detail modal opens automatically
   - Verify URL is cleaned to `/firewalls` (no query params remain)
   - Press browser Back → returns to map

2. **Deep-link (without Firewalls access):**
   - Log in as a user without `firewalls` in allowed_tabs
   - Open the map, click a device pin
   - Verify "View Details →" link is **not present** in the popup

3. **Deep-link edge cases:**
   - Navigate to `/firewalls?device=NONEXISTENT&adom=ANYTHING` manually → search runs, shows "No devices matched", no error
   - Navigate to `/firewalls?device=NAME` (missing adom param) → normal page load, no auto-search

4. **Health ledger:**
   - Load the map → ledger appears bottom-right after data loads
   - Verify four colored dots with counts
   - Toggle ADOM filter checkboxes → ledger counts do NOT change (fleet-wide)
   - Zoom and scroll the map → ledger stays fixed in bottom-right corner
   - Test in both light and dark themes

5. **Documentation:**
   - Open help panel on Map page → "Device Details" and "Health Status Ledger" subsections present
   - Open help panel on Firewalls page → Map cross-reference note present in Search section
