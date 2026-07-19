from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import and_, case, delete, func, or_, select, update

from server.config import settings
from server.db import session_scope
from server.duplicates.models import DuplicateDetectionResult, EmbeddingResult
from server.models.tables import ContributionRecord, ScoringFeedbackRecord, WebhookDeliveryRecord
from server.scorer.models import ScoreResult
from server.triage import get_triage_thresholds, score_distribution_bucket, triage_bucket_from_values


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _deserialize_labels(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _serialize_labels(labels: Iterable[str]) -> str:
    normalized: list[str] = []
    for label in labels:
        cleaned = str(label).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return json.dumps(normalized)


def _effective_labels(record: ContributionRecord) -> list[str]:
    override_labels = _deserialize_labels(record.maintainer_override_labels_json)
    if record.maintainer_override_labels_json is not None:
        return override_labels
    return _deserialize_labels(record.suggested_labels_json)


def _find_record(
    session,
    event: dict[str, Any],
    *,
    for_update: bool = False,
) -> ContributionRecord | None:
    stmt = select(ContributionRecord).where(
        ContributionRecord.repository == (event.get("repository") or "unknown/unknown"),
        ContributionRecord.kind == event["kind"],
        ContributionRecord.number == event["number"],
    )
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def _apply_event_snapshot(record: ContributionRecord, event: dict[str, Any], *, received_at: datetime | None = None) -> None:
    record.repository = event.get("repository") or "unknown/unknown"
    record.repository_id = event.get("repository_id")
    record.github_id = event.get("github_id")
    record.kind = event["kind"]
    record.action = event["action"]
    record.number = event["number"]
    record.title = event.get("title") or ""
    record.body = event.get("body") or ""
    record.author = event.get("author")
    record.sender = event.get("sender")
    record.html_url = event.get("html_url")
    if received_at is not None:
        record.received_at = received_at


def _reset_scoring_state(record: ContributionRecord) -> None:
    record.quality_score = None
    record.relevance_score = None
    record.completeness_score = None
    record.suspicion_score = None
    record.overall_score = None
    record.ai_summary = None
    record.suggested_labels_json = None
    record.scorer_provider = None
    record.scorer_model = None
    record.prompt_version = None
    record.embedding_json = None
    record.embedding_provider = None
    record.embedding_model = None
    record.duplicate_candidates_json = None
    record.possible_duplicate = False
    record.top_duplicate_similarity = None
    record.duplicate_checked_at = None
    record.scored_at = None
    record.maintainer_override_labels_json = None


def _event_content_fingerprint(event: dict[str, Any]) -> str:
    payload = {
        "repository": event.get("repository") or "unknown/unknown",
        "repository_id": event.get("repository_id"),
        "kind": event.get("kind"),
        "number": event.get("number"),
        "action": event.get("action"),
        "title": event.get("title") or "",
        "body": event.get("body") or "",
        "html_url": event.get("html_url") or "",
        "head_sha": event.get("head_sha"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def register_webhook_delivery(
    *,
    event_name: str,
    delivery_id: str | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    normalized_delivery_id = (delivery_id or f"generated-{uuid4()}").strip()
    now = _utc_now()
    fingerprint = _event_content_fingerprint(event)

    with session_scope() as session:
        existing_delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == normalized_delivery_id)
        ).scalar_one_or_none()
        if existing_delivery is not None:
            return {
                "status": "ignored",
                "reason": "duplicate_delivery",
                "delivery_id": normalized_delivery_id,
            }

        record = _find_record(session, event, for_update=True)
        if (
            record is not None
            and record.content_fingerprint == fingerprint
            and record.status in {"pending", "scored"}
        ):
            session.add(
                WebhookDeliveryRecord(
                    delivery_id=normalized_delivery_id,
                    event_name=event_name,
                    repository=event.get("repository") or "unknown/unknown",
                    repository_id=event.get("repository_id"),
                    kind=event.get("kind"),
                    action=event.get("action"),
                    number=event.get("number"),
                    contribution_id=record.id,
                    content_fingerprint=fingerprint,
                    payload_json=json.dumps(event),
                    status="ignored_duplicate_content",
                    queued_at=now,
                    processed_at=now,
                )
            )
            return {
                "status": "ignored",
                "reason": "duplicate_content",
                "delivery_id": normalized_delivery_id,
                "contribution_id": record.id,
            }

        if record is None:
            record = ContributionRecord(
                repository=event.get("repository") or "unknown/unknown",
                repository_id=event.get("repository_id"),
                github_id=event.get("github_id"),
                kind=event["kind"],
                action=event["action"],
                number=event["number"],
                title=event.get("title") or "",
                body=event.get("body") or "",
                author=event.get("author"),
                sender=event.get("sender"),
                html_url=event.get("html_url"),
                received_at=now,
                status="pending",
            )
            session.add(record)
            session.flush()

        _apply_event_snapshot(record, event, received_at=now)
        record.status = "pending"
        record.content_fingerprint = fingerprint
        record.error_message = None
        _reset_scoring_state(record)
        session.flush()

        session.add(
            WebhookDeliveryRecord(
                delivery_id=normalized_delivery_id,
                event_name=event_name,
                repository=record.repository,
                repository_id=record.repository_id,
                kind=record.kind,
                action=record.action,
                number=record.number,
                contribution_id=record.id,
                content_fingerprint=fingerprint,
                payload_json=json.dumps(event),
                status="accepted",
                queued_at=now,
            )
        )

        return {
            "status": "accepted",
            "delivery_id": normalized_delivery_id,
            "contribution_id": record.id,
        }


_REQUEABLE_QUEUED_STATUSES = ("accepted", "queue_failed", "failed")
_REQUEABLE_QUEUE_FAILED_STATUSES = ("accepted", "queued")
_CLAIMABLE_STATUSES = ("accepted", "queued", "queue_failed", "failed")


def mark_webhook_delivery_queued(delivery_id: str) -> None:
    with session_scope() as session:
        session.execute(
            update(WebhookDeliveryRecord)
            .where(
                WebhookDeliveryRecord.delivery_id == delivery_id,
                WebhookDeliveryRecord.status.in_(_REQUEABLE_QUEUED_STATUSES),
            )
            .values(status="queued", error_message=None)
        )


def mark_webhook_delivery_queue_failed(delivery_id: str, error_message: str) -> None:
    with session_scope() as session:
        session.execute(
            update(WebhookDeliveryRecord)
            .where(
                WebhookDeliveryRecord.delivery_id == delivery_id,
                WebhookDeliveryRecord.status.in_(_REQUEABLE_QUEUE_FAILED_STATUSES),
            )
            .values(status="queue_failed", error_message=error_message)
        )


def claim_webhook_delivery(delivery_id: str) -> dict[str, Any] | None:
    now = _utc_now()
    stale_cutoff = now - timedelta(seconds=settings.webhook_processing_stale_seconds)

    with session_scope() as session:
        claim_result = session.execute(
            update(WebhookDeliveryRecord)
            .where(
                WebhookDeliveryRecord.delivery_id == delivery_id,
                or_(
                    WebhookDeliveryRecord.status.in_(_CLAIMABLE_STATUSES),
                    and_(
                        WebhookDeliveryRecord.status == "processing",
                        WebhookDeliveryRecord.processing_started_at.is_not(None),
                        WebhookDeliveryRecord.processing_started_at < stale_cutoff,
                    ),
                ),
            )
            .values(status="processing", processing_started_at=now, error_message=None)
        )
        if claim_result.rowcount != 1:
            return None

        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return None

        try:
            payload = json.loads(delivery.payload_json)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            delivery.status = "failed"
            delivery.processed_at = now
            delivery.error_message = "Webhook delivery payload was not a JSON object."
            return None
        return payload


def mark_webhook_delivery_processed(delivery_id: str) -> None:
    with session_scope() as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return
        delivery.status = "processed"
        delivery.processed_at = _utc_now()
        delivery.error_message = None


def mark_webhook_delivery_failed(delivery_id: str, error_message: str) -> None:
    with session_scope() as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return
        delivery.status = "failed"
        delivery.processed_at = _utc_now()
        delivery.error_message = error_message


def list_retriable_webhook_delivery_ids(
    *,
    statuses: tuple[str, ...] = ("accepted", "queue_failed", "failed"),
    limit: int = 100,
) -> list[str]:
    stale_cutoff = _utc_now() - timedelta(seconds=settings.webhook_processing_stale_seconds)
    with session_scope() as session:
        rows = session.execute(
            select(WebhookDeliveryRecord.delivery_id)
            .where(
                or_(
                    WebhookDeliveryRecord.status.in_(statuses),
                    and_(
                        WebhookDeliveryRecord.status == "processing",
                        WebhookDeliveryRecord.processing_started_at.is_not(None),
                        WebhookDeliveryRecord.processing_started_at < stale_cutoff,
                    ),
                )
            )
            .order_by(WebhookDeliveryRecord.queued_at.asc())
            .limit(limit)
        ).all()
    return [str(row.delivery_id) for row in rows]


def persist_scored_contribution(
    event: dict[str, Any],
    score: ScoreResult,
    *,
    embedding_result: EmbeddingResult | None = None,
    duplicate_result: DuplicateDetectionResult | None = None,
) -> bool:
    event_fingerprint = _event_content_fingerprint(event)
    with session_scope() as session:
        record = _find_record(session, event, for_update=True)
        if (
            record is not None
            and record.content_fingerprint is not None
            and record.content_fingerprint != event_fingerprint
        ):
            return False
        if record is None:
            record = ContributionRecord(
                repository=event.get("repository") or "unknown/unknown",
                repository_id=event.get("repository_id"),
                github_id=event.get("github_id"),
                kind=event["kind"],
                action=event["action"],
                number=event["number"],
                title=event.get("title") or "",
                body=event.get("body") or "",
                author=event.get("author"),
                sender=event.get("sender"),
                html_url=event.get("html_url"),
                received_at=_utc_now(),
                status="scored",
            )
            session.add(record)

        _apply_event_snapshot(record, event)
        record.status = "scored"
        record.content_fingerprint = event_fingerprint
        record.quality_score = score.quality
        record.relevance_score = score.relevance
        record.completeness_score = score.completeness
        record.suspicion_score = score.suspicion
        record.overall_score = score.overall_score
        record.ai_summary = score.summary
        record.suggested_labels_json = _serialize_labels(score.suggested_labels)
        record.maintainer_override_labels_json = None
        record.scorer_provider = score.provider
        record.scorer_model = score.model
        record.prompt_version = score.prompt_version
        record.error_message = None
        if embedding_result is not None:
            record.embedding_json = json.dumps(embedding_result.embedding)
            record.embedding_provider = embedding_result.provider
            record.embedding_model = embedding_result.model
        else:
            record.embedding_json = None
            record.embedding_provider = None
            record.embedding_model = None
        if duplicate_result is not None:
            record.duplicate_candidates_json = json.dumps(
                [candidate.model_dump() for candidate in duplicate_result.candidates]
            )
            record.possible_duplicate = duplicate_result.possible_duplicate
            record.top_duplicate_similarity = duplicate_result.top_similarity
            record.duplicate_checked_at = _utc_now()
        else:
            record.duplicate_candidates_json = None
            record.possible_duplicate = False
            record.top_duplicate_similarity = None
            record.duplicate_checked_at = None
        record.scored_at = _utc_now()
        return True


def persist_failed_contribution(event: dict[str, Any], error_message: str) -> bool:
    event_fingerprint = _event_content_fingerprint(event)
    with session_scope() as session:
        record = _find_record(session, event, for_update=True)
        if (
            record is not None
            and record.content_fingerprint is not None
            and record.content_fingerprint != event_fingerprint
        ):
            return False
        if record is None:
            record = ContributionRecord(
                repository=event.get("repository") or "unknown/unknown",
                repository_id=event.get("repository_id"),
                github_id=event.get("github_id"),
                kind=event["kind"],
                action=event["action"],
                number=event["number"],
                title=event.get("title") or "",
                body=event.get("body") or "",
                author=event.get("author"),
                sender=event.get("sender"),
                html_url=event.get("html_url"),
                received_at=_utc_now(),
                status="failed",
            )
            session.add(record)

        _apply_event_snapshot(record, event)
        record.status = "failed"
        record.content_fingerprint = event_fingerprint
        record.error_message = error_message
        record.scored_at = _utc_now()
        return True


@contextmanager
def current_contribution_snapshot(event: dict[str, Any]):  # noqa: ANN201
    """Hold the contribution row lock while current-snapshot side effects run."""
    event_fingerprint = _event_content_fingerprint(event)
    with session_scope() as session:
        record = _find_record(session, event, for_update=True)
        yield bool(record is not None and record.content_fingerprint == event_fingerprint)


def list_recent_contributions(limit: int = 20) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(ContributionRecord)
            .order_by(
                ContributionRecord.scored_at.desc().nullslast(),
                ContributionRecord.received_at.desc(),
            )
            .limit(limit)
        )
        records = session.execute(stmt).scalars().all()

    items: list[dict[str, Any]] = []
    for record in records:
        item: dict[str, Any] = {
            "id": record.id,
            "status": record.status,
            "repository": record.repository,
            "kind": record.kind,
            "number": record.number,
            "title": record.title,
            "author": record.author,
            "html_url": record.html_url,
            "received_at": record.received_at.isoformat() if record.received_at else None,
            "scored_at": record.scored_at.isoformat() if record.scored_at else None,
        }
        if record.status == "scored":
            item["score"] = {
                "quality": record.quality_score,
                "relevance": record.relevance_score,
                "completeness": record.completeness_score,
                "suspicion": record.suspicion_score,
                "overall_score": record.overall_score,
                "summary": record.ai_summary,
                "suggested_labels": _effective_labels(record),
                "provider": record.scorer_provider,
                "model": record.scorer_model,
                "prompt_version": record.prompt_version,
            }
            duplicate_candidates = (
                json.loads(record.duplicate_candidates_json)
                if record.duplicate_candidates_json
                else []
            )
            item["duplicates"] = {
                "possible_duplicate": bool(record.possible_duplicate),
                "top_similarity": record.top_duplicate_similarity,
                "embedding_provider": record.embedding_provider,
                "embedding_model": record.embedding_model,
                "candidates": duplicate_candidates,
                "checked_at": record.duplicate_checked_at.isoformat()
                if record.duplicate_checked_at
                else None,
            }
        if record.error_message:
            item["error"] = record.error_message
        items.append(item)
    return items


def list_repository_duplicate_candidates(
    repository: str,
    *,
    exclude_number: int | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(ContributionRecord)
            .where(
                ContributionRecord.repository == repository,
                ContributionRecord.embedding_json.is_not(None),
                ContributionRecord.status == "scored",
            )
            .order_by(ContributionRecord.scored_at.desc(), ContributionRecord.received_at.desc())
            .limit(limit)
        )
        records = session.execute(stmt).scalars().all()

    items: list[dict[str, Any]] = []
    for record in records:
        if exclude_number is not None and record.number == exclude_number:
            continue
        if not record.embedding_json:
            continue
        try:
            embedding = [float(value) for value in json.loads(record.embedding_json)]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        items.append(
            {
                "id": record.id,
                "repository": record.repository,
                "kind": record.kind,
                "number": record.number,
                "title": record.title,
                "html_url": record.html_url,
                "embedding": embedding,
            }
        )
    return items


def _repository_summary_stmt(thresholds):  # noqa: ANN001
    return select(
        ContributionRecord.repository_id,
        ContributionRecord.repository,
        func.count(ContributionRecord.id).label("contribution_count"),
        func.sum(case((ContributionRecord.status == "scored", 1), else_=0)).label(
            "scored_count"
        ),
        func.sum(
            case((ContributionRecord.possible_duplicate.is_(True), 1), else_=0)
        ).label("duplicate_count"),
        func.sum(
            case(
                (
                    func.coalesce(ContributionRecord.suspicion_score, 0)
                    >= thresholds.suspicious_score,
                    1,
                ),
                else_=0,
            )
        ).label("suspicious_count"),
        func.sum(case((ContributionRecord.status == "pending", 1), else_=0)).label(
            "pending_count"
        ),
        func.max(ContributionRecord.received_at).label("last_received_at"),
    ).group_by(ContributionRecord.repository_id, ContributionRecord.repository)


def _comparable_timestamp(value: datetime | None) -> datetime:
    # SQLite's DateTime(timezone=True) columns can round-trip as either naive or
    # tz-aware Python datetimes depending on how the row was written (ORM bind vs.
    # raw SQL), so normalize to naive UTC before comparing to avoid TypeError:
    # can't compare offset-naive and offset-aware datetimes.
    if value is None:
        return datetime.min
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _merge_repository_groups(rows: Iterable[Any]) -> dict[int, dict[str, Any]]:
    # A GitHub repository rename creates a second (repository_id, repository) group
    # for the same id. Merge those groups here instead of relying on SQL grouping
    # (or `.one_or_none()`) to return a single row per repository id.
    merged: dict[int, dict[str, Any]] = {}
    for row in rows:
        repo_id = row.repository_id
        entry = merged.get(repo_id)
        if entry is None:
            merged[repo_id] = {
                "id": repo_id,
                "name": row.repository,
                "contribution_count": int(row.contribution_count or 0),
                "scored_count": int(row.scored_count or 0),
                "duplicate_count": int(row.duplicate_count or 0),
                "suspicious_count": int(row.suspicious_count or 0),
                "pending_count": int(row.pending_count or 0),
                "last_received_at": row.last_received_at,
            }
            continue
        entry["contribution_count"] += int(row.contribution_count or 0)
        entry["scored_count"] += int(row.scored_count or 0)
        entry["duplicate_count"] += int(row.duplicate_count or 0)
        entry["suspicious_count"] += int(row.suspicious_count or 0)
        entry["pending_count"] += int(row.pending_count or 0)
        if row.last_received_at is not None and (
            entry["last_received_at"] is None
            or _comparable_timestamp(row.last_received_at)
            > _comparable_timestamp(entry["last_received_at"])
        ):
            entry["last_received_at"] = row.last_received_at
            entry["name"] = row.repository
    return merged


def _serialize_repository_summary(entry: dict[str, Any]) -> dict[str, Any]:
    last_received_at = entry["last_received_at"]
    return {
        **entry,
        "last_received_at": last_received_at.isoformat() if last_received_at else None,
    }


def list_repositories() -> list[dict[str, Any]]:
    thresholds = get_triage_thresholds()
    with session_scope() as session:
        stmt = _repository_summary_stmt(thresholds).where(
            ContributionRecord.repository_id.is_not(None)
        )
        rows = session.execute(stmt).all()

    merged = _merge_repository_groups(rows)
    ordered = sorted(
        merged.values(),
        key=lambda entry: _comparable_timestamp(entry["last_received_at"]),
        reverse=True,
    )
    return [_serialize_repository_summary(entry) for entry in ordered]


def get_repository_summary(repo_id: int) -> dict[str, Any] | None:
    thresholds = get_triage_thresholds()
    with session_scope() as session:
        stmt = _repository_summary_stmt(thresholds).where(
            ContributionRecord.repository_id == repo_id
        )
        rows = session.execute(stmt).all()

    if not rows:
        return None

    merged = _merge_repository_groups(rows)
    return _serialize_repository_summary(merged[repo_id])


def list_repo_inbox(
    repo_id: int,
    *,
    status: str | None = None,
    kind: str | None = None,
    min_score: int | None = None,
    duplicates_only: bool = False,
    suspicious_only: bool = False,
    search: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    thresholds = get_triage_thresholds()
    triage_rank = case(
        (ContributionRecord.status == "pending", 0),
        (ContributionRecord.possible_duplicate.is_(True), 1),
        (
            func.coalesce(ContributionRecord.suspicion_score, 0) >= thresholds.suspicious_score,
            2,
        ),
        (func.coalesce(ContributionRecord.overall_score, 0) >= thresholds.review_first, 3),
        (func.coalesce(ContributionRecord.overall_score, 0) >= thresholds.worth_a_look, 4),
        else_=5,
    )

    with session_scope() as session:
        stmt = select(ContributionRecord).where(ContributionRecord.repository_id == repo_id)
        if status:
            stmt = stmt.where(ContributionRecord.status == status)
        if kind:
            stmt = stmt.where(ContributionRecord.kind == kind)
        if min_score is not None and min_score > 0:
            stmt = stmt.where(func.coalesce(ContributionRecord.overall_score, -1) >= min_score)
        if duplicates_only:
            stmt = stmt.where(ContributionRecord.possible_duplicate.is_(True))
        if suspicious_only:
            stmt = stmt.where(
                func.coalesce(ContributionRecord.suspicion_score, 0) >= thresholds.suspicious_score
            )
        lowered_search = (search or "").strip().lower()
        if lowered_search:
            pattern = f"%{_escape_like_pattern(lowered_search)}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(ContributionRecord.title, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(ContributionRecord.body, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(ContributionRecord.author, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(ContributionRecord.html_url, "")).like(
                        pattern, escape="\\"
                    ),
                )
            )
        stmt = stmt.order_by(
            triage_rank.asc(),
            func.coalesce(ContributionRecord.suspicion_score, 0).desc(),
            func.coalesce(ContributionRecord.overall_score, 0).desc(),
            ContributionRecord.received_at.desc(),
        ).limit(limit)
        records = session.execute(stmt).scalars().all()

    return [_serialize_contribution_summary(record) for record in records]


def get_contribution_detail(contribution_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        record = session.get(ContributionRecord, contribution_id)
        if record is None:
            return None
        feedback_records = (
            session.execute(
                select(ScoringFeedbackRecord)
                .where(ScoringFeedbackRecord.contribution_id == contribution_id)
                .order_by(ScoringFeedbackRecord.created_at.desc())
            )
            .scalars()
            .all()
        )

    item = _serialize_contribution_detail(record)
    item["feedback"] = [_serialize_feedback(feedback) for feedback in feedback_records]
    return item


def create_scoring_feedback(
    contribution_id: int,
    *,
    maintainer_action: str,
    correct_labels: list[str] | None = None,
    notes: str | None = None,
    actor_username: str | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        record = session.get(ContributionRecord, contribution_id)
        if record is None:
            raise ValueError(f"Contribution {contribution_id} does not exist.")

        cleaned_labels = [label.strip() for label in (correct_labels or []) if label.strip()]
        feedback = ScoringFeedbackRecord(
            contribution_id=contribution_id,
            maintainer_action=maintainer_action,
            actor_username=actor_username.strip() if actor_username else None,
            correct_labels_json=_serialize_labels(cleaned_labels),
            notes=notes.strip() if notes else None,
        )
        session.add(feedback)

        if maintainer_action == "override":
            record.maintainer_override_labels_json = _serialize_labels(cleaned_labels)

        session.flush()
        session.refresh(feedback)
        return _serialize_feedback(feedback)


def plan_retention_purge(
    *,
    webhook_retention_days: int,
    contribution_body_retention_days: int,
    feedback_note_retention_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    current_time = now or _utc_now()
    result = {
        "delete_webhook_deliveries": 0,
        "scrub_contribution_bodies": 0,
        "scrub_feedback_notes": 0,
    }

    with session_scope() as session:
        if webhook_retention_days > 0:
            webhook_cutoff = _retention_cutoff(current_time, webhook_retention_days)
            result["delete_webhook_deliveries"] = int(
                session.execute(
                    select(func.count())
                    .select_from(WebhookDeliveryRecord)
                    .where(
                        or_(
                            WebhookDeliveryRecord.processed_at < webhook_cutoff,
                            (
                                WebhookDeliveryRecord.processed_at.is_(None)
                                & (WebhookDeliveryRecord.queued_at < webhook_cutoff)
                            ),
                        )
                    )
                ).scalar_one()
            )

        if contribution_body_retention_days > 0:
            contribution_cutoff = _retention_cutoff(current_time, contribution_body_retention_days)
            result["scrub_contribution_bodies"] = int(
                session.execute(
                    select(func.count())
                    .select_from(ContributionRecord)
                    .where(
                        ContributionRecord.received_at < contribution_cutoff,
                        or_(
                            ContributionRecord.body != "",
                            ContributionRecord.embedding_json.is_not(None),
                            ContributionRecord.duplicate_candidates_json.is_not(None),
                            ContributionRecord.possible_duplicate.is_(True),
                        ),
                    )
                ).scalar_one()
            )

        if feedback_note_retention_days > 0:
            feedback_cutoff = _retention_cutoff(current_time, feedback_note_retention_days)
            result["scrub_feedback_notes"] = int(
                session.execute(
                    select(func.count())
                    .select_from(ScoringFeedbackRecord)
                    .where(
                        ScoringFeedbackRecord.created_at < feedback_cutoff,
                        ScoringFeedbackRecord.notes.is_not(None),
                    )
                ).scalar_one()
            )

    return result


def apply_retention_purge(
    *,
    webhook_retention_days: int,
    contribution_body_retention_days: int,
    feedback_note_retention_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    current_time = now or _utc_now()
    plan = plan_retention_purge(
        webhook_retention_days=webhook_retention_days,
        contribution_body_retention_days=contribution_body_retention_days,
        feedback_note_retention_days=feedback_note_retention_days,
        now=current_time,
    )

    with session_scope() as session:
        if plan["delete_webhook_deliveries"] > 0:
            webhook_cutoff = _retention_cutoff(current_time, webhook_retention_days)
            session.execute(
                delete(WebhookDeliveryRecord).where(
                    or_(
                        WebhookDeliveryRecord.processed_at < webhook_cutoff,
                        (
                            WebhookDeliveryRecord.processed_at.is_(None)
                            & (WebhookDeliveryRecord.queued_at < webhook_cutoff)
                        ),
                    )
                )
            )

        if plan["scrub_contribution_bodies"] > 0:
            contribution_cutoff = _retention_cutoff(current_time, contribution_body_retention_days)
            session.execute(
                update(ContributionRecord)
                .where(
                    ContributionRecord.received_at < contribution_cutoff,
                    or_(
                        ContributionRecord.body != "",
                        ContributionRecord.embedding_json.is_not(None),
                        ContributionRecord.duplicate_candidates_json.is_not(None),
                        ContributionRecord.possible_duplicate.is_(True),
                    ),
                )
                .values(
                    body="",
                    embedding_json=None,
                    duplicate_candidates_json=None,
                    possible_duplicate=False,
                    top_duplicate_similarity=None,
                    updated_at=current_time,
                )
            )

        if plan["scrub_feedback_notes"] > 0:
            feedback_cutoff = _retention_cutoff(current_time, feedback_note_retention_days)
            session.execute(
                update(ScoringFeedbackRecord)
                .where(
                    ScoringFeedbackRecord.created_at < feedback_cutoff,
                    ScoringFeedbackRecord.notes.is_not(None),
                )
                .values(notes=None)
            )

    return plan


def get_contribution_writeback_target(contribution_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        record = session.get(ContributionRecord, contribution_id)
        if record is None:
            return None
        return {
            "repository": record.repository,
            "number": record.number,
            "labels": _effective_labels(record),
        }


def count_recent_contributions_by_author(
    author: str,
    *,
    within_hours: int,
    exclude: tuple[str, str, int] | None = None,
) -> int:
    normalized_author = (author or "").strip().lower()
    if not normalized_author:
        return 0

    cutoff = _utc_now() - timedelta(hours=within_hours)
    with session_scope() as session:
        stmt = (
            select(func.count())
            .select_from(ContributionRecord)
            .where(
                func.lower(ContributionRecord.author) == normalized_author,
                ContributionRecord.received_at >= cutoff,
            )
        )
        if exclude is not None:
            exclude_repository, exclude_kind, exclude_number = exclude
            stmt = stmt.where(
                or_(
                    ContributionRecord.repository != exclude_repository,
                    ContributionRecord.kind != exclude_kind,
                    ContributionRecord.number != exclude_number,
                )
            )
        return int(session.execute(stmt).scalar_one())


def count_author_contributions_in_repository(
    author: str,
    repository: str,
    *,
    exclude_kind: str | None = None,
    exclude_number: int | None = None,
) -> int:
    normalized_author = (author or "").strip().lower()
    if not normalized_author:
        return 0

    normalized_repository = (repository or "").strip().lower()
    with session_scope() as session:
        stmt = (
            select(func.count())
            .select_from(ContributionRecord)
            .where(
                func.lower(ContributionRecord.author) == normalized_author,
                func.lower(ContributionRecord.repository) == normalized_repository,
            )
        )
        if exclude_kind is not None and exclude_number is not None:
            stmt = stmt.where(
                or_(
                    ContributionRecord.kind != exclude_kind,
                    ContributionRecord.number != exclude_number,
                )
            )
        return int(session.execute(stmt).scalar_one())


def get_repo_stats(repo_id: int) -> dict[str, Any] | None:
    summary = get_repository_summary(repo_id)
    if summary is None:
        return None

    with session_scope() as session:
        rows = session.execute(
            select(
                ContributionRecord.status,
                ContributionRecord.suspicion_score,
                ContributionRecord.possible_duplicate,
                ContributionRecord.overall_score,
                ContributionRecord.received_at,
                ContributionRecord.scored_at,
            ).where(ContributionRecord.repository_id == repo_id)
        ).all()

    score_buckets = {
        "high": 0,
        "medium": 0,
        "low": 0,
    }
    pending_count = 0
    reviewed_count = 0
    suspicious_count = 0
    duplicate_count = 0
    latencies: list[float] = []
    timeline: dict[str, int] = {}
    thresholds = get_triage_thresholds()

    for row in rows:
        if row.status == "pending":
            pending_count += 1
        if row.status == "scored":
            reviewed_count += 1
        if (row.suspicion_score or 0) >= thresholds.suspicious_score:
            suspicious_count += 1
        if row.possible_duplicate:
            duplicate_count += 1

        bucket = score_distribution_bucket(row.overall_score)
        if bucket is not None:
            score_buckets[bucket] += 1
        if row.received_at and row.scored_at:
            latency = (row.scored_at - row.received_at).total_seconds()
            if latency >= 0:
                latencies.append(latency)
        day_key = row.received_at.date().isoformat() if row.received_at else "unknown"
        timeline[day_key] = timeline.get(day_key, 0) + 1

    average_latency_seconds = round(sum(latencies) / len(latencies), 2) if latencies else None
    timeline_points = [
        {"date": date_key, "count": count}
        for date_key, count in sorted(timeline.items())
    ]

    return {
        "repository": summary,
        "queue_depth": pending_count,
        "reviewed_count": reviewed_count,
        "suspicious_count": suspicious_count,
        "duplicate_count": duplicate_count,
        "average_processing_latency_seconds": average_latency_seconds,
        "score_distribution": score_buckets,
        "activity_timeline": timeline_points,
    }


def _serialize_contribution_summary(record: ContributionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "repository_id": record.repository_id,
        "repository": record.repository,
        "kind": record.kind,
        "number": record.number,
        "title": record.title,
        "author": record.author,
        "status": record.status,
        "overall_score": record.overall_score,
        "suspicion_score": record.suspicion_score,
        "possible_duplicate": bool(record.possible_duplicate),
        "labels": _effective_labels(record),
        "summary": record.ai_summary,
        "html_url": record.html_url,
        "received_at": record.received_at.isoformat() if record.received_at else None,
        "scored_at": record.scored_at.isoformat() if record.scored_at else None,
        "triage_bucket": _triage_bucket(record),
    }


def _serialize_contribution_detail(record: ContributionRecord) -> dict[str, Any]:
    ai_labels = _deserialize_labels(record.suggested_labels_json)
    override_labels = _deserialize_labels(record.maintainer_override_labels_json)
    duplicate_candidates = (
        json.loads(record.duplicate_candidates_json) if record.duplicate_candidates_json else []
    )
    return {
        "id": record.id,
        "repository_id": record.repository_id,
        "repository": record.repository,
        "github_id": record.github_id,
        "kind": record.kind,
        "action": record.action,
        "number": record.number,
        "title": record.title,
        "body": record.body,
        "author": record.author,
        "sender": record.sender,
        "status": record.status,
        "html_url": record.html_url,
        "score": {
            "quality": record.quality_score,
            "relevance": record.relevance_score,
            "completeness": record.completeness_score,
            "suspicion": record.suspicion_score,
            "overall_score": record.overall_score,
            "summary": record.ai_summary,
            "suggested_labels": _effective_labels(record),
            "ai_suggested_labels": ai_labels,
            "maintainer_override_labels": override_labels,
            "has_maintainer_label_override": record.maintainer_override_labels_json is not None,
            "provider": record.scorer_provider,
            "model": record.scorer_model,
            "prompt_version": record.prompt_version,
        },
        "duplicates": {
            "possible_duplicate": bool(record.possible_duplicate),
            "top_similarity": record.top_duplicate_similarity,
            "embedding_provider": record.embedding_provider,
            "embedding_model": record.embedding_model,
            "candidates": duplicate_candidates,
            "checked_at": record.duplicate_checked_at.isoformat()
            if record.duplicate_checked_at
            else None,
        },
        "error": record.error_message,
        "received_at": record.received_at.isoformat() if record.received_at else None,
        "scored_at": record.scored_at.isoformat() if record.scored_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _serialize_feedback(feedback: ScoringFeedbackRecord) -> dict[str, Any]:
    labels = _deserialize_labels(feedback.correct_labels_json)
    return {
        "id": feedback.id,
        "contribution_id": feedback.contribution_id,
        "maintainer_action": feedback.maintainer_action,
        "actor_username": feedback.actor_username,
        "correct_labels": labels,
        "notes": feedback.notes,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def _retention_cutoff(now: datetime, retention_days: int) -> datetime:
    return now - timedelta(days=retention_days)


def _triage_bucket(record: ContributionRecord) -> str:
    return triage_bucket_from_values(
        status=record.status,
        possible_duplicate=bool(record.possible_duplicate),
        suspicion_score=record.suspicion_score,
        overall_score=record.overall_score,
    )
