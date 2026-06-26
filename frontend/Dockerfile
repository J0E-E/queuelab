# QueueLab frontend production image (Epic 19).
#
# One baked artifact: a multi-stage build compiles the Vite + React bundle, then copies it
# into an nginx image that ALSO terminates TLS and reverse-proxies the API/WebSocket/health
# endpoints to the `api` service. This single image is pushed to the `frontend` ECR repo and
# is the only public-facing container in production.
#
# Built for linux/arm64 to match the Graviton (t4g.small) host — CodeBuild runs on an ARM
# image and buildspec.yml passes `--platform linux/arm64`.
#
#   docker build -f frontend/Dockerfile -t queuelab-frontend:latest ./frontend

# --- Stage 1: build the static bundle ---------------------------------------------------
# ECR Public mirror (not Docker Hub) — avoids CodeBuild's anonymous Docker Hub pull rate limit.
FROM public.ecr.aws/docker/library/node:20-alpine AS build
WORKDIR /app

# Install dependencies from the lockfile first for better layer caching.
COPY package.json package-lock.json ./
RUN npm ci

# Compile the bundle. `npm run build` runs `tsc --noEmit && vite build`, emitting to dist/.
COPY . .
RUN npm run build

# --- Stage 2: nginx that serves the bundle + terminates TLS + reverse-proxies -----------
FROM public.ecr.aws/docker/library/nginx:1.27-alpine

# Tools the certbot/bootstrap flow needs: openssl mints the throwaway self-signed cert so the
# TLS server block can start before a real Let's Encrypt cert exists (see docker-entrypoint).
RUN apk add --no-cache openssl

# Our site config replaces the stock default server.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

# Startup hooks run by the stock entrypoint in filename order, AFTER 20-envsubst (so ${DOMAIN}
# is already substituted): 40 mints a throwaway self-signed cert if none exists so the TLS
# server can start; 45 launches the background loop that reloads nginx to pick up renewed certs.
COPY nginx/docker-entrypoint.sh   /docker-entrypoint.d/40-queuelab-bootstrap.sh
COPY nginx/start-cert-reload.sh   /docker-entrypoint.d/45-queuelab-start-cert-reload.sh
COPY nginx/cert-reload.sh         /usr/local/bin/queuelab-cert-reload.sh
RUN chmod +x /docker-entrypoint.d/40-queuelab-bootstrap.sh \
             /docker-entrypoint.d/45-queuelab-start-cert-reload.sh \
             /usr/local/bin/queuelab-cert-reload.sh

# The compiled SPA bundle.
COPY --from=build /app/dist /usr/share/nginx/html

# Document the ports nginx listens on (compose publishes 80 + 443).
EXPOSE 80 443
