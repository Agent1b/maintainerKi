from __future__ import annotations

import argparse
import json

from server.config import settings
from server.db import init_database, run_database_migrations
from server.repository import apply_retention_purge, plan_retention_purge


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrub or delete old maintainerKi data according to the configured retention windows.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the purge. Without this flag the command only prints a dry-run plan.",
    )
    args = parser.parse_args()

    init_database()
    run_database_migrations()

    retention = {
        "webhook_retention_days": settings.webhook_retention_days,
        "contribution_body_retention_days": settings.contribution_body_retention_days,
        "feedback_note_retention_days": settings.feedback_note_retention_days,
    }
    plan = plan_retention_purge(**retention)

    if not args.apply:
        print(json.dumps({"mode": "dry-run", "retention": retention, "plan": plan}, indent=2))
        return 0

    result = apply_retention_purge(**retention)
    print(json.dumps({"mode": "applied", "retention": retention, "result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
