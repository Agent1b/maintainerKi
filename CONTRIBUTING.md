# Contributing to maintainerKi

Thanks for taking a look at maintainerKi.

## Project shape

This project is currently:

- alpha / MVP
- self-hosted
- GitHub App based
- provider-flexible for local or remote model backends

Please keep contributions aligned with that scope unless an issue or discussion says otherwise.

## Good contribution types

- bug fixes
- tests
- docs improvements
- dashboard polish
- provider reliability improvements
- duplicate detection improvements
- setup / deployment fixes

## Before you open a pull request

### 1. Set up the project

Backend:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Optional semantic duplicate detection:

```bash
./.venv/bin/pip install -r requirements.semantic-duplicates.txt
```

Frontend:

```bash
cd dashboard
npm install
cd ..
```

### 2. Run the local checks

Backend tests:

```bash
./.venv/bin/pytest -q
```

Frontend build:

```bash
cd dashboard
npm run lint
npm run build
cd ..
```

### 3. Keep changes scoped

Please avoid mixing unrelated changes in one pull request.

Good:

- one bug fix
- one dashboard improvement
- one docs cleanup

Less good:

- refactor + feature + docs rewrite + deployment changes all in one PR

## Coding notes

- Prefer existing patterns already used in `server/`, `worker/`, and `dashboard/`
- Keep environment variable behavior documented when you add or change config
- Add tests for backend behavior changes when possible
- Avoid checking in secrets, private keys, local databases, or `.env` files

## Pull request checklist

- [ ] tests pass
- [ ] frontend lint/build pass if frontend changed
- [ ] docs updated if config or behavior changed
- [ ] no secrets or machine-specific paths were introduced

## Reporting bugs

When possible, include:

- what you expected
- what happened instead
- logs or tracebacks
- provider used (`mock`, `ollama`, `mlx`)
- whether you were using local dev, packaged compose, or hosted mode

## Large ideas

For big changes, please open an issue or discussion first so the implementation direction is clear before a large PR lands.
