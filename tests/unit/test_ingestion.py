from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from server import db as db_module
from server.config import settings
from server.db import get_engine, init_database
from server.duplicates.models import DuplicateCandidate, DuplicateDetectionResult, EmbeddingResult
from server.enrichment import enrich_contribution
from server.ingestion import (
    enqueue_contribution_event,
    enqueue_webhook_delivery,
    process_contribution_event,
    process_webhook_delivery,
)
from server.models import Base
from server.models.tables import WebhookDeliveryRecord
from server.repository import register_webhook_delivery
from server.scorer.models import ContributionInput, ScoreResult


@pytest.fixture(autouse=True)
def _current_snapshot_by_default(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(
        "server.ingestion.current_contribution_snapshot",
        lambda event: nullcontext(True),
    )


def _event() -> dict[str, object]:
    return {
        "kind": "issue",
        "action": "opened",
        "github_id": 101,
        "number": 42,
        "title": "Webhook retry issue",
        "body": "Steps to reproduce included.",
        "html_url": "https://github.com/example/repo/issues/42",
        "repository": "example/repo",
        "repository_id": 501,
        "author": "octocat",
        "sender": "sendercat",
        "head_sha": None,
    }


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def test_enqueue_webhook_delivery_uses_celery_when_available(monkeypatch) -> None:
    queued: list[str] = []
    monkeypatch.setattr("server.ingestion._queue_expected", lambda: True)
    monkeypatch.setattr(
        "server.ingestion._enqueue_with_celery",
        lambda delivery_id: queued.append(delivery_id) or True,
    )
    marks: list[str] = []
    monkeypatch.setattr("server.ingestion.mark_webhook_delivery_queued", marks.append)

    result = enqueue_webhook_delivery("delivery-123")

    assert result is True
    assert queued == ["delivery-123"]
    assert marks == ["delivery-123"]


def test_enqueue_webhook_delivery_marks_queued_before_dispatch(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr("server.ingestion._queue_expected", lambda: True)
    monkeypatch.setattr(
        "server.ingestion.mark_webhook_delivery_queued",
        lambda delivery_id: order.append("queued"),
    )
    monkeypatch.setattr(
        "server.ingestion._enqueue_with_celery",
        lambda delivery_id: order.append("dispatched") or True,
    )

    result = enqueue_webhook_delivery("delivery-123")

    assert result is True
    assert order == ["queued", "dispatched"]


def test_enqueue_webhook_delivery_marks_queue_failure_when_broker_is_down(monkeypatch) -> None:
    monkeypatch.setattr("server.ingestion._queue_expected", lambda: True)
    monkeypatch.setattr("server.ingestion._enqueue_with_celery", lambda delivery_id: False)
    queued: list[str] = []
    monkeypatch.setattr("server.ingestion.mark_webhook_delivery_queued", queued.append)
    failures: list[tuple[str, str]] = []
    monkeypatch.setattr("server.ingestion.mark_webhook_delivery_queue_failed", lambda delivery_id, message: failures.append((delivery_id, message)))
    invoked: list[str] = []
    monkeypatch.setattr("server.ingestion.process_webhook_delivery", invoked.append)

    result = enqueue_webhook_delivery("delivery-123")

    assert result is False
    assert invoked == []
    assert queued == ["delivery-123"]
    assert failures and failures[0][0] == "delivery-123"


def test_enqueue_contribution_event_still_processes_direct_events(monkeypatch) -> None:
    invoked: list[dict[str, object]] = []
    monkeypatch.setattr("server.ingestion.process_contribution_event", invoked.append)

    enqueue_contribution_event(_event())

    assert invoked == [_event()]


def test_process_contribution_event_scores_the_enriched_contribution(monkeypatch) -> None:
    enriched = ContributionInput.from_event(_event()).model_copy(
        update={"author_recent_contributions": 7}
    )
    enrich_calls: list[ContributionInput] = []

    def fake_enrich(contribution: ContributionInput) -> ContributionInput:
        enrich_calls.append(contribution)
        return enriched

    monkeypatch.setattr("server.ingestion.enrich_contribution", fake_enrich)

    score = ScoreResult(
        quality=80,
        relevance=77,
        completeness=74,
        suspicion=9,
        overall_score=78,
        summary="Solid contribution with enough detail to review.",
        suggested_labels=["maintainerki:worth-a-look"],
        provider="mock",
        model="heuristic-v1",
        prompt_version="phase2-v3",
    )
    scored_with: list[ContributionInput] = []

    def fake_score_contribution(contribution: ContributionInput) -> ScoreResult:
        scored_with.append(contribution)
        return score

    monkeypatch.setattr("server.ingestion.score_contribution", fake_score_contribution)
    monkeypatch.setattr("server.ingestion.detect_duplicates", lambda contribution: (None, None))
    monkeypatch.setattr("server.ingestion.persist_scored_contribution", lambda *a, **k: True)
    monkeypatch.setattr("server.ingestion.record_scoring_result", lambda result: None)
    monkeypatch.setattr("server.ingestion.apply_score_labels", lambda *a, **k: False)
    monkeypatch.setattr(
        "server.ingestion.build_github_client",
        lambda: type("DummyClient", (), {"is_configured": lambda self: False})(),
    )

    process_contribution_event(_event())

    assert enrich_calls == [ContributionInput.from_event(_event())]
    assert scored_with == [enriched]


def test_process_contribution_event_applies_labels_after_scoring(monkeypatch) -> None:
    score = ScoreResult(
        quality=80,
        relevance=77,
        completeness=74,
        suspicion=9,
        overall_score=78,
        summary="Solid contribution with enough detail to review.",
        suggested_labels=["maintainerki:worth-a-look"],
        provider="mock",
        model="heuristic-v1",
        prompt_version="phase2-v1",
    )

    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr(
        "server.ingestion.detect_duplicates",
        lambda contribution: (
            EmbeddingResult(
                provider="hashing",
                model="hashing-384d",
                normalized_text="webhook retry issue steps to reproduce included",
                embedding=[0.2, 0.3, 0.4],
            ),
            DuplicateDetectionResult(
                provider="hashing",
                model="hashing-384d",
                threshold=0.8,
                possible_duplicate=True,
                top_similarity=0.87,
                candidates=[],
            ),
        ),
    )
    persisted: list[tuple[dict[str, object], ScoreResult]] = []
    monkeypatch.setattr(
        "server.ingestion.persist_scored_contribution",
        lambda event, result, **kwargs: persisted.append((event, result)),
    )
    monkeypatch.setattr("server.ingestion.record_scoring_result", lambda result: None)
    monkeypatch.setattr(
        "server.ingestion.apply_score_labels",
        lambda event, result, **kwargs: True,
    )
    monkeypatch.setattr("server.ingestion.settings.github_duplicate_comments_enabled", False)
    monkeypatch.setattr(
        "server.ingestion.build_github_client",
        lambda: type("DummyClient", (), {"is_configured": lambda self: False})(),
    )

    process_contribution_event(_event())

    assert persisted == [(_event(), score)]
    assert "maintainerki:possible-duplicate" in score.suggested_labels


def test_process_contribution_event_posts_duplicate_comment_when_writeback_applies(monkeypatch) -> None:
    score = ScoreResult(
        quality=82,
        relevance=79,
        completeness=75,
        suspicion=8,
        overall_score=80,
        summary="High-signal contribution that overlaps with an existing report.",
        suggested_labels=["maintainerki:review-first"],
        provider="mock",
        model="heuristic-v1",
        prompt_version="phase2-v1",
    )

    duplicate_result = DuplicateDetectionResult(
        provider="hashing",
        model="hashing-384d",
        threshold=0.8,
        possible_duplicate=True,
        top_similarity=0.93,
        candidates=[
            DuplicateCandidate(
                contribution_id=7,
                repository="example/repo",
                kind="issue",
                number=11,
                title="Webhook retries create duplicate scoring jobs",
                html_url="https://github.com/example/repo/issues/11",
                similarity=0.93,
            )
        ],
    )

    class DummyClient:
        def __init__(self) -> None:
            self.comments: list[dict[str, object]] = []

        def is_configured(self) -> bool:
            return True

        def create_issue_comment(
            self,
            *,
            repository_full_name: str,
            number: int,
            body: str,
            marker: str,
        ) -> None:
            self.comments.append(
                {
                    "repository_full_name": repository_full_name,
                    "number": number,
                    "body": body,
                    "marker": marker,
                }
            )

    dummy_client = DummyClient()

    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr(
        "server.ingestion.detect_duplicates",
        lambda contribution: (
            EmbeddingResult(
                provider="hashing",
                model="hashing-384d",
                normalized_text="webhook retry issue steps to reproduce included",
                embedding=[0.2, 0.3, 0.4],
            ),
            duplicate_result,
        ),
    )
    monkeypatch.setattr("server.ingestion.persist_scored_contribution", lambda *args, **kwargs: True)
    monkeypatch.setattr("server.ingestion.record_scoring_result", lambda result: None)
    monkeypatch.setattr("server.ingestion.apply_score_labels", lambda *args, **kwargs: True)
    monkeypatch.setattr("server.ingestion.settings.github_duplicate_comments_enabled", True)
    monkeypatch.setattr("server.ingestion.build_github_client", lambda: dummy_client)

    process_contribution_event(_event())

    assert len(dummy_client.comments) == 1
    assert dummy_client.comments[0]["repository_full_name"] == "example/repo"
    assert dummy_client.comments[0]["number"] == 42
    assert dummy_client.comments[0]["marker"] == "<!-- maintainerki:possible-duplicate -->"
    assert "Webhook retries create duplicate scoring jobs" in str(dummy_client.comments[0]["body"])
    assert "#11 (issue, 93% similar)" in str(dummy_client.comments[0]["body"])


def test_process_contribution_event_reraises_and_skips_writeback_on_persistence_failure(
    monkeypatch,
) -> None:
    score = ScoreResult(
        quality=80,
        relevance=77,
        completeness=74,
        suspicion=9,
        overall_score=78,
        summary="Solid contribution with enough detail to review.",
        suggested_labels=["maintainerki:worth-a-look"],
        provider="mock",
        model="heuristic-v1",
        prompt_version="phase2-v1",
    )

    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr(
        "server.ingestion.detect_duplicates",
        lambda contribution: (None, None),
    )

    def _raise_persistence_error(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is gone")

    monkeypatch.setattr("server.ingestion.persist_scored_contribution", _raise_persistence_error)
    writeback_calls: list[object] = []
    monkeypatch.setattr(
        "server.ingestion.apply_score_labels",
        lambda *a, **k: writeback_calls.append((a, k)) or True,
    )
    record_calls: list[object] = []
    monkeypatch.setattr(
        "server.ingestion.record_scoring_result",
        lambda result: record_calls.append(result),
    )

    with pytest.raises(SQLAlchemyError):
        process_contribution_event(_event())

    assert writeback_calls == []
    assert record_calls == []


def test_process_contribution_event_skips_writeback_for_stale_result(monkeypatch) -> None:
    score = ScoreResult(
        quality=80,
        relevance=80,
        completeness=80,
        suspicion=10,
        overall_score=80,
        summary="A useful contribution.",
        suggested_labels=["maintainerki:review-first"],
        provider="mock",
        model="mock",
        prompt_version="test",
    )
    monkeypatch.setattr(
        "server.ingestion.enrich_contribution",
        lambda contribution: contribution,
    )
    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr("server.ingestion.detect_duplicates", lambda contribution: (None, None))
    monkeypatch.setattr(
        "server.ingestion.persist_scored_contribution",
        lambda *args, **kwargs: False,
    )
    writeback_calls: list[object] = []
    monkeypatch.setattr(
        "server.ingestion.apply_score_labels",
        lambda *args, **kwargs: writeback_calls.append((args, kwargs)) or True,
    )
    recorded_results: list[dict[str, object]] = []
    monkeypatch.setattr(
        "server.ingestion.record_scoring_result",
        lambda result: recorded_results.append(result),
    )

    process_contribution_event(_event())

    assert writeback_calls == []
    assert recorded_results == []


def test_process_contribution_event_rechecks_snapshot_before_side_effects(monkeypatch) -> None:
    score = ScoreResult(
        quality=80,
        relevance=80,
        completeness=80,
        suspicion=10,
        overall_score=80,
        summary="A useful contribution.",
        suggested_labels=["maintainerki:review-first"],
        provider="mock",
        model="mock",
        prompt_version="test",
    )
    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr("server.ingestion.detect_duplicates", lambda contribution: (None, None))
    monkeypatch.setattr(
        "server.ingestion.persist_scored_contribution",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "server.ingestion.current_contribution_snapshot",
        lambda event: nullcontext(False),
    )
    writeback_calls: list[object] = []
    monkeypatch.setattr(
        "server.ingestion.apply_score_labels",
        lambda *args, **kwargs: writeback_calls.append((args, kwargs)) or True,
    )
    recorded_results: list[dict[str, object]] = []
    monkeypatch.setattr(
        "server.ingestion.record_scoring_result",
        lambda result: recorded_results.append(result),
    )

    process_contribution_event(_event())

    assert writeback_calls == []
    assert recorded_results == []


def test_process_webhook_delivery_marks_failed_when_persistence_fails(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_ingestion_failure.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())

    registration = register_webhook_delivery(
        event_name="issues",
        delivery_id="delivery-persist-fail",
        event=_event(),
    )
    assert registration["status"] == "accepted"

    score = ScoreResult(
        quality=80,
        relevance=77,
        completeness=74,
        suspicion=9,
        overall_score=78,
        summary="Solid contribution with enough detail to review.",
        suggested_labels=["maintainerki:worth-a-look"],
        provider="mock",
        model="heuristic-v1",
        prompt_version="phase2-v1",
    )

    monkeypatch.setattr("server.ingestion.score_contribution", lambda contribution: score)
    monkeypatch.setattr("server.ingestion.detect_duplicates", lambda contribution: (None, None))

    def _raise_persistence_error(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is gone")

    monkeypatch.setattr("server.ingestion.persist_scored_contribution", _raise_persistence_error)
    writeback_calls: list[object] = []
    monkeypatch.setattr(
        "server.ingestion.apply_score_labels",
        lambda *a, **k: writeback_calls.append((a, k)) or True,
    )
    monkeypatch.setattr("server.ingestion.record_scoring_result", lambda result: None)

    with pytest.raises(SQLAlchemyError):
        process_webhook_delivery("delivery-persist-fail")

    assert writeback_calls == []

    with Session(get_engine()) as session:
        delivery = session.execute(
            select(WebhookDeliveryRecord).where(
                WebhookDeliveryRecord.delivery_id == "delivery-persist-fail"
            )
        ).scalar_one()
        assert delivery.status == "failed"
        assert delivery.error_message and "SQLAlchemyError" in delivery.error_message


# --- server.enrichment.enrich_contribution -----------------------------------
#
# These tests monkeypatch the contract functions from server.repository and
# server.github_client rather than depending on their real implementations,
# per the parallel-development contract for this phase.


class _FakeGitHubClient:
    def __init__(
        self,
        *,
        configured: bool = True,
        created_at: datetime | None = None,
        files: list[dict[str, object]] | None = None,
        files_error: Exception | None = None,
    ) -> None:
        self.configured = configured
        self.created_at = created_at
        self.files = files if files is not None else []
        self.files_error = files_error
        self.created_at_calls: list[tuple[str, str]] = []
        self.files_calls: list[tuple[str, int]] = []

    def is_configured(self) -> bool:
        return self.configured

    def get_user_created_at(self, username: str, *, repository_full_name: str) -> datetime | None:
        self.created_at_calls.append((username, repository_full_name))
        return self.created_at

    def get_pull_request_files(
        self, repository_full_name: str, number: int, *, max_files: int
    ) -> list[dict[str, object]]:
        self.files_calls.append((repository_full_name, number))
        if self.files_error is not None:
            raise self.files_error
        return self.files


def _contribution(**overrides: object) -> ContributionInput:
    fields: dict[str, object] = {
        "kind": "issue",
        "action": "opened",
        "title": "Report a bug",
        "body": "Steps to reproduce included.",
        "repository": "example/repo",
        "author": "octocat",
        "number": 1,
    }
    fields.update(overrides)
    return ContributionInput(**fields)


def test_enrich_contribution_populates_velocity_and_history_from_db(monkeypatch) -> None:
    monkeypatch.setattr("server.enrichment.settings.github_enrichment_enabled", False)
    velocity_calls: list[tuple[object, ...]] = []
    history_calls: list[tuple[object, ...]] = []

    def fake_recent(author, *, within_hours, exclude):  # noqa: ANN001
        velocity_calls.append((author, within_hours, exclude))
        return 5

    def fake_previous(author, repository, *, exclude_kind=None, exclude_number=None):  # noqa: ANN001
        history_calls.append((author, repository, exclude_kind, exclude_number))
        return 3

    monkeypatch.setattr("server.enrichment.count_recent_contributions_by_author", fake_recent)
    monkeypatch.setattr(
        "server.enrichment.count_author_contributions_in_repository", fake_previous
    )

    contribution = _contribution(author="octocat", repository="example/repo", kind="issue", number=9)

    enriched = enrich_contribution(contribution)

    # The scoring velocity count includes the contribution currently being
    # processed, while the database query excludes it to avoid double-counting
    # updates to an existing issue or pull request.
    assert enriched.author_recent_contributions == 6
    assert enriched.author_previous_contributions == 3
    assert velocity_calls == [
        ("octocat", settings.velocity_window_hours, ("example/repo", "issue", 9))
    ]
    assert history_calls == [("octocat", "example/repo", "issue", 9)]
    # enrich_contribution returns a copy; the input is left untouched.
    assert contribution.author_recent_contributions is None


def test_enrich_contribution_survives_github_api_failure(monkeypatch) -> None:
    monkeypatch.setattr("server.enrichment.settings.github_enrichment_enabled", True)
    monkeypatch.setattr(
        "server.enrichment.count_recent_contributions_by_author", lambda *a, **k: 2
    )
    monkeypatch.setattr(
        "server.enrichment.count_author_contributions_in_repository", lambda *a, **k: 1
    )
    fake_client = _FakeGitHubClient(
        configured=True,
        created_at=None,
        files_error=RuntimeError("GitHub API is down"),
    )
    monkeypatch.setattr("server.enrichment.build_github_client", lambda: fake_client)

    contribution = _contribution(kind="pull_request", number=42)

    enriched = enrich_contribution(contribution)

    assert enriched.author_recent_contributions == 3
    assert enriched.author_previous_contributions == 1
    assert enriched.diff_excerpt is None
    assert enriched.changed_filenames is None


def test_enrich_contribution_skips_api_calls_when_enrichment_disabled(monkeypatch) -> None:
    monkeypatch.setattr("server.enrichment.settings.github_enrichment_enabled", False)
    monkeypatch.setattr(
        "server.enrichment.count_recent_contributions_by_author", lambda *a, **k: 4
    )
    monkeypatch.setattr(
        "server.enrichment.count_author_contributions_in_repository", lambda *a, **k: 6
    )
    build_calls: list[bool] = []

    def fail_if_called():
        build_calls.append(True)
        raise AssertionError(
            "build_github_client should not be called when enrichment is disabled"
        )

    monkeypatch.setattr("server.enrichment.build_github_client", fail_if_called)

    contribution = _contribution(kind="pull_request", number=43)

    enriched = enrich_contribution(contribution)

    assert build_calls == []
    assert enriched.author_recent_contributions == 5
    assert enriched.author_previous_contributions == 6
    assert enriched.author_account_age_days is None
    assert enriched.diff_excerpt is None


def test_enrich_contribution_caches_account_age_per_author(monkeypatch) -> None:
    monkeypatch.setattr("server.enrichment._account_age_cache", {})
    monkeypatch.setattr("server.enrichment.settings.github_enrichment_enabled", True)
    monkeypatch.setattr(
        "server.enrichment.count_recent_contributions_by_author", lambda *a, **k: 0
    )
    monkeypatch.setattr(
        "server.enrichment.count_author_contributions_in_repository", lambda *a, **k: 0
    )
    created_at = datetime.now(timezone.utc) - timedelta(days=200)
    fake_client = _FakeGitHubClient(configured=True, created_at=created_at, files=[])
    monkeypatch.setattr("server.enrichment.build_github_client", lambda: fake_client)

    first = enrich_contribution(_contribution(author="cache-test-user", kind="issue", number=1))
    second = enrich_contribution(_contribution(author="cache-test-user", kind="issue", number=2))

    assert len(fake_client.created_at_calls) == 1
    assert first.author_account_age_days == 200
    assert second.author_account_age_days == 200
