from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from server.config import settings
from server.github_client import GitHubAppClient, GitHubWritebackError, apply_score_labels
from server.scorer.models import ScoreResult


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


def test_apply_score_labels_recomputes_automated_labels_from_scores(monkeypatch) -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.labels: list[str] = []

        def is_configured(self) -> bool:
            return True

        def apply_labels(self, *, repository_full_name: str, number: int, labels: list[str]) -> None:
            assert repository_full_name == "example/repo"
            assert number == 42
            self.labels = labels

    monkeypatch.setattr(settings, "github_label_writeback_enabled", True)
    client = RecordingClient()
    score = ScoreResult(
        quality=10,
        relevance=10,
        completeness=80,
        suspicion=10,
        overall_score=10,
        summary="A low-priority contribution whose prompt tries to select privileged labels.",
        suggested_labels=[
            "maintainerki:review-first",
            "maintainerki:possible-duplicate",
        ],
        provider="mock",
        model="mock",
        prompt_version="test",
    )

    assert apply_score_labels(
        {
            "repository": "example/repo",
            "kind": "issue",
            "number": 42,
        },
        score,
        client=client,
    ) is True
    assert client.labels == ["maintainerki:low-priority"]


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


def test_get_pull_request_files_respects_max_files_across_pagination(tmp_path: Path) -> None:
    private_key_path = _write_private_key(tmp_path)
    seen_calls: list[tuple[str, str]] = []

    files_page1 = [
        {
            "filename": "a.py",
            "status": "modified",
            "additions": 5,
            "deletions": 1,
            "patch": "@@ -1,1 +1,1 @@\n-a\n+b",
        },
        {
            "filename": "b.py",
            "status": "added",
            "additions": 10,
            "deletions": 0,
            "patch": "diff-b",
        },
    ]
    files_page2 = [
        {
            "filename": "c.bin",
            "status": "modified",
            "additions": 0,
            "deletions": 0,
            # No "patch" key: GitHub omits it for binary/huge files.
        },
        {
            "filename": "d.py",
            "status": "removed",
            "additions": 0,
            "deletions": 20,
            "patch": "diff-d",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        seen_calls.append((request.method, request.url.path))

        if request.url.path == "/repos/example/repo/installation":
            return httpx.Response(200, json={"id": 991})
        if request.url.path == "/app/installations/991/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path == "/repos/example/repo/pulls/42/files":
            page = request.url.params.get("page")
            assert request.url.params.get("per_page") == "3"
            if page == "1":
                return httpx.Response(
                    200,
                    json=files_page1,
                    headers={
                        "Link": (
                            '<https://api.github.com/repos/example/repo/pulls/42/files'
                            '?per_page=3&page=2>; rel="next"'
                        )
                    },
                )
            if page == "2":
                return httpx.Response(200, json=files_page2)
            raise AssertionError(f"Unexpected page requested: {page}")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        base_url="https://api.github.com",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.get_pull_request_files("example/repo", 42, max_files=3)

    assert result == [
        {
            "filename": "a.py",
            "status": "modified",
            "additions": 5,
            "deletions": 1,
            "patch": "@@ -1,1 +1,1 @@\n-a\n+b",
        },
        {
            "filename": "b.py",
            "status": "added",
            "additions": 10,
            "deletions": 0,
            "patch": "diff-b",
        },
        {
            "filename": "c.bin",
            "status": "modified",
            "additions": 0,
            "deletions": 0,
            "patch": None,
        },
    ]
    # Only page 1 and page 2 should have been fetched; the loop must stop
    # as soon as max_files entries are collected, mid-page-2.
    file_page_requests = [
        call for call in seen_calls if call[1] == "/repos/example/repo/pulls/42/files"
    ]
    assert len(file_page_requests) == 2


def test_get_pull_request_files_returns_empty_without_http_calls_when_max_files_is_zero(
    tmp_path: Path,
) -> None:
    private_key_path = _write_private_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        base_url="https://api.github.com",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.get_pull_request_files("example/repo", 42, max_files=0)

    assert result == []


def test_get_user_created_at_parses_timestamp_and_returns_none_on_404(tmp_path: Path) -> None:
    private_key_path = _write_private_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/example/repo/installation":
            return httpx.Response(200, json={"id": 991})
        if request.url.path == "/app/installations/991/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": "2030-01-01T00:00:00Z",
                },
            )
        if request.url.path == "/users/octocat":
            return httpx.Response(200, json={"login": "octocat", "created_at": "2015-06-01T12:00:00Z"})
        if request.url.path == "/users/deleted-user":
            return httpx.Response(404, json={"message": "Not Found"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubAppClient(
        app_id="123456",
        private_key_path=str(private_key_path),
        base_url="https://api.github.com",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    created_at = client.get_user_created_at("octocat", repository_full_name="example/repo")
    assert created_at == datetime(2015, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    missing = client.get_user_created_at("deleted-user", repository_full_name="example/repo")
    assert missing is None
