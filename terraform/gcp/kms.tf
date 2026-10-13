# Application-layer secrets encryption for GKE — see docs/kubernetes-overview.md
# "Secrets baseline". Grants the GKE service agent permission to use the key for
# envelope-encrypting Secret data at rest.

resource "google_kms_key_ring" "gke" {
  name     = "${var.cluster_name}-keyring"
  location = var.region
}

resource "google_kms_crypto_key" "gke_secrets" {
  name     = "gke-secrets"
  key_ring = google_kms_key_ring.gke.id

  lifecycle {
    prevent_destroy = true
  }
}

data "google_project" "current" {}

resource "google_kms_crypto_key_iam_member" "gke_sa_encrypt_decrypt" {
  crypto_key_id = google_kms_crypto_key.gke_secrets.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@container-engine-robot.iam.gserviceaccount.com"
}
