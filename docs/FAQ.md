# maintainerKi FAQ

## Does maintainerKi auto-close issues or PRs?

No. It only scores, sorts, and suggests. The maintainer still decides what to do.

## Do I need to host my own model?

No, but you need some scoring provider.

Current providers in the MVP:

- `mock`
- `ollama`
- `mlx`

`mock` is good for smoke tests, not real triage.

For semantic duplicate detection, install:

```bash
./.venv/bin/pip install -r requirements.semantic-duplicates.txt
```

## Can I run maintainerKi on one repository only?

Yes.

Use the setup wizard or set:

```env
MONITORED_REPOSITORIES=owner/repo
```

## Can I monitor every repository where the app is installed?

Yes.

Leave `MONITORED_REPOSITORIES` blank.

## Does maintainerKi require PostgreSQL?

For real packaged deployments, yes.

During development, the app can fall back to local SQLite if Postgres is missing, but production should use Postgres.

## Why is there both `.env` and `.env.local`?

- `.env` is your base configuration
- `.env.local` is for machine-specific or wizard-generated overrides

`.env.local` wins if the same key exists in both files.

## Can I run the dashboard without nginx?

Yes in development.

Use Vite:

```bash
cd dashboard
npm run dev
```

The production compose stack uses nginx because it serves the built dashboard and proxies `/api` and `/webhooks` to the FastAPI server.

## Can I use maintainerKi without GitHub label write-back?

Yes.

Set:

```env
GITHUB_LABEL_WRITEBACK_ENABLED=false
```

You will still get scored records in the dashboard.

## Can I put the hosted deployment on the public internet?

You can self-host it, but the current hosted deployment does **not** include end-user authentication.

So today it is better treated as:

- an internal tool
- a private admin dashboard
- a trusted self-hosted service

If you want a true public-facing hosted product, auth still needs to be built.

## What happens if my model or queue is down?

- if the queue is unavailable, maintainerKi can fall back to in-process scoring
- if the scoring provider fails, the contribution is marked as failed instead of crashing the whole app

## Is this already marketplace-ready?

Not yet.

This MVP is for self-hosting and testing on real repos before a broader public release.

## Why is the production dashboard bound to 127.0.0.1 by default?

Because the recommended hosted setup puts Caddy in front of maintainerKi.

That way:

- raw dashboard nginx is not directly exposed
- HTTPS termination happens in one place
- GitHub webhooks and browser traffic share the same public origin

If you want the direct dashboard port exposed on the server, change:

- `DASHBOARD_BIND_ADDRESS`

in `.env.production`, but the safer default is to leave it on loopback.
