/* Admin page — groups management + application log viewer */
(function () {
  'use strict';

  // ── Sub-tab switching ──────────────────────────────────────────────────────
  document.querySelectorAll('.admin-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.admin-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.admin-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.panel).classList.add('active');
      if (btn.dataset.panel === 'logs') loadLogs();
      if (btn.dataset.panel === 'map-regions' && !_mapRegionsLoaded) loadMapRegions();
      if (btn.dataset.panel === 'external-api' && !_extApiLoaded) loadExtApi();
      if (btn.dataset.panel === 'config-diff') { loadSMTP(); loadJobs(); }
    });
  });

  // ══════════════════════  GROUPS  ═══════════════════════════════════════════

  let allTabs  = [];
  let allUsers = [];
  let allAdoms = [];          // [{name}] from /admin/api/adoms
  let pendingDeleteName = null;

  async function loadGroups() {
    const tbody = document.getElementById('groupsTbody');
    tbody.innerHTML = '<tr><td colspan="5" class="loading-placeholder">Loading…</td></tr>';

    const [groupsRes, tabsRes, usersRes, adomsRes] = await Promise.all([
      fetch('/admin/api/groups'),
      fetch('/admin/api/tabs'),
      fetch('/admin/api/users'),
      fetch('/admin/api/adoms'),
    ]);

    if (!groupsRes.ok || !tabsRes.ok || !usersRes.ok) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-danger">Failed to load data.</td></tr>';
      return;
    }

    const groups = await groupsRes.json();
    allTabs  = await tabsRes.json();
    allUsers = await usersRes.json();
    if (adomsRes.ok) {
      const adomData = await adomsRes.json();
      allAdoms = (adomData.adoms || []).map(n => ({ name: n }));
      const statusEl = document.getElementById('adomCacheStatus');
      if (statusEl && adomData.last_updated) {
        statusEl.textContent = `Last synced: ${adomData.last_updated}`;
      }
    }

    if (!groups.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state" style="padding:.85rem 1rem">No groups yet — click <strong>+ New Group</strong> to create one.</td></tr>';
      return;
    }

    const tabMap = Object.fromEntries(allTabs.map(t => [t.key, t.name]));
    tbody.innerHTML = groups.map(g => {
      let adomCell;
      if (!g.adom_restrict) {
        adomCell = '<span class="text-muted">All ADOMs</span>';
      } else if (!g.allowed_adoms || !g.allowed_adoms.length) {
        adomCell = '<span style="color:var(--danger)">None (restricted)</span>';
      } else {
        const preview = g.allowed_adoms.slice(0, 3).map(esc).join(', ');
        const extra   = g.allowed_adoms.length > 3 ? ` <span class="text-muted">+${g.allowed_adoms.length - 3} more</span>` : '';
        adomCell = preview + extra;
      }
      const adGroupsCell = (g.ad_groups && g.ad_groups.length)
        ? g.ad_groups.slice(0, 2).map(esc).join(', ')
          + (g.ad_groups.length > 2 ? ` <span class="text-muted">+${g.ad_groups.length - 2} more</span>` : '')
        : '<span class="text-muted">—</span>';
      return `
      <tr>
        <td><strong>${esc(g.name)}</strong></td>
        <td>${g.members.length ? g.members.map(esc).join(', ') : '<span class="text-muted">—</span>'}</td>
        <td>${adGroupsCell}</td>
        <td>${g.allowed_tabs.length
              ? g.allowed_tabs.map(k => `<span class="tab-badge">${esc(tabMap[k] || k)}</span>`).join(' ')
              : '<span class="text-muted">None</span>'}</td>
        <td>${adomCell}</td>
        <td>
          <button class="btn btn-sm btn-link" data-action="edit" data-group="${esc(g.name)}">Edit</button>
          <button class="btn btn-sm" style="background:rgba(220,53,69,.1);color:var(--danger);border:1px solid rgba(220,53,69,.25)"
                  data-action="delete" data-group="${esc(g.name)}">Delete</button>
        </td>
      </tr>`;
    }).join('');
  }

  // Event delegation for Edit / Delete buttons in the groups table
  document.getElementById('groupsTbody').addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const name = btn.dataset.group;
    if (btn.dataset.action === 'edit') {
      fetch('/admin/api/groups').then(r => r.json()).then(groups => {
        const g = groups.find(x => x.name === name);
        if (g) openGroupModal('edit', g);
      });
    } else if (btn.dataset.action === 'delete') {
      pendingDeleteName = name;
      document.getElementById('deleteGroupName').textContent = name;
      document.getElementById('deleteModal').classList.remove('hidden');
    }
  });

  // ── Group Modal ────────────────────────────────────────────────────────────

  function openGroupModal(mode, group) {
    document.getElementById('groupModalMode').value = mode;
    document.getElementById('groupModalOrigName').value = group ? group.name : '';
    document.getElementById('groupModalTitle').textContent = mode === 'edit' ? 'Edit Group' : 'New Group';
    document.getElementById('groupNameInput').value = group ? group.name : '';
    document.getElementById('groupNameInput').disabled = (mode === 'edit');
    document.getElementById('groupModalError').classList.add('hidden');

    // Tab checkboxes
    const tabBox = document.getElementById('tabCheckboxes');
    tabBox.innerHTML = allTabs.map(t => `
      <label class="checkbox-label">
        <input type="checkbox" name="tab" value="${esc(t.key)}"
               ${group && group.allowed_tabs.includes(t.key) ? 'checked' : ''} />
        ${esc(t.name)}
      </label>`).join('');

    // Member checkboxes (only non-admin users)
    const memberBox = document.getElementById('memberCheckboxes');
    const viewers = allUsers.filter(u => u.role !== 'admin');
    if (!viewers.length) {
      memberBox.innerHTML = '<span class="text-muted" style="font-size:.82rem">No viewer accounts found.</span>';
    } else {
      memberBox.innerHTML = viewers.map(u => `
        <label class="checkbox-label">
          <input type="checkbox" name="member" value="${esc(u.username)}"
                 ${group && group.members.includes(u.username) ? 'checked' : ''} />
          ${esc(u.username)}
        </label>`).join('');
    }

    // AD group tags
    _setAdGroupTags(group ? (group.ad_groups || []) : []);

    // ADOM restrict toggle
    const restrict = group ? !!group.adom_restrict : false;
    document.getElementById('adomRestrictToggle').checked = restrict;
    _toggleAdomSection(restrict);

    // ADOM checkboxes
    _buildAdomCheckboxes(group ? (group.allowed_adoms || []) : []);

    document.getElementById('groupModal').classList.remove('hidden');
  }

  // ── AD Group tag helpers ───────────────────────────────────────────────────

  function _setAdGroupTags(tags) {
    const container = document.getElementById('adGroupTags');
    container.innerHTML = '';
    tags.forEach(t => _appendAdGroupTag(container, t));
  }

  function _appendAdGroupTag(container, value) {
    if (!value.trim()) return;
    const span = document.createElement('span');
    span.style.cssText = 'display:inline-flex;align-items:center;gap:.25rem;background:var(--surface-alt);border:1px solid var(--border);border-radius:4px;padding:.15rem .45rem;font-size:.82rem';
    span.dataset.value = value.trim();
    span.innerHTML = `${esc(value.trim())} <button type="button" style="background:none;border:none;cursor:pointer;color:var(--text-muted);font-size:1rem;line-height:1;padding:0" aria-label="Remove">&times;</button>`;
    span.querySelector('button').addEventListener('click', () => span.remove());
    container.appendChild(span);
  }

  function _getAdGroupTags() {
    return [...document.querySelectorAll('#adGroupTags [data-value]')].map(s => s.dataset.value);
  }

  document.getElementById('adGroupAdd').addEventListener('click', () => {
    const inp = document.getElementById('adGroupInput');
    const val = inp.value.trim();
    if (!val) return;
    // prevent exact duplicates
    if (!_getAdGroupTags().includes(val)) {
      _appendAdGroupTag(document.getElementById('adGroupTags'), val);
    }
    inp.value = '';
    inp.focus();
  });

  document.getElementById('adGroupInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('adGroupAdd').click();
    }
  });

  function _toggleAdomSection(show) {
    document.getElementById('adomCheckboxWrap').style.display = show ? '' : 'none';
  }

  function _buildAdomCheckboxes(selected) {
    const box = document.getElementById('adomCheckboxes');
    if (!allAdoms.length) {
      box.innerHTML = '<span class="text-muted" style="font-size:.82rem">No ADOMs loaded yet (FortiManager may be unreachable).</span>';
      return;
    }
    box.innerHTML = allAdoms.map(a => `
      <label class="checkbox-label">
        <input type="checkbox" name="adom" value="${esc(a.name)}"
               ${selected.includes(a.name) ? 'checked' : ''} />
        ${esc(a.name)}
      </label>`).join('');
  }

  document.getElementById('adomRestrictToggle').addEventListener('change', e => {
    _toggleAdomSection(e.target.checked);
  });

  document.getElementById('adomSelectAll').addEventListener('click', () => {
    document.querySelectorAll('#adomCheckboxes input[name=adom]').forEach(cb => cb.checked = true);
  });

  document.getElementById('adomSelectNone').addEventListener('click', () => {
    document.querySelectorAll('#adomCheckboxes input[name=adom]').forEach(cb => cb.checked = false);
  });

  document.getElementById('btnNewGroup').addEventListener('click', () => openGroupModal('create', null));

  function closeGroupModal() {
    document.getElementById('groupModal').classList.add('hidden');
  }
  document.getElementById('groupModalClose').addEventListener('click', closeGroupModal);
  document.getElementById('groupModalCancel').addEventListener('click', closeGroupModal);

  document.getElementById('groupModalSave').addEventListener('click', async () => {
    const mode         = document.getElementById('groupModalMode').value;
    const origName     = document.getElementById('groupModalOrigName').value;
    const name         = document.getElementById('groupNameInput').value.trim();
    const tabs         = [...document.querySelectorAll('#tabCheckboxes input[name=tab]:checked')].map(i => i.value);
    const members      = [...document.querySelectorAll('#memberCheckboxes input[name=member]:checked')].map(i => i.value);
    const adGroups     = _getAdGroupTags();
    const adomRestrict = document.getElementById('adomRestrictToggle').checked;
    const allowedAdoms = [...document.querySelectorAll('#adomCheckboxes input[name=adom]:checked')].map(i => i.value);
    const errEl        = document.getElementById('groupModalError');
    errEl.classList.add('hidden');

    if (!name) { showModalError('Group name is required.'); return; }

    const body = {
      members,
      ad_groups:     adGroups,
      allowed_tabs:  tabs,
      adom_restrict: adomRestrict,
      allowed_adoms: adomRestrict ? allowedAdoms : [],
    };

    let res;
    if (mode === 'create') {
      res = await fetch('/admin/api/groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ...body }),
      });
    } else {
      res = await fetch(`/admin/api/groups/${encodeURIComponent(origName)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }

    if (res.ok) {
      closeGroupModal();
      loadGroups();
    } else {
      const data = await res.json().catch(() => ({}));
      showModalError(data.error || 'Failed to save group.');
    }
  });

  function showModalError(msg) {
    const el = document.getElementById('groupModalError');
    el.textContent = msg;
    el.classList.remove('hidden');
  }

  // ── Delete Modal ───────────────────────────────────────────────────────────

  function closeDeleteModal() {
    document.getElementById('deleteModal').classList.add('hidden');
    pendingDeleteName = null;
  }
  document.getElementById('deleteModalClose').addEventListener('click', closeDeleteModal);
  document.getElementById('deleteModalCancel').addEventListener('click', closeDeleteModal);

  document.getElementById('deleteModalConfirm').addEventListener('click', async () => {
    if (!pendingDeleteName) return;
    const res = await fetch(`/admin/api/groups/${encodeURIComponent(pendingDeleteName)}`, { method: 'DELETE' });
    closeDeleteModal();
    if (res.ok) loadGroups();
  });

  // Close modals on overlay click
  document.getElementById('groupModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeGroupModal();
  });
  document.getElementById('deleteModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeDeleteModal();
  });


  // ══════════════════════  EXTERNAL API  ════════════════════════════════════

  let _extApiLoaded = false;

  async function loadExtApi() {
    const [settingsRes, tokensRes] = await Promise.all([
      fetch('/admin/api/settings'),
      fetch('/admin/api/tokens'),
    ]);
    if (!settingsRes.ok) return;
    const settings = await settingsRes.json();
    document.getElementById('extApiEnabled').checked = !!settings.external_api_enabled;

    if (tokensRes.ok) {
      const tokens = await tokensRes.json();
      renderTokens(tokens);
    }
    _extApiLoaded = true;
  }

  function renderTokens(tokens) {
    const tbody = document.getElementById('tokensTbody');
    if (!tokens.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty-state" style="padding:.85rem 1rem">No tokens yet — click <strong>+ New Token</strong> to create one.</td></tr>';
      return;
    }
    tbody.innerHTML = tokens.map(t => `
      <tr>
        <td><strong>${esc(t.name)}</strong></td>
        <td>${esc(t.created_by || '—')}</td>
        <td>
          <button class="btn btn-sm"
                  style="background:rgba(220,53,69,.1);color:var(--danger);border:1px solid rgba(220,53,69,.25)"
                  data-action="revoke" data-token-id="${esc(t.id)}">Revoke</button>
        </td>
      </tr>`).join('');
  }

  async function reloadTokens() {
    const res = await fetch('/admin/api/tokens');
    if (res.ok) renderTokens(await res.json());
  }

  // Save toggle
  document.getElementById('btnSaveExtApiToggle').addEventListener('click', async () => {
    const enabled = document.getElementById('extApiEnabled').checked;
    const msgEl = document.getElementById('extApiToggleMsg');
    const res = await fetch('/admin/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ external_api_enabled: enabled }),
    });
    if (res.ok) {
      msgEl.textContent = enabled ? 'External API enabled.' : 'External API disabled.';
      msgEl.style.color = enabled ? 'var(--success)' : 'var(--warning)';
    } else {
      msgEl.textContent = 'Failed to save.';
      msgEl.style.color = 'var(--danger)';
    }
    setTimeout(() => { msgEl.textContent = ''; }, 3000);
  });

  // Revoke via event delegation
  document.getElementById('tokensTbody').addEventListener('click', async e => {
    const btn = e.target.closest('[data-action="revoke"]');
    if (!btn) return;
    if (!confirm('Revoke this token? Any program using it will lose access immediately.')) return;
    const res = await fetch(`/admin/api/tokens/${encodeURIComponent(btn.dataset.tokenId)}`, { method: 'DELETE' });
    if (res.ok) reloadTokens();
  });

  // New token modal
  function openNewTokenModal() {
    document.getElementById('newTokenName').value = '';
    document.getElementById('newTokenError').classList.add('hidden');
    document.getElementById('newTokenModal').classList.remove('hidden');
    document.getElementById('newTokenName').focus();
  }
  function closeNewTokenModal() {
    document.getElementById('newTokenModal').classList.add('hidden');
  }

  document.getElementById('btnNewToken').addEventListener('click', openNewTokenModal);
  document.getElementById('newTokenModalClose').addEventListener('click', closeNewTokenModal);
  document.getElementById('newTokenCancel').addEventListener('click', closeNewTokenModal);
  document.getElementById('newTokenModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeNewTokenModal();
  });

  document.getElementById('newTokenSave').addEventListener('click', async () => {
    const name = document.getElementById('newTokenName').value.trim();
    const errEl = document.getElementById('newTokenError');
    errEl.classList.add('hidden');
    if (!name) { errEl.textContent = 'Name is required.'; errEl.classList.remove('hidden'); return; }

    const res = await fetch('/admin/api/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      errEl.textContent = d.error || 'Failed to create token.';
      errEl.classList.remove('hidden');
      return;
    }
    const data = await res.json();
    closeNewTokenModal();
    reloadTokens();
    // Show the plaintext token once
    document.getElementById('tokenRevealValue').textContent = data.token;
    document.getElementById('tokenRevealModal').classList.remove('hidden');
  });

  // Token reveal modal
  document.getElementById('tokenRevealClose').addEventListener('click', () => {
    document.getElementById('tokenRevealModal').classList.add('hidden');
  });
  document.getElementById('tokenRevealDone').addEventListener('click', () => {
    document.getElementById('tokenRevealModal').classList.add('hidden');
  });
  document.getElementById('tokenRevealModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) document.getElementById('tokenRevealModal').classList.add('hidden');
  });
  document.getElementById('btnCopyToken').addEventListener('click', () => {
    const val = document.getElementById('tokenRevealValue').textContent;
    navigator.clipboard.writeText(val).then(() => {
      const btn = document.getElementById('btnCopyToken');
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
    });
  });

  // Enter key in new-token name field
  document.getElementById('newTokenName').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('newTokenSave').click(); }
  });


  // ══════════════════════  MAP REGIONS  ═════════════════════════════════════

  let _mapRegionsLoaded = false;
  let _mapAllStates     = [];

  async function loadMapRegions() {
    const tbody = document.getElementById('mapRegionsTbody');
    tbody.innerHTML = '<tr><td colspan="4" class="loading-placeholder">Loading…</td></tr>';

    const res = await fetch('/admin/api/map-regions');
    if (!res.ok) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-danger">Failed to load region data.</td></tr>';
      return;
    }
    const data = await res.json();
    _mapAllStates = data.all_states || [];
    _renderMapRegions(data);
    _mapRegionsLoaded = true;
  }

  // Build the inner HTML for one named-region <tr> (called for existing and new rows).
  function _makeRegionRow(r) {
    const assigned = new Set(r.states || []);
    const options  = _mapAllStates.map(s =>
      `<option value="${esc(s)}"${assigned.has(s) ? ' selected' : ''}>${esc(s)}</option>`
    ).join('');
    const color = r.color || '#888888';
    return `<tr class="region-row">
      <td style="vertical-align:top;padding-top:.5rem">
        <input type="text" class="form-control region-name-input"
               value="${esc(r.name)}" placeholder="Region name"
               style="font-size:.85rem;padding:.35rem .5rem;font-weight:500" />
      </td>
      <td>
        <select multiple class="region-states-select"
                style="width:100%;min-height:110px;border:1px solid var(--border);border-radius:4px;font-size:.82rem;padding:.2rem;background:var(--surface);color:var(--text)">
          ${options}
        </select>
        <p style="font-size:.75rem;color:var(--text-muted);margin:.25rem 0 0">
          Hold Ctrl / Cmd to select multiple states.
        </p>
      </td>
      <td style="vertical-align:top;padding-top:.5rem">
        <div style="display:flex;align-items:center;gap:.6rem">
          <input type="color" class="region-color-input" value="${esc(color)}"
                 style="width:44px;height:30px;border:1px solid var(--border);border-radius:4px;cursor:pointer;padding:2px" />
          <span class="region-color-hex" style="font-size:.82rem;font-family:monospace">${esc(color)}</span>
        </div>
      </td>
      <td style="vertical-align:top;padding-top:.4rem;text-align:center">
        <button class="delete-region-btn btn btn-sm" title="Delete region"
                style="background:rgba(220,53,69,.1);color:var(--danger);border:1px solid rgba(220,53,69,.25);padding:.2rem .55rem;font-size:1.1rem;line-height:1">&times;</button>
      </td>
    </tr>`;
  }

  function _renderMapRegions(data) {
    const tbody      = document.getElementById('mapRegionsTbody');
    const otherColor = data.other_color || '#333333';

    const regionRows = (data.regions || []).map(_makeRegionRow).join('');

    const otherRow = `<tr id="otherRegionRow" style="border-top:2px solid var(--border)">
      <td style="vertical-align:middle"><strong>Other</strong></td>
      <td style="font-size:.83rem;color:var(--text-muted);vertical-align:middle">
        Any state not assigned to a named region above
      </td>
      <td style="vertical-align:middle">
        <div style="display:flex;align-items:center;gap:.6rem">
          <input type="color" id="otherColorInput" value="${esc(otherColor)}"
                 style="width:44px;height:30px;border:1px solid var(--border);border-radius:4px;cursor:pointer;padding:2px" />
          <span id="otherColorHex" style="font-size:.82rem;font-family:monospace">${esc(otherColor)}</span>
        </div>
      </td>
      <td></td>
    </tr>`;

    tbody.innerHTML = regionRows + otherRow;
    _syncStateSelects();
  }

  // Event delegation — handles all interactions inside the tbody.
  const _mrTbody = document.getElementById('mapRegionsTbody');

  _mrTbody.addEventListener('input', e => {
    if (e.target.matches('.region-color-input')) {
      e.target.nextElementSibling.textContent = e.target.value;
    }
    if (e.target.id === 'otherColorInput') {
      document.getElementById('otherColorHex').textContent = e.target.value;
    }
  });

  _mrTbody.addEventListener('change', e => {
    if (e.target.matches('.region-states-select')) _syncStateSelects();
  });

  _mrTbody.addEventListener('click', e => {
    const btn = e.target.closest('.delete-region-btn');
    if (btn) { btn.closest('tr').remove(); _syncStateSelects(); }
  });

  // Disable any state option that is already selected in a different region's select.
  function _syncStateSelects() {
    const selects = [...document.querySelectorAll('.region-states-select')];
    selects.forEach(sel => {
      const takenElsewhere = new Set(
        selects
          .filter(s => s !== sel)
          .flatMap(s => [...s.options].filter(o => o.selected).map(o => o.value))
      );
      sel.querySelectorAll('option').forEach(opt => {
        if (takenElsewhere.has(opt.value)) {
          opt.disabled = true;
          opt.selected = false;
        } else {
          opt.disabled = false;
        }
      });
    });
  }

  function _showMapRegionsMsg(msg, isError) {
    const el = document.getElementById('mapRegionsMsg');
    el.textContent = msg;
    el.style.background = isError ? 'rgba(220,53,69,.12)' : 'rgba(40,167,69,.12)';
    el.style.border      = isError ? '1px solid rgba(220,53,69,.3)' : '1px solid rgba(40,167,69,.3)';
    el.style.color       = isError ? 'var(--danger)' : 'var(--success)';
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 4000);
  }

  document.getElementById('btnAddRegion').addEventListener('click', () => {
    const otherRow = document.getElementById('otherRegionRow');
    if (!otherRow) return;
    otherRow.insertAdjacentHTML('beforebegin', _makeRegionRow({ name: '', color: '#888888', states: [] }));
    _syncStateSelects();
    otherRow.previousElementSibling.querySelector('.region-name-input').focus();
  });

  document.getElementById('btnSaveRegionColors').addEventListener('click', async () => {
    const regions = [];
    document.querySelectorAll('#mapRegionsTbody .region-row').forEach(row => {
      const name   = row.querySelector('.region-name-input').value.trim();
      const color  = row.querySelector('.region-color-input').value;
      const states = [...row.querySelectorAll('.region-states-select option')]
                       .filter(o => o.selected && !o.disabled)
                       .map(o => o.value);
      regions.push({ name, color, states });
    });

    const otherInp = document.getElementById('otherColorInput');
    const body = { regions, other_color: otherInp ? otherInp.value : '#333333' };

    const res = await fetch('/admin/api/map-regions', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (res.ok) {
      const data = await res.json();
      _mapAllStates = data.all_states || _mapAllStates;
      _renderMapRegions(data);
      _showMapRegionsMsg('Region configuration saved. The map will update on next load.', false);
    } else {
      const err = await res.json().catch(() => ({}));
      _showMapRegionsMsg(err.error || 'Failed to save.', true);
    }
  });


  // ══════════════════════  LOGS  ═════════════════════════════════════════════

  const LOG_LEVEL_COLORS = {
    TRACE: 'var(--text-muted)',
    DEBUG: 'var(--accent)',
    INFO:  'var(--success)',
    WARN:  'var(--warning)',
    ERROR: 'var(--danger)',
  };

  let logMeta = null;

  async function loadLogs() {
    const level     = document.getElementById('logFilterLevel').value || '';
    const component = document.getElementById('logFilterComponent').value.trim();
    const params    = new URLSearchParams({ limit: 500 });
    if (level)     params.set('level', level);
    if (component) params.set('component', component);

    const res = await fetch(`/admin/api/logs?${params}`);
    if (!res.ok) { document.getElementById('logContainer').textContent = 'Failed to load logs.'; return; }

    const data = await res.json();
    logMeta = data;

    // Populate level selects if first load
    const levelSelect = document.getElementById('logLevelSelect');
    const filterSelect = document.getElementById('logFilterLevel');
    if (!levelSelect.options.length) {
      data.levels.forEach(l => {
        levelSelect.add(new Option(l, l));
        filterSelect.add(new Option(l, l));
      });
    }
    levelSelect.value = data.current_level;
    document.getElementById('logCurrentLevel').textContent = data.current_level;
    document.getElementById('logCount').textContent = data.count;

    renderLogs(data.entries);
  }

  function renderLogs(entries) {
    const container = document.getElementById('logContainer');
    if (!entries.length) {
      container.innerHTML = '<div class="empty-state" style="padding:1rem">No log entries match your filter.</div>';
      return;
    }
    container.innerHTML = entries.slice().reverse().map(e => {
      const color = LOG_LEVEL_COLORS[e.level] || 'var(--text)';
      const extra = e.extra ? ' ' + Object.entries(e.extra).map(([k,v]) => `${k}=${JSON.stringify(v)}`).join(' ') : '';
      return `<div class="log-line">
        <span class="log-ts">${esc(e.ts)}</span>
        <span class="log-level" style="color:${color}">${esc(e.level.padEnd(5))}</span>
        <span class="log-component">[${esc(e.component)}]</span>
        <span class="log-msg">${esc(e.message)}${esc(extra)}</span>
      </div>`;
    }).join('');
    container.scrollTop = 0;
  }

  document.getElementById('btnRefreshLogs').addEventListener('click', loadLogs);

  document.getElementById('btnApplyFilter').addEventListener('click', loadLogs);

  document.getElementById('btnSetLevel').addEventListener('click', async () => {
    const level = document.getElementById('logLevelSelect').value;
    const res = await fetch('/admin/api/logs/level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level }),
    });
    if (res.ok) loadLogs();
  });

  document.getElementById('btnClearLogs').addEventListener('click', async () => {
    if (!confirm('Clear all log entries from the in-memory buffer?')) return;
    await fetch('/admin/api/logs', { method: 'DELETE' });
    loadLogs();
  });


  // ══════════════════════  HELPERS  ═════════════════════════════════════════

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }


  // ── Boot ───────────────────────────────────────────────────────────────────
  loadGroups();
})();

/* ── Config-Diff: SMTP ───────────────────────────────────────────────────── */

async function loadSMTP() {
  const res = await fetch('/admin/api/smtp');
  if (!res.ok) return;
  const cfg = await res.json();
  document.getElementById('smtpHost').value          = cfg.host || '';
  document.getElementById('smtpPort').value          = cfg.port || 25;
  document.getElementById('smtpTls').value           = cfg.tls_mode || 'none';
  document.getElementById('smtpUsername').value      = cfg.username || '';
  document.getElementById('smtpPassword').value      = cfg.password || '';
  document.getElementById('smtpFrom').value          = cfg.from_address || '';
  document.getElementById('smtpRetentionDays').value = cfg.run_history_days || 30;
  document.getElementById('smtpEnabled').checked     = !!cfg.enabled;
}

async function saveSMTP() {
  const msg = document.getElementById('smtpMsg');
  const payload = {
    host:              document.getElementById('smtpHost').value.trim(),
    port:              parseInt(document.getElementById('smtpPort').value) || 25,
    tls_mode:          document.getElementById('smtpTls').value,
    username:          document.getElementById('smtpUsername').value.trim(),
    password:          document.getElementById('smtpPassword').value,
    from_address:      document.getElementById('smtpFrom').value.trim(),
    run_history_days:  parseInt(document.getElementById('smtpRetentionDays').value) || 30,
    enabled:           document.getElementById('smtpEnabled').checked,
  };
  const res = await fetch('/admin/api/smtp', { method: 'PUT',
    headers: {'Content-Type':'application/json', 'X-CSRF-Token': getCSRF()},
    body: JSON.stringify(payload) });
  msg.style.color = res.ok ? '#166534' : '#b91c1c';
  msg.textContent = res.ok ? 'Saved.' : 'Save failed.';
  setTimeout(() => msg.textContent = '', 3000);
}

async function testSMTP() {
  const msg = document.getElementById('smtpMsg');
  const to  = document.getElementById('smtpTestTo').value.trim();
  if (!to) { msg.style.color='#b91c1c'; msg.textContent='Enter a test recipient first.'; return; }
  msg.style.color = '#6b7280'; msg.textContent = 'Sending…';
  const res  = await fetch('/admin/api/smtp/test', { method: 'POST',
    headers: {'Content-Type':'application/json', 'X-CSRF-Token': getCSRF()},
    body: JSON.stringify({to}) });
  const data = await res.json();
  msg.style.color = data.ok ? '#166534' : '#b91c1c';
  msg.textContent = data.ok ? 'Test email sent!' : `Error: ${data.error}`;
}

/* ── Config-Diff: Jobs ───────────────────────────────────────────────────── */

const _DAY_CODES = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
const _DAY_LABELS = {SUN:'Sun',MON:'Mon',TUE:'Tue',WED:'Wed',THU:'Thu',FRI:'Fri',SAT:'Sat'};

let _cdiffJobs = [];

async function loadJobs() {
  const res = await fetch('/admin/api/config-diff/jobs');
  _cdiffJobs = res.ok ? await res.json() : [];
  renderJobsTable();
}

function renderJobsTable() {
  const tbody = document.getElementById('jobsTableBody');
  if (!tbody) return;
  if (!_cdiffJobs.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="color:var(--text-muted);text-align:center">No scheduled jobs.</td></tr>';
    return;
  }
  tbody.innerHTML = _cdiffJobs.map(j => {
    const last = j.runs && j.runs[0];
    const ts   = last ? new Date(last.ran_at).toLocaleString() : '—';
    const badge = !last ? '<span style="color:var(--text-muted)">Never</span>'
      : last.status === 'ok'
        ? '<span style="color:#166534;font-weight:600">OK</span>'
        : `<span style="color:var(--danger);font-weight:600" title="${escH(last.error||'')}">ERROR</span>`;
    return `<tr>
      <td>${escH(j.adom)}</td>
      <td>${(j.days_of_week||[]).map(d=>_DAY_LABELS[d]||d).join(', ')}</td>
      <td>${escH(j.time)}</td>
      <td>${escH(j.format.toUpperCase())}</td>
      <td>${escH(j.email)}</td>
      <td style="font-size:11px">${ts}</td>
      <td>${badge}</td>
      <td>
        <button class="btn-sm" onclick="editJob('${j.id}')">Edit</button>
        <button class="btn-sm" style="color:var(--danger)" onclick="deleteJob('${j.id}')">Delete</button>
        <button class="btn-sm" id="runBtn-${j.id}" onclick="runJobNow('${j.id}')">Run Now</button>
      </td>
    </tr>`;
  }).join('');
}

function escH(s) {
  return String(s||'').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadJobAdoms() {
  const sel = document.getElementById('jobFormAdom');
  if (!sel) return;
  const res = await fetch('/admin/api/adoms');
  const data = res.ok ? await res.json() : [];
  sel.innerHTML = (data.adoms || []).map(a => `<option value="${escH(a)}">${escH(a)}</option>`).join('');
}

function showJobForm(job) {
  document.getElementById('jobFormTitle').textContent = job ? 'Edit Scheduled Export' : 'New Scheduled Export';
  document.getElementById('jobFormId').value      = job ? job.id : '';
  document.getElementById('jobFormAdom').value    = job ? job.adom : '';
  const activeDays = job ? (job.days_of_week || ['MON']) : ['MON'];
  _DAY_CODES.forEach(code => {
    const chk = document.getElementById('dayChk-' + code);
    if (chk) chk.checked = activeDays.includes(code);
  });
  document.getElementById('jobFormTime').value    = job ? job.time : '06:00';
  document.getElementById('jobFormFormat').value  = job ? job.format : 'pdf';
  document.getElementById('jobFormEmail').value   = job ? job.email : '';
  document.getElementById('jobFormEnabled').checked = job ? !!job.enabled : true;
  document.getElementById('jobFormMsg').textContent = '';
  document.getElementById('jobForm').style.display = 'block';
  loadJobAdoms();
}

function cancelJobForm() {
  document.getElementById('jobForm').style.display = 'none';
}

function editJob(id) {
  const job = _cdiffJobs.find(j => j.id === id);
  if (job) showJobForm(job);
}

async function saveJob() {
  const msg    = document.getElementById('jobFormMsg');
  const id     = document.getElementById('jobFormId').value;
  const selectedDays = _DAY_CODES.filter(code => {
    const chk = document.getElementById('dayChk-' + code);
    return chk && chk.checked;
  });
  if (selectedDays.length === 0) {
    msg.style.color = 'var(--danger)';
    msg.textContent = 'Select at least one day.';
    return;
  }
  const payload = {
    adom:         document.getElementById('jobFormAdom').value,
    days_of_week: selectedDays,
    time:         document.getElementById('jobFormTime').value,
    format:       document.getElementById('jobFormFormat').value,
    email:        document.getElementById('jobFormEmail').value.trim(),
    enabled:      document.getElementById('jobFormEnabled').checked,
  };
  const url    = id ? `/admin/api/config-diff/jobs/${id}` : '/admin/api/config-diff/jobs';
  const method = id ? 'PUT' : 'POST';
  const res    = await fetch(url, { method,
    headers: {'Content-Type':'application/json','X-CSRF-Token': getCSRF()},
    body: JSON.stringify(payload) });
  if (res.ok) {
    cancelJobForm();
    loadJobs();
  } else {
    const err = await res.json().catch(() => ({}));
    msg.style.color = 'var(--danger)';
    msg.textContent = err.error || 'Save failed.';
  }
}

async function deleteJob(id) {
  if (!confirm('Delete this scheduled export?')) return;
  await fetch(`/admin/api/config-diff/jobs/${id}`, { method: 'DELETE',
    headers: {'X-CSRF-Token': getCSRF()} });
  loadJobs();
}

async function runJobNow(id) {
  const btn = document.getElementById(`runBtn-${id}`);
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  const runRes = await fetch(`/admin/api/config-diff/jobs/${id}/run`, { method: 'POST',
    headers: {'X-CSRF-Token': getCSRF()} });
  if (!runRes.ok) {
    if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
    return;
  }
  // Poll status every 3s until done
  const poll = setInterval(async () => {
    try {
      const res  = await fetch(`/admin/api/config-diff/jobs/${id}/status`);
      const data = await res.json();
      if (!data.running) {
        clearInterval(poll);
        if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
        loadJobs();
      }
    } catch (_) {
      clearInterval(poll);
      if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
    }
  }, 3000);
}

function getCSRF() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}
