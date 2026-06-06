'use strict';

/* ── Utilities ─────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ── Protocol badge rendering (mirrors firewalls.js) ───────────────────────── */
function protoBadgeHtml(proto) {
  const base = 'display:inline-block;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600;border:1px solid;margin:1px 2px';
  const label = proto.name.toUpperCase();
  if (proto.secure === false)
    return `<span style="${base};color:#dc3545;border-color:#dc3545;background:#fff5f5">${esc(label)}</span>`;
  if (proto.secure === true)
    return `<span style="${base};color:#2d6a2d;border-color:#5a9e5a;background:#f4faf4">${esc(label)}</span>`;
  return `<span style="${base};color:#555;border-color:#aaa;background:#f8f8f8">${esc(label)}</span>`;
}

function protoListHtml(protocols) {
  if (!protocols || !protocols.length) return '<span style="color:#888">—</span>';
  return protocols.map(protoBadgeHtml).join('');
}

function statusBadgeHtml(status) {
  const base = 'display:inline-block;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600;border:1px solid';
  if ((status || '') === 'up')
    return `<span style="${base};color:#2d6a2d;border-color:#5a9e5a;background:#f4faf4">UP</span>`;
  if ((status || '') === 'down')
    return `<span style="${base};color:#888;border-color:#ccc;background:#f5f5f5">DOWN</span>`;
  return `<span style="${base};color:#555;border-color:#aaa;background:#f8f8f8">${esc(status || '?')}</span>`;
}

/* ── State ──────────────────────────────────────────────────────────────────── */
let allRows      = [];
let lastMeta     = null;
let currentPage  = 1;
let pageSize     = 25;
let filterText   = '';
let filterDevice = '';
let filterStatus = 'up';        // 'up' = only up interfaces; 'all' = include down
let activeProtos = new Set();   // protocol names currently checked; empty = show all
let _protoMeta   = {};          // proto name → secure (true/false/null)
let _abortRun    = false;       // set to true to cancel in-flight per-device loop
let _knownDevices = [];         // populated when ADOM is selected

/* ── Error/clear ────────────────────────────────────────────────────────────── */
function showError(msg) {
  const el = document.getElementById('drError');
  el.textContent = msg;
  el.style.display = '';
}
function clearError() {
  const el = document.getElementById('drError');
  el.textContent = '';
  el.style.display = 'none';
}

/* ── Progress bar helpers ───────────────────────────────────────────────────── */
function showProgress(done, total, currentDevice) {
  const wrap = document.getElementById('drProgressWrap');
  const bar  = document.getElementById('drProgressBar');
  const lbl  = document.getElementById('drProgressLabel');
  if (!wrap) return;
  wrap.style.display = '';
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  bar.style.width = pct + '%';
  bar.textContent  = pct + '%';
  const remaining  = total - done;
  lbl.textContent  = `Analysing… ${done} / ${total} devices` +
    (currentDevice ? ` — ${currentDevice}` : '') +
    (remaining > 0  ? ` (${remaining} remaining)` : '');
}

function hideProgress() {
  const wrap = document.getElementById('drProgressWrap');
  if (wrap) wrap.style.display = 'none';
}

/* ── ADOM loader ────────────────────────────────────────────────────────────── */
async function loadAdoms() {
  const sel = document.getElementById('drAdom');
  try {
    const resp = await fetch('/api/adoms');
    if (resp.status === 401) { location.href = '/login'; return; }
    const adoms = await resp.json();
    if (!Array.isArray(adoms)) return;
    adoms.forEach(a => {
      const opt = document.createElement('option');
      opt.value = a.name; opt.textContent = a.name;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

/* ── Fetch device list when ADOM changes ────────────────────────────────────── */
async function onAdomChange(adom) {
  _knownDevices = [];
  document.getElementById('drResults').style.display = 'none';
  document.getElementById('drRunBtn').disabled = true;
  clearError();
  allRows = [];

  if (!adom) return;

  document.getElementById('drDeviceLoading').style.display = '';
  try {
    const resp = await fetch(`/api/device-review/adoms/${encodeURIComponent(adom)}/devices`);
    if (resp.status === 401) { location.href = '/login'; return; }
    const data = await resp.json();
    if (Array.isArray(data)) {
      _knownDevices = data;
      document.getElementById('drRunBtn').disabled = false;
      document.getElementById('drRunBtn').title =
        `${data.length} device${data.length !== 1 ? 's' : ''} in this ADOM`;
    }
  } catch (e) {
    showError('Could not load device list: ' + e.message);
  } finally {
    document.getElementById('drDeviceLoading').style.display = 'none';
  }
}

/* ── Run analysis (per-device loop with live progress) ──────────────────────── */
async function runAnalysis() {
  clearError();
  hideProgress();
  const adom = document.getElementById('drAdom').value;
  if (!adom) return;

  const checks = [...document.querySelectorAll('input[name="dr_check"]:checked')].map(cb => cb.value);
  if (!checks.length) { showError('Select at least one check.'); return; }

  const deviceList = _knownDevices.map(d => d.name).filter(Boolean);
  if (!deviceList.length) { showError('No devices found in this ADOM.'); return; }

  _abortRun = false;
  document.getElementById('drRunBtn').disabled        = true;
  const cancelBtn = document.getElementById('drCancelBtn');
  cancelBtn.disabled    = false;
  cancelBtn.textContent = '⏹ Cancel';
  cancelBtn.style.display = '';
  document.getElementById('drRunning').style.display = '';
  document.getElementById('drResults').style.display = 'none';

  const collectedRows = [];
  const reviewed      = [];

  showProgress(0, deviceList.length, deviceList[0]);

  for (let i = 0; i < deviceList.length; i++) {
    if (_abortRun) break;

    const device = deviceList[i];
    showProgress(i, deviceList.length, device);

    try {
      const resp = await fetch('/api/device-review/run/device', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ adom, device, checks }),
      });
      if (resp.status === 401) { location.href = '/login'; return; }
      const data = await resp.json();
      if (resp.ok && Array.isArray(data.rows)) {
        collectedRows.push(...data.rows);
        reviewed.push(device);
      }
    } catch (_) {
      // network error on one device — skip and continue
    }
  }

  showProgress(deviceList.length, deviceList.length, '');

  const runAt = new Date().toLocaleString();
  allRows  = collectedRows;
  lastMeta = {
    adom:         adom,
    run_at:       runAt,
    device_count: reviewed.length,
    checks_run:   checks,
    devices:      reviewed,
  };

  // Reset filters
  filterText   = '';
  filterDevice = '';
  filterStatus = 'up';
  currentPage  = 1;
  document.getElementById('drFilter').value        = '';
  document.getElementById('drDeviceFilter').value  = '';
  document.getElementById('drStatusFilter').value  = 'up';

  populateDeviceFilter(reviewed);
  buildProtoCheckboxes();
  renderTable();

  document.getElementById('drResults').style.display = '';
  const insCount = allRows.filter(r => r.has_insecure).length;
  document.getElementById('drLastRunLabel').textContent =
    `Last run: ${runAt} — ${reviewed.length} device(s) · ${allRows.length} interface(s)` +
    (insCount ? ` · ${insCount} with insecure protocol(s)` : '') +
    (_abortRun ? ' (cancelled)' : '');

  document.getElementById('drRunBtn').disabled        = false;
  cancelBtn.style.display  = 'none';
  cancelBtn.disabled       = false;
  cancelBtn.textContent    = '⏹ Cancel';
  document.getElementById('drRunning').style.display  = 'none';
  setTimeout(hideProgress, 2000);
}

/* ── Protocol checkbox panel ────────────────────────────────────────────────── */
function buildProtoCheckboxes() {
  _protoMeta = {};
  allRows.forEach(row => {
    (row.protocols || []).forEach(p => {
      if (!(p.name in _protoMeta)) _protoMeta[p.name] = p.secure;
    });
  });

  const sorted = Object.keys(_protoMeta).sort((a, b) => {
    const rank = v => v === false ? 0 : v === true ? 1 : 2;
    const ra = rank(_protoMeta[a]), rb = rank(_protoMeta[b]);
    return ra !== rb ? ra - rb : a.localeCompare(b);
  });

  activeProtos = new Set(sorted);

  const container = document.getElementById('drProtoChecks');
  container.innerHTML = '';

  if (!sorted.length) {
    container.innerHTML = '<span class="text-muted" style="font-size:.82rem">No protocols found.</span>';
    return;
  }

  sorted.forEach(name => {
    const secure = _protoMeta[name];
    const count  = allRows.filter(r => (r.protocols || []).some(p => p.name === name)).length;

    let badgeStyle = 'display:inline-block;padding:1px 5px;border-radius:3px;font-size:.72rem;font-weight:600;border:1px solid;margin-left:4px;vertical-align:middle';
    if (secure === false)  badgeStyle += ';color:#dc3545;border-color:#dc3545;background:#fff5f5';
    else if (secure === true) badgeStyle += ';color:#2d6a2d;border-color:#5a9e5a;background:#f4faf4';
    else                   badgeStyle += ';color:#555;border-color:#aaa;background:#f8f8f8';

    const lbl = document.createElement('label');
    lbl.className = 'checkbox-label';
    lbl.innerHTML =
      `<input type="checkbox" class="dr-proto-cb" value="${esc(name)}" checked />` +
      `<span style="${badgeStyle}">${esc(name.toUpperCase())}</span>` +
      `<span style="font-size:.75rem;color:var(--text-muted);margin-left:3px">(${count})</span>`;
    container.appendChild(lbl);
  });

  container.querySelectorAll('.dr-proto-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      activeProtos = new Set(
        [...container.querySelectorAll('.dr-proto-cb:checked')].map(c => c.value)
      );
      currentPage = 1;
      renderTable();
    });
  });
}

function setAllProtos(checked) {
  document.querySelectorAll('.dr-proto-cb').forEach(cb => { cb.checked = checked; });
  activeProtos = checked ? new Set(Object.keys(_protoMeta)) : new Set();
  currentPage = 1;
  renderTable();
}

/* ── Device dropdown ────────────────────────────────────────────────────────── */
function populateDeviceFilter(deviceNames) {
  const sel = document.getElementById('drDeviceFilter');
  sel.innerHTML = '<option value="">All devices</option>';
  [...new Set(deviceNames)].sort().forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    sel.appendChild(opt);
  });
}

/* ── Filtering ──────────────────────────────────────────────────────────────── */
function filtered() {
  const q = filterText.toLowerCase();
  return allRows.filter(row => {
    if (filterStatus === 'up' && (row.status || '') !== 'up') return false;
    if (filterDevice && row.device !== filterDevice) return false;
    if (activeProtos.size > 0) {
      const rowProtos = new Set((row.protocols || []).map(p => p.name));
      if (![...activeProtos].some(p => rowProtos.has(p))) return false;
    }
    if (!q) return true;
    const protoNames = (row.protocols || []).map(p => p.name).join(' ').toLowerCase();
    return (
      (row.device    || '').toLowerCase().includes(q) ||
      (row.interface || '').toLowerCase().includes(q) ||
      (row.vdom      || '').toLowerCase().includes(q) ||
      (row.ip        || '').toLowerCase().includes(q) ||
      (row.type      || '').toLowerCase().includes(q) ||
      (row.status    || '').toLowerCase().includes(q) ||
      protoNames.includes(q)
    );
  });
}

function visibleProtocols(row) {
  return activeProtos.size > 0
    ? (row.protocols || []).filter(p => activeProtos.has(p.name))
    : (row.protocols || []);
}

/* ── Render table ───────────────────────────────────────────────────────────── */
function renderTable() {
  const rows  = filtered();
  const start = (currentPage - 1) * pageSize;
  const page  = rows.slice(start, start + pageSize);
  const tbody = document.getElementById('drTbody');

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">No interfaces match the current filters.</td></tr>';
    document.getElementById('drPager').innerHTML    = '';
    document.getElementById('drSummary').textContent = buildSummary(rows);
    return;
  }

  tbody.innerHTML = page.map(row => {
    const rowClass    = row.has_insecure ? ' class="dr-row-insecure"' : '';
    const vdom        = row.vdom && row.vdom !== 'root' ? row.vdom : '';
    const visProtos   = visibleProtocols(row);
    const statusBadge = statusBadgeHtml(row.status);
    return `<tr${rowClass}>
      <td><strong>${esc(row.device)}</strong></td>
      <td><code>${esc(row.interface)}</code></td>
      <td>${vdom ? `<span class="dr-vdom-badge">${esc(vdom)}</span>` : '<span style="color:var(--text-muted)">root</span>'}</td>
      <td><span class="dr-type-badge">${esc(row.type || 'physical')}</span></td>
      <td>${statusBadge}</td>
      <td><code>${esc(row.ip)}</code></td>
      <td>${protoListHtml(visProtos)}</td>
    </tr>`;
  }).join('');

  document.getElementById('drSummary').textContent = buildSummary(rows);
  renderPager(rows.length);
}

function buildSummary(rows) {
  const insecure = rows.filter(r => r.has_insecure).length;
  const devices  = new Set(rows.map(r => r.device)).size;
  let s = `${rows.length} interface(s) · ${devices} device(s)`;
  if (insecure) s += ` · ${insecure} with insecure protocol(s)`;
  return s;
}

/* ── Pagination ─────────────────────────────────────────────────────────────── */
function renderPager(total) {
  const pages = Math.ceil(total / pageSize);
  const pager = document.getElementById('drPager');
  if (pages <= 1) { pager.innerHTML = ''; return; }

  const range = [1];
  for (let p = Math.max(2, currentPage - 2); p <= Math.min(pages - 1, currentPage + 2); p++) range.push(p);
  if (!range.includes(pages)) range.push(pages);

  let html = `<button ${currentPage === 1 ? 'disabled' : ''} data-page="1">&laquo;</button>`;
  html    += `<button ${currentPage === 1 ? 'disabled' : ''} data-page="${currentPage - 1}">&lsaquo;</button>`;
  let prev = 0;
  range.forEach(p => {
    if (p - prev > 1) html += `<span class="pagination-ellipsis">…</span>`;
    html += `<button ${p === currentPage ? 'class="active"' : ''} data-page="${p}">${p}</button>`;
    prev = p;
  });
  html += `<button ${currentPage === pages ? 'disabled' : ''} data-page="${currentPage + 1}">&rsaquo;</button>`;
  html += `<button ${currentPage === pages ? 'disabled' : ''} data-page="${pages}">&raquo;</button>`;
  pager.innerHTML = html;
}

/* ── Exports ────────────────────────────────────────────────────────────────── */
function exportCsv() {
  const rows = filtered();
  if (!rows.length) { showError('No filtered results to export.'); return; }
  clearError();
  const meta = lastMeta || {};
  const header = [
    `ADOM,${meta.adom || ''}`,
    `Date/Time,${meta.run_at || ''}`,
    `Devices Reviewed,${meta.device_count ?? ''}`,
    `Total Interfaces,${rows.length}`,
    '',
  ].join('\r\n');
  const cols = ['Device', 'Interface', 'VDOM', 'Type', 'Status', 'IP Address', 'Protocols', 'Has Insecure'];
  const body = [cols.join(','), ...rows.map(r => [
    r.device, r.interface, r.vdom, r.type, r.status || '',
    r.ip,
    visibleProtocols(r).map(p => p.name).join(' '),
    r.has_insecure ? 'YES' : 'no',
  ].map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))].join('\r\n');
  download(`device-review-${meta.adom || 'export'}.csv`, header + body, 'text/csv');
}

function exportJson() {
  const meta = lastMeta || {};
  const rows = filtered();
  if (!rows.length) { showError('No filtered results to export.'); return; }
  clearError();
  download(
    `device-review-${meta.adom || 'export'}.json`,
    JSON.stringify({ meta, rows }, null, 2),
    'application/json',
  );
}

function exportPdf() {
  const rows = filtered();
  if (!rows.length) { showError('No filtered results to export.'); return; }
  clearError();
  const meta        = lastMeta || {};
  const ts          = meta.run_at || new Date().toLocaleString();
  const title       = `Interface Protocol Review — ADOM: ${meta.adom || ''}`;
  const insecCount  = rows.filter(r => r.has_insecure).length;
  const deviceCount = new Set(rows.map(r => r.device)).size;

  const protoCell = protos => {
    if (!protos || !protos.length) return '—';
    return protos.map(p => {
      const style = p.secure === false
        ? 'color:#b91c1c;font-weight:700;background:#fee2e2;padding:0 4px;border-radius:2px;margin:0 1px'
        : p.secure === true
          ? 'color:#166534;font-weight:600;background:#dcfce7;padding:0 4px;border-radius:2px;margin:0 1px'
          : 'color:#374151;background:#f3f4f6;padding:0 4px;border-radius:2px;margin:0 1px';
      return `<span style="${style}">${esc(p.name.toUpperCase())}</span>`;
    }).join('');
  };

  const tableRows = rows.map(r => {
    const rowStyle  = r.has_insecure ? 'background:#fff5f5' : '';
    const vdom      = r.vdom && r.vdom !== 'root' ? r.vdom : 'root';
    const visProtos = visibleProtocols(r);
    const st = (r.status || '').toUpperCase() || '—';
    const stStyle = r.status === 'up'
      ? 'color:#166534;font-weight:700'
      : r.status === 'down' ? 'color:#888' : 'color:#374151';
    return `<tr style="${rowStyle}">
      <td>${esc(r.device)}</td>
      <td><code>${esc(r.interface)}</code></td>
      <td>${esc(vdom)}</td>
      <td>${esc(r.type || '')}</td>
      <td style="${stStyle}">${esc(st)}</td>
      <td><code>${esc(r.ip)}</code></td>
      <td>${protoCell(visProtos)}</td>
    </tr>`;
  }).join('');

  const protoLegend = [...activeProtos].sort().map(n => {
    const s = _protoMeta[n];
    const style = s === false
      ? 'color:#b91c1c;background:#fee2e2;border:1px solid #fca5a5;padding:0 5px;border-radius:2px;font-weight:700;font-size:10px'
      : s === true
        ? 'color:#166534;background:#dcfce7;border:1px solid #86efac;padding:0 5px;border-radius:2px;font-size:10px'
        : 'color:#374151;background:#f3f4f6;border:1px solid #d1d5db;padding:0 5px;border-radius:2px;font-size:10px';
    return `<span style="${style}">${esc(n.toUpperCase())}</span>`;
  }).join(' ');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:Arial,sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:16px;margin-bottom:6px}
  .meta{background:#f3f4f6;border-left:4px solid #3b82f6;padding:8px 12px;border-radius:3px;margin-bottom:14px;font-size:10px}
  .meta table{border:none;width:auto}
  .meta td{padding:1px 14px 1px 0;border:none;background:none}
  .meta td:first-child{font-weight:700;color:#1f2937}
  .stats{display:flex;gap:12px;margin-bottom:14px}
  .stat{padding:4px 12px;border-radius:4px;font-size:11px;font-weight:700}
  .stat-total{background:#f3f4f6;color:#374151}
  .stat-insecure{background:#fee2e2;color:#991b1b}
  table.main{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:4px 8px;border-bottom:1px solid #e5e7eb;vertical-align:middle}
  code{font-family:monospace;font-size:10px}
  @media print{body{margin:.8cm}.stats{display:block}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">
  <table>
    <tr><td>ADOM</td><td>${esc(meta.adom || '')}</td></tr>
    <tr><td>Date / Time</td><td>${esc(ts)}</td></tr>
    <tr><td>Devices in ADOM</td><td>${meta.device_count ?? 0}</td></tr>
    <tr><td>Devices in Report</td><td>${deviceCount}</td></tr>
    <tr><td>Interfaces in Report</td><td>${rows.length}</td></tr>
    <tr><td>Protocols Shown</td><td>${protoLegend || '—'}</td></tr>
  </table>
</div>
<div class="stats">
  <span class="stat stat-total">Interfaces: ${rows.length}</span>
  ${insecCount ? `<span class="stat stat-insecure">&#9888; Insecure: ${insecCount}</span>` : ''}
</div>
<table class="main">
  <thead><tr><th>Device</th><th>Interface</th><th>VDOM</th><th>Type</th><th>Status</th><th>IP Address</th><th>Protocols</th></tr></thead>
  <tbody>${tableRows}</tbody>
</table>
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.focus(); win.print(); }
}

function download(filename, content, mime) {
  const a  = document.createElement('a');
  const bl = new Blob([content], { type: mime });
  a.href   = URL.createObjectURL(bl);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ── Event wiring ───────────────────────────────────────────────────────────── */
document.getElementById('drAdom').addEventListener('change', e => onAdomChange(e.target.value));

document.getElementById('drRunBtn').addEventListener('click', runAnalysis);

document.getElementById('drCancelBtn').addEventListener('click', function () {
  _abortRun = true;
  this.disabled    = true;
  this.textContent = 'Cancelling…';
});

document.getElementById('drFilter').addEventListener('input', e => {
  filterText  = e.target.value;
  currentPage = 1;
  renderTable();
});

document.getElementById('drDeviceFilter').addEventListener('change', e => {
  filterDevice = e.target.value;
  currentPage  = 1;
  renderTable();
});

document.getElementById('drStatusFilter').addEventListener('change', e => {
  filterStatus = e.target.value;
  currentPage  = 1;
  renderTable();
});

document.getElementById('drPageSize').addEventListener('change', e => {
  pageSize    = parseInt(e.target.value, 10);
  currentPage = 1;
  renderTable();
});

document.getElementById('drPager').addEventListener('click', e => {
  const btn = e.target.closest('button[data-page]');
  if (!btn || btn.disabled) return;
  currentPage = parseInt(btn.dataset.page, 10);
  renderTable();
});

document.getElementById('drProtoAll').addEventListener('click',  () => setAllProtos(true));
document.getElementById('drProtoNone').addEventListener('click', () => setAllProtos(false));

document.getElementById('drExportCsv').addEventListener('click', exportCsv);
document.getElementById('drExportJson').addEventListener('click', exportJson);
document.getElementById('drExportPdf').addEventListener('click', exportPdf);

/* ── Init ───────────────────────────────────────────────────────────────────── */
loadAdoms();
