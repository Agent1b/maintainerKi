from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from server.auth import (
    SessionPrincipal,
    clear_session_cookie,
    get_current_session,
    require_admin_session,
    set_session_cookie,
    verify_login_credentials,
)
from server.config import settings
from server.github_client import GitHubWritebackError, build_github_client
from server.rate_limit import rate_limiter, too_many_requests
from server.request_meta import get_client_ip
from server.repository import (
    create_scoring_feedback,
    get_contribution_detail,
    get_contribution_writeback_target,
    get_repo_stats,
    get_repository_summary,
    list_repo_inbox,
    list_repositories,
)

router = APIRouter()
auth_router = APIRouter(prefix="/api/auth", tags=["dashboard-auth"])
protected_router = APIRouter(
    prefix="/api",
    tags=["dashboard-api"],
    dependencies=[Depends(require_admin_session)],
)
logger = logging.getLogger(__name__)


class FeedbackPayload(BaseModel):
    maintainer_action: Literal["agreed", "disagreed", "override"]
    correct_labels: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@auth_router.get("/session")
def api_auth_session(
    response: Response,
    session: SessionPrincipal | None = Depends(get_current_session),
) -> dict[str, object]:
    _set_no_store(response)
    return {
        "auth_enabled": settings.admin_auth_enabled,
        "authenticated": session is not None,
        "username": session.username if session else None,
    }


@auth_router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def api_auth_login(payload: LoginPayload, request: Request, response: Response) -> Response:
    _set_no_store(response)
    if not settings.admin_auth_enabled:
        response.status_code = status.HTTP_204_NO_CONTENT
        return response
    client_ip = get_client_ip(request)
    decision = rate_limiter.consume(
        "admin-login",
        client_ip,
        limit=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_seconds,
        block_seconds=settings.login_rate_limit_block_seconds,
    )
    if not decision.allowed:
        raise too_many_requests(
            "Too many login attempts. Try again later.",
            decision.retry_after_seconds,
        )
    if not verify_login_credentials(payload.username, payload.password):
        logger.warning(
            "Admin login failed username=%s client_ip=%s",
            payload.username,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    rate_limiter.clear("admin-login", client_ip)
    set_session_cookie(response, payload.username)
    logger.info(
        "Admin login succeeded username=%s client_ip=%s",
        payload.username,
        client_ip,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def api_auth_logout(
    request: Request,
    response: Response,
    session: SessionPrincipal | None = Depends(get_current_session),
) -> Response:
    _set_no_store(response)
    clear_session_cookie(response)
    logger.info(
        "Admin logout username=%s client_ip=%s",
        session.username if session else "anonymous",
        get_client_ip(request),
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@protected_router.get("/repos")
def api_list_repositories(response: Response) -> dict[str, object]:
    _set_no_store(response)
    repositories = list_repositories()
    return {
        "count": len(repositories),
        "repositories": repositories,
    }


@protected_router.get("/repos/{repo_id}/inbox")
def api_repo_inbox(
    response: Response,
    repo_id: int,
    status_filter: str | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None, pattern="^(issue|pull_request)$"),
    min_score: int | None = Query(default=None, ge=0, le=100),
    duplicates_only: bool = Query(default=False),
    suspicious_only: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    _set_no_store(response)
    repo = get_repository_summary(repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")

    items = list_repo_inbox(
        repo_id,
        status=status_filter,
        kind=kind,
        min_score=min_score,
        duplicates_only=duplicates_only,
        suspicious_only=suspicious_only,
        search=search,
        limit=limit,
    )
    return {
        "repository": repo,
        "count": len(items),
        "items": items,
    }


@protected_router.get("/repos/{repo_id}/stats")
def api_repo_stats(repo_id: int, response: Response) -> dict[str, object]:
    _set_no_store(response)
    stats = get_repo_stats(repo_id)
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
    return stats


@protected_router.get("/contributions/{contribution_id}")
def api_contribution_detail(contribution_id: int, response: Response) -> dict[str, object]:
    _set_no_store(response)
    contribution = get_contribution_detail(contribution_id)
    if contribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribution not found.",
        )
    return contribution


@protected_router.post("/contributions/{contribution_id}/feedback")
def api_create_feedback(
    response: Response,
    contribution_id: int,
    payload: FeedbackPayload,
    session: SessionPrincipal | None = Depends(require_admin_session),
) -> dict[str, object]:
    _set_no_store(response)
    try:
        feedback = create_scoring_feedback(
            contribution_id,
            maintainer_action=payload.maintainer_action,
            correct_labels=payload.correct_labels,
            notes=payload.notes,
            actor_username=session.username if session else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if payload.maintainer_action == "override":
        target = get_contribution_writeback_target(contribution_id)
        if target:
            try:
                client = build_github_client()
                if client.is_configured():
                    client.apply_labels(
                        repository_full_name=str(target["repository"] or "unknown/unknown"),
                        number=int(target["number"]),
                        labels=[str(label) for label in target["labels"]],
                    )
            except GitHubWritebackError as exc:
                logger.exception(
                    "Failed to write back maintainer label override for contribution %s: %s",
                    contribution_id,
                    exc,
                )

    contribution = get_contribution_detail(contribution_id)
    return {
        "feedback": feedback,
        "contribution": contribution,
    }


router.include_router(auth_router)
router.include_router(protected_router)
