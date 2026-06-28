from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "github_issue_opened.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import db as db_module
from server.db import init_database, run_database_migrations
from server.repository import persist_scored_contribution
from server.scorer.models import ScoreResult


def _reset_database_state() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._session_factory = None
    db_module._database_backend_name = None
    db_module._using_sqlite_fallback = False


def _load_fixture_event() -> dict[str, object]:
    payload = json.loads(FIXTURE_PATH.read_text())
    issue = payload["issue"]
    repository = payload["repository"]
    sender = payload["sender"]
    return {
        "repository": repository["full_name"],
        "repository_id": repository["id"],
        "github_id": issue["id"],
        "kind": "issue",
        "action": payload["action"],
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "author": issue["user"]["login"],
        "sender": sender["login"],
        "html_url": issue["html_url"],
    }


def _seed() -> None:
    db_path = os.environ.get("MAINTAINERKI_E2E_DB_PATH", "").strip()
    if db_path:
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        if db_file.exists():
            db_file.unlink()

    _reset_database_state()
    init_database()
    run_database_migrations()

    issue_event = _load_fixture_event()
    issue_score = ScoreResult(
        quality=84,
        relevance=92,
        completeness=76,
        suspicion=8,
        overall_score=85,
        summary="Clear reproduction details and a concrete mobile regression worth maintainer review.",
        suggested_labels=["maintainerki:review-first", "documentation"],
        provider="mock",
        model="playwright-e2e",
        prompt_version="e2e-seed-v1",
    )
    persist_scored_contribution(issue_event, issue_score)

    pull_request_event = {
        "repository": "example/repo",
        "repository_id": 999,
        "github_id": 202,
        "kind": "pull_request",
        "action": "opened",
        "number": 71,
        "title": "Throttle webhook replay retries",
        "body": (
            "Adds a small backoff around webhook replay fetches so transient 502s do not fan "
            "out into duplicate processing."
        ),
        "author": "hubot",
        "sender": "hubot",
        "html_url": "https://github.com/example/repo/pull/71",
    }
    pull_request_score = ScoreResult(
        quality=74,
        relevance=81,
        completeness=69,
        suspicion=11,
        overall_score=75,
        summary="Solid operational fix with enough context for a maintainer to validate quickly.",
        suggested_labels=["maintainerki:worth-a-look", "backend"],
        provider="mock",
        model="playwright-e2e",
        prompt_version="e2e-seed-v1",
    )
    persist_scored_contribution(pull_request_event, pull_request_score)


if __name__ == "__main__":
    _seed()
