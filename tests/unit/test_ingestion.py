from __future__ import annotations

from server.duplicates.models import DuplicateDetectionResult, EmbeddingResult
from server.ingestion import enqueue_contribution_event, enqueue_webhook_delivery, process_contribution_event
from server.scorer.models import ScoreResult


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
    }


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


def test_enqueue_webhook_delivery_marks_queue_failure_when_broker_is_down(monkeypatch) -> None:
    monkeypatch.setattr("server.ingestion._queue_expected", lambda: True)
    monkeypatch.setattr("server.ingestion._enqueue_with_celery", lambda delivery_id: False)
    failures: list[tuple[str, str]] = []
    monkeypatch.setattr("server.ingestion.mark_webhook_delivery_queue_failed", lambda delivery_id, message: failures.append((delivery_id, message)))
    invoked: list[str] = []
    monkeypatch.setattr("server.ingestion.process_webhook_delivery", invoked.append)

    result = enqueue_webhook_delivery("delivery-123")

    assert result is False
    assert invoked == []
    assert failures and failures[0][0] == "delivery-123"


def test_enqueue_contribution_event_still_processes_direct_events(monkeypatch) -> None:
    invoked: list[dict[str, object]] = []
    monkeypatch.setattr("server.ingestion.process_contribution_event", invoked.append)

    enqueue_contribution_event(_event())

    assert invoked == [_event()]


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
