# Security Policy

## Supported versions

maintainerKi is currently in beta for self-hosted single-admin use.

At the moment, security fixes should be assumed to target:

- the latest `main` branch
- the latest tagged beta release, when one exists

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a security vulnerability.

Instead, use a **private reporting path**:

- use [GitHub private vulnerability reporting](https://github.com/Agent1b/maintainerKi/security/advisories/new)
- if that form is unavailable, email **michbz@proton.me**

Please do not include secrets in an email subject line. You should receive an acknowledgement within seven days.

When reporting, include:

- affected component
- reproduction steps
- impact
- whether secrets, webhook verification, GitHub App auth, queueing, or dashboard rendering are involved

## Areas that deserve extra care

- GitHub webhook signature verification
- GitHub App private key handling
- secrets in `.env` files
- admin password hashes and session secrets
- dashboard rendering of user-supplied issue / PR content
- model/provider prompt handling and logging
- Docker deployment defaults
- retention windows, backups, and who can restore them

## Secret handling reminders

Do not commit:

- `.env`
- `.env.local`
- `.env.production`
- private key `.pem` files
- local databases
- copied plaintext admin passwords or session secrets from production env files

Use the example files in this repo instead:

- `.env.example`
- `.env.production.example`

## Privacy and retention

The repo ships with a documented retention policy and a purge helper:

- see [docs/PRIVACY_RETENTION.md](docs/PRIVACY_RETENTION.md)
- dry run: `./.venv/bin/python -m scripts.purge_old_data`
- apply: `make purge-old-data`
