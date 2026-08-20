'use strict';

/* ── Utilities ─────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function getCSRF() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

/* ── State ─────────────────────────────────────────────────────────────────── */
let flows      = [];   // [{src, dst, service, comment}, ...]
let selections = [];   // [{adom, device, vdoms}]
let results    = [];   // analysis results from server
let metadata   = {};   // {change_number, owner, justification}

/* ── ADOM loader ────────────────────────────────────────────────────────────── */
async function loadAdoms() {
  const sel = document.getElementById('rrAdom');
  try {
    const resp = await fetch('/api/rule-review/adoms');
    if (resp.status === 401) { location.href = '/login'; return; }
    const adoms = await resp.json();
    if (!Array.isArray(adoms)) return;
    adoms.forEach(a => {
      const opt = document.createElement('option');
      opt.value = a; opt.textContent = a;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

async function loadDevices(adom) {
  const sel = document.getElementById('rrDevice');
  sel.innerHTML = '<option value="">Loading…</option>';
  sel.disabled = true;
  document.getElementById('rrAddDevBtn').disabled = true;
  document.getElementById('rrVdomRow').style.display = 'none';
  try {
    const resp = await fetch(`/api/rule-review/adoms/${encodeURIComponent(adom)}/devices`);
    if (resp.status === 401) { location.href = '/login'; return; }
    const devices = await resp.json();
    sel.innerHTML = '<option value="">— select firewall —</option>';
    if (Array.isArray(devices)) {
      devices.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.name;
        opt.textContent = d.ip ? `${d.name} (${d.ip})` : d.name;
        sel.appendChild(opt);
      });
    }
    sel.disabled = false;
  } catch (_) {
    sel.innerHTML = '<option value="">Failed to load</option>';
  }
}

async function loadVdoms(adom, device) {
  const vdomRow    = document.getElementById('rrVdomRow');
  const vdomChecks = document.getElementById('rrVdomChecks');
  document.getElementById('rrAddDevBtn').disabled = true;
  vdomRow.style.display = 'none';
  vdomChecks.innerHTML  = '';
  try {
    const resp = await fetch(
      `/api/rule-review/adoms/${encodeURIComponent(adom)}/devices/${encodeURIComponent(device)}/vdoms`
    );
    if (resp.status === 401) { location.href = '/login'; return; }
    const vdoms = await resp.json();
    if (Array.isArray(vdoms) && !(vdoms.length === 1 && vdoms[0] === 'root')) {
      vdoms.forEach(v => {
        const label = document.createElement('label');
        label.style.cssText = 'display:flex;align-items:center;gap:.3rem;font-size:.85rem;cursor:pointer';
        label.innerHTML = `<input type="checkbox" value="${esc(v)}" checked> ${esc(v)}`;
        vdomChecks.appendChild(label);
      });
      vdomRow.style.display = '';
    }
    document.getElementById('rrAddDevBtn').disabled = false;
  } catch (_) {
    document.getElementById('rrAddDevBtn').disabled = false;
  }
}

/* ── Zone-script status ─────────────────────────────────────────────────────── */
async function checkZoneStatus() {
  try {
    const resp = await fetch('/api/rule-review/zone-status');
    const data = await resp.json();
    const badge = document.getElementById('rrZoneStatus');
    badge.style.display = '';
    if (data.available) {
      badge.textContent = '✓ Zone policy database connected';
      badge.className   = 'rr-zone-badge rr-zone-ok';
    } else {
      badge.textContent = '⚠ Zone policy database not available';
      badge.className   = 'rr-zone-badge rr-zone-warn';
    }
  } catch (_) {}
}

/* ── Flow management ────────────────────────────────────────────────────────── */
function renderFlows() {
  const tbody = document.getElementById('rrFlowTbody');
  const wrap  = document.getElementById('rrFlowTableWrap');
  if (!flows.length) { wrap.style.display = 'none'; tbody.innerHTML = ''; updateReviewBtn(); return; }
  wrap.style.display = '';
  tbody.innerHTML = flows.map((f, i) => `
    <tr>
      <td style="color:var(--text-muted);font-size:.8rem">${i + 1}</td>
      <td><code>${esc(f.src)}</code></td>
      <td><code>${esc(f.dst)}</code></td>
      <td>${esc(f.service) || '<span class="text-muted">—</span>'}</td>
      <td style="color:var(--text-muted);font-size:.82rem">${esc(f.comment) || ''}</td>
      <td><button class="btn btn-sm btn-ghost rr-remove-btn" data-type="flow" data-idx="${i}" title="Remove">&#10005;</button></td>
    </tr>`).join('');
  updateReviewBtn();
}

function splitIPs(raw) {
  return raw.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
}

function addFlow(srcRaw, dstRaw, service, comment) {
  const srcs = splitIPs(srcRaw);
  const dsts = splitIPs(dstRaw);
  service = service.trim();
  comment = comment.trim();
  if (!srcs.length || !dsts.length) return;
  for (const src of srcs) {
    for (const dst of dsts) {
      flows.push({ src, dst, service, comment });
    }
  }
  renderFlows();
  clearFlowInputs();
}

function clearFlowInputs() {
  ['rrSrc','rrDst','rrSvc','rrComment'].forEach(id => {
    document.getElementById(id).value = '';
  });
}

/* ── Change Request metadata ────────────────────────────────────────────── */
function getMetadata() {
  return {
    change_number: (document.getElementById('rrChangeNumber').value || '').trim(),
    owner:         (document.getElementById('rrOwner').value || '').trim(),
    justification: (document.getElementById('rrJustification').value || '').trim(),
  };
}

function getFilePrefix() {
  const cn = (document.getElementById('rrChangeNumber').value || '').trim();
  if (cn) return cn;
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `rule-analysis-${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

/* ── Selection (firewall/VDOM) management ───────────────────────────────── */
function renderSelections() {
  const tbody = document.getElementById('rrSelectTbody');
  const wrap  = document.getElementById('rrSelectTableWrap');
  if (!selections.length) { wrap.style.display = 'none'; tbody.innerHTML = ''; updateReviewBtn(); return; }
  wrap.style.display = '';
  tbody.innerHTML = selections.map((s, i) => `
    <tr>
      <td style="color:var(--text-muted);font-size:.8rem">${i + 1}</td>
      <td>${esc(s.device)}</td>
      <td><span class="text-muted" style="font-size:.85rem">${esc(s.vdoms.join(', '))}</span></td>
      <td>${esc(s.adom)}</td>
      <td><button class="btn btn-sm btn-ghost rr-remove-btn" data-type="sel" data-idx="${i}" title="Remove">&#10005;</button></td>
    </tr>`).join('');
  updateReviewBtn();
}

function addSelection() {
  const adom   = document.getElementById('rrAdom').value;
  const device = document.getElementById('rrDevice').value;
  if (!adom || !device) return;

  const vdomRow  = document.getElementById('rrVdomRow');
  let vdoms;
  if (vdomRow.style.display === 'none') {
    vdoms = ['root'];
  } else {
    const checks = document.querySelectorAll('#rrVdomChecks input[type=checkbox]:checked');
    vdoms = Array.from(checks).map(c => c.value);
    if (!vdoms.length) vdoms = ['root'];
  }

  // Dedup: skip same adom+device+vdoms combo
  const key = `${adom}|${device}|${vdoms.sort().join(',')}`;
  if (selections.some(s => `${s.adom}|${s.device}|${s.vdoms.slice().sort().join(',')}` === key)) return;
  selections.push({ adom, device, vdoms });
  renderSelections();
}

function updateReviewBtn() {
  document.getElementById('rrReviewBtn').disabled = !(flows.length && selections.length);
}

/* ── CSV / XLSX import ──────────────────────────────────────────────────────── */
async function handleImport(file) {
  const statusEl = document.getElementById('rrImportStatus');
  statusEl.textContent = 'Parsing…';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const resp = await fetch('/api/rule-review/parse-import', { method: 'POST', headers: { 'X-CSRF-Token': getCSRF() }, body: fd });
    const data = await resp.json();
    if (!resp.ok) { statusEl.textContent = data.error || 'Import failed'; return; }
    const imported = data.rows || [];
    imported.forEach(r => flows.push(r));
    renderFlows();
    const errs = data.errors || [];
    statusEl.textContent = `Imported ${imported.length} row${imported.length !== 1 ? 's' : ''}` +
      (errs.length ? ` (${errs.length} error${errs.length !== 1 ? 's' : ''}: ${errs[0]})` : '');
  } catch (e) {
    statusEl.textContent = 'Import error: ' + e.message;
  }
  document.getElementById('rrImportFile').value = '';
}

/* ── Analysis ───────────────────────────────────────────────────────────────── */
async function runReview() {
  const errEl = document.getElementById('rrError');
  errEl.style.display = 'none';
  document.getElementById('rrResults').style.display   = 'none';
  document.getElementById('rrCliPanel').style.display  = 'none';
  document.getElementById('rrReviewBtn').disabled = true;
  document.getElementById('rrRunning').style.display   = '';
  checkZoneStatus();

  try {
    const resp = await fetch('/api/rule-review/analyze', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCSRF() },
      body:    JSON.stringify({ flows, selections, metadata: getMetadata() }),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || 'Analysis failed.'); return; }

    results  = data.results  || [];
    metadata = data.metadata || {};
    renderResults(data.zone_available);
    document.getElementById('rrResults').style.display = '';
    document.getElementById('rrStatusLine').textContent = `Last run: ${new Date().toLocaleString()}`;
  } catch (e) {
    showError(e.message);
  } finally {
    document.getElementById('rrReviewBtn').disabled = !(flows.length && selections.length);
    document.getElementById('rrRunning').style.display = 'none';
  }
}

function showError(msg) {
  const el = document.getElementById('rrError');
  el.textContent = msg;
  el.style.display = '';
}

/* ── Verdict / zone helpers ─────────────────────────────────────────────────── */
const VERDICT_LABEL = {
  PERMITTED:         'PERMITTED',
  EXPLICITLY_DENIED: 'EXPLICITLY DENIED',
  MODIFIABLE:        'MODIFIABLE',
  NEW_RULE_NEEDED:   'NEW RULE NEEDED',
  ERROR:             'Error',
};

function verdictClass(v) {
  return { PERMITTED: 'ALLOWED', EXPLICITLY_DENIED: 'BLOCKED',
           MODIFIABLE: 'UNKNOWN', NEW_RULE_NEEDED: 'UNKNOWN',
           ERROR: 'ERROR' }[v] || 'UNKNOWN';
}

function zoneClass(v) {
  return { ALLOWED: 'ALLOWED', BLOCKED: 'BLOCKED',
           UNKNOWN: 'UNKNOWN', UNAVAILABLE: 'UNKNOWN', ERROR: 'BLOCKED' }[v] || 'UNKNOWN';
}

function verdictLabel(v) {
  return VERDICT_LABEL[v] || v;
}

function zoneLabel(v) {
  if (v === 'UNKNOWN') return 'NO RULE';
  return v;
}

/* ── Governing rule HTML (matches zone-script style) ───────────────────────── */
function ruleRowHtml(p) {
  const svc = p.services && p.services.length
    ? `<span class="rr-rule-svc">[${esc(p.services.join(', '))}]</span>` : '';
  const sev = p.severity ? `<span class="rr-rule-sev">(${esc(p.severity)})</span>` : '';
  return `<div class="rr-rule-row">
    <span class="rr-rule-set">[${esc(p.policy_set || '')}]</span>
    ${esc(p.matched_from_zone || p.from_zone || '')} → ${esc(p.matched_to_zone || p.to_zone || '')}
    &nbsp;|&nbsp;
    <strong>${esc(p.access_type || '')}</strong>
    ${svc} ${sev}
  </div>`;
}

/* ── Path-relevance badge ───────────────────────────────────────────────────── */
function pathBadgeHtml(r) {
  const ip = r.path_in_path;
  if (ip === true)  return `<span class="rr-path-badge rr-path-yes">✓ In Path</span>`;
  if (ip === false) return `<span class="rr-path-badge rr-path-no">⚠ Not In Path</span>`;
  return `<span class="rr-path-badge rr-path-unknown">? Path Unknown</span>`;
}

/* ── Results rendering — zone-script card style ─────────────────────────────── */
function renderResults(zoneAvail) {
  const container = document.getElementById('rrResultCards');
  container.innerHTML = '';

  // Metadata banner (shown only if any field is populated)
  const metaBanner = document.getElementById('rrMetaBanner');
  if (metadata.change_number || metadata.owner || metadata.justification) {
    const parts = [];
    if (metadata.change_number) parts.push(`<strong>${esc(metadata.change_number)}</strong>`);
    if (metadata.owner)         parts.push(`Owner: ${esc(metadata.owner)}`);
    if (metadata.justification) parts.push(`<em>${esc(metadata.justification)}</em>`);
    metaBanner.innerHTML = parts.join(' &nbsp;|&nbsp; ');
    metaBanner.style.display = '';
  } else {
    metaBanner.style.display = 'none';
  }

  // Summary counts
  const vc = { PERMITTED: 0, EXPLICITLY_DENIED: 0, MODIFIABLE: 0, NEW_RULE_NEEDED: 0, ERROR: 0 };
  const zc = { ALLOWED: 0, BLOCKED: 0, UNKNOWN: 0 };
  results.forEach(r => {
    if (vc[r.verdict] !== undefined) vc[r.verdict]++;
    if (zc[r.zone_verdict] !== undefined) zc[r.zone_verdict]++;
  });

  const bar = document.getElementById('rrSummaryBar');
  let barHtml = `<span class="rr-summary-chip">${results.length} result${results.length !== 1 ? 's' : ''}</span>`;
  if (vc.PERMITTED)         barHtml += `<span class="rr-summary-chip chip-allowed">${vc.PERMITTED} Permitted</span>`;
  if (vc.NEW_RULE_NEEDED)   barHtml += `<span class="rr-summary-chip chip-unknown">${vc.NEW_RULE_NEEDED} New Rule Needed</span>`;
  if (vc.MODIFIABLE)        barHtml += `<span class="rr-summary-chip chip-warn">${vc.MODIFIABLE} Modifiable</span>`;
  if (vc.EXPLICITLY_DENIED) barHtml += `<span class="rr-summary-chip chip-blocked">${vc.EXPLICITLY_DENIED} Explicitly Denied</span>`;
  if (vc.ERROR)             barHtml += `<span class="rr-summary-chip chip-error">${vc.ERROR} Error</span>`;
  if (zoneAvail) {
    if (zc.BLOCKED)  barHtml += `<span class="rr-summary-chip chip-blocked">Zone: ${zc.BLOCKED} Blocked</span>`;
    if (zc.UNKNOWN)  barHtml += `<span class="rr-summary-chip chip-warn">Zone: ${zc.UNKNOWN} No Rule</span>`;
  }
  bar.innerHTML = barHtml;

  // One card per result
  results.forEach((r, idx) => {
    const vClass = verdictClass(r.verdict);
    const vLabel = verdictLabel(r.verdict);
    const zClass = zoneClass(r.zone_verdict);
    const zLabel = zoneLabel(r.zone_verdict);

    // Flow header
    const svcBadge = r.service
      ? `<span class="rr-flow-svc">${esc(r.service)}</span>` : '';
    const pathBadge = pathBadgeHtml(r);

    // Zone section
    let zoneHtml = '';
    if (r.zone_available) {
      const governing = r.zone_governing || [];
      const allPols   = r.zone_all_policies || [];
      let govHtml = '';
      if (governing.length) {
        govHtml = `<div class="rr-card-subsection">
          <div class="rr-subsection-label">Governing rule:</div>
          ${governing.map(ruleRowHtml).join('')}
        </div>`;
      } else if (r.zone_verdict === 'UNKNOWN') {
        govHtml = `<div class="rr-no-rule">No policy rule covers this zone pair — treat as implicitly blocked.</div>`;
      }

      let allPolsHtml = '';
      if (allPols.length > governing.length) {
        allPolsHtml = `<details class="rr-details">
          <summary class="rr-details-summary">All matching rules (${allPols.length})</summary>
          <div class="rr-details-body">${allPols.map(ruleRowHtml).join('')}</div>
        </details>`;
      }

      zoneHtml = `<div class="rr-card-zone-block">
        <div class="rr-card-row rr-zone-header">
          <span class="rr-zone-block-label">Zone Policy</span>
          <span class="verdict-${zClass} rr-zone-verdict">${esc(zLabel)}</span>
        </div>
        <div class="rr-card-row rr-zone-zones">
          <span>&#8599; Src zones: <strong>${esc((r.zone_src || []).join(', ') || '(none matched)')}</strong></span><br>
          <span>&#8600; Dst zones: <strong>${esc((r.zone_dst || []).join(', ') || '(none matched)')}</strong></span>
        </div>
        ${govHtml}
        ${allPolsHtml}
      </div>`;
    } else {
      zoneHtml = `<div class="rr-card-zone-block rr-zone-na">
        <span class="rr-zone-block-label">Zone Policy</span>
        <span class="text-muted" style="font-size:.8rem;margin-left:.5rem">not available</span>
      </div>`;
    }

    // FortiGate policy section
    let fgtHtml = '';
    if (r.matching_rules && r.matching_rules.length) {
      fgtHtml += `<div class="rr-card-subsection">
        <div class="rr-subsection-label">Matching rules:</div>
        ${r.matching_rules.map(m => `
        <div class="rr-rule-row">
          <span class="rr-rule-set">ID ${esc(m.id)}</span>
          ${m.name ? esc(m.name) : '<em>unnamed</em>'}
          &nbsp;|&nbsp;
          <strong style="color:${m.action === 'accept' ? 'var(--success)' : 'var(--danger)'}">${esc(m.action)}</strong>
        </div>`).join('')}
      </div>`;
    }
    if (r.modifiable_rules && r.modifiable_rules.length) {
      fgtHtml += `<div class="rr-card-subsection">
        <div class="rr-subsection-label">Modifiable rules:</div>
        ${r.modifiable_rules.map(m => `
        <div class="rr-rule-row">
          <span class="rr-rule-set">ID ${esc(m.id)}</span>
          ${m.name ? esc(m.name) : '<em>unnamed</em>'}
          &nbsp;|&nbsp; <span style="color:var(--warning)">${esc(m.suggestion)}</span>
        </div>`).join('')}
      </div>`;
    }

    // Path check section
    let pathHtml = '';
    if (r.path_notes && r.path_notes.length) {
      const routeInfo = [];
      if (r.path_src_iface) routeInfo.push(`Src → ${esc(r.path_src_iface)}`);
      if (r.path_dst_iface) routeInfo.push(`Dst → ${esc(r.path_dst_iface)}`);
      pathHtml = `<div class="rr-card-subsection rr-path-section rr-path-${r.path_in_path === true ? 'yes' : r.path_in_path === false ? 'no' : 'unknown'}">
        <div class="rr-subsection-label">Path Analysis (${esc(r.path_confidence || 'low')} confidence):</div>
        <div class="rr-path-note">${esc(r.path_notes[0] || '')}</div>
        ${routeInfo.length ? `<div class="rr-path-route">${routeInfo.join('  |  ')}</div>` : ''}
      </div>`;
    }

    // Notes
    const policyNotes = (r.notes || []).filter(n =>
      !n.startsWith('⚠ ZONE') && !n.startsWith('Zone policy:') &&
      !n.startsWith('⚠ PATH') && !n.startsWith('✓ PATH')
    );
    const notesHtml = policyNotes.length
      ? `<div class="rr-card-subsection">
          ${policyNotes.map(n => `<div class="rr-note">${esc(n)}</div>`).join('')}
        </div>` : '';

    const _riskLevel = (r.approval || {}).risk_level || '';
    const _riskBadge = _riskLevel
      ? `<span class="badge badge-risk-${_riskLevel}">${_riskLevel.toUpperCase()}</span>` : '';

    const card = document.createElement('div');
    card.className = `rr-result-card result-card-${vClass}`;
    card.innerHTML = `
      <div class="rr-card-header">
        <div class="rr-card-flow">
          <code>${esc(r.src)}</code>
          <span class="rr-arrow">→</span>
          <code>${esc(r.dst)}</code>
          ${svcBadge}
          <span class="rr-pkg-label">${r.device ? esc(r.device) + (r.vdom ? ' / ' + esc(r.vdom) : '') : esc(r.adom) + ' / ' + esc(r.pkg_name)}</span>
        </div>
        <div class="rr-card-badges">
          ${pathBadge}
          <span class="verdict-${vClass}">${esc(vLabel)}</span>
          ${_riskBadge}
          <button class="btn btn-sm btn-secondary rr-detail-btn" data-idx="${idx}" title="Full details">⋯</button>
        </div>
      </div>

      ${zoneHtml}

      <div class="rr-card-fgt-block">
        <div class="rr-zone-block-label" style="margin-bottom:.4rem">FortiGate Policy</div>
        ${fgtHtml || '<div class="rr-no-rule">No matching rules found.</div>'}
        ${notesHtml}
        ${pathHtml}
      </div>
    `;
    container.appendChild(card);
  });

  if (!results.length) {
    container.innerHTML = '<div class="empty-state" style="padding:1.5rem">No results returned.</div>';
  }

  // CLI panel
  const cliSnippets = results.filter(r => r.fortios_cli).map(r => r.fortios_cli);
  const cliPanel  = document.getElementById('rrCliPanel');
  const cliOutput = document.getElementById('rrCliOutput');
  if (cliSnippets.length) {
    cliOutput.textContent = cliSnippets.join('\n\n' + '─'.repeat(60) + '\n\n');
    cliPanel.style.display = '';
  } else {
    cliPanel.style.display = 'none';
  }
  document.getElementById('rrExportToolbar').style.display = results.length ? '' : 'none';
}

/* ── Detail modal ───────────────────────────────────────────────────────────── */
function showDetail(idx) {
  const r = results[idx];
  if (!r) return;

  const vClass = verdictClass(r.verdict);
  const vLabel = verdictLabel(r.verdict);
  const zClass = zoneClass(r.zone_verdict);
  const zLabel = zoneLabel(r.zone_verdict);

  let html = `
    <div class="rr-detail-grid">
      <div class="rr-detail-row"><span class="rr-detail-label">Source</span><code>${esc(r.src)}</code></div>
      <div class="rr-detail-row"><span class="rr-detail-label">Destination</span><code>${esc(r.dst)}</code></div>
      <div class="rr-detail-row"><span class="rr-detail-label">Service</span>${esc(r.service) || '<em>any</em>'}</div>
      <div class="rr-detail-row"><span class="rr-detail-label">ADOM</span>${esc(r.adom)}</div>
      ${r.device ? `<div class="rr-detail-row"><span class="rr-detail-label">Device</span>${esc(r.device)}</div>` : ''}
      ${r.vdom ? `<div class="rr-detail-row"><span class="rr-detail-label">VDOM</span>${esc(r.vdom)}</div>` : `<div class="rr-detail-row"><span class="rr-detail-label">Package</span>${esc(r.pkg_name)}</div>`}
      <div class="rr-detail-row"><span class="rr-detail-label">FGT Verdict</span>
        <span class="verdict-${vClass}" style="font-weight:700">${esc(vLabel)}</span></div>
    </div>`;

  // Zone policy
  html += `<div class="rr-detail-section">
    <div class="rr-detail-section-title">Zone Segmentation Policy
      ${r.zone_available ? `<span class="verdict-${zClass}" style="margin-left:.5rem;font-weight:700">${esc(zLabel)}</span>` : '<span class="text-muted" style="margin-left:.5rem;font-size:.8rem">not available</span>'}
    </div>`;
  if (r.zone_available) {
    html += `<div class="rr-detail-row"><span class="rr-detail-label">Source Zones</span>
        ${esc((r.zone_src || []).join(', ') || '(none matched)')}</div>
      <div class="rr-detail-row"><span class="rr-detail-label">Dest Zones</span>
        ${esc((r.zone_dst || []).join(', ') || '(none matched)')}</div>`;
    if (r.zone_governing && r.zone_governing.length) {
      html += `<div style="margin-top:.5rem"><div class="rr-subsection-label">Governing rule:</div>
        ${r.zone_governing.map(ruleRowHtml).join('')}</div>`;
    } else if (r.zone_verdict === 'UNKNOWN') {
      html += `<div class="rr-no-rule">No policy rule covers this zone pair — treat as implicitly blocked.</div>`;
    }
    const allPols = r.zone_all_policies || [];
    if (allPols.length > (r.zone_governing || []).length) {
      html += `<details class="rr-details" style="margin-top:.4rem">
        <summary class="rr-details-summary">All matching rules (${allPols.length})</summary>
        <div class="rr-details-body">${allPols.map(ruleRowHtml).join('')}</div>
      </details>`;
    }
  }
  html += `</div>`;

  // Path analysis
  html += `<div class="rr-detail-section">
    <div class="rr-detail-section-title">Path Analysis</div>`;
  if (r.path_in_path === true)  html += `<div style="color:var(--success);font-weight:600;margin-bottom:.35rem">✓ Device is in the traffic path</div>`;
  if (r.path_in_path === false) html += `<div style="color:var(--warning);font-weight:600;margin-bottom:.35rem">⚠ Device may NOT be in the traffic path — proceed with caution</div>`;
  if (r.path_in_path === null)  html += `<div style="color:var(--text-muted);margin-bottom:.35rem">Path data unavailable</div>`;

  if (r.path_src_iface || r.path_src_route) {
    html += `<div class="rr-detail-row"><span class="rr-detail-label">Src Interface</span>${esc(r.path_src_iface || '—')}</div>`;
    if (r.path_src_route) {
      html += `<div class="rr-detail-row"><span class="rr-detail-label">Src Route</span>
        ${esc(r.path_src_route.network)} via ${esc(r.path_src_route.gateway || 'direct')} (${esc(r.path_src_route.interface || '?')})</div>`;
    }
  }
  if (r.path_dst_iface || r.path_dst_route) {
    html += `<div class="rr-detail-row"><span class="rr-detail-label">Dst Interface</span>${esc(r.path_dst_iface || '—')}</div>`;
    if (r.path_dst_route) {
      html += `<div class="rr-detail-row"><span class="rr-detail-label">Dst Route</span>
        ${esc(r.path_dst_route.network)} via ${esc(r.path_dst_route.gateway || 'direct')} (${esc(r.path_dst_route.interface || '?')})</div>`;
    }
  }
  (r.path_notes || []).forEach(n => {
    html += `<div class="rr-note" style="margin-top:.25rem">${esc(n)}</div>`;
  });
  html += `</div>`;

  // FortiGate matching rules
  if (r.matching_rules && r.matching_rules.length) {
    html += `<div class="rr-detail-section">
      <div class="rr-detail-section-title">Matching Rules</div>
      <table class="data-table" style="font-size:.82rem">
        <thead><tr><th>ID</th><th>Name</th><th>Action</th></tr></thead>
        <tbody>${r.matching_rules.map(m => `<tr>
          <td>${esc(m.id)}</td>
          <td>${esc(m.name || '—')}</td>
          <td style="font-weight:600;color:${m.action==='accept'?'var(--success)':'var(--danger)'}">${esc(m.action)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
  }

  if (r.modifiable_rules && r.modifiable_rules.length) {
    html += `<div class="rr-detail-section">
      <div class="rr-detail-section-title">Rules That Could Be Modified</div>
      <table class="data-table" style="font-size:.82rem">
        <thead><tr><th>ID</th><th>Name</th><th>Suggestion</th></tr></thead>
        <tbody>${r.modifiable_rules.map(m => `<tr>
          <td>${esc(m.id)}</td><td>${esc(m.name || '—')}</td>
          <td style="color:var(--warning)">${esc(m.suggestion)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
  }

  // All notes
  const allNotes = r.notes || [];
  if (allNotes.length) {
    html += `<div class="rr-detail-section">
      <div class="rr-detail-section-title">All Notes</div>
      ${allNotes.map(n => `<div class="rr-note">${esc(n)}</div>`).join('')}
    </div>`;
  }

  // CLI
  if (r.fortios_cli) {
    html += `<div class="rr-detail-section">
      <div class="rr-detail-section-title">FortiOS CLI</div>
      <pre class="rr-cli-block" style="margin-top:.5rem">${esc(r.fortios_cli)}</pre>
    </div>`;
  }

  // Planner fields
  html += renderObjectPlans(r.object_plans);
  html += renderApproval(r.approval);
  html += renderAlternative(r.alternative);
  html += renderPermissivenessWarnings(r.permissiveness_warnings);

  document.getElementById('rrModalTitle').textContent =
    `${r.src} → ${r.dst}${r.service ? ' : ' + r.service : ''} — ${r.device || r.pkg_name}`;
  document.getElementById('rrModalBody').innerHTML = html;
  document.getElementById('rrDetailModal').style.display = '';
}

/* ── Planner render helpers ─────────────────────────────────────────────────── */
function renderObjectPlans(plans) {
  if (!plans || !plans.length) return '';
  const rows = plans.map(o => {
    const actionBadge = o.action === 'reuse'
      ? '<span class="badge badge-success">REUSE</span>'
      : '<span class="badge badge-warning">CREATE</span>';
    const cliBlock = o.cli
      ? `<pre class="cli-block cli-block-sm">${esc(o.cli)}</pre>`
      : '';
    return `<tr>
      <td>${esc(o.role)}</td>
      <td>${esc(o.obj_type)}</td>
      <td><code>${esc(o.name)}</code></td>
      <td>${actionBadge}</td>
      <td>${cliBlock}</td>
    </tr>`;
  }).join('');
  return `
    <div class="rr-detail-section object-plans-section">
      <div class="rr-detail-section-title">Object Plan</div>
      <table class="object-plans-table">
        <thead><tr><th>Role</th><th>Type</th><th>Name</th><th>Action</th><th>CLI</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderApproval(approval) {
  if (!approval || !approval.risk_level) return '';
  const approvers = (approval.approvers || []).join(', ') || 'None listed';
  const sla = approval.sla_hours ? `${approval.sla_hours}h SLA` : '';
  const window_ = approval.change_window || '';
  return `
    <div class="rr-detail-section approval-section">
      <div class="rr-detail-section-title">Approval Requirements <span class="badge badge-risk-${approval.risk_level}">${approval.risk_level.toUpperCase()}</span></div>
      <table class="approval-table">
        <tr><td>Approvers</td><td>${esc(approvers)}</td></tr>
        ${approval.peer_review ? `<tr><td>Peer Review</td><td>${esc(approval.peer_review)}</td></tr>` : ''}
        ${approval.security_review ? `<tr><td>Security Review</td><td>${esc(approval.security_review)}</td></tr>` : ''}
        ${window_ ? `<tr><td>Change Window</td><td>${esc(window_)}</td></tr>` : ''}
        ${sla ? `<tr><td>SLA</td><td>${esc(sla)}</td></tr>` : ''}
      </table>
    </div>`;
}

function renderAlternative(alt) {
  if (!alt) return '';
  const membersList = (alt.member_names || []).map(n => `<code>${esc(n)}</code>`).join(', ');
  const cliContent = alt.group_cli || alt.direct_cli || '';
  const affectedNote = alt.affected_count > 0
    ? `<div class="alert alert-warning">&#9888; Appending to group also affects ${alt.affected_count} other rule(s).</div>`
    : '';
  const warnList = (alt.warnings || []).map(w => `<li>${esc(w)}</li>`).join('');
  return `
    <div class="rr-detail-section alternative-section alert alert-info">
      <strong>Alternative Available:</strong> ${esc(alt.summary)}
      <br>Members: ${membersList}
      ${affectedNote}
      ${warnList ? `<ul>${warnList}</ul>` : ''}
      ${cliContent ? `<pre class="cli-block cli-block-sm">${esc(cliContent)}</pre>` : ''}
      <small class="text-muted">Choose ONE option — new rule OR this alternative, not both.</small>
    </div>`;
}

function renderPermissivenessWarnings(warnings) {
  if (!warnings || !warnings.length) return '';
  const items = warnings.map(w => `<li class="text-warning">&#9888; ${esc(w)}</li>`).join('');
  return `<div class="rr-detail-section"><ul class="permissiveness-warnings">${items}</ul></div>`;
}

/* ── Clear all ──────────────────────────────────────────────────────────────── */
function clearAll() {
  flows      = [];
  selections = [];
  results    = [];
  metadata   = {};
  renderFlows();
  renderSelections();
  document.getElementById('rrResults').style.display    = 'none';
  document.getElementById('rrCliPanel').style.display   = 'none';
  document.getElementById('rrExportToolbar').style.display = 'none';
  document.getElementById('rrError').style.display      = 'none';
  document.getElementById('rrMetaBanner').style.display = 'none';
  document.getElementById('rrStatusLine').textContent = '';
  document.getElementById('rrZoneStatus').style.display = 'none';
  clearFlowInputs();
  document.getElementById('rrChangeNumber').value = '';
  document.getElementById('rrOwner').value = '';
  document.getElementById('rrJustification').value = '';
  document.getElementById('rrMetaBody').style.display = 'none';
  document.getElementById('rrMetaArrow').innerHTML = '&#9654;';
}

/* ── CLI copy / download ────────────────────────────────────────────────────── */
function copyCli() {
  const text = document.getElementById('rrCliOutput').textContent;
  navigator.clipboard.writeText(text).catch(() => {});
}

function downloadCli() {
  const text = document.getElementById('rrCliOutput').textContent;
  const a  = document.createElement('a');
  const bl = new Blob([text], { type: 'text/plain' });
  a.href   = URL.createObjectURL(bl);
  a.download = 'rule_review_cli.txt';
  a.click();
  URL.revokeObjectURL(a.href);
}

function downloadHtmlReport() {
  const prefix = getFilePrefix();
  const now    = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  const user   = (typeof window._username !== 'undefined') ? window._username : '';

  const VERDICT_CSS = {
    PERMITTED:         'color:#1a7f3c;font-weight:700',
    EXPLICITLY_DENIED: 'color:#c0392b;font-weight:700',
    MODIFIABLE:        'color:#1a6fa0;font-weight:700',
    NEW_RULE_NEEDED:   'color:#d35400;font-weight:700',
    ERROR:             'color:#7f8c8d;font-weight:700',
  };

  function flowSections() {
    const groups = new Map();
    results.forEach(r => {
      const key = `${r.src}||${r.dst}||${r.service}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    });

    let html = '';
    let flowIdx = 1;
    groups.forEach((fwResults, key) => {
      const [src, dst, svc] = key.split('||');
      html += `<section class="flow-section">
        <h2>Flow ${flowIdx++}: ${esc(src)} &rarr; ${esc(dst)}${svc ? ' &nbsp;<code>' + esc(svc) + '</code>' : ''}</h2>`;

      fwResults.forEach(r => {
        const vstyle = VERDICT_CSS[r.verdict] || 'color:#555;font-weight:700';
        const label  = verdictLabel(r.verdict);
        const devLabel = r.device ? `${esc(r.device)}${r.vdom ? ' / ' + esc(r.vdom) : ''}` : esc(r.pkg_name);
        html += `<details open class="fw-result">
          <summary><span style="${vstyle}">[${esc(label)}]</span> ${devLabel}</summary>`;

        if (r.verdict === 'ERROR') {
          html += `<p class="error-msg">&#9888; ${esc(r.error || r.notes?.[0] || 'Error')}</p>`;
        }

        if (r.matching_rules && r.matching_rules.length) {
          html += `<p><strong>Matched rule${r.matching_rules.length > 1 ? 's' : ''}:</strong> ` +
            r.matching_rules.map(m => `#${esc(m.id)} ${esc(m.name || '')} [${esc(m.action)}]`).join(', ') +
            `</p>`;
        }

        if (r.path_in_path === true)  html += `<p class="path-ok">&#10003; In path: src via ${esc(r.path_src_iface||'?')}, dst via ${esc(r.path_dst_iface||'?')}</p>`;
        if (r.path_in_path === false) html += `<p class="path-warn">&#9888; May not be in path — proceed with caution</p>`;

        if ((r.verdict === 'NEW_RULE_NEEDED' || r.verdict === 'MODIFIABLE') && r.fortios_cli) {
          html += `<h4>Option A — Recommended action</h4><pre>${esc(r.fortios_cli)}</pre>`;
        }
        if (r.alternative && r.alternative.group_cli) {
          html += `<h4>Option B — Extend group ${esc(r.alternative.group_name || '')}</h4>` +
            `<pre>${esc(r.alternative.group_cli)}</pre>`;
          if (r.alternative.affected_count > 0) {
            html += `<p class="warn-note">&#9888; Affects ${r.alternative.affected_count} other rule(s).</p>`;
          }
        }

        html += `</details>`;
      });
      html += `</section>`;
    });
    return html;
  }

  const metaRows = [
    metadata.change_number ? `<tr><td>Change</td><td>${esc(metadata.change_number)}</td></tr>` : '',
    metadata.owner         ? `<tr><td>Owner</td><td>${esc(metadata.owner)}</td></tr>` : '',
    `<tr><td>Generated</td><td>${esc(now)}</td></tr>`,
    user                   ? `<tr><td>Generated by</td><td>${esc(user)}</td></tr>` : '',
    metadata.justification ? `<tr><td>Justification</td><td>${esc(metadata.justification)}</td></tr>` : '',
  ].filter(Boolean).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rule Validation Report${metadata.change_number ? ' — ' + esc(metadata.change_number) : ''}</title>
<style>
  body{font-family:Segoe UI,Arial,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222;font-size:.95rem}
  h1{margin-bottom:.25rem;color:#1a2a40;font-size:1.4rem}
  h2{margin:1.5rem 0 .5rem;font-size:1.1rem;border-bottom:2px solid #ddd;padding-bottom:.25rem}
  h4{margin:.75rem 0 .25rem;font-size:.92rem;color:#333}
  table.meta{border-collapse:collapse;margin-bottom:1.5rem;font-size:.88rem}
  table.meta td{padding:.25rem .75rem .25rem 0;vertical-align:top}
  table.meta td:first-child{font-weight:600;color:#555;white-space:nowrap;padding-right:1rem}
  details.fw-result{margin:.5rem 0;border:1px solid #ddd;border-radius:4px;padding:.5rem .75rem}
  details.fw-result summary{cursor:pointer;font-size:.93rem;user-select:none}
  pre{background:#f5f5f5;padding:.6rem .85rem;border-radius:4px;font-size:.8rem;white-space:pre-wrap;overflow-x:auto;margin:.35rem 0 .5rem}
  .path-ok{color:#1a7f3c;margin:.25rem 0}
  .path-warn{color:#d35400;margin:.25rem 0}
  .error-msg{color:#c0392b;margin:.25rem 0}
  .warn-note{color:#d35400;margin:.25rem 0;font-size:.85rem}
  footer{margin-top:3rem;font-size:.78rem;color:#888;text-align:center;border-top:1px solid #eee;padding-top:.75rem}
  @media print{details{display:block!important}details>*{display:block!important}}
</style>
</head>
<body>
<h1>Rule Validation Report</h1>
<table class="meta">${metaRows}</table>
${flowSections()}
<footer>Generated by 4THealth Rule Validation</footer>
</body>
</html>`;

  const a  = document.createElement('a');
  const bl = new Blob([html], { type: 'text/html' });
  a.href     = URL.createObjectURL(bl);
  a.download = `${prefix}-report.html`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function downloadCliConfig() {
  const prefix = getFilePrefix();
  const now    = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  const actionable = results.filter(r =>
    r.verdict === 'NEW_RULE_NEEDED' || r.verdict === 'MODIFIABLE'
  );
  const permitted = results.filter(r =>
    r.verdict === 'PERMITTED' || r.verdict === 'EXPLICITLY_DENIED'
  );

  const header = [
    '# ================================================================',
    `# Rule Validation CLI Configuration`,
    `# Change:    ${metadata.change_number || '(none)'}`,
    `# Owner:     ${metadata.owner || '(none)'}`,
    `# Generated: ${now}`,
    '# ================================================================',
  ];

  if (permitted.length) {
    header.push('# Firewalls with no changes required:');
    const seen = new Set();
    permitted.forEach(r => {
      const k = r.device ? `${r.device}${r.vdom ? ' / ' + r.vdom : ''}` : r.pkg_name;
      if (!seen.has(k)) { seen.add(k); header.push(`#   ${k} — ${r.verdict}`); }
    });
    header.push('# ================================================================');
  }

  const byDevice = new Map();
  actionable.forEach(r => {
    const k = r.device ? `${r.device}||${r.vdom || 'root'}` : r.pkg_name;
    if (!byDevice.has(k)) byDevice.set(k, []);
    byDevice.get(k).push(r);
  });

  const sections = [];
  byDevice.forEach((rList, key) => {
    const [dev, vdom] = key.split('||');
    sections.push('');
    sections.push('# ----------------------------------------------------------------');
    sections.push(`# Device: ${dev}${vdom ? ' / VDOM: ' + vdom : ''}`);
    sections.push('# ----------------------------------------------------------------');
    rList.forEach(r => {
      sections.push('');
      sections.push(`# Flow: ${r.src} -> ${r.dst}${r.service ? '  ' + r.service : ''}`);
      sections.push(`# Verdict: ${r.verdict}`);
      if (r.fortios_cli) {
        sections.push('# --- Recommended ---');
        sections.push(r.fortios_cli);
      }
      if (r.alternative && r.alternative.group_cli) {
        sections.push(`# --- Alternative: extend group ${r.alternative.group_name || ''} ---`);
        sections.push(r.alternative.group_cli);
      }
    });
  });

  if (!sections.length && !actionable.length) {
    sections.push('');
    sections.push('# No changes required — all flows are already permitted or denied.');
  }

  const text = [...header, ...sections].join('\n') + '\n';
  const a  = document.createElement('a');
  const bl = new Blob([text], { type: 'text/plain' });
  a.href     = URL.createObjectURL(bl);
  a.download = `${prefix}-config.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ── Event wiring ───────────────────────────────────────────────────────────── */
document.getElementById('rrAdom').addEventListener('change', function () {
  const devSel = document.getElementById('rrDevice');
  devSel.innerHTML = '<option value="">— select firewall —</option>';
  devSel.disabled = true;
  document.getElementById('rrAddDevBtn').disabled = true;
  document.getElementById('rrVdomRow').style.display = 'none';
  if (this.value) loadDevices(this.value);
});

document.getElementById('rrDevice').addEventListener('change', function () {
  const adom = document.getElementById('rrAdom').value;
  if (this.value && adom) loadVdoms(adom, this.value);
  else {
    document.getElementById('rrVdomRow').style.display = 'none';
    document.getElementById('rrAddDevBtn').disabled = true;
  }
});

document.getElementById('rrAddFlowBtn').addEventListener('click', () => {
  addFlow(
    document.getElementById('rrSrc').value,
    document.getElementById('rrDst').value,
    document.getElementById('rrSvc').value,
    document.getElementById('rrComment').value,
  );
});

document.getElementById('rrComment').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('rrAddFlowBtn').click();
});

document.getElementById('rrAddDevBtn').addEventListener('click', addSelection);
document.getElementById('rrReviewBtn').addEventListener('click', runReview);
document.getElementById('rrClearBtn').addEventListener('click', clearAll);
document.getElementById('rrMetaToggle').addEventListener('click', () => {
  const body  = document.getElementById('rrMetaBody');
  const arrow = document.getElementById('rrMetaArrow');
  const open  = body.style.display !== 'none';
  body.style.display  = open ? 'none' : '';
  arrow.innerHTML = open ? '&#9654;' : '&#9660;';
});
document.getElementById('rrCopyCliBtn').addEventListener('click', copyCli);
document.getElementById('rrDownloadCliBtn').addEventListener('click', downloadCli);
document.getElementById('rrHtmlReportBtn').addEventListener('click', downloadHtmlReport);
document.getElementById('rrCliConfigBtn').addEventListener('click', downloadCliConfig);

document.getElementById('rrModalClose').addEventListener('click', () => {
  document.getElementById('rrDetailModal').style.display = 'none';
});
document.getElementById('rrDetailModal').addEventListener('click', e => {
  if (e.target === document.getElementById('rrDetailModal'))
    document.getElementById('rrDetailModal').style.display = 'none';
});

document.getElementById('rrFlowTbody').addEventListener('click', e => {
  const btn = e.target.closest('.rr-remove-btn');
  if (!btn || btn.dataset.type !== 'flow') return;
  flows.splice(parseInt(btn.dataset.idx, 10), 1);
  renderFlows();
});

document.getElementById('rrSelectTbody').addEventListener('click', e => {
  const btn = e.target.closest('.rr-remove-btn');
  if (!btn || btn.dataset.type !== 'sel') return;
  selections.splice(parseInt(btn.dataset.idx, 10), 1);
  renderSelections();
});

document.getElementById('rrResultCards').addEventListener('click', e => {
  const btn = e.target.closest('.rr-detail-btn');
  if (btn) showDetail(parseInt(btn.dataset.idx, 10));
});

document.getElementById('rrImportFile').addEventListener('change', function () {
  if (this.files && this.files[0]) handleImport(this.files[0]);
});

/* ── Init ───────────────────────────────────────────────────────────────────── */
loadAdoms();
checkZoneStatus();
document.getElementById('rrZoneStatus').style.display = '';
