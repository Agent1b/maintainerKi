from __future__ import annotations

from server import db as db_module
from server.db import get_engine, init_database
from server.duplicates.models import DuplicateCandidate, DuplicateDetectionResult, EmbeddingResult
from server.models import Base
from server.repository import (
    list_recent_contributions,
    list_repository_duplicate_candidates,
    persist_failed_contribution,
    persist_scored_contribution,
)
from server.scorer.models import ScoreResult


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


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

from server.repository import create_scoring_feedback, get_contribution_detail, get_repo_stats, register_webhook_delivery


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
