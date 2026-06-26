# CI/CD: GitHub source -> CodeBuild (build & push images) -> CodeDeploy (in-place on the EC2).
# The CodeConnections connection is created PENDING and must be authorized ONCE in the
# console before any pipeline run can pull source (see README).

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- GitHub connection -----------------------------------------------------------------
resource "aws_codestarconnections_connection" "github" {
  name          = "${local.name_prefix}-github"
  provider_type = "GitHub"
  tags          = local.common_tags
}

# --- Artifact bucket -------------------------------------------------------------------
resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.name_prefix}-artifacts-"
  force_destroy = true # lab convenience: lets `terraform destroy` clean up non-empty bucket
  tags          = local.common_tags
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =======================================================================================
# CodeBuild
# =======================================================================================
data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${local.name_prefix}-codebuild-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }

  statement {
    sid = "Artifacts"
    actions = [
      "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }

  # Build images and push them to ECR. GetAuthorizationToken cannot be scoped to a resource.
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repo in aws_ecr_repository.repos : repo.arn]
  }
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "${local.name_prefix}-codebuild-policy"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

resource "aws_codebuild_project" "build" {
  name         = "${local.name_prefix}-build"
  service_role = aws_iam_role.codebuild.arn
  tags         = local.common_tags

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    # ARM image so it can build linux/arm64 natively for the Graviton instance (Epic 19).
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type            = "ARM_CONTAINER"
    privileged_mode = true # needed for docker builds
  }

  source {
    type = "CODEPIPELINE"
    # buildspec.yml arrives in Epic 19 and lives at the repo root by default.
  }
}

# =======================================================================================
# CodeDeploy
# =======================================================================================
data "aws_iam_policy_document" "codedeploy_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codedeploy" {
  name               = "${local.name_prefix}-codedeploy-role"
  assume_role_policy = data.aws_iam_policy_document.codedeploy_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
}

resource "aws_codedeploy_app" "main" {
  name             = "${local.name_prefix}-app"
  compute_platform = "Server" # EC2/on-prem in-place deploys via the agent
  tags             = local.common_tags
}

resource "aws_codedeploy_deployment_group" "main" {
  app_name              = aws_codedeploy_app.main.name
  deployment_group_name = "${local.name_prefix}-dg"
  service_role_arn      = aws_iam_role.codedeploy.arn

  deployment_style {
    deployment_type   = "IN_PLACE"
    deployment_option = "WITHOUT_TRAFFIC_CONTROL"
  }

  # Target the single host by its tag (set in compute.tf).
  ec2_tag_set {
    ec2_tag_filter {
      key   = "DeployGroup"
      type  = "KEY_AND_VALUE"
      value = "${local.name_prefix}-host"
    }
  }

  tags = local.common_tags
}

# =======================================================================================
# CodePipeline
# =======================================================================================
data "aws_iam_policy_document" "codepipeline_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codepipeline" {
  name               = "${local.name_prefix}-codepipeline-role"
  assume_role_policy = data.aws_iam_policy_document.codepipeline_assume_role.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "codepipeline" {
  statement {
    sid = "Artifacts"
    actions = [
      "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }

  statement {
    sid       = "UseConnection"
    actions   = ["codestar-connections:UseConnection"]
    resources = [aws_codestarconnections_connection.github.arn]
  }

  statement {
    sid = "RunBuild"
    actions = [
      "codebuild:BatchGetBuilds", "codebuild:StartBuild"
    ]
    resources = [aws_codebuild_project.build.arn]
  }

  statement {
    sid = "RunDeploy"
    actions = [
      "codedeploy:CreateDeployment",
      "codedeploy:GetApplication",
      "codedeploy:GetApplicationRevision",
      "codedeploy:GetDeployment",
      "codedeploy:GetDeploymentConfig",
      "codedeploy:RegisterApplicationRevision",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "PassDeployServiceRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.codedeploy.arn]
  }
}

resource "aws_iam_role_policy" "codepipeline" {
  name   = "${local.name_prefix}-codepipeline-policy"
  role   = aws_iam_role.codepipeline.id
  policy = data.aws_iam_policy_document.codepipeline.json
}

resource "aws_codepipeline" "main" {
  name          = "${local.name_prefix}-pipeline"
  role_arn      = aws_iam_role.codepipeline.arn
  pipeline_type = "V2"
  tags          = local.common_tags

  artifact_store {
    location = aws_s3_bucket.artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = var.github_repository
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "Build"
    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["build_output"]

      configuration = {
        ProjectName = aws_codebuild_project.build.name
      }
    }
  }

  stage {
    name = "Deploy"
    action {
      name            = "Deploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "CodeDeploy"
      version         = "1"
      input_artifacts = ["build_output"]

      configuration = {
        ApplicationName     = aws_codedeploy_app.main.name
        DeploymentGroupName = aws_codedeploy_deployment_group.main.deployment_group_name
      }
    }
  }
}
