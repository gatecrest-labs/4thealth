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
| `outputs.tf` | Values you'll need for the next steps (egress IP, ingress IP, kubectl config command) |
| `terraform.tfvars.example` | Template for your own `terraform.tfvars` |

## Modify for your own environment

1. **Copy the tfvars template:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Edit `terraform.tfvars`** — at minimum, change:
   - `project_id` — **required, no default.** Your GCP project ID (`gcloud config get-value project`).
   - `region` — your preferred region; `us-central1` is just an example.
   - `cluster_name` — if you're running more than one environment (e.g. `4thealth-dev`).
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

```bash
terraform destroy
```

The `google_kms_crypto_key` has `prevent_destroy = true` set deliberately — Google doesn't let you
delete KMS key material anyway (only schedule key *versions* for destruction), so Terraform will
refuse to remove the key resource itself even on `destroy`. Everything else (cluster, VPC, Cloud
NAT, reserved IPs, Artifact Registry) is removed normally.
