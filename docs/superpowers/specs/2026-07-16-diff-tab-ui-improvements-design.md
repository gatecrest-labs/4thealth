# DIFF Tab UI Improvements — Design Spec

**Date:** 2026-07-16  
**Status:** Approved  
**Files affected:** `app/templates/pending_changes.html`, `app/static/js/pending_changes.js`, `app/static/css/style.css`

---

## Problem Statement

The DIFF (BETA) tab has three UX issues:

1. **Horizontal scroll on long CLI lines** — The `<pre class="diff-block">` uses `overflow-x:auto`, so long lines (e.g. LDAP DNs, long address object names) force a horizontal scrollbar and require the user to scroll sideways to read content.
2. **Layout overlap on narrow viewports** — The two-column flex layout has the device list at `flex:0 0 420px` with no shrink allowance. On narrow screens the diff panel bleeds over or under the device list.
3. **No pagination for large diffs** — Devices with hundreds of CLI diff lines render everything at once, making it hard to read. Users want to page through 10/25/50 lines at a time.

---

## Approach: Wrap + Responsive Stack + Per-VDOM Pagination

### Section 1: Line Wrapping

**File:** `app/static/js/pending_changes.js`

In `renderDiffPanel()`, the `<pre class="diff-block">` inline style changes:

- **Before:** `overflow-x:auto`
- **After:** `white-space:pre-wrap; overflow-wrap:break-word`

Long lines wrap within the panel width. No horizontal scrollbar.

**Hanging indent:** Each `.diff-add`, `.diff-remove`, `.diff-modify` span gets `padding-left:1.4em; text-indent:-1.4em` added to its inline style. This is a CSS hanging-indent that keeps the leading `+`/`-`/`~` symbol visually anchored on the left while continuation text wraps indented, preserving readability.

### Section 2: Responsive Layout

**Files:** `app/templates/pending_changes.html`, `app/static/css/style.css`

Replace the inline `style=` attributes on the outer flex container and its two children with CSS classes:

```css
.pc-layout       { display:flex; gap:1.25rem; margin-top:1.25rem; align-items:flex-start; }
.pc-layout-left  { flex:0 0 420px; min-width:280px; }
.pc-layout-right { flex:1; min-width:0; overflow:hidden; }

@media (max-width:900px) {
  .pc-layout { flex-direction:column; }
  .pc-layout-left { flex:none; width:100%; }
}
```

- Above 900px: identical to current behaviour (side-by-side columns).
- Below 900px: device list stacks above diff panel — no overlap possible.

The template's inline `style=` on the container div and both child divs is removed and replaced with `class="pc-layout"`, `class="pc-layout-left"`, and `class="pc-layout-right"` respectively.

### Section 3: Per-VDOM Diff Pagination

**File:** `app/static/js/pending_changes.js`

#### State

A module-level `Map` named `vdomPageState` maps `vdom.name → { page: number, pageSize: number }`.

- Default page size: 25
- Reset completely at the start of every `renderDiffPanel()` call (new device = fresh state).

#### Rendering

Each VDOM block in `renderDiffPanel()` slices `vdom.changes` to the current page window before rendering the `<pre>` block. Below the `<pre>`, a pagination control row is rendered **only when the VDOM has more lines than the current page size**:

```
[<<] [<]  Page 2 of 5  [>] [>>]    Show [10 ▾]    110 lines total
```

- Page size selector: options 10 / 25 / 50
- `<<` / `>>` jump to first/last page
- `<` / `>` step one page; disabled at boundaries
- Line count label shows total lines in that VDOM (not the current page slice)
- VDOMs with ≤ pageSize lines render no controls at all

#### Interaction

A `setVdomPage(vdomName, newPage, newPageSize)` function updates `vdomPageState` and re-calls `renderDiffPanel(currentDiff)`. This reuses the existing full-rerender pattern (already used by the "Add to Queue" button refresh).

#### Export unaffected

The export queue stores the full `currentDiff` object which holds complete `changes` arrays. Pagination is display-only and has no effect on CSV/JSON/PDF output.

---

## Out of scope

- Resizable panel splitter (Approach C)
- Pooled cross-VDOM pagination
- Any changes to the backend / routes

---

## Testing checklist

- [ ] Long CLI lines wrap and the `+`/`-`/`~` prefix stays left-anchored
- [ ] No horizontal scrollbar appears on the diff panel
- [ ] At viewport < 900px device list stacks above the diff panel with no overlap
- [ ] At viewport ≥ 900px layout is identical to before
- [ ] Per-VDOM pagination controls appear only when lines > page size
- [ ] `<<` / `<` / `>` / `>>` navigate correctly; boundary buttons are disabled
- [ ] Page size selector (10/25/50) changes the slice immediately
- [ ] Selecting a new device resets all VDOM page state
- [ ] Changing ADOM clears the diff panel and resets state
- [ ] CSV / JSON / PDF exports still contain all lines (not just the current page)
