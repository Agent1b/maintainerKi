from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from server.config import settings
from server.github_client import build_github_client
from server.repository import (
    count_author_contributions_in_repository,
    count_recent_contributions_by_author,
)
from server.scorer.models import ContributionInput

logger = logging.getLogger(__name__)

_ACCOUNT_AGE_CACHE_TTL_SECONDS = 24 * 60 * 60
_ACCOUNT_AGE_CACHE_MAX_ENTRIES = 1000

# Floods repeat the same author across many contributions in a short window, so
# caching account-creation lookups per username keeps GitHub API calls flat
# instead of growing with the number of suspicious submissions.
_account_age_cache: dict[str, tuple[datetime, datetime]] = {}
_account_age_cache_lock = threading.Lock()


def _prune_account_age_cache_locked() -> None:
    if len(_account_age_cache) <= _ACCOUNT_AGE_CACHE_MAX_ENTRIES:
        return
    # Drop the oldest entries first (by cache time) until back under the cap.
    for username, _ in sorted(_account_age_cache.items(), key=lambda item: item[1][1])[
        : len(_account_age_cache) - _ACCOUNT_AGE_CACHE_MAX_ENTRIES
    ]:
        _account_age_cache.pop(username, None)


def _cached_account_created_at(username: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    with _account_age_cache_lock:
        cached = _account_age_cache.get(username)
        if cached is None:
            return None
        created_at, cached_at = cached
        if (now - cached_at).total_seconds() >= _ACCOUNT_AGE_CACHE_TTL_SECONDS:
            return None
        return created_at


def _store_account_created_at(username: str, created_at: datetime) -> None:
    now = datetime.now(timezone.utc)
    with _account_age_cache_lock:
        _account_age_cache[username] = (created_at, now)
        _prune_account_age_cache_locked()


def _resolve_account_created_at(client, author: str, repository: str) -> datetime | None:
    cached = _cached_account_created_at(author)
    if cached is not None:
        return cached

    created_at = client.get_user_created_at(author, repository_full_name=repository)
    if created_at is not None:
        _store_account_created_at(author, created_at)
    return created_at


def _format_diff_excerpt(files: list[dict]) -> str:
    blocks: list[str] = []
    for file_info in files:
        patch = file_info.get("patch")
        if patch is None:
            continue
        filename = file_info.get("filename", "")
        file_additions = file_info.get("additions", 0)
        file_deletions = file_info.get("deletions", 0)
        blocks.append(f"--- {filename} (+{file_additions}/-{file_deletions})\n{patch}")

    excerpt = "\n\n".join(blocks)
    max_chars = settings.pr_diff_excerpt_max_chars
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n[diff truncated]"
    return excerpt


def _apply_db_velocity(contribution: ContributionInput) -> dict:
    if not contribution.author:
        return {}
    try:
        recent_count = count_recent_contributions_by_author(
            contribution.author,
            within_hours=settings.velocity_window_hours,
            exclude=(contribution.repository, contribution.kind, contribution.number),
        )
        return {"author_recent_contributions": recent_count + 1}
    except Exception:  # noqa: BLE001
        logger.warning(
            "Velocity lookup failed for author=%s repository=%s",
            contribution.author,
            contribution.repository,
            exc_info=True,
        )
        return {}


def _apply_db_history(contribution: ContributionInput) -> dict:
    if not contribution.author:
        return {}
    try:
        previous_count = count_author_contributions_in_repository(
            contribution.author,
            contribution.repository,
            exclude_kind=contribution.kind,
            exclude_number=contribution.number,
        )
        return {"author_previous_contributions": previous_count}
    except Exception:  # noqa: BLE001
        logger.warning(
            "Contribution history lookup failed for author=%s repository=%s",
            contribution.author,
            contribution.repository,
            exc_info=True,
        )
        return {}


def _apply_account_age(contribution: ContributionInput, client) -> dict:
    if not contribution.author:
        return {}
    try:
        created_at = _resolve_account_created_at(client, contribution.author, contribution.repository)
        if created_at is None:
            return {}
        age_days = (datetime.now(timezone.utc) - created_at).days
        return {"author_account_age_days": age_days}
    except Exception:  # noqa: BLE001
        logger.warning(
            "Account age lookup failed for author=%s repository=%s",
            contribution.author,
            contribution.repository,
            exc_info=True,
        )
        return {}


def _apply_pr_diff(contribution: ContributionInput, client) -> dict:
    if contribution.kind != "pull_request":
        return {}
    try:
        files = client.get_pull_request_files(
            contribution.repository,
            contribution.number,
            max_files=settings.pr_diff_max_files,
        )
        update: dict = {
            "changed_filenames": [file_info["filename"] for file_info in files],
            "diff_excerpt": _format_diff_excerpt(files) or None,
        }
        if contribution.files_changed is None:
            update["files_changed"] = len(files)
        return update
    except Exception:  # noqa: BLE001
        logger.warning(
            "PR diff lookup failed for repository=%s number=%s",
            contribution.repository,
            contribution.number,
            exc_info=True,
        )
        return {}


def enrich_contribution(contribution: ContributionInput) -> ContributionInput:
    """Return an enriched copy of contribution, never raising.

    Every enrichment step degrades gracefully: a failed DB lookup or GitHub
    API call is logged and skipped, leaving the corresponding field(s) None
    rather than aborting the whole pipeline.
    """
    updates: dict = {}
    updates.update(_apply_db_velocity(contribution))
    updates.update(_apply_db_history(contribution))

    try:
        if settings.github_enrichment_enabled:
            client = build_github_client()
            if client.is_configured():
                updates.update(_apply_account_age(contribution, client))
                updates.update(_apply_pr_diff(contribution, client))
    except Exception:  # noqa: BLE001
        logger.warning(
            "GitHub enrichment setup failed for repository=%s number=%s",
            contribution.repository,
            contribution.number,
            exc_info=True,
        )

    if not updates:
        return contribution
    return contribution.model_copy(update=updates)
