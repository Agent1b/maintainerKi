.PHONY: dev test infra-up infra-down migrate-dev-db dashboard-build prod-up prod-down hosted-config hosted-up hosted-down prod-smoke setup-wizard requeue-webhooks source-snapshot

dev:
	./.venv/bin/uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

test:
	./.venv/bin/pytest -q

infra-up:
	docker compose up -d db redis

infra-down:
	docker compose stop db redis

migrate-dev-db:
	./.venv/bin/python -m scripts.migrate_sqlite_to_postgres --target "$$DATABASE_URL"

dashboard-build:
	cd dashboard && npm run build

prod-up:
	docker compose --env-file .env.production -f docker-compose.production.yml up -d --build

prod-down:
	docker compose --env-file .env.production -f docker-compose.production.yml down

hosted-config:
	docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml config

hosted-up:
	docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml up -d --build

hosted-down:
	docker compose --env-file .env.production -f docker-compose.production.yml -f docker-compose.hosted.yml down

prod-smoke:
	./.venv/bin/python -m scripts.production_smoke_test --base-url "$${BASE_URL:-http://127.0.0.1:8080}"

setup-wizard:
	./.venv/bin/python -m scripts.setup_wizard

requeue-webhooks:
	./.venv/bin/python -m scripts.requeue_webhook_deliveries

source-snapshot:
	./.venv/bin/python -m scripts.export_source_snapshot
