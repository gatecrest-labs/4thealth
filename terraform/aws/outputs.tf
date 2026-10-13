output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "kms_key_arn" {
  value = aws_kms_key.eks_secrets.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "nat_gateway_public_ip" {
  description = "Hand this IP to your network team for FortiManager/SMTP/RADIUS/SNMP allowlisting."
  value       = module.vpc.nat_public_ips[0]
}

output "lb_controller_role_arn" {
  description = "Pass to --set serviceAccount.annotations when helm-installing aws-load-balancer-controller."
  value       = module.lb_controller_irsa.iam_role_arn
}

output "ebs_csi_role_arn" {
  value = module.ebs_csi_irsa.iam_role_arn
}

output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
