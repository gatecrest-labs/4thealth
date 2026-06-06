# 4THealth Production Deployment Guide

Linux Server + Nginx + Gunicorn + Active Directory LDAP Authentication

This guide walks through deploying 4THealth on RHEL/Rocky/AlmaLinux or Ubuntu/Debian with:

- Gunicorn as the WSGI application server
- Nginx as the TLS-terminating reverse proxy
- Active Directory authentication via LDAP with AD group to role mapping
- Systemd service management
- Role-based access control (Admin, Viewer) — already implemented in the codebase

> **Note:** RBAC, session management, group/tab permissions, and the application log viewer
> are all implemented and ready to use out of the box. Phase 5 of this guide explains how
> they work and what (if anything) to configure for your environment.

Estimated total time: 2-4 hours for a first deployment.

## Phase 1 - Linux Server Prerequisites

Goal: A clean server with the right OS packages, a dedicated service account, and firewall rules allowing HTTPS.

### 1.1 Supported OS

Tested on:

- Rocky Linux 9 / AlmaLinux 9 / RHEL 9
- Ubuntu 22.04 LTS / 24.04 LTS
- Debian 12

Minimum specs: 2 vCPU, 2 GB RAM, 20 GB disk.

### 1.2 OS Package Installation

```bash
# RHEL / Rocky / AlmaLinux
sudo dnf install -y git curl openssl nginx python3 python3-pip \
    gcc python3-devel openldap-devel cyrus-sasl-devel

# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y git curl openssl nginx python3 python3-pip \
    build-essential python3-dev libldap2-dev libsasl2-dev libssl-dev
```

### 1.3 Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/env

# Verify
uv --version
```

### 1.4 Create a Dedicated Service Account

```bash
sudo useradd --system --shell /sbin/nologin --home /opt/4thealth \
    --create-home 4thealth

# Give your admin user sudo-free read access to the app directory
sudo usermod -aG 4thealth $USER
```

### 1.5 Firewall Rules

```bash
# RHEL / Rocky / AlmaLinux (firewalld)
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp
sudo ufw reload

# Verify the app can reach FortiManager (outbound HTTPS on port 443)
curl -k https://<your-fortimanager-ip>/jsonrpc --max-time 5
```

## Phase 2 - Application Deployment

Goal: Deploy the application code, configure the environment, generate SSL credentials, add a production user, and verify the app starts.

### 2.1 Clone or Copy the Repository

```bash
sudo mkdir -p /opt/4thealth
sudo chown 4thealth:4thealth /opt/4thealth

# Option A - git clone (recommended)
sudo -u 4thealth git clone <your-repo-url> /opt/4thealth

# Option B - copy from dev machine (replace IP/path)
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude 'certs' \
    /path/to/fortigate-health/ user@server:/opt/4thealth/
```

### 2.2 Install Python Dependencies

```bash
cd /opt/4thealth
sudo -u 4thealth uv sync --extra prod
```

This installs Flask, gunicorn, APScheduler, bcrypt, requests, and python-dotenv into `/opt/4thealth/.venv`.

### 2.3 Configure Environment Variables

```bash
sudo -u 4thealth cp .env.example .env
sudo chmod 640 /opt/4thealth/.env
sudo chown 4thealth:4thealth /opt/4thealth/.env

# Edit .env
sudo -u 4thealth nano /opt/4thealth/.env
```

Minimum required changes in `.env`:

```dotenv
SECRET_KEY=<generate below>
FMG_PRIMARY_HOST=<FortiManager primary IP>
FMG_API_TOKEN=<bearer token from FortiManager>   # preferred
# FMG_USERNAME=<api account>                      # fallback if no token
# FMG_PASSWORD=<api password>
COOKIE_SECURE=true
PORT=8100

# Optional — change the nightly summary recalculation time (default 01:00 local)
# SUMMARY_REFRESH_HOUR=1
# SUMMARY_REFRESH_MINUTE=0
```

### 2.3a Configure Infrastructure Dashboard Targets

```bash
sudo -u 4thealth cp infra_targets.example.json infra_targets.json
sudo chmod 640 /opt/4thealth/infra_targets.json
sudo chown 4thealth:4thealth /opt/4thealth/infra_targets.json

# Edit infra_targets.json — set the correct IP for each device
sudo -u 4thealth nano /opt/4thealth/infra_targets.json
```

Each entry in the array is one dashboard card:

```json
{ "label": "FortiManager Primary", "host": "10.0.0.1", "type": "FortiManager" }
```

To add devices (e.g. FortiAuthenticator), append entries to the array. No code changes or service restarts are needed beyond a page refresh — the list is read at each `/api/infrastructure` call.

Generate a strong `SECRET_KEY`:

```bash
cd /opt/4thealth
sudo -u 4thealth uv run python manage_users.py secret
```

### 2.4 Generate a TLS Certificate

Option A - Self-signed (internal/lab use):

```bash
sudo mkdir -p /opt/4thealth/certs
sudo openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout /opt/4thealth/certs/key.pem \
  -out /opt/4thealth/certs/cert.pem \
  -days 3650 \
  -subj "/CN=4thealth.yourdomain.com" \
  -addext "subjectAltName=DNS:4thealth.yourdomain.com,IP:<SERVER_IP>"
sudo chown -R 4thealth:4thealth /opt/4thealth/certs
sudo chmod 600 /opt/4thealth/certs/key.pem
```

Option B - Internal CA / corporate cert:

- Place cert at `/opt/4thealth/certs/cert.pem`
- Place key at `/opt/4thealth/certs/key.pem`
- Or update `SSL_CERT` / `SSL_KEY` in `.env`

Option C - Let's Encrypt (public DNS only):

```bash
sudo dnf install -y certbot python3-certbot-nginx
# or
sudo apt-get install -y certbot python3-certbot-nginx

sudo certbot --nginx -d 4thealth.yourdomain.com
```

### 2.5 Create Initial User Accounts (local fallback)

```bash
cd /opt/4thealth
sudo -u 4thealth uv run python manage_users.py add admin --role admin
sudo -u 4thealth uv run python manage_users.py add readonly --role viewer
```

Keep at least one local admin account in `users.json` for emergency access.

### 2.6 Create the Systemd Service

Create `/etc/systemd/system/4thealth.service`:

```ini
[Unit]
Description=4THealth Dashboard
After=network.target

[Service]
Type=simple
User=4thealth
Group=4thealth
WorkingDirectory=/opt/4thealth
EnvironmentFile=/opt/4thealth/.env
ExecStart=/opt/4thealth/.venv/bin/gunicorn \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --bind 127.0.0.1:8100 \
    --timeout 130 \
    --access-logfile /var/log/4thealth/access.log \
    --error-logfile /var/log/4thealth/error.log \
    wsgi:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> **Worker configuration note:** The `gthread` worker class with `--workers 2 --threads 4` is required because the background summary job uses a Python `threading.Thread`. The default `sync` worker model forks separate processes — background threads started in the parent do not transfer to child workers, which means the summary job would never start. The `gthread` model shares in-process threads, so APScheduler and the summary job run correctly in each worker. If you need more concurrency, increase `--threads` rather than `--workers`.
>
> **Timeout rationale:** `--timeout 130` is set to match the FMG client's worst-case paginated request ceiling (120 s per page fetch in `_get_paged`) plus a 10 s buffer. This ensures gunicorn never kills a thread that is legitimately waiting on a slow FortiManager response. The Nginx `proxy_read_timeout 140s` sits 10 s above the gunicorn timeout so Nginx never cuts the upstream connection before gunicorn has had a chance to return a proper error response. If a user closes their browser mid-request, the in-flight thread continues to run until the FMG call completes and then exits cleanly — all FMG sessions are closed by the context manager (`with make_client()`) regardless of whether the response is delivered.

Then run:

```bash
sudo mkdir -p /var/log/4thealth
sudo chown 4thealth:4thealth /var/log/4thealth

sudo systemctl daemon-reload
sudo systemctl enable 4thealth
sudo systemctl start 4thealth
sudo systemctl status 4thealth

# Tail logs
sudo journalctl -u 4thealth -f
```

### 2.7 Smoke Test (before Nginx)

```bash
curl -sk http://127.0.0.1:8100/login | grep -i 4thealth
```

## Phase 3 - Nginx Reverse Proxy + TLS Termination

Goal: Nginx handles TLS on port 443, proxies requests to Gunicorn on `127.0.0.1:8100`, and optionally redirects port 80 to 443.

### 3.1 Nginx Configuration

Create `/etc/nginx/conf.d/4thealth.conf`:

```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name 4thealth.yourdomain.com;
    return 301 https://$host$request_uri;
}

# HTTPS reverse proxy
server {
    listen 443 ssl http2;
    server_name 4thealth.yourdomain.com;

    ssl_certificate     /opt/4thealth/certs/cert.pem;
    ssl_certificate_key /opt/4thealth/certs/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location / {
        proxy_pass         http://127.0.0.1:8100;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 140s;
        proxy_connect_timeout 10s;
    }

    location /static/ {
        alias /opt/4thealth/app/static/;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }

    location ~ /\.(env|git)      { deny all; return 404; }
    location /users.json          { deny all; return 404; }
    location /infra_targets.json  { deny all; return 404; }
    location /policy_db.json      { deny all; return 404; }
}
```

```bash
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

### 3.2 SELinux (RHEL/Rocky only)

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo restorecon -Rv /opt/4thealth/certs/
```

### 3.3 Verify End-to-End

```bash
curl -sk https://4thealth.yourdomain.com/login | grep -i 4thealth

openssl s_client -connect 4thealth.yourdomain.com:443 </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -dates
```

## Phase 4 - Active Directory / LDAP Authentication

Goal: Replace (or supplement) local bcrypt auth with Active Directory auth. Users log in with AD credentials, and AD groups map to app roles.

### 4.1 Install python-ldap

```bash
cd /opt/4thealth

# Add "python-ldap>=3.4" to [project] dependencies in pyproject.toml
sudo nano /opt/4thealth/pyproject.toml

sudo -u 4thealth uv sync --extra prod
```

### 4.2 Add AD Configuration to .env

```dotenv
AD_ENABLED=true
AD_SERVER=ldaps://your-dc.yourdomain.com:636
AD_DOMAIN=YOURDOMAIN
AD_BASE_DN=DC=yourdomain,DC=com
AD_BIND_USER=CN=svc_4thealth,OU=Service Accounts,DC=yourdomain,DC=com
AD_BIND_PASSWORD=<service-account-password>
AD_USER_SEARCH=OU=Users,DC=yourdomain,DC=com
AD_GROUP_ADMIN=CN=4THealth-Admins,OU=Security Groups,DC=yourdomain,DC=com
AD_GROUP_VIEWER=CN=4THealth-Viewers,OU=Security Groups,DC=yourdomain,DC=com
AD_VERIFY_SSL=false
```

### 4.3 Update app/config.py

Add inside `Config`:

```python
# Active Directory / LDAP
AD_ENABLED       = os.environ.get("AD_ENABLED", "false").lower() == "true"
AD_SERVER        = os.environ.get("AD_SERVER", "")
AD_DOMAIN        = os.environ.get("AD_DOMAIN", "")
AD_BASE_DN       = os.environ.get("AD_BASE_DN", "")
AD_BIND_USER     = os.environ.get("AD_BIND_USER", "")
AD_BIND_PASSWORD = os.environ.get("AD_BIND_PASSWORD", "")
AD_USER_SEARCH   = os.environ.get("AD_USER_SEARCH", "")
AD_GROUP_ADMIN   = os.environ.get("AD_GROUP_ADMIN", "")
AD_GROUP_VIEWER  = os.environ.get("AD_GROUP_VIEWER", "")
AD_VERIFY_SSL    = os.environ.get("AD_VERIFY_SSL", "false").lower() == "true"
```

### 4.4 Replace app/auth.py with AD-aware version

Update `app/auth.py` to add LDAP/AD authentication. The structure mirrors the
FortiAuthenticator RADIUS implementation shown in the
[Optional: FortiAuthenticator RADIUS Authentication](#optional-fortiauthentic
ator-radius-authentication) section — replace the RADIUS bind with an `ldap3`
bind using the AD credentials from `.env`, check `memberOf` for the admin/viewer
group DNs, and preserve the local bcrypt fallback path unchanged.

Key integration points:
- `authenticate(username, password)` — attempt AD bind first; fall back to local bcrypt on failure
- `get_user_role(username)` — resolve role from AD group membership (`AD_GROUP_ADMIN` / `AD_GROUP_VIEWER`)
- Keep at least one local `admin` entry in `users.json` as an emergency fallback

### 4.5 Create AD Security Groups

```powershell
New-ADGroup -Name "4THealth-Admins"  -GroupScope Global -GroupCategory Security
New-ADGroup -Name "4THealth-Viewers" -GroupScope Global -GroupCategory Security

Add-ADGroupMember -Identity "4THealth-Admins"  -Members "jsmith"
Add-ADGroupMember -Identity "4THealth-Viewers" -Members "bjones","mlee"

New-ADUser -Name "svc_4thealth" `
  -SamAccountName "svc_4thealth" `
  -UserPrincipalName "svc_4thealth@yourdomain.com" `
  -AccountPassword (ConvertTo-SecureString "StrongPassword123!" -AsPlainText -Force) `
  -Enabled $true `
  -PasswordNeverExpires $true `
  -Description "4THealth LDAP bind account - read-only"
```

### 4.6 Test AD Authentication

```bash
ldapsearch -x -H ldaps://your-dc.yourdomain.com:636 \
  -D "CN=svc_4thealth,OU=Service Accounts,DC=yourdomain,DC=com" \
  -w "StrongPassword123!" \
  -b "OU=Users,DC=yourdomain,DC=com" \
  "(sAMAccountName=jsmith)" dn memberOf

sudo systemctl restart 4thealth
sudo journalctl -u 4thealth -n 30
```

## Phase 5 - Role-Based Access Control (RBAC)

> **Already implemented.** This phase explains what is in place so you can verify
> correct behavior and know what to configure. No code changes are required.

### 5.1 How RBAC Works

4THealth ships with a fully-implemented RBAC system:

- **Roles:** `admin` (full access) or `viewer` (tab-based access).
- **Sessions:** Role is stored in the signed Flask session cookie at login. Clients cannot tamper with it — the `SECRET_KEY` cryptographically signs and verifies the cookie on every request.
- **Route protection:** Every route that renders a page uses `@login_required`. Admin-only routes additionally enforce `@admin_required` (returns HTTP 403 to non-admins). Tab-access routes use `@tab_required("<tab_key>")`.
- **Template rendering:** `current_role` and `allowed_tabs` are injected as Jinja2 globals by the app factory (`app/__init__.py`), so every template can conditionally show or hide nav items.

### 5.2 Role and Tab Summary

| Role   | Dashboard | Firewalls | Device Versions | Rule Review | Rule Validation | Zone Policy | Device Review | Map (Beta) | Admin page | Raw/Debug endpoints |
|--------|-----------|-----------|-----------------|-------------|-----------------|-------------|---------------|------------|------------|---------------------|
| admin  | Always    | Always    | Always          | Always      | Always          | Always      | Always        | Always     | YES        | YES                 |
| viewer | Per group | Per group | Per group       | Per group   | Per group       | Per group   | Per group     | Per group  | NO         | NO                  |

Viewer tab access is the **union** of all tabs granted by the groups the user belongs to, configured in **Admin → Groups & Permissions**.

### 5.3 Verifying RBAC Is Working

After deployment, confirm the following:

1. Log in as a `viewer` account with no group memberships — the nav bar should show no content tabs (Dashboard, Firewalls, etc.).
2. Add the viewer to a group with Dashboard access. On next login the Dashboard tab should appear.
3. While logged in as a viewer, directly browse to `/admin` — expect HTTP 403.
4. While logged in as a viewer, call `/api/infrastructure/raw` — expect HTTP 403.
5. Log in as an `admin` — all tabs, the Admin nav link, and raw endpoints should be accessible.

### 5.4 Session and Cookie Configuration

These are already set in `app/config.py`:

```python
SESSION_COOKIE_HTTPONLY = True      # JS cannot read the cookie
SESSION_COOKIE_SAMESITE = "Lax"    # CSRF mitigation
SESSION_COOKIE_SECURE   = True      # Set automatically when TLS is detected
PERMANENT_SESSION_LIFETIME = 3600  # 1-hour session expiry
```

In production behind Nginx, ensure `COOKIE_SECURE=true` is set in `.env`.

### 5.5 Application Logs

The **Admin → Application Logs** tab provides a live in-memory log viewer:

- Up to **2 000 entries**, cleared on process restart.
- Five capture levels: `ERROR`, `WARN`, `INFO` (default), `DEBUG`, `TRACE`.
- Level can be changed at runtime from the Admin UI — no restart needed.
- Thread-safe ring buffer; safe under gunicorn multi-worker deployments (each worker has its own buffer).

## Phase 6 - Hardening and Security

Goal: Lock down the production environment following security best practices.

### 6.1 Secure the .env File

```bash
sudo chmod 640 /opt/4thealth/.env
sudo chown 4thealth:4thealth /opt/4thealth/.env
ls -la /opt/4thealth/.env
```

Expected mode: `-rw-r-----`.

### 6.2 Secure users.json, infra_targets.json, and policy_db.json

```bash
sudo chmod 640 /opt/4thealth/users.json
sudo chown 4thealth:4thealth /opt/4thealth/users.json

sudo chmod 640 /opt/4thealth/infra_targets.json
sudo chown 4thealth:4thealth /opt/4thealth/infra_targets.json

sudo chmod 640 /opt/4thealth/policy_db.json
sudo chown 4thealth:4thealth /opt/4thealth/policy_db.json
```

### 6.3 Rotate Flask SECRET_KEY

```bash
uv run python manage_users.py secret
# Update .env
sudo systemctl restart 4thealth
```

Note: rotating `SECRET_KEY` invalidates all active sessions.

### 6.4 Log Rotation

Create `/etc/logrotate.d/4thealth`:

```conf
/var/log/4thealth/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 4thealth 4thealth
    postrotate
        systemctl kill -s USR1 4thealth
    endscript
}
```

### 6.5 Fail2ban (Brute Force Protection)

```bash
sudo dnf install -y fail2ban
# or
sudo apt-get install -y fail2ban
```

Create `/etc/fail2ban/jail.d/4thealth.conf`:

```ini
[4thealth-login]
enabled   = true
port      = https
filter    = 4thealth-login
logpath   = /var/log/4thealth/access.log
maxretry  = 5
findtime  = 300
bantime   = 3600
```

Create `/etc/fail2ban/filter.d/4thealth-login.conf`:

```ini
[Definition]
failregex = ^<HOST> .* "POST /login .*" 401
```

```bash
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
```

### 6.6 Nginx Rate Limiting

Add to `nginx.conf` or `conf.d/4thealth.conf`:

```nginx
# In http {}
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;

# In server/location
location /login {
    limit_req zone=login burst=3 nodelay;
    proxy_pass http://127.0.0.1:8100;
    ...
}
```

### 6.7 SELinux Audit (RHEL/Rocky)

```bash
sudo ausearch -c gunicorn --ts recent
sudo ausearch -c nginx --ts recent
sudo setsebool -P httpd_can_network_connect 1
```

### 6.8 Security Checklist

- [ ] `SECRET_KEY` is a 64-char random hex string
- [ ] `.env` permission is `640`, owner `4thealth`
- [ ] `users.json` permission is `640`, owner `4thealth`
- [ ] `policy_db.json` permission is `640`, owner `4thealth`
- [ ] `COOKIE_SECURE=true` in `.env`
- [ ] `AD_BIND_PASSWORD` is strong and unique
- [ ] `FMG_VERIFY_SSL=true` if FMG has a valid cert
- [ ] Nginx HSTS header is present
- [ ] TLS 1.0/1.1 are disabled
- [ ] fail2ban is running and monitoring `/login`
- [ ] Port `8100` is not externally exposed
- [ ] `certs/key.pem` permission is `600`
- [ ] log rotation is configured
- [ ] Gunicorn is using `gthread` worker class (required for background summary job and map cache — see Phase 2.6 note)
- [ ] Gunicorn `--timeout 130` and Nginx `proxy_read_timeout 140s` are set (covers 120 s paginated FMG calls — see Phase 2.6 timeout note)
- [ ] `SUMMARY_REFRESH_HOUR` is set to a low-traffic window (default `1` = 01:00 local time)
- [ ] `MAP_CACHE_INTERVAL_HOURS` is set appropriately (default `24` — once per day is sufficient)

### 6.9 Map (Beta) Tab — Internet connectivity and tile server

The Map (Beta) tab renders device locations on an **OpenStreetMap** base layer using the Leaflet library. In production there are two things to confirm:

**No internet connectivity required for the app server itself.** All Leaflet/MarkerCluster JavaScript and CSS are bundled in `app/static/vendor/` and served from your own server — no CDN calls are made from the server process.

**Users' browsers do need to reach the OpenStreetMap tile server** (`https://{s}.tile.openstreetmap.org`) to render the map background. The tile requests come from each user's browser, not from the 4THealth server. If your users access 4THealth from a browser on the corporate network:

| Browser network access | Result |
|---|---|
| Browser can reach `*.tile.openstreetmap.org` on port 443 | Map tiles render normally |
| Browser is blocked from that domain | Map shows a grey background; device pins and clustering still work correctly — only the background imagery is missing |

If internet access from browsers is restricted and you need a fully on-prem tile server, a self-hosted alternative (e.g. [OpenMapTiles](https://openmaptiles.org/) or a simple tile proxy) can be substituted by changing the `L.tileLayer(...)` URL in `app/static/js/map.js`.

**The `us-states.json` GeoJSON file** (`app/static/vendor/us-states.json`) is already bundled in the repo. No external fetch is needed for the point-in-polygon state lookup.

**Security checklist additions for Map (Beta):**

- [ ] Confirm user browsers can reach `tile.openstreetmap.org:443`, or document that map tiles will be unavailable and device pins still render
- [ ] Grant the `map_view` tab key to any group that should see the Map tab via **Admin → Groups & Permissions**
- [ ] Optionally set `MAP_CACHE_INTERVAL_HOURS` in `.env` (default `24`) to control how often device locations are re-fetched from FortiManager

### 6.10 Zone Policy Tab — policy_db.json

The Zone Policy tab requires a `policy_db.json` file in the project root (`/opt/4thealth/policy_db.json`). This file is the network segmentation policy database — it is not committed to the repository and must be placed on the server manually.

**Create or copy the file:**

```bash
# Option A — copy from another server or dev machine
scp policy_db.json deploy@server:/opt/4thealth/policy_db.json

# Option B — start from the example (creates an empty but valid structure)
sudo -u 4thealth cp policy_db.example.json /opt/4thealth/policy_db.json
```

**Set correct permissions:**

```bash
sudo chmod 640 /opt/4thealth/policy_db.json
sudo chown 4thealth:4thealth /opt/4thealth/policy_db.json
```

**Block direct HTTP access in Nginx** (already included in the Phase 3 config):

```nginx
location /policy_db.json { deny all; return 404; }
```

**What happens if the file is missing:**

The Zone Policy tab loads but all queries return an empty result with a warning. No other tabs are affected. The file can be added or replaced at runtime — changes take effect immediately on the next request without a service restart.

**Backing up the database:**

```bash
sudo cp /opt/4thealth/policy_db.json /opt/4thealth/policy_db.json.bak.$(date +%Y%m%d)
```

The file is written atomically by the app on each admin edit, so backups are safe to take at any time.

**Security checklist additions for Zone Policy:**

- [ ] `policy_db.json` permission is `640`, owner `4thealth`
- [ ] `policy_db.json` is blocked in Nginx (`deny all; return 404`)
- [ ] Zone Policy Edit Database tab is restricted to `admin` role (enforced by `@admin_required` — no config needed)
- [ ] `us-states.json` in `app/static/vendor/` is present (committed to repo — no action needed)

## Phase 7 - Monitoring, Updates and Maintenance

Goal: Keep the service running, up-to-date, and observable in production.

### 7.1 Systemd Watchdog and Health Check

```bash
sudo systemctl status 4thealth
sudo journalctl -u 4thealth -f
sudo tail -f /var/log/4thealth/access.log
```

### 7.1a Monitoring the Background Summary Job

The managed network summary job writes structured log lines you can grep for in journald:

```bash
# Confirm the job started at app boot
sudo journalctl -u 4thealth | grep "summary_job"

# See the final result of the last run (firewalls, rules, elapsed time)
sudo journalctl -u 4thealth | grep "summary_job: done"

# See current status via the API (requires an active session cookie)
curl -sk --cookie "session=..." https://4thealth.yourdomain.com/api/summary
```

Expected log output after a successful run:

```
summary_job: scheduler started — daily at 01:00 local time
summary_job: starting calculation
summary_job: 24 ADOMs found: [...]
summary_job: 900 firewalls across 4 ADOMs with devices: [...]
summary_job: ADOM ENTERPRISE-SDWAN — 33 packages to count
...
summary_job: done in 277.7s — 900 firewalls, 14767 rules
```

If the job fails, `status` in the `/api/summary` response will be `"error"` with an `error` field explaining what went wrong. The FMG API token must have read access to `dvmdb`, `pm/pkg`, and `pm/config`.

**Manual refresh after a large change window:**

```bash
# POST to the refresh endpoint (admin session required)
curl -sk -X POST --cookie "session=..." https://4thealth.yourdomain.com/api/summary/refresh
# Returns: {"queued": true}
# Watch journald for the job to complete
sudo journalctl -u 4thealth -f | grep summary_job
```

### 7.1b Monitoring the Map Cache

The map location cache writes log lines you can grep for:

```bash
# Confirm the cache started at boot
sudo journalctl -u 4thealth | grep "map_cache"

# See last completed run
sudo journalctl -u 4thealth | grep "map_cache: done"

# Check current status via the API (requires active session cookie)
curl -sk --cookie "session=..." https://4thealth.yourdomain.com/api/map/status
```

Expected log on a successful run:
```
map_cache: scheduler started — every 24 hours
map_cache: starting refresh
map_cache: done in 18.4s — 846 devices with coords across 10 ADOMs
```

The map cache is lightweight (no per-device proxy calls — only dvmdb reads) and typically completes in under 30 seconds regardless of ADOM count.

### 7.2 Application Health Endpoint (optional)

Add to `app/routes/api_routes.py`:

```python
@bp.route("/health")
def health():
    return jsonify({"status": "ok"}), 200
```

Monitor endpoint:

```bash
curl -sk https://4thealth.yourdomain.com/api/health
# Expected: {"status": "ok"}
```

### 7.3 Updating the Application

```bash
cd /opt/4thealth
sudo -u 4thealth git pull
sudo -u 4thealth uv sync --extra prod
grep -n "v=" app/templates/base.html
sudo systemctl restart 4thealth
sudo systemctl status 4thealth
```

### 7.4 Updating AD Group Membership

No app restart is needed. AD group changes apply at next login.

To force immediate re-authentication:

- Remove user from both AD groups
- Wait for session expiration (`PERMANENT_SESSION_LIFETIME`)
- Or rotate `SECRET_KEY` to invalidate all sessions

### 7.5 Backup

```bash
sudo cp /opt/4thealth/.env /opt/4thealth/.env.bak.$(date +%Y%m%d)
sudo cp /opt/4thealth/users.json /opt/4thealth/users.json.bak.$(date +%Y%m%d)
sudo cp /opt/4thealth/infra_targets.json /opt/4thealth/infra_targets.json.bak.$(date +%Y%m%d)
sudo cp /opt/4thealth/policy_db.json /opt/4thealth/policy_db.json.bak.$(date +%Y%m%d)
gpg --symmetric /opt/4thealth/.env.bak.*
```

### 7.6 SSL Certificate Renewal

Option A - Let's Encrypt:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

Option B - Manual cert replacement:

```bash
sudo systemctl restart nginx
sudo systemctl restart 4thealth
```

Option C - Self-signed renewal:

- Re-run the `openssl` command from Phase 2.4 when needed.

## Migrating Local Groups to Active Directory

When you enable AD authentication (Phase 4), the `users.json` member lists inside
`groups.json` are no longer authoritative — AD resolves membership dynamically at
login. Follow these steps to migrate without losing tab permissions.

### Pre-migration checklist

- [ ] Phase 4 AD authentication is working (`AD_ENABLED=true`).
- [ ] Each AD group that should map to an app group exists in Active Directory.
- [ ] You have at least one local admin fallback account (see Phase 2.5).

### Step 1 — Match group names to AD group names

The app looks up tab permissions by **group name** stored in `groups.json`.
When AD is active, membership is resolved from AD `memberOf` — but only if
the group names in `groups.json` match the AD group names (or role strings).

Two common mapping strategies:

**Strategy A — name groups to match AD group SAMAccountNames**

```
groups.json group name:  "4THealth-NOC"
AD group SAMAccountName: "4THealth-NOC"
```

Update your AD auth code so that after a successful bind it reads the user's
`memberOf` attribute, extracts the `CN=` part of each group DN, and passes
those CN values to `get_allowed_tabs(username)` in place of the local member
lookup.

**Strategy B — keep generic group names, map AD groups to roles only**

Keep two groups (`admin`, `viewer`) in `groups.json` and rely solely on the
`AD_GROUP_ADMIN` / `AD_GROUP_VIEWER` env-vars to assign the role. Then grant
the role-level tab permissions to the `admin` and `viewer` groups.

### Step 2 — Update app/groups.py for AD membership lookup

Replace the `_load_users()` call inside `get_allowed_tabs()` with a call to your
AD membership resolver:

```python
def get_allowed_tabs(username: str, ad_groups: list[str] | None = None) -> set[str]:
    """ad_groups: list of CN values resolved from AD memberOf, or None for local auth."""
    from app.auth import _load_users
    users = _load_users()
    user_entry = users.get(username, {})
    if user_entry.get("role") == "admin":
        return set(KNOWN_TABS.keys())

    with _lock:
        groups = _load()

    # When AD is active, use the injected group list instead of stored members
    if ad_groups is not None:
        tabs: set[str] = set()
        for group_name in ad_groups:
            g = groups.get(group_name)
            if g:
                tabs.update(g.get("allowed_tabs", []))
        return tabs

    # Local-auth path (fallback)
    tabs = set()
    for g in groups.values():
        if username in g.get("members", []):
            tabs.update(g.get("allowed_tabs", []))
    return tabs
```

Pass `ad_groups=<resolved_cns>` from `auth_routes.py` at login time.

### Step 3 — Clear stale member lists (optional hygiene)

After AD migration, the `members` arrays in `groups.json` are no longer used for
AD-authenticated users. You can clear them via the Admin UI (Edit → remove all
members) or leave them in place — they are ignored when `ad_groups` is passed.

### Step 4 — Backup groups.json before any changes

```bash
cp /opt/4thealth/groups.json /opt/4thealth/groups.json.bak.$(date +%Y%m%d)
```

`groups.json` is gitignored runtime data — keep this backup copy as your version history.

### Step 5 — Test with a non-admin account

1. Log in with an AD viewer account.
2. Confirm only the expected tabs are visible.
3. Log in with an AD admin account.
4. Confirm all tabs are visible including the Admin nav link.
5. Confirm non-admins receive `403` when they directly browse `/admin`.

### Step 6 — Keep the local admin fallback

Do **not** delete the local `admin` account from `users.json`.
If the AD server is unreachable, local accounts are the only way in.
Add this to your runbook: "If AD is down and login fails, set `AD_ENABLED=false`
in `.env`, restart the service, log in with the local admin account, re-enable
after AD recovery."

---

## Optional: FortiAuthenticator RADIUS Authentication

This section covers using FortiAuthenticator (FAC) as the RADIUS authentication proxy instead of connecting directly to Active Directory via LDAP. FAC handles the AD bind and group lookups internally — the app only needs to speak RADIUS. This is the preferred approach in environments where direct LDAP access to domain controllers is restricted or where FAC is already deployed for other VPN/SSO workflows.

**How it works:**

1. 4THealth sends a RADIUS Access-Request (username + password) to FAC.
2. FAC validates the credentials against AD and resolves the user's AD groups.
3. FAC returns a RADIUS Access-Accept with a `Filter-Id` or `Class` attribute carrying the user's role group name.
4. 4THealth reads that attribute, maps it to `admin` or `viewer`, and proceeds with the normal session setup.

Local `users.json` accounts continue to work as a fallback — the RADIUS path only activates when `RADIUS_ENABLED=true`.

### FAC-1 — FortiAuthenticator Configuration

These steps are performed in the FortiAuthenticator web UI.

#### FAC-1.1 Add the RADIUS NAS client

**Authentication → RADIUS Service → Clients → Create New**

| Field | Value |
|---|---|
| Name | `4thealth-prod` |
| Client IP/Subnet | `<4THealth server IP>` |
| Secret | `<generate a strong shared secret>` |
| Authentication method | PAP (or CHAP — must match `RADIUS_AUTH_METHOD` in `.env`) |

#### FAC-1.2 Connect FAC to Active Directory

If FAC is already joined to AD for other services, skip to FAC-1.3.

**Authentication → Remote Auth Servers → LDAP → Create New**

| Field | Value |
|---|---|
| Name | `AD-Corp` |
| Server name/IP | `your-dc.yourdomain.com` |
| Server port | `636` (LDAPS) or `389` |
| Distinguished name | `DC=yourdomain,DC=com` |
| Bind type | Regular |
| Username | `CN=svc_4thealth,OU=Service Accounts,DC=yourdomain,DC=com` |
| Password | `<service account password>` |

Test the connection using the **Test** button before saving.

#### FAC-1.3 Create a RADIUS User Group for each role

**Authentication → User Groups → Create New** — repeat for each role.

Group 1 (admin role):

| Field | Value |
|---|---|
| Name | `4THealth-Admins` |
| Type | RADIUS |
| Members | Leave empty — membership comes from AD group below |
| Remote servers | Select `AD-Corp` |
| Remote group filter | `CN=4THealth-Admins,OU=Security Groups,DC=yourdomain,DC=com` |

Group 2 (viewer role):

| Field | Value |
|---|---|
| Name | `4THealth-Viewers` |
| Type | RADIUS |
| Remote servers | Select `AD-Corp` |
| Remote group filter | `CN=4THealth-Viewers,OU=Security Groups,DC=yourdomain,DC=com` |

#### FAC-1.4 Configure RADIUS policy to return a group attribute

**Authentication → RADIUS Service → Policies → Create New**

| Field | Value |
|---|---|
| Name | `4thealth-policy` |
| NAS client | `4thealth-prod` |
| Users/Groups | Add both `4THealth-Admins` and `4THealth-Viewers` |
| Authentication | Password-based |

Under **Reply Attributes**, add one entry per group:

| Group | Attribute | Value |
|---|---|---|
| `4THealth-Admins` | `Filter-Id` | `4THealth-Admins` |
| `4THealth-Viewers` | `Filter-Id` | `4THealth-Viewers` |

The `Filter-Id` string is what 4THealth reads to determine the role. The values here must match `RADIUS_GROUP_ADMIN` and `RADIUS_GROUP_VIEWER` in `.env`.

> **Deny all others:** In the same policy, set the default action to **Reject** so users who are not in either group cannot authenticate.

#### FAC-1.5 Test from the FAC CLI

```bash
# From FAC SSH console
diagnose radius-test auth <NAS-client-name> <username> <password>
```

A successful response shows `Access-Accept` with `Filter-Id = 4THealth-Admins` (or Viewers). If you see `Access-Reject`, check the AD group membership and the remote group filter DN.

### FAC-2 — Linux Server Configuration

#### FAC-2.1 Install the RADIUS client library

```bash
cd /opt/4thealth
sudo -u 4thealth uv add pyrad
```

This adds `pyrad` to `pyproject.toml` and updates `uv.lock`. Commit both files.

#### FAC-2.2 Add RADIUS variables to `.env`

```dotenv
RADIUS_ENABLED=true
RADIUS_HOST=<FortiAuthenticator IP>
RADIUS_PORT=1812
RADIUS_SECRET=<shared secret from FAC-1.1>
RADIUS_AUTH_METHOD=pap        # pap or chap — must match FAC client config
RADIUS_TIMEOUT=10             # seconds before falling back to local auth
RADIUS_GROUP_ADMIN=4THealth-Admins
RADIUS_GROUP_VIEWER=4THealth-Viewers
```

#### FAC-2.3 Add RADIUS support to `app/auth.py`

Replace `app/auth.py` with the following. Local bcrypt authentication remains intact as a fallback when `RADIUS_ENABLED=false` or when RADIUS is unreachable.

```python
"""User authentication.

Priority when RADIUS_ENABLED=true:
  1. RADIUS → FortiAuthenticator → Active Directory
  2. Local bcrypt (users.json) fallback for the emergency admin account

When RADIUS_ENABLED=false, only local bcrypt is used.
"""

import json
import os
import secrets
import socket
import string
from pathlib import Path

import bcrypt

USERS_FILE = Path(__file__).parent.parent / "users.json"


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with USERS_FILE.open() as f:
        return json.load(f)


# ── RADIUS ────────────────────────────────────────────────────────────────────

def _radius_authenticate(username: str, password: str) -> str | None:
    """Send a RADIUS Access-Request and return the Filter-Id value on success,
    or None on failure/timeout.

    Returns the Filter-Id string (e.g. '4THealth-Admins') so the caller can
    map it to an app role. Returns None for Access-Reject or any error.
    """
    try:
        from pyrad import packet, dictionary, client as pyrad_client
    except ImportError:
        return None

    host    = os.environ.get("RADIUS_HOST", "")
    port    = int(os.environ.get("RADIUS_PORT", "1812"))
    secret  = os.environ.get("RADIUS_SECRET", "").encode()
    method  = os.environ.get("RADIUS_AUTH_METHOD", "pap").lower()
    timeout = int(os.environ.get("RADIUS_TIMEOUT", "10"))

    if not host or not secret:
        return None

    try:
        d = dictionary.Dictionary()  # empty dictionary — we only need basic attrs
        srv = pyrad_client.Client(
            server=host,
            authport=port,
            secret=secret,
            dict=d,
        )
        srv.timeout = timeout
        srv.retries = 1

        req = srv.CreateAuthPacket(code=packet.AccessRequest, User_Name=username)

        if method == "chap":
            req["CHAP-Password"] = req.PwCrypt(password)
        else:
            req["User-Password"] = req.PwCrypt(password)

        reply = srv.SendPacket(req)

        if reply.code == packet.AccessAccept:
            # Filter-Id is attribute 11 — pyrad returns it as a list of bytes
            filter_ids = reply.get("Filter-Id", [])
            if filter_ids:
                val = filter_ids[0]
                return val.decode() if isinstance(val, bytes) else str(val)
            return ""   # accepted but no group attribute — treat as viewer

    except (socket.timeout, OSError):
        pass  # timeout or network error — fall through to local auth

    return None


def _radius_role(filter_id: str) -> str:
    """Map a RADIUS Filter-Id to an app role string."""
    admin_group  = os.environ.get("RADIUS_GROUP_ADMIN",  "4THealth-Admins")
    viewer_group = os.environ.get("RADIUS_GROUP_VIEWER", "4THealth-Viewers")
    if filter_id == admin_group:
        return "admin"
    if filter_id == viewer_group:
        return "viewer"
    return "viewer"   # unknown group — default to least privilege


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> bool:
    """Return True if credentials are valid via RADIUS or local bcrypt."""
    if os.environ.get("RADIUS_ENABLED", "false").lower() == "true":
        result = _radius_authenticate(username, password)
        if result is not None:
            return True
        # None means RADIUS rejected or timed out — fall through to local

    users = _load_users()
    entry = users.get(username)
    if not entry:
        return False
    stored_hash = entry.get("password_hash", "")
    return bcrypt.checkpw(password.encode(), stored_hash.encode())


def get_user_role(username: str) -> str:
    """Return the role for this user.

    For RADIUS-authenticated users the role comes from the Filter-Id attribute
    returned at login time. This function is called *after* authenticate(), so
    we re-query RADIUS only for the group mapping — not for re-authentication.
    The session stores the role, so in practice this is only called once per
    login. Local users fall back to users.json as before.
    """
    if os.environ.get("RADIUS_ENABLED", "false").lower() == "true":
        # Re-use the cached result if stored in a thread-local or re-derive
        # from users.json for local-fallback accounts.
        users = _load_users()
        if username not in users:
            # Pure RADIUS user — role was resolved during authenticate()
            # auth_routes.py must call _radius_role_for(username) instead.
            return "viewer"

    users = _load_users()
    return users.get(username, {}).get("role", "viewer")


def get_radius_role_for(username: str, password: str) -> str:
    """Authenticate via RADIUS and return the resolved role string.

    Called from auth_routes.py when RADIUS is enabled so the role is derived
    from the Filter-Id in the same round-trip as authentication.
    Returns 'viewer' on any failure.
    """
    filter_id = _radius_authenticate(username, password)
    if filter_id is None:
        return "viewer"
    return _radius_role(filter_id)


# ── Local-only helpers (unchanged) ───────────────────────────────────────────

def validate_password_policy(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if not any(c.islower() for c in password):
        raise ValueError("Password must include at least one lowercase letter")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must include at least one uppercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must include at least one number")
    if not any(c in string.punctuation for c in password):
        raise ValueError("Password must include at least one special character")


def add_user(username: str, password: str, role: str = "viewer") -> None:
    validate_password_policy(password)
    users = _load_users()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password_hash": hashed, "role": role}
    with USERS_FILE.open("w") as f:
        json.dump(users, f, indent=2)


def delete_user(username: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    del users[username]
    with USERS_FILE.open("w") as f:
        json.dump(users, f, indent=2)
    return True


def list_users() -> list:
    return [{"username": u, "role": v.get("role", "viewer")} for u, v in _load_users().items()]


def generate_secret_key() -> str:
    return secrets.token_hex(32)
```

#### FAC-2.4 Update `app/routes/auth_routes.py` to capture the RADIUS role

The login handler must call `get_radius_role_for()` when RADIUS is active so the correct role (admin vs viewer) is written into the session. Replace the login POST block:

```python
        if authenticate(username, password):
            _clear_failures(ip, username)
            session.permanent = True
            session["user"] = username

            # Derive role: RADIUS path returns it from Filter-Id; local path
            # reads it from users.json.
            import os
            if os.environ.get("RADIUS_ENABLED", "false").lower() == "true":
                from app.auth import get_radius_role_for
                role = get_radius_role_for(username, password)
            else:
                role = get_user_role(username)

            session["role"] = role
            allowed = list(get_allowed_tabs(username))
            session["allowed_tabs"] = allowed
            app_log("INFO", "auth", "Login successful", username=username, role=role)
            next_url = request.args.get("next", "").strip()
            if next_url and _safe_redirect(next_url):
                return redirect(next_url)
            return redirect(_first_allowed_url(allowed))
```

#### FAC-2.5 Handle RADIUS users in `app/groups.py`

RADIUS-authenticated users are not listed in `users.json`, so `get_allowed_tabs()` and `get_allowed_adoms()` need to handle them. The session role is already correct — add a session-aware path by passing the role in from the route layer, or use the simpler approach: add RADIUS users to the appropriate group in `groups.json` by their AD username.

**Recommended approach — add users to groups.json via the Admin UI:**

1. Log in as a local admin.
2. Go to **Admin → Groups & Permissions**.
3. Edit the group that matches their role (e.g. `NOC-Viewers`).
4. Add the AD `sAMAccountName` (e.g. `jsmith`) to the Members list.

When that user authenticates via RADIUS, `get_allowed_tabs("jsmith")` finds them in the group and returns the correct tab set. Their role (admin/viewer) comes from the RADIUS Filter-Id.

**Alternative — role-only approach (no per-user group membership):**

For environments where managing a members list is impractical, update `get_allowed_tabs()` in `app/groups.py` to fall back to role when no group membership is found:

```python
def get_allowed_tabs(username: str, role: str | None = None) -> set[str]:
    from app.auth import _load_users
    users = _load_users()
    user_entry = users.get(username, {})
    effective_role = role or user_entry.get("role", "viewer")

    if effective_role == "admin":
        return set(KNOWN_TABS.keys())

    with _lock:
        groups = _load()

    tabs: set[str] = set()
    for g in groups.values():
        if username in g.get("members", []):
            tabs.update(g.get("allowed_tabs", []))

    # RADIUS user not in any group — grant default viewer tabs by role
    if not tabs and effective_role == "viewer":
        viewer_group = groups.get("default-viewers", {})
        tabs.update(viewer_group.get("allowed_tabs", []))

    return tabs
```

Then pass `role=session["role"]` from `auth_routes.py` when calling `get_allowed_tabs()`.

#### FAC-2.6 Smoke test

```bash
# Verify FAC is reachable from the server (UDP 1812)
nc -zu <FAC-IP> 1812 && echo "RADIUS port reachable" || echo "BLOCKED"

# Test a full authentication round-trip with radtest (install from freeradius-utils)
sudo dnf install -y freeradius-utils   # or apt-get install freeradius-utils
radtest <ad-username> <password> <FAC-IP> 0 <shared-secret>
# Expected: Received Access-Accept

# Restart the app and attempt login in the browser
sudo systemctl restart 4thealth
sudo journalctl -u 4thealth -f
```

A successful login will log:
```
auth: Login successful  username=jsmith  role=admin
```

If the role is wrong (viewer instead of admin), the Filter-Id attribute is either not being returned by FAC or `RADIUS_GROUP_ADMIN` in `.env` does not exactly match the string FAC is sending. Use `radtest` output with `-x` for verbose RADIUS attribute dump.

### FAC-3 — Fallback and Recovery

| Scenario | Behaviour |
|---|---|
| FAC unreachable (timeout) | `_radius_authenticate()` returns `None`; app falls through to local `users.json` bcrypt auth |
| User not in any FAC group | FAC sends Access-Reject; app falls through to local auth |
| AD outage (FAC cannot reach DC) | FAC sends Access-Reject; fallback to local auth |
| `RADIUS_ENABLED=false` | RADIUS path skipped entirely; pure local bcrypt |

Keep the local `admin` account in `users.json` at all times. If FAC is unreachable, set `RADIUS_ENABLED=false` in `.env` and restart:

```bash
sudo systemctl restart 4thealth
```

### FAC-4 — Security Checklist

- [ ] RADIUS shared secret is at least 32 characters and stored only in `.env` (mode `640`)
- [ ] FAC RADIUS policy default action is **Reject** (users not in either group are denied)
- [ ] FAC client IP is locked to the 4THealth server IP — no wildcard `/0` subnet
- [ ] UDP port 1812 is open from the 4THealth server to FAC and closed from everywhere else
- [ ] `RADIUS_AUTH_METHOD` matches the FAC client config (both PAP, or both CHAP)
- [ ] Local `admin` account in `users.json` is retained as an emergency fallback
- [ ] `RADIUS_TIMEOUT` is set low enough (10s) that login failures are not excessively slow
- [ ] FAC is configured to log all authentication attempts for audit trail

---

## Quick Reference - Common Commands

```bash
# Start / stop / restart service
sudo systemctl start|stop|restart 4thealth

# View live application logs
sudo journalctl -u 4thealth -f

# View access log
sudo tail -f /var/log/4thealth/access.log

# Add a local user
cd /opt/4thealth && sudo -u 4thealth uv run python manage_users.py add <user> --role admin|viewer

# List local users
cd /opt/4thealth && sudo -u 4thealth uv run python manage_users.py list

# Generate a new SECRET_KEY
cd /opt/4thealth && sudo -u 4thealth uv run python manage_users.py secret

# Test LDAP connectivity
ldapsearch -x -H ldaps://your-dc:636 -D "<bind_dn>" -w "<pw>" -b "<base_dn>" "(sAMAccountName=<user>)" dn memberOf

# Check nginx config
sudo nginx -t

# Reload nginx without downtime
sudo nginx -s reload

# Check open ports
ss -tlnp | grep -E '443|80|8100'

# Check SELinux denials (RHEL/Rocky)
sudo ausearch -c gunicorn --ts recent
```

## Environment Variable Reference

- `SECRET_KEY`: Required. 64-char random hex. Rotate to log out all users.
- `COOKIE_SECURE`: `true` in production (HTTPS).
- `PORT`: Gunicorn internal port. Default `8100`.
- `SSL_CERT`: Path to TLS cert (direct Flask SSL).
- `SSL_KEY`: Path to TLS key.

- `FMG_PRIMARY_HOST`: FortiManager primary IP/hostname — used for ADOM, device, and policy queries.
- `FMG_API_TOKEN`: Bearer token (preferred, global). Generate on FMG: System Settings → Administrators → edit account → API token. Used for all devices that don't have their own `"token"` field in `infra_targets.json`.
- `FMG_USERNAME`: API account username (fallback when no token is set).
- `FMG_PASSWORD`: API account password (fallback when no token is set).
- `FMG_VERIFY_SSL`: `false` skips cert validation.

Per-device tokens (FortiAnalyzer, FortiCollector, etc. each generate their own tokens) are set via the optional `"token"` field in each `infra_targets.json` entry — token priority is: per-device token → `FMG_API_TOKEN` → username/password.
- `FMG_TIMEOUT`: API timeout seconds (default `30`).

Infrastructure dashboard cards are defined in `infra_targets.json` (not in `.env`).
Copy `infra_targets.example.json` to `infra_targets.json` and edit the host IPs.
Add or remove entries freely — no code changes required.

- `CPU_WARN` / `CPU_CRIT`: warning/critical CPU threshold percent.
- `MEM_WARN` / `MEM_CRIT`: warning/critical memory threshold percent.

- `SUMMARY_REFRESH_HOUR`: Hour (0–23, server local time) the nightly summary job fires. Default `1` (01:00).
- `SUMMARY_REFRESH_MINUTE`: Minute within the hour. Default `0`.

- `MAP_CACHE_INTERVAL_HOURS`: How often (in hours) device location data is re-fetched from FortiManager. Default `24`.
- `VERSIONS_CACHE_INTERVAL_MIN`: How often (in minutes) the Device Versions cache is refreshed. Default `30`.
- `FMG_SUPPRESS_INSECURE_WARNING`: Set to `false` to show urllib3 SSL warnings when `FMG_VERIFY_SSL=false`. Default `true` (suppressed).

- `AD_ENABLED`: `true` enables AD auth.
- `AD_SERVER`: LDAP server URL, preferably `ldaps://...:636`.
- `AD_DOMAIN`: NetBIOS domain.
- `AD_BASE_DN`: Directory base DN.
- `AD_BIND_USER`: Full DN of service account.
- `AD_BIND_PASSWORD`: Service account password.
- `AD_USER_SEARCH`: User search OU.
- `AD_GROUP_ADMIN`: Full DN of admin group.
- `AD_GROUP_VIEWER`: Full DN of viewer group.
- `AD_VERIFY_SSL`: Validate DC TLS certificate.

- `RADIUS_ENABLED`: `true` enables FortiAuthenticator RADIUS authentication (see FAC section).
- `RADIUS_HOST`: FortiAuthenticator IP or hostname.
- `RADIUS_PORT`: RADIUS auth port. Default `1812`.
- `RADIUS_SECRET`: Shared secret — must match the NAS client config on FAC.
- `RADIUS_AUTH_METHOD`: `pap` or `chap`. Default `pap`.
- `RADIUS_TIMEOUT`: Seconds before falling back to local auth. Default `10`.
- `RADIUS_GROUP_ADMIN`: Filter-Id string FAC returns for admin group. Default `4THealth-Admins`.
- `RADIUS_GROUP_VIEWER`: Filter-Id string FAC returns for viewer group. Default `4THealth-Viewers`.

## Continued Lifecycle

Goal: Automate testing and controlled production deployments from GitLab to your Linux server.

### Lifecycle Strategy

Use a two-stage approach:

1. Validate code in GitLab CI (`lint`, `tests`, optional security scan).
2. Deploy only from protected branches/tags to production with approval gates.

Recommended branch flow:

- Feature branches -> merge request -> `main`
- Auto-run CI on merge requests
- Deploy from:
    - `main` for continuous deployment, or
    - version tags (`v1.2.3`) for release-based deployment

### 8.1 GitLab Prerequisites

1. GitLab project configured with protected `main` branch.
2. Linux target server has:
     - Git
     - `uv`
     - systemd service (`4thealth.service`) already working
3. Dedicated deploy user on server (recommended: `4thealth` or `deploy`).
4. SSH access from GitLab runner to server.
5. GitLab CI/CD variables configured:
     - `SSH_PRIVATE_KEY` (masked, protected)
     - `DEPLOY_HOST` (example: `4thealth-prod.yourdomain.com`)
     - `DEPLOY_USER` (example: `deploy`)
     - `DEPLOY_PATH` (example: `/opt/4thealth`)
     - `DEPLOY_PORT` (optional, default 22)

### 8.2 Server Preparation for GitLab Deploys

Create a deploy user and grant only required permissions:

```bash
sudo useradd --system --create-home --shell /bin/bash deploy
sudo usermod -aG 4thealth deploy
```

Allow deploy user to restart only required services with sudo (least privilege):

```bash
sudo visudo -f /etc/sudoers.d/4thealth-deploy
```

Add:

```text
deploy ALL=(root) NOPASSWD:/bin/systemctl restart 4thealth,/bin/systemctl status 4thealth
```

Install GitLab runner public key into deploy user's authorized keys:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy chmod 700 /home/deploy/.ssh
sudo -u deploy nano /home/deploy/.ssh/authorized_keys
sudo -u deploy chmod 600 /home/deploy/.ssh/authorized_keys
```

Initialize app directory as a git checkout on server (one-time):

```bash
sudo mkdir -p /opt/4thealth
sudo chown -R 4thealth:4thealth /opt/4thealth
sudo -u 4thealth git clone <your-gitlab-repo-url> /opt/4thealth
```

### 8.3 Add GitLab CI Pipeline

Create `.gitlab-ci.yml` in repository root:

```yaml
stages:
    - test
    - deploy

default:
    image: python:3.12
    before_script:
        - python -V
        - pip install uv

variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
    paths:
        - .cache/pip

test:
    stage: test
    script:
        - uv sync --extra prod
        - uv run python -m compileall app manage_users.py wsgi.py
        # Add your real test command when available, e.g.:
        # - uv run pytest -q
    rules:
        - if: $CI_PIPELINE_SOURCE == "merge_request_event"
        - if: $CI_COMMIT_BRANCH == "main"

deploy_production:
    stage: deploy
    image: alpine:3.20
    before_script:
        - apk add --no-cache openssh-client bash
        - eval "$(ssh-agent -s)"
        - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
        - mkdir -p ~/.ssh
        - chmod 700 ~/.ssh
        - ssh-keyscan -p "${DEPLOY_PORT:-22}" "$DEPLOY_HOST" >> ~/.ssh/known_hosts
    script:
        - >
            ssh -p "${DEPLOY_PORT:-22}" "$DEPLOY_USER@$DEPLOY_HOST"
            "cd '$DEPLOY_PATH' &&
            git fetch --all &&
            git checkout main &&
            git reset --hard origin/main &&
            uv sync --extra prod &&
            sudo systemctl restart 4thealth &&
            sudo systemctl status 4thealth --no-pager"
    environment:
        name: production
    rules:
        - if: $CI_COMMIT_BRANCH == "main"
            when: manual
    allow_failure: false
```

Notes:

- Keep `deploy_production` as `manual` initially for safe rollout.
- After confidence, change to automatic on `main` or on signed tags.
- The deploy step uses `uv sync --extra prod` which writes the venv under `/opt/4thealth/.venv`. The systemd unit calls `gunicorn` directly from that venv path, so no `uv run` wrapper is needed at runtime.

### 8.4 What It Takes to Push Updates from GitLab to Linux Server

Minimum moving parts:

1. A GitLab runner that can execute the deploy job.
2. SSH private key in GitLab variables; matching public key on server.
3. Network path from runner to server (`22/tcp` open or custom SSH port).
4. Server checkout path with repository already cloned.
5. Controlled service restart permission (`sudoers` least privilege).

Deployment sequence per update:

1. Developer merges to `main` (or creates release tag).
2. GitLab runs test stage.
3. Deploy job connects over SSH.
4. Server pulls latest commit.
5. Server runs `uv sync --extra prod`.
6. Server restarts `4thealth`.
7. Job verifies service status and returns pass/fail.

### 8.5 Optional: Zero-Downtime and Safety Improvements

- Add pre-deploy backup of `.env` and `users.json`.
- Add health check gate after restart:

```bash
curl -sk https://4thealth.yourdomain.com/api/health
```

- Use GitLab Environments with required approvals for production.
- Restrict deploy job to protected branches and protected variables.
- Add rollback job:
    - Store previous commit hash before reset
    - Re-checkout previous hash on failure
    - Restart service and re-check health

### 8.6 Alternative Pattern: Pull-Based Auto-Update

If inbound SSH from GitLab runner is not allowed:

1. Keep CI for tests in GitLab.
2. On server, run a systemd timer every 5 minutes:
     - `git fetch`
     - compare local `HEAD` with `origin/main`
     - if changed, `uv sync --extra prod` and restart service
3. Log each run to journald for auditing.

This is less immediate than push-based deploys but often easier in restricted enterprise networks.
