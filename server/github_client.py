from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote
import time

import httpx
import jwt

from server.config import settings
from server.scorer.models import ScoreResult

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "maintainerKi/0.1.0",
}
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class LabelDefinition:
    color: str
    description: str


@dataclass(slots=True)
class ExpiringToken:
    token: str
    expires_at: datetime

    def is_fresh(self) -> bool:
        return self.expires_at > datetime.now(timezone.utc) + timedelta(minutes=2)


DEFAULT_LABEL_DEFINITIONS: dict[str, LabelDefinition] = {
    "maintainerki:suspicious": LabelDefinition(
        color="B60205",
        description="Potential spam, AI slop, or suspicious contribution.",
    ),
    "maintainerki:needs-info": LabelDefinition(
        color="FBCA04",
        description="Needs more detail before a maintainer can review it.",
    ),
    "maintainerki:review-first": LabelDefinition(
        color="0E8A16",
        description="High-signal contribution worth early maintainer review.",
    ),
    "maintainerki:worth-a-look": LabelDefinition(
        color="1D76DB",
        description="Looks promising but is not urgent.",
    ),
    "maintainerki:low-priority": LabelDefinition(
        color="6E7781",
        description="Low-priority triage bucket from maintainerKi.",
    ),
    "maintainerki:duplicate": LabelDefinition(
        color="8250DF",
        description="Likely duplicate contribution detected by maintainerKi.",
    ),
    "maintainerki:possible-duplicate": LabelDefinition(
        color="8250DF",
        description="Likely duplicate contribution detected by maintainerKi.",
    ),
    "spam": LabelDefinition(
        color="D73A4A",
        description="Spam or very low-signal contribution.",
    ),
    "invalid": LabelDefinition(
        color="E4E669",
        description="Submission does not currently match project scope.",
    ),
}


class GitHubWritebackError(RuntimeError):
    pass


class GitHubAppClient:
    def __init__(
        self,
        *,
        app_id: str,
        private_key_path: str,
        base_url: str = "https://api.github.com",
        timeout_seconds: float = 30,
        auto_create_labels: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.app_id = app_id.strip()
        self.private_key_path = private_key_path.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.auto_create_labels = auto_create_labels
        self._http_client = http_client
        self._owned_http_client: httpx.Client | None = None
        self._token_cache: dict[int, ExpiringToken] = {}
        self._installation_id_cache: dict[str, int] = {}
        self._label_cache: set[tuple[str, str, str]] = set()
        self._token_lock = Lock()
        self._app_jwt_lock = Lock()
        self._app_jwt_cache: ExpiringToken | None = None
        self._private_key_cache: str | None = None

    def is_configured(self) -> bool:
        return bool(self.app_id and self.private_key_path)

    def get_authenticated_app(self) -> dict[str, Any]:
        response = self._request_app(
            method="GET",
            path="/app",
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubWritebackError("GitHub returned an invalid app payload.")
        return payload

    def list_installations(self) -> list[dict[str, Any]]:
        return self._paginate_app_list("/app/installations")

    def list_installation_repositories(self, installation_id: int) -> list[dict[str, Any]]:
        installation_token = self.get_installation_token(installation_id)
        page = 1
        repositories: list[dict[str, Any]] = []
        while True:
            response = self._request_installation(
                installation_token=installation_token,
                method="GET",
                path=f"/installation/repositories?per_page=100&page={page}",
            )
            payload = response.json()
            page_items = payload.get("repositories", []) if isinstance(payload, dict) else []
            if not isinstance(page_items, list):
                raise GitHubWritebackError("GitHub returned an invalid repositories payload.")
            repositories.extend(item for item in page_items if isinstance(item, dict))
            if not _has_next_page(response, len(page_items), page):
                return repositories
            page += 1

    def list_issue_comments(self, *, repository_full_name: str, number: int) -> list[dict[str, Any]]:
        owner, repo = _split_repository_full_name(repository_full_name)
        installation_id = self.get_repository_installation_id(owner=owner, repo=repo)
        installation_token = self.get_installation_token(installation_id)
        page = 1
        comments: list[dict[str, Any]] = []
        while True:
            response = self._request_installation(
                installation_token=installation_token,
                method="GET",
                path=f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=100&page={page}",
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubWritebackError("GitHub returned an invalid issue comments payload.")
            comments.extend(item for item in payload if isinstance(item, dict))
            if not _has_next_page(response, len(payload), page):
                return comments
            page += 1

    def issue_comment_with_marker_exists(
        self,
        *,
        repository_full_name: str,
        number: int,
        marker: str,
    ) -> bool:
        for comment in self.list_issue_comments(repository_full_name=repository_full_name, number=number):
            body = comment.get("body")
            if isinstance(body, str) and marker in body:
                return True
        return False

    def apply_labels(self, *, repository_full_name: str, number: int, labels: list[str]) -> None:
        cleaned_labels = _normalize_labels(labels)
        if not cleaned_labels:
            logger.info(
                "Skipping GitHub label write-back for %s#%s because no labels were suggested.",
                repository_full_name,
                number,
            )
            return

        owner, repo = _split_repository_full_name(repository_full_name)
        installation_id = self.get_repository_installation_id(owner=owner, repo=repo)
        installation_token = self.get_installation_token(installation_id)

        if self.auto_create_labels:
            for label in cleaned_labels:
                self.ensure_label_exists(
                    owner=owner,
                    repo=repo,
                    label=label,
                    installation_token=installation_token,
                )

        self._request_installation(
            installation_token=installation_token,
            method="POST",
            path=f"/repos/{owner}/{repo}/issues/{number}/labels",
            json={"labels": cleaned_labels},
        )

    def create_issue_comment(
        self,
        *,
        repository_full_name: str,
        number: int,
        body: str,
        marker: str | None = None,
    ) -> bool:
        if marker and self.issue_comment_with_marker_exists(
            repository_full_name=repository_full_name,
            number=number,
            marker=marker,
        ):
            logger.info(
                "Skipping duplicate maintainerKi comment for %s#%s because marker %s already exists.",
                repository_full_name,
                number,
                marker,
            )
            return False

        owner, repo = _split_repository_full_name(repository_full_name)
        installation_id = self.get_repository_installation_id(owner=owner, repo=repo)
        installation_token = self.get_installation_token(installation_id)
        self._request_installation(
            installation_token=installation_token,
            method="POST",
            path=f"/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        return True

    def get_repository_installation_id(self, *, owner: str, repo: str) -> int:
        cache_key = f"{owner}/{repo}".lower()
        cached = self._installation_id_cache.get(cache_key)
        if cached is not None:
            return cached

        response = self._request_app(
            method="GET",
            path=f"/repos/{owner}/{repo}/installation",
        )
        installation_id = response.json().get("id")
        if not installation_id:
            raise GitHubWritebackError(
                f"GitHub did not return an installation id for {owner}/{repo}."
            )
        resolved = int(installation_id)
        self._installation_id_cache[cache_key] = resolved
        return resolved

    def get_installation_token(self, installation_id: int) -> str:
        with self._token_lock:
            cached = self._token_cache.get(installation_id)
            if cached and cached.is_fresh():
                return cached.token

        response = self._request_app(
            method="POST",
            path=f"/app/installations/{installation_id}/access_tokens",
            json={},
        )
        payload = response.json()
        token = payload.get("token")
        expires_at_raw = payload.get("expires_at")
        if not token or not expires_at_raw:
            raise GitHubWritebackError(
                f"GitHub did not return a valid installation token for installation {installation_id}."
            )

        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        with self._token_lock:
            self._token_cache[installation_id] = ExpiringToken(
                token=token,
                expires_at=expires_at,
            )
        return token

    def ensure_label_exists(
        self,
        *,
        owner: str,
        repo: str,
        label: str,
        installation_token: str,
    ) -> None:
        cache_key = (owner.lower(), repo.lower(), label)
        if cache_key in self._label_cache:
            return

        encoded_label = quote(label, safe="")
        response = self._request_installation(
            installation_token=installation_token,
            method="GET",
            path=f"/repos/{owner}/{repo}/labels/{encoded_label}",
            expected_statuses={200, 404},
        )
        if response.status_code == 200:
            self._label_cache.add(cache_key)
            return

        definition = DEFAULT_LABEL_DEFINITIONS.get(
            label,
            LabelDefinition(
                color="6E7781",
                description="Label created automatically by maintainerKi.",
            ),
        )
        create_response = self._request_installation(
            installation_token=installation_token,
            method="POST",
            path=f"/repos/{owner}/{repo}/labels",
            json={
                "name": label,
                "color": definition.color,
                "description": definition.description,
            },
            expected_statuses={201, 422},
        )
        if create_response.status_code == 422:
            logger.info(
                "GitHub reported label %s already exists in %s/%s while creating it.",
                label,
                owner,
                repo,
            )
        self._label_cache.add(cache_key)

    def _build_app_jwt(self) -> str:
        with self._app_jwt_lock:
            if self._app_jwt_cache and self._app_jwt_cache.is_fresh():
                return self._app_jwt_cache.token

            private_key = self._load_private_key()
            now = datetime.now(timezone.utc)
            payload = {
                "iat": int((now - timedelta(seconds=60)).timestamp()),
                "exp": int((now + timedelta(minutes=9)).timestamp()),
                "iss": self.app_id,
            }
            token = jwt.encode(payload, private_key, algorithm="RS256")
            self._app_jwt_cache = ExpiringToken(
                token=token,
                expires_at=now + timedelta(minutes=9),
            )
            return token

    def _load_private_key(self) -> str:
        if self._private_key_cache is not None:
            return self._private_key_cache
        path = Path(self.private_key_path).expanduser()
        if not path.exists():
            raise GitHubWritebackError(
                f"GitHub private key file does not exist: {self.private_key_path}"
            )
        try:
            self._private_key_cache = path.read_text()
        except OSError as exc:
            raise GitHubWritebackError(
                f"GitHub private key file is not readable: {self.private_key_path} ({exc})"
            ) from exc
        return self._private_key_cache

    def _request_app(
        self,
        *,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        expected_statuses: set[int] | None = None,
    ) -> httpx.Response:
        app_jwt = self._build_app_jwt()
        return self._request(
            method=method,
            path=path,
            headers={"Authorization": f"Bearer {app_jwt}"},
            json=json,
            expected_statuses=expected_statuses or {200, 201},
        )

    def _request_installation(
        self,
        *,
        installation_token: str,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        expected_statuses: set[int] | None = None,
    ) -> httpx.Response:
        return self._request(
            method=method,
            path=path,
            headers={"Authorization": f"Bearer {installation_token}"},
            json=json,
            expected_statuses=expected_statuses or {200, 201},
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        expected_statuses: set[int],
    ) -> httpx.Response:
        request_headers = {**_DEFAULT_HEADERS, **headers}
        retryable = _is_retryable_request(method=method, path=path)
        max_attempts = 3 if retryable else 1
        response: httpx.Response | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                client = self._http_client or self._get_or_create_owned_client()
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=request_headers,
                    json=json,
                    timeout=self.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                if retryable and attempt < max_attempts:
                    logger.warning(
                        "Transient GitHub API transport failure for %s %s (attempt %s/%s): %s",
                        method,
                        path,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    self._reset_owned_client()
                    time.sleep(0.5 * attempt)
                    continue
                raise GitHubWritebackError(f"GitHub API request failed: {exc}") from exc

            if (
                retryable
                and response.status_code in _TRANSIENT_STATUS_CODES
                and attempt < max_attempts
            ):
                logger.warning(
                    "Transient GitHub API status for %s %s (attempt %s/%s): %s",
                    method,
                    path,
                    attempt,
                    max_attempts,
                    response.status_code,
                )
                self._reset_owned_client()
                time.sleep(0.5 * attempt)
                continue

            if response.status_code not in expected_statuses:
                message = _extract_github_error_message(response)
                raise GitHubWritebackError(
                    f"GitHub API {method} {path} failed with status {response.status_code}: {message}"
                )
            return response

        assert response is not None
        return response

    def _get_or_create_owned_client(self) -> httpx.Client:
        if self._owned_http_client is None:
            self._owned_http_client = httpx.Client(timeout=self.timeout_seconds)
        return self._owned_http_client

    def _reset_owned_client(self) -> None:
        if self._http_client is not None:
            return
        if self._owned_http_client is not None:
            self._owned_http_client.close()
            self._owned_http_client = None

    def _paginate_app_list(self, path: str) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            response = self._request_app(
                method="GET",
                path=f"{path}?per_page=100&page={page}",
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubWritebackError("GitHub returned an invalid paginated list payload.")
            items.extend(item for item in payload if isinstance(item, dict))
            if not _has_next_page(response, len(payload), page):
                return items
            page += 1


def build_github_client(http_client: httpx.Client | None = None) -> GitHubAppClient:
    return GitHubAppClient(
        app_id=settings.github_app_id,
        private_key_path=settings.github_private_key_path,
        base_url=settings.github_api_base_url,
        timeout_seconds=settings.github_writeback_timeout_seconds,
        auto_create_labels=settings.github_auto_create_labels,
        http_client=http_client,
    )


def apply_score_labels(
    event: dict[str, Any],
    score: ScoreResult,
    *,
    client: GitHubAppClient | None = None,
) -> bool:
    if not settings.github_label_writeback_enabled:
        logger.info(
            "GitHub label write-back disabled; skipping %s #%s in %s.",
            event["kind"],
            event["number"],
            event["repository"],
        )
        return False

    resolved_client = client or build_github_client()
    if not resolved_client.is_configured():
        logger.info(
            "GitHub App credentials are not configured; skipping label write-back for %s #%s in %s.",
            event["kind"],
            event["number"],
            event["repository"],
        )
        return False

    resolved_client.apply_labels(
        repository_full_name=event["repository"] or "unknown/unknown",
        number=event["number"],
        labels=score.suggested_labels,
    )
    logger.info(
        "Applied %s GitHub labels to %s #%s in %s.",
        len(_normalize_labels(score.suggested_labels)),
        event["kind"],
        event["number"],
        event["repository"],
    )
    return True


def _is_retryable_request(*, method: str, path: str) -> bool:
    normalized_method = method.upper().strip()
    if normalized_method in {"GET", "HEAD"}:
        return True
    if normalized_method == "POST" and path.endswith("/access_tokens"):
        return True
    if normalized_method == "POST" and path.endswith("/labels"):
        return True
    return False


def _normalize_labels(labels: list[str]) -> list[str]:
    normalized: list[str] = []
    for label in labels:
        cleaned = label.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _split_repository_full_name(repository_full_name: str) -> tuple[str, str]:
    parts = [part for part in repository_full_name.strip().split("/") if part]
    if len(parts) != 2:
        raise GitHubWritebackError(
            f"Repository name must look like owner/repo, got: {repository_full_name!r}"
        )
    return parts[0], parts[1]


def _extract_github_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or "Unknown GitHub error"

    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return response.text or "Unknown GitHub error"


def _has_next_page(response: httpx.Response, page_size: int, page_number: int) -> bool:
    link_header = response.headers.get("Link") or response.headers.get("link")
    if link_header:
        return 'rel="next"' in link_header
    if page_size < 100:
        return False
    if response.request.url.params.get("page") and int(response.request.url.params["page"]) != page_number:
        return False
    return page_size == 100
