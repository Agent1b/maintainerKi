# Changelog

All notable maintainerKi release-facing changes should be summarized here.

The project currently targets a self-hosted beta release model.

## Unreleased

- Ongoing polish, docs, and release automation work for the public beta repository.

## v0.1.0-beta.1

- GitHub webhook intake with signature verification, repo filtering, and replay/idempotency handling
- Async worker flow with PostgreSQL + Redis-backed self-hosted deployment path
- Scoring provider abstraction with `mock`, `ollama`, and `mlx`
- Duplicate detection with dashboard visibility and optional GitHub duplicate comments
- Dashboard inbox, detail view, filtering, stats, and maintainer feedback loop
- Dashboard Playwright E2E coverage for login, inbox, detail, feedback, and logout
- Production-like Docker Compose smoke validation and release audit automation
- Source snapshot export, self-hosted docs, retention controls, and GitHub release workflow
