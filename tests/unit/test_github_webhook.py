from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.rate_limit import rate_limiter
from server.webhooks.security import build_github_signature

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "github_issue_opened.json"
WEBHOOK_SECRET = "test-secret"

client = TestClient(app)


def _load_fixture_bytes() -> bytes:
    payload = json.loads(FIXTURE_PATH.read_text())
    return json.dumps(payload).encode("utf-8")


def _headers(event: str, body: bytes, *, signature: str | None = None) -> dict[str, str]:
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "delivery-123",
        "X-Hub-Signature-256": signature or build_github_signature(WEBHOOK_SECRET, body),
    }


def _issue_payload(action: str = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "issue": {
            "id": 101,
            "number": 42,
            "title": f"Issue action: {action}",
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


def _pull_request_payload(action: str = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "pull_request": {
            "id": 202,
            "number": 7,
            "title": f"PR action: {action}",
            "body": "PR body",
            "html_url": "https://github.com/example/repo/pull/7",
            "user": {"login": "octocat"},
            "head": {"sha": "abc123def456"},
            "changed_files": 3,
            "additions": 40,
            "deletions": 5,
        },
        "repository": {
            "id": 501,
            "full_name": "example/repo",
        },
        "sender": {"login": "sendercat"},
    }


def _to_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_rejects_invalid_signature(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    body = _load_fixture_bytes()

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body, signature="sha256=bad"),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature."


def test_rejects_missing_event_header(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    body = _load_fixture_bytes()

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": build_github_signature(WEBHOOK_SECRET, body)},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing X-GitHub-Event header."


def test_rejects_missing_signature(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    body = _load_fixture_bytes()

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-123",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature."


@pytest.mark.parametrize("action", ["opened", "edited", "reopened"])
def test_accepts_issue_supported_actions_and_registers_then_enqueues(monkeypatch, action: str) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured_registrations: list[dict[str, Any]] = []
    captured_enqueues: list[str] = []

    def fake_register(*, event_name: str, delivery_id: str | None, event: dict[str, Any]) -> dict[str, Any]:
        captured_registrations.append(
            {"event_name": event_name, "delivery_id": delivery_id, "event": event}
        )
        return {"status": "accepted", "delivery_id": "delivery-123", "contribution_id": 1}

    monkeypatch.setattr("server.webhooks.github.register_webhook_delivery", fake_register)
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured_enqueues.append)
    body = _to_bytes(_issue_payload(action))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["repository"] == "example/repo"
    assert response.json()["number"] == 42
    assert captured_registrations == [
        {
            "event_name": "issues",
            "delivery_id": "delivery-123",
            "event": {
                "kind": "issue",
                "action": action,
                "github_id": 101,
                "number": 42,
                "title": f"Issue action: {action}",
                "body": "Issue body",
                "html_url": "https://github.com/example/repo/issues/42",
                "repository": "example/repo",
                "repository_id": 501,
                "author": "octocat",
                "sender": "sendercat",
                "head_sha": None,
                "files_changed": None,
                "additions": None,
                "deletions": None,
            },
        }
    ]
    assert captured_enqueues == ["delivery-123"]


def test_accepts_ping_event(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    body = b'{"zen":"keep it logically awesome"}'

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("ping", body),
    )

    assert response.status_code == 200
    assert response.json()["event"] == "ping"


def test_ignores_unsupported_event(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    body = _load_fixture_bytes()

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("discussion", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unsupported_event"


def test_ignores_unmonitored_repository(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(
        "server.webhooks.github.settings.monitored_repositories",
        "other/repo",
    )
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    body = _to_bytes(_issue_payload("opened"))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "repository_not_monitored"
    assert captured == []


def test_ignores_duplicate_delivery_after_registration(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(
        "server.webhooks.github.register_webhook_delivery",
        lambda **kwargs: {
            "status": "ignored",
            "reason": "duplicate_delivery",
            "delivery_id": "delivery-123",
        },
    )
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    body = _to_bytes(_issue_payload("opened"))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "duplicate_delivery"
    assert captured == []


def test_ignores_unsupported_action_for_issue_event(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    body = _to_bytes(_issue_payload("closed"))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unsupported_action"
    assert response.json()["event"] == "issues"
    assert response.json()["action"] == "closed"


def test_rate_limits_repeated_webhook_requests(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr("server.webhooks.github.settings.webhook_rate_limit_requests", 1)
    monkeypatch.setattr("server.webhooks.github.settings.webhook_rate_limit_window_seconds", 60)
    rate_limiter.clear("github-webhook", "testclient")
    body = _to_bytes(_issue_payload("opened"))

    first = client.post("/webhooks/github", content=body, headers=_headers("issues", body))
    second = client.post("/webhooks/github", content=body, headers=_headers("issues", body))
    rate_limiter.clear("github-webhook", "testclient")

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.parametrize("action", ["opened", "edited", "reopened", "synchronize"])
def test_accepts_pull_request_supported_actions_and_registers_then_enqueues(
    monkeypatch,
    action: str,
) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured_registrations: list[dict[str, Any]] = []
    captured_enqueues: list[str] = []

    def fake_register(*, event_name: str, delivery_id: str | None, event: dict[str, Any]) -> dict[str, Any]:
        captured_registrations.append(
            {"event_name": event_name, "delivery_id": delivery_id, "event": event}
        )
        return {"status": "accepted", "delivery_id": "delivery-123", "contribution_id": 7}

    monkeypatch.setattr("server.webhooks.github.register_webhook_delivery", fake_register)
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured_enqueues.append)
    body = _to_bytes(_pull_request_payload(action))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("pull_request", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["repository"] == "example/repo"
    assert response.json()["number"] == 7
    assert captured_registrations == [
        {
            "event_name": "pull_request",
            "delivery_id": "delivery-123",
            "event": {
                "kind": "pull_request",
                "action": action,
                "github_id": 202,
                "number": 7,
                "title": f"PR action: {action}",
                "body": "PR body",
                "html_url": "https://github.com/example/repo/pull/7",
                "repository": "example/repo",
                "repository_id": 501,
                "author": "octocat",
                "sender": "sendercat",
                "head_sha": "abc123def456",
                "files_changed": 3,
                "additions": 40,
                "deletions": 5,
            },
        }
    ]
    assert captured_enqueues == ["delivery-123"]


def test_ignores_unsupported_action_for_pull_request_event(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    body = _to_bytes(_pull_request_payload("closed"))

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("pull_request", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unsupported_action"
    assert response.json()["event"] == "pull_request"
    assert response.json()["action"] == "closed"
    assert captured == []


@pytest.mark.parametrize("body", [b"null", b"[1, 2, 3]", b'"just a string"', b"42"])
def test_rejects_non_dict_json_payload(monkeypatch, body: bytes) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Webhook payload must be a JSON object."


def test_ignores_issue_missing_number(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    payload = _issue_payload("opened")
    del payload["issue"]["number"]
    body = _to_bytes(payload)

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("issues", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "missing_number"
    assert response.json()["event"] == "issues"
    assert captured == []


def test_pull_request_missing_diff_stats_yields_none_without_crashing(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured_registrations: list[dict[str, Any]] = []
    captured_enqueues: list[str] = []

    def fake_register(*, event_name: str, delivery_id: str | None, event: dict[str, Any]) -> dict[str, Any]:
        captured_registrations.append(
            {"event_name": event_name, "delivery_id": delivery_id, "event": event}
        )
        return {"status": "accepted", "delivery_id": "delivery-123", "contribution_id": 7}

    monkeypatch.setattr("server.webhooks.github.register_webhook_delivery", fake_register)
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured_enqueues.append)
    payload = _pull_request_payload("opened")
    del payload["pull_request"]["changed_files"]
    del payload["pull_request"]["additions"]
    del payload["pull_request"]["deletions"]
    body = _to_bytes(payload)

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("pull_request", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert captured_registrations[0]["event"]["files_changed"] is None
    assert captured_registrations[0]["event"]["additions"] is None
    assert captured_registrations[0]["event"]["deletions"] is None


def test_ignores_pull_request_missing_number(monkeypatch) -> None:
    monkeypatch.setattr("server.webhooks.github.settings.github_webhook_secret", WEBHOOK_SECRET)
    captured: list[str] = []
    monkeypatch.setattr("server.webhooks.github.enqueue_webhook_delivery", captured.append)
    payload = _pull_request_payload("opened")
    del payload["pull_request"]["number"]
    body = _to_bytes(payload)

    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers("pull_request", body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "missing_number"
    assert response.json()["event"] == "pull_request"
    assert captured == []
