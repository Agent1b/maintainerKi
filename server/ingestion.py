from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from server.config import settings
from server.duplicates.detector import detect_duplicates
from server.duplicates.embedder import DuplicateEmbeddingError
from server.enrichment import enrich_contribution
from server.github_client import GitHubWritebackError, apply_score_labels, build_github_client
from server.repository import (
    claim_webhook_delivery,
    current_contribution_snapshot,
    list_retriable_webhook_delivery_ids,
    mark_webhook_delivery_failed,
    mark_webhook_delivery_processed,
    mark_webhook_delivery_queue_failed,
    mark_webhook_delivery_queued,
    persist_failed_contribution,
    persist_scored_contribution,
)
from server.scorer.models import ContributionInput
from server.scorer.providers import ScoringProviderError
from server.scorer.quality import score_contribution
from server.scoring_store import record_scoring_result

logger = logging.getLogger(__name__)

DUPLICATE_COMMENT_MARKER = "<!-- maintainerki:possible-duplicate -->"


def enqueue_webhook_delivery(delivery_id: str) -> bool:
    if _queue_expected():
        # Mark the delivery queued before dispatch so a fast worker that claims and
        # finishes the job first can't have its "processing"/"processed" status
        # clobbered back to "queued" by this call landing afterwards.
        mark_webhook_delivery_queued(delivery_id)
        if _enqueue_with_celery(delivery_id):
            return True
        mark_webhook_delivery_queue_failed(
            delivery_id,
            "Queue unavailable; delivery persisted and can be retried later.",
        )
        logger.error(
            "Webhook delivery %s was accepted but not queued because the Celery broker was unavailable.",
            delivery_id,
        )
        return False

    process_webhook_delivery(delivery_id)
    return True


# Backward-compatible helper for direct/local callers.
def enqueue_contribution_event(event: dict[str, Any]) -> None:
    process_contribution_event(event)


def process_webhook_delivery(delivery_id: str) -> None:
    event = claim_webhook_delivery(delivery_id)
    if event is None:
        logger.info("Webhook delivery %s was already handled or does not exist.", delivery_id)
        return

    try:
        process_contribution_event(event)
    except Exception as exc:
        mark_webhook_delivery_failed(delivery_id, f"{exc.__class__.__name__}: {exc}")
        raise
    else:
        mark_webhook_delivery_processed(delivery_id)


def requeue_persisted_deliveries(limit: int = 100) -> int:
    count = 0
    for delivery_id in list_retriable_webhook_delivery_ids(limit=limit):
        enqueue_webhook_delivery(delivery_id)
        count += 1
    return count


def process_contribution_event(event: dict[str, Any]) -> None:
    logger.info(
        "Processing %s #%s for %s by %s",
        event["kind"],
        event["number"],
        event["repository"],
        event["author"],
    )

    contribution = ContributionInput.from_event(event)
    contribution = enrich_contribution(contribution)
    try:
        score = score_contribution(contribution)
        embedding_result = None
        duplicate_result = None
        try:
            embedding_result, duplicate_result = detect_duplicates(contribution)
        except DuplicateEmbeddingError as exc:
            logger.exception(
                "Duplicate detection failed for %s #%s in %s: %s",
                event["kind"],
                event["number"],
                event["repository"],
                exc,
            )

        if duplicate_result and duplicate_result.possible_duplicate:
            duplicate_label = settings.duplicate_label_name.strip()
            if duplicate_label and duplicate_label not in score.suggested_labels:
                score.suggested_labels.append(duplicate_label)

        try:
            persisted = persist_scored_contribution(
                event,
                score,
                embedding_result=embedding_result,
                duplicate_result=duplicate_result,
            )
        except SQLAlchemyError:
            logger.exception(
                "Database persistence failed for scored %s #%s in %s; skipping label "
                "writeback and letting the caller mark the delivery failed for retry.",
                event["kind"],
                event["number"],
                event["repository"],
            )
            raise
        if not persisted:
            logger.info(
                "Discarding stale scoring result for %s #%s in %s because a newer "
                "webhook snapshot is already registered.",
                event["kind"],
                event["number"],
                event["repository"],
            )
            return
        with current_contribution_snapshot(event) as is_current:
            if not is_current:
                logger.info(
                    "Skipping stale side effects for %s #%s in %s because a newer "
                    "webhook snapshot is already registered.",
                    event["kind"],
                    event["number"],
                    event["repository"],
                )
                return
            record_scoring_result(
                {
                    "status": "scored",
                    "repository": event["repository"],
                    "kind": event["kind"],
                    "number": event["number"],
                    "title": event["title"],
                    "score": score.model_dump(),
                    "duplicates": duplicate_result.model_dump() if duplicate_result else None,
                }
            )
            writeback_applied = False
            try:
                github_client = build_github_client()
                writeback_applied = apply_score_labels(
                    event,
                    score,
                    possible_duplicate=bool(
                        duplicate_result and duplicate_result.possible_duplicate
                    ),
                    client=github_client,
                )
                if (
                    writeback_applied
                    and duplicate_result
                    and duplicate_result.possible_duplicate
                    and settings.github_duplicate_comments_enabled
                    and github_client.is_configured()
                ):
                    github_client.create_issue_comment(
                        repository_full_name=event["repository"] or "unknown/unknown",
                        number=event["number"],
                        body=_build_duplicate_comment(duplicate_result),
                        marker=DUPLICATE_COMMENT_MARKER,
                    )
            except GitHubWritebackError as exc:
                logger.exception(
                    "GitHub label write-back failed for %s #%s in %s: %s",
                    event["kind"],
                    event["number"],
                    event["repository"],
                    exc,
                )
        logger.info(
            "Scored %s #%s overall=%s suspicion=%s labels=%s provider=%s model=%s writeback=%s",
            event["kind"],
            event["number"],
            score.overall_score,
            score.suspicion,
            ",".join(score.suggested_labels),
            score.provider,
            score.model,
            writeback_applied,
        )
    except ScoringProviderError as exc:
        try:
            persisted = persist_failed_contribution(event, str(exc))
        except SQLAlchemyError:
            logger.exception(
                "Database persistence failed for failed %s #%s in %s",
                event["kind"],
                event["number"],
                event["repository"],
            )
            raise
        if not persisted:
            logger.info(
                "Discarding stale scoring failure for %s #%s in %s because a newer "
                "webhook snapshot is already registered.",
                event["kind"],
                event["number"],
                event["repository"],
            )
            return
        record_scoring_result(
            {
                "status": "failed",
                "repository": event["repository"],
                "kind": event["kind"],
                "number": event["number"],
                "title": event["title"],
                "error": str(exc),
            }
        )
        logger.exception(
            "Scoring failed for %s #%s in %s",
            event["kind"],
            event["number"],
            event["repository"],
        )
        raise


def _queue_expected() -> bool:
    return (
        settings.celery_enabled
        and settings.queue_provider.lower().strip() == "celery"
        and bool(settings.celery_broker_url or settings.redis_url)
    )


def _enqueue_with_celery(delivery_id: str) -> bool:
    if not _queue_expected():
        return False

    try:
        from worker.tasks.score_task import process_contribution_event_task

        process_contribution_event_task.delay(delivery_id)
    except Exception:
        logger.exception("Failed to enqueue Celery job for delivery %s", delivery_id)
        return False

    logger.info("Queued webhook delivery %s with Celery.", delivery_id)
    return True


def _build_duplicate_comment(duplicate_result) -> str:  # noqa: ANN001
    lines = [
        "maintainerKi found similar existing contributions:",
        "",
    ]
    for candidate in duplicate_result.candidates:
        similarity_percent = int(round(candidate.similarity * 100))
        lines.append(
            f"- #{candidate.number} ({candidate.kind}, {similarity_percent}% similar): {candidate.title}"
        )
    lines.extend(
        [
            "",
            "Please check whether this is a duplicate before spending more maintainer time on it.",
            "",
            DUPLICATE_COMMENT_MARKER,
        ]
    )
    return "\n".join(lines)
