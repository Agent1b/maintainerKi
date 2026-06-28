from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from server.config import settings
from server.ingestion import enqueue_webhook_delivery
from server.rate_limit import rate_limiter, too_many_requests
from server.repository import register_webhook_delivery
from server.request_meta import get_client_ip
from server.webhooks.security import verify_github_signature

router = APIRouter(prefix="/webhooks", tags=["github-webhooks"])
logger = logging.getLogger(__name__)

SUPPORTED_ACTIONS: dict[str, set[str]] = {
    "issues": {"opened", "edited", "reopened"},
    "pull_request": {"opened", "edited", "reopened", "synchronize"},
}


def _normalize_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    repository = payload.get("repository") or {}
    sender = payload.get("sender") or {}

    if event_name == "issues":
        subject = payload.get("issue") or {}
        kind = "issue"
    else:
        subject = payload.get("pull_request") or {}
        kind = "pull_request"

    return {
        "kind": kind,
        "action": payload.get("action"),
        "github_id": subject.get("id"),
        "number": subject.get("number"),
        "title": subject.get("title"),
        "body": subject.get("body") or "",
        "html_url": subject.get("html_url"),
        "repository": repository.get("full_name"),
        "repository_id": repository.get("id"),
        "author": (subject.get("user") or {}).get("login"),
        "sender": sender.get("login"),
    }


@router.post("/github")
async def receive_github_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict[str, Any]:
    rate_limit_decision = rate_limiter.consume(
        "github-webhook",
        get_client_ip(request),
        limit=settings.webhook_rate_limit_requests,
        window_seconds=settings.webhook_rate_limit_window_seconds,
    )
    if not rate_limit_decision.allowed:
        raise too_many_requests(
            "Webhook rate limit exceeded. Try again shortly.",
            rate_limit_decision.retry_after_seconds,
        )

    if not x_github_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header.",
        )

    raw_body = await request.body()
    if not verify_github_signature(
        secret=settings.github_webhook_secret,
        payload=raw_body,
        signature_header=x_hub_signature_256,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    payload = await request.json()

    if x_github_event == "ping":
        logger.info("Received GitHub ping delivery=%s", x_github_delivery)
        return {
            "status": "ok",
            "event": "ping",
            "delivery_id": x_github_delivery,
        }

    if x_github_event not in SUPPORTED_ACTIONS:
        logger.info(
            "Ignoring unsupported GitHub event=%s delivery=%s",
            x_github_event,
            x_github_delivery,
        )
        return {
            "status": "ignored",
            "reason": "unsupported_event",
            "event": x_github_event,
        }

    action = payload.get("action")
    if action not in SUPPORTED_ACTIONS[x_github_event]:
        logger.info(
            "Ignoring unsupported action=%s event=%s delivery=%s",
            action,
            x_github_event,
            x_github_delivery,
        )
        return {
            "status": "ignored",
            "reason": "unsupported_action",
            "event": x_github_event,
            "action": action,
        }

    normalized = _normalize_payload(x_github_event, payload)
    monitored_repositories = settings.monitored_repository_set()
    normalized_repository = str(normalized.get("repository") or "").lower()
    if monitored_repositories and normalized_repository not in monitored_repositories:
        logger.info(
            "Ignoring repo=%s delivery=%s because it is not in MONITORED_REPOSITORIES.",
            normalized.get("repository"),
            x_github_delivery,
        )
        return {
            "status": "ignored",
            "reason": "repository_not_monitored",
            "event": x_github_event,
            "repository": normalized.get("repository"),
        }

    registration = register_webhook_delivery(
        event_name=x_github_event,
        delivery_id=x_github_delivery,
        event=normalized,
    )
    if registration["status"] != "accepted":
        logger.info(
            "Ignored GitHub %s action=%s number=%s repo=%s delivery=%s reason=%s",
            normalized["kind"],
            normalized["action"],
            normalized["number"],
            normalized["repository"],
            registration["delivery_id"],
            registration.get("reason"),
        )
        return {
            "status": "ignored",
            "reason": registration.get("reason", "ignored"),
            "event": x_github_event,
            "action": action,
            "delivery_id": registration["delivery_id"],
            "repository": normalized["repository"],
            "number": normalized["number"],
        }

    background_tasks.add_task(enqueue_webhook_delivery, registration["delivery_id"])

    logger.info(
        "Accepted GitHub %s action=%s number=%s repo=%s delivery=%s",
        normalized["kind"],
        normalized["action"],
        normalized["number"],
        normalized["repository"],
        registration["delivery_id"],
    )

    return {
        "status": "accepted",
        "event": x_github_event,
        "action": action,
        "delivery_id": registration["delivery_id"],
        "repository": normalized["repository"],
        "number": normalized["number"],
    }
