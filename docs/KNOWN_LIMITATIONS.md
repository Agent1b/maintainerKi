# maintainerKi Known Limitations

maintainerKi is a **beta self-hosted maintainer tool** for the single-admin workflow, but it still has intentional scope boundaries and operator responsibility.

## Product scope limits

- maintainerKi is **not** a public multi-tenant SaaS
- maintainerKi is **not** GitHub Marketplace-ready
- maintainerKi is **not** a fully autonomous moderation system
- maintainers remain the final decision-maker for triage and label overrides

## Auth and access model

- the hosted dashboard supports a **single-admin login**
- it does **not** yet support:
  - multiple user accounts
  - team roles or permissions
  - per-repo access control inside the dashboard
  - SSO / OAuth / enterprise identity providers

For shared or internet-exposed deployments, treat the product as a private admin console unless you add stronger access control in front of it.

## Deployment model

- the recommended production path is one self-hosted deployment per maintainer or team
- production guidance assumes:
  - Docker Compose
  - PostgreSQL
  - Redis
  - one GitHub App owned by the maintainer or team

It is not yet optimized for:

- large multi-org hosted fleets
- automatic blue/green deployment orchestration
- centralized multi-instance admin operations

## AI and scoring limits

- scoring quality depends on the configured provider and model
- local models may be slower or less consistent than paid remote providers
- maintainerKi does not yet learn online from feedback in a closed-loop retraining system
- threshold tuning is still a human-operated task

## Duplicate detection limits

- the default hashing-based duplicate detection is lightweight, but less semantically rich than embedding-based matching
- semantic duplicate detection may require heavier local dependencies and first-run model downloads
- very large repositories may eventually need a stronger vector-search storage/indexing strategy

## Operational limits

- deployment docs and smoke tests are provided, but real-world production trust still depends on dogfooding on your own repositories
- backup, restore, rollback, and incident handling are documented for self-hosters, not managed by a hosted maintainerKi service
- privacy retention is configurable, but operators still own backup retention and restore access
- release confidence is strongest when you run `make release-audit` before publishing changes

## Open-source release limits

- the repo is ready to be published as a **beta** open-source self-hosted product
- published releases should come from tracked Git files or `make source-snapshot`
- you should never publish raw workspace archives that may contain local secrets, databases, or private keys
