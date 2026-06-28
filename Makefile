.PHONY: dev test infra-up infra-down migrate-dev-db dashboard-build dashboard-e2e prod-up prod-down hosted-config hosted-up hosted-down prod-smoke setup-wizard requeue-webhooks source-snapshot auth-secrets release-audit purge-old-data flask-webhook-test

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

dashboard-e2e:
	cd dashboard && npm run e2e

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

flask-webhook-test:
	./.venv/bin/python -m scripts.send_flask_fixture_webhooks --base-url "$${BASE_URL:-http://127.0.0.1:8000}"

setup-wizard:
	./.venv/bin/python -m scripts.setup_wizard

requeue-webhooks:
	./.venv/bin/python -m scripts.requeue_webhook_deliveries

source-snapshot:
	./.venv/bin/python -m scripts.export_source_snapshot

auth-secrets:
	./.venv/bin/python -m scripts.generate_admin_auth

release-audit:
	./.venv/bin/python -m scripts.release_audit

purge-old-data:
	./.venv/bin/python -m scripts.purge_old_data --apply
