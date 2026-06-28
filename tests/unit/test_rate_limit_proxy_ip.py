from __future__ import annotations

import json

from fastapi.testclient import TestClient

from server.auth import hash_password
from server.main import app
from server.rate_limit import rate_limiter
from server.request_meta import TRUSTED_PROXY_HEADER, TRUSTED_PROXY_VALUE
from server.webhooks.security import build_github_signature

WEBHOOK_SECRET = "test-secret"
REAL_CLIENT_IP = "8.8.4.4"
PROXY_CLIENT = ("172.18.0.5", 50000)
UPSTREAM_PROXY_IP = "172.19.0.9"


def _configure_admin_auth(monkeypatch) -> None:
    monkeypatch.setattr("server.config.settings.admin_auth_enabled", True)
    monkeypatch.setattr("server.config.settings.admin_username", "admin")
    monkeypatch.setattr(
        "server.config.settings.admin_password_hash",
        hash_password("let-me-in"),
    )
    monkeypatch.setattr("server.config.settings.admin_password", "")
    monkeypatch.setattr(
        "server.config.settings.session_secret",
        "test-session-secret-that-is-long-enough",
    )
    monkeypatch.setattr("server.config.settings.session_cookie_secure", False)
    monkeypatch.setattr("server.config.settings.session_ttl_seconds", 3600)


def _proxy_headers(*, forwarded_for: str, real_ip: str) -> dict[str, str]:
    return {
        TRUSTED_PROXY_HEADER: TRUSTED_PROXY_VALUE,
        "X-Forwarded-For": forwarded_for,
        "X-Real-IP": real_ip,
    }


def _webhook_headers(*, body: bytes, forwarded_for: str, real_ip: str) -> dict[str, str]:
    headers = _proxy_headers(forwarded_for=forwarded_for, real_ip=real_ip)
    headers.update(
        {
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-123",
            "X-Hub-Signature-256": build_github_signature(WEBHOOK_SECRET, body),
        }
    )
    return headers


def _issue_body() -> bytes:
    return json.dumps(
        {
            "action": "opened",
            "issue": {
                "id": 101,
                "number": 42,
                "title": "Issue action: opened",
                "body": "Issue body",
                "html_url": "https://github.com/example/repo/issues/42",
                "user": {"login": "octocat"},
            },
            "repository": {
                "id": 501,
                "full_name": "example/repo",
            },
            "sender": {"login": "sendercat"},
        }
    ).encode("utf-8")


def test_admin_login_rate_limit_keys_off_trusted_proxy_client_ip(monkeypatch) -> None:
    _configure_admin_auth(monkeypatch)
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_attempts", 1)
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_window_seconds", 300)
    monkeypatch.setattr("server.api.routes.settings.login_rate_limit_block_seconds", 60)

    for key in (REAL_CLIENT_IP, UPSTREAM_PROXY_IP, "1.1.1.1", "2.2.2.2"):
        rate_limiter.clear("admin-login", key)

    client = TestClient(app, client=PROXY_CLIENT)
    try:
        first = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "bad-1"},
            headers=_proxy_headers(
                forwarded_for=f"1.1.1.1, {REAL_CLIENT_IP}, {UPSTREAM_PROXY_IP}",
                real_ip=UPSTREAM_PROXY_IP,
            ),
        )
        second = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "bad-2"},
            headers=_proxy_headers(
                forwarded_for=f"2.2.2.2, {REAL_CLIENT_IP}, {UPSTREAM_PROXY_IP}",
                real_ip=UPSTREAM_PROXY_IP,
            ),
        )
    finally:
        client.close()

    for key in (REAL_CLIENT_IP, UPSTREAM_PROXY_IP, "1.1.1.1", "2.2.2.2"):
        rate_limiter.clear("admin-login", key)

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"


def test_webhook_rate_limit_keys_off_trusted_proxy_client_ip(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr("server.webhooks.github.settings.webhook_rate_limit_requests", 1)
    monkeypatch.setattr("server.webhooks.github.settings.webhook_rate_limit_window_seconds", 60)
    monkeypatch.setattr(
        "server.webhooks.github.register_webhook_delivery",
        lambda **_: {"status": "accepted", "delivery_id": "delivery-123", "contribution_id": 7},
    )
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", lambda *_: None)

    body = _issue_body()
    for key in (REAL_CLIENT_IP, UPSTREAM_PROXY_IP, "1.1.1.1", "2.2.2.2"):
        rate_limiter.clear("github-webhook", key)

    client = TestClient(app, client=PROXY_CLIENT)
    try:
        first = client.post(
            "/webhooks/github",
            content=body,
            headers=_webhook_headers(
                body=body,
                forwarded_for=f"1.1.1.1, {REAL_CLIENT_IP}, {UPSTREAM_PROXY_IP}",
                real_ip=UPSTREAM_PROXY_IP,
            ),
        )
        second = client.post(
            "/webhooks/github",
            content=body,
            headers=_webhook_headers(
                body=body,
                forwarded_for=f"2.2.2.2, {REAL_CLIENT_IP}, {UPSTREAM_PROXY_IP}",
                real_ip=UPSTREAM_PROXY_IP,
            ),
        )
    finally:
        client.close()

    for key in (REAL_CLIENT_IP, UPSTREAM_PROXY_IP, "1.1.1.1", "2.2.2.2"):
        rate_limiter.clear("github-webhook", key)

    assert first.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.status_code == 429
