variable "project_id" {
  description = "GCP project ID to deploy into. No default — you must set this."
  type        = string
}

variable "region" {
  description = "GCP region for the cluster, subnet, Cloud NAT, and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "Name for the GKE Autopilot cluster and the resources derived from it. Must start with a letter — GCP rejects names like \"4thealth\"."
  type        = string
  default     = "fourthealth"
}

variable "subnet_cidr" {
  description = "Primary IP range for the GKE subnet (node IPs)."
  type        = string
  default     = "10.60.0.0/20"
}

variable "pods_cidr" {
  description = "Secondary range for Pod IPs."
  type        = string
  default     = "10.61.0.0/16"
}

variable "services_cidr" {
  description = "Secondary range for Service IPs."
  type        = string
  default     = "10.62.0.0/20"
}

variable "master_cidr" {
  description = "CIDR block for the private GKE control plane (/28 required by GKE)."
  type        = string
  default     = "172.16.0.0/28"
}

variable "enable_public_access" {
  description = "Temporary test access: reserve a static external IP and render a Service manifest that exposes 4THealth over HTTPS, restricted to public_access_cidrs. Leave false except while testing."
  type        = bool
  default     = false
}

variable "public_access_cidrs" {
  description = "Source CIDRs allowed to reach the public test endpoint, e.g. [\"203.0.113.7/32\"] (your public IP). Required when enable_public_access is true."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.public_access_cidrs, "0.0.0.0/0")
    error_message = "0.0.0.0/0 would open the test endpoint to the whole internet; list specific CIDRs."
  }
}
