# QueueLab — First Deploy Runbook (Epic 19)

This is the **manual operator runbook** for the first live deploy. The CI/CD *plumbing*
(buildspec, appspec, hooks, prod compose, TLS) ships with Epic 19; the steps below are the
human actions that take it live. Nothing here is run automatically — `terraform apply` and the
one-time GitHub authorization are deliberately manual.

Everything references real files/outputs: `infra/*.tf`, `infra/outputs.tf`, `buildspec.yml`,
`appspec.yml`, `scripts/deploy/*`, `docker-compose.prod.yml`, `ops/deploy/prod.env.example`.

---

## 0. Prerequisites

- AWS credentials with rights to apply `infra/`.
- The Route53 hosted zone `joeyshub.com` already exists (looked up by `infra/dns.tf`, never
  created here).
- Repo pushed to `J0E-E/queuelab` (the `github_repository` default in `infra/variables.tf`).

---

## 1. Provision infrastructure — `terraform apply`

```bash
cd infra
terraform init
terraform apply
```

This creates the VPC/host/EIP, the four ECR repos (`queuelab-{api,autoscaler,worker,frontend}`),
the CodeBuild/CodeDeploy/CodePipeline, and the Route53 **A record**
`queuelab.joeyshub.com -> EIP` (`infra/dns.tf`). Note the outputs (`infra/outputs.tf`):

- `eip_public_ip` — the host's Elastic IP (the A record points here).
- `ecr_repository_urls` — push URLs for the four repos.
- `codestar_connection_arn` — needed for step 2.
- `instance_id` — for SSM Session Manager shell access.
- `route53_fqdn` — `queuelab.joeyshub.com`.

---

## 2. Authorize the GitHub connection (ONE time)

The CodeConnections connection is created **PENDING** and cannot pull source until a human
authorizes it once in the console (`infra/cicd.tf` comment says exactly this):

1. AWS Console -> Developer Tools -> Settings -> Connections.
2. Find `queuelab-github` (or use the `codestar_connection_arn` output).
3. **Update pending connection** -> install/authorize the GitHub app on `J0E-E/queuelab`.

Until this is done every pipeline run fails at the Source stage.

---

## 3. Put the production secret on the host — `prod.env`

The production secret lives in a host file for this lab (SSM hardening is noted at the bottom).
Shell onto the instance via SSM Session Manager (no SSH/key needed; the agent is installed by
`infra/user_data.sh.tftpl`):

```bash
aws ssm start-session --target <instance_id>      # from the terraform output
sudo -i
mkdir -p /opt/queuelab
cd /opt/queuelab
# Paste in prod.env using ops/deploy/prod.env.example as the template.
```

Fill it from `ops/deploy/prod.env.example`. The only true secret is **`POSTGRES_PASSWORD`**
(use a strong value; make `DATABASE_URL` use the same password). Also set `DOMAIN`,
`CERTBOT_EMAIL`, and the `WORKER_*` values. Leave `IMAGE_TAG`/`ECR_REGISTRY` as placeholders —
the `before_install` hook overwrites them on every deploy.

> The data directory `/mnt/queuelab-data` (the EBS volume from `infra/compute.tf`) is mounted by
> first-boot user-data; postgres/redis bind their data there so it survives redeploys.

---

## 4. Trigger the deploy — push to `main`

```bash
git push origin main
```

CodePipeline watches `main` (`infra/variables.tf` `github_branch`). Push fires:

1. **Source** — pulls via the authorized connection.
2. **Build** — CodeBuild runs `buildspec.yml`: builds the four `linux/arm64` images (backend ->
   both `api` + `autoscaler`, worker from repo root, the baked frontend), pushes each tagged
   with the commit SHA **and** `latest`, and emits the deploy artifact (appspec, hooks, both
   compose files, `prod.env.example`, `image_tag.env`).
3. **Deploy** — CodeDeploy runs the `appspec.yml` hooks on the host in order:
   `application_stop` (compose down, **keeps data volumes**) ->
   `before_install` (ECR login, stamp `IMAGE_TAG`/`ECR_REGISTRY` into `prod.env`) ->
   `application_start` (`compose pull && up -d`, Alembic migrate, reload nginx) ->
   `validate_service` (curl `https://$DOMAIN/health` through the running stack).

Watch it in the CodePipeline console (or `aws codepipeline get-pipeline-state --name
queuelab-pipeline`). The CodeDeploy hook logs are on the host at
`/opt/codedeploy-agent/deployment-root/.../logs/scripts.log`.

---

## 5. Verify the live narrative

Once the pipeline is green:

1. **HTTPS** — open `https://queuelab.joeyshub.com`. The SPA loads over TLS (see cert
   troubleshooting if the browser warns about the cert — it means certbot has not finished
   issuing yet; give it a minute and reload).
2. **WebSocket** — the dashboard's live feed connects (`/ws`); the connection indicator goes
   live. In devtools, `wss://queuelab.joeyshub.com/ws` shows status 101.
3. **The end-to-end story** — drive the lab narrative and watch it work live:
   - **submit** jobs -> they appear in the queue feed;
   - **break** (chaos) -> failures show in the feed/metrics;
   - **recover** -> the queue drains again;
   - **scale** -> as depth rises the autoscaler spawns worker containers (visible via
     `docker ps` on the host) and kills them as it drains.

---

## 6. TLS / certbot troubleshooting

The cert flow: nginx starts on a **throwaway self-signed** cert (so :443 can listen before any
real cert exists), the `certbot` sidecar issues the real Let's Encrypt cert via HTTP-01 webroot,
and nginx's own 6-hourly reload loop picks it up.

- **Dry run first.** Let's Encrypt rate-limits the production CA hard. Set `CERTBOT_STAGING=1`
  in `prod.env` and redeploy to issue against the **staging** CA (untrusted but unlimited).
  Confirm the cert appears under `/etc/letsencrypt/live/$DOMAIN/`, then set `CERTBOT_STAGING=0`,
  delete the staging cert, and redeploy for the real one:
  ```bash
  docker compose -p queuelab -f docker-compose.yml -f docker-compose.prod.yml \
    run --rm --entrypoint "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf /etc/letsencrypt/archive/$DOMAIN" certbot
  ```
- **Challenge fails (timeout/connection refused).** The HTTP-01 path must be reachable: DNS A
  record points at the EIP (step 1), the security group allows :80 + :443, and nginx is serving
  `/.well-known/acme-challenge/` over plain HTTP. Check `docker logs queuelab-certbot-1`.
- **Browser shows an untrusted cert.** Either still on the placeholder/staging cert, or issuance
  failed — check the certbot logs and re-run the renewal.

---

## 7. Rollback

CodeDeploy keeps the previous revision. To roll back, redeploy the last good pipeline execution
(CodeDeploy console -> the deployment group -> **Stop and roll back**, or re-run the previous
revision). Because `application_stop` never removes data volumes, Postgres/Redis data carries
across rollbacks unchanged. To pin an older image without a new build, set `IMAGE_TAG` in
`prod.env` to the desired commit SHA and re-run `application_start` on the host.

---

## Hardening (future)

For this learning lab the production secret is the host `prod.env`. The obvious next step is to
move `POSTGRES_PASSWORD` (and friends) into **SSM Parameter Store / Secrets Manager** and have
`before_install` fetch them, so no plaintext secret sits on the host. Noted, not done here.
