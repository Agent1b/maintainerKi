# maintainerKi Installation Guide

This guide is for maintainers who want maintainerKi running without digging through the codebase first.

## What you need

- A GitHub account
- A GitHub App that is installed on the repositories you want to monitor
- Python 3.12
- Node.js 22
- Docker Desktop or Docker Engine
- Your GitHub App private key `.pem` file
- Your GitHub App webhook secret

The CI, Docker images, and tested local toolchain currently use Python 3.12 and Node.js 22.

## Minimum GitHub App setup

Before you run maintainerKi, make sure your GitHub App is configured with:

- Permissions:
  - Pull requests: **Read and write**
  - Issues: **Read and write**
  - Metadata: **Read-only**
- Subscribed webhook events:
  - **Pull request**
  - **Issues**

You will also need:

- the numeric **App ID**
- the generated private key `.pem`
- the webhook secret you set in GitHub

## Option A: local development install

### 1. Create the base config

Copy:

- `.env.example`

to:

- `.env`

### 2. Install backend dependencies

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

If you want to run the full release audit locally, also install:

```bash
./.venv/bin/pip install pip-audit
```

If you want semantic duplicate detection instead of hashing-based duplicate detection, also run:

```bash
./.venv/bin/pip install -r requirements.semantic-duplicates.txt
```

### 3. Install dashboard dependencies

```bash
cd dashboard
npm ci
cd ..
```

### 4. Run the setup wizard

```bash
./.venv/bin/python -m scripts.setup_wizard
```

The wizard will test your GitHub App credentials and create:

- `.env.local`

### 5. Start infrastructure

```bash
make infra-up
```

This starts:

- PostgreSQL
- Redis

### 6. Start maintainerKi

API:

```bash
./.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
./.venv/bin/celery -A worker.celery_app.celery_app worker --loglevel=INFO --pool=solo
```

For local development, `--pool=solo` is the simplest cross-platform worker mode. The packaged stack controls worker concurrency separately through `CELERY_WORKER_CONCURRENCY`.

Dashboard:

```bash
cd dashboard
npm run dev -- --host 127.0.0.1 --port 3000
```

### 7. Open the dashboard

- [http://127.0.0.1:3000](http://127.0.0.1:3000)

## Option B: packaged production-style install

### 1. Create the production env file

Copy:

- `.env.production.example`

to:

- `.env.production`

### 2. Fill in the required values

You must set at least:

- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `GITHUB_WEBHOOK_SECRET`
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY_HOST_PATH`
- `GITHUB_PRIVATE_KEY_PATH`
- `POSTGRES_PASSWORD`

If you want semantic duplicate detection in the packaged stack, also set:

- `INSTALL_SEMANTIC_DUPLICATES=true`
- `DUPLICATE_EMBEDDING_PROVIDER=sentence-transformers`

Notes:

- `make auth-secrets` prints Compose-safe quoted values for `ADMIN_PASSWORD_HASH` and `SESSION_SECRET`
- if you use a non-default env file name with Compose, set `MAINTAINERKI_ENV_FILE=/path/to/that.env` alongside `--env-file`

### 3. Build and start everything

```bash
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

### 4. Open the packaged dashboard

- [http://127.0.0.1:8080](http://127.0.0.1:8080)

### 5. Point your GitHub App webhook to the packaged stack

Use:

- `http://YOUR_HOST:8080/webhooks/github` for local/LAN testing
- `https://YOUR_DOMAIN/webhooks/github` for real production

GitHub requires HTTPS for normal hosted production use.

## Option C: hosted 24/7 install with HTTPS

If you want maintainerKi reachable from the public internet:

1. Set `APP_DOMAIN` in `.env.production`
2. Set `ACME_EMAIL` in `.env.production`
3. Keep `DASHBOARD_BIND_ADDRESS=127.0.0.1`
4. Generate auth values:

```bash
make auth-secrets
```

5. Paste the generated `ADMIN_PASSWORD_HASH` and `SESSION_SECRET` into `.env.production`
6. Run:

```bash
make hosted-up
```

This adds Caddy in front of the dashboard and API so the public entrypoint becomes:

- `https://YOUR_DOMAIN`

Important:

- hosted mode includes a built-in single-admin sign-in flow
- treat it as a trusted self-hosted admin tool, not a public SaaS
- if you expose it publicly, you should still add stronger access control in front of it for shared use

Use the full deployment guide for the VPS/DNS flow:

- `docs/DEPLOYMENT.md`

## First-run checklist

- `/healthz` returns status ok
- `/api/auth/session` reports the expected auth mode
- `./.venv/bin/python -m scripts.purge_old_data` works as a dry run when you want to verify retention settings later
- `make purge-old-data` applies the retention purge when you actually want to delete expired records
- the GitHub App is installed on at least one repository
- a test issue or PR appears in the dashboard
- labels are written back to GitHub
- the worker logs show scoring completed successfully

## If you already have SQLite development data

Start Postgres and run:

```bash
set -a
source .env
set +a
./.venv/bin/python -m scripts.migrate_sqlite_to_postgres --source maintainerki_dev.db --target "$DATABASE_URL"
```

That copies your local dev contributions and feedback into PostgreSQL **only if the target maintainerKi tables are empty**. If you intentionally want to wipe the target tables first, rerun with `--force-reset-target`.
