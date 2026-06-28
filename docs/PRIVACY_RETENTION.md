# maintainerKi Privacy and Retention

maintainerKi is a self-hosted maintainer tool, so the operator controls storage, backups, and retention.

This document describes the default data-retention posture shipped with the repo.

## What maintainerKi stores

By default, maintainerKi stores:

- contribution metadata:
  - repository
  - issue/PR number
  - GitHub IDs
  - title
  - author and sender usernames
  - URLs
  - score outputs and labels
- contribution bodies
- duplicate-detection artifacts:
  - embeddings
  - duplicate candidate snapshots
- maintainer feedback:
  - action
  - corrected labels
  - optional notes
  - `actor_username` for feedback actions
- webhook delivery rows and normalized payload snapshots
- auth event logs and operator-visible application logs may include:
  - admin username
  - client IP address
  - timestamps
- in-memory rate-limit state uses client IP addresses transiently for login and webhook abuse controls

## Default retention windows

The shipped defaults are:

- `WEBHOOK_RETENTION_DAYS=30`
  - old webhook delivery records are deleted
- `CONTRIBUTION_BODY_RETENTION_DAYS=90`
  - old contribution `body` values are scrubbed
  - old stored embeddings are scrubbed
  - old duplicate-candidate snapshots are scrubbed
- `FEEDBACK_NOTE_RETENTION_DAYS=365`
  - old maintainer feedback notes are scrubbed
  - feedback action, labels, timestamps, and actor username remain for auditability

These values can be changed in `.env`, `.env.local`, or `.env.production`.

## What is intentionally retained longer

maintainerKi keeps a smaller operational record even after retention jobs run:

- contribution title
- repository and GitHub identifiers
- score outputs
- applied / suggested labels
- maintainer feedback action
- feedback actor username
- timestamps

That retained subset is what keeps the dashboard, metrics, and feedback history useful after raw text is scrubbed.

## What the purge job does not remove

The purge job does **not** delete:

- application logs written by the process, container runtime, reverse proxy, or host OS
- operator-managed backup archives
- transient in-memory rate-limit state that exists only until process restart or window expiry

If you log to files, a central log collector, or a hosted observability stack, log retention is operator-owned and should be reviewed separately from the maintainerKi purge schedule.

## Running the purge job

Dry run:

```bash
./.venv/bin/python -m scripts.purge_old_data
```

Apply:

```bash
make purge-old-data
```

The dry run prints the configured windows and how many rows or fields will be touched.

## Recommended cadence

For a self-hosted production deployment, run the purge job daily with cron or your preferred scheduler.

Example:

```bash
0 3 * * * cd /opt/maintainerki && docker compose --env-file .env.production -f docker-compose.production.yml exec -T server python -m scripts.purge_old_data --apply
```

## Backups and deletion expectations

Retention only affects live application data. It does not rewrite old backups.

If you need stronger deletion guarantees:

- shorten backup retention
- encrypt backups
- keep backups in a private location
- document who can restore them

## Operator guidance

If you are using maintainerKi for private or sensitive repositories, review and tune:

- retention windows
- backup retention
- log retention
- who can access Postgres backups
- who can access `.env.production` and GitHub App private keys
