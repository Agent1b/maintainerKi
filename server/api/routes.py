from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from server.github_client import GitHubWritebackError, build_github_client
from server.repository import (
    create_scoring_feedback,
    get_contribution_detail,
    get_contribution_writeback_target,
    get_repo_stats,
    get_repository_summary,
    list_repo_inbox,
    list_repositories,
)

router = APIRouter(prefix="/api", tags=["dashboard-api"])
logger = logging.getLogger(__name__)


class FeedbackPayload(BaseModel):
    maintainer_action: Literal["agreed", "disagreed", "override"]
    correct_labels: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


@router.get("/repos")
def api_list_repositories() -> dict[str, object]:
    repositories = list_repositories()
    return {
        "count": len(repositories),
        "repositories": repositories,
    }


@router.get("/repos/{repo_id}/inbox")
def api_repo_inbox(
    repo_id: int,
    status_filter: str | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None, pattern="^(issue|pull_request)$"),
    min_score: int | None = Query(default=None, ge=0, le=100),
    duplicates_only: bool = Query(default=False),
    suspicious_only: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
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


@router.get("/repos/{repo_id}/stats")
def api_repo_stats(repo_id: int) -> dict[str, object]:
    stats = get_repo_stats(repo_id)
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
    return stats


@router.get("/contributions/{contribution_id}")
def api_contribution_detail(contribution_id: int) -> dict[str, object]:
    contribution = get_contribution_detail(contribution_id)
    if contribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribution not found.",
        )
    return contribution


@router.post("/contributions/{contribution_id}/feedback")
def api_create_feedback(
    contribution_id: int,
    payload: FeedbackPayload,
) -> dict[str, object]:
    try:
        feedback = create_scoring_feedback(
            contribution_id,
            maintainer_action=payload.maintainer_action,
            correct_labels=payload.correct_labels,
            notes=payload.notes,
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
