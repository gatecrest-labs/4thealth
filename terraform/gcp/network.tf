# Private-nodes VPC + Cloud NAT with a reserved egress IP, and a reserved internal IP for the
# dashboard load balancer. See docs/kubernetes-gcp.md Phase 1/3 for why private nodes are
# required here (public nodes get ephemeral egress IPs, defeating the allowlisting requirement).

resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "gke" {
  name          = "${var.cluster_name}-subnet"
  ip_cidr_range = var.subnet_cidr
  region        = var.region
  network       = google_compute_network.vpc.id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  private_ip_google_access = true
}

# Static egress IP — hand this to your network team for FortiManager/SMTP/RADIUS/SNMP allowlisting.
resource "google_compute_address" "nat_egress" {
  name   = "${var.cluster_name}-nat-egress"
  region = var.region
}

resource "google_compute_router" "nat" {
  name    = "${var.cluster_name}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.cluster_name}-nat"
  router                             = google_compute_router.nat.name
  region                             = var.region
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat_egress.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# Reserved internal IP for the dashboard's internal passthrough Network LB (docs/kubernetes-gcp.md
# Phase 3). Reference this address's IP as `loadBalancerIP` in the Service manifest.
resource "google_compute_address" "ingress_internal" {
  name         = "${var.cluster_name}-ingress"
  region       = var.region
  subnetwork   = google_compute_subnetwork.gke.id
  address_type = "INTERNAL"
}
