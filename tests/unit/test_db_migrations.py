from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from server import db as db_module
from server.db import get_engine, init_database, run_database_migrations
from server.models import Base


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def _create_legacy_pre_alembic_schema() -> None:
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE contributions (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                repository VARCHAR(255) NOT NULL,
                repository_id INTEGER,
                github_id INTEGER,
                kind VARCHAR(32) NOT NULL,
                action VARCHAR(32) NOT NULL,
                number INTEGER NOT NULL,
                title VARCHAR(500) NOT NULL,
                body TEXT NOT NULL,
                author VARCHAR(255),
                sender VARCHAR(255),
                html_url VARCHAR(1000),
                status VARCHAR(32) NOT NULL,
                quality_score INTEGER,
                relevance_score INTEGER,
                completeness_score INTEGER,
                suspicion_score INTEGER,
                overall_score INTEGER,
                ai_summary TEXT,
                suggested_labels_json TEXT,
                scorer_provider VARCHAR(64),
                scorer_model VARCHAR(1000),
                prompt_version VARCHAR(64),
                error_message TEXT,
                received_at DATETIME NOT NULL,
                scored_at DATETIME,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_contribution_repo_kind_number UNIQUE (repository, kind, number)
            )
            """
        )
        for statement in (
            "CREATE INDEX ix_contributions_repository ON contributions (repository)",
            "CREATE INDEX ix_contributions_github_id ON contributions (github_id)",
            "CREATE INDEX ix_contributions_kind ON contributions (kind)",
            "CREATE INDEX ix_contributions_number ON contributions (number)",
            "CREATE INDEX ix_contributions_overall_score ON contributions (overall_score)",
            "CREATE INDEX ix_contributions_status ON contributions (status)",
            """
            CREATE TABLE scoring_feedback (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                contribution_id INTEGER NOT NULL,
                maintainer_action VARCHAR(32) NOT NULL,
                correct_labels_json TEXT,
                notes TEXT,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(contribution_id) REFERENCES contributions (id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX ix_scoring_feedback_contribution_id ON scoring_feedback (contribution_id)",
            "CREATE INDEX ix_scoring_feedback_maintainer_action ON scoring_feedback (maintainer_action)",
            "CREATE INDEX ix_scoring_feedback_created_at ON scoring_feedback (created_at)",
        ):
            connection.exec_driver_sql(statement)


def _contribution_column(inspector, name: str) -> dict[str, object]:
    return next(column for column in inspector.get_columns("contributions") if column["name"] == name)


def test_run_database_migrations_creates_schema_for_empty_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_migration_empty.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")

    _reset_database_state()
    init_database()
    run_database_migrations()

    inspector = inspect(get_engine())
    table_names = set(inspector.get_table_names())
    assert {"alembic_version", "contributions", "scoring_feedback", "webhook_deliveries"} <= table_names
    feedback_columns = {column["name"] for column in inspector.get_columns("scoring_feedback")}
    assert "actor_username" in feedback_columns
    contribution_indexes = {index["name"] for index in inspector.get_indexes("contributions")}
    assert {
        "ix_contributions_possible_duplicate",
        "ix_contributions_received_at",
        "ix_contributions_repo_duplicate_received_at",
        "ix_contributions_repo_status_received_at",
    } <= contribution_indexes


def test_run_database_migrations_bootstraps_existing_pre_alembic_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_migration_existing.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")

    _reset_database_state()
    init_database()
    _create_legacy_pre_alembic_schema()

    version_before = inspect(get_engine()).get_table_names()
    assert "alembic_version" not in version_before

    run_database_migrations()

    inspector = inspect(get_engine())
    assert "alembic_version" in inspector.get_table_names()
    contribution_indexes = {index["name"] for index in inspector.get_indexes("contributions")}
    assert {
        "ix_contributions_possible_duplicate",
        "ix_contributions_received_at",
        "ix_contributions_repo_duplicate_received_at",
        "ix_contributions_repo_status_received_at",
    } <= contribution_indexes
    webhook_indexes = {index["name"] for index in inspector.get_indexes("webhook_deliveries")}
    assert {
        "ix_webhook_deliveries_processed_at",
        "ix_webhook_deliveries_status_queued_at",
    } <= webhook_indexes
    possible_duplicate = _contribution_column(inspector, "possible_duplicate")
    assert possible_duplicate["nullable"] is False
    assert str(possible_duplicate["default"]).lower() in {"0", "false"}
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260627_000001"


def test_run_database_migrations_restores_missing_indexes_for_legacy_schema(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_migration_missing_indexes.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")

    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    with get_engine().begin() as connection:
        for table_name in ("contributions", "scoring_feedback", "webhook_deliveries"):
            for index in inspect(get_engine()).get_indexes(table_name):
                connection.exec_driver_sql(f"DROP INDEX {index['name']}")

    run_database_migrations()

    inspector = inspect(get_engine())
    contribution_indexes = {index["name"] for index in inspector.get_indexes("contributions")}
    assert {
        "ix_contributions_possible_duplicate",
        "ix_contributions_received_at",
        "ix_contributions_repo_duplicate_received_at",
        "ix_contributions_repo_status_received_at",
    } <= contribution_indexes
