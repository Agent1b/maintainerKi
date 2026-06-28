from __future__ import annotations

from pathlib import Path

import yaml


def test_production_compose_runs_migrations_before_server_and_worker() -> None:
    compose = yaml.safe_load(Path("docker-compose.production.yml").read_text())
    services = compose["services"]

    migrate_service = services["migrate"]
    assert migrate_service["restart"] == "no"
    assert migrate_service["env_file"] == ["${MAINTAINERKI_ENV_FILE:-.env.production}"]
    assert migrate_service["depends_on"]["db"]["condition"] == "service_healthy"

    for service_name in ("db", "server", "worker"):
        assert services[service_name]["env_file"] == ["${MAINTAINERKI_ENV_FILE:-.env.production}"]

    for service_name in ("server", "worker"):
        assert (
            services[service_name]["depends_on"]["migrate"]["condition"]
            == "service_completed_successfully"
        )
