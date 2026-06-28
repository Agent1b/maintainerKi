from __future__ import annotations

import json

import httpx

from scripts import production_smoke_test


def test_build_signature_uses_sha256() -> None:
    signature = production_smoke_test._build_signature("secret", b"hello")
    assert signature.startswith("sha256=")
    assert len(signature) > len("sha256=")


def test_run_smoke_test_checks_endpoints(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/api/auth/session":
            return httpx.Response(200, json={"auth_enabled": False, "authenticated": False})
        if request.method == "GET" and request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/readyz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/api/repos":
            return httpx.Response(200, json={"count": 0, "repositories": []})
        if request.method == "POST" and request.url.path == "/webhooks/github":
            assert request.headers["X-GitHub-Event"] == "ping"
            assert request.headers["X-Hub-Signature-256"].startswith("sha256=")
            return httpx.Response(200, json={"status": "ok", "event": "ping"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)

    class FakeClient(httpx.Client):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(production_smoke_test.httpx, "Client", FakeClient)

    exit_code = production_smoke_test.run_smoke_test(
        base_url="https://maintainerki.example.com",
        timeout_seconds=5,
        webhook_secret="test-secret",
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "/api/auth/session"),
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/api/repos"),
        ("POST", "/webhooks/github"),
    ]


def test_run_smoke_test_logs_in_when_admin_auth_is_enabled(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    authenticated = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal authenticated
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/api/auth/session":
            return httpx.Response(
                200,
                json={"auth_enabled": True, "authenticated": authenticated, "username": "admin" if authenticated else None},
            )
        if request.method == "POST" and request.url.path == "/api/auth/login":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload == {"username": "admin", "password": "test-password"}
            authenticated = True
            return httpx.Response(204)
        if request.method == "GET" and request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/readyz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and request.url.path == "/api/repos":
            return httpx.Response(200, json={"count": 0, "repositories": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)

    class FakeClient(httpx.Client):
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(production_smoke_test.httpx, "Client", FakeClient)

    exit_code = production_smoke_test.run_smoke_test(
        base_url="https://maintainerki.example.com",
        timeout_seconds=5,
        webhook_secret=None,
        admin_username="admin",
        admin_password="test-password",
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "/api/auth/session"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/session"),
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/api/repos"),
    ]
