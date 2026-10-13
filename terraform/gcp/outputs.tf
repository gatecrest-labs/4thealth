output "cluster_name" {
  value = google_container_cluster.autopilot.name
}

output "cluster_endpoint" {
  value     = google_container_cluster.autopilot.endpoint
  sensitive = true
}

output "nat_egress_ip" {
  description = "Hand this IP to your network team for FortiManager/SMTP/RADIUS/SNMP allowlisting."
  value       = google_compute_address.nat_egress.address
}

output "ingress_internal_ip" {
  description = "Use as `loadBalancerIP` in the dashboard Service manifest (docs/kubernetes-gcp.md Phase 3)."
  value       = google_compute_address.ingress_internal.address
}

output "artifact_registry_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "kms_key_id" {
  value = google_kms_crypto_key.gke_secrets.id
}

output "configure_kubectl" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.autopilot.name} --region ${var.region} --project ${var.project_id}"
}
