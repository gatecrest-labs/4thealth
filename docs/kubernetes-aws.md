# Kubernetes on AWS (EKS) — 4THealth Deployment Guide

Read [docs/kubernetes-overview.md](kubernetes-overview.md) first — the single-replica rule,
persistent storage, secrets, and TLS design decisions explained there apply here without
repeating them. This doc covers only what's AWS-specific.

**Tools you'll install locally:** `aws` CLI v2, `eksctl`, `kubectl`, `docker`, `helm`.

---

## Phase 1 — Cluster bring-up

`eksctl` is the more teachable path for a first EKS cluster — one command/config file wires up
the VPC, subnets across multiple AZs (EKS requires the control plane to span ≥2 AZs even though
our node group will live in one), the cluster IAM role, the node IAM role, and the OIDC identity
provider (needed later for IRSA — IAM Roles for Service Accounts). Terraform
(`terraform-aws-modules/eks/aws`) is the better long-term choice if your org already standardizes
on Terraform elsewhere; treat that as an org-specific follow-up, not the first attempt.

**Node group type:** use a **managed node group**, not Fargate. Fargate pods cannot mount EBS
volumes (EFS only), and this app needs EBS-backed local disk for its JSON/SQLite files.

Per the overview doc's zone-pinning decision, pin the node group — and the NAT Gateway — to a
single AZ. `eksctl` supports this via a cluster config file rather than the one-line `eksctl
create cluster` command:

```yaml
# cluster.yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: 4thealth
  region: us-east-1
  version: "1.31"
vpc:
  nat:
    gateway: Single        # one NAT Gateway total, not one per AZ
secretsEncryption:
  keyARN: arn:aws:kms:us-east-1:ACCOUNT_ID:key/KEY_ID   # see Phase 4
managedNodeGroups:
  - name: ng-single-az
    instanceType: t3.medium
    desiredCapacity: 1
    minSize: 1
    maxSize: 1
    availabilityZones: ["us-east-1a"]   # pin to the same AZ as the NAT Gateway
iam:
  withOIDC: true           # required for IRSA (Load Balancer Controller, EBS CSI driver)
```

```bash
eksctl create cluster -f cluster.yaml
kubectl get nodes   # confirm the node is Ready
```

> Create the KMS key referenced above first: `aws kms create-key --description "4thealth EKS secrets"`.

---

## Phase 2 — kubectl access

```bash
aws eks update-kubeconfig --region us-east-1 --name 4thealth
kubectl get nodes
```

Whoever runs `eksctl create cluster` becomes the implicit cluster admin via an auto-created
**access entry**. For anyone else who needs access, grant it explicitly — don't edit the legacy
`aws-auth` ConfigMap on a new cluster; use access entries instead:

```bash
aws eks create-access-entry \
  --cluster-name 4thealth \
  --principal-arn arn:aws:iam::ACCOUNT_ID:user/alice

aws eks associate-access-policy \
  --cluster-name 4thealth \
  --principal-arn arn:aws:iam::ACCOUNT_ID:user/alice \
  --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminPolicy
```

> Your local `kubectl` version should stay within one minor version of the cluster's Kubernetes
> version — this is a real source of confusing errors if it drifts.

---

## Phase 3 — Networking: static IPs

### Inbound — static IP for the dashboard

**Gotcha: an Application Load Balancer (ALB) has no native static IP** — its IP addresses are
assigned per-AZ and can change. Don't reach for an ALB here. Use a **Network Load Balancer (NLB)
with an assigned Elastic IP** instead — this also happens to be the right choice because TLS
stays inside the container (see the overview doc): an NLB passes TCP through untouched, where an
ALB would terminate and re-encrypt.

First install the AWS Load Balancer Controller (needed to provision NLBs/ALBs from Kubernetes
Service/Ingress objects):

```bash
# One-time: IAM policy + IRSA service account for the controller
curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
aws iam create-policy --policy-name AWSLoadBalancerControllerIAMPolicy --policy-document file://iam-policy.json

eksctl create iamserviceaccount \
  --cluster 4thealth --namespace kube-system --name aws-load-balancer-controller \
  --attach-policy-arn arn:aws:iam::ACCOUNT_ID:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve

helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system --set clusterName=4thealth --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

Then allocate an Elastic IP and reference it on the Service:

```bash
aws ec2 allocate-address   # note the AllocationId, e.g. eipalloc-0123456789abcdef0
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: 4thealth
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    service.beta.kubernetes.io/aws-load-balancer-eip-allocations: "eipalloc-0123456789abcdef0"
spec:
  type: LoadBalancer
  selector: { app: 4thealth }
  ports:
    - port: 443
      targetPort: 8100
```

### Outbound — static egress IP for FortiManager/SMTP/RADIUS/SNMP allowlisting

The `cluster.yaml` in Phase 1 already set `vpc.nat.gateway: Single`, so `eksctl` provisioned
exactly one NAT Gateway (in the same AZ as the node group) instead of the default one-per-AZ.
Get its Elastic IP to hand to your network team for allowlisting:

```bash
aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=<VPC_ID>" \
  --query "NatGateways[].NatGatewayAddresses[].PublicIp"
```

That IP is the stable source address for all outbound traffic from the pod — FortiManager
JSON-RPC calls, SMTP relay connections, RADIUS requests, SNMP polling.

---

## Phase 4 — Secrets

Enable KMS envelope encryption for Secrets at cluster creation — already set in the
`cluster.yaml` above via `secretsEncryption.keyARN`. Then create the Secret from your `.env`:

```bash
kubectl create namespace 4thealth
kubectl create secret generic 4thealth-env --from-env-file=.env -n 4thealth
```

For a stronger posture once the team is comfortable with the basics: **External Secrets
Operator** pulling from AWS Secrets Manager keeps secret material out of manifests and `kubectl`
history entirely, and supports rotation. Not required to get started.

---

## Phase 5 — Container registry & image pipeline

```bash
aws ecr create-repository --repository-name 4thealth

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

docker build -t ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:$(git rev-parse --short HEAD) .
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:$(git rev-parse --short HEAD)
```

Use a real tag (git SHA or semver) in the Deployment manifest, never `:latest` — you need to be
able to roll back to a known image.

The managed node group's default IAM role already includes
`AmazonEC2ContainerRegistryReadOnly`, so no `imagePullSecrets` are needed.

---

## Phase 6 — Persistent storage

Install the EBS CSI driver as an EKS add-on (requires IRSA, same pattern as Phase 3):

```bash
eksctl create iamserviceaccount \
  --cluster 4thealth --namespace kube-system --name ebs-csi-controller-sa \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
  --approve

eksctl create addon --cluster 4thealth --name aws-ebs-csi-driver \
  --service-account-role-arn arn:aws:iam::ACCOUNT_ID:role/<role-created-above>
```

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
volumeBindingMode: WaitForFirstConsumer
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: 4thealth-data
  namespace: 4thealth
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: gp3
  resources:
    requests:
      storage: 5Gi
```

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
          image: ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:GIT_SHA
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
      nodeSelector:
        topology.kubernetes.io/zone: us-east-1a   # match the single-AZ node group
```

> `GET /api/health` is unauthenticated and has no FortiManager/SMTP/RADIUS dependency — see
> [docs/kubernetes-overview.md](kubernetes-overview.md#observability-how-do-you-know-a-nightly-job-didnt-silently-stop-running).

```bash
kubectl apply -f storageclass.yaml -f pvc.yaml -f deployment.yaml -f service.yaml
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
STATIC_IP=$(aws ec2 describe-addresses --allocation-ids eipalloc-0123456789abcdef0 --query 'Addresses[0].PublicIp' -o text)
curl -sk https://$STATIC_IP/login | grep -i 4thealth

kubectl logs -n 4thealth deploy/4thealth | grep -i scheduler
```

Confirm the egress IP with your network team by having them watch for a connection attempt from
the NAT Gateway's EIP (Phase 3) on the FortiManager/SMTP/RADIUS side.

---

## Updating the application

```bash
docker build -t ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:$(git rev-parse --short HEAD) .
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:$(git rev-parse --short HEAD)
kubectl set image deployment/4thealth 4thealth=ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/4thealth:$(git rev-parse --short HEAD) -n 4thealth
# strategy: Recreate means a short outage here — expected, see docs/kubernetes-overview.md
kubectl rollout status deployment/4thealth -n 4thealth
```

---

## Cost reference (us-east-1, approximate, 2026)

| Item | Approximate cost |
|---|---|
| EKS control plane | $0.10/hr (~$73/mo) |
| NAT Gateway | ~$0.045/hr (~$33/mo) + $0.045/GB processed |
| Network Load Balancer | ~$0.0225/hr (~$16/mo) + per-LCU usage |
| EBS gp3 (5 GiB) | ~$0.08/GB-mo (~$0.40/mo) |
| EC2 node (t3.medium, on-demand) | ~$30/mo |

Roughly **$150–180/mo** before data transfer, well above a single small VM — factor this in
before committing, and remember this is per-cluster, not per-app, if you later host other
workloads on the same cluster.

---

## Quick reference

```bash
kubectl get pods -n 4thealth
kubectl logs -f -n 4thealth deploy/4thealth
kubectl exec -it -n 4thealth deploy/4thealth -- python manage_users.py add <user> --role viewer
kubectl exec -it -n 4thealth deploy/4thealth -- python manage_users.py list
kubectl rollout restart deployment/4thealth -n 4thealth
```
