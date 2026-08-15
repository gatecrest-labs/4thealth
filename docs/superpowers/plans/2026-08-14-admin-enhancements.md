# Admin Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three admin improvements — move Zone Policy Edit Database to the Admin tab, add SCP as a backup transfer protocol, and add live CPU/Memory/Disk resource graphs above the Admin tab bar with 90-day historical data.

**Architecture:** Feature 1 relocates existing frontend HTML/JS from `zone_policy.html`/`zone_policy.js` to `admin.html`/`admin.js` with zero backend changes (mutation routes are already `@admin_required`). Feature 2 adds a third `protocol == 'scp'` branch to the existing SFTP/FTP transfer logic in `backup_scheduler.py` using the `scp` PyPI package (which wraps paramiko). Feature 3 introduces a new `app/host_metrics.py` module that polls `psutil` every 60 s, stores samples in a SQLite DB at the project root, exposes data via a new admin API endpoint, and renders three Chart.js line charts above the Admin tab bar.

**Tech Stack:** Python/Flask, psutil, scp (PyPI), Chart.js 4.4.0 (vendored), SQLite (stdlib `sqlite3`), APScheduler (already a dependency), paramiko (already a dependency)

**Spec:** `docs/superpowers/specs/2026-08-14-admin-enhancements-design.md`

## Global Constraints

- Package manager: `uv` — always `uv add <pkg>`, never `pip install`
- Branch: `development`
- All admin routes protected by `@_admin_required` (existing decorator in `admin_routes.py`)
- Flask Blueprint variable in `admin_routes.py` is `bp`
- CSRF pattern in `admin.js`: `'X-CSRF-Token': getCSRF()` (helper already exists at line 922)
- CSS variables in `style.css`: `--border` for borders, `--accent` for active/highlight
- Chart.js vendored at `app/static/js/vendor/chart.min.js` — no CDN
- `host_metrics.db` at project root, gitignored
- Disk monitoring: root partition `/` only
- Data retention: 90 days, pruned daily at 03:00
- Polling interval: 60 seconds
- Compatible with RHEL bare-metal and Docker — no root required for psutil

---

### Task 1: Setup — Dependencies, Vendor Chart.js, Gitignore

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `app/static/js/vendor/chart.min.js`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `psutil` and `scp` importable; `Chart` global available in browser; `host_metrics.db` gitignored

---

- [ ] **Step 1: Add Python dependencies**

```bash
uv add psutil scp
```

Verify:
```bash
uv run python -c "import psutil, scp; print('ok')"
```
Expected output: `ok`

- [ ] **Step 2: Create vendor directory and download Chart.js**

```bash
mkdir -p app/static/js/vendor
curl -L "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" \
     -o app/static/js/vendor/chart.min.js
```

Verify the file downloaded successfully:
```bash
wc -c app/static/js/vendor/chart.min.js
```
Expected: more than 100,000 bytes.

- [ ] **Step 3: Gitignore host_metrics.db**

Open `.gitignore`. Add this line alongside the other gitignored runtime data files (near `backup_config.json`, `api_tokens.json`, etc.):

```
host_metrics.db
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock app/static/js/vendor/chart.min.js .gitignore
git commit -m "chore: add psutil/scp deps, vendor Chart.js 4.4.0, gitignore host_metrics.db"
```

---

### Task 2: Feature 1 — Move Edit Database to Admin Tab

**Files:**
- Modify: `app/templates/zone_policy.html`
- Modify: `app/static/js/zone_policy.js`
- Modify: `app/templates/admin.html`
- Modify: `app/static/js/admin.js`

**Interfaces:**
- Consumes (unchanged API endpoints): `POST /api/zone/backup`, `POST /api/zone/zone/add`, `POST /api/zone/zone/remove`, `POST /api/zone/zone/modify`, `POST /api/zone/subnet/add`, `POST /api/zone/subnet/remove`, `POST /api/zone/policy/add`, `POST /api/zone/policy/modify`, `POST /api/zone/policy/remove`, `GET /api/zone/zones`, `GET /api/zone/policies`
- Produces: Admin tab has new "Zone Policy" panel with all edit functionality; Zone Policy tab no longer shows Edit Database to anyone

---

- [ ] **Step 1: Remove Edit Database from zone_policy.html**

Open `app/templates/zone_policy.html`.

Delete the tab button (find by `data-panel="edit"` — exact text may read "Edit Database"):
```html
<button ... data-panel="edit">Edit Database</button>
```

Delete the entire admin-conditional block — from `{% if session.get('role') == 'admin' %}` to its closing `{% endif %}` — that wraps the `id="panel-edit"` div.

Delete the inline `<script>` tag that injects `window._zpIsAdmin`.

After deletion, verify the file contains no remaining occurrences of `panel-edit` or `_zpIsAdmin`.

- [ ] **Step 2: Remove edit JS from zone_policy.js**

Open `app/static/js/zone_policy.js`. Remove all code related to the edit panel:

- The `zpBackupBtn` click handler
- Any functions prefixed with `zpZone`, `zpSubnet`, `zpPolicy`, or `zpEdit`
- All `fetch()` calls to `/api/zone/zone/...`, `/api/zone/subnet/...`, `/api/zone/policy/...`, `/api/zone/backup`
- Any dropdown-population functions called exclusively for the edit panel

Do **not** remove query, browse, or validate code. After removing, scan remaining code for broken references to any deleted functions.

- [ ] **Step 3: Add Zone Policy tab button to admin.html**

Open `app/templates/admin.html`. Find the admin tab bar (the `<div>` containing the `<button class="admin-tab" ...>` elements). Add a new button after the Backup button:

```html
<button class="admin-tab" data-panel="zone-policy">Zone Policy</button>
```

- [ ] **Step 4: Add Zone Policy panel to admin.html**

After the closing `</div>` of `id="panel-backup"`, add:

```html
<div class="admin-panel" id="panel-zone-policy">
  <h2>Zone Policy Database</h2>

  <div class="section-block" style="margin-bottom:1rem;">
    <button id="zpAdminBackupBtn" class="btn btn-secondary">Backup policy_db.json</button>
    <span id="zpAdminBackupStatus" style="margin-left:0.75rem;font-size:0.85rem;"></span>
  </div>

  <div class="zp-edit-grid">
    <div class="zp-edit-section">
      <h3>Zone Operations</h3>

      <form id="zpAdminZoneAddForm" class="zp-form">
        <h4>Add Zone</h4>
        <label>Name <input type="text" name="name" required></label>
        <label>Domain <input type="text" name="domain" value="Default"></label>
        <label>Description <input type="text" name="description"></label>
        <label><input type="checkbox" name="is_shared"> Shared</label>
        <button type="submit" class="btn btn-primary btn-sm">Add Zone</button>
        <span class="form-status" id="zpAdminZoneAddStatus"></span>
      </form>

      <form id="zpAdminZoneRemoveForm" class="zp-form">
        <h4>Remove Zone</h4>
        <label>Zone <select name="zone" id="zpAdminRemoveZoneSelect"></select></label>
        <button type="submit" class="btn btn-danger btn-sm">Remove Zone</button>
        <span class="form-status" id="zpAdminZoneRemoveStatus"></span>
      </form>

      <form id="zpAdminZoneModifyForm" class="zp-form">
        <h4>Modify Zone Field</h4>
        <label>Zone <select name="zone" id="zpAdminModifyZoneSelect"></select></label>
        <label>Field
          <select name="field">
            <option value="description">description</option>
            <option value="domain">domain</option>
            <option value="is_shared">is_shared</option>
          </select>
        </label>
        <label>Value <input type="text" name="value"></label>
        <button type="submit" class="btn btn-primary btn-sm">Update</button>
        <span class="form-status" id="zpAdminZoneModifyStatus"></span>
      </form>
    </div>

    <div class="zp-edit-section">
      <h3>Subnet Operations</h3>

      <form id="zpAdminSubnetAddForm" class="zp-form">
        <h4>Add Subnet to Zone</h4>
        <label>Zone <select name="zone" id="zpAdminSubnetAddZoneSelect"></select></label>
        <label>Subnet (CIDR) <input type="text" name="subnet" placeholder="10.0.0.0/24"></label>
        <label>Description <input type="text" name="description"></label>
        <button type="submit" class="btn btn-primary btn-sm">Add Subnet</button>
        <span class="form-status" id="zpAdminSubnetAddStatus"></span>
      </form>

      <form id="zpAdminSubnetRemoveForm" class="zp-form">
        <h4>Remove Subnet from Zone</h4>
        <label>Zone <select name="zone" id="zpAdminSubnetRemoveZoneSelect"></select></label>
        <label>Subnet <input type="text" name="subnet" placeholder="exact CIDR e.g. 10.0.0.0/24"></label>
        <button type="submit" class="btn btn-danger btn-sm">Remove Subnet</button>
        <span class="form-status" id="zpAdminSubnetRemoveStatus"></span>
      </form>
    </div>

    <div class="zp-edit-section zp-edit-section--full">
      <h3>Policy Rule Operations</h3>

      <form id="zpAdminPolicyAddForm" class="zp-form">
        <h4>Add Policy Rule</h4>
        <label>Policy Set <input type="text" name="policy_set" required></label>
        <label>From Zone <select name="from_zone" id="zpAdminPolicyFromZoneSelect"></select></label>
        <label>To Zone <select name="to_zone" id="zpAdminPolicyToZoneSelect"></select></label>
        <label>Access Type
          <select name="access_type">
            <option value="allow all">allow all</option>
            <option value="allow only">allow only</option>
            <option value="block all">block all</option>
            <option value="block only">block only</option>
          </select>
        </label>
        <label>Severity
          <select name="severity">
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </label>
        <label>Services (comma-separated) <input type="text" name="services"></label>
        <label>Description <input type="text" name="description"></label>
        <button type="submit" class="btn btn-primary btn-sm">Add Rule</button>
        <span class="form-status" id="zpAdminPolicyAddStatus"></span>
      </form>

      <form id="zpAdminPolicyEditForm" class="zp-form">
        <h4>Modify / Remove Rule by Index</h4>
        <label>Index <input type="number" name="index" min="0" id="zpAdminPolicyIndex"></label>
        <label>Field
          <select name="field" id="zpAdminPolicyField">
            <option value="policy_set">policy_set</option>
            <option value="from_zone">from_zone</option>
            <option value="to_zone">to_zone</option>
            <option value="access_type">access_type</option>
            <option value="severity">severity</option>
            <option value="services">services</option>
            <option value="description">description</option>
          </select>
        </label>
        <label>Value <input type="text" name="value" id="zpAdminPolicyValue"></label>
        <div class="btn-row" style="display:flex;gap:0.5rem;margin-top:0.5rem;">
          <button type="button" id="zpAdminPolicyUpdateBtn" class="btn btn-primary btn-sm">Update</button>
          <button type="button" id="zpAdminPolicyRemoveBtn" class="btn btn-danger btn-sm">Remove</button>
        </div>
        <span class="form-status" id="zpAdminPolicyEditStatus"></span>
      </form>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Add Zone Policy edit JS to admin.js**

At the end of `app/static/js/admin.js`, add:

```javascript
// --- Zone Policy Edit ---

function zpAdminLoadZones() {
  fetch('/api/zone/zones')
    .then(r => r.json())
    .then(zones => {
      const names = zones.map(z => z.name).sort();
      const opts  = names.map(n => `<option value="${n}">${n}</option>`).join('');
      [
        'zpAdminRemoveZoneSelect', 'zpAdminModifyZoneSelect',
        'zpAdminSubnetAddZoneSelect', 'zpAdminSubnetRemoveZoneSelect',
        'zpAdminPolicyFromZoneSelect', 'zpAdminPolicyToZoneSelect'
      ].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = opts;
      });
    })
    .catch(() => {});
}

function zpAdminSetStatus(id, msg, ok) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.style.color  = ok ? 'var(--success, green)' : 'var(--danger, red)';
  setTimeout(() => { el.textContent = ''; }, 4000);
}

function zpAdminPost(url, body, statusId, successMsg, onSuccess) {
  fetch(url, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCSRF() },
    body:    JSON.stringify(body),
  })
    .then(r => r.json())
    .then(d => {
      if (d.error) { zpAdminSetStatus(statusId, d.error, false); return; }
      zpAdminSetStatus(statusId, successMsg, true);
      zpAdminLoadZones();
      if (onSuccess) onSuccess(d);
    })
    .catch(e => zpAdminSetStatus(statusId, e.message, false));
}

(function initZpAdminPanel() {
  const panel = document.getElementById('panel-zone-policy');
  if (!panel) return;

  let loaded = false;

  // Lazy-load zone dropdowns the first time the tab is opened
  document.querySelectorAll('.admin-tab[data-panel="zone-policy"]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!loaded) { zpAdminLoadZones(); loaded = true; }
    });
  });

  // Backup
  document.getElementById('zpAdminBackupBtn').addEventListener('click', () => {
    fetch('/api/zone/backup', {
      method:  'POST',
      headers: { 'X-CSRF-Token': getCSRF() },
    })
      .then(r => r.json())
      .then(d => {
        const el = document.getElementById('zpAdminBackupStatus');
        el.textContent  = d.error ? d.error : (d.file || 'Backup created');
        el.style.color  = d.error ? 'var(--danger, red)' : 'var(--success, green)';
      });
  });

  // Add Zone
  document.getElementById('zpAdminZoneAddForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost(
      '/api/zone/zone/add',
      { name: fd.get('name'), domain: fd.get('domain'),
        description: fd.get('description'), is_shared: fd.get('is_shared') === 'on' },
      'zpAdminZoneAddStatus', 'Zone added',
      () => e.target.reset()
    );
  });

  // Remove Zone
  document.getElementById('zpAdminZoneRemoveForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost('/api/zone/zone/remove', { name: fd.get('zone') },
      'zpAdminZoneRemoveStatus', 'Zone removed');
  });

  // Modify Zone
  document.getElementById('zpAdminZoneModifyForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost('/api/zone/zone/modify',
      { name: fd.get('zone'), field: fd.get('field'), value: fd.get('value') },
      'zpAdminZoneModifyStatus', 'Updated');
  });

  // Add Subnet
  document.getElementById('zpAdminSubnetAddForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost('/api/zone/subnet/add',
      { zone: fd.get('zone'), subnet: fd.get('subnet'), description: fd.get('description') },
      'zpAdminSubnetAddStatus', 'Subnet added',
      () => e.target.reset()
    );
  });

  // Remove Subnet
  document.getElementById('zpAdminSubnetRemoveForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost('/api/zone/subnet/remove',
      { zone: fd.get('zone'), subnet: fd.get('subnet') },
      'zpAdminSubnetRemoveStatus', 'Subnet removed');
  });

  // Add Policy Rule
  document.getElementById('zpAdminPolicyAddForm').addEventListener('submit', e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    zpAdminPost('/api/zone/policy/add',
      { policy_set:   fd.get('policy_set'),
        from_zone:    fd.get('from_zone'),
        to_zone:      fd.get('to_zone'),
        access_type:  fd.get('access_type'),
        severity:     fd.get('severity'),
        services:     fd.get('services'),
        description:  fd.get('description') },
      'zpAdminPolicyAddStatus', 'Rule added',
      () => e.target.reset()
    );
  });

  // Modify Policy Rule
  document.getElementById('zpAdminPolicyUpdateBtn').addEventListener('click', () => {
    zpAdminPost('/api/zone/policy/modify',
      { index: parseInt(document.getElementById('zpAdminPolicyIndex').value, 10),
        field: document.getElementById('zpAdminPolicyField').value,
        value: document.getElementById('zpAdminPolicyValue').value },
      'zpAdminPolicyEditStatus', 'Updated');
  });

  // Remove Policy Rule
  document.getElementById('zpAdminPolicyRemoveBtn').addEventListener('click', () => {
    zpAdminPost('/api/zone/policy/remove',
      { index: parseInt(document.getElementById('zpAdminPolicyIndex').value, 10) },
      'zpAdminPolicyEditStatus', 'Rule removed');
  });
})();
```

- [ ] **Step 6: Manual verification**

Start the dev server (`python wsgi.py`). Log in as admin.

- Go to **Admin → Zone Policy** tab. Verify the edit forms appear and zone dropdowns populate when the tab is first clicked.
- Go to **Zone Policy** page. Verify there is no "Edit Database" tab.
- Log in as a non-admin viewer. Verify the Zone Policy page shows no edit tab and Admin is inaccessible.

- [ ] **Step 7: Commit**

```bash
git add app/templates/zone_policy.html app/templates/admin.html \
        app/static/js/zone_policy.js app/static/js/admin.js
git commit -m "feat: move zone policy edit database to admin tab"
```

---

### Task 3: Feature 2 — SCP Backup Transfer Protocol

**Files:**
- Modify: `app/backup_scheduler.py`
- Modify: `app/templates/admin.html`
- Create: `tests/test_backup_scp.py`

**Interfaces:**
- Consumes: `transfer_file(ftp_cfg, local_path)` and `test_connection(ftp_cfg)` in `backup_scheduler.py`, where `ftp_cfg` is the `cfg['ftp']` dict with keys: `protocol`, `host`, `port`, `username`, `password`, `remote_dir`
- Produces: both functions handle `protocol == 'scp'` in addition to existing `'sftp'` and `'ftp'`

---

- [ ] **Step 1: Create test file**

```bash
mkdir -p tests
```

Create `tests/test_backup_scp.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

CFG = {
    'enabled': True,
    'protocol': 'scp',
    'host': '10.0.0.1',
    'port': 22,
    'username': 'user',
    'password': 'secret',
    'remote_dir': '/backups',
}


def test_transfer_file_scp_connects_and_puts(tmp_path):
    local_file = tmp_path / 'backup.zip'
    local_file.write_bytes(b'data')

    mock_ssh = MagicMock()
    mock_transport = MagicMock()
    mock_ssh.get_transport.return_value = mock_transport

    mock_scpc = MagicMock()
    mock_scpc.__enter__ = MagicMock(return_value=mock_scpc)
    mock_scpc.__exit__ = MagicMock(return_value=False)

    with patch('paramiko.SSHClient', return_value=mock_ssh), \
         patch('scp.SCPClient', return_value=mock_scpc):
        from app.backup_scheduler import transfer_file
        transfer_file(CFG, str(local_file))

    mock_ssh.connect.assert_called_once_with(
        '10.0.0.1', port=22, username='user', password='secret'
    )
    mock_scpc.put.assert_called_once_with(str(local_file), '/backups/backup.zip')
    mock_ssh.close.assert_called_once()


def test_test_connection_scp_returns_ok():
    mock_ssh = MagicMock()
    mock_stdout = MagicMock()
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_ssh.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        from app.backup_scheduler import test_connection
        result = test_connection(CFG)

    assert result['status'] == 'ok'
    mock_ssh.connect.assert_called_once_with(
        '10.0.0.1', port=22, username='user', password='secret'
    )
    mock_ssh.exec_command.assert_called_once_with('ls -la /backups')
    mock_ssh.close.assert_called_once()


def test_test_connection_scp_bad_dir_returns_error():
    mock_ssh = MagicMock()
    mock_stdout = MagicMock()
    mock_stdout.channel.recv_exit_status.return_value = 1
    mock_ssh.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        from app.backup_scheduler import test_connection
        result = test_connection(CFG)

    assert result['status'] == 'error'
    assert '/backups' in result.get('message', '')
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_backup_scp.py -v
```

Expected: 3 FAIL — `transfer_file` and `test_connection` don't have SCP branches yet.

- [ ] **Step 3: Add SCP branch to transfer_file()**

Open `app/backup_scheduler.py`. Find the `transfer_file(cfg, local_path)` function. After the SFTP `elif` block, add:

```python
elif protocol == 'scp':
    import scp as scp_lib
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=username, password=password)
    remote_path = remote_dir.rstrip('/') + '/' + os.path.basename(local_path)
    with scp_lib.SCPClient(ssh.get_transport()) as scpc:
        scpc.put(local_path, remote_path)
    ssh.close()
```

`os` and `paramiko` are already imported at module level in `backup_scheduler.py`. The `import scp as scp_lib` is intentionally inside the branch so a missing package only fails at transfer time, not import time.

- [ ] **Step 4: Add SCP branch to test_connection()**

In `app/backup_scheduler.py`, find the `test_connection(cfg)` function. After the SFTP branch, add:

```python
elif protocol == 'scp':
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=username, password=password)
    _stdin, stdout, _stderr = ssh.exec_command(f'ls -la {remote_dir}')
    exit_code = stdout.channel.recv_exit_status()
    ssh.close()
    if exit_code != 0:
        return {'status': 'error', 'message': f'remote_dir not accessible: {remote_dir}'}
    return {'status': 'ok', 'protocol': 'scp', 'host': host}
```

- [ ] **Step 5: Run tests — expect pass**

```bash
uv run pytest tests/test_backup_scp.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Add SCP option to admin.html**

In `app/templates/admin.html`, find the protocol `<select>` inside the backup panel. Add after the SFTP option:

```html
<option value="scp">SCP</option>
```

Verify that the FTP plaintext warning logic in `admin.js` (the block that shows/hides a warning banner) uses a strict `=== 'ftp'` check. SCP uses SSH and must not trigger the plaintext warning.

- [ ] **Step 7: Manual smoke test**

Start the server. Go to **Admin → Backup → Remote Transfer**. Select "SCP" from the dropdown. Verify:
- FTP plaintext warning does not appear.
- Port remains 22.
- "Test Connection" button calls the new SCP branch (a real connection test requires a live remote host; skip in dev unless one is available).

- [ ] **Step 8: Commit**

```bash
git add app/backup_scheduler.py app/templates/admin.html tests/test_backup_scp.py
git commit -m "feat: add SCP as backup transfer protocol"
```

---

### Task 4: Feature 3 — Host Metrics Storage Module

**Files:**
- Create: `app/host_metrics.py`
- Create: `tests/test_host_metrics.py`

**Interfaces:**
- Produces:
  - `init_db(db_path: str = None) -> None`
  - `record_sample(db_path: str = None) -> None`
  - `get_metrics(range_key: str, db_path: str = None) -> dict` — returns `{'cpu': [{'ts': int, 'v': float}, ...], 'mem': [...], 'disk': [...]}`
  - `prune_old_data(db_path: str = None) -> None`
  - `init_scheduler(app) -> None`
  - `_DB_PATH: str` — default SQLite path (project root `host_metrics.db`)

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_host_metrics.py`:

```python
import sqlite3
import time
import pytest


@pytest.fixture
def db(tmp_path):
    from app.host_metrics import init_db
    path = str(tmp_path / 'test.db')
    init_db(path)
    return path


def test_init_db_creates_table(db):
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert 'host_metrics' in tables


def test_init_db_creates_index(db):
    conn = sqlite3.connect(db)
    indexes = [r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index'"
    ).fetchall()]
    conn.close()
    assert 'idx_ts' in indexes


def test_record_sample_inserts_row(db):
    from app.host_metrics import record_sample
    record_sample(db)
    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts, cpu, mem, disk FROM host_metrics').fetchall()
    conn.close()
    assert len(rows) == 1
    ts, cpu, mem, disk = rows[0]
    assert isinstance(ts, int) and ts > 0
    assert 0.0 <= cpu <= 100.0
    assert 0.0 <= mem <= 100.0
    assert 0.0 <= disk <= 100.0


def test_get_metrics_returns_structure(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    for i in range(5):
        conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)',
                     (now - i * 60, 20.0, 50.0, 30.0))
    conn.commit()
    conn.close()

    result = get_metrics('1h', db)
    assert set(result.keys()) == {'cpu', 'mem', 'disk'}
    assert len(result['cpu']) > 0
    for point in result['cpu']:
        assert 'ts' in point and 'v' in point


def test_get_metrics_unknown_range_defaults_to_1h(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (now - 60, 10.0, 40.0, 20.0))
    conn.commit()
    conn.close()
    result = get_metrics('bogus', db)
    assert 'cpu' in result


def test_get_metrics_7d_buckets_by_hour(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    # 4 rows within the same 1-hour bucket
    for i in range(4):
        conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)',
                     (now - i * 300, 40.0, 60.0, 50.0))
    conn.commit()
    conn.close()

    result = get_metrics('7d', db)
    assert len(result['cpu']) == 1
    assert result['cpu'][0]['v'] == pytest.approx(40.0, abs=0.1)


def test_prune_removes_old_rows(db):
    from app.host_metrics import prune_old_data
    now = int(time.time())
    old = now - (91 * 86400)  # 91 days ago, beyond 90-day retention
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (old, 10.0, 40.0, 20.0))
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (now - 60, 10.0, 40.0, 20.0))
    conn.commit()
    conn.close()

    prune_old_data(db)

    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts FROM host_metrics').fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == now - 60
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/test_host_metrics.py -v
```

Expected: all 7 fail with `ModuleNotFoundError` — `app/host_metrics.py` doesn't exist yet.

- [ ] **Step 3: Implement app/host_metrics.py**

Create `app/host_metrics.py`:

```python
import os
import sqlite3
import threading
import time

import psutil
from apscheduler.schedulers.background import BackgroundScheduler

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'host_metrics.db')
_RETENTION_DAYS = 90

_BUCKETS = {
    '1h':  {'window': 3_600,     'bucket': 60},
    '4h':  {'window': 14_400,    'bucket': 300},
    '12h': {'window': 43_200,    'bucket': 600},
    '1d':  {'window': 86_400,    'bucket': 900},
    '7d':  {'window': 604_800,   'bucket': 3_600},
    '14d': {'window': 1_209_600, 'bucket': 7_200},
}


def init_db(db_path=None):
    path = db_path or _DB_PATH
    conn = sqlite3.connect(path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS host_metrics (
            ts    INTEGER NOT NULL,
            cpu   REAL,
            mem   REAL,
            disk  REAL
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ts ON host_metrics(ts)')
    conn.commit()
    conn.close()


def record_sample(db_path=None):
    path = db_path or _DB_PATH
    cpu  = psutil.cpu_percent(interval=None)
    mem  = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    ts   = int(time.time())
    conn = sqlite3.connect(path)
    conn.execute(
        'INSERT INTO host_metrics (ts, cpu, mem, disk) VALUES (?, ?, ?, ?)',
        (ts, cpu, mem, disk),
    )
    conn.commit()
    conn.close()


def get_metrics(range_key, db_path=None):
    path   = db_path or _DB_PATH
    cfg    = _BUCKETS.get(range_key, _BUCKETS['1h'])
    window = cfg['window']
    bucket = cfg['bucket']
    conn   = sqlite3.connect(path)
    rows   = conn.execute(
        '''
        SELECT (ts / ?) * ? AS t,
               AVG(cpu)  AS cpu,
               AVG(mem)  AS mem,
               AVG(disk) AS disk
        FROM host_metrics
        WHERE ts >= strftime('%s', 'now') - ?
        GROUP BY t
        ORDER BY t
        ''',
        (bucket, bucket, window),
    ).fetchall()
    conn.close()
    return {
        'cpu':  [{'ts': int(r[0]), 'v': round(r[1], 1)} for r in rows],
        'mem':  [{'ts': int(r[0]), 'v': round(r[2], 1)} for r in rows],
        'disk': [{'ts': int(r[0]), 'v': round(r[3], 1)} for r in rows],
    }


def prune_old_data(db_path=None):
    path   = db_path or _DB_PATH
    cutoff = int(time.time()) - (_RETENTION_DAYS * 86400)
    conn   = sqlite3.connect(path)
    conn.execute('DELETE FROM host_metrics WHERE ts < ?', (cutoff,))
    conn.commit()
    conn.close()


def init_scheduler(app):
    init_db()
    threading.Thread(target=record_sample, daemon=True).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(record_sample,  'interval', seconds=60,      id='host_metrics_sample')
    scheduler.add_job(prune_old_data, 'cron',     hour=3, minute=0, id='host_metrics_prune')
    scheduler.start()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/test_host_metrics.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/host_metrics.py tests/test_host_metrics.py
git commit -m "feat: add host_metrics module (psutil + SQLite, 90-day retention)"
```

---

### Task 5: Feature 3 — Host Metrics API Endpoint

**Files:**
- Modify: `app/__init__.py`
- Modify: `app/routes/admin_routes.py`

**Interfaces:**
- Consumes: `host_metrics.get_metrics(range_key, db_path=None) -> dict`
- Produces:
  - `GET /admin/api/host-metrics?range=<1h|4h|12h|1d|7d|14d>` → `{'cpu': [...], 'mem': [...], 'disk': [...], 'range': str, 'generated_at': int}`
  - Template context in `admin_page()` gains `in_docker: bool`

---

- [ ] **Step 1: Register host_metrics scheduler in __init__.py**

Open `app/__init__.py`. Find the block where other schedulers are initialised — look for lines like `summary_job.init_scheduler(app)`, `infra_health_cache.init_scheduler(app)`, etc. Add immediately after the last one:

```python
from app import host_metrics as _host_metrics_mod
_host_metrics_mod.init_scheduler(app)
```

Match the import style (aliased with underscore prefix) used for the other scheduler modules in the same block.

- [ ] **Step 2: Add in_docker to admin_page() template context**

Open `app/routes/admin_routes.py`. At the top of the file, verify `import os` is present. If not, add it alongside the other stdlib imports.

Find the `admin_page()` function (it calls `render_template('admin.html', ...)`). Add `in_docker=os.path.exists('/.dockerenv')` to the `render_template` call:

```python
return render_template(
    'admin.html',
    ...,
    in_docker=os.path.exists('/.dockerenv'),
)
```

- [ ] **Step 3: Add the host-metrics API route**

In `app/routes/admin_routes.py`, verify `import time` is present at the top. If not, add it. Then add this route near the other `GET /admin/api/...` routes:

```python
@bp.route('/api/host-metrics')
@_admin_required
def api_host_metrics():
    from app import host_metrics as _hm
    range_key = request.args.get('range', '1h')
    data = _hm.get_metrics(range_key)
    data['range'] = range_key
    data['generated_at'] = int(time.time())
    return jsonify(data)
```

Note: the blueprint `bp` has `url_prefix="/admin"`, so this route resolves to `GET /admin/api/host-metrics`.

- [ ] **Step 4: Manual smoke test**

Start the dev server (`python wsgi.py`). While logged in as admin, open:
```
https://localhost:5443/admin/api/host-metrics?range=1h
```

Expected response shape:
```json
{
  "cpu":  [{"ts": 1723633260, "v": 14.2}],
  "mem":  [{"ts": 1723633260, "v": 62.1}],
  "disk": [{"ts": 1723633260, "v": 35.8}],
  "range": "1h",
  "generated_at": 1723633320
}
```

If the arrays are empty (fresh DB, scheduler hasn't fired yet), seed a sample manually:

```bash
uv run python -c "
from app.host_metrics import init_db, record_sample, _DB_PATH
init_db()
record_sample()
print('seeded to', _DB_PATH)
"
```

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py app/routes/admin_routes.py
git commit -m "feat: register host_metrics scheduler, add /admin/api/host-metrics endpoint"
```

---

### Task 6: Feature 3 — Resource Graphs Frontend

**Files:**
- Modify: `app/templates/admin.html`
- Modify: `app/static/js/admin.js`
- Modify: `app/static/css/style.css`

**Interfaces:**
- Consumes: `GET /admin/api/host-metrics?range=<range>`, `window._inDocker` (bool injected by template), `Chart` global from `chart.min.js`
- Produces: three line charts (CPU / Memory / Disk) above the Admin tab bar, time-range pills (1H default), 60 s auto-refresh

---

- [ ] **Step 1: Load Chart.js in admin.html**

Find where JS files are loaded in `admin.html` (likely at the bottom of `<body>` or in a `{% block scripts %}` section). Add the Chart.js script tag **before** `admin.js`:

```html
<script src="{{ url_for('static', filename='js/vendor/chart.min.js') }}"></script>
```

- [ ] **Step 2: Inject in_docker flag into admin.html**

Find the existing inline `<script>` block near the top of `admin.html` (where `window._checks_meta` or similar globals are set). Add:

```html
<script>window._inDocker = {{ in_docker | tojson }};</script>
```

- [ ] **Step 3: Add metrics header HTML to admin.html**

Locate the admin page heading (`<h1>` or equivalent) and the tab bar `<div>` immediately below it. Insert the metrics header block **between** them:

```html
<div class="admin-metrics-header">
  <div class="metrics-range-bar">
    <span class="metrics-range-label">Time Range:</span>
    <button class="metrics-range-btn active" data-range="1h">1H</button>
    <button class="metrics-range-btn" data-range="4h">4H</button>
    <button class="metrics-range-btn" data-range="12h">12H</button>
    <button class="metrics-range-btn" data-range="1d">1D</button>
    <button class="metrics-range-btn" data-range="7d">7D</button>
    <button class="metrics-range-btn" data-range="14d">14D</button>
  </div>
  <div class="metrics-cards">
    <div class="metrics-card">
      <div class="metrics-card-title">CPU</div>
      <div class="metrics-chart-wrap"><canvas id="chartCpu"></canvas></div>
    </div>
    <div class="metrics-card">
      <div class="metrics-card-title">
        Memory
        <span class="metrics-docker-note" id="metricsDockerNote"
              title="Reflects host memory — container memory limit may differ"
              style="display:none;">ⓘ</span>
      </div>
      <div class="metrics-chart-wrap"><canvas id="chartMem"></canvas></div>
    </div>
    <div class="metrics-card">
      <div class="metrics-card-title">Disk</div>
      <div class="metrics-chart-wrap"><canvas id="chartDisk"></canvas></div>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add CSS to style.css**

Open `app/static/css/style.css`. Append to the end of the file:

```css
/* Admin host metrics header */
.admin-metrics-header {
    margin-bottom: 1.5rem;
}

.metrics-range-bar {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
}

.metrics-range-label {
    font-size: 0.82rem;
    opacity: 0.7;
    margin-right: 0.25rem;
}

.metrics-range-btn {
    padding: 0.2rem 0.65rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: transparent;
    cursor: pointer;
    font-size: 0.78rem;
    line-height: 1.4;
    transition: background 0.15s, color 0.15s;
}

.metrics-range-btn.active,
.metrics-range-btn:hover {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
}

.metrics-cards {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
}

@media (max-width: 900px) {
    .metrics-cards { grid-template-columns: 1fr; }
}

.metrics-card {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
}

.metrics-card-title {
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 0.4rem;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}

.metrics-chart-wrap {
    height: 130px;
    position: relative;
}

.metrics-docker-note {
    font-size: 0.75rem;
    opacity: 0.55;
    cursor: help;
}
```

- [ ] **Step 5: Add chart JS to admin.js**

At the end of `app/static/js/admin.js`, add:

```javascript
// --- Host Metrics Charts ---

(function initAdminMetrics() {
    let charts   = {};
    let current  = '1h';
    let timer    = null;

    function fmtLabel(ts, range) {
        const d = new Date(ts * 1000);
        if (['1h', '4h', '12h'].includes(range)) {
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function makeChart(canvasId, color) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    data: [],
                    borderColor: color,
                    backgroundColor: color + '28',
                    fill: true,
                    tension: 0.35,
                    pointRadius: 0,
                    borderWidth: 1.5,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    y: {
                        min: 0, max: 100,
                        ticks: { callback: v => v + '%', maxTicksLimit: 5 },
                    },
                    x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(1) + '%' } },
                },
            },
        });
    }

    function loadMetrics(range) {
        current = range;
        document.querySelectorAll('.metrics-range-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.range === range);
        });
        fetch('/admin/api/host-metrics?range=' + range)
            .then(r => r.json())
            .then(data => {
                [['cpu', charts.cpu], ['mem', charts.mem], ['disk', charts.disk]]
                    .forEach(([key, chart]) => {
                        if (!chart) return;
                        chart.data.labels               = data[key].map(p => fmtLabel(p.ts, range));
                        chart.data.datasets[0].data     = data[key].map(p => p.v);
                        chart.update('none');
                    });
            })
            .catch(() => {});
    }

    function init() {
        charts.cpu  = makeChart('chartCpu',  '#4e79a7');
        charts.mem  = makeChart('chartMem',  '#f28e2b');
        charts.disk = makeChart('chartDisk', '#59a14f');

        if (!charts.cpu) return; // canvases absent — not on admin page

        if (window._inDocker) {
            const note = document.getElementById('metricsDockerNote');
            if (note) note.style.display = 'inline';
        }

        document.querySelectorAll('.metrics-range-btn').forEach(btn => {
            btn.addEventListener('click', () => loadMetrics(btn.dataset.range));
        });

        loadMetrics('1h');
        timer = setInterval(() => loadMetrics(current), 60000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
```

- [ ] **Step 6: Manual verification**

Start the server (`python wsgi.py`). Open the Admin page. Verify:

1. Three chart cards appear above the admin tab bar showing CPU / Memory / Disk.
2. **1H** pill is active by default; charts render (may be sparse on a fresh DB — seed if needed).
3. Clicking **4H / 12H / 1D / 7D / 14D** reloads all three charts without a page refresh.
4. Charts remain visible and responsive when switching between admin tabs.
5. After 60 seconds, charts auto-refresh (verify via browser DevTools Network tab — a `host-metrics` fetch fires).
6. On a Docker host (or by temporarily creating `/.dockerenv`), the Memory card shows "ⓘ" with a hover tooltip.

Seed data to make charts non-empty:
```bash
uv run python -c "
import time
from app.host_metrics import init_db, record_sample, _DB_PATH
init_db()
for _ in range(10):
    record_sample()
    time.sleep(2)
print('seeded to', _DB_PATH)
"
```

- [ ] **Step 7: Commit**

```bash
git add app/templates/admin.html app/static/js/admin.js app/static/css/style.css
git commit -m "feat: add CPU/memory/disk resource graphs to admin page"
```
