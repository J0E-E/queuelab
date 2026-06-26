# Point queuelab.joeyshub.com at the Elastic IP. The hosted zone already exists, so it is
# looked up (data source) and never created or managed by this config.

data "aws_route53_zone" "main" {
  name         = var.hosted_zone_name
  private_zone = false
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.main.public_ip]
}
