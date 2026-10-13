# Kubernetes Deployment — Overview & Shared Patterns

This is the shared design doc for running 4THealth on Kubernetes. [docs/kubernetes-aws.md](kubernetes-aws.md)
and [docs/kubernetes-gcp.md](kubernetes-gcp.md) cover the cloud-specific commands; read this
file first — both cloud guides assume you've read it and reference it instead of repeating it.

## Why Kubernetes, and why not horizontal scaling

4THealth is a good fit for Kubernetes for the same reasons it's a good fit for Docker (see
[container.md](../container.md)): single process, no compiled native dependencies, no GPU. On
top of that, Kubernetes gives you automatic restart on crash, node-failure rescheduling, rolling
image updates, and a declarative config you can diff and review — real operational wins over a
bare VM or a single `docker compose up -d`.

**What Kubernetes does *not* give you here: horizontal scale-out.** The app starts roughly a
dozen in-process background schedulers at boot (`init_scheduler()` in `infra_health_cache.py`,
`adom_cache.py`, `backup_scheduler.py`, `pending_status_cache.py`, `config_diff_scheduler.py`,
`device_review_scheduler.py`, `map_cache.py`, `rule_hygiene_scheduler.py`,
`rule_policy_scheduler.py`), and reads/writes about fifteen local JSON files plus two SQLite
files directly on disk — the same way it does today on a single VM or container. None of that
code is designed for more than one live instance. This deployment is a **lift-and-shift of a
single-instance app**, not a redesign into a scale-out service. If you later need more than one
replica, that requires real code changes (moving scheduled jobs behind leader election or into a
separate single-instance worker, and replacing the local JSON files with a real datastore) — out
of scope for this guide.

## The single-replica rule — the most important thing in this doc

A Kubernetes `Deployment` with `replicas: 1` is **not** automatically single-instance in practice.
Its default `RollingUpdate` strategy (`maxSurge: 1`, `maxUnavailable: 0`) brings up a **second**
pod before terminating the old one on every image update or node drain. For a few seconds to a
few minutes, two live processes exist — two full sets of background schedulers, two SNMP polling
cycles, a nightly digest or scheduled PDF report possibly sent twice, and two processes writing
the same mounted JSON files with no cross-process locking.

You must pin the deployment strategy explicitly:

```yaml
spec:
  replicas: 1
  strategy:
    type: Recreate   # kill the old pod completely before starting the new one
```

`Recreate` means a short outage on every deploy (seconds to a couple of minutes while the new pod
starts and the scheduled jobs re-initialize) — that's the correct, deliberate trade for
correctness over availability here.

**Never add any of the following to this Deployment, for the same reason:**
- `HorizontalPodAutoscaler` (HPA)
- `VerticalPodAutoscaler` (VPA) in a mode that triggers pod replacement/eviction
- A `PodDisruptionBudget` with `minAvailable: 1` combined with voluntary multi-replica tooling

If a future requirement genuinely needs more than one replica, treat it as a new design — don't
quietly raise `replicas` on this Deployment.

## Persistent storage

One `PersistentVolumeClaim`, `accessModes: [ReadWriteOnce]`, mounted into the pod with a
`subPath` per file — this mirrors today's Docker Compose bind-mount list
(`docker-compose.yml`, `container.md`) file-for-file, so no application code changes are needed.

The authoritative list of runtime files is the project's `.gitignore` (these are exactly the
files that must survive a pod restart):

| Path | Purpose |
|---|---|
| `certs/` | TLS cert + key (or mount via a `Secret` of type `kubernetes.io/tls` instead — see TLS below) |
| `users.json` | Local accounts (bcrypt hashes) |
| `groups.json` | Group tab/ADOM permissions |
| `infra_targets.json` | Infrastructure dashboard targets |
| `policy_db.json` | Zone Policy database |
| `app_settings.json` | Feature flags |
| `api_tokens.json` | External API bearer token hashes |
| `summary_history.json` | Nightly summary job history |
| `smtp_config.json` | SMTP relay config |
| `config_diff_jobs.json` | Config-Delta scheduled jobs |
| `device_review_jobs.json` | Audit Review scheduled jobs |
| `rule_hygiene_jobs.json` | Rule Hygiene scheduled jobs |
| `rule_policy_jobs.json` | Rule Policy scheduled jobs |
| `package_change_alerts.json` | Package Change Alert rules + dedupe state |
| `backup_config.json` | Backup password + FTP/SFTP config + run history |
| `protocol_severity.json` | Audit Review protocol severity overrides (optional) |
| `host_metrics.db`, `login_events.db` (+ `-wal`/`-shm`) | SQLite metrics stores |

> **Note:** `docker-compose.yml` as currently written only bind-mounts a subset of this list.
> Carrying the full list into the K8s manifest is a good opportunity to close that gap, but it's
> a pre-existing Compose issue, not something this guide needs to fix.

**Zone/AZ pinning:** both AWS (EBS) and GCP (Persistent Disk) volumes are zone-bound — a pod can
only be scheduled onto a node in the same zone as its attached volume. Combined with the static
egress IP requirement below (which is cheapest and simplest as a single NAT endpoint in one
zone), this guide deliberately pins the node pool to a single zone rather than spreading across
zones for HA. You lose cross-zone failover; you gain a deterministic egress IP and a PVC that
always has somewhere to attach. For a non-scaled internal tool, that's the right trade. Each
cloud doc shows exactly how to pin it.

**Backup:** your existing backup approach ([docs/backup.md](backup.md)) still applies — it just
needs to run against the PVC-backed files instead of host files. The simplest options are
`kubectl cp` to copy files out of the running pod on a schedule, or a `CronJob` in the same
namespace that mounts the same PVC read-only and runs the copy/archive step.

## Secrets baseline

Create a native Kubernetes `Secret` from your existing `.env` file — this is close to a drop-in
replacement:

```bash
kubectl create secret generic 4thealth-env --from-env-file=.env -n 4thealth
```

Reference it in the pod spec with `envFrom`, instead of relying on `python-dotenv` loading a
mounted `.env` file:

```yaml
envFrom:
  - secretRef:
      name: 4thealth-env
```

No code change is required for this: `load_dotenv()` in `wsgi.py` and `app/config.py` silently
does nothing when no `.env` file is present, and `Config` reads everything from
`os.environ` either way.

**This is a security *downgrade* from today's gitignored, bind-mounted `.env` unless you also
enable encryption at rest for Secrets** (K8s Secrets are base64-encoded, not encrypted, by
default). Both cloud docs show the one-line cluster-creation flag to enable KMS/CMEK envelope
encryption for Secrets — treat that as required, not optional, given this app's real secrets
(`FMG_API_TOKEN`, `RADIUS_SECRET`, `AD_BIND_PASSWORD`, SNMP auth/priv keys).

Once your team is comfortable with the basics, the natural "level 2" upgrade is a managed secret
store (AWS Secrets Manager + External Secrets Operator, or GCP Secret Manager + the Secret
Manager CSI driver + Workload Identity) so secret material never sits in a manifest, `kubectl`
history, or CI logs in the first place. Each cloud doc has a short pointer to this; it's not
required to get started.

## TLS

Keep TLS termination inside the container exactly as it works today — gunicorn's
`--certfile`/`--keyfile` flags, same cert files, same `SSL_CERT`/`SSL_KEY` env vars. No app code
or `Dockerfile` change. Front the pod with an L4/passthrough load balancer (not an L7 load
balancer that would terminate and re-encrypt) so the TLS handshake still happens inside gunicorn.
If you later want CDN/WAF/URL-based routing, that's a legitimate reason to move TLS termination
to the load balancer — it's not needed for this initial migration.

## Static IP: inbound vs. outbound are two different problems

- **Inbound** — browser users need a stable IP or DNS name to reach the dashboard reliably.
- **Outbound/egress** — FortiManager, your SMTP relay, RADIUS server, and SNMP-polled devices
  allowlist traffic by source IP on their side. If the pod's outbound IP changes, those
  integrations silently break.

**These two concerns use different mechanisms on both clouds, and the mechanisms are not
symmetric between AWS and GCP** — AWS's load balancer story in particular has a real gotcha (an
ALB has no native static IP). Don't assume one cloud's approach maps directly onto the other;
each cloud doc covers its own mechanics in full, rather than forcing an artificial 1:1 mirror.

## Cost — order of magnitude

Both clouds charge separately for: the control plane itself, the load balancer, the NAT
gateway/Cloud NAT (often more than compute for a low-traffic app, due to per-GB processing
charges), and the persistent disk. None of this is free the way "just add a VM" might feel. Each
cloud doc gives concrete current numbers — read that section before you provision anything, so
the first time you see these costs is in planning, not on a bill.

## Observability: how do you know a nightly job didn't silently stop running?

On a VM, "is it running" is a simple question — check the process. In Kubernetes, a liveness
probe failure, an OOMKill, or a `CrashLoopBackOff` restarts the pod and it looks "Running" again
within seconds, which can hide the fact that a scheduled digest or SNMP poll cycle was killed
mid-flight.

Two concrete steps:

1. **Use `GET /api/health`** (`app/routes/api_routes.py`) as the liveness/readiness probe target
   instead of `/login` — it returns `{"status": "ok"}`, requires no auth, and has no
   FortiManager/SMTP/RADIUS dependency, so a probe failure actually means the process is unhealthy
   rather than a downstream integration being slow. Both cloud docs' manifests already point at it.
2. **Alert on the absence of expected log lines**, not just on errors. The background jobs log
   their own start/completion (e.g. `map_cache: scheduler started`, `map_cache: done in 18.4s —
   846 devices`). Ship container stdout/stderr to CloudWatch Logs (AWS) or Cloud Logging (GCP)
   and set up a log-based alert that fires when an expected "done" line hasn't appeared within
   its scheduled window — this catches a silently-killed job that a liveness probe would hide.

## Rollback and parallel-run plan

Don't decommission the existing Ansible/systemd or Docker Compose deployment the day Kubernetes
goes live. Keep it available as a fallback — DNS cutover is cheap to reverse, a stuck PV or a
botched cluster upgrade during your first few weeks on K8s is not something you want to debug
under pressure with no working fallback. A reasonable default: run the K8s deployment as the
primary for several weeks of real production use before retiring the old path.

## What changes in the application

**No required code changes.** The existing environment-variable-driven config, local JSON/SQLite
file I/O, and single-process background-scheduler model all map directly onto this design,
provided the Deployment enforces `strategy: Recreate` and nothing introduces a second replica.

The one enhancement worth making for this migration — a dedicated `GET /api/health` endpoint
decoupled from FortiManager/session state, for use as the K8s probe target — has been added
(`app/routes/api_routes.py`); see Observability above.

## Initial access checklist (generic — cloud-specific commands in each cloud doc)

1. Get `kubectl` access to the cluster (cloud-specific — see Phase 2 of your cloud's doc).
2. Create a namespace: `kubectl create namespace 4thealth`.
3. Generate `SECRET_KEY` and fill in your real `.env` locally, exactly as you would for a Docker
   or VM install (`python manage_users.py secret`).
4. Create the `Secret` from that `.env` file (see Secrets baseline above) — this must happen
   **before** the first pod starts, since `Config._require_secret_key()` raises at import time if
   `SECRET_KEY` is missing.
5. Create the `PersistentVolumeClaim`.
6. Seed the PVC with starter data: with the PVC mounted into a running (even if not-yet-healthy)
   pod, use `kubectl cp` to copy your local `*.example.json` files (renamed, e.g.
   `groups.example.json` → `groups.json`) into the pod's mounted paths — the same files and the
   same rename-from-example pattern as `container.md` Step 5, just via `kubectl cp` instead of a
   host bind mount.
7. Apply the `Deployment` and `Service` (+ `Ingress` if you added one later).
8. `kubectl exec` into the pod to create the first admin account, exactly as in `container.md`
   Step 7: `kubectl exec -it deploy/4thealth -- python manage_users.py add admin --role admin`.
9. Verify: hit the static IP/DNS name in a browser, check `kubectl logs` for the scheduler
   startup lines, confirm the egress IP by having the network/firewall team watch for the
   expected source IP on an allowlisted connection attempt.
