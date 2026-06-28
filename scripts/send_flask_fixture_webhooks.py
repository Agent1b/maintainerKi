from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _build_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text())


def _post_fixture(
    client: httpx.Client,
    *,
    base_url: str,
    webhook_secret: str,
    delivery_id: str,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        _join_url(base_url, "/webhooks/github"),
        content=body,
        headers={
            "X-GitHub-Event": event_name,
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": _build_signature(webhook_secret, body),
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    parsed = response.json()
    if parsed.get("status") != "accepted":
        raise RuntimeError(
            f"{event_name} fixture was not accepted: {json.dumps(parsed, indent=2)}"
        )
    print(
        f"✓ sent {event_name} fixture repo={parsed.get('repository')} "
        f"number={parsed.get('number')} delivery={parsed.get('delivery_id')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send bundled Flask issue and PR webhook fixtures to a running maintainerKi instance."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL for the target maintainerKi instance, for example http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.getenv("MAINTAINERKI_WEBHOOK_SECRET"),
        help="GitHub webhook secret. Can also come from MAINTAINERKI_WEBHOOK_SECRET.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args()

    if not args.webhook_secret:
        print(
            "Missing webhook secret. Pass --webhook-secret or set MAINTAINERKI_WEBHOOK_SECRET.",
            file=sys.stderr,
        )
        return 1

    issue_payload = _load_fixture("github_flask_issue_opened.json")
    pr_payload = _load_fixture("github_flask_pr_opened.json")

    try:
        with httpx.Client(timeout=args.timeout_seconds, follow_redirects=True) as client:
            _post_fixture(
                client,
                base_url=args.base_url,
                webhook_secret=args.webhook_secret,
                delivery_id="flask-issue-6065",
                event_name="issues",
                payload=issue_payload,
            )
            _post_fixture(
                client,
                base_url=args.base_url,
                webhook_secret=args.webhook_secret,
                delivery_id="flask-pr-6066",
                event_name="pull_request",
                payload=pr_payload,
            )
    except Exception as exc:  # pragma: no cover - CLI error path
        print(f"Flask fixture webhook test failed: {exc}", file=sys.stderr)
        return 1

    print("Flask fixture webhook test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
