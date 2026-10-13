variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "primary_availability_zone" {
  description = <<-EOT
    The single AZ that the managed node group, the NAT Gateway, and the EBS volume are pinned to.
    See docs/kubernetes-overview.md "Persistent storage" for why this is single-AZ by design, not
    spread for HA.
  EOT
  type        = string
  default     = "us-east-1a"
}

variable "secondary_availability_zone" {
  description = <<-EOT
    A second AZ used only to satisfy the EKS control plane's requirement to span >= 2 AZs. No
    node group or workload runs here.
  EOT
  type        = string
  default     = "us-east-1b"
}

variable "cluster_name" {
  description = "Name for the EKS cluster and the resources derived from it (KMS alias, ECR repo, IAM roles)."
  type        = string
  default     = "4thealth"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane."
  type        = string
  default     = "1.31"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC created for this cluster."
  type        = string
  default     = "10.42.0.0/16"
}

variable "node_instance_type" {
  description = "EC2 instance type for the single-node managed node group."
  type        = string
  default     = "t3.medium"
}

variable "admin_principal_arns" {
  description = <<-EOT
    IAM principal ARNs (IAM users or roles) to grant EKS cluster-admin access via EKS Access
    Entries, in addition to whichever principal runs `terraform apply` (which EKS grants
    cluster-admin automatically). Example: ["arn:aws:iam::123456789012:user/alice"].
  EOT
  type        = list(string)
  default     = []
}
