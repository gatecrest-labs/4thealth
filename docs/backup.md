# Backup and Restore Guide

Backups are managed through the 4THealth admin panel: **Admin → Backup**.

From there you can:
- Set the encryption password and backup directory
- Create a one-time backup (saved to the server and downloaded to your browser)
- Configure FTP/SFTP remote transfer
- Schedule recurring backups (daily, weekly, or custom day combinations)

Archives are AES-256 encrypted ZIPs named `SERVERNAME-BACKUP_YYYY-MM-DD_HHmm.zip`.
The last 20 archives are kept locally; older ones are pruned automatically.

> **Important:** The backup password is shown once on first save and never again.
> Store it in a separate secrets manager or offline vault.
> If lost, all existing backups become permanently unrecoverable.

**Encryption scope:** AES-256 encryption protects archives in transit and on the remote
FTP/SFTP server. It does not protect against a local server compromise — `backup_config.json`
(containing the password) lives on the same server as the archives.

---

## Pre-provisioning the backup directory (Linux)

The app user (`4thealth`) cannot create `/var/backups/4thealth/` automatically.
Run this once during initial setup (or add to `ExecStartPre` in the systemd unit):

```bash
sudo mkdir -p /var/backups/4thealth
sudo chown 4thealth:4thealth /var/backups/4thealth
sudo chmod 750 /var/backups/4thealth
```

---

## Restore on a New Server

These steps assume you have a backup archive from one of the procedures above.

### Step 0 — Decrypt the backup archive

The archive is an AES-256 encrypted ZIP. Decrypt it with 7-Zip (Windows/Linux GUI),
`unzip` with password, or `pyzipper`:

```bash
# Using pyzipper (Python)
python3 -c "
import pyzipper, sys
with pyzipper.AESZipFile(sys.argv[1]) as zf:
    zf.setpassword(input('Password: ').encode())
    zf.extractall('restore-out')
" 4thealth-backup-SERVERNAME-BACKUP_2026-08-10_0200.zip
```

Or with 7-Zip:
```bash
7z x SERVERNAME-BACKUP_2026-08-10_0200.zip -obackup-out
# Enter password when prompted
```

### Step 1 — Set up the new server (restore-out folder contents)

Follow the full deployment guide for your target platform:

- **Linux:** [deployment.md](deployment.md) through Phase 2.4 (stop before creating users — `users.json` will be restored from backup).
- **Docker:** [../container.md](../container.md) through the image pull / build step.

### Step 2 — Transfer the backup archive

```bash
# From the old server or a file share
scp /root/4thealth-backup-<date>.tar.gz user@new-server:/tmp/
```

### Step 3 — Restore files (Linux)

```bash
ARCHIVE="/tmp/4thealth-backup-<date>.tar.gz"

# Extract app-level files into /opt/4thealth
sudo tar -xzf "$ARCHIVE" \
  --strip-components=0 \
  -C /opt/4thealth \
  --exclude='etc'

# Restore systemd and nginx configs (paths are absolute inside the archive)
sudo tar -xzf "$ARCHIVE" \
  etc/systemd/system/4thealth.service \
  etc/nginx/conf.d/4thealth.conf \
  -C / 2>/dev/null || true

# Fix ownership
sudo chown -R 4thealth:4thealth /opt/4thealth
sudo chmod 600 /opt/4thealth/certs/key.pem
sudo chmod 600 /opt/4thealth/.env

# Reload and start
sudo systemctl daemon-reload
sudo systemctl enable 4thealth
sudo systemctl restart 4thealth
sudo nginx -t && sudo systemctl restart nginx
```

### Step 3 — Restore files (Docker)

```bash
APP_DIR="/opt/4thealth"   # wherever docker-compose.yml lives
ARCHIVE="/tmp/4thealth-backup-<date>.tar.gz"

# Extract everything into the app directory
tar -xzf "$ARCHIVE" -C "$APP_DIR"

# Fix permissions on secrets
chmod 600 "$APP_DIR/.env"
chmod 600 "$APP_DIR/certs/key.pem"

# Start the container
docker compose -f "$APP_DIR/docker-compose.yml" up -d
```

### Step 4 — Verify

```bash
# Linux
sudo systemctl status 4thealth
curl -sk https://localhost/login | grep -i 4thealth

# Docker
docker compose ps
curl -sk https://localhost:8100/login | grep -i 4thealth
```

Log in with an account from the restored `users.json` and confirm:

- The correct ADOMs appear in the ADOM selector
- Zone Policy tab loads data (confirms `policy_db.json` restored)
- Infrastructure tab shows devices (confirms `infra_targets.json` restored)
- Admin → Scheduled shows existing jobs (confirms `config_diff_jobs.json` / `device_review_jobs.json` restored)

---

## TLS Certificate Notes

| Cert type | Back up? | Notes |
|-----------|----------|-------|
| Self-signed (generated with `openssl req -x509`) | Yes | Back up both `cert.pem` and `key.pem` — cannot be reissued |
| Corporate / internal CA | Yes | The key cannot be re-exported; back up the key or re-request from your CA on restore |
| Let's Encrypt (`certbot`) | No | Skip — re-run `certbot` on the new server; cert auto-renews |

If you cannot recover a self-signed cert, generate a new one on the new server and re-add it to any browser trust stores or client systems that pinned the old cert:

```bash
sudo openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout /opt/4thealth/certs/key.pem \
  -out /opt/4thealth/certs/cert.pem \
  -days 3650 \
  -subj "/CN=4thealth.yourdomain.com" \
  -addext "subjectAltName=DNS:4thealth.yourdomain.com,IP:<new-server-ip>"
sudo chown 4thealth:4thealth /opt/4thealth/certs/*.pem
sudo chmod 600 /opt/4thealth/certs/key.pem
```
