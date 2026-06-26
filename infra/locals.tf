# Shared name prefix and tags applied to every resource (via default_tags would also work,
# but explicit locals keep the intent obvious for a learner reading the code).
locals {
  name_prefix = var.project_name

  common_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Epic      = "18-infrastructure"
  }
}
