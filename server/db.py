from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from server.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_backend_name: str | None = None
_using_sqlite_fallback = False

DEV_SQLITE_FALLBACK_URL = "sqlite:///./maintainerki_dev.db"


def _resolved_database_url() -> str:
    configured = settings.database_url.strip()
    if configured:
        if configured.startswith("postgresql://") and "+psycopg" not in configured:
            return configured.replace("postgresql://", "postgresql+psycopg://", 1)
        return configured
    return DEV_SQLITE_FALLBACK_URL


def _make_engine(database_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        if database_url.startswith("sqlite:///./"):
            Path(database_url.removeprefix("sqlite:///./")).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        connect_args["check_same_thread"] = False
    return create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def init_database() -> None:
    global _database_backend_name, _engine, _session_factory, _using_sqlite_fallback

    if _engine is not None and _session_factory is not None:
        return

    database_url = _resolved_database_url()

    try:
        engine = _make_engine(database_url)
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        _using_sqlite_fallback = False
    except SQLAlchemyError as exc:
        if settings.app_env.lower() == "development" and not database_url.startswith("sqlite"):
            logger.warning(
                "Primary database unavailable; falling back to local SQLite for development. error=%s",
                exc,
            )
            engine = _make_engine(DEV_SQLITE_FALLBACK_URL)
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            _using_sqlite_fallback = True
        else:
            raise

    _engine = engine
    _database_backend_name = engine.dialect.name
    _session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    logger.info(
        "Database initialized. backend=%s fallback=%s",
        _database_backend_name,
        _using_sqlite_fallback,
    )


def get_engine() -> Engine:
    if _engine is None:
        init_database()
    assert _engine is not None
    return _engine


def get_database_status() -> dict[str, object]:
    engine = get_engine()
    return {
        "backend": _database_backend_name or engine.dialect.name,
        "using_sqlite_fallback": _using_sqlite_fallback,
        "url": str(engine.url).replace(engine.url.password or "", "***")
        if engine.url.password
        else str(engine.url),
    }


def ensure_schema_upgrades() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "contributions" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("contributions")}
    existing_column_types = {
        column["name"]: str(column["type"]).lower() for column in inspector.get_columns("contributions")
    }
    existing_indexes = {
        index["name"]
        for table in table_names
        for index in inspector.get_indexes(table)
    }
    dialect = engine.dialect.name

    statements: list[str] = []

    def add_column(column_name: str, sqlite_type: str, postgres_type: str | None = None) -> None:
        if column_name in existing_columns:
            return
        column_type = sqlite_type if dialect == "sqlite" else (postgres_type or sqlite_type)
        statements.append(f"ALTER TABLE contributions ADD COLUMN {column_name} {column_type}")

    def add_index(name: str, statement: str) -> None:
        if name in existing_indexes:
            return
        statements.append(statement)

    add_column("embedding_json", "TEXT")
    add_column("embedding_provider", "VARCHAR(64)")
    add_column("embedding_model", "VARCHAR(255)")
    add_column("duplicate_candidates_json", "TEXT")
    add_column("possible_duplicate", "BOOLEAN")
    add_column("top_duplicate_similarity", "FLOAT")
    add_column("duplicate_checked_at", "TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITH TIME ZONE")
    add_column("content_fingerprint", "VARCHAR(64)")
    add_column("maintainer_override_labels_json", "TEXT")

    if dialect == "postgresql":
        for column_name in ("repository_id", "github_id"):
            if column_name in existing_columns and "bigint" not in existing_column_types.get(column_name, ""):
                statements.append(
                    f"ALTER TABLE contributions ALTER COLUMN {column_name} TYPE BIGINT"
                )

    add_index(
        "ix_contributions_repository_id",
        "CREATE INDEX IF NOT EXISTS ix_contributions_repository_id ON contributions (repository_id)",
    )
    add_index(
        "ix_contributions_content_fingerprint",
        "CREATE INDEX IF NOT EXISTS ix_contributions_content_fingerprint ON contributions (content_fingerprint)",
    )
    add_index(
        "ix_contributions_repo_status_received_at",
        "CREATE INDEX IF NOT EXISTS ix_contributions_repo_status_received_at ON contributions (repository_id, status, received_at)",
    )
    add_index(
        "ix_contributions_repo_duplicate_received_at",
        "CREATE INDEX IF NOT EXISTS ix_contributions_repo_duplicate_received_at ON contributions (repository_id, possible_duplicate, received_at)",
    )

    if "webhook_deliveries" in table_names:
        add_index(
            "ix_webhook_deliveries_status_queued_at",
            "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_status_queued_at ON webhook_deliveries (status, queued_at)",
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


@contextmanager
def session_scope() -> Iterator[Session]:
    if _session_factory is None:
        init_database()
    assert _session_factory is not None

    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
