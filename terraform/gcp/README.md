# Terraform — GCP (GKE)

Provisions the GCP infrastructure described in [docs/kubernetes-gcp.md](../../docs/kubernetes-gcp.md):
a private-nodes VPC, a GKE Autopilot cluster with KMS-encrypted Secrets, a Cloud NAT with a
reserved static egress IP, a reserved internal IP for the dashboard load balancer, and an
Artifact Registry repository. See [terraform/README.md](../README.md) for what this does *not*
cover (Kubernetes manifests).

## Files

| File | What it defines |
|---|---|
| `versions.tf` | Terraform + Google provider version constraints |
| `variables.tf` | Every input you can override — see below |
| `network.tf` | VPC, subnet with Pod/Service secondary ranges, Cloud NAT, reserved egress + ingress IPs |
| `kms.tf` | KMS key ring/key for GKE Secrets encryption, IAM binding for the GKE service agent |
| `gke.tf` | GKE Autopilot cluster, private nodes |
| `artifact_registry.tf` | Artifact Registry repository for the app image |
| `public_access.tf` | Optional static external IP for temporary test access (off by default) |
| `outputs.tf` | Values you'll need for the next steps (egress IP, ingress IP, kubectl config command) |
| `terraform.tfvars.example` | Template for your own `terraform.tfvars` |
| `k8s/` | Kubernetes manifests for the app (namespace, PVC, Deployment, Service) |

## Modify for your own environment

1. **Copy the tfvars template:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Edit `terraform.tfvars`** — at minimum, change:
   - `project_id` — **required, no default.** Your GCP project ID (`gcloud config get-value project`).
   - `region` — your preferred region; `us-central1` is just an example.
   - `cluster_name` — if you're running more than one environment (e.g. `fourthealth-dev`).
   - `subnet_cidr`, `pods_cidr`, `services_cidr`, `master_cidr` — change any of these if they
     overlap with an existing VPC you'll connect this one to (Cloud VPN/Interconnect, matching the
     internal-only dashboard access model). The defaults are arbitrary private ranges with no
     special meaning.

3. **Authenticate the Google provider:**
   ```bash
   gcloud auth application-default login
   ```

4. **Enable the required APIs** (one-time per project):
   ```bash
   gcloud services enable container.googleapis.com compute.googleapis.com \
     artifactregistry.googleapis.com cloudkms.googleapis.com
   ```

5. **Run it:**
   ```bash
   terraform init
   terraform plan   # review before applying — this creates billed resources
   terraform apply
   ```

6. **Continue with `docs/kubernetes-gcp.md` Phase 2 onward** — `terraform output configure_kubectl`
   gives you the exact `gcloud container clusters get-credentials` command.
   `terraform output ingress_internal_ip` gives you the IP to put in the Service manifest's
   `loadBalancerIP` field from Phase 3, and `terraform output nat_egress_ip` is the address to hand
   your network team for FortiManager/SMTP/RADIUS/SNMP allowlisting.

## Testing without a VPN

Nodes are private and the ingress IP is an internal load balancer, so the app isn't reachable from
the Internet. The Kubernetes API endpoint *is* public (authenticated with your Google login), so you
can test from your own machine with `kubectl port-forward`:

1. **Install kubectl and the auth plugin** (one-time):
   ```bash
   gcloud components install kubectl gke-gcloud-auth-plugin
   ```

2. **Push an image** to the Artifact Registry repo. On Apple Silicon, build for `linux/amd64` or the
   pod will fail with `exec format error`:
   ```bash
   gcloud auth configure-docker us-central1-docker.pkg.dev
   docker build --platform linux/amd64 -t $(terraform output -raw artifact_registry_repo)/app:test .
   docker push $(terraform output -raw artifact_registry_repo)/app:test
   ```

3. **Fetch cluster credentials:**
   ```bash
   $(terraform output -raw configure_kubectl)
   ```

4. **Deploy your manifests, then forward a local port to the Service:**
   ```bash
   kubectl port-forward svc/<service-name> 8080:80
   ```
   Browse to `http://localhost:8080`. Nothing is exposed publicly.

There are no default cluster credentials. Access is via IAM: the account that ran `terraform apply`
(a project Owner) is cluster admin. Grant others `roles/container.admin` or
`roles/container.developer`.

### Temporary public HTTPS test access

To test login and the UI from a browser without port-forward, expose the app on a static external
IP, locked to your own public IP. Off by default; there is no GUI VM, your Mac's browser is the client.

1. **Enable it** in `terraform.tfvars` (get your IP with `curl -s ifconfig.me`; `0.0.0.0/0` is rejected):
   ```hcl
   enable_public_access = true
   public_access_cidrs  = ["203.0.113.7/32"]
   ```
   then `terraform apply`. This reserves the static IP (`terraform output public_test_ip`).
2. **Create the Service** from the rendered manifest. It is named `fourthealth-public`, so it
   coexists with the ClusterIP Service:
   ```bash
   terraform output -raw public_lb_manifest | kubectl apply -f -
   kubectl get svc -n 4thealth fourthealth-public -w   # wait for EXTERNAL-IP
   ```
3. **Browse** to `https://<public_test_ip>`. TLS passes through to the app, so you get its
   self-signed certificate warning; accept it and log in.
4. **Turn it off** when done, in this order (so the IP isn't released while in use):
   ```bash
   kubectl delete svc -n 4thealth fourthealth-public
   ```
   then set `enable_public_access = false` and `terraform apply`.

Only the listed CIDRs can connect, but the login page is still on the internet while this is on, so
keep it short-lived and use a strong admin password. No FortiManager is involved: expect pages that
need FMG data to be empty or show connection errors.

## Moving to remote state

Local state (`terraform.tfstate` on your machine) is fine solo. Once a second person touches this
cluster, add a GCS backend before anyone runs `apply` again:

```hcl
# backend.tf — create this file yourself; the bucket must already exist
terraform {
  backend "gcs" {
    bucket = "your-terraform-state-bucket"
    prefix = "4thealth/gcp"
  }
}
```

Then run `terraform init -migrate-state`.

## Tearing down

The `google_kms_crypto_key` has `prevent_destroy = true` set deliberately — Google doesn't let you
delete KMS key rings or keys anyway (only schedule key *versions* for destruction).

**A plain `terraform destroy` fails.** Terraform aborts the whole destroy with
`Instance cannot be destroyed` *before deleting anything*, so the cluster keeps running and billing.
Remove the KMS resources from state first (this doesn't touch GCP), then destroy:

```bash
terraform state rm google_kms_crypto_key_iam_member.gke_sa_encrypt_decrypt \
  google_kms_crypto_key.gke_secrets google_kms_key_ring.gke
terraform destroy
```

This removes the cluster, VPC, Cloud NAT, reserved IPs and Artifact Registry. The cluster takes
about 5 minutes to delete. Afterwards, confirm nothing is left running:

```bash
gcloud container clusters list
gcloud compute addresses list
gcloud compute routers list
```

The key ring and key remain in GCP (free). They are no longer in Terraform state.

### Rebuilding after a teardown

Because the key ring and key still exist, `terraform apply` fails with "already exists" until you
import them. Run this before the first `apply` (adjust the project, region, and `cluster_name`):

```bash
terraform import google_kms_key_ring.gke \
  projects/PROJECT_ID/locations/us-central1/keyRings/CLUSTER_NAME-keyring
terraform import google_kms_crypto_key.gke_secrets \
  projects/PROJECT_ID/locations/us-central1/keyRings/CLUSTER_NAME-keyring/cryptoKeys/gke-secrets
```

Alternatively, set a different `cluster_name` so a new key ring is created.

### Other gotchas learned the hard way

- **Names must start with a letter.** GCP rejects `cluster_name` values such as `4thealth`.
- **Capacity errors.** `Google Compute Engine does not have enough resources` on cluster creation is
  a temporary regional shortage. Wait a few minutes and re-run `terraform apply`.
