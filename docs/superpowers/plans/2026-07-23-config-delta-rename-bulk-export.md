# Config-Delta Rename & Bulk ADOM Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the DIFF (BETA) tab to "Config-Delta" and add a one-click "Export All Devices" button that fetches every device's pending diff in the selected ADOM and downloads a combined CSV, JSON, or PDF.

**Architecture:** All rename changes are string-only (no URL, route key, or permission changes). The bulk export is purely client-side: a sequential loop in `pending_changes.js` reuses the existing POST preview + poll task endpoints, collecting results into a local array before triggering a download. No new backend endpoints.

**Tech Stack:** Flask/Jinja2 (backend, no changes), vanilla JS (frontend), Bootstrap 5 (dropdown widget), existing `download()` helper already in `pending_changes.js`.

## Global Constraints

- Internal tab key `pending_changes`, URL `/pending-changes`, and all `/api/pending-changes/*` paths must NOT change.
- No new Python files, no new backend endpoints.
- `pytest tests/test_pending_changes.py` must stay green throughout.
- All export filenames use the `config-delta-` prefix (replacing `diff-beta-`).
- Historical plan/spec docs under `docs/superpowers/` are left unchanged.
- Branch: `development`.

---

## File Map

| File | Change |
|---|---|
| `app/routes/pending_changes_routes.py` | Line 51: update `registry.register()` display label |
| `app/templates/pending_changes.html` | Update `<title>`, `<h2>`, add Export All button + progress div |
| `app/static/js/pending_changes.js` | Rename strings, add bulk export state/logic/generators |
| `CLAUDE.md` | Rename section heading |
| `docs/features.md` | Rename section heading |
| `docs/api-reference.md` | Rename section heading |

---

## Task 1: Tab Rename

**Files:**
- Modify: `app/routes/pending_changes_routes.py:51`
- Modify: `app/templates/pending_changes.html:2,7`
- Modify: `app/static/js/pending_changes.js:433,451,456,468,474`

**Interfaces:**
- Produces: nav label "Config-Delta", page title "Config-Delta", export filenames prefixed `config-delta-`

- [ ] **Step 1: Update the registry label**

In `app/routes/pending_changes_routes.py`, change line 51:

```python
# Old:
registry.register(
    "pending_changes", "DIFF (BETA)", "pending_changes.pending_changes_page"
)

# New:
registry.register(
    "pending_changes", "Config-Delta", "pending_changes.pending_changes_page"
)
```

- [ ] **Step 2: Update the HTML page title and heading**

In `app/templates/pending_changes.html`, change lines 2 and 7:

```html
{% block title %}Config-Delta — 4THealth{% endblock %}
```

```html
<h2>Config-Delta</h2>
```

- [ ] **Step 3: Update export filenames and PDF title in JS**

In `app/static/js/pending_changes.js`, make these four changes:

Line 433 — CSV meta header comment:
```js
// Old:
  let csv = `# DIFF (BETA) Export\n# Generated: ${ts}\n# User: ${user}\n# ADOM: ${adom}\n# Devices: ${devices}\n`;
// New:
  let csv = `# Config-Delta Export\n# Generated: ${ts}\n# User: ${user}\n# ADOM: ${adom}\n# Devices: ${devices}\n`;
```

Line 451 — CSV download filename:
```js
// Old:
  download(`diff-beta-${adom || 'export'}.csv`, csv, 'text/csv');
// New:
  download(`config-delta-${adom || 'export'}.csv`, csv, 'text/csv');
```

Line 468 — JSON download filename:
```js
// Old:
  download(`diff-beta-${adom || 'export'}.json`, JSON.stringify(payload, null, 2), 'application/json');
// New:
  download(`config-delta-${adom || 'export'}.json`, JSON.stringify(payload, null, 2), 'application/json');
```

Line 474 — PDF window title:
```js
// Old:
  const title = `DIFF (BETA) — ADOM: ${adom}`;
// New:
  const title = `Config-Delta — ADOM: ${adom}`;
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/alan.k.wodarski/Library/CloudStorage/OneDrive-previousemployer/code/gitlab-sites/4thealth
python -m pytest tests/test_pending_changes.py -v
```

Expected: all tests pass (PASSED).

- [ ] **Step 5: Commit**

```bash
git add app/routes/pending_changes_routes.py \
        app/templates/pending_changes.html \
        app/static/js/pending_changes.js
git commit -m "$(cat <<'EOF'
feat: rename DIFF (BETA) tab to Config-Delta

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Bulk Export Button + Progress UI

**Files:**
- Modify: `app/templates/pending_changes.html` — add button group + progress div

**Interfaces:**
- Produces: `#pcExportAllBtn` (Bootstrap dropdown trigger, disabled by default), `#pcBulkProgress` (hidden div), `#pcBulkStatus` (text span), `#pcBulkCancel` (cancel anchor)
- Consumed by: Task 3 JS logic

- [ ] **Step 1: Add the Export All dropdown and progress div to the HTML**

In `app/templates/pending_changes.html`, replace the `.hygiene-selectors` block (lines 13–22) with:

```html
<!-- Top controls -->
<div class="hygiene-selectors">
  <div class="hygiene-selector-row">
    <label for="pcAdom">ADOM</label>
    <select id="pcAdom" class="form-select" style="max-width:280px">
      <option value="">— select ADOM —</option>
    </select>
    <span id="pcAdomLoading" class="text-muted"
          style="display:none;font-style:italic;font-size:.88rem;margin-left:.5rem">Loading…</span>

    <!-- Export All Devices dropdown -->
    <div class="dropdown" style="margin-left:.75rem">
      <button class="btn btn-sm btn-secondary dropdown-toggle" id="pcExportAllBtn"
              data-bs-toggle="dropdown" aria-expanded="false"
              disabled title="Export pending diffs for all devices in this ADOM">
        Export All Devices
      </button>
      <ul class="dropdown-menu">
        <li><a class="dropdown-item" href="#" onclick="exportAllDevices('csv');return false">CSV</a></li>
        <li><a class="dropdown-item" href="#" onclick="exportAllDevices('json');return false">JSON</a></li>
        <li><a class="dropdown-item" href="#" onclick="exportAllDevices('pdf');return false">PDF</a></li>
      </ul>
    </div>
  </div>

  <!-- Bulk export progress (hidden until a bulk run is active) -->
  <div id="pcBulkProgress" style="display:none;margin-top:.4rem;font-size:.88rem;color:var(--text-muted)">
    <span id="pcBulkStatus"></span>
    <a href="#" id="pcBulkCancel"
       onclick="cancelBulkExport();return false"
       style="margin-left:.75rem;color:var(--text-muted);text-decoration:none">× Cancel</a>
  </div>
</div>
```

- [ ] **Step 2: Verify button exists and is disabled on page load**

Start the app (`python wsgi.py`), navigate to `/pending-changes`. Confirm:
- "Export All Devices" button is visible.
- Button is disabled (greyed out) before any ADOM is selected.
- No JS console errors.

- [ ] **Step 3: Commit**

```bash
git add app/templates/pending_changes.html
git commit -m "$(cat <<'EOF'
feat: add Export All Devices button and progress UI to Config-Delta tab

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Bulk Export Logic + Format Generators

**Files:**
- Modify: `app/static/js/pending_changes.js`

**Interfaces:**
- Consumes: `allDevices` (array), `currentAdom` (string), `PC_USER` (template global), `exportQueue` (array), `renderQueue()`, `download(filename, content, mime)` — all already in scope
- Produces: `exportAllDevices(format)`, `cancelBulkExport()`, `updateExportAllState()`, `pollTask(taskId, cancelFn)`, `exportAllCsv(results)`, `exportAllJson(results)`, `exportAllPdf(results)`

- [ ] **Step 1: Add bulk state variables at the top of the State section**

In `pending_changes.js`, after line 30 (`let vdomPageState = ...`), add:

```js
let bulkRunning   = false;   // true while a bulk export run is in progress
let bulkCancelled = false;   // set by cancelBulkExport() to abort the loop
```

- [ ] **Step 2: Add `updateExportAllState()` function**

Add after the `renderQueue()` function (after line 420):

```js
/* ── Bulk export state ──────────────────────────────────────────────────────── */
function updateExportAllState() {
  const btn = document.getElementById('pcExportAllBtn');
  if (btn) btn.disabled = bulkRunning || !allDevices.length || !currentAdom;
}
```

- [ ] **Step 3: Wire `updateExportAllState()` into `fetchDevices()`**

In `fetchDevices()`, add two calls:

```js
async function fetchDevices(adom) {
  currentAdom = adom;
  allDevices = [];
  filteredDevices = [];
  currentPage = 1;
  clearDiffPanel();
  updateExportAllState();          // ← ADD: disable button immediately on ADOM change
  if (!adom) { renderDeviceTable(); return; }

  const loading = document.getElementById('pcAdomLoading');
  loading.style.display = '';
  try {
    const resp = await fetch(`/api/pending-changes/adoms/${encodeURIComponent(adom)}/devices`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    allDevices = await resp.json();
    applyFilters();
  } catch (e) {
    showDeviceError('Failed to load devices: ' + e.message);
  } finally {
    loading.style.display = 'none';
    updateExportAllState();        // ← ADD: enable/disable based on loaded devices
  }
}
```

- [ ] **Step 4: Add the `pollTask()` helper**

Add after `updateExportAllState()`:

```js
// Polls a task every 2 s until status is not 'running'. Returns the task object.
// cancelFn() returning true causes an immediate { status: 'cancelled' } return.
async function pollTask(taskId, cancelFn) {
  const POLL_MS = 2000;
  while (true) {
    if (cancelFn()) return { status: 'cancelled', result: null, error: null };
    await new Promise(res => setTimeout(res, POLL_MS));
    if (cancelFn()) return { status: 'cancelled', result: null, error: null };
    try {
      const resp = await fetch(`/api/pending-changes/task/${encodeURIComponent(taskId)}`);
      if (!resp.ok) return { status: 'error', result: null, error: `Poll HTTP ${resp.status}` };
      const task = await resp.json();
      if (task.status !== 'running') return task;
    } catch (e) {
      return { status: 'error', result: null, error: e.message };
    }
  }
}
```

- [ ] **Step 5: Add `cancelBulkExport()`**

```js
function cancelBulkExport() {
  bulkCancelled = true;
}
```

- [ ] **Step 6: Add `exportAllDevices(format)`**

```js
async function exportAllDevices(format) {
  if (bulkRunning || !allDevices.length || !currentAdom) return;
  bulkRunning   = true;
  bulkCancelled = false;

  const queueFooter  = document.getElementById('pcQueueFooter');
  const progressEl   = document.getElementById('pcBulkProgress');
  const statusEl     = document.getElementById('pcBulkStatus');
  const queueVisible = queueFooter.style.display !== 'none';

  queueFooter.style.display = 'none';
  progressEl.style.display  = '';
  updateExportAllState();

  const results = [];
  const total   = allDevices.length;

  for (let i = 0; i < total; i++) {
    if (bulkCancelled) break;
    const device = allDevices[i];
    statusEl.textContent = `Fetching ${i + 1} of ${total} — ${device.name}…`;

    try {
      const postResp = await fetch(
        `/api/pending-changes/adoms/${encodeURIComponent(currentAdom)}/device/${encodeURIComponent(device.name)}/preview`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) }
      );
      if (!postResp.ok) throw new Error(`HTTP ${postResp.status}`);
      const { task_id } = await postResp.json();

      const taskResult = await pollTask(task_id, () => bulkCancelled);
      if (bulkCancelled) break;

      if (taskResult.status === 'done') {
        const r = taskResult.result;
        const hasChanges = Array.isArray(r.vdoms) && r.vdoms.some(v => v.changes && v.changes.length > 0);
        results.push({
          device:    device.name,
          ip:        r.ip || device.ip || '',
          adom:      currentAdom,
          status:    hasChanges ? 'ok' : 'no_changes',
          summary:   r.summary  || null,
          vdoms:     r.vdoms    || [],
          raw:       r.raw      || null,
          error:     null,
          timestamp: new Date().toISOString(),
        });
      } else {
        results.push({
          device:    device.name,
          ip:        device.ip || '',
          adom:      currentAdom,
          status:    'error',
          summary:   null,
          vdoms:     null,
          raw:       null,
          error:     taskResult.error || 'Unknown error',
          timestamp: new Date().toISOString(),
        });
      }
    } catch (e) {
      results.push({
        device:    device.name,
        ip:        device.ip || '',
        adom:      currentAdom,
        status:    'error',
        summary:   null,
        vdoms:     null,
        raw:       null,
        error:     e.message,
        timestamp: new Date().toISOString(),
      });
    }
  }

  // Restore UI
  bulkRunning             = false;
  progressEl.style.display = 'none';
  statusEl.textContent     = '';
  updateExportAllState();
  if (queueVisible || exportQueue.length) renderQueue();

  if (!bulkCancelled && results.length) {
    if (format === 'csv')  exportAllCsv(results);
    if (format === 'json') exportAllJson(results);
    if (format === 'pdf')  exportAllPdf(results);
  }
}
```

- [ ] **Step 7: Add `exportAllCsv(results)`**

```js
/* ── Bulk export format generators ─────────────────────────────────────────── */
function exportAllCsv(results) {
  const ts   = new Date().toLocaleString();
  const user = typeof PC_USER !== 'undefined' ? PC_USER : '';
  const adom = currentAdom;
  const withChanges = results.filter(r => r.status === 'ok').length;
  const q    = s => '"' + String(s ?? '').replace(/"/g, '""') + '"';

  let csv = `# Config-Delta — Full ADOM Export\n`;
  csv    += `# ADOM: ${adom}\n# Generated: ${ts}\n# User: ${user}\n`;
  csv    += `# Total devices: ${results.length}\n# Devices with changes: ${withChanges}\n\n`;
  csv    += 'device,ip,vdom,change_type,line,result,error_message\n';

  results.forEach(r => {
    if (r.status === 'ok') {
      (r.vdoms || []).forEach(v => {
        (v.changes || []).forEach(c => {
          csv += `${q(r.device)},${q(r.ip)},${q(v.name)},${q(c.type)},${q(c.line)},ok,\n`;
        });
      });
    } else if (r.status === 'no_changes') {
      csv += `${q(r.device)},${q(r.ip)},,,,no_changes,\n`;
    } else {
      csv += `${q(r.device)},${q(r.ip)},,,,error,${q(r.error)}\n`;
    }
  });

  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  download(`config-delta-${adom || 'export'}-all-${date}.csv`, csv, 'text/csv');
}
```

- [ ] **Step 8: Add `exportAllJson(results)`**

```js
function exportAllJson(results) {
  const user = typeof PC_USER !== 'undefined' ? PC_USER : '';
  const adom = currentAdom;
  const payload = {
    adom,
    exported_at: new Date().toISOString(),
    exported_by: user,
    devices: results.map(r => ({
      device:    r.device,
      ip:        r.ip,
      status:    r.status,
      timestamp: r.timestamp,
      summary:   r.summary,
      changes:   r.status === 'ok' ? r.vdoms : null,
      error:     r.error || null,
    })),
  };
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  download(`config-delta-${adom || 'export'}-all-${date}.json`, JSON.stringify(payload, null, 2), 'application/json');
}
```

- [ ] **Step 9: Add `exportAllPdf(results)`**

```js
function exportAllPdf(results) {
  const ts   = new Date().toLocaleString();
  const user = typeof PC_USER !== 'undefined' ? PC_USER : '';
  const adom = currentAdom;

  function escH(s) {
    return String(s ?? '').replace(/[&<>"']/g,
      c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  const deviceSections = results.map((r, idx) => {
    let body = '';
    if (r.status === 'no_changes') {
      body = '<p style="font-size:10px;color:#6b7280;font-style:italic">No pending changes.</p>';
    } else if (r.status === 'error') {
      body = `<p style="font-size:10px;color:#b91c1c">Export failed: ${escH(r.error || '')}</p>`;
    } else {
      const s = r.summary || {};
      const summaryItems = Object.entries(s)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `<span style="margin-right:12px"><strong>${v}</strong> ${k.replace(/_/g, ' ')}</span>`)
        .join('');
      const vdomBlocks = (r.vdoms || []).map(v => {
        if (!v.changes || !v.changes.length) return '';
        const lines = v.changes.map(c => {
          const color  = c.type === 'add' ? '#166534' : c.type === 'remove' ? '#b91c1c' : '#92400e';
          const prefix = c.type === 'add' ? '+' : c.type === 'remove' ? '-' : '~';
          return `<span style="color:${color};display:block">${escH(prefix + ' ' + c.line)}</span>`;
        }).join('');
        return `<div style="margin-top:8px">
          <strong style="font-size:10px">vdom: ${escH(v.name)}</strong>
          <pre style="background:#f8f9fa;border:1px solid #e5e7eb;border-radius:3px;padding:8px;
                      font-size:9px;margin:4px 0;overflow-wrap:break-word;white-space:pre-wrap">${lines}</pre>
        </div>`;
      }).join('');
      body = (summaryItems ? `<div style="margin-bottom:8px;font-size:10px">${summaryItems}</div>` : '') +
             (vdomBlocks  || '<p style="font-size:10px;color:#6b7280;font-style:italic">No pending changes found.</p>');
    }
    return `<div style="${idx > 0 ? 'page-break-before:always;padding-top:1cm' : ''}">
      <h2 style="font-size:14px;margin:0 0 4px">${escH(r.device)}</h2>
      <div style="font-size:10px;color:#6b7280;margin-bottom:6px"><code>${escH(r.ip || '')}</code></div>
      ${body}
    </div>`;
  }).join('');

  const title = `Config-Delta — ADOM: ${adom}`;
  const html  = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${escH(title)}</title>
<style>
  body{font-family:Arial,sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:16px;margin-bottom:6px}
  .meta{background:#f3f4f6;border-left:4px solid #3b82f6;padding:8px 12px;border-radius:3px;margin-bottom:14px;font-size:10px}
  code{font-family:monospace;font-size:10px}
  @media print{@page{margin:1.2cm}}
</style></head><body>
<h1>${escH(title)}</h1>
<div class="meta">
  Generated: ${escH(ts)}<br>User: ${escH(user)}<br>ADOM: ${escH(adom)}<br>
  Total devices: ${results.length} — With changes: ${results.filter(r => r.status === 'ok').length}
</div>
${deviceSections}
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.print(); }
}
```

- [ ] **Step 10: Run tests**

```bash
python -m pytest tests/test_pending_changes.py -v
```

Expected: all tests pass.

- [ ] **Step 11: Manual smoke tests**

Start the app: `python wsgi.py`

| Check | Expected |
|---|---|
| Select an ADOM | "Export All Devices" button enables |
| No ADOM selected | Button is disabled |
| Export All → CSV on an ADOM | Progress shows `Fetching 1 of N — <device>…`, CSV downloads at end |
| CSV contents | Header block with ADOM/date/user, rows for each device, `no_changes` row for devices with empty diffs |
| Export All → JSON | JSON file with `adom`, `exported_at`, `exported_by`, `devices` array |
| Export All → PDF | Print dialog opens, one section per device |
| Cancel mid-run | Run stops, no download, button re-enables |
| Existing per-device queue | "Add to Export Queue" and queue footer still work as before |

- [ ] **Step 12: Commit**

```bash
git add app/static/js/pending_changes.js
git commit -m "$(cat <<'EOF'
feat: add bulk ADOM export with progress indicator to Config-Delta tab

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Docs, Graphify, Final Test, and Push

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/features.md`
- Modify: `docs/api-reference.md`

- [ ] **Step 1: Update CLAUDE.md section heading**

Find and replace in `CLAUDE.md`:

```
### DIFF tab (Beta)
```
→
```
### Config-Delta tab
```

Also update the inline description on the same section to reference "Config-Delta" where it says "DIFF (Beta)":

The section starts at the line `### DIFF tab (Beta)`. Change only that heading line — leave body content intact unless it contains the literal string "DIFF (Beta)" or "DIFF (BETA)" as a display label (update those too; leave internal key references like `pending_changes` untouched).

- [ ] **Step 2: Update docs/features.md section heading**

Find:
```markdown
## DIFF (Beta)
```
Replace with:
```markdown
## Config-Delta
```

- [ ] **Step 3: Update docs/api-reference.md section heading**

Find:
```markdown
## DIFF (Beta)
```
Replace with:
```markdown
## Config-Delta
```

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/test_pending_changes.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Update graphify knowledge graph**

```bash
graphify update .
```

Expected: completes without error, graph files under `graphify-out/` are updated.

- [ ] **Step 6: Commit docs + graphify**

```bash
git add CLAUDE.md docs/features.md docs/api-reference.md graphify-out/
git commit -m "$(cat <<'EOF'
docs: update DIFF (Beta) → Config-Delta in CLAUDE.md, features.md, api-reference.md; refresh graphify

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Push to GitLab**

```bash
git push origin development
```

Expected: push succeeds, `development` branch on GitLab is up to date.
