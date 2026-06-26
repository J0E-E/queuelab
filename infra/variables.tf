# All knobs an operator might turn. Defaults are the locked Epic 18 decisions.

variable "aws_region" {
  description = "AWS region everything lives in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used as a prefix for resource names and tags."
  type        = string
  default     = "queuelab"
}

variable "instance_type" {
  description = "EC2 instance type. t4g.small is ARM/Graviton (2 vCPU / 2 GiB) — paired with a swap file to tolerate up to MAX_WORKERS worker containers."
  type        = string
  default     = "t4g.small"
}

variable "data_volume_size_gb" {
  description = "Size of the separate gp3 EBS data volume that holds Postgres/Redis data across redeploys and reboots."
  type        = number
  default     = 20
}

variable "swap_size_gb" {
  description = "Size of the swap file created on the instance at first boot (helps the small instance tolerate many worker containers)."
  type        = number
  default     = 2
}

variable "github_repository" {
  description = "GitHub repo (owner/name) that CodeConnections + CodePipeline pull source from."
  type        = string
  default     = "J0E-E/queuelab"
}

variable "github_branch" {
  description = "Branch CodePipeline watches for new source."
  type        = string
  default     = "main"
}

variable "domain_name" {
  description = "Public hostname for the app. An A record for this name is created in the existing hosted zone."
  type        = string
  default     = "queuelab.joeyshub.com"
}

variable "hosted_zone_name" {
  description = "Name of the EXISTING Route53 hosted zone the A record goes into (looked up, never created)."
  type        = string
  default     = "joeyshub.com"
}

variable "data_volume_mount_path" {
  description = "Where the EBS data volume is mounted on the instance."
  type        = string
  default     = "/mnt/queuelab-data"
}
