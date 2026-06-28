from __future__ import annotations

from server.duplicates.models import DuplicateCandidate, DuplicateDetectionResult, EmbeddingResult
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
    monkeypatch.setattr("server.ingestion.persist_scored_contribution", lambda *args, **kwargs: None)
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
