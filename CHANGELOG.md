# Changelog

All notable maintainerKi release-facing changes should be summarized here.

The project currently targets a self-hosted beta release model.

## Unreleased

- Ongoing polish, docs, and release automation work for the public beta repository.

## v0.1.0-beta.3

- Fixed the hosted production-smoke GitHub App key permissions for the non-root application container
- Added a regression contract for the ephemeral CI key mount
- Validated the complete public GitHub CI path, including Dashboard E2E and the production-like Docker Compose smoke test

## v0.1.0-beta.2

- Fixed GitHub Actions Dashboard E2E startup by resolving the backend Python executable from the absolute workspace path
- Added workflow regression coverage for the E2E virtualenv contract
- Marked hyphenated release tags, including beta versions, as GitHub prereleases automatically

## v0.1.0-beta.1

- GitHub webhook intake with signature verification, repo filtering, and replay/idempotency handling
- Durable webhook claiming/retry recovery and stale-event result protection
- Async worker flow with PostgreSQL + Redis-backed self-hosted deployment path
- Scoring provider abstraction with `mock`, `ollama`, and `mlx`
- Contributor velocity/history scoring context and opt-in GitHub account/diff enrichment
- Duplicate detection with dashboard visibility and optional GitHub duplicate comments
- Default-off GitHub write-back restricted to deterministic `maintainerki:*` labels
- Dashboard inbox, detail view, filtering, stats, and maintainer feedback loop
- Dashboard Playwright E2E coverage for login, inbox, detail, feedback, and logout
- Production-like Docker Compose smoke validation and release audit automation
- Source snapshot export, self-hosted docs, retention controls, and GitHub release workflow
- Fail-closed production container defaults and least-privilege GitHub App documentation
