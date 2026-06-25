from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import case, func, or_, select

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


def _find_record(session, event: dict[str, Any]) -> ContributionRecord | None:
    stmt = select(ContributionRecord).where(
        ContributionRecord.repository == (event.get("repository") or "unknown/unknown"),
        ContributionRecord.kind == event["kind"],
        ContributionRecord.number == event["number"],
    )
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
        "title": event.get("title") or "",
        "body": event.get("body") or "",
        "html_url": event.get("html_url") or "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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

        record = _find_record(session, event)
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


def mark_webhook_delivery_queued(delivery_id: str) -> None:
    with session_scope() as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return
        delivery.status = "queued"
        delivery.error_message = None


def mark_webhook_delivery_queue_failed(delivery_id: str, error_message: str) -> None:
    with session_scope() as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return
        delivery.status = "queue_failed"
        delivery.error_message = error_message


def claim_webhook_delivery(delivery_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(WebhookDeliveryRecord.delivery_id == delivery_id)
        ).scalar_one_or_none()
        if delivery is None:
            return None
        if delivery.status in {"processed", "ignored_duplicate_content", "processing"}:
            return None
        delivery.status = "processing"
        delivery.processing_started_at = _utc_now()
        delivery.error_message = None
        payload = json.loads(delivery.payload_json)
        if not isinstance(payload, dict):
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
    with session_scope() as session:
        rows = session.execute(
            select(WebhookDeliveryRecord.delivery_id)
            .where(WebhookDeliveryRecord.status.in_(statuses))
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
) -> None:
    with session_scope() as session:
        record = _find_record(session, event)
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
        record.content_fingerprint = _event_content_fingerprint(event)
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


def persist_failed_contribution(event: dict[str, Any], error_message: str) -> None:
    with session_scope() as session:
        record = _find_record(session, event)
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
        record.content_fingerprint = _event_content_fingerprint(event)
        record.error_message = error_message
        record.scored_at = _utc_now()


def list_recent_contributions(limit: int = 20) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(ContributionRecord)
            .order_by(ContributionRecord.scored_at.desc(), ContributionRecord.received_at.desc())
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


def list_repositories() -> list[dict[str, Any]]:
    thresholds = get_triage_thresholds()
    with session_scope() as session:
        stmt = (
            select(
                ContributionRecord.repository_id,
                ContributionRecord.repository,
                func.count(ContributionRecord.id).label("contribution_count"),
                func.sum(
                    case((ContributionRecord.status == "scored", 1), else_=0)
                ).label("scored_count"),
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
                func.sum(
                    case((ContributionRecord.status == "pending", 1), else_=0)
                ).label("pending_count"),
                func.max(ContributionRecord.received_at).label("last_received_at"),
            )
            .where(ContributionRecord.repository_id.is_not(None))
            .group_by(ContributionRecord.repository_id, ContributionRecord.repository)
            .order_by(func.max(ContributionRecord.received_at).desc())
        )
        rows = session.execute(stmt).all()

    return [
        {
            "id": row.repository_id,
            "name": row.repository,
            "contribution_count": int(row.contribution_count or 0),
            "scored_count": int(row.scored_count or 0),
            "duplicate_count": int(row.duplicate_count or 0),
            "suspicious_count": int(row.suspicious_count or 0),
            "pending_count": int(row.pending_count or 0),
            "last_received_at": row.last_received_at.isoformat() if row.last_received_at else None,
        }
        for row in rows
    ]


def get_repository_summary(repo_id: int) -> dict[str, Any] | None:
    thresholds = get_triage_thresholds()
    with session_scope() as session:
        row = session.execute(
            select(
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
            )
            .where(ContributionRecord.repository_id == repo_id)
            .group_by(ContributionRecord.repository_id, ContributionRecord.repository)
        ).one_or_none()

    if row is None:
        return None
    return {
        "id": row.repository_id,
        "name": row.repository,
        "contribution_count": int(row.contribution_count or 0),
        "scored_count": int(row.scored_count or 0),
        "duplicate_count": int(row.duplicate_count or 0),
        "suspicious_count": int(row.suspicious_count or 0),
        "pending_count": int(row.pending_count or 0),
        "last_received_at": row.last_received_at.isoformat() if row.last_received_at else None,
    }


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
        if min_score is not None:
            stmt = stmt.where(func.coalesce(ContributionRecord.overall_score, -1) >= min_score)
        if duplicates_only:
            stmt = stmt.where(ContributionRecord.possible_duplicate.is_(True))
        if suspicious_only:
            stmt = stmt.where(
                func.coalesce(ContributionRecord.suspicion_score, 0) >= thresholds.suspicious_score
            )
        lowered_search = (search or "").strip().lower()
        if lowered_search:
            pattern = f"%{lowered_search}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(ContributionRecord.title, "")).like(pattern),
                    func.lower(func.coalesce(ContributionRecord.body, "")).like(pattern),
                    func.lower(func.coalesce(ContributionRecord.author, "")).like(pattern),
                    func.lower(func.coalesce(ContributionRecord.html_url, "")).like(pattern),
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
) -> dict[str, Any]:
    with session_scope() as session:
        record = session.get(ContributionRecord, contribution_id)
        if record is None:
            raise ValueError(f"Contribution {contribution_id} does not exist.")

        cleaned_labels = [label.strip() for label in (correct_labels or []) if label.strip()]
        feedback = ScoringFeedbackRecord(
            contribution_id=contribution_id,
            maintainer_action=maintainer_action,
            correct_labels_json=_serialize_labels(cleaned_labels),
            notes=notes.strip() if notes else None,
        )
        session.add(feedback)

        if maintainer_action == "override":
            record.maintainer_override_labels_json = _serialize_labels(cleaned_labels)

        session.flush()
        session.refresh(feedback)
        return _serialize_feedback(feedback)


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
        "correct_labels": labels,
        "notes": feedback.notes,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def _triage_bucket(record: ContributionRecord) -> str:
    return triage_bucket_from_values(
        status=record.status,
        possible_duplicate=bool(record.possible_duplicate),
        suspicion_score=record.suspicion_score,
        overall_score=record.overall_score,
    )
