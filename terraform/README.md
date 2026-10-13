# Terraform — 4THealth on Kubernetes

Infrastructure-as-code for the AWS and GCP designs documented in:

- [docs/kubernetes-overview.md](../docs/kubernetes-overview.md) — shared design, single-replica
  rule, zone-pinning rationale
- [docs/kubernetes-aws.md](../docs/kubernetes-aws.md) — AWS (EKS) mechanics
- [docs/kubernetes-gcp.md](../docs/kubernetes-gcp.md) — GCP (GKE) mechanics

Read those docs before touching these files — this Terraform just automates the cloud
infrastructure (network, cluster, IAM, KMS, image registry) each doc walks through by hand.

## Scope: what Terraform does and doesn't do

Terraform here provisions the **cloud infrastructure** — VPC/network, the EKS/GKE cluster, the
NAT Gateway / Cloud NAT with its static egress IP, a reserved **internal** IP for the dashboard
load balancer, KMS/CMEK encryption, IAM roles, and the image registry.

It does **not** apply Kubernetes manifests — the `Deployment`, `Service`, `PersistentVolumeClaim`,
and `Secret` YAML from each cloud doc's Phase 4/6/7 are applied with `kubectl` after the cluster
exists, same as if you'd built the cluster by hand with `eksctl`/`gcloud`. Keeping these layers
separate means you can tear down and rebuild the cluster without re-authoring your app secrets or
losing track of what's infra vs. what's app.

## Folders

| Folder | Cloud | Contents |
|---|---|---|
| [aws/](aws/) | AWS EKS | VPC, single-AZ managed node group, EKS cluster, KMS, IRSA roles, ECR |
| [gcp/](gcp/) | GCP GKE | VPC, Cloud NAT, GKE Autopilot cluster, KMS, Artifact Registry |

Each folder is a **standalone root module** — `terraform init`/`plan`/`apply` from inside
`terraform/aws/` or `terraform/gcp/`, not from this top-level folder.

## Before you run either one

1. Install Terraform (>= 1.6) and the relevant cloud CLI (`aws` or `gcloud`), and authenticate.
2. Copy `terraform.tfvars.example` to `terraform.tfvars` in the cloud folder you're using and fill
   in your own values — see that folder's own `README.md` for exactly which variables you need to
   change.
3. **Never commit `terraform.tfvars`** if it contains anything specific to your organization
   (account IDs, project IDs, real IAM ARNs). The root `.gitignore` already excludes it, but double
   check before pushing to a public fork.
4. These both provision real, billed cloud resources — review the plan (`terraform plan`) before
   `terraform apply`, and see each cloud doc's "Cost reference" section for what to expect on the
   bill.

## State

Both folders default to **local state** (a `terraform.tfstate` file on your machine) to keep the
first run simple. For anything beyond a solo trial, move to a remote backend (S3 + DynamoDB locking
for AWS, a GCS bucket for GCP) before a second person touches the same cluster — each folder's
`README.md` shows the minimal backend block to add.
