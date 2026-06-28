from __future__ import annotations

import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from server.github_client import GitHubAppClient, GitHubWritebackError


def _write_private_key(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "app-private-key.pem"
    path.write_bytes(pem)
    return path


def test_apply_labels_creates_missing_labels_and_applies_them(tmp_path: Path) -> None:
    private_key_path = _write_private_key(tmp_path)
    seen_calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, request.url.path))

        if request.url.path == "/repos/example/repo/installation":
            assert request.headers["Authorization"].startswith("Bearer ")
            return httpx.Response(200, json={"id": 991})
        if request.url.path == "/app/installations/991/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path in {
            "/repos/example/repo/labels/maintainerki%3Asuspicious",
            "/repos/example/repo/labels/maintainerki:suspicious",
        }:
            return httpx.Response(404, json={"message": "Not Found"})
        if request.url.path == "/repos/example/repo/labels":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["name"] == "maintainerki:suspicious"
            assert payload["color"] == "B60205"
            return httpx.Response(201, json=payload)
        if request.url.path == "/repos/example/repo/issues/42/labels":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["labels"] == ["maintainerki:suspicious"]
            assert request.headers["Authorization"] == "Bearer installation-token"
            return httpx.Response(200, json={"labels": payload["labels"]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        base_url="https://api.github.com",
        timeout_seconds=5,
        auto_create_labels=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.apply_labels(
        repository_full_name="example/repo",
        number=42,
        labels=["maintainerki:suspicious"],
    )

    assert seen_calls == [
        ("GET", "/repos/example/repo/installation"),
        ("POST", "/app/installations/991/access_tokens"),
        seen_calls[2],
        ("POST", "/repos/example/repo/labels"),
        ("POST", "/repos/example/repo/issues/42/labels"),
    ]
    assert seen_calls[2][0] == "GET"
    assert seen_calls[2][1] in {
        "/repos/example/repo/labels/maintainerki%3Asuspicious",
        "/repos/example/repo/labels/maintainerki:suspicious",
    }


def test_apply_labels_rejects_bad_repository_name(tmp_path: Path) -> None:
    private_key_path = _write_private_key(tmp_path)
    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    try:
        client.apply_labels(repository_full_name="not-valid", number=1, labels=["x"])
    except GitHubWritebackError as exc:
        assert "owner/repo" in str(exc)
    else:
        raise AssertionError("Expected GitHubWritebackError for an invalid repo name.")


def test_lists_installations_and_repositories(tmp_path: Path) -> None:
    private_key_path = _write_private_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app":
            return httpx.Response(200, json={"name": "maintainerki-dev"})
        if request.url.path == "/app/installations":
            return httpx.Response(200, json=[{"id": 991}])
        if request.url.path == "/app/installations/991/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path == "/installation/repositories":
            return httpx.Response(
                200,
                json={"repositories": [{"full_name": "example/repo"}]},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_authenticated_app()["name"] == "maintainerki-dev"
    assert client.list_installations() == [{"id": 991}]
    assert client.list_installation_repositories(991) == [{"full_name": "example/repo"}]


def test_apply_labels_retries_transient_transport_error(tmp_path: Path, monkeypatch) -> None:
    private_key_path = _write_private_key(tmp_path)
    attempts = {"installation": 0}
    seen_calls: list[tuple[str, str]] = []
    monkeypatch.setattr("server.github_client.time.sleep", lambda *_args, **_kwargs: None)

    def handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, request.url.path))

        if request.url.path == "/repos/example/repo/installation":
            attempts["installation"] += 1
            if attempts["installation"] == 1:
                raise httpx.ConnectError("temporary eof", request=request)
            return httpx.Response(200, json={"id": 991})
        if request.url.path == "/app/installations/991/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path in {
            "/repos/example/repo/labels/maintainerki%3Areview-first",
            "/repos/example/repo/labels/maintainerki:review-first",
        }:
            return httpx.Response(200, json={"name": "maintainerki:review-first"})
        if request.url.path == "/repos/example/repo/issues/42/labels":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["labels"] == ["maintainerki:review-first"]
            return httpx.Response(200, json={"labels": payload["labels"]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        base_url="https://api.github.com",
        timeout_seconds=5,
        auto_create_labels=True,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.apply_labels(
        repository_full_name="example/repo",
        number=42,
        labels=["maintainerki:review-first"],
    )

    assert attempts["installation"] == 2
    assert seen_calls[:2] == [
        ("GET", "/repos/example/repo/installation"),
        ("GET", "/repos/example/repo/installation"),
    ]
