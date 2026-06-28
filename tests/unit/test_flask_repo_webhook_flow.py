from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server import db as db_module
from server.db import ensure_schema_upgrades, get_engine, init_database
from server.main import app
from server.models import Base
from server.scorer.models import ScoreResult
from server.webhooks.security import build_github_signature

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FLASK_ISSUE_FIXTURE = FIXTURES_DIR / "github_flask_issue_opened.json"
FLASK_PR_FIXTURE = FIXTURES_DIR / "github_flask_pr_opened.json"
WEBHOOK_SECRET = "test-secret"


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def _configure_runtime(monkeypatch, db_path: Path) -> None:
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    monkeypatch.setattr("server.config.settings.app_env", "test")
    monkeypatch.setattr("server.config.settings.admin_auth_enabled", False)
    monkeypatch.setattr("server.config.settings.celery_enabled", False)
    monkeypatch.setattr("server.config.settings.monitored_repositories", "pallets/flask")
    monkeypatch.setattr("server.webhooks.github.settings.monitored_repositories", "pallets/flask")
    monkeypatch.setattr("server.config.settings.github_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
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

    def fake_score(contribution):  # noqa: ANN001
        if contribution.kind == "issue":
            return ScoreResult(
                quality=84,
                relevance=88,
                completeness=72,
                suspicion=8,
                overall_score=83,
                summary="Legitimate feature request with enough detail for maintainer review.",
                suggested_labels=["maintainerki:review-first", "feature-request"],
                provider="mock",
                model="heuristic-v1",
                prompt_version="phase2-v1",
            )

        return ScoreResult(
            quality=87,
            relevance=90,
            completeness=78,
            suspicion=7,
            overall_score=86,
            summary="Concrete framework pull request with clear implementation intent.",
            suggested_labels=["maintainerki:review-first", "pull-request"],
            provider="mock",
            model="heuristic-v1",
            prompt_version="phase2-v1",
        )

    monkeypatch.setattr("server.ingestion.score_contribution", fake_score)
    monkeypatch.setattr("server.ingestion.detect_duplicates", lambda contribution: (None, None))
    monkeypatch.setattr("server.ingestion.record_scoring_result", lambda result: None)
    monkeypatch.setattr("server.ingestion.apply_score_labels", lambda event, result, **kwargs: False)
    monkeypatch.setattr(
        "server.ingestion.build_github_client",
        lambda: type("DummyClient", (), {"is_configured": lambda self: False})(),
    )


def _load_payload(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _post_github_event(
    client: TestClient,
    *,
    event_name: str,
    delivery_id: str,
    payload: dict[str, object],
) -> None:
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event_name,
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": build_github_signature(WEBHOOK_SECRET, body),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_flask_issue_and_pr_flow_through_webhook_to_dashboard(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_flask_flow.db"
    _configure_runtime(monkeypatch, db_path)

    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()

    with TestClient(app) as client:
        _post_github_event(
            client,
            event_name="issues",
            delivery_id="flask-issue-6065",
            payload=_load_payload(FLASK_ISSUE_FIXTURE),
        )
        _post_github_event(
            client,
            event_name="pull_request",
            delivery_id="flask-pr-6066",
            payload=_load_payload(FLASK_PR_FIXTURE),
        )

        repos_response = client.get("/api/repos")
        assert repos_response.status_code == 200
        repos_payload = repos_response.json()
        assert repos_payload["count"] == 1
        assert repos_payload["repositories"][0]["id"] == 596892
        assert repos_payload["repositories"][0]["name"] == "pallets/flask"
        assert repos_payload["repositories"][0]["contribution_count"] == 2
        assert repos_payload["repositories"][0]["scored_count"] == 2

        repo_id = repos_payload["repositories"][0]["id"]
        inbox_response = client.get(f"/api/repos/{repo_id}/inbox")
        assert inbox_response.status_code == 200
        inbox_payload = inbox_response.json()
        assert inbox_payload["count"] == 2
        assert inbox_payload["repository"]["name"] == "pallets/flask"
        assert {item["kind"] for item in inbox_payload["items"]} == {"issue", "pull_request"}
        assert {item["number"] for item in inbox_payload["items"]} == {6065, 6066}

        issue_item = next(item for item in inbox_payload["items"] if item["kind"] == "issue")
        detail_response = client.get(f"/api/contributions/{issue_item['id']}")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["repository"] == "pallets/flask"
        assert detail_payload["number"] == 6065
        assert detail_payload["score"]["overall_score"] == 83
        assert detail_payload["score"]["provider"] == "mock"
        assert detail_payload["html_url"] == "https://github.com/pallets/flask/issues/6065"


def test_flask_fixture_repo_filter_blocks_unrelated_repositories(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_flask_repo_filter.db"
    _configure_runtime(monkeypatch, db_path)

    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()

    payload = _load_payload(FLASK_ISSUE_FIXTURE)
    payload["repository"] = {"id": 123, "full_name": "other/repo"}
    payload["issue"]["html_url"] = "https://github.com/other/repo/issues/1"
    payload["issue"]["number"] = 1
    payload["issue"]["id"] = 999001

    with TestClient(app) as client:
        body = json.dumps(payload).encode("utf-8")
        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "other-repo-issue-1",
                "X-Hub-Signature-256": build_github_signature(WEBHOOK_SECRET, body),
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["reason"] == "repository_not_monitored"
        assert client.get("/api/repos").json()["count"] == 0
