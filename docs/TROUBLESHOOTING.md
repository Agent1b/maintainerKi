# maintainerKi Troubleshooting

## The API starts but says it is using SQLite fallback

Check:

- Postgres is running
- `DATABASE_URL` is correct
- the hostname inside Docker is `db`, not `localhost`

Quick check:

```bash
curl http://127.0.0.1:8000/healthz
```

If you see:

- `"backend": "sqlite"`
- `"using_sqlite_fallback": true`

then Postgres is not being reached by the app.

## /readyz fails but /healthz is fine

That means the API process is alive, but one of the production dependencies is not fully ready.

Check:

- database connectivity
- Redis connectivity
- Celery worker health
- GitHub App secret/private key presence in production

Useful command:

```bash
curl http://127.0.0.1:8000/readyz
```

Read the `components` section to see which dependency is degraded.

## The worker is running but nothing gets scored

Check:

- Redis is running
- `CELERY_BROKER_URL` is valid
- the worker process is actually started

Useful command:

```bash
./.venv/bin/celery -A worker.celery_app.celery_app worker --loglevel=INFO --pool=solo
```

Look for queue or scoring exceptions in the logs.

## GitHub says the webhook failed

Check:

- the webhook URL is correct
- `GITHUB_WEBHOOK_SECRET` matches the GitHub App settings
- the server is reachable from GitHub
- HTTPS is configured in real hosted production

For local testing, GitHub usually needs a tunnel/forwarder or a reachable host.

## Labels are not written back to GitHub

Check:

- `GITHUB_APP_ID` is correct
- `GITHUB_PRIVATE_KEY_PATH` points to the right `.pem`
- the app is installed on that repository
- the app has the permissions needed to manage issues/PR labels
- `GITHUB_LABEL_WRITEBACK_ENABLED=true`

Run the setup wizard again if needed:

```bash
./.venv/bin/python -m scripts.setup_wizard
```

## The dashboard loads but shows no repositories

Check:

- webhook events actually arrived
- the worker completed scoring
- the data was saved to Postgres
- the repo is not being filtered out by `MONITORED_REPOSITORIES`

If `MONITORED_REPOSITORIES` is set, only listed repositories are accepted.

## Docker production stack will not start

Check:

- Docker Desktop / Docker Engine is running
- `.env.production` exists
- `GITHUB_PRIVATE_KEY_HOST_PATH` points to a real host file
- the value of `GITHUB_PRIVATE_KEY_PATH` is the in-container path, not the host path

Validate the compose file:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml config
```

For the hosted HTTPS stack:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml config
```

## HTTPS works locally but the public domain does not

Check:

- DNS for `APP_DOMAIN` points to the VPS
- ports `80` and `443` are open
- Caddy is running

Useful log command:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml logs -f caddy
```

## Why do `/debug/...` endpoints return 404?

That is expected unless `DEBUG_API_ENABLED=true`.

The debug API is meant for local development and is disabled by default outside development.

## The dashboard is up but scoring is fake

That usually means:

- `SCORER_PROVIDER=mock`

Change the provider to `ollama` or `mlx` in your environment config if you want real model scoring.

## Duplicate detection is slow on first run

That is normal if you use:

- `DUPLICATE_EMBEDDING_PROVIDER=sentence-transformers`

The embedding model may need to download the first time.

If you installed only the base requirements, switch to `DUPLICATE_EMBEDDING_PROVIDER=hashing` or install:

```bash
./.venv/bin/pip install -r requirements.semantic-duplicates.txt
```

## The setup wizard cannot find repositories

Check:

- the GitHub App is installed on at least one repository
- the private key is from the same GitHub App as the App ID
- the GitHub API base URL is correct

The wizard will still work even if it finds no repositories; you can leave repo monitoring open or enter repo names later by editing `.env.local`.
