# EKS cluster + single-AZ managed node group.
# docs/kubernetes-aws.md Phase 1 does this with eksctl; this is the Terraform equivalent the doc
# calls out as "the better long-term choice if your org already standardizes on Terraform".

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  cluster_endpoint_public_access = true

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets # control plane ENIs span both AZs

  enable_irsa = true # required for IRSA — Load Balancer Controller + EBS CSI driver roles below

  cluster_encryption_config = {
    provider_key_arn = aws_kms_key.eks_secrets.arn
    resources        = ["secrets"]
  }

  eks_managed_node_groups = {
    single_az = {
      instance_types = [var.node_instance_type]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      subnet_ids     = [module.vpc.private_subnets[0]] # primary AZ only — see network.tf
    }
  }

  access_entries = {
    for arn in var.admin_principal_arns : arn => {
      principal_arn = arn
      policy_associations = {
        admin = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }
}
