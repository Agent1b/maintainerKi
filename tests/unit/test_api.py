from __future__ import annotations

from fastapi.testclient import TestClient

from server.auth import hash_password
from server import db as db_module
from server.db import ensure_schema_upgrades, get_engine, init_database
from server.main import app, create_app
from server.models import Base
from server.rate_limit import rate_limiter
from server.repository import persist_scored_contribution
from server.scorer.models import ScoreResult

SAME_ORIGIN_HEADERS = {"Origin": "http://testserver"}


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


def _configure_admin_auth(
    monkeypatch,
    *,
    enabled: bool,
    session_cookie_secure: bool = False,
    password_hash: str = "",
    password: str = "",
) -> None:
    monkeypatch.setattr("server.config.settings.admin_auth_enabled", enabled)
    monkeypatch.setattr("server.config.settings.admin_username", "admin")
    monkeypatch.setattr("server.config.settings.admin_password_hash", password_hash)
    monkeypatch.setattr("server.config.settings.admin_password", password)
    monkeypatch.setattr(
        "server.config.settings.session_secret",
        "test-session-secret-that-is-long-enough",
    )
    monkeypatch.setattr("server.config.settings.session_cookie_secure", session_cookie_secure)
    monkeypatch.setattr("server.config.settings.session_ttl_seconds", 3600)


def test_dashboard_api_endpoints(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_api.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _configure_admin_auth(monkeypatch, enabled=False)
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
        assert feedback_payload["feedback"]["actor_username"] is None
        assert feedback_payload["contribution"]["feedback"][0]["notes"] == "This score looks right."


def test_dashboard_api_404s_for_missing_resources(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_api_missing.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _configure_admin_auth(monkeypatch, enabled=False)
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
    _configure_admin_auth(monkeypatch, enabled=False)
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
    _configure_admin_auth(monkeypatch, enabled=False)
    monkeypatch.setattr("server.debug.settings.debug_api_enabled", False)

    with TestClient(app) as client:
        response = client.get("/debug/contributions")
        assert response.status_code == 404


def test_admin_auth_requires_login_for_dashboard_api(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_auth_required.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _configure_admin_auth(monkeypatch, enabled=True, password="let-me-in")
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    _seed_contribution()

    with TestClient(app) as client:
        session_response = client.get("/api/auth/session")
        assert session_response.status_code == 200
        assert session_response.json() == {
            "auth_enabled": True,
            "authenticated": False,
            "username": None,
        }

        repos_response = client.get("/api/repos")
        assert repos_response.status_code == 401
        assert repos_response.json()["detail"] == "Authentication required."


def test_admin_auth_login_round_trip_with_hashed_password(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_auth_login.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _configure_admin_auth(
        monkeypatch,
        enabled=True,
        password_hash=hash_password("let-me-in"),
    )
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    _seed_contribution()

    with TestClient(app) as client:
        bad_login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert bad_login.status_code == 401

        good_login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "let-me-in"},
        )
        assert good_login.status_code == 204

        session_response = client.get("/api/auth/session")
        assert session_response.status_code == 200
        assert session_response.json() == {
            "auth_enabled": True,
            "authenticated": True,
            "username": "admin",
        }

        repos_response = client.get("/api/repos")
        assert repos_response.status_code == 200
        assert repos_response.json()["count"] == 1

        logout_response = client.post("/api/auth/logout", headers=SAME_ORIGIN_HEADERS)
        assert logout_response.status_code == 204

        repos_after_logout = client.get("/api/repos")
        assert repos_after_logout.status_code == 401


def test_admin_state_changing_routes_require_allowed_origin(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_auth_origin.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    _configure_admin_auth(
        monkeypatch,
        enabled=True,
        password_hash=hash_password("let-me-in"),
    )
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    _seed_contribution()

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "let-me-in"},
        )
        assert login.status_code == 204

        repo_id = client.get("/api/repos").json()["repositories"][0]["id"]
        contribution_id = client.get(f"/api/repos/{repo_id}/inbox").json()["items"][0]["id"]

        missing_origin_feedback = client.post(
            f"/api/contributions/{contribution_id}/feedback",
            json={"maintainer_action": "agreed", "correct_labels": [], "notes": None},
        )
        assert missing_origin_feedback.status_code == 403

        foreign_origin_feedback = client.post(
            f"/api/contributions/{contribution_id}/feedback",
            headers={"Origin": "https://evil.example.com"},
            json={"maintainer_action": "agreed", "correct_labels": [], "notes": None},
        )
        assert foreign_origin_feedback.status_code == 403

        same_origin_feedback = client.post(
            f"/api/contributions/{contribution_id}/feedback",
            headers=SAME_ORIGIN_HEADERS,
            json={"maintainer_action": "agreed", "correct_labels": [], "notes": None},
        )
        assert same_origin_feedback.status_code == 200

        foreign_origin_logout = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://evil.example.com"},
        )
        assert foreign_origin_logout.status_code == 403

        same_origin_logout = client.post("/api/auth/logout", headers=SAME_ORIGIN_HEADERS)
        assert same_origin_logout.status_code == 204


def test_production_status_endpoints_hide_details(monkeypatch) -> None:
    _configure_admin_auth(monkeypatch, enabled=False)
    monkeypatch.setattr("server.main.settings.expose_api_docs", False)
    monkeypatch.setattr("server.main.settings.detailed_public_health", False)
    monkeypatch.setattr("server.main.settings.trusted_hosts", "")
    monkeypatch.setattr(
        "server.main.build_readiness_status",
        lambda: {
            "status": "ok",
            "environment": "production",
            "components": {
                "database": {"ok": True},
            },
        },
    )

    secured_app = create_app()

    with TestClient(secured_app) as client:
        root_response = client.get("/")
        assert root_response.status_code == 200
        assert root_response.json() == {"name": "maintainerKi", "status": "running"}

        health_response = client.get("/healthz")
        assert health_response.status_code == 200
        assert health_response.json() == {"name": "maintainerKi", "status": "ok"}

        ready_response = client.get("/readyz")
        assert ready_response.status_code == 200
        assert ready_response.json() == {"status": "ok"}

        docs_response = client.get("/docs")
        assert docs_response.status_code == 404


def test_trusted_hosts_reject_unexpected_hosts(monkeypatch) -> None:
    _configure_admin_auth(monkeypatch, enabled=False)
    monkeypatch.setattr("server.main.settings.expose_api_docs", False)
    monkeypatch.setattr("server.main.settings.detailed_public_health", False)
    monkeypatch.setattr("server.main.settings.trusted_hosts", "maintainerki.example.com,testserver")

    secured_app = create_app()

    with TestClient(secured_app, base_url="http://evil.example.com") as client:
        response = client.get("/healthz")
        assert response.status_code == 400


def test_admin_login_rate_limits_repeated_failures(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "maintainerki_rate_limit.db"
    monkeypatch.setattr("server.db.settings.database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr("server.db.settings.app_env", "test")
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_attempts", 2)
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_window_seconds", 300)
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_block_seconds", 60)
    _configure_admin_auth(
        monkeypatch,
        enabled=True,
        password_hash=hash_password("let-me-in"),
    )
    _reset_database_state()
    init_database()
    Base.metadata.create_all(bind=get_engine())
    ensure_schema_upgrades()
    rate_limiter.clear("admin-login", "testclient")

    with TestClient(app) as client:
        first = client.post("/api/auth/login", json={"username": "admin", "password": "bad-1"})
        second = client.post("/api/auth/login", json={"username": "admin", "password": "bad-2"})
        third = client.post("/api/auth/login", json={"username": "admin", "password": "bad-3"})
    rate_limiter.clear("admin-login", "testclient")

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"
