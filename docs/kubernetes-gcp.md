# Kubernetes on GCP (GKE) — 4THealth Deployment Guide

Read [docs/kubernetes-overview.md](kubernetes-overview.md) first — the single-replica rule,
persistent storage, secrets, and TLS design decisions explained there apply here without
repeating them. This doc covers only what's GCP-specific.

**Tools you'll install locally:** `gcloud` CLI, `kubectl`, the `gke-gcloud-auth-plugin`, `docker`.

---

## Phase 1 — Cluster bring-up

```bash
gcloud components install gke-gcloud-auth-plugin
```

**Autopilot vs Standard:** use **Autopilot**. It removes node management, OS patching, and
node-pool sizing — you pay per pod resource request rather than per provisioned node, which fits
one small single-replica container well. It supports the built-in Persistent Disk CSI driver,
which is all this app needs. Standard mode only earns its extra operational burden if you later
need custom DaemonSets or specific machine shapes — not the case here.

Use **private nodes** — this is both the better security posture and a requirement for the
static-egress-IP setup in Phase 3 (public nodes get their own ephemeral egress IPs,
undermining the whole point):

```bash
gcloud container clusters create-auto 4thealth \
  --region us-central1 \
  --enable-private-nodes \
  --database-encryption-key projects/PROJECT_ID/locations/us-central1/keyRings/4thealth/cryptoKeys/gke-secrets
```

> Create the KMS key referenced above first:
> `gcloud kms keyrings create 4thealth --location us-central1`
> `gcloud kms keys create gke-secrets --keyring 4thealth --location us-central1 --purpose encryption`
> This enables application-layer secrets encryption — see Phase 4.

> **Zone-pinning caveat:** Autopilot does not let you pin node placement to a single zone the
> way a Standard node pool does. Your pod's zone (and therefore which zone its PersistentVolume
> must be in) is chosen by GKE at schedule time. Two options, per
> [docs/kubernetes-overview.md](kubernetes-overview.md#persistent-storage): accept the small risk
> that a reschedule lands in a different zone than the existing PD (rare, but would leave the pod
> `Pending` until it's rescheduled back), or use a **Regional Persistent Disk**
> (`replication-type: regional-pd`) which is synchronously replicated across two zones at extra
> cost. For a first deployment, accepting the risk is reasonable; revisit if you see it happen.

---

## Phase 2 — kubectl access

```bash
gcloud container clusters get-credentials 4thealth --region us-central1 --project PROJECT_ID
kubectl get nodes
```

Minimal IAM role for day-to-day kubectl work: `roles/container.developer`. Cluster-admin actions
need `roles/container.admin`; read-only access needs `roles/container.clusterViewer`.

> **Naming collision to be aware of:** "Workload Identity" refers to two unrelated things — (a)
> GKE Workload Identity, which lets a *pod* authenticate to GCP APIs without a downloaded service
> account key (used in Phase 4 for Secret Manager), and (b) Workload Identity Federation, which
> lets *external* systems (your laptop, CI) authenticate to `gcloud` without a downloaded key.
> They solve different problems; don't conflate them when reading GCP docs.

---

## Phase 3 — Networking: static IPs

### Inbound — static IP for the dashboard

The dashboard is internal-only — not exposed to the internet. Use an **internal passthrough
Network Load Balancer** — a plain `Service` of type `LoadBalancer` with a reserved internal IP,
reachable only from within the VPC (via Cloud VPN or Cloud Interconnect from your corporate
network). TLS stays inside the container (see the overview doc), so L4 passthrough is correct here.

Reserve an internal (private) IP in the cluster's subnet:

```bash
gcloud compute addresses create 4thealth-ingress \
  --region us-central1 \
  --subnet default
gcloud compute addresses describe 4thealth-ingress --region us-central1 --format='get(address)'
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: 4thealth
  annotations:
    networking.gke.io/load-balancer-type: "Internal"
spec:
  type: LoadBalancer
  loadBalancerIP: "STATIC_IP_FROM_ABOVE"
  selector: { app: 4thealth }
  ports:
    - port: 443
      targetPort: 8100
```

### Outbound — static egress IP for FortiManager/SMTP/RADIUS/SNMP allowlisting

Reserve a static IP and attach it to a Cloud NAT gateway on the cluster's region/subnet. Because
the cluster uses private nodes (Phase 1), **all** outbound pod traffic transits Cloud NAT —
giving you one controllable, stable egress IP:

```bash
gcloud compute addresses create 4thealth-egress --region us-central1

gcloud compute routers create 4thealth-router --region us-central1 --network default

gcloud compute routers nats create 4thealth-nat \
  --router 4thealth-router --region us-central1 \
  --nat-external-ip-pool 4thealth-egress \
  --nat-all-subnet-ip-ranges
```

Hand `4thealth-egress`'s IP to your network team for allowlisting on FortiManager, SMTP, RADIUS,
and SNMP targets.

---

## Phase 4 — Secrets

KMS-backed secrets encryption was already enabled at cluster creation in Phase 1
(`--database-encryption-key`). Create the Secret from your `.env`:

```bash
kubectl create namespace 4thealth
kubectl create secret generic 4thealth-env --from-env-file=.env -n 4thealth
```

For a stronger posture once the team is comfortable with the basics: **GCP Secret Manager +
the Secret Manager CSI driver**, combined with **GKE Workload Identity** (binding the pod's
Kubernetes ServiceAccount to a GCP IAM service account with `roles/secretmanager.secretAccessor`,
no downloaded key file) — gives rotation and audit logging. Not required to get started.

---

## Phase 5 — Artifact Registry & image pipeline

Container Registry (`gcr.io`) is deprecated — use Artifact Registry:

```bash
gcloud artifacts repositories create 4thealth --repository-format=docker --location=us-central1
gcloud auth configure-docker us-central1-docker.pkg.dev

docker build -t us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:$(git rev-parse --short HEAD) .
docker push us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:$(git rev-parse --short HEAD)
```

Grant the node's (or Workload Identity) service account `roles/artifactregistry.reader`. Use a
real tag (git SHA), never `:latest`.

---

## Phase 6 — Persistent storage

The Persistent Disk CSI driver is enabled by default on new GKE clusters.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: 4thealth-data
  namespace: 4thealth
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: standard-rwo   # or premium-rwo for SSD; see note below for regional-pd
  resources:
    requests:
      storage: 5Gi
```

If you decided to accept the regional-PD cost from Phase 1's zone-pinning caveat, set
`storageClassName` to a StorageClass with `replication-type: regional-pd` instead.

---

## Phase 7 — Deploy the app

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: 4thealth
  namespace: 4thealth
spec:
  replicas: 1
  strategy:
    type: Recreate            # see docs/kubernetes-overview.md — do not change
  selector:
    matchLabels: { app: 4thealth }
  template:
    metadata:
      labels: { app: 4thealth }
    spec:
      containers:
        - name: 4thealth
          image: us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:GIT_SHA
          ports: [{ containerPort: 8100 }]
          envFrom:
            - secretRef: { name: 4thealth-env }
          volumeMounts:
            - { name: data, mountPath: /app/certs, subPath: certs }
            - { name: data, mountPath: /app/users.json, subPath: users.json }
            - { name: data, mountPath: /app/groups.json, subPath: groups.json }
            - { name: data, mountPath: /app/infra_targets.json, subPath: infra_targets.json }
            - { name: data, mountPath: /app/policy_db.json, subPath: policy_db.json }
            - { name: data, mountPath: /app/app_settings.json, subPath: app_settings.json }
            - { name: data, mountPath: /app/api_tokens.json, subPath: api_tokens.json }
            - { name: data, mountPath: /app/summary_history.json, subPath: summary_history.json }
            - { name: data, mountPath: /app/smtp_config.json, subPath: smtp_config.json }
            - { name: data, mountPath: /app/config_diff_jobs.json, subPath: config_diff_jobs.json }
            - { name: data, mountPath: /app/device_review_jobs.json, subPath: device_review_jobs.json }
            - { name: data, mountPath: /app/rule_hygiene_jobs.json, subPath: rule_hygiene_jobs.json }
            - { name: data, mountPath: /app/rule_policy_jobs.json, subPath: rule_policy_jobs.json }
            - { name: data, mountPath: /app/package_change_alerts.json, subPath: package_change_alerts.json }
            - { name: data, mountPath: /app/backup_config.json, subPath: backup_config.json }
          readinessProbe:
            httpGet: { path: /api/health, port: 8100, scheme: HTTPS }
            initialDelaySeconds: 10
          livenessProbe:
            httpGet: { path: /api/health, port: 8100, scheme: HTTPS }
            initialDelaySeconds: 15
            periodSeconds: 30
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: 4thealth-data }
```

> `GET /api/health` is unauthenticated and has no FortiManager/SMTP/RADIUS dependency — see
> [docs/kubernetes-overview.md](kubernetes-overview.md#observability-how-do-you-know-a-nightly-job-didnt-silently-stop-running).

```bash
kubectl apply -f pvc.yaml -f deployment.yaml -f service.yaml
```

---

## Phase 8 — Seed data and create the first admin user

```bash
POD=$(kubectl get pod -n 4thealth -l app=4thealth -o jsonpath='{.items[0].metadata.name}')

# Copy renamed example files in (same pattern as container.md Step 5, via kubectl cp)
kubectl cp groups.example.json 4thealth/$POD:/app/groups.json
kubectl cp infra_targets.example.json 4thealth/$POD:/app/infra_targets.json
kubectl cp policy_db.example.json 4thealth/$POD:/app/policy_db.json
mkdir -p certs && openssl req -x509 -newkey rsa:4096 -nodes -keyout certs/key.pem -out certs/cert.pem -days 3650 -subj "/CN=4thealth.yourdomain.com"
kubectl cp certs 4thealth/$POD:/app/certs

# Create the first admin account
kubectl exec -it -n 4thealth $POD -- python manage_users.py add admin --role admin
```

---

## Phase 9 — Verify

```bash
# Run from inside the VPC (Cloud VPN connected):
STATIC_IP=$(gcloud compute addresses describe 4thealth-ingress --region us-central1 --format='get(address)')
curl -sk https://$STATIC_IP/login | grep -i 4thealth

kubectl logs -n 4thealth deploy/4thealth | grep -i scheduler
```

Confirm the egress IP with your network team by having them watch for a connection attempt from
the `4thealth-egress` IP (Phase 3) on the FortiManager/SMTP/RADIUS side.

---

## Updating the application

```bash
docker build -t us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:$(git rev-parse --short HEAD) .
docker push us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:$(git rev-parse --short HEAD)
kubectl set image deployment/4thealth 4thealth=us-central1-docker.pkg.dev/PROJECT_ID/4thealth/app:$(git rev-parse --short HEAD) -n 4thealth
# strategy: Recreate means a short outage here — expected, see docs/kubernetes-overview.md
kubectl rollout status deployment/4thealth -n 4thealth
```

---

## Cost reference (us-central1, approximate, 2026)

| Item | Approximate cost |
|---|---|
| GKE cluster management fee | $0.10/hr (~$73/mo) beyond one free zonal cluster/billing account |
| Autopilot pod resource (small single pod, e.g. 0.5 vCPU/1 GiB) | ~$15–25/mo |
| Cloud NAT | ~$0.045/hr (~$33/mo) + $0.045/GB processed |
| Regional external passthrough Network LB | ~$0.025/hr (~$18/mo) + per-GB |
| Persistent Disk (5 GiB, standard-rwo) | ~$0.04/GB-mo (~$0.20/mo); roughly double for regional PD |

Roughly **$140–150/mo** before data transfer — confirm current pricing before committing, and
note the free-tier zonal cluster only applies to Standard mode in most billing setups, not
Autopilot.

---

## Quick reference

```bash
kubectl get pods -n 4thealth
kubectl logs -f -n 4thealth deploy/4thealth
kubectl exec -it -n 4thealth deploy/4thealth -- python manage_users.py add <user> --role viewer
kubectl exec -it -n 4thealth deploy/4thealth -- python manage_users.py list
kubectl rollout restart deployment/4thealth -n 4thealth
```
