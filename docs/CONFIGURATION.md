# maintainerKi Configuration Guide

maintainerKi reads environment variables from:

1. the process environment
2. `.env`
3. `.env.local`

`.env.local` is loaded after `.env`, so it is the easiest place for machine-specific overrides.

## GitHub App settings

Minimum GitHub App requirements:

- Repository permissions:
  - Pull requests: **Read-only**
  - Issues: **Read and write**
  - Metadata: **Read-only**
- Webhook event subscriptions:
  - **Pull request**
  - **Issues**

- `GITHUB_WEBHOOK_SECRET`
  - shared secret used to verify GitHub webhook signatures
- `GITHUB_APP_ID`
  - numeric GitHub App ID
- `GITHUB_PRIVATE_KEY_PATH`
  - path to the GitHub App private key `.pem`
- `GITHUB_API_BASE_URL`
  - defaults to `https://api.github.com`
- `GITHUB_LABEL_WRITEBACK_ENABLED`
  - defaults to `false`; opt in to writing the fixed `maintainerki:*` triage labels back to GitHub
  - free-form labels suggested by a scoring model are never written automatically
- `GITHUB_AUTO_CREATE_LABELS`
  - defaults to `false`; if explicitly enabled, missing approved `maintainerki:*` labels are created automatically
- `GITHUB_DUPLICATE_COMMENTS_ENABLED`
  - defaults to `false`; if explicitly enabled together with write-back, likely duplicates get a GitHub comment listing similar items

## Repository monitoring

- `MONITORED_REPOSITORIES`
  - comma-separated `owner/repo` names
  - if blank, maintainerKi accepts webhook events from every repo where the app is installed
  - if set, unlisted repositories are ignored at webhook time

Example:

```env
MONITORED_REPOSITORIES=octo-org/docs,octo-org/cli
```

## Scoring provider

- `SCORER_PROVIDER`
  - `mock`
  - `ollama`
  - `mlx`
- `SCORER_TIMEOUT_SECONDS`
- `SCORER_TEMPERATURE`

### Ollama

- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_TEMPERATURE`
- `OLLAMA_KEEP_ALIVE`

### MLX

- `MLX_COMMAND`
- `MLX_MODEL_PATH`
- `MLX_MAX_TOKENS`
- `MLX_USE_DEFAULT_CHAT_TEMPLATE`

### Scoring enrichment

Before scoring, each contribution is enriched with context so the model judges more than the description text:

- `GITHUB_ENRICHMENT_ENABLED` (default `false`) — opt in to fetching the author's account age and, for pull requests, the changed-file list and a diff excerpt from the GitHub API. It requires GitHub App credentials and adds synchronous API work to each scoring job. When disabled or unconfigured, scoring proceeds with database-derived context only. Enrichment failures never block scoring.
- `PR_DIFF_MAX_FILES` (default `20`) — maximum changed files fetched per pull request.
- `PR_DIFF_EXCERPT_MAX_CHARS` (default `5000`) — cap on the diff excerpt included in the scoring prompt.

Submission-velocity guard (works even with API enrichment disabled — it only uses the local database):

- `VELOCITY_WINDOW_HOURS` (default `24`) — window for counting recent submissions by the same author across all monitored repositories.
- `VELOCITY_SUSPICION_COUNT_THRESHOLD` (default `10`) — at this many submissions inside the window, the suspicion score is deterministically raised to the floor below, regardless of what the model returned. This catches floods of individually plausible-looking contributions.
- `VELOCITY_SUSPICION_FLOOR` (default `70`) — the minimum suspicion score applied to flooding authors. With the default thresholds this triggers the `maintainerki:suspicious` label.

## Duplicate detection

- `INSTALL_SEMANTIC_DUPLICATES`
  - production Docker build arg
  - if `true`, the Docker image installs `requirements.semantic-duplicates.txt`
- `DUPLICATE_EMBEDDING_PROVIDER`
- `DUPLICATE_EMBEDDING_MODEL`
- `DUPLICATE_SIMILARITY_THRESHOLD`
- `DUPLICATE_MAX_CANDIDATES`
- `DUPLICATE_LABEL_NAME`

On each incoming event, detection compares the new contribution against every stored embedding for that repository — a linear scan computed in Python. That is comfortable for repositories with up to a few thousand scored contributions. pgvector is the planned scale path.

## Queue and database

- `DATABASE_URL`
- `REDIS_URL`
- `QUEUE_PROVIDER`
- `CELERY_ENABLED`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CELERY_TASK_ALWAYS_EAGER`

### Delivery reliability tuning

- `WEBHOOK_PROCESSING_STALE_SECONDS` (default `900`) — a webhook delivery stuck in `processing` longer than this (for example because a worker crashed mid-scoring) becomes claimable again and is picked up by the retry sweep. Set it comfortably above your slowest expected scoring run.
- `GITHUB_READINESS_CACHE_SECONDS` (default `300`) — how long `/readyz` caches a successful GitHub App authentication check before making a fresh API call. Failures are cached for 30 seconds regardless, so recovery is quick.
- `GITHUB_READINESS_TIMEOUT_SECONDS` (default `5`) — hard time budget for the GitHub call made by `/readyz`, independent of the (longer) label writeback timeout. Keep it below your load balancer's probe timeout.

## Dashboard/API

- `DASHBOARD_ALLOWED_ORIGINS`
- `DASHBOARD_BIND_ADDRESS`
- `DASHBOARD_PORT`
- `HOST`
- `PORT`
- `LOG_LEVEL`
- `ADMIN_AUTH_ENABLED`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH`
- `SESSION_SECRET`
- `SESSION_NOT_BEFORE_EPOCH`
- `SESSION_COOKIE_NAME`
- `SESSION_TTL_SECONDS`
- `SESSION_COOKIE_SECURE`
- `LOGIN_RATE_LIMIT_ATTEMPTS`
- `LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `LOGIN_RATE_LIMIT_BLOCK_SECONDS`
- `WEBHOOK_RATE_LIMIT_REQUESTS`
- `WEBHOOK_RATE_LIMIT_WINDOW_SECONDS`
- `DEBUG_API_ENABLED`
- `TRUSTED_HOSTS`

For the hosted production path, the recommended default is:

- `ADMIN_AUTH_ENABLED=true`
- `ADMIN_PASSWORD_HASH` generated with `make auth-secrets`
- `SESSION_SECRET` generated with `make auth-secrets`
- `TRUSTED_HOSTS=maintainerki.example.com,localhost,127.0.0.1`

`ADMIN_PASSWORD` exists as a local/testing fallback, but `ADMIN_PASSWORD_HASH` is the recommended production path.
`make auth-secrets` prints `ADMIN_PASSWORD_HASH` and `SESSION_SECRET` already quoted for safe use in Compose-managed env files.

`SESSION_NOT_BEFORE_EPOCH` is an emergency “invalidate every existing session before this timestamp” switch.

## Single-process constraints

maintainerKi is designed to run as one server process per deployment. Three pieces of state live in process memory rather than in a shared store:

- the login rate limiter
- the GitHub App installation token cache
- the debug scoring buffer

Running multiple server replicas or multiple uvicorn workers is not currently supported: each process keeps its own copies, so login rate limits are effectively divided by the number of processes and each process fetches its own installation tokens. Supporting multiple processes would first require moving this state to a shared store such as Redis.

## Abuse and privacy controls

- `WEBHOOK_RETENTION_DAYS`
  - delete old webhook delivery rows after this many days
- `CONTRIBUTION_BODY_RETENTION_DAYS`
  - scrub old contribution bodies, embeddings, and duplicate snapshots after this many days
- `FEEDBACK_NOTE_RETENTION_DAYS`
  - scrub old maintainer feedback notes after this many days

See also:

- `docs/PRIVACY_RETENTION.md`

## Hosted HTTPS deployment

- `APP_DOMAIN`
  - public hostname for the Caddy-based hosted deployment
- `ACME_EMAIL`
  - email Caddy uses for certificate registration and renewal notices

The hosted deployment uses:

- `docker-compose.hosted.yml`
- `docker/caddy/Caddyfile`

Keep `DASHBOARD_BIND_ADDRESS=127.0.0.1` unless you deliberately want the raw dashboard port exposed on the host.

`DEBUG_API_ENABLED` defaults to:

- `true` in development
- `false` outside development unless explicitly enabled

Leave it disabled for public or shared deployments.

The hosted deployment protects the dashboard/API with the built-in single-admin login flow. That is enough for a private maintainer console, but it is still not full multi-user auth.

If you use `docker compose --env-file SOME_OTHER_FILE ...`, also set:

```bash
export MAINTAINERKI_ENV_FILE=SOME_OTHER_FILE
```

so the same env file is injected into the production containers.

## Score threshold tuning

These thresholds are used when translating model scores into labels:

- `SUSPICIOUS_SCORE_THRESHOLD`
  - default: `70`
  - if suspicion is at or above this value, `maintainerki:suspicious` is applied
- `NEEDS_INFO_COMPLETENESS_THRESHOLD`
  - default: `40`
  - if completeness is below this value, `maintainerki:needs-info` is applied
- `REVIEW_FIRST_THRESHOLD`
  - default: `80`
  - if overall score is at or above this value, `maintainerki:review-first` is applied
- `WORTH_A_LOOK_THRESHOLD`
  - default: `55`
  - if overall score is below `REVIEW_FIRST_THRESHOLD` but at or above this value, `maintainerki:worth-a-look` is applied

`WORTH_A_LOOK_THRESHOLD` should never be greater than `REVIEW_FIRST_THRESHOLD`.

## Recommended starting profiles

### Conservative triage

```env
SUSPICIOUS_SCORE_THRESHOLD=80
NEEDS_INFO_COMPLETENESS_THRESHOLD=35
REVIEW_FIRST_THRESHOLD=85
WORTH_A_LOOK_THRESHOLD=60
```

### Aggressive spam filtering

```env
SUSPICIOUS_SCORE_THRESHOLD=60
NEEDS_INFO_COMPLETENESS_THRESHOLD=45
REVIEW_FIRST_THRESHOLD=80
WORTH_A_LOOK_THRESHOLD=50
```

## Production compose notes

The production stack expects:

- `GITHUB_PRIVATE_KEY_HOST_PATH` = absolute path on the host
- `GITHUB_PRIVATE_KEY_PATH` = path inside the container

Example:

```env
GITHUB_PRIVATE_KEY_HOST_PATH=/opt/maintainerki/secrets/app.private-key.pem
GITHUB_PRIVATE_KEY_PATH=/run/secrets/maintainerki.private-key.pem
```

## Optional semantic duplicate detection

Local install:

```bash
./.venv/bin/pip install -r requirements.semantic-duplicates.txt
```

Production compose:

```env
INSTALL_SEMANTIC_DUPLICATES=true
DUPLICATE_EMBEDDING_PROVIDER=sentence-transformers
```
