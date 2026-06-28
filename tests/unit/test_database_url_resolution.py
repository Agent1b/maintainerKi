from __future__ import annotations

from server import db as db_module
from sqlalchemy import create_engine


def test_resolved_database_url_uses_postgres_env_parts(monkeypatch) -> None:
    monkeypatch.setattr("server.db.settings.database_url", "")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "maintainerki")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pa$$ word:/@")
    monkeypatch.setenv("POSTGRES_DB", "maintainerki-prod")

    resolved = db_module._resolved_database_url()

    assert resolved == (
        "postgresql+psycopg://maintainerki:pa%24%24%20word%3A%2F%40@db:5432/maintainerki-prod"
    )


def test_resolved_database_url_prefers_explicit_database_url(monkeypatch) -> None:
    monkeypatch.setattr("server.db.settings.database_url", "postgresql://user:pass@db:5432/app")
    monkeypatch.setenv("POSTGRES_HOST", "ignored-db")
    monkeypatch.setenv("POSTGRES_USER", "ignored-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ignored-password")
    monkeypatch.setenv("POSTGRES_DB", "ignored-db-name")

    resolved = db_module._resolved_database_url()

    assert resolved == "postgresql+psycopg://user:pass@db:5432/app"


def test_engine_database_url_preserves_password_for_alembic() -> None:
    engine = create_engine("postgresql+psycopg://maintainerki:secret-pass@db:5432/app")

    rendered = db_module._engine_database_url(engine)

    assert rendered == "postgresql+psycopg://maintainerki:secret-pass@db:5432/app"
