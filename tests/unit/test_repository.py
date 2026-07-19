from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from server import db as db_module
from server.db import get_engine, init_database
from server.duplicates.models import DuplicateCandidate, DuplicateDetectionResult, EmbeddingResult
from server.models import Base
from server.models.tables import ContributionRecord, WebhookDeliveryRecord
from server.repository import (
    apply_retention_purge,
    claim_webhook_delivery,
    count_author_contributions_in_repository,
    count_recent_contributions_by_author,
    current_contribution_snapshot,
    create_scoring_feedback,
    get_contribution_detail,
    get_repo_stats,
    get_repository_summary,
    list_recent_contributions,
    list_repo_inbox,
    list_repositories,
    list_repository_duplicate_candidates,
    mark_webhook_delivery_failed,
    mark_webhook_delivery_processed,
    mark_webhook_delivery_queued,
    plan_retention_purge,
    persist_failed_contribution,
    persist_scored_contribution,
    register_webhook_delivery,
)
from server.scorer.models import ScoreResult


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def _sqlite_timestamp(value: datetime) -> str:
    # Match the naive, space-separated, offset-free text format SQLAlchemy's
    # SQLite dialect uses when binding DateTime columns, so raw SQL writes used
    # to backdate timestamps in tests sort/compare correctly against
    # ORM-produced values (a plain `.isoformat()` string uses a "T" separator
    # plus a "+00:00" suffix and does not compare correctly against it).
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def test_persist_scored_contribution_round_trip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_test.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12345,
        "kind": "issue",
        "action": "opened",
        "number": 44,
        "title": "Clarify install docs",
        "body": "We should mention Apple Silicon explicitly.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/44",
    }
    score = ScoreResult(
        quality=80,
        relevance=92,
        completeness=70,
        suspicion=10,
        overall_score=83,
        summary="Useful documentation improvement request with low suspicion.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )

    persist_scored_contribution(event, score)
    results = list_recent_contributions(limit=10)

    assert len(results) == 1
    assert results[0]["number"] == 44
    assert results[0]["status"] == "scored"
    assert results[0]["score"]["overall_score"] == 83
    assert results[0]["score"]["provider"] == "mlx"


def test_persist_scored_contribution_stores_duplicate_metadata(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_duplicates.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12346,
        "kind": "issue",
        "action": "opened",
        "number": 45,
        "title": "Login button broken on phones",
        "body": "Duplicate-ish issue report.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/45",
    }
    score = ScoreResult(
        quality=71,
        relevance=88,
        completeness=63,
        suspicion=11,
        overall_score=76,
        summary="Looks legitimate and overlaps with a previous report.",
        suggested_labels=["maintainerki:worth-a-look", "maintainerki:possible-duplicate"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )
    embedding = EmbeddingResult(
        provider="hashing",
        model="hashing-384d",
        normalized_text="login button broken on mobile duplicate-ish issue report",
        embedding=[0.1, 0.2, 0.3],
    )
    duplicates = DuplicateDetectionResult(
        provider="hashing",
        model="hashing-384d",
        threshold=0.8,
        possible_duplicate=True,
        top_similarity=0.91,
        candidates=[
            DuplicateCandidate(
                contribution_id=1,
                repository="example/repo",
                kind="issue",
                number=44,
                title="Login button doesn't work on mobile",
                html_url="https://github.com/example/repo/issues/44",
                similarity=0.91,
            )
        ],
    )

    persist_scored_contribution(
        event,
        score,
        embedding_result=embedding,
        duplicate_result=duplicates,
    )
    results = list_recent_contributions(limit=10)

    assert results[0]["duplicates"]["possible_duplicate"] is True
    assert results[0]["duplicates"]["top_similarity"] == 0.91
    assert results[0]["duplicates"]["candidates"][0]["number"] == 44

    candidates = list_repository_duplicate_candidates("example/repo")
    assert len(candidates) == 1
    assert candidates[0]["embedding"] == [0.1, 0.2, 0.3]


def test_persist_failed_contribution_round_trip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_failed.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 888,
        "kind": "pull_request",
        "action": "opened",
        "number": 45,
        "title": "Add docs example",
        "body": "This PR adds a short example.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/pull/45",
    }

    persist_failed_contribution(event, "model timed out")
    results = list_recent_contributions(limit=10)

    assert len(results) == 1
    assert results[0]["number"] == 45
    assert results[0]["status"] == "failed"
    assert results[0]["error"] == "model timed out"

def test_register_webhook_delivery_sets_pending_and_ignores_duplicate_content(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_delivery.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 999,
        "kind": "issue",
        "action": "opened",
        "number": 77,
        "title": "Need install help",
        "body": "Same content twice.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/77",
    }

    accepted = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-1",
        event=event,
    )
    duplicate = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-2",
        event=event,
    )

    stats = get_repo_stats(501)
    assert accepted["status"] == "accepted"
    assert duplicate["status"] == "ignored"
    assert duplicate["reason"] == "duplicate_content"
    assert stats is not None
    assert stats["queue_depth"] == 1


def test_list_repo_inbox_search_treats_like_wildcards_as_literals(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_search.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    percent_event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12345,
        "kind": "issue",
        "action": "opened",
        "number": 44,
        "title": "Fix 50% failure rate on retry",
        "body": "Retries fail half the time.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/44",
    }
    plain_event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12346,
        "kind": "issue",
        "action": "opened",
        "number": 45,
        "title": "Add dark mode toggle",
        "body": "The dashboard needs a dark theme.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/45",
    }
    score = ScoreResult(
        quality=80,
        relevance=92,
        completeness=70,
        suspicion=10,
        overall_score=83,
        summary="Useful documentation improvement request with low suspicion.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )

    persist_scored_contribution(percent_event, score)
    persist_scored_contribution(plain_event, score)

    percent_results = list_repo_inbox(501, search="50%")
    assert len(percent_results) == 1
    assert percent_results[0]["title"] == "Fix 50% failure rate on retry"

    underscore_results = list_repo_inbox(501, search="_")
    assert underscore_results == []


def test_override_feedback_updates_effective_labels(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_override.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12345,
        "kind": "issue",
        "action": "opened",
        "number": 44,
        "title": "Clarify install docs",
        "body": "We should mention Apple Silicon explicitly.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/44",
    }
    score = ScoreResult(
        quality=80,
        relevance=92,
        completeness=70,
        suspicion=10,
        overall_score=83,
        summary="Useful documentation improvement request with low suspicion.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )

    persist_scored_contribution(event, score)
    create_scoring_feedback(
        1,
        maintainer_action="override",
        correct_labels=["docs", "help-wanted"],
        notes="Use maintainer labels instead.",
    )

    detail = get_contribution_detail(1)
    assert detail is not None
    assert detail["score"]["suggested_labels"] == ["docs", "help-wanted"]
    assert detail["score"]["ai_suggested_labels"] == ["maintainerki:review-first", "documentation"]
    assert detail["score"]["has_maintainer_label_override"] is True


def test_retention_purge_scrubs_old_payloads_and_notes(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_retention.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 12345,
        "kind": "issue",
        "action": "opened",
        "number": 44,
        "title": "Clarify install docs",
        "body": "We should mention Apple Silicon explicitly.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/44",
    }
    score = ScoreResult(
        quality=80,
        relevance=92,
        completeness=70,
        suspicion=10,
        overall_score=83,
        summary="Useful documentation improvement request with low suspicion.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )

    persist_scored_contribution(event, score)
    register_webhook_delivery(event_name="issues", delivery_id="delivery-retain", event=event)
    create_scoring_feedback(
        1,
        maintainer_action="agreed",
        correct_labels=["documentation"],
        notes="Contains maintainer note",
        actor_username="admin",
    )

    old_timestamp = datetime.now(timezone.utc) - timedelta(days=120)
    old_iso = old_timestamp.isoformat()
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            f"UPDATE contributions SET received_at = '{old_iso}', updated_at = '{old_iso}' WHERE id = 1"
        )
        connection.exec_driver_sql(
            f"UPDATE scoring_feedback SET created_at = '{old_iso}' WHERE id = 1"
        )
        connection.exec_driver_sql(
            "UPDATE webhook_deliveries SET queued_at = ?, processed_at = ? WHERE delivery_id = ?",
            (old_iso, old_iso, "delivery-retain"),
        )

    plan = plan_retention_purge(
        webhook_retention_days=30,
        contribution_body_retention_days=90,
        feedback_note_retention_days=30,
    )
    result = apply_retention_purge(
        webhook_retention_days=30,
        contribution_body_retention_days=90,
        feedback_note_retention_days=30,
    )

    assert plan == {
        "delete_webhook_deliveries": 1,
        "scrub_contribution_bodies": 1,
        "scrub_feedback_notes": 1,
    }
    assert result == plan

    detail = get_contribution_detail(1)
    assert detail is not None
    assert detail["body"] == ""
    assert detail["feedback"][0]["notes"] is None
    assert detail["feedback"][0]["actor_username"] == "admin"


def _score() -> ScoreResult:
    return ScoreResult(
        quality=80,
        relevance=92,
        completeness=70,
        suspicion=10,
        overall_score=83,
        summary="Useful documentation improvement request with low suspicion.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mlx",
        model="local-mlx-model",
        prompt_version="phase2-v1",
    )


def test_claim_webhook_delivery_claims_exactly_once(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_claim.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 601,
        "kind": "issue",
        "action": "opened",
        "number": 60,
        "title": "Claim me once",
        "body": "Body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/60",
    }
    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-claim-once",
        event=event,
    )
    assert registration["status"] == "accepted"

    first_claim = claim_webhook_delivery("delivery-claim-once")
    second_claim = claim_webhook_delivery("delivery-claim-once")

    assert first_claim is not None
    assert first_claim["number"] == 60
    assert second_claim is None


def test_claim_webhook_delivery_reclaims_stale_processing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_claim_stale.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 602,
        "kind": "issue",
        "action": "opened",
        "number": 61,
        "title": "Reclaim me after a crash",
        "body": "Body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/61",
    }
    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-claim-stale",
        event=event,
    )
    assert registration["status"] == "accepted"

    first_claim = claim_webhook_delivery("delivery-claim-stale")
    assert first_claim is not None

    # A worker crashed mid-processing: nothing ever marked this delivery
    # processed/failed, and processing_started_at is now well past the
    # stale threshold.
    stale_timestamp = _sqlite_timestamp(datetime.now(timezone.utc) - timedelta(seconds=1000))
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            "UPDATE webhook_deliveries SET processing_started_at = ? WHERE delivery_id = ?",
            (stale_timestamp, "delivery-claim-stale"),
        )

    reclaimed = claim_webhook_delivery("delivery-claim-stale")
    assert reclaimed is not None
    assert reclaimed["number"] == 61


def test_mark_webhook_delivery_queued_does_not_regress_processed(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_no_regress.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 603,
        "kind": "issue",
        "action": "opened",
        "number": 62,
        "title": "Do not regress me",
        "body": "Body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/62",
    }
    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-no-regress",
        event=event,
    )
    assert registration["status"] == "accepted"
    assert claim_webhook_delivery("delivery-no-regress") is not None
    mark_webhook_delivery_processed("delivery-no-regress")

    # A slow/duplicated enqueue call arrives after the delivery already finished.
    mark_webhook_delivery_queued("delivery-no-regress")

    with Session(get_engine()) as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(
                WebhookDeliveryRecord.delivery_id == "delivery-no-regress"
            )
        ).scalar_one()
        assert delivery.status == "processed"


def test_mark_webhook_delivery_queued_requeues_failed_delivery(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_requeue_failed.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 604,
        "kind": "issue",
        "action": "opened",
        "number": 63,
        "title": "Requeue me after failure",
        "body": "Body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/63",
    }
    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-requeue-failed",
        event=event,
    )
    assert registration["status"] == "accepted"

    mark_webhook_delivery_failed("delivery-requeue-failed", "boom")

    with Session(get_engine()) as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(
                WebhookDeliveryRecord.delivery_id == "delivery-requeue-failed"
            )
        ).scalar_one()
        assert delivery.status == "failed"

    mark_webhook_delivery_queued("delivery-requeue-failed")

    with Session(get_engine()) as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(
                WebhookDeliveryRecord.delivery_id == "delivery-requeue-failed"
            )
        ).scalar_one()
        assert delivery.status == "queued"
        assert delivery.error_message is None


def test_register_webhook_delivery_reaccepts_reopened_with_unchanged_content(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "maintainerki_reopened.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 604,
        "kind": "issue",
        "action": "opened",
        "number": 63,
        "title": "Issue that gets reopened",
        "body": "Same body throughout.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/63",
        "head_sha": None,
    }
    persist_scored_contribution(event, _score())

    reopened_event = dict(event, action="reopened")
    result = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-reopened",
        event=reopened_event,
    )

    assert result["status"] == "accepted"


def test_register_webhook_delivery_reaccepts_synchronize_with_new_head_sha(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "maintainerki_synchronize.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 605,
        "kind": "pull_request",
        "action": "opened",
        "number": 64,
        "title": "PR that gets new commits",
        "body": "Same body throughout.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/pull/64",
        "head_sha": "sha-original",
    }
    persist_scored_contribution(event, _score())

    synchronize_event = dict(event, action="synchronize", head_sha="sha-updated")
    result = register_webhook_delivery(
        event_name="pull_request",
        delivery_id="delivery-synchronize",
        event=synchronize_event,
    )

    assert result["status"] == "accepted"


def test_register_webhook_delivery_dedupes_identical_redelivery(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_redeliver.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 606,
        "kind": "issue",
        "action": "opened",
        "number": 65,
        "title": "Issue that gets redelivered identically",
        "body": "Unchanged body.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/65",
        "head_sha": None,
    }
    persist_scored_contribution(event, _score())

    result = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-redelivered",
        event=event,
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "duplicate_content"


def test_stale_scoring_result_cannot_overwrite_newer_registered_snapshot(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "maintainerki_stale_score.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    older_event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 607,
        "kind": "pull_request",
        "action": "opened",
        "number": 66,
        "title": "Original title",
        "body": "Original body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/pull/66",
        "head_sha": "sha-original",
    }
    newer_event = dict(
        older_event,
        action="synchronize",
        title="Updated title",
        body="Updated body",
        head_sha="sha-newer",
    )

    assert register_webhook_delivery(
        event_name="pull_request",
        delivery_id="delivery-older",
        event=older_event,
    )["status"] == "accepted"
    assert register_webhook_delivery(
        event_name="pull_request",
        delivery_id="delivery-newer",
        event=newer_event,
    )["status"] == "accepted"

    assert persist_scored_contribution(older_event, _score()) is False

    detail = get_contribution_detail(1)
    assert detail is not None
    assert detail["status"] == "pending"
    assert detail["title"] == "Updated title"
    assert detail["body"] == "Updated body"

    assert persist_scored_contribution(newer_event, _score()) is True
    detail = get_contribution_detail(1)
    assert detail is not None
    assert detail["status"] == "scored"
    assert detail["title"] == "Updated title"
    assert detail["body"] == "Updated body"


def test_current_contribution_snapshot_rejects_stale_event(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_snapshot_lock.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    older_event = _contribution_event(
        repository="example/repo",
        repository_id=501,
        github_id=608,
        number=67,
        author="octocat",
        title="Older snapshot",
    )
    newer_event = dict(older_event, action="edited", title="Newer snapshot")
    assert register_webhook_delivery(
        event_name="issues",
        delivery_id="snapshot-older",
        event=older_event,
    )["status"] == "accepted"
    assert register_webhook_delivery(
        event_name="issues",
        delivery_id="snapshot-newer",
        event=newer_event,
    )["status"] == "accepted"

    with current_contribution_snapshot(older_event) as is_current:
        assert is_current is False
    with current_contribution_snapshot(newer_event) as is_current:
        assert is_current is True


def test_list_repositories_merges_renamed_repository_groups(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_rename.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    old_name_event = {
        "repository": "example/old-name",
        "repository_id": 900,
        "github_id": 701,
        "kind": "issue",
        "action": "opened",
        "number": 1,
        "title": "First issue, before rename",
        "body": "Body one",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/old-name/issues/1",
    }
    new_name_event = {
        "repository": "example/new-name",
        "repository_id": 900,
        "github_id": 702,
        "kind": "issue",
        "action": "opened",
        "number": 2,
        "title": "Second issue, after rename",
        "body": "Body two",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/new-name/issues/2",
    }

    persist_scored_contribution(old_name_event, _score())
    persist_scored_contribution(new_name_event, _score())

    old_timestamp = _sqlite_timestamp(datetime.now(timezone.utc) - timedelta(days=1))
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            "UPDATE contributions SET received_at = ? WHERE repository = ?",
            (old_timestamp, "example/old-name"),
        )

    repos = list_repositories()
    assert len(repos) == 1
    assert repos[0]["id"] == 900
    assert repos[0]["name"] == "example/new-name"
    assert repos[0]["contribution_count"] == 2
    assert repos[0]["scored_count"] == 2

    summary = get_repository_summary(900)
    assert summary is not None
    assert summary["name"] == "example/new-name"
    assert summary["contribution_count"] == 2

    stats = get_repo_stats(900)
    assert stats is not None
    assert stats["repository"]["contribution_count"] == 2


def test_list_repo_inbox_min_score_zero_includes_pending_rows(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_min_score.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 707,
        "kind": "issue",
        "action": "opened",
        "number": 70,
        "title": "Still pending, no score yet",
        "body": "Body",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/70",
    }
    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-min-score",
        event=event,
    )
    assert registration["status"] == "accepted"

    results_without_filter = list_repo_inbox(501)
    results_with_min_score_zero = list_repo_inbox(501, min_score=0)

    assert len(results_without_filter) == 1
    assert len(results_with_min_score_zero) == 1
    assert results_with_min_score_zero[0]["status"] == "pending"


def test_retention_purge_clears_orphaned_duplicate_flags(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_retention_duplicates.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    event = {
        "repository": "example/repo",
        "repository_id": 501,
        "github_id": 708,
        "kind": "issue",
        "action": "opened",
        "number": 71,
        "title": "Old possible duplicate",
        "body": "Body that will get scrubbed.",
        "author": "octocat",
        "sender": "octocat",
        "html_url": "https://github.com/example/repo/issues/71",
    }
    duplicates = DuplicateDetectionResult(
        provider="hashing",
        model="hashing-384d",
        threshold=0.8,
        possible_duplicate=True,
        top_similarity=0.95,
        candidates=[],
    )

    persist_scored_contribution(event, _score(), duplicate_result=duplicates)

    old_iso = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    with get_engine().begin() as connection:
        connection.exec_driver_sql(
            f"UPDATE contributions SET received_at = '{old_iso}', updated_at = '{old_iso}' WHERE id = 1"
        )

    apply_retention_purge(
        webhook_retention_days=30,
        contribution_body_retention_days=90,
        feedback_note_retention_days=30,
    )

    detail = get_contribution_detail(1)
    assert detail is not None
    assert detail["body"] == ""
    assert detail["duplicates"]["possible_duplicate"] is False
    assert detail["duplicates"]["top_similarity"] is None


def _contribution_event(
    *,
    repository: str,
    repository_id: int,
    github_id: int,
    number: int,
    author: str,
    title: str = "Contribution",
) -> dict[str, Any]:
    return {
        "repository": repository,
        "repository_id": repository_id,
        "github_id": github_id,
        "kind": "issue",
        "action": "opened",
        "number": number,
        "title": title,
        "body": "Body",
        "author": author,
        "sender": author,
        "html_url": f"https://github.com/{repository}/issues/{number}",
    }


def test_count_recent_contributions_by_author(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_velocity.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    recent_one = _contribution_event(
        repository="example/repo1", repository_id=501, github_id=901, number=201, author="octocat"
    )
    recent_two = _contribution_event(
        repository="example/repo2", repository_id=502, github_id=902, number=202, author="octocat"
    )
    stale = _contribution_event(
        repository="example/repo3", repository_id=503, github_id=903, number=203, author="octocat"
    )
    other_author = _contribution_event(
        repository="example/repo4", repository_id=504, github_id=904, number=204, author="other-cat"
    )

    persist_scored_contribution(recent_one, _score())
    persist_scored_contribution(recent_two, _score())
    persist_scored_contribution(stale, _score())
    persist_scored_contribution(other_author, _score())

    # Backdate the "stale" contribution's creation timestamp beyond the
    # velocity window via a direct ORM update inside a session.
    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=48)
    with Session(get_engine()) as session:
        record = session.execute(
            select(ContributionRecord).where(ContributionRecord.number == 203)
        ).scalar_one()
        record.received_at = old_timestamp
        session.commit()

    assert count_recent_contributions_by_author("octocat", within_hours=24) == 2
    # Case-insensitive author matching.
    assert count_recent_contributions_by_author("OctoCat", within_hours=24) == 2
    # Excluding the "current" contribution leaves just the other recent one.
    assert (
        count_recent_contributions_by_author(
            "octocat",
            within_hours=24,
            exclude=("example/repo1", "issue", 201),
        )
        == 1
    )
    # A different author is not counted.
    assert count_recent_contributions_by_author("other-cat", within_hours=24) == 1
    # Empty/None author short-circuits to zero without querying.
    assert count_recent_contributions_by_author("", within_hours=24) == 0
    assert count_recent_contributions_by_author(None, within_hours=24) == 0  # type: ignore[arg-type]


def test_count_author_contributions_in_repository(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_author_counts.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    first_in_repo = _contribution_event(
        repository="example/repo1", repository_id=501, github_id=911, number=301, author="octocat"
    )
    second_in_repo = _contribution_event(
        repository="example/repo1", repository_id=501, github_id=912, number=302, author="octocat"
    )
    in_other_repo = _contribution_event(
        repository="example/repo2", repository_id=502, github_id=913, number=303, author="octocat"
    )

    persist_scored_contribution(first_in_repo, _score())
    persist_scored_contribution(second_in_repo, _score())
    persist_scored_contribution(in_other_repo, _score())

    assert count_author_contributions_in_repository("octocat", "example/repo1") == 2
    # Case-insensitive on both author and repository.
    assert count_author_contributions_in_repository("OctoCat", "EXAMPLE/repo1") == 2
    # Scoped per repository.
    assert count_author_contributions_in_repository("octocat", "example/repo2") == 1
    # Excluding the current contribution (kind + number) leaves just the other one.
    assert (
        count_author_contributions_in_repository(
            "octocat",
            "example/repo1",
            exclude_kind="issue",
            exclude_number=301,
        )
        == 1
    )
    # Empty author short-circuits to zero without querying.
    assert count_author_contributions_in_repository("", "example/repo1") == 0
