# KMS envelope encryption for EKS Secrets — see docs/kubernetes-overview.md "Secrets baseline".
# K8s Secrets are base64, not encrypted, by default; this is required, not optional.

resource "aws_kms_key" "eks_secrets" {
  description             = "EKS Secrets envelope encryption for ${var.cluster_name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "eks_secrets" {
  name          = "alias/${var.cluster_name}-eks-secrets"
  target_key_id = aws_kms_key.eks_secrets.key_id
}
