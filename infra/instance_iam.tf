# IAM role + instance profile the EC2 box assumes. It needs to:
#   - pull container images from ECR        (AmazonEC2ContainerRegistryReadOnly)
#   - be managed/shelled-into via SSM        (AmazonSSMManagedInstanceCore)
#   - let the CodeDeploy agent read the deploy artifact from the pipeline's S3 bucket

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${local.name_prefix}-instance-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = local.common_tags
}

resource "aws_iam_role_policy_attachment" "instance_ecr_read" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "instance_ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# The CodeDeploy agent on the instance fetches the deployment bundle from the artifact bucket.
data "aws_iam_policy_document" "instance_codedeploy_artifacts" {
  statement {
    sid     = "ReadDeployArtifacts"
    actions = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "instance_codedeploy_artifacts" {
  name   = "${local.name_prefix}-instance-codedeploy-artifacts"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance_codedeploy_artifacts.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name_prefix}-instance-profile"
  role = aws_iam_role.instance.name
  tags = local.common_tags
}
