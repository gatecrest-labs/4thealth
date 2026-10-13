# Terraform — AWS (EKS)

Provisions the AWS infrastructure described in [docs/kubernetes-aws.md](../../docs/kubernetes-aws.md):
a single-AZ VPC with one NAT Gateway, an EKS cluster with KMS-encrypted Secrets, a single-node
managed node group, IRSA roles for the Load Balancer Controller and EBS CSI driver, and an ECR
repository. See [terraform/README.md](../README.md) for what this does *not* cover (Kubernetes
manifests, helm installs).

## Files

| File | What it defines |
|---|---|
| `versions.tf` | Terraform + AWS provider version constraints |
| `variables.tf` | Every input you can override — see below |
| `network.tf` | VPC, two-AZ subnets, single NAT Gateway (`terraform-aws-modules/vpc/aws`) |
| `kms.tf` | KMS key for EKS Secrets envelope encryption |
| `eks.tf` | EKS cluster + single-AZ managed node group (`terraform-aws-modules/eks/aws`) |
| `irsa.tf` | IAM roles for the Load Balancer Controller and EBS CSI driver |
| `ecr.tf` | ECR repository for the app image |
| `outputs.tf` | Values you'll need for the next steps (NAT IP, kubectl config command, IRSA role ARNs) |
| `terraform.tfvars.example` | Template for your own `terraform.tfvars` |

## Modify for your own environment

1. **Copy the tfvars template:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. **Edit `terraform.tfvars`** — at minimum, change:
   - `region`, `primary_availability_zone`, `secondary_availability_zone` — your AWS region and
     the two AZs it has (the primary AZ is where the node group, NAT Gateway, and EBS volume all
     live — see the zone-pinning note in `docs/kubernetes-overview.md`).
   - `cluster_name` — if you're running more than one environment (e.g. `4thealth-dev`), or if
     `4thealth` collides with an existing resource name in your account.
   - `vpc_cidr` — change if `10.42.0.0/16` overlaps with an existing VPC you'll peer or connect
     this VPC to (VPN/Direct Connect, matching the internal-only dashboard access model).
   - `admin_principal_arns` — add IAM users/roles (besides whoever runs `terraform apply`) who
     need `kubectl` admin access. Find your own ARN with `aws sts get-caller-identity`.

3. **Authenticate the AWS provider** the normal way — `aws configure`, environment variables, or
   an assumed role. This repo doesn't hardcode credentials anywhere.

4. **Run it:**
   ```bash
   terraform init
   terraform plan   # review before applying — this creates billed resources
   terraform apply
   ```

5. **Continue with `docs/kubernetes-aws.md` Phase 2 onward** — `terraform output configure_kubectl`
   gives you the exact `aws eks update-kubeconfig` command. From there, install the Load Balancer
   Controller via Helm (use `terraform output lb_controller_role_arn` for the service account
   annotation instead of running `eksctl create iamserviceaccount` — Terraform already created
   that role), then apply the `Deployment`/`Service`/`PersistentVolumeClaim` manifests from
   Phase 6/7.

## Moving to remote state

Local state (`terraform.tfstate` on your machine) is fine solo. Once a second person touches this
cluster, add an S3 + DynamoDB backend before anyone runs `apply` again:

```hcl
# backend.tf — create this file yourself; bucket/table must already exist
terraform {
  backend "s3" {
    bucket         = "your-terraform-state-bucket"
    key            = "4thealth/aws/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "your-terraform-lock-table"
    encrypt        = true
  }
}
```

Then run `terraform init -migrate-state`.

## Tearing down

```bash
terraform destroy
```

This deletes the cluster, VPC, NAT Gateway, and ECR repository. It does **not** delete anything
inside the cluster's PersistentVolume automatically if you've already set `deletion_protection`
or taken manual EBS snapshots — check for orphaned EBS volumes afterward if you skipped backups.
