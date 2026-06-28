# maintainerKi

maintainerKi is an open-source, self-hosted GitHub triage assistant for issues and pull requests.

It receives GitHub webhooks, scores new contributions, flags likely duplicates, suggests labels, and gives maintainers a dashboard to work from.

## Project status

- beta / self-hosted MVP
- self-hosted only
- bring your own GitHub App
- bring your own model provider
- no official hosted SaaS yet

## What it does

- receives `issues` and `pull_request` GitHub webhooks
- scores contributions for quality, relevance, completeness, and suspicion
- detects likely duplicates
- suggests labels and can write them back to GitHub
- gives maintainers a dashboard inbox and feedback loop

## Supported scoring providers

- `mock`
- `ollama`
- `mlx`

Duplicate detection providers:

- `hashing` (default)
- `sentence-transformers` (optional heavier install)

## Quick start

### Local development

1. Copy `.env.example` to `.env`
2. Install backend dependencies:
   - `python3 -m venv .venv`
   - `./.venv/bin/pip install -r requirements.txt`
3. Optional semantic duplicate detection:
   - `./.venv/bin/pip install -r requirements.semantic-duplicates.txt`
4. Install dashboard dependencies:
   - `cd dashboard && npm ci`
5. Start infrastructure:
   - `make infra-up`
6. Start the API:
   - `./.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000`
7. Start the worker:
   - `./.venv/bin/celery -A worker.celery_app.celery_app worker --loglevel=INFO --pool=solo`
8. Start the dashboard:
   - `cd dashboard && npm run dev -- --host 127.0.0.1 --port 3000`

### Setup wizard

Run:

```bash
./.venv/bin/python -m scripts.setup_wizard
```

The wizard:

- verifies GitHub App credentials
- discovers installed repositories
- lets you choose which repositories to monitor
- writes `.env.local` overrides for repo filters and thresholds

### Packaged self-hosted stack

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

`make infra-up` starts both PostgreSQL and Redis for local development.

## Open-source release model

Use Git or `make source-snapshot` to publish a source release. Do **not** upload a raw zip/tar of your working directory because local `.env`, database, or private-key files may exist outside Git.


maintainerKi is currently designed to be used like this:

- you run it locally or on your own server
- you create and install your own GitHub App
- you choose your own model provider
- you keep control of your own secrets and infrastructure

That means maintainerKi is suitable for a beta self-hosted open-source source release even without an official hosted deployment, but release archives should be produced from tracked Git files, not by zipping the raw workspace.

## Important hosting note

The hosted deployment path is currently for:

- trusted self-hosting
- internal teams
- private admin use

It now includes a **single-admin dashboard sign-in mode** for self-hosted deployments.

That helps protect the maintainer dashboard and API, but it is **not** the same thing as:

- multi-user auth
- team roles / permissions
- public multi-tenant SaaS auth

So if you deploy it on the public internet, keep treating it like a private admin tool unless you add a broader access-control layer and finish the later SaaS/auth work.

The production examples now default to a safer baseline:

- `EXPOSE_API_DOCS=false`
- `DETAILED_PUBLIC_HEALTH=false`
- `TRUSTED_HOSTS=...` for host-header validation
- `ADMIN_AUTH_ENABLED=true`

Generate auth secrets with:

```bash
make auth-secrets
```

That prints:

- `ADMIN_PASSWORD_HASH=...`
- `SESSION_SECRET=...`

Paste those into `.env.production` exactly as printed. The generated values are intentionally quoted so Docker Compose treats `$` safely.

For dashboard browser coverage, you can run:

```bash
cd dashboard
npm run e2e:install
npm run e2e
```

For a realistic local webhook simulation against a well-known public repo target, the repo also ships bundled Flask issue + PR fixtures:

```bash
export MAINTAINERKI_WEBHOOK_SECRET="YOUR_WEBHOOK_SECRET"
make flask-webhook-test BASE_URL=http://127.0.0.1:8000
```

That sends signed `pallets/flask` issue and pull-request fixture payloads into your running maintainerKi instance so you can verify end-to-end ingest without waiting on live GitHub traffic.

## Repository layout

- `server/` — FastAPI backend
- `worker/` — Celery worker
- `dashboard/` — React + Vite frontend
- `scripts/` — setup and operational helpers
- `docs/` — installation, configuration, deployment, troubleshooting

## Documentation

- [Installation guide](docs/INSTALLATION.md)
- [Configuration guide](docs/CONFIGURATION.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Privacy and retention](docs/PRIVACY_RETENTION.md)
- [Release guide](docs/RELEASE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [FAQ](docs/FAQ.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Production MVP checklist](docs/PRODUCTION_MVP_CHECKLIST.md)
- `maintainerKi-README.md` — original long-form design / roadmap notes

## Development commands

- `make infra-up`
- `make infra-down`
- `make test`
- `make dashboard-build`
- `make dashboard-e2e`
- `make setup-wizard`
- `make prod-up`
- `make prod-down`
- `make source-snapshot`
- `make release-audit`
- `make purge-old-data`
- `make requeue-webhooks`

## Contributing and security

- See [CONTRIBUTING.md](CONTRIBUTING.md)
- See [SECURITY.md](SECURITY.md)
