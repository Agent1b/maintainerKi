# maintainerKi Deployment Guide

This is the Phase 6 path: a small self-hosted production setup that can stay online 24/7.

Important:

- this deployment path is for self-hosting
- it now supports built-in single-admin dashboard authentication
- do not treat it as a public multi-tenant SaaS
- if you expose it to the public internet, add your own access control layer

The default recommendation is:

- one Linux VPS
- Docker Engine + Docker Compose
- a real domain name
- Caddy for HTTPS
- PostgreSQL + Redis in Docker

## Recommended hosting shape

- VPS size: 2 vCPU / 4 GB RAM is a practical starting point
- OS: Ubuntu 24.04 LTS or another recent Linux distro
- open inbound ports:
  - `80`
  - `443`
- point a DNS record at the server:
  - `maintainerki.example.com -> YOUR_SERVER_IP`

## Files used for hosted production

- `docker-compose.production.yml`
- `docker-compose.hosted.yml`
- `docker/caddy/Caddyfile`
- `.env.production.example`
- `scripts/production_smoke_test.py`

## 1. Prepare the server

Clone the repo onto the VPS, then create the production env file:

```bash
cp .env.production.example .env.production
```

## 2. Fill in production values

At minimum, set:

- `POSTGRES_PASSWORD`
- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `GITHUB_WEBHOOK_SECRET`
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY_HOST_PATH`
- `GITHUB_PRIVATE_KEY_PATH`
- `APP_DOMAIN`
- `ACME_EMAIL`

Important notes:

- `GITHUB_PRIVATE_KEY_HOST_PATH` is the real file path on the VPS
- `GITHUB_PRIVATE_KEY_PATH` is where that file appears inside the containers
- `DASHBOARD_BIND_ADDRESS=127.0.0.1` keeps the raw dashboard off the public internet
- public traffic should go through Caddy on `https://APP_DOMAIN`
- `ADMIN_PASSWORD_HASH` and `SESSION_SECRET` can be generated with `make auth-secrets`
- `make auth-secrets` prints those values already quoted for safe use in `.env.production`
- keep `TRUSTED_HOSTS` aligned with your public hostname
- `ADMIN_PASSWORD` should stay unset in production; use `ADMIN_PASSWORD_HASH`
- the default rate limits and retention windows live in `.env.production.example`

If you run Compose with a non-default env file path, also export:

```bash
export MAINTAINERKI_ENV_FILE=/path/to/your.env.production
```

before `docker compose ... --env-file /path/to/your.env.production ...` so the same file is passed through to the containers.

## 3. Validate the hosted config

```bash
make hosted-config
```

## 4. Start the hosted stack

```bash
make hosted-up
```

That starts:

- PostgreSQL
- Redis
- FastAPI server
- Celery worker
- dashboard nginx
- Caddy with HTTPS

Debug endpoints are disabled by default in production through `DEBUG_API_ENABLED=false`.

## 5. Check readiness

Run:

```bash
export MAINTAINERKI_ADMIN_USERNAME="admin"
export MAINTAINERKI_ADMIN_PASSWORD="YOUR_ADMIN_PASSWORD"
export MAINTAINERKI_WEBHOOK_SECRET="YOUR_WEBHOOK_SECRET"
python -m scripts.production_smoke_test --base-url "https://YOUR_DOMAIN"
```

What this checks:

- `/api/auth/session`
- `/healthz`
- `/readyz`
- `/api/repos`
- signed webhook `ping`

## 6. Update the GitHub App webhook URL

Change your GitHub App webhook target to:

```text
https://YOUR_DOMAIN/webhooks/github
```

## 7. Dogfood on a real repository

- install the app on your test repo
- create a test issue
- create or update a test PR
- confirm:
  - webhook delivery succeeds
  - the worker scores the contribution
  - labels appear back on GitHub
  - the dashboard updates

## Monitoring

Point UptimeRobot or another uptime checker at:

- `https://YOUR_DOMAIN/healthz` for liveness
- `https://YOUR_DOMAIN/readyz` for full dependency readiness

`/readyz` checks:

- database connectivity
- Redis connectivity
- Celery worker responsiveness
- production GitHub App credential readability and GitHub App authentication

## Useful log commands

```bash
docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml logs -f server
docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml logs -f worker
docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml logs -f caddy
```

## Backups

Simple Postgres backup:

```bash
mkdir -p backups
docker compose --env-file .env.production -f docker-compose.production.yml exec -T db \
  sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backups/maintainerki-$(date +%F-%H%M%S).sql"
```

Retention dry run:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec -T server \
  python -m scripts.purge_old_data
```

Retention apply:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec -T server \
  python -m scripts.purge_old_data --apply
```

Recommended: schedule the retention job daily and document who owns backup restores.

## Restore notes

Basic restore flow:

1. stop the app stack
2. restore the Postgres dump into the target database
3. start the stack again
4. rerun the smoke test
5. if webhook deliveries were left in `accepted`, `queue_failed`, or `failed`, run:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml exec -T server \
  python -m scripts.requeue_webhook_deliveries --limit 200
```

## Rollback

If a release is bad:

1. check logs first
2. redeploy the previous known-good version
3. rerun the smoke test
4. requeue persisted webhook deliveries if the bad release interrupted scoring

## Shutdown

```bash
make hosted-down
```
