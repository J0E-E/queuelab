# Values an operator needs after `apply` — for DNS checks, pushing images, and the one-time
# CodeConnections authorization.

output "eip_public_ip" {
  description = "Elastic IP of the host (the A record points here)."
  value       = aws_eip.main.public_ip
}

output "ecr_repository_urls" {
  description = "Push URLs for the four ECR repos, keyed by short name (api/autoscaler/worker/frontend)."
  value       = { for name, repo in aws_ecr_repository.repos : name => repo.repository_url }
}

output "codestar_connection_arn" {
  description = "ARN of the GitHub connection — authorize it ONCE in the console before the first pipeline run."
  value       = aws_codestarconnections_connection.github.arn
}

output "instance_id" {
  description = "EC2 instance id (use with SSM Session Manager for shell access)."
  value       = aws_instance.main.id
}

output "route53_fqdn" {
  description = "Fully qualified domain name serving the app."
  value       = aws_route53_record.app.fqdn
}
