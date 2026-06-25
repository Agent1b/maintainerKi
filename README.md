# maintainerKi

maintainerKi is an open-source, self-hosted GitHub triage assistant for issues and pull requests.

It receives GitHub webhooks, scores new contributions, flags likely duplicates, suggests labels, and gives maintainers a dashboard to work from.

## Project status

- alpha / MVP
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
   - `cd dashboard && npm install`
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

That means maintainerKi is suitable for an alpha self-hosted open-source source release even without an official hosted deployment, but release archives should be produced from tracked Git files, not by zipping the raw workspace.

## Important hosting note

The hosted deployment path is currently for:

- trusted self-hosting
- internal teams
- private admin use

It does **not** include end-user authentication yet.

So if you deploy it on the public internet, put it behind your own access controls or treat it as an internal tool until auth exists.

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
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [FAQ](docs/FAQ.md)
- [Production MVP checklist](docs/PRODUCTION_MVP_CHECKLIST.md)
- `maintainerKi-README.md` — original long-form design / roadmap notes

## Development commands

- `make infra-up`
- `make infra-down`
- `make test`
- `make dashboard-build`
- `make setup-wizard`
- `make prod-up`
- `make prod-down`
- `make source-snapshot`
- `make requeue-webhooks`

## Contributing and security

- See [CONTRIBUTING.md](CONTRIBUTING.md)
- See [SECURITY.md](SECURITY.md)
