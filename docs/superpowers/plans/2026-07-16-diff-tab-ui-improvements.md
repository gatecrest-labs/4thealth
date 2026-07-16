# DIFF Tab UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three UX issues in the DIFF (BETA) tab: horizontal scroll on long CLI diff lines, layout overlap on narrow viewports, and no pagination for large diffs.

**Architecture:** Pure frontend change — three files touched, no backend or route changes. CSS classes replace inline styles for the layout, `white-space:pre-wrap` replaces `overflow-x:auto` on the diff `<pre>`, and a module-level `Map` (`vdomPageState`) drives per-VDOM pagination rendered inline in the diff panel.

**Tech Stack:** Vanilla JS (ES6), Jinja2 templates, CSS (no build step — edits are live on next page reload).

## Global Constraints

- No backend changes — all three tasks are frontend-only.
- No new npm/pip dependencies.
- All JS is vanilla ES6 — no frameworks.
- Follow the existing inline-style + `esc()` pattern already used in `pending_changes.js`.
- Default page size for pagination: 25. Options: 10, 25, 50.
- CSS breakpoint for responsive stack: 900px.
- Tests are manual visual verification — there are no JS unit tests for this frontend; the existing Python test suite (`tests/test_pending_changes.py`) tests the parser only and must remain green.

---

## File Map

| File | Role |
|---|---|
| `app/static/css/style.css` | Add `.pc-layout`, `.pc-layout-left`, `.pc-layout-right` classes + 900px media query |
| `app/templates/pending_changes.html` | Replace inline `style=` on layout divs with the new CSS classes |
| `app/static/js/pending_changes.js` | (1) Change `<pre>` to wrap; (2) Add hanging-indent to diff spans; (3) Add `vdomPageState` Map + `setVdomPage()`; (4) Slice changes per page in `renderDiffPanel()` |

---

### Task 1: Responsive CSS layout classes

Replace the three inline `style=` blocks in the template with dedicated CSS classes, and add a 900px breakpoint that stacks the columns vertically to prevent overlap.

**Files:**
- Modify: `app/static/css/style.css` (append near end of file, after existing rules)
- Modify: `app/templates/pending_changes.html:25-78`

**Interfaces:**
- Produces: CSS classes `.pc-layout`, `.pc-layout-left`, `.pc-layout-right` consumed by Task 1's template edit and no other task.

- [ ] **Step 1: Add CSS classes to style.css**

Append the following block at the end of `app/static/css/style.css`:

```css
/* ── DIFF tab two-column layout ─────────────────────────────────────────── */
.pc-layout       { display:flex; gap:1.25rem; margin-top:1.25rem; align-items:flex-start; }
.pc-layout-left  { flex:0 0 420px; min-width:280px; }
.pc-layout-right { flex:1; min-width:0; overflow:hidden; }

@media (max-width:900px) {
  .pc-layout { flex-direction:column; }
  .pc-layout-left { flex:none; width:100%; }
}
```

- [ ] **Step 2: Update the template to use the new classes**

In `app/templates/pending_changes.html`, replace lines 25–78 (the two-column layout block). The three `style=` attributes on the outer div and two child divs are the only things changing — the content inside each div is untouched.

Replace:
```html
<!-- Two-column layout -->
<div style="display:flex;gap:1.25rem;margin-top:1.25rem;align-items:flex-start">

  <!-- Left: device list -->
  <div style="flex:0 0 420px;min-width:280px">
```
With:
```html
<!-- Two-column layout -->
<div class="pc-layout">

  <!-- Left: device list -->
  <div class="pc-layout-left">
```

Replace:
```html
  <!-- Right: diff panel -->
  <div style="flex:1;min-width:0;overflow:hidden">
```
With:
```html
  <!-- Right: diff panel -->
  <div class="pc-layout-right">
```

- [ ] **Step 3: Manual verification**

Start the dev server:
```bash
python wsgi.py
```
Open `https://localhost:5443`, navigate to DIFF tab.

Check at full-width viewport (≥900px):
- Two columns side by side — device list on left (~420px), diff panel fills the rest. Layout identical to before.

Resize browser to ~700px wide:
- Device list should stack **above** the diff panel, full width, no overlap.
- No horizontal scrollbar on the page container.

- [ ] **Step 4: Run Python tests to confirm nothing broken**

```bash
python -m pytest tests/test_pending_changes.py -v
```
Expected: all tests pass (this task touches no Python code).

- [ ] **Step 5: Commit**

```bash
git add app/static/css/style.css app/templates/pending_changes.html
git commit -m "style: replace DIFF tab inline layout styles with responsive CSS classes

Adds .pc-layout* classes with a 900px breakpoint that stacks the device
list above the diff panel on narrow viewports, preventing overlap."
```

---

### Task 2: Line wrapping with hanging indent

Change the diff `<pre>` block from horizontal-scroll to line-wrap, and add a CSS hanging indent so the `+`/`-`/`~` prefix stays anchored while wrapped continuation text is indented.

**Files:**
- Modify: `app/static/js/pending_changes.js:270-283` (inside `renderDiffPanel()`)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing consumed by other tasks (self-contained visual change).

- [ ] **Step 1: Update the diff span and pre in renderDiffPanel()**

In `app/static/js/pending_changes.js`, locate the `vdomsHtml` mapping inside `renderDiffPanel()` (around line 268). Replace the existing `linesHtml` map and the `<pre>` template literal:

Replace:
```js
    const linesHtml = vdom.changes.map(c => {
      const cls = c.type === 'add' ? 'diff-add' : c.type === 'remove' ? 'diff-remove' : 'diff-modify';
      const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
      return `<span class="${cls}">${esc(prefix + ' ' + c.line)}</span>`;
    }).join('\n');
    return `<details open style="margin-top:.6rem">
      <summary style="cursor:pointer;font-weight:500;font-size:.82rem;padding:.2rem 0;
                       color:var(--text-muted);letter-spacing:.03em;text-transform:uppercase">
        vdom: ${esc(vdom.name)}
      </summary>
      <pre class="diff-block" style="background:var(--surface-alt);border:1px solid var(--border);
           border-radius:4px;padding:.75rem;overflow-x:auto;font-size:.8rem;margin:.4rem 0 0">${linesHtml}</pre>
    </details>`;
```

With:
```js
    const linesHtml = vdom.changes.map(c => {
      const cls = c.type === 'add' ? 'diff-add' : c.type === 'remove' ? 'diff-remove' : 'diff-modify';
      const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
      return `<span class="${cls}" style="display:block;padding-left:1.4em;text-indent:-1.4em">${esc(prefix + ' ' + c.line)}</span>`;
    }).join('\n');
    return `<details open style="margin-top:.6rem">
      <summary style="cursor:pointer;font-weight:500;font-size:.82rem;padding:.2rem 0;
                       color:var(--text-muted);letter-spacing:.03em;text-transform:uppercase">
        vdom: ${esc(vdom.name)}
      </summary>
      <pre class="diff-block" style="background:var(--surface-alt);border:1px solid var(--border);
           border-radius:4px;padding:.75rem;white-space:pre-wrap;overflow-wrap:break-word;font-size:.8rem;margin:.4rem 0 0">${linesHtml}</pre>
    </details>`;
```

- [ ] **Step 2: Manual verification**

On the DIFF tab, select a device that has a diff with long lines (e.g. LDAP DN lines or long address object names — search for a device showing `Pkg Pending` in the ENTERPRISE-SERVICES ADOM).

Check:
- Long lines **wrap** within the diff panel — no horizontal scrollbar inside the `<pre>`.
- The leading `+`, `-`, or `~` character stays on the left margin; continuation text is indented by the same width (hanging indent).
- Short lines (under panel width) are unaffected — single line, no extra indent visible.
- Green/red/amber colouring on add/remove/modify lines is unchanged.

- [ ] **Step 3: Run Python tests**

```bash
python -m pytest tests/test_pending_changes.py -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "style: wrap long diff lines with hanging indent in DIFF tab

Replaces overflow-x:auto with white-space:pre-wrap on the diff <pre>
and adds a 1.4em hanging indent so the +/-/~ prefix stays anchored
while continuation text wraps within the panel."
```

---

### Task 3: Per-VDOM diff pagination

Add a module-level `vdomPageState` Map and a `setVdomPage()` function, then wire them into `renderDiffPanel()` so each VDOM block shows a paginated slice of its changes with `<< < Page N of M > >>` controls and a 10/25/50 page-size selector.

**Files:**
- Modify: `app/static/js/pending_changes.js` — State section (~line 18), `loadPreview()` (~line 187), `renderDiffPanel()` (~line 244)

**Interfaces:**
- Consumes: `currentDiff` (existing module-level variable), `renderDiffPanel()` (existing function — called by `setVdomPage` to re-render).
- Produces: `setVdomPage(vdomName: string, newPage: number, newPageSize: number|null): void` — called from inline `onclick` attributes in the generated HTML.

- [ ] **Step 1: Add vdomPageState to the State block**

In `app/static/js/pending_changes.js`, find the State block (around line 18–29). Add `vdomPageState` after the existing `_previewAbort` line:

Replace:
```js
let _previewAbort  = null;
```
With:
```js
let _previewAbort  = null;
let vdomPageState  = new Map(); // vdom.name → { page, pageSize }
```

- [ ] **Step 2: Add setVdomPage() function**

Add this function anywhere after the State block and before `renderDiffPanel()` — a good place is just before the `/* ── Diff panel rendering ───── */` comment block (around line 219):

```js
/* ── Per-VDOM pagination ────────────────────────────────────────────────── */
function setVdomPage(vdomName, newPage, newPageSize) {
  const current = vdomPageState.get(vdomName) || { page: 1, pageSize: 25 };
  vdomPageState.set(vdomName, {
    page: newPage,
    pageSize: newPageSize != null ? newPageSize : current.pageSize,
  });
  renderDiffPanel(currentDiff);
}
```

- [ ] **Step 3: Reset vdomPageState when a new device preview is loaded**

In `loadPreview()` (around line 187), add a reset at the top of the function so switching devices clears pagination state:

Replace:
```js
async function loadPreview(adom, deviceName) {
  if (_previewAbort) { _previewAbort.abort(); }
```
With:
```js
async function loadPreview(adom, deviceName) {
  vdomPageState = new Map();
  if (_previewAbort) { _previewAbort.abort(); }
```

- [ ] **Step 4: Wire pagination into the VDOM rendering in renderDiffPanel()**

In `renderDiffPanel()`, replace the entire `vdomsHtml` mapping (the `diff.vdoms.map(...)` block, lines ~268–283) with the paginated version below. This replaces the existing block in full — the `linesHtml` build and `<details>` template literal are both contained within this replacement.

Replace (the full `const vdomsHtml = diff.vdoms.map(vdom => { ... }).join('');` block):
```js
  const vdomsHtml = diff.vdoms.map(vdom => {
    if (!vdom.changes.length) return '';
    const linesHtml = vdom.changes.map(c => {
      const cls = c.type === 'add' ? 'diff-add' : c.type === 'remove' ? 'diff-remove' : 'diff-modify';
      const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
      return `<span class="${cls}" style="display:block;padding-left:1.4em;text-indent:-1.4em">${esc(prefix + ' ' + c.line)}</span>`;
    }).join('\n');
    return `<details open style="margin-top:.6rem">
      <summary style="cursor:pointer;font-weight:500;font-size:.82rem;padding:.2rem 0;
                       color:var(--text-muted);letter-spacing:.03em;text-transform:uppercase">
        vdom: ${esc(vdom.name)}
      </summary>
      <pre class="diff-block" style="background:var(--surface-alt);border:1px solid var(--border);
           border-radius:4px;padding:.75rem;overflow-x:auto;font-size:.8rem;margin:.4rem 0 0">${linesHtml}</pre>
    </details>`;
  }).join('');
```

With:
```js
  const vdomsHtml = diff.vdoms.map(vdom => {
    if (!vdom.changes.length) return '';

    if (!vdomPageState.has(vdom.name)) {
      vdomPageState.set(vdom.name, { page: 1, pageSize: 25 });
    }
    const { page, pageSize: ps } = vdomPageState.get(vdom.name);
    const totalLines  = vdom.changes.length;
    const totalPages  = Math.ceil(totalLines / ps);
    const sliceStart  = (page - 1) * ps;
    const pageChanges = vdom.changes.slice(sliceStart, sliceStart + ps);

    const linesHtml = pageChanges.map(c => {
      const cls    = c.type === 'add' ? 'diff-add' : c.type === 'remove' ? 'diff-remove' : 'diff-modify';
      const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
      return `<span class="${cls}" style="display:block;padding-left:1.4em;text-indent:-1.4em">${esc(prefix + ' ' + c.line)}</span>`;
    }).join('\n');

    const vn   = JSON.stringify(vdom.name); // safe JS string literal for onclick
    const pbtn = (label, p, disabled) =>
      `<button class="btn btn-xs" onclick="setVdomPage(${vn},${p},null)" ${disabled ? 'disabled' : ''}>${label}</button>`;

    const paginationHtml = totalLines > ps ? `
      <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-top:.4rem;font-size:.8rem">
        ${pbtn('&laquo;', 1,           page === 1)}
        ${pbtn('&lsaquo;', page - 1,  page === 1)}
        <span style="color:var(--text-muted);padding:0 .2rem">Page ${page} of ${totalPages}</span>
        ${pbtn('&rsaquo;', page + 1,  page === totalPages)}
        ${pbtn('&raquo;', totalPages,  page === totalPages)}
        <select class="form-select form-select-sm" style="width:70px;font-size:.8rem"
                onchange="setVdomPage(${vn}, 1, parseInt(this.value, 10))">
          ${[10, 25, 50].map(n => `<option value="${n}"${n === ps ? ' selected' : ''}>${n}</option>`).join('')}
        </select>
        <span style="color:var(--text-muted)">${totalLines} lines total</span>
      </div>` : '';

    return `<details open style="margin-top:.6rem">
      <summary style="cursor:pointer;font-weight:500;font-size:.82rem;padding:.2rem 0;
                       color:var(--text-muted);letter-spacing:.03em;text-transform:uppercase">
        vdom: ${esc(vdom.name)}
      </summary>
      <pre class="diff-block" style="background:var(--surface-alt);border:1px solid var(--border);
           border-radius:4px;padding:.75rem;white-space:pre-wrap;overflow-wrap:break-word;font-size:.8rem;margin:.4rem 0 0">${linesHtml}</pre>
      ${paginationHtml}
    </details>`;
  }).join('');
```

> **Note:** This step supersedes Task 2's Step 1 — both wrapping changes (`white-space:pre-wrap`, hanging indent) are included here. If Task 2 was already committed, the old `linesHtml` block and `<pre>` in the replacement above already match Task 2's output — the only net-new lines are the pagination state, slice, and `paginationHtml`.

- [ ] **Step 5: Manual verification**

On the DIFF tab, open a device with a large diff (many lines). Test all of the following:

**Pagination controls:**
- A VDOM with >25 lines shows `[<<] [<] Page 1 of N [>] [>>]  Show [25▾]  X lines total` below the `<pre>`.
- A VDOM with ≤25 lines shows **no** pagination controls.
- `[>]` advances to page 2; `[<]` goes back; both disable at their respective boundaries.
- `[<<]` jumps to page 1; `[>>]` jumps to last page.
- Changing Show to `10` re-renders with 10 lines per page and resets to page 1.
- Changing Show to `50` re-renders with 50 lines per page and resets to page 1.

**State reset:**
- Click a different device — pagination resets to page 1 / 25 per page.
- Click `+ Add to Export Queue` — pagination position is preserved (not reset).

**Export integrity:**
- Stage a device with a multi-page diff into the export queue.
- Navigate to page 3 of a VDOM block.
- Export as CSV — verify the CSV contains **all** lines from that VDOM, not just the 25 on the current page. (Row count in CSV should equal the "X lines total" label.)

**Wrapping (regression check from Task 2):**
- Long lines still wrap; `+`/`-`/`~` prefix stays anchored on left margin.

- [ ] **Step 6: Run Python tests**

```bash
python -m pytest tests/test_pending_changes.py -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "feat: add per-VDOM pagination to DIFF tab diff panel

Each VDOM block is paginated (10/25/50 lines, default 25) with
<< < Page N of M > >> controls. Controls only appear when the VDOM
has more lines than the current page size. Switching devices resets
all VDOM page state; exports always include the full change set."
```

---

## Final smoke check

After all three tasks are committed:

```bash
python -m pytest tests/ -v
```
Expected: full suite green — no regressions.

Then do a final pass on the DIFF tab at both wide (≥900px) and narrow (≤800px) viewports, with a device that has a large diff, confirming all items in the spec testing checklist are satisfied.
