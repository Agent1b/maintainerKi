from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from server.config import settings
from server.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_database_backend_name: str | None = None
_using_sqlite_fallback = False

DEV_SQLITE_FALLBACK_URL = "sqlite:///./maintainerki_dev.db"


def _database_url_from_postgres_parts() -> str | None:
    host = os.getenv("POSTGRES_HOST", "").strip()
    user = os.getenv("POSTGRES_USER", "").strip()
    database = os.getenv("POSTGRES_DB", "").strip()
    if not host or not user or not database:
        return None

    password = os.getenv("POSTGRES_PASSWORD", "")
    port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
    safe_user = quote(user, safe="")
    safe_password = quote(password, safe="")
    safe_database = quote(database, safe="")
    auth = safe_user if password == "" else f"{safe_user}:{safe_password}"
    return f"postgresql+psycopg://{auth}@{host}:{port}/{safe_database}"


def _resolved_database_url() -> str:
    configured = settings.database_url.strip()
    if configured:
        if configured.startswith("postgresql://") and "+psycopg" not in configured:
            return configured.replace("postgresql://", "postgresql+psycopg://", 1)
        return configured
    postgres_fallback = _database_url_from_postgres_parts()
    if postgres_fallback:
        return postgres_fallback
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


def _engine_database_url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def run_database_migrations() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    app_tables = {"contributions", "scoring_feedback", "webhook_deliveries"}
    alembic_config = _build_alembic_config(_engine_database_url(engine))

    if "alembic_version" in table_names:
        command.upgrade(alembic_config, "head")
        return

    if table_names & app_tables:
        logger.info("Bootstrapping existing database into Alembic versioning.")
        Base.metadata.create_all(bind=engine)
        ensure_schema_upgrades()
        command.stamp(alembic_config, _get_alembic_bootstrap_revision(alembic_config))
        command.upgrade(alembic_config, "head")
        return

    logger.info("Applying initial Alembic migrations to empty database.")
    command.upgrade(alembic_config, "head")


def ensure_schema_upgrades() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "contributions" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("contributions")}
    feedback_columns = (
        {column["name"] for column in inspector.get_columns("scoring_feedback")}
        if "scoring_feedback" in table_names
        else set()
    )
    existing_column_types = {
        column["name"]: str(column["type"]).lower() for column in inspector.get_columns("contributions")
    }
    dialect = engine.dialect.name

    statements: list[str] = []

    def add_column(column_name: str, sqlite_type: str, postgres_type: str | None = None) -> None:
        if column_name in existing_columns:
            return
        column_type = sqlite_type if dialect == "sqlite" else (postgres_type or sqlite_type)
        statements.append(f"ALTER TABLE contributions ADD COLUMN {column_name} {column_type}")

    add_column("embedding_json", "TEXT")
    add_column("embedding_provider", "VARCHAR(64)")
    add_column("embedding_model", "VARCHAR(255)")
    add_column("duplicate_candidates_json", "TEXT")
    add_column("possible_duplicate", "BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE")
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

    if "scoring_feedback" in table_names and "actor_username" not in feedback_columns:
        statements.append("ALTER TABLE scoring_feedback ADD COLUMN actor_username VARCHAR(255)")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)

    _ensure_expected_indexes(engine)


def _build_alembic_config(database_url: str) -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "db_migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _get_alembic_bootstrap_revision(config: Config) -> str:
    return ScriptDirectory.from_config(config).get_base() or "head"


def _ensure_expected_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    existing_indexes = {
        table_name: {index["name"] for index in inspector.get_indexes(table_name)}
        for table_name in table_names
    }

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in table_names:
                continue

            known_indexes = existing_indexes.setdefault(table.name, set())
            for index in table.indexes:
                if not index.name or index.name in known_indexes:
                    continue
                index.create(bind=connection, checkfirst=True)
                known_indexes.add(index.name)


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
