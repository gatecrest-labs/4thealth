resource "google_artifact_registry_repository" "app" {
  repository_id = var.cluster_name
  location      = var.region
  format        = "DOCKER"
}
