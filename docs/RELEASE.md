# maintainerKi Release Guide

Use this guide when preparing an open-source release for the self-hosted maintainerKi repo.

## Release goals

Each release should prove:

- the backend tests pass
- the dashboard lint/build passes
- the dashboard browser E2E pass
- the production-like Docker Compose smoke test passes in CI
- dependency audits are clean
- the hosted compose stack renders from example production settings
- the source snapshot contains only tracked Git files

## 1. Start from a clean working tree

Check:

```bash
git status --short
```

Do not release while `.env`, private keys, local databases, or machine-specific throwaway files are staged.

## 2. Run the release audit

```bash
make release-audit
```

That audit is the repo’s main pre-release gate for:

- backend tests
- dashboard lint/build
- Python dependency audit
- dashboard production dependency audit
- hosted compose config rendering
- tracked-file secret hygiene
- safe source snapshot export

CI also runs:

- dashboard Playwright E2E
- a production-like Compose boot + smoke flow with a stubbed GitHub App API

## 3. Review docs that commonly drift

Double-check:

- `README.md`
- `docs/INSTALLATION.md`
- `docs/CONFIGURATION.md`
- `docs/DEPLOYMENT.md`
- `docs/KNOWN_LIMITATIONS.md`

especially when changing:

- environment variables
- auth behavior
- deployment flow
- GitHub App requirements
- scoring providers

## 4. Create the source snapshot

```bash
make source-snapshot
```

This produces:

- `dist/maintainerki-source-snapshot.tar.gz`

That archive is built only from tracked Git files.

## 5. Tag and publish

Typical flow:

```bash
git add .
git commit -m "Release prep"
git tag v0.x.y
git push origin main --tags
```

Tag pushes trigger `.github/workflows/release.yml`, which reruns the release audit and publishes the tracked source snapshot as a GitHub release asset.

If you publish release artifacts, prefer:

- the Git tag / GitHub release source archive
- `dist/maintainerki-source-snapshot.tar.gz`

Do **not** publish a raw zip/tar of your working directory.

## 6. Post-release smoke checks

For a real hosted deployment, rerun:

```bash
export MAINTAINERKI_ADMIN_USERNAME="admin"
export MAINTAINERKI_ADMIN_PASSWORD="YOUR_PASSWORD"
export MAINTAINERKI_WEBHOOK_SECRET="YOUR_WEBHOOK_SECRET"
python -m scripts.production_smoke_test --base-url "https://YOUR_DOMAIN"
```

## Release checklist

- [ ] working tree reviewed
- [ ] `make release-audit` passes
- [ ] docs updated for behavior/config changes
- [ ] `make source-snapshot` succeeds
- [ ] release tag created from audited code
