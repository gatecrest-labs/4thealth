# Temporary public HTTPS test access, off by default (enable_public_access). Reserves a static
# external IP and renders a Service manifest for an external passthrough Network LB that only
# accepts traffic from public_access_cidrs. TLS is not terminated at the LB, so the browser sees
# the app's self-signed cert. Apply the manifest with kubectl (see k8s/README.md); destroy it by
# deleting the Service and setting enable_public_access = false.

resource "google_compute_address" "public_test" {
  count  = var.enable_public_access ? 1 : 0
  name   = "${var.cluster_name}-public-test"
  region = var.region

  lifecycle {
    precondition {
      condition     = length(var.public_access_cidrs) > 0
      error_message = "Set public_access_cidrs (e.g. your IP as x.x.x.x/32) when enable_public_access is true."
    }
  }
}
