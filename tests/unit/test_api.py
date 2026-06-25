from __future__ import annotations

from fastapi.testclient import TestClient

from server import db as db_module
from server.db import ensure_schema_upgrades, get_engine, init_database
from server.main import app
from server.models import Base
from server.repository import persist_scored_contribution
from server.scorer.models import ScoreResult


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def _seed_contribution() -> None:
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


def test_dashboard_api_endpoints(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_api.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    monkeypatch.setattr(
        "server.main.build_readiness_status",
        lambda: {
            "status": "ok",
            "environment": "test",
            "components": {
                "database": {"ok": True},
                "redis": {"ok": True},
                "worker": {"ok": True},
                "github_app": {"ok": True},
            },
        },
    )
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    _seed_contribution()

    with TestClient(app) as client:
        health_response = client.get("/healthz")
        assert health_response.status_code == 200
        assert health_response.json()["database"]["backend"] == "sqlite"
        assert health_response.json()["database"]["using_sqlite_fallback"] is False
        ready_response = client.get("/readyz")
        assert ready_response.status_code == 200
        assert ready_response.json()["status"] == "ok"

        repos_response = client.get("/api/repos")
        assert repos_response.status_code == 200
        repos_payload = repos_response.json()
        assert repos_payload["count"] == 1
        repo_id = repos_payload["repositories"][0]["id"]

        inbox_response = client.get(f"/api/repos/{repo_id}/inbox")
        assert inbox_response.status_code == 200
        inbox_payload = inbox_response.json()
        assert inbox_payload["count"] == 1
        contribution_id = inbox_payload["items"][0]["id"]

        stats_response = client.get(f"/api/repos/{repo_id}/stats")
        assert stats_response.status_code == 200
        stats_payload = stats_response.json()
        assert stats_payload["repository"]["id"] == repo_id
        assert stats_payload["score_distribution"]["high"] == 1

        detail_response = client.get(f"/api/contributions/{contribution_id}")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["score"]["overall_score"] == 83
        assert detail_payload["feedback"] == []

        feedback_response = client.post(
            f"/api/contributions/{contribution_id}/feedback",
            json={
                "maintainer_action": "agreed",
                "correct_labels": ["documentation"],
                "notes": "This score looks right.",
            },
        )
        assert feedback_response.status_code == 200
        feedback_payload = feedback_response.json()
        assert feedback_payload["feedback"]["maintainer_action"] == "agreed"
        assert feedback_payload["contribution"]["feedback"][0]["notes"] == "This score looks right."


def test_dashboard_api_404s_for_missing_resources(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_api_missing.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()

    with TestClient(app) as client:
        assert client.get("/api/repos/999/inbox").status_code == 404
        assert client.get("/api/repos/999/stats").status_code == 404
        assert client.get("/api/contributions/999").status_code == 404
        assert (
            client.post(
                "/api/contributions/999/feedback",
                json={"maintainer_action": "agreed", "correct_labels": [], "notes": None},
            ).status_code
            == 404
        )


def test_readyz_returns_503_when_a_dependency_is_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "server.main.build_readiness_status",
        lambda: {
            "status": "degraded",
            "environment": "test",
            "components": {
                "database": {"ok": True},
                "redis": {"ok": True},
                "worker": {"ok": False, "error": "No Celery workers responded to ping."},
                "github_app": {"ok": True},
            },
        },
    )

    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "degraded"
        assert payload["components"]["worker"]["ok"] is False


def test_debug_routes_return_404_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr("server.debug.settings.debug_api_enabled", False)

    with TestClient(app) as client:
        response = client.get("/debug/contributions")
        assert response.status_code == 404
