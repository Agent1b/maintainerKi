from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from server.models import Base, ContributionRecord, ScoringFeedbackRecord


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def clone_record(record: object, excluded_fields: set[str] | None = None) -> dict[str, object]:
    excluded_fields = excluded_fields or set()
    return {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
        if column.name not in excluded_fields
    }


def _target_has_existing_data(target_session: Session) -> bool:
    contribution_exists = target_session.scalar(select(ContributionRecord.id).limit(1)) is not None
    feedback_exists = target_session.scalar(select(ScoringFeedbackRecord.id).limit(1)) is not None
    return contribution_exists or feedback_exists


def migrate(
    source_sqlite_path: Path,
    target_database_url: str,
    *,
    force_reset_target: bool = False,
) -> tuple[int, int]:
    if not source_sqlite_path.exists():
        raise FileNotFoundError(f"SQLite source not found: {source_sqlite_path}")

    source_engine = create_engine(f"sqlite:///{source_sqlite_path}", future=True)
    target_engine = create_engine(normalize_database_url(target_database_url), future=True)

    if target_engine.dialect.name == "sqlite":
        raise RuntimeError("Target database must be PostgreSQL, not SQLite.")

    if force_reset_target:
        Base.metadata.drop_all(
            bind=target_engine,
            tables=[ScoringFeedbackRecord.__table__, ContributionRecord.__table__],
        )
    Base.metadata.create_all(bind=target_engine)

    contribution_id_map: dict[int, int] = {}

    with Session(source_engine) as source_session, Session(target_engine) as target_session:
        if not force_reset_target and _target_has_existing_data(target_session):
            raise RuntimeError(
                "Target PostgreSQL tables are not empty. Refusing to overwrite existing data. "
                "Use --force-reset-target only if you intentionally want to wipe target tables first."
            )

        source_contributions = source_session.scalars(
            select(ContributionRecord).order_by(ContributionRecord.id)
        ).all()
        for contribution in source_contributions:
            cloned = ContributionRecord(**clone_record(contribution, {"id"}))
            target_session.add(cloned)
            target_session.flush()
            contribution_id_map[contribution.id] = cloned.id

        source_feedback = source_session.scalars(
            select(ScoringFeedbackRecord).order_by(ScoringFeedbackRecord.id)
        ).all()
        for feedback in source_feedback:
            payload = clone_record(feedback, {"id", "contribution_id"})
            payload["contribution_id"] = contribution_id_map[feedback.contribution_id]
            target_session.add(ScoringFeedbackRecord(**payload))

        target_session.commit()

    return len(contribution_id_map), len(source_feedback)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy maintainerKi development data from local SQLite into PostgreSQL.",
    )
    parser.add_argument(
        "--source",
        default="maintainerki_dev.db",
        help="Path to the SQLite file to migrate from.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target PostgreSQL DATABASE_URL.",
    )
    parser.add_argument(
        "--force-reset-target",
        action="store_true",
        help="Dangerous: drop maintainerKi target tables before importing data.",
    )
    args = parser.parse_args()

    contributions, feedback = migrate(
        Path(args.source),
        args.target,
        force_reset_target=args.force_reset_target,
    )
    print(
        f"Migrated {contributions} contributions and {feedback} feedback entries "
        f"from {args.source} to PostgreSQL."
    )


if __name__ == "__main__":
    main()
