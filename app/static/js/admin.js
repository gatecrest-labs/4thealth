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
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state" style="padding:.85rem 1rem">No groups yet — click <strong>+ New Group</strong> to create one.</td></tr>';
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
      return `
      <tr>
        <td><strong>${esc(g.name)}</strong></td>
        <td>${g.members.length ? g.members.map(esc).join(', ') : '<span class="text-muted">—</span>'}</td>
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

    // ADOM restrict toggle
    const restrict = group ? !!group.adom_restrict : false;
    document.getElementById('adomRestrictToggle').checked = restrict;
    _toggleAdomSection(restrict);

    // ADOM checkboxes
    _buildAdomCheckboxes(group ? (group.allowed_adoms || []) : []);

    document.getElementById('groupModal').classList.remove('hidden');
  }

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
    const adomRestrict = document.getElementById('adomRestrictToggle').checked;
    const allowedAdoms = [...document.querySelectorAll('#adomCheckboxes input[name=adom]:checked')].map(i => i.value);
    const errEl        = document.getElementById('groupModalError');
    errEl.classList.add('hidden');

    if (!name) { showModalError('Group name is required.'); return; }

    const body = {
      members,
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


  // ══════════════════════  MAP REGIONS  ═════════════════════════════════════

  let _mapRegionsLoaded = false;

  async function loadMapRegions() {
    const tbody = document.getElementById('mapRegionsTbody');
    tbody.innerHTML = '<tr><td colspan="3" class="loading-placeholder">Loading…</td></tr>';

    const res = await fetch('/admin/api/map-regions');
    if (!res.ok) {
      tbody.innerHTML = '<tr><td colspan="3" class="text-danger">Failed to load region data.</td></tr>';
      return;
    }
    const data = await res.json();
    _renderMapRegions(data);
    _mapRegionsLoaded = true;
  }

  function _renderMapRegions(data) {
    const tbody = document.getElementById('mapRegionsTbody');
    const regions = data.regions || [];
    const otherColor = data.other_color || '#333333';

    const regionRows = regions.map(r => {
      const states = (r.states || []).join(', ') || '—';
      return `<tr>
        <td><strong>${esc(r.name)}</strong></td>
        <td style="font-size:.83rem;color:var(--text-muted)">${esc(states)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:.6rem">
            <input type="color" class="region-color-input" data-region="${esc(r.name)}"
                   value="${esc(r.color)}" style="width:44px;height:30px;border:1px solid var(--border);border-radius:4px;cursor:pointer;padding:2px" />
            <span class="region-color-hex" style="font-size:.82rem;font-family:monospace">${esc(r.color)}</span>
          </div>
        </td>
      </tr>`;
    }).join('');

    const otherRow = `<tr style="border-top:2px solid var(--border)">
      <td><strong>Other</strong></td>
      <td style="font-size:.83rem;color:var(--text-muted)">Any state not assigned to a named region</td>
      <td>
        <div style="display:flex;align-items:center;gap:.6rem">
          <input type="color" id="otherColorInput" value="${esc(otherColor)}"
                 style="width:44px;height:30px;border:1px solid var(--border);border-radius:4px;cursor:pointer;padding:2px" />
          <span id="otherColorHex" style="font-size:.82rem;font-family:monospace">${esc(otherColor)}</span>
        </div>
      </td>
    </tr>`;

    tbody.innerHTML = regionRows + otherRow;

    // Live-update hex label as color changes
    tbody.querySelectorAll('.region-color-input').forEach(inp => {
      inp.addEventListener('input', () => {
        inp.nextElementSibling.textContent = inp.value;
      });
    });
    const otherInp = document.getElementById('otherColorInput');
    if (otherInp) {
      otherInp.addEventListener('input', () => {
        document.getElementById('otherColorHex').textContent = otherInp.value;
      });
    }
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

  document.getElementById('btnSaveRegionColors').addEventListener('click', async () => {
    const regionColors = {};
    document.querySelectorAll('.region-color-input').forEach(inp => {
      regionColors[inp.dataset.region] = inp.value;
    });
    const otherInp = document.getElementById('otherColorInput');
    const otherColor = otherInp ? otherInp.value : null;

    const body = { region_colors: regionColors };
    if (otherColor) body.other_color = otherColor;

    const res = await fetch('/admin/api/map-regions', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (res.ok) {
      const data = await res.json();
      _renderMapRegions(data);
      _showMapRegionsMsg('Colors saved. The map will use the new colors on next load.', false);
    } else {
      const err = await res.json().catch(() => ({}));
      _showMapRegionsMsg(err.error || 'Failed to save colors.', true);
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
