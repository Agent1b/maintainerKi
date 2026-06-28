"""Initial maintainerKi schema.

Revision ID: 20260627_000001
Revises:
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260627_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contributions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("github_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("html_url", sa.String(length=1000), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("relevance_score", sa.Integer(), nullable=True),
        sa.Column("completeness_score", sa.Integer(), nullable=True),
        sa.Column("suspicion_score", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("suggested_labels_json", sa.Text(), nullable=True),
        sa.Column("maintainer_override_labels_json", sa.Text(), nullable=True),
        sa.Column("scorer_provider", sa.String(length=64), nullable=True),
        sa.Column("scorer_model", sa.String(length=1000), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("duplicate_candidates_json", sa.Text(), nullable=True),
        sa.Column("possible_duplicate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top_duplicate_similarity", sa.Float(), nullable=True),
        sa.Column("duplicate_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository", "kind", "number", name="uq_contribution_repo_kind_number"),
    )
    op.create_index("ix_contributions_content_fingerprint", "contributions", ["content_fingerprint"])
    op.create_index("ix_contributions_github_id", "contributions", ["github_id"])
    op.create_index("ix_contributions_kind", "contributions", ["kind"])
    op.create_index("ix_contributions_number", "contributions", ["number"])
    op.create_index("ix_contributions_overall_score", "contributions", ["overall_score"])
    op.create_index("ix_contributions_possible_duplicate", "contributions", ["possible_duplicate"])
    op.create_index("ix_contributions_received_at", "contributions", ["received_at"])
    op.create_index("ix_contributions_repository", "contributions", ["repository"])
    op.create_index("ix_contributions_repository_id", "contributions", ["repository_id"])
    op.create_index(
        "ix_contributions_repo_duplicate_received_at",
        "contributions",
        ["repository_id", "possible_duplicate", "received_at"],
    )
    op.create_index(
        "ix_contributions_repo_status_received_at",
        "contributions",
        ["repository_id", "status", "received_at"],
    )
    op.create_index("ix_contributions_status", "contributions", ["status"])

    op.create_table(
        "scoring_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contribution_id", sa.Integer(), nullable=False),
        sa.Column("maintainer_action", sa.String(length=32), nullable=False),
        sa.Column("actor_username", sa.String(length=255), nullable=True),
        sa.Column("correct_labels_json", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contribution_id"], ["contributions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scoring_feedback_actor_username", "scoring_feedback", ["actor_username"])
    op.create_index("ix_scoring_feedback_contribution_id", "scoring_feedback", ["contribution_id"])
    op.create_index("ix_scoring_feedback_created_at", "scoring_feedback", ["created_at"])
    op.create_index("ix_scoring_feedback_maintainer_action", "scoring_feedback", ["maintainer_action"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("event_name", sa.String(length=64), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("contribution_id", sa.Integer(), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["contribution_id"], ["contributions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id"),
    )
    op.create_index("ix_webhook_deliveries_content_fingerprint", "webhook_deliveries", ["content_fingerprint"])
    op.create_index("ix_webhook_deliveries_contribution_id", "webhook_deliveries", ["contribution_id"])
    op.create_index("ix_webhook_deliveries_delivery_id", "webhook_deliveries", ["delivery_id"])
    op.create_index("ix_webhook_deliveries_event_name", "webhook_deliveries", ["event_name"])
    op.create_index("ix_webhook_deliveries_kind", "webhook_deliveries", ["kind"])
    op.create_index("ix_webhook_deliveries_number", "webhook_deliveries", ["number"])
    op.create_index("ix_webhook_deliveries_processed_at", "webhook_deliveries", ["processed_at"])
    op.create_index("ix_webhook_deliveries_queued_at", "webhook_deliveries", ["queued_at"])
    op.create_index("ix_webhook_deliveries_repository", "webhook_deliveries", ["repository"])
    op.create_index("ix_webhook_deliveries_repository_id", "webhook_deliveries", ["repository_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index(
        "ix_webhook_deliveries_status_queued_at",
        "webhook_deliveries",
        ["status", "queued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status_queued_at", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_repository_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_repository", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_processed_at", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_queued_at", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_number", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_kind", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_event_name", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_delivery_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_contribution_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_content_fingerprint", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_scoring_feedback_maintainer_action", table_name="scoring_feedback")
    op.drop_index("ix_scoring_feedback_created_at", table_name="scoring_feedback")
    op.drop_index("ix_scoring_feedback_contribution_id", table_name="scoring_feedback")
    op.drop_index("ix_scoring_feedback_actor_username", table_name="scoring_feedback")
    op.drop_table("scoring_feedback")

    op.drop_index("ix_contributions_status", table_name="contributions")
    op.drop_index("ix_contributions_repo_status_received_at", table_name="contributions")
    op.drop_index("ix_contributions_repo_duplicate_received_at", table_name="contributions")
    op.drop_index("ix_contributions_repository_id", table_name="contributions")
    op.drop_index("ix_contributions_repository", table_name="contributions")
    op.drop_index("ix_contributions_received_at", table_name="contributions")
    op.drop_index("ix_contributions_possible_duplicate", table_name="contributions")
    op.drop_index("ix_contributions_overall_score", table_name="contributions")
    op.drop_index("ix_contributions_number", table_name="contributions")
    op.drop_index("ix_contributions_kind", table_name="contributions")
    op.drop_index("ix_contributions_github_id", table_name="contributions")
    op.drop_index("ix_contributions_content_fingerprint", table_name="contributions")
    op.drop_table("contributions")
