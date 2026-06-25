from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ContributionRecord(Base):
    __tablename__ = "contributions"
    __table_args__ = (
        UniqueConstraint("repository", "kind", "number", name="uq_contribution_repo_kind_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    repository_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32))
    number: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(32), index=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completeness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suspicion_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintainer_override_labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scorer_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scorer_model: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duplicate_candidates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    possible_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    top_duplicate_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplicate_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ScoringFeedbackRecord(Base):
    __tablename__ = "scoring_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contribution_id: Mapped[int] = mapped_column(
        ForeignKey("contributions.id", ondelete="CASCADE"),
        index=True,
    )
    maintainer_action: Mapped[str] = mapped_column(String(32), index=True)
    correct_labels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class WebhookDeliveryRecord(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    event_name: Mapped[str] = mapped_column(String(64), index=True)
    repository: Mapped[str] = mapped_column(String(255), index=True)
    repository_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contribution_id: Mapped[int | None] = mapped_column(
        ForeignKey("contributions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
