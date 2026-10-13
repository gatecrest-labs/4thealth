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
  description = "Name for the GKE Autopilot cluster and the resources derived from it."
  type        = string
  default     = "4thealth"
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
