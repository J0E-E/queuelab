# QueueLab Infrastructure (`infra/`)

Terraform for a cheap, fully-automated **single-EC2** AWS deployment of QueueLab.
One Graviton (arm64) instance runs the whole Docker Compose stack; CodePipeline
ships new images on every push to `main`.

## What it creates

- **Networking:** VPC, one public subnet, internet gateway, route table, security group
  (inbound **80/443 only** — shell access is via SSM Session Manager, so there is no SSH).
- **Compute:** one EC2 instance (`t4g.small`, arm64 Amazon Linux 2023), an Elastic IP, and a
  separate gp3 EBS data volume mounted at `/mnt/queuelab-data` for Postgres/Redis persistence.
  First-boot `user_data` adds a swap file, mounts the data volume, installs Docker + the
  Compose plugin, and installs the CodeDeploy + SSM agents.
- **Registries:** four ECR repos — `api`, `autoscaler`, `worker`, `frontend` (scan-on-push,
  keep last 10 images).
- **CI/CD:** a GitHub CodeConnections connection, an S3 artifact bucket, CodeBuild, CodeDeploy,
  and a CodePipeline (Source → Build → Deploy).
- **DNS:** an A record `queuelab.joeyshub.com` → the Elastic IP, in the existing
  `joeyshub.com` hosted zone (looked up, not created).

## Prerequisites

- Terraform >= 1.5 and AWS credentials for the target account (`aws configure` or env vars).
- The `joeyshub.com` Route53 hosted zone must already exist.

## Variables

Every variable has a sensible default (the locked Epic 18 decisions), so you can run with no
`terraform.tfvars` at all. To override, copy the example:

```sh
cp terraform.tfvars.example terraform.tfvars
# edit as needed
```

Key knobs: `instance_type` (default `t4g.small`), `aws_region` (`us-east-1`),
`github_repository` (`J0E-E/queuelab`), `data_volume_size_gb` (20), `swap_size_gb` (2).

## Usage

```sh
terraform init      # download the AWS provider
terraform plan      # review what will change (needs AWS creds)
terraform apply      # create/update resources — MANUAL & gated; run deliberately
```

State is **local** (no S3/DynamoDB backend) and git-ignored. Keep `terraform.tfstate` safe.

## One-time manual step — authorize the GitHub connection

The CodeConnections connection is created in **PENDING** status; Terraform cannot complete
the GitHub handshake. Before the first pipeline run, authorize it **once**:

1. AWS console → **Developer Tools → Settings → Connections**.
2. Select the `queuelab-github` connection (status *Pending*) → **Update pending connection**.
3. Complete the GitHub OAuth/app authorization.

After that the pipeline can pull source on every push to `main`.

## arm64 note

The instance is **Graviton (arm64)**. Images built and deployed to it must be `linux/arm64`
(handled by the CodeBuild ARM environment + the Epic 19 buildspec). The AMI is resolved at
plan time from the AL2023 arm64 SSM public parameter — no AMI id is ever hardcoded.

## Apply is gated

`terraform apply` is intentionally manual. `terraform validate` (no creds) is the automated
gate for this infra; `plan`/`apply` are run by a human against real AWS.
