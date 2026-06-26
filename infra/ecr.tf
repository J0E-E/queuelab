# Container image registries. Four repos for spec fidelity even though api & autoscaler
# share one backend image at runtime (see Implementation notes / README). Each scans images
# on push and keeps only the last ~10 to avoid unbounded storage cost.

locals {
  ecr_repositories = ["api", "autoscaler", "worker", "frontend"]
}

resource "aws_ecr_repository" "repos" {
  for_each = toset(local.ecr_repositories)

  name                 = "${local.name_prefix}-${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-${each.key}" })
}

resource "aws_ecr_lifecycle_policy" "repos" {
  for_each = aws_ecr_repository.repos

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the last 10 images."
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}
