# Security Policy

## Supported versions

maintainerKi is currently in alpha.

At the moment, security fixes should be assumed to target:

- the latest `main` branch
- the latest unpublished local release state

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a security vulnerability.

Instead, report it privately to the project maintainer first through whatever private contact channel is listed on the repository profile or release notes.

When reporting, include:

- affected component
- reproduction steps
- impact
- whether secrets, webhook verification, GitHub App auth, queueing, or dashboard rendering are involved

## Areas that deserve extra care

- GitHub webhook signature verification
- GitHub App private key handling
- secrets in `.env` files
- dashboard rendering of user-supplied issue / PR content
- model/provider prompt handling and logging
- Docker deployment defaults

## Secret handling reminders

Do not commit:

- `.env`
- `.env.local`
- `.env.production`
- private key `.pem` files
- local databases

Use the example files in this repo instead:

- `.env.example`
- `.env.production.example`
