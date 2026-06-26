# The single EC2 host that runs the whole QueueLab compose stack, its Elastic IP, and a
# separate gp3 EBS data volume for Postgres/Redis persistence.

# Latest Amazon Linux 2023 arm64 AMI, resolved at plan time from the public SSM parameter.
# Never hardcode an AMI id — it differs per region and rolls forward over time.
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "main" {
  ami                    = data.aws_ssm_parameter.al2023_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.instance.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    swap_size_gb           = var.swap_size_gb
    data_volume_mount_path = var.data_volume_mount_path
    region                 = var.aws_region
  })

  root_block_device {
    volume_type = "gp3"
    volume_size = 16
  }

  # Tag drives CodeDeploy's deployment-group EC2 targeting (see cicd.tf).
  tags = merge(local.common_tags, {
    Name        = "${local.name_prefix}-host"
    DeployGroup = "${local.name_prefix}-host"
  })
}

# Separate data volume — kept distinct from the root so it can outlive instance replacement.
resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.main.availability_zone
  size              = var.data_volume_size_gb
  type              = "gp3"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-data" })
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.main.id
}

resource "aws_eip" "main" {
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-eip" })
}

resource "aws_eip_association" "main" {
  instance_id   = aws_instance.main.id
  allocation_id = aws_eip.main.id
}
