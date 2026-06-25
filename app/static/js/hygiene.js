'use strict';

/* ── Utilities ─────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ── Hygiene state ──────────────────────────────────────────────────────────── */
let allFindings  = [];
let checkLabels  = {};
let currentPage  = 1;
let pageSize     = 25;
let filterText   = '';
let filterCheck  = '';
let lastMeta     = null;

/* ── Policy viewer state ────────────────────────────────────────────────────── */
let allPolicies    = [];
let pvPage         = 1;
let pvPageSize     = 25;
let pvSearch       = '';
let pvField        = '';
let pvRegex        = false;
let pvFiltered     = [];   // computed by applyPvFilter()
let pvMeta         = null; // { adom, pkg }
let pvPkgPaths     = {};

/* ── Object Lookup state ────────────────────────────────────────────────────── */
let olAllObjects   = [];
let olFiltered     = [];
let olPage         = 1;
let olPageSize     = 25;
let olFilter       = '';
let olMeta         = null; // { adom, query }

/* ── ADOM loaders ───────────────────────────────────────────────────────────── */
async function loadAdoms() {
  try {
    const resp = await fetch('/api/adoms');
    if (resp.status === 401) { location.href = '/login'; return; }
    const adoms = await resp.json();
    if (!Array.isArray(adoms)) return;
    ['pvAdom', 'hygieneAdom', 'olAdom'].forEach(id => {
      const sel = document.getElementById(id);
      adoms.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a.name; opt.textContent = a.name;
        sel.appendChild(opt);
      });
    });
  } catch (_) {}
}

/* ── Policy Rules package loader ────────────────────────────────────────────── */
async function loadPvPackages(adom) {
  const sel = document.getElementById('pvPackage');
  sel.innerHTML = '<option value="">Loading…</option>';
  sel.disabled = true;
  pvPkgPaths = {};
  document.getElementById('policyView').style.display = 'none';
  allPolicies = [];
  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/packages`);
    if (resp.status === 401) { location.href = '/login'; return; }
    const pkgs = await resp.json();
    sel.innerHTML = '<option value="">— select package —</option>';
    if (Array.isArray(pkgs)) {
      pkgs.forEach(p => {
        pvPkgPaths[p.name] = p.path || p.name;
        const opt = document.createElement('option');
        opt.value = p.name; opt.textContent = p.name;
        sel.appendChild(opt);
      });
    }
    sel.disabled = false;
  } catch (_) {
    sel.innerHTML = '<option value="">Failed to load packages</option>';
  }
}

/* ── Hygiene package loader ─────────────────────────────────────────────────── */
let pkgPaths = {};

async function loadHygienePackages(adom) {
  const sel = document.getElementById('hygienePackage');
  sel.innerHTML = '<option value="">Loading…</option>';
  sel.disabled = true;
  pkgPaths = {};
  document.getElementById('hygieneRunBtn').disabled = true;
  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/packages`);
    if (resp.status === 401) { location.href = '/login'; return; }
    const pkgs = await resp.json();
    sel.innerHTML = '<option value="">— select package —</option>';
    if (Array.isArray(pkgs)) {
      pkgs.forEach(p => {
        pkgPaths[p.name] = p.path || p.name;
        const opt = document.createElement('option');
        opt.value = p.name; opt.textContent = p.name;
        sel.appendChild(opt);
      });
    }
    sel.disabled = false;
  } catch (_) {
    sel.innerHTML = '<option value="">Failed to load packages</option>';
  }
}

/* ── Run analysis ───────────────────────────────────────────────────────────── */
async function runAnalysis() {
  const adom    = document.getElementById('hygieneAdom').value;
  const pkg     = document.getElementById('hygienePackage').value;
  const path    = pkgPaths[pkg] || pkg;
  const checked = [...document.querySelectorAll('input[name=hygiene_check]:checked')].map(i => i.value);

  if (!adom || !pkg) return;

  const errEl = document.getElementById('hygieneError');
  errEl.style.display = 'none';
  document.getElementById('hygieneResults').style.display = 'none';
  document.getElementById('hygieneRunBtn').disabled = true;
  document.getElementById('hygieneRunning').style.display = '';

  try {
    const resp = await fetch('/api/hygiene/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adom, package: pkg, path, checks: checked }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || 'Analysis failed.');
      return;
    }

    allFindings = data.findings || [];
    lastMeta    = data;
    currentPage = 1;
    filterText  = '';
    filterCheck = '';
    document.getElementById('hygieneFilter').value      = '';
    document.getElementById('hygieneCheckFilter').value = '';
    document.getElementById('lastRunLabel').textContent =
      `Last run: ${new Date().toLocaleString()} — ${data.policy_count} policies analysed`;

    populateCheckFilter(data.checks_run);
    renderTable();
    document.getElementById('hygieneResults').style.display = '';
  } catch (err) {
    showError(err.message);
  } finally {
    document.getElementById('hygieneRunBtn').disabled = false;
    document.getElementById('hygieneRunning').style.display = 'none';
  }
}

function showError(msg) {
  const el = document.getElementById('hygieneError');
  el.textContent = msg;
  el.style.display = '';
}

/* ── Check filter dropdown population ──────────────────────────────────────── */
function populateCheckFilter(checksRun) {
  const sel = document.getElementById('hygieneCheckFilter');
  sel.innerHTML = '<option value="">All checks</option>';
  checksRun.forEach(key => {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = checkLabels[key] || key;
    sel.appendChild(opt);
  });
}

/* ── Hygiene filtering ──────────────────────────────────────────────────────── */
function filtered() {
  return allFindings.filter(f => {
    if (filterCheck && f.check !== filterCheck) return false;
    if (!filterText) return true;
    const q = filterText.toLowerCase();
    return (
      f.policy_name.toLowerCase().includes(q) ||
      f.policy_id.toLowerCase().includes(q)   ||
      (checkLabels[f.check] || f.check).toLowerCase().includes(q) ||
      f.detail.toLowerCase().includes(q)
    );
  });
}

/* ── Render hygiene table ───────────────────────────────────────────────────── */
function renderTable() {
  const rows  = filtered();
  const total = Math.ceil(rows.length / pageSize) || 1;
  currentPage = Math.min(currentPage, total);
  const slice = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  const meta = lastMeta || {};
  document.getElementById('hygieneSummary').textContent =
    `${rows.length === allFindings.length
      ? allFindings.length
      : `${rows.length} of ${allFindings.length}`
    } finding${allFindings.length !== 1 ? 's' : ''} across ${meta.policy_count || '?'} policies` +
    (meta.package ? ` in "${meta.package}"` : '');

  document.getElementById('hygieneCount').textContent =
    `${rows.length} finding${rows.length !== 1 ? 's' : ''} — page ${currentPage} of ${total}`;

  const BADGE_COLORS = {
    unnamed:     '#6366f1',
    unlogged:    '#f59e0b',
    shadow:      '#ef4444',
    disabled:    '#64748b',
    expired:     '#dc2626',
    unhit:       '#0ea5e9',
  };

  const tbody = document.getElementById('hygieneTbody');

  const ruleCard = (r, title) => `
    <div class="shadow-rule-card">
      <div class="shadow-rule-title">${esc(title)}</div>
      <div class="shadow-rule-grid">
        <span class="shadow-rule-label">ID</span><span>${esc(r.id)}</span>
        <span class="shadow-rule-label">Name</span><span>${esc(r.name || '—')}</span>
        <span class="shadow-rule-label">Status</span><span style="font-weight:600;color:${r.status==='enable'?'#22c55e':'var(--text-muted)'}">${esc(r.status || '—')}</span>
        <span class="shadow-rule-label">Action</span><span style="font-weight:600;color:${r.action==='deny'||r.action==='block'?'#ef4444':'#22c55e'}">${esc(r.action)}</span>
        <span class="shadow-rule-label">Source</span><span>${esc((r.srcaddr||[]).join(', ') || 'any')}</span>
        <span class="shadow-rule-label">Destination</span><span>${esc((r.dstaddr||[]).join(', ') || 'any')}</span>
        <span class="shadow-rule-label">Service</span><span>${esc((r.service||[]).join(', ') || 'any')}</span>
        ${r.srcintf && r.srcintf.length ? `<span class="shadow-rule-label">Src Interface</span><span>${esc(r.srcintf.join(', '))}</span>` : ''}
        ${r.dstintf && r.dstintf.length ? `<span class="shadow-rule-label">Dst Interface</span><span>${esc(r.dstintf.join(', '))}</span>` : ''}
        ${r.fsso_groups && r.fsso_groups.length ? `<span class="shadow-rule-label">AD Groups</span><span>${esc(r.fsso_groups.join(', '))}</span>` : ''}
        ${r.comment ? `<span class="shadow-rule-label">Comment</span><span style="color:var(--text-muted)">${esc(r.comment)}</span>` : ''}
      </div>
    </div>`;

  const rowsHtml = slice.map((f, i) => {
    const color  = BADGE_COLORS[f.check] || '#94a3b8';
    const label  = checkLabels[f.check] || f.check;
    const rowId  = `finding-detail-${currentPage}-${i}`;
    const isShadow     = f.check === 'shadow' && f.shadow_rule && f.shadowing_rule;
    const hasDetail    = isShadow || !!f.rule_detail;
    const expandBtn = hasDetail
      ? ` <button class="shadow-expand-btn" data-target="${rowId}" title="Show rule details" aria-expanded="false">&#9660;</button>`
      : '';
    const mainRow = `<tr class="${hasDetail ? 'shadow-finding-row' : ''}" ${hasDetail ? `data-target="${rowId}"` : ''}>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(String(f.seq || '—'))}</td>
      <td><strong>${esc(f.policy_name)}</strong>${f.policy_id && f.policy_id !== f.policy_name ? `<br><span style="font-size:.75rem;color:var(--text-muted)">id: ${esc(f.policy_id)}</span>` : ''}</td>
      <td><span class="hygiene-badge" style="background:${color}20;color:${color};border-color:${color}40">${esc(label)}</span></td>
      <td style="font-size:.82rem">${esc(f.detail)}${expandBtn}</td>
    </tr>`;

    if (!hasDetail) return mainRow;

    let detailContent;
    if (isShadow) {
      detailContent = ruleCard(f.shadow_rule, 'Shadowed Rule (hidden — never hit)') +
                      ruleCard(f.shadowing_rule, 'Shadowing Rule (earlier — intercepts traffic)');
    } else {
      detailContent = ruleCard(f.rule_detail, 'Rule Details');
    }

    const detailRow = `<tr id="${rowId}" class="shadow-detail-row" style="display:none">
      <td colspan="4">
        <div class="shadow-detail-wrap">${detailContent}</div>
      </td>
    </tr>`;
    return mainRow + detailRow;
  }).join('') || `<tr><td colspan="4" class="empty-state" style="padding:.85rem 1rem">No findings match your filter.</td></tr>`;

  tbody.innerHTML = rowsHtml;
  renderPagination(total);
}

/* ── Hygiene pagination ─────────────────────────────────────────────────────── */
function renderPagination(total) {
  const pg = document.getElementById('hygienePagination');
  if (total <= 1) { pg.innerHTML = ''; return; }

  function btn(label, page, disabled, active) {
    return `<button class="pg-btn${active ? ' active' : ''}" data-hpage="${page}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }
  let html = btn('&laquo;&laquo;', 1, currentPage === 1, false);
  html += btn('&lsaquo;', currentPage - 1, currentPage === 1, false);
  const s = Math.max(1, currentPage - 2), e = Math.min(total, s + 4);
  for (let i = s; i <= e; i++) html += btn(i, i, false, i === currentPage);
  html += btn('&rsaquo;', currentPage + 1, currentPage === total, false);
  html += btn('&raquo;&raquo;', total, currentPage === total, false);
  pg.innerHTML = html;
}

/* ── Hygiene exports ────────────────────────────────────────────────────────── */
function exportCsv() {
  const rows = filtered();
  const header = ['Seq', 'Policy ID', 'Policy Name', 'Check', 'Detail'];
  const lines  = [header.join(',')];
  rows.forEach(f => {
    lines.push([
      f.seq,
      `"${String(f.policy_id).replace(/"/g, '""')}"`,
      `"${String(f.policy_name).replace(/"/g, '""')}"`,
      `"${(checkLabels[f.check] || f.check).replace(/"/g, '""')}"`,
      `"${String(f.detail).replace(/"/g, '""')}"`,
    ].join(','));
  });
  download('hygiene_report.csv', lines.join('\r\n'), 'text/csv');
}

function exportJson() {
  const payload = {
    meta: lastMeta,
    generated: new Date().toISOString(),
    findings: filtered().map(f => ({ ...f, check_label: checkLabels[f.check] || f.check })),
  };
  download('hygiene_report.json', JSON.stringify(payload, null, 2), 'application/json');
}

function exportPdf() {
  const rows = filtered();
  const meta = lastMeta || {};
  const ts = new Date().toLocaleString();
  const title = `Rule Review — ${meta.adom || ''} / ${meta.package || ''}`;

  const tableRows = rows.map(f => `
    <tr>
      <td>${esc(String(f.seq || '—'))}</td>
      <td>${esc(f.policy_name)}<br><small>${esc(f.policy_id)}</small></td>
      <td>${esc(checkLabels[f.check] || f.check)}</td>
      <td>${esc(f.detail)}</td>
    </tr>`).join('');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:16px;margin-bottom:4px}
  .meta{font-size:10px;color:#5a6478;margin-bottom:12px}
  table{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:4px 8px;border-bottom:1px solid #d0d7e2;vertical-align:top}
  small{color:#5a6478}
  @media print{body{margin:1cm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">Generated ${ts} &bull; ${rows.length} findings &bull; ${meta.policy_count || '?'} policies analysed</div>
<table>
  <thead><tr><th>#</th><th>Rule</th><th>Check</th><th>Detail</th></tr></thead>
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

/* ═══════════════════════════════════════════════════════════════════════════════
   POLICY VIEWER
   ═══════════════════════════════════════════════════════════════════════════════ */

/* ── Load policies ──────────────────────────────────────────────────────────── */

// Tag to cancel stale object-enrichment requests when the user switches package.
let _pvObjLoadTag = 0;

function _expandAddr(name, addrGrpMap, addrDetailMap) {
  if (addrGrpMap[name]) return { name, type: 'group', members: addrGrpMap[name] };
  return { name, type: 'object', detail: addrDetailMap[name] || '' };
}
function _expandSvc(name, svcGrpMap) {
  if (svcGrpMap[name]) return { name, type: 'group', members: svcGrpMap[name] };
  return { name, type: 'object' };
}

function _backfillRule(r, addrGrpMap, addrDetailMap, svcGrpMap) {
  r.srcaddr_exp = (r.srcaddr || []).map(n => _expandAddr(n, addrGrpMap, addrDetailMap));
  r.dstaddr_exp = (r.dstaddr || []).map(n => _expandAddr(n, addrGrpMap, addrDetailMap));
  r.service_exp = (r.service || []).map(n => _expandSvc(n, svcGrpMap));
}

function _hideBadgeIfDone() {
  const objBadge = document.getElementById('pvObjBadge');
  if (objBadge && objBadge.dataset.pending === '0') objBadge.style.display = 'none';
}

async function _loadPolicyObjects(adom, tag) {
  try {
    const resp = await fetch('/api/hygiene/policies/objects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adom }),
    });
    if (_pvObjLoadTag !== tag) return;
    if (!resp.ok) return;
    let obj;
    try { obj = await resp.json(); } catch (_) { return; }
    if (_pvObjLoadTag !== tag) return;

    const { addr_grp_map = {}, svc_grp_map = {}, addr_detail_map = {} } = obj;

    for (const p of allPolicies) {
      if (p.policy_block !== undefined) {
        for (const r of (p.rules || [])) _backfillRule(r, addr_grp_map, addr_detail_map, svc_grp_map);
      } else {
        _backfillRule(p, addr_grp_map, addr_detail_map, svc_grp_map);
      }
    }

    applyPvFilter();
    renderPolicyTable();
  } catch (_) { /* silently ignore */ }
  finally {
    const objBadge = document.getElementById('pvObjBadge');
    if (objBadge) {
      objBadge.dataset.pending = String(Math.max(0, Number(objBadge.dataset.pending || 1) - 1));
      _hideBadgeIfDone();
    }
  }
}

async function _loadPolicyPblocks(adom, names, tag) {
  if (!names || !names.length) {
    const objBadge = document.getElementById('pvObjBadge');
    if (objBadge) {
      objBadge.dataset.pending = String(Math.max(0, Number(objBadge.dataset.pending || 1) - 1));
      _hideBadgeIfDone();
    }
    return;
  }
  try {
    const resp = await fetch('/api/hygiene/policies/pblocks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adom, names }),
    });
    if (_pvObjLoadTag !== tag) return;
    if (!resp.ok) return;
    let obj;
    try { obj = await resp.json(); } catch (_) { return; }
    if (_pvObjLoadTag !== tag) return;

    const pblocks = obj.pblocks || {};
    for (const p of allPolicies) {
      if (p.policy_block !== undefined && pblocks[p.policy_block] !== undefined) {
        p.rules    = pblocks[p.policy_block];
        p.assigned = p.rules.length > 0;
      }
    }

    // Update rule count now that pblock rules are known
    const ruleCount = _pvRuleCount(allPolicies);
    document.getElementById('policyViewTitle').textContent =
      `${ruleCount} rule${ruleCount !== 1 ? 's' : ''} in "${pvMeta.pkg}" (${pvMeta.adom})`;

    applyPvFilter();
    renderPolicyTable();
  } catch (_) { /* silently ignore */ }
  finally {
    const objBadge = document.getElementById('pvObjBadge');
    if (objBadge) {
      objBadge.dataset.pending = String(Math.max(0, Number(objBadge.dataset.pending || 1) - 1));
      _hideBadgeIfDone();
    }
  }
}

async function showPolicy() {
  const adom = document.getElementById('pvAdom').value;
  const pkg  = document.getElementById('pvPackage').value;
  const path = pvPkgPaths[pkg] || pkg;
  if (!adom || !pkg) return;

  _pvObjLoadTag++;
  const myTag = _pvObjLoadTag;

  document.getElementById('pvLoading').style.display = '';
  document.getElementById('pvProgressWrap').style.display = 'block';
  document.getElementById('policyView').style.display = 'none';

  try {
    const resp = await fetch('/api/hygiene/policies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adom, package: pkg, path }),
    });
    let data;
    try { data = await resp.json(); } catch (_) { showError(`Server error (HTTP ${resp.status})`); return; }
    if (!resp.ok) { showError(data.error || 'Failed to load policies.'); return; }

    allPolicies = data.policies || [];
    pvMeta      = { adom, pkg };
    pvPage      = 1;
    pvSearch    = '';
    pvField     = '';
    pvRegex     = false;
    document.getElementById('pvSearch').value        = '';
    document.getElementById('pvFieldFilter').value   = '';
    document.getElementById('pvRegexMode').checked   = false;
    document.getElementById('pvSearchError').style.display = 'none';

    const ruleCount = _pvRuleCount(allPolicies);
    document.getElementById('policyViewTitle').textContent =
      `${ruleCount} rule${ruleCount !== 1 ? 's' : ''} in "${pkg}" (${adom})`;

    applyPvFilter();
    renderPolicyTable();
    document.getElementById('policyView').style.display = '';

    // Show badge and kick off both deferred loads in parallel (2 pending)
    const pblockNames = data.pblock_names || [];
    const pendingCount = 1 + (pblockNames.length ? 1 : 0); // objects always; pblocks only if present
    const objBadge = document.getElementById('pvObjBadge');
    if (objBadge) { objBadge.dataset.pending = String(pendingCount); objBadge.style.display = ''; }

    _loadPolicyObjects(adom, myTag);
    _loadPolicyPblocks(adom, pblockNames, myTag);
  } catch (err) {
    showError(err.message);
  } finally {
    document.getElementById('pvLoading').style.display = 'none';
    document.getElementById('pvProgressWrap').style.display = 'none';
  }
}

/* ── Policy filter logic ────────────────────────────────────────────────────── */
function applyPvFilter() {
  const errEl = document.getElementById('pvSearchError');
  errEl.style.display = 'none';

  if (!pvSearch) {
    pvFiltered = allPolicies;
    return;
  }

  let matcher;
  if (pvRegex) {
    try {
      const re = new RegExp(pvSearch, 'i');
      matcher = s => re.test(s);
    } catch (e) {
      errEl.textContent = `Invalid regex: ${e.message}`;
      errEl.style.display = '';
      pvFiltered = allPolicies;
      return;
    }
  } else {
    const q = pvSearch.toLowerCase();
    matcher = s => String(s).toLowerCase().includes(q);
  }

  pvFiltered = allPolicies.reduce((acc, p) => {
    if (p.policy_block !== undefined) {
      // Block header — include if block name matches, or filter its rules
      const blockMatch = matcher(p.policy_block || '');
      const matchedRules = (p.rules || []).filter(r => _pvRuleMatches(r, matcher));
      if (blockMatch || matchedRules.length > 0) {
        acc.push({ ...p, rules: blockMatch ? p.rules : matchedRules });
      }
      return acc;
    }
    if (_pvRuleMatches(p, matcher)) acc.push(p);
    return acc;
  }, []);
}

function _pvRuleCount(policies) {
  let n = 0;
  for (const p of policies) {
    if (p.policy_block !== undefined) n += (p.rules || []).length;
    else if (!p.implicit) n++;  // implicit deny is not counted as a user-defined rule
  }
  return n;
}

function _pvRuleMatches(r, matcher) {
  const fields = {
    name:    r.name || '',
    id:      String(r.id || ''),
    comment: r.comment || '',
    srcaddr: _pvAddrText(r.srcaddr_exp || r.srcaddr) + ' ' + (r.fsso_groups || []).join(' '),
    dstaddr: _pvAddrText(r.dstaddr_exp || r.dstaddr),
    service: _pvSvcText(r.service_exp || r.service),
    srcintf: (r.srcintf || []).join(' '),
    dstintf: (r.dstintf || []).join(' '),
  };
  return Object.values(fields).some(v => matcher(v));
}

function _pvAddrText(items) {
  if (!items) return '';
  if (Array.isArray(items)) {
    return items.map(i => {
      if (typeof i === 'string') return i;
      let t = i.name || '';
      if (i.detail) t += ' ' + i.detail;
      if (i.members) t += ' ' + i.members.join(' ');
      return t;
    }).join(' ');
  }
  return String(items);
}

function _pvSvcText(items) {
  if (!items) return '';
  if (Array.isArray(items)) {
    return items.map(i => {
      if (typeof i === 'string') return i;
      let t = i.name || '';
      if (i.members) t += ' ' + i.members.join(' ');
      return t;
    }).join(' ');
  }
  return String(items);
}

/* ── Object expansion HTML helpers ─────────────────────────────────────────── */
function _addrCellHtml(items) {
  if (!items || !items.length) return '<span style="color:var(--text-muted)">—</span>';
  return items.map(item => {
    if (typeof item === 'string') return `<div class="pv-obj">${esc(item)}</div>`;
    if (item.type === 'group') {
      const members = (item.members || []).map(m => `<div class="pv-member">↳ ${esc(m)}</div>`).join('');
      return `<div class="pv-obj pv-group" title="Address group">
        <span class="pv-group-icon">&#9650;</span>${esc(item.name)}
        <div class="pv-members">${members}</div>
      </div>`;
    }
    const detail = item.detail ? `<span class="pv-detail">${esc(item.detail)}</span>` : '';
    return `<div class="pv-obj">${esc(item.name)}${detail}</div>`;
  }).join('');
}

function _fssoGroupsHtml(groups) {
  if (!groups || !groups.length) return '';
  return groups.map(g => `<div class="pv-obj pv-fsso" title="FSSO/AD group"><span class="pv-fsso-icon">&#128100;</span>${esc(g)}</div>`).join('');
}

function _svcCellHtml(items) {
  if (!items || !items.length) return '<span style="color:var(--text-muted)">—</span>';
  return items.map(item => {
    if (typeof item === 'string') return `<div class="pv-obj">${esc(item)}</div>`;
    if (item.type === 'group') {
      const members = (item.members || []).map(m => `<div class="pv-member">↳ ${esc(m)}</div>`).join('');
      return `<div class="pv-obj pv-group" title="Service group">
        <span class="pv-group-icon">&#9650;</span>${esc(item.name)}
        <div class="pv-members">${members}</div>
      </div>`;
    }
    return `<div class="pv-obj">${esc(item.name)}</div>`;
  }).join('');
}

/* ── Render policy table ────────────────────────────────────────────────────── */
function _pvFlattenForPage(filtered) {
  // Expand block entries into [header-sentinel, rule, rule, ...] for pagination
  const flat = [];
  for (const p of filtered) {
    if (p.policy_block !== undefined) {
      flat.push({ _blockHeader: true, policy_block: p.policy_block, assigned: p.assigned, ruleCount: (p.rules || []).length });
      for (const r of (p.rules || [])) flat.push({ ...r, _inBlock: true });
    } else {
      flat.push(p);
    }
  }
  return flat;
}

function _pvRuleRow(p) {
  const statusColor = p.status === 'enable' ? 'var(--success, #22c55e)' : 'var(--text-muted)';
  const actionColor = p.action === 'deny' || p.action === 'block' ? '#ef4444' : '#22c55e';
  const srcHtml = _addrCellHtml(p.srcaddr_exp || (p.srcaddr || []).map(n => ({ name: n, type: 'object' })))
                + _fssoGroupsHtml(p.fsso_groups);
  const dstHtml = _addrCellHtml(p.dstaddr_exp || (p.dstaddr || []).map(n => ({ name: n, type: 'object' })));
  const svcHtml = _svcCellHtml(p.service_exp || (p.service || []).map(n => ({ name: n, type: 'object' })));
  const intfStr = [
    ...(p.srcintf || []).map(i => `<span class="pv-intf pv-intf-src" title="Source">${esc(i)}</span>`),
    ...(p.dstintf || []).map(i => `<span class="pv-intf pv-intf-dst" title="Destination">${esc(i)}</span>`),
  ].join('');

  if (p.implicit) {
    return `<tr style="background:repeating-linear-gradient(135deg,#fef2f2,#fef2f2 8px,#fff1f1 8px,#fff1f1 16px);border-top:2px solid #fca5a5">
      <td style="font-size:.8rem;color:#9ca3af;font-style:italic">—</td>
      <td><span style="font-size:.75rem;font-weight:600;color:#22c55e">enable</span></td>
      <td><span style="font-size:.75rem;font-weight:600;color:#ef4444">deny</span></td>
      <td><strong style="color:#b91c1c">Implicit Deny</strong><br><span style="font-size:.72rem;color:#9ca3af;font-style:italic">default</span></td>
      <td style="font-size:.8rem;color:#6b7280;font-style:italic">all</td>
      <td style="font-size:.8rem;color:#6b7280;font-style:italic">all</td>
      <td style="font-size:.8rem;color:#6b7280;font-style:italic">ALL</td>
      <td style="font-size:.78rem;color:#9ca3af;font-style:italic">any → any</td>
      <td style="font-size:.78rem;color:#9ca3af;font-style:italic">${esc(p.comment)}</td>
    </tr>`;
  }

  const indent = p._inBlock ? ' style="background:var(--bg-alt,#f8fafc)"' : '';
  const seqPrefix = p._inBlock ? '<span style="color:var(--text-muted);font-size:.7rem">↳ </span>' : '';
  return `<tr${p.status !== 'enable' ? ' style="opacity:.55"' : ''}${indent}>
    <td style="font-size:.8rem;color:var(--text-muted)">${seqPrefix}${esc(String(p.seq))}</td>
    <td><span style="font-size:.75rem;font-weight:600;color:${statusColor}">${esc(p.status)}</span></td>
    <td><span style="font-size:.75rem;font-weight:600;color:${actionColor}">${esc(p.action)}</span></td>
    <td><strong>${esc(p.name || '—')}</strong>${p.id && p.id !== p.name ? `<br><span style="font-size:.72rem;color:var(--text-muted)">id:${esc(p.id)}</span>` : ''}</td>
    <td style="font-size:.8rem">${srcHtml}</td>
    <td style="font-size:.8rem">${dstHtml}</td>
    <td style="font-size:.8rem">${svcHtml}</td>
    <td style="font-size:.78rem">${intfStr || '<span style="color:var(--text-muted)">—</span>'}</td>
    <td style="font-size:.78rem;color:var(--text-muted)">${esc(p.comment)}</td>
  </tr>`;
}

function renderPolicyTable() {
  const flat  = _pvFlattenForPage(pvFiltered);
  const filteredRuleCount = _pvRuleCount(pvFiltered);
  const totalRuleCount    = _pvRuleCount(allPolicies);
  const total = Math.ceil(flat.length / pvPageSize) || 1;
  pvPage      = Math.min(pvPage, total);
  const slice = flat.slice((pvPage - 1) * pvPageSize, pvPage * pvPageSize);

  const shown = filteredRuleCount === totalRuleCount
    ? `${totalRuleCount} rule${totalRuleCount !== 1 ? 's' : ''}`
    : `${filteredRuleCount} of ${totalRuleCount} rule${totalRuleCount !== 1 ? 's' : ''}`;
  document.getElementById('policyCount').textContent =
    `${shown} — page ${pvPage} of ${total}`;

  const tbody = document.getElementById('policyTbody');
  tbody.innerHTML = slice.map(p => {
    if (p._blockHeader) {
      const badge = p.assigned
        ? `<span style="background:#3b82f6;color:#fff;font-size:.7rem;padding:1px 6px;border-radius:3px;margin-left:6px">${p.ruleCount} rule${p.ruleCount !== 1 ? 's' : ''}</span>`
        : `<span style="background:#9ca3af;color:#fff;font-size:.7rem;padding:1px 6px;border-radius:3px;margin-left:6px">not assigned</span>`;
      return `<tr style="background:var(--bg-header,#eef1f8)">
        <td colspan="9" style="padding:.4rem .75rem;font-size:.8rem;font-weight:600;color:var(--text-secondary,#374151)">
          &#127758; Global Policy Block: ${esc(p.policy_block)}${badge}
        </td>
      </tr>`;
    }
    return _pvRuleRow(p);
  }).join('') || `<tr><td colspan="9" class="empty-state" style="padding:.85rem 1rem">No policies match your search.</td></tr>`;

  renderPolicyPagination(total);
}

/* ── Policy pagination ──────────────────────────────────────────────────────── */
function renderPolicyPagination(total) {
  const pg = document.getElementById('policyPagination');
  if (total <= 1) { pg.innerHTML = ''; return; }

  function btn(label, page, disabled, active) {
    return `<button class="pg-btn${active ? ' active' : ''}" data-ppage="${page}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }
  let html = btn('&laquo;&laquo;', 1, pvPage === 1, false);
  html += btn('&lsaquo;', pvPage - 1, pvPage === 1, false);
  const s = Math.max(1, pvPage - 2), e = Math.min(total, s + 4);
  for (let i = s; i <= e; i++) html += btn(i, i, false, i === pvPage);
  html += btn('&rsaquo;', pvPage + 1, pvPage === total, false);
  html += btn('&raquo;&raquo;', total, pvPage === total, false);
  pg.innerHTML = html;
}

/* ── Policy exports ─────────────────────────────────────────────────────────── */
function _filterHeader() {
  const lines = [];
  const meta  = pvMeta || {};
  lines.push(`Package: ${meta.pkg || ''} (ADOM: ${meta.adom || ''})`);
  lines.push(`Generated: ${new Date().toLocaleString()}`);
  lines.push(`Total rules: ${_pvRuleCount(allPolicies)}  Shown: ${_pvRuleCount(pvFiltered)}`);
  if (pvSearch) lines.push(`Search: "${pvSearch}"${pvField ? ` in field: ${pvField}` : ''}${pvRegex ? ' (regex)' : ''}`);
  return lines;
}

function _flatAddrNames(items) {
  if (!items) return [];
  return items.map(i => {
    if (typeof i === 'string') return i;
    const base = i.name || '';
    if (i.type === 'group' && i.members && i.members.length) {
      return `${base} [${i.members.join(', ')}]`;
    }
    return i.detail ? `${base} (${i.detail})` : base;
  });
}

function _flatSvcNames(items) {
  if (!items) return [];
  return items.map(i => {
    if (typeof i === 'string') return i;
    const base = i.name || '';
    if (i.type === 'group' && i.members && i.members.length) {
      return `${base} [${i.members.join(', ')}]`;
    }
    return base;
  });
}

function _pvExportRules(filtered) {
  // Flatten block entries into plain rule objects with a global_block label
  const rules = [];
  for (const p of filtered) {
    if (p.policy_block !== undefined) {
      for (const r of (p.rules || [])) rules.push({ ...r, _blockLabel: p.policy_block });
    } else {
      rules.push(p);
    }
  }
  return rules;
}

function pvExportCsv() {
  const header = ['Seq', 'ID', 'Name', 'Status', 'Action',
                  'Source', 'Destination', 'Service', 'Src Interface', 'Dst Interface', 'Comment', 'Global Block', 'Implicit'];
  const fh = _filterHeader().map(l => `# ${l}`);
  const lines = [...fh, header.join(',')];
  _pvExportRules(pvFiltered).forEach(p => {
    const q = s => `"${String(s ?? '').replace(/"/g, '""')}"`;
    const src = [..._flatAddrNames(p.srcaddr_exp || p.srcaddr), ...(p.fsso_groups || [])];
    const dst = _flatAddrNames(p.dstaddr_exp || p.dstaddr);
    const svc = _flatSvcNames(p.service_exp || p.service);
    lines.push([
      p.seq, q(p.id), q(p.name), p.status, p.action,
      q(src.join('; ')), q(dst.join('; ')), q(svc.join('; ')),
      q((p.srcintf || []).join('; ')), q((p.dstintf || []).join('; ')),
      q(p.comment), q(p._blockLabel || ''), p.implicit ? 'true' : 'false',
    ].join(','));
  });
  const meta = pvMeta || {};
  download(`policy_${meta.pkg || 'rules'}.csv`, lines.join('\r\n'), 'text/csv');
}

function pvExportJson() {
  const meta = pvMeta || {};
  const exportRules = _pvExportRules(pvFiltered);
  const payload = {
    package:   meta.pkg,
    adom:      meta.adom,
    generated: new Date().toISOString(),
    filters: {
      search:    pvSearch || null,
      field:     pvField  || null,
      regex:     pvRegex,
    },
    total_rules:    _pvRuleCount(allPolicies),
    filtered_rules: _pvRuleCount(pvFiltered),
    rules: exportRules.map(p => ({
      seq:          p.seq,
      id:           p.id,
      name:         p.name,
      status:       p.status,
      action:       p.action,
      global_block: p._blockLabel || null,
      srcaddr:      [..._flatAddrNames(p.srcaddr_exp || p.srcaddr), ...(p.fsso_groups || [])],
      dstaddr:      _flatAddrNames(p.dstaddr_exp || p.dstaddr),
      service:      _flatSvcNames(p.service_exp  || p.service),
      srcintf:      p.srcintf || [],
      dstintf:      p.dstintf || [],
      comment:      p.comment,
      implicit:         p.implicit || false,
      fsso_groups:      p.fsso_groups || [],
      srcaddr_expanded: p.srcaddr_exp || [],
      dstaddr_expanded: p.dstaddr_exp || [],
      service_expanded: p.service_exp || [],
    })),
  };
  download(`policy_${meta.pkg || 'rules'}.json`, JSON.stringify(payload, null, 2), 'application/json');
}

function pvExportPdf() {
  const meta = pvMeta || {};
  const fh   = _filterHeader();
  const title = `Policy Rules — ${meta.pkg || ''} (${meta.adom || ''})`;

  const tableRows = _pvFlattenForPage(pvFiltered).map(p => {
    if (p._blockHeader) {
      const label = p.assigned ? `${p.ruleCount} rule${p.ruleCount !== 1 ? 's' : ''}` : 'not assigned';
      return `<tr style="background:#eef1f8">
        <td colspan="9" style="font-weight:600;font-size:9px;padding:3px 6px">
          &#127758; Global Policy Block: ${esc(p.policy_block)} [${esc(label)}]
        </td>
      </tr>`;
    }
    if (p.implicit) {
      return `<tr style="background:#fef2f2;border-top:2px solid #fca5a5">
        <td style="color:#9ca3af;font-style:italic">—</td>
        <td style="color:#16a34a;font-weight:600">enable</td>
        <td style="color:#dc2626;font-weight:600">deny</td>
        <td><strong style="color:#b91c1c">Implicit Deny</strong><br><small style="font-style:italic">default</small></td>
        <td style="color:#6b7280;font-style:italic">all</td>
        <td style="color:#6b7280;font-style:italic">all</td>
        <td style="color:#6b7280;font-style:italic">ALL</td>
        <td style="color:#9ca3af;font-style:italic">any → any</td>
        <td style="color:#9ca3af;font-style:italic">${esc(p.comment)}</td>
      </tr>`;
    }
    const src = [..._flatAddrNames(p.srcaddr_exp || p.srcaddr), ...(p.fsso_groups || [])].join('<br>');
    const dst = _flatAddrNames(p.dstaddr_exp || p.dstaddr).join('<br>');
    const svc = _flatSvcNames(p.service_exp  || p.service).join('<br>');
    const actionColor = p.action === 'deny' || p.action === 'block' ? '#dc2626' : '#16a34a';
    const statusColor = p.status === 'enable' ? '#16a34a' : '#9ca3af';
    const bg = p._inBlock ? ' style="background:#f8fafc"' : '';
    return `<tr${p.status !== 'enable' ? ' style="opacity:.55"' : ''}${bg}>
      <td>${p._inBlock ? '↳ ' : ''}${esc(String(p.seq))}</td>
      <td style="color:${statusColor};font-weight:600">${esc(p.status)}</td>
      <td style="color:${actionColor};font-weight:600">${esc(p.action)}</td>
      <td><strong>${esc(p.name || '—')}</strong><br><small>id: ${esc(p.id)}</small></td>
      <td>${src}</td>
      <td>${dst}</td>
      <td>${svc}</td>
      <td>${esc((p.srcintf || []).join(', '))} → ${esc((p.dstintf || []).join(', '))}</td>
      <td style="color:#5a6478">${esc(p.comment)}</td>
    </tr>`;
  }).join('');

  const filterMeta = fh.map(l => `<div>${esc(l)}</div>`).join('');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:sans-serif;font-size:10px;color:#1a2133;margin:1cm}
  h1{font-size:14px;margin-bottom:4px}
  .meta{font-size:9px;color:#5a6478;margin-bottom:8px;border-left:3px solid #93c5fd;padding-left:6px}
  table{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:4px 6px;font-size:9px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:3px 6px;border-bottom:1px solid #e5e7eb;vertical-align:top;font-size:9px}
  small{color:#5a6478}
  @media print{body{margin:.5cm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">${filterMeta}</div>
<table>
  <thead><tr><th>#</th><th>Status</th><th>Action</th><th>Name / ID</th><th>Source</th><th>Destination</th><th>Service</th><th>Interfaces</th><th>Comment</th></tr></thead>
  <tbody>${tableRows}</tbody>
</table>
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.focus(); win.print(); }
}

/* ═══════════════════════════════════════════════════════════════════════════════
   OBJECT LOOKUP
   ═══════════════════════════════════════════════════════════════════════════════ */

async function runObjectLookup() {
  const adom  = document.getElementById('olAdom').value;
  const query = document.getElementById('olQuery').value.trim();
  if (!adom || !query) return;

  document.getElementById('olError').style.display    = 'none';
  document.getElementById('olResults').style.display  = 'none';
  document.getElementById('olSearchBtn').disabled     = true;
  document.getElementById('olRunning').style.display  = '';
  document.getElementById('olProgressWrap').style.display = 'block';

  try {
    const resp = await fetch(`/api/hygiene/adoms/${encodeURIComponent(adom)}/objects/lookup`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ query }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      document.getElementById('olError').textContent  = data.error || 'Lookup failed.';
      document.getElementById('olError').style.display = '';
      return;
    }
    olAllObjects = data.objects || [];
    olMeta       = { adom, query };
    olPage       = 1;
    olFilter     = '';
    document.getElementById('olFilter').value = '';
    applyOlFilter();
    renderOlTable();
    document.getElementById('olResults').style.display = '';
  } catch (err) {
    document.getElementById('olError').textContent  = err.message;
    document.getElementById('olError').style.display = '';
  } finally {
    document.getElementById('olSearchBtn').disabled    = false;
    document.getElementById('olRunning').style.display = 'none';
    document.getElementById('olProgressWrap').style.display = 'none';
  }
}

function applyOlFilter() {
  if (!olFilter) { olFiltered = olAllObjects; return; }
  const q = olFilter.toLowerCase();
  olFiltered = olAllObjects.filter(o =>
    o.name.toLowerCase().includes(q) ||
    (o.detail || '').toLowerCase().includes(q) ||
    (o.members || []).some(m =>
      (typeof m === 'string' ? m : (m.name + ' ' + (m.detail || ''))).toLowerCase().includes(q)
    )
  );
}

function renderOlTable() {
  const rows  = olFiltered;
  const total = Math.ceil(rows.length / olPageSize) || 1;
  olPage      = Math.min(olPage, total);
  const slice = rows.slice((olPage - 1) * olPageSize, olPage * olPageSize);
  const meta  = olMeta || {};

  const shown = rows.length === olAllObjects.length
    ? `${olAllObjects.length} object${olAllObjects.length !== 1 ? 's' : ''}`
    : `${rows.length} of ${olAllObjects.length} object${olAllObjects.length !== 1 ? 's' : ''}`;
  document.getElementById('olSummary').textContent =
    `${shown} matching "${meta.query || ''}" in ${meta.adom || ''}`;
  document.getElementById('olCount').textContent =
    `${shown} — page ${olPage} of ${total}`;

  const tbody = document.getElementById('olTbody');
  tbody.innerHTML = slice.map((o, i) => {
    const globalIdx = (olPage - 1) * olPageSize + i + 1;
    const typeBadge  = o.type === 'group'
      ? (o.category === 'service'
          ? `<span class="obj-type-badge obj-type-svcgrp">SVC Group</span>`
          : `<span class="obj-type-badge obj-type-group">Addr Group</span>`)
      : (o.category === 'service'
          ? `<span class="obj-type-badge obj-type-svc">Service</span>`
          : `<span class="obj-type-badge obj-type-object">Address</span>`);
    const catLabel = o.category === 'service' ? 'Service' : 'Address';

    let detailHtml = esc(o.detail || '—');
    if (o.members && o.members.length) {
      detailHtml += `<div class="obj-lookup-members">` +
        o.members.map(m => {
          const mname   = typeof m === 'string' ? m : (m.name || '');
          const mdetail = typeof m === 'string' ? '' : (m.detail || '');
          return `<div class="obj-lookup-member">↳ ${esc(mname)}${mdetail ? `<span style="color:var(--text-muted);margin-left:.4rem">${esc(mdetail)}</span>` : ''}</div>`;
        }).join('') +
        `</div>`;
    }
    return `<tr>
      <td style="font-size:.8rem;color:var(--text-muted)">${globalIdx}</td>
      <td><strong>${esc(o.name)}</strong></td>
      <td>${typeBadge}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${esc(catLabel)}</td>
      <td style="font-size:.8rem">${detailHtml}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="5" class="empty-state" style="padding:.85rem 1rem">No objects match your filter.</td></tr>`;

  renderOlPagination(total);
}

function renderOlPagination(total) {
  const pg = document.getElementById('olPagination');
  if (total <= 1) { pg.innerHTML = ''; return; }
  function btn(label, page, disabled, active) {
    return `<button class="pg-btn${active ? ' active' : ''}" data-olpage="${page}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }
  let html = btn('&laquo;&laquo;', 1, olPage === 1, false);
  html += btn('&lsaquo;', olPage - 1, olPage === 1, false);
  const s = Math.max(1, olPage - 2), e = Math.min(total, s + 4);
  for (let i = s; i <= e; i++) html += btn(i, i, false, i === olPage);
  html += btn('&rsaquo;', olPage + 1, olPage === total, false);
  html += btn('&raquo;&raquo;', total, olPage === total, false);
  pg.innerHTML = html;
}

/* ── Object Lookup exports ──────────────────────────────────────────────────── */
function olExportCsv() {
  const meta = olMeta || {};
  const header = ['#', 'Name', 'Type', 'Category', 'Detail', 'Members'];
  const fh = [
    `# ADOM: ${meta.adom || ''}`,
    `# Query: ${meta.query || ''}`,
    `# Generated: ${new Date().toLocaleString()}`,
    `# Total: ${olAllObjects.length}  Shown: ${olFiltered.length}`,
  ];
  const lines = [...fh, header.join(',')];
  olFiltered.forEach((o, i) => {
    const q = s => `"${String(s ?? '').replace(/"/g, '""')}"`;
    lines.push([
      i + 1,
      q(o.name),
      q(o.type === 'group' ? (o.category === 'service' ? 'SVC Group' : 'Addr Group') : (o.category === 'service' ? 'Service' : 'Address')),
      q(o.category),
      q(o.detail || ''),
      q((o.members || []).map(m => typeof m === 'string' ? m : (m.detail ? `${m.name} (${m.detail})` : m.name)).join('; ')),
    ].join(','));
  });
  download('object_lookup.csv', lines.join('\r\n'), 'text/csv');
}

function olExportJson() {
  const meta = olMeta || {};
  const payload = {
    adom:      meta.adom,
    query:     meta.query,
    generated: new Date().toISOString(),
    total:     olAllObjects.length,
    filtered:  olFiltered.length,
    objects:   olFiltered,
  };
  download('object_lookup.json', JSON.stringify(payload, null, 2), 'application/json');
}

function olExportPdf() {
  const meta  = olMeta || {};
  const title = `Object Lookup — "${meta.query || ''}" in ${meta.adom || ''}`;
  const ts    = new Date().toLocaleString();
  const tableRows = olFiltered.map((o, i) => {
    const typeLabel = o.type === 'group'
      ? (o.category === 'service' ? 'SVC Group' : 'Addr Group')
      : (o.category === 'service' ? 'Service' : 'Address');
    const memberHtml = o.members && o.members.length
      ? o.members.map(m => {
          const mname   = typeof m === 'string' ? m : (m.name || '');
          const mdetail = typeof m === 'string' ? '' : (m.detail || '');
          return `<br><small>↳ ${esc(mname)}${mdetail ? ` — ${esc(mdetail)}` : ''}</small>`;
        }).join('') : '';
    return `<tr>
      <td>${i + 1}</td>
      <td><strong>${esc(o.name)}</strong></td>
      <td>${esc(typeLabel)}</td>
      <td>${esc(o.category)}</td>
      <td>${esc(o.detail || '—')}${memberHtml}</td>
    </tr>`;
  }).join('');

  const html = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${esc(title)}</title>
<style>
  body{font-family:sans-serif;font-size:11px;color:#1a2133;margin:1.5cm}
  h1{font-size:15px;margin-bottom:4px}
  .meta{font-size:10px;color:#5a6478;margin-bottom:12px;border-left:3px solid #93c5fd;padding-left:6px}
  table{width:100%;border-collapse:collapse}
  th{background:#eef1f5;text-align:left;padding:5px 8px;font-size:10px;text-transform:uppercase;border-bottom:2px solid #d0d7e2}
  td{padding:4px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}
  small{color:#5a6478}
  @media print{body{margin:1cm}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="meta">Generated ${ts} &bull; ${olFiltered.length} of ${olAllObjects.length} objects</div>
<table>
  <thead><tr><th>#</th><th>Name</th><th>Type</th><th>Category</th><th>Detail / Members</th></tr></thead>
  <tbody>${tableRows}</tbody>
</table>
</body></html>`;

  const win = window.open('', '_blank');
  if (win) { win.document.write(html); win.document.close(); win.focus(); win.print(); }
}

/* ── Debounce helper ────────────────────────────────────────────────────────── */
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* ── Capture check labels from the rendered checkboxes ─────────────────────── */
function captureCheckLabels() {
  document.querySelectorAll('input[name=hygiene_check]').forEach(inp => {
    const label = inp.closest('label');
    if (label) checkLabels[inp.value] = label.textContent.trim();
  });
}

/* ══════════════════════════════════════════════════════════════════════════════
   EVENT WIRING
   ══════════════════════════════════════════════════════════════════════════════ */

/* ── Policy Rules selectors ─────────────────────────────────────────────────── */
document.getElementById('pvAdom').addEventListener('change', function () {
  if (this.value) {
    loadPvPackages(this.value);
  } else {
    const sel = document.getElementById('pvPackage');
    sel.innerHTML = '<option value="">— select package —</option>';
    sel.disabled = true;
    document.getElementById('policyView').style.display = 'none';
    allPolicies = [];
  }
  document.getElementById('pvPkgError').style.display = 'none';
});

/* ── Policy package direct-name loader ──────────────────────────────────────── */
async function pvLoadByName() {
  const adom  = document.getElementById('pvAdom').value;
  const typed = document.getElementById('pvPkgSearch').value.trim();
  const errEl = document.getElementById('pvPkgError');
  errEl.style.display = 'none';

  if (!adom) {
    errEl.textContent = 'Please select an ADOM first.';
    errEl.style.display = '';
    return;
  }
  if (!typed) return;

  // If packages not yet loaded for this ADOM, load them first
  if (document.getElementById('pvPackage').disabled) {
    await loadPvPackages(adom);
  }

  // Case-insensitive match against loaded package names
  const lower   = typed.toLowerCase();
  const matched = Object.keys(pvPkgPaths).find(name => name.toLowerCase() === lower);

  if (!matched) {
    errEl.textContent = `No package found matching "${typed}".`;
    errEl.style.display = '';
    return;
  }

  // Select it in the dropdown and trigger load
  const sel = document.getElementById('pvPackage');
  sel.value = matched;
  showPolicy();
}

document.getElementById('pvPkgLoadBtn').addEventListener('click', pvLoadByName);

document.getElementById('pvPkgSearch').addEventListener('keydown', e => {
  if (e.key === 'Enter') pvLoadByName();
});

document.getElementById('pvPkgSearch').addEventListener('input', () => {
  document.getElementById('pvPkgError').style.display = 'none';
});

document.getElementById('pvPackage').addEventListener('change', function () {
  if (this.value) {
    showPolicy();
  } else {
    document.getElementById('policyView').style.display = 'none';
    allPolicies = [];
  }
});

/* ── Hygiene selectors ──────────────────────────────────────────────────────── */
document.getElementById('hygieneAdom').addEventListener('change', function () {
  if (this.value) loadHygienePackages(this.value);
  else {
    const sel = document.getElementById('hygienePackage');
    sel.innerHTML = '<option value="">— select package —</option>';
    sel.disabled = true;
    document.getElementById('hygieneRunBtn').disabled = true;
  }
});

document.getElementById('hygienePackage').addEventListener('change', function () {
  document.getElementById('hygieneRunBtn').disabled = !this.value;
});

document.getElementById('hygieneRunBtn').addEventListener('click', runAnalysis);

document.getElementById('hygieneFilter').addEventListener('input', function () {
  filterText  = this.value;
  currentPage = 1;
  renderTable();
});

document.getElementById('hygienePageSize').addEventListener('change', function () {
  pageSize    = parseInt(this.value, 10);
  currentPage = 1;
  renderTable();
});

document.getElementById('hygieneCheckFilter').addEventListener('change', function () {
  filterCheck = this.value;
  currentPage = 1;
  renderTable();
});

document.getElementById('hygienePagination').addEventListener('click', e => {
  const btn = e.target.closest('[data-hpage]');
  if (!btn || btn.disabled) return;
  currentPage = parseInt(btn.dataset.hpage, 10);
  renderTable();
});

document.getElementById('hygieneTbody').addEventListener('click', e => {
  const btn = e.target.closest('.shadow-expand-btn');
  if (!btn) return;
  const targetId = btn.dataset.target;
  const detailRow = document.getElementById(targetId);
  if (!detailRow) return;
  const open = detailRow.style.display !== 'none';
  detailRow.style.display = open ? 'none' : '';
  btn.setAttribute('aria-expanded', String(!open));
  btn.innerHTML = open ? '&#9660;' : '&#9650;';
});

document.getElementById('exportCsv').addEventListener('click', exportCsv);
document.getElementById('exportJson').addEventListener('click', exportJson);
document.getElementById('exportPdf').addEventListener('click', exportPdf);

/* ── Policy viewer events ───────────────────────────────────────────────────── */
const debouncedPvSearch = debounce(() => {
  pvSearch = document.getElementById('pvSearch').value;
  pvPage   = 1;
  applyPvFilter();
  renderPolicyTable();
}, 250);

document.getElementById('pvSearch').addEventListener('input', debouncedPvSearch);

document.getElementById('pvFieldFilter').addEventListener('change', function () {
  pvField = this.value;
  pvPage  = 1;
  applyPvFilter();
  renderPolicyTable();
});

document.getElementById('pvRegexMode').addEventListener('change', function () {
  pvRegex = this.checked;
  pvPage  = 1;
  applyPvFilter();
  renderPolicyTable();
});

document.getElementById('policyPageSize').addEventListener('change', function () {
  pvPageSize = parseInt(this.value, 10);
  pvPage     = 1;
  renderPolicyTable();
});

document.getElementById('policyPagination').addEventListener('click', e => {
  const btn = e.target.closest('[data-ppage]');
  if (!btn || btn.disabled) return;
  const total = Math.ceil(_pvFlattenForPage(pvFiltered).length / pvPageSize) || 1;
  pvPage = Math.max(1, Math.min(total, parseInt(btn.dataset.ppage, 10)));
  renderPolicyTable();
});

document.getElementById('pvExportCsv').addEventListener('click', pvExportCsv);
document.getElementById('pvExportJson').addEventListener('click', pvExportJson);
document.getElementById('pvExportPdf').addEventListener('click', pvExportPdf);

// Click-to-expand address/service groups in the policy table
document.getElementById('policyTbody').addEventListener('click', e => {
  const grp = e.target.closest('.pv-group');
  if (!grp) return;
  grp.classList.toggle('pv-open');
});

/* ── Close buttons ──────────────────────────────────────────────────────────── */
document.getElementById('pvCloseBtn').addEventListener('click', () => {
  document.getElementById('policyView').style.display = 'none';
  document.getElementById('pvPackage').value = '';
  document.getElementById('pvPackage').disabled = true;
  document.getElementById('pvAdom').value = '';
  allPolicies = []; pvFiltered = [];
});

document.getElementById('hygieneCloseBtn').addEventListener('click', () => {
  document.getElementById('hygieneResults').style.display = 'none';
  allFindings = [];
  document.getElementById('hygienePackage').value = '';
  document.getElementById('hygienePackage').disabled = true;
  document.getElementById('hygieneAdom').value = '';
  document.getElementById('hygieneRunBtn').disabled = true;
});

document.getElementById('olCloseBtn').addEventListener('click', () => {
  document.getElementById('olResults').style.display = 'none';
  olAllObjects = []; olFiltered = [];
  document.getElementById('olQuery').value   = '';
  document.getElementById('olFilter').value  = '';
  document.getElementById('olAdom').value    = '';
  document.getElementById('olQuery').disabled   = true;
  document.getElementById('olSearchBtn').disabled = true;
});

/* ── Object Lookup events ───────────────────────────────────────────────────── */
document.getElementById('olAdom').addEventListener('change', function () {
  const hasAdom = !!this.value;
  document.getElementById('olQuery').disabled    = !hasAdom;
  document.getElementById('olSearchBtn').disabled = !hasAdom || !document.getElementById('olQuery').value.trim();
  if (!hasAdom) {
    document.getElementById('olResults').style.display = 'none';
    olAllObjects = []; olFiltered = [];
  }
});

document.getElementById('olQuery').addEventListener('input', function () {
  const adom = document.getElementById('olAdom').value;
  document.getElementById('olSearchBtn').disabled = !adom || !this.value.trim();
});

document.getElementById('olQuery').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('olSearchBtn').click();
});

document.getElementById('olSearchBtn').addEventListener('click', runObjectLookup);

document.getElementById('olFilter').addEventListener('input', debounce(function () {
  olFilter = this.value;
  olPage   = 1;
  applyOlFilter();
  renderOlTable();
}, 200));

document.getElementById('olPageSize').addEventListener('change', function () {
  olPageSize = parseInt(this.value, 10);
  olPage     = 1;
  renderOlTable();
});

document.getElementById('olPagination').addEventListener('click', e => {
  const btn = e.target.closest('[data-olpage]');
  if (!btn || btn.disabled) return;
  const total = Math.ceil(olFiltered.length / olPageSize) || 1;
  olPage = Math.max(1, Math.min(total, parseInt(btn.dataset.olpage, 10)));
  renderOlTable();
});

document.getElementById('olExportCsv').addEventListener('click', olExportCsv);
document.getElementById('olExportJson').addEventListener('click', olExportJson);
document.getElementById('olExportPdf').addEventListener('click', olExportPdf);

/* ── Init ───────────────────────────────────────────────────────────────────── */
captureCheckLabels();
loadAdoms();
