from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from redis import Redis

from server.config import settings
from server.db import get_database_status, get_engine
from server.github_client import GitHubWritebackError, build_github_client
from worker.celery_app import celery_app


def _redact_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.password is None:
        return value
    username = parts.username or ""
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    auth = f"{username}:***@" if username else "***@"
    netloc = f"{auth}{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def check_database() -> dict[str, Any]:
    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        status = get_database_status()
        status.pop("url", None)
        return {
            "ok": True,
            **status,
        }
    except Exception as exc:  # pragma: no cover - depends on runtime database failures
        return {
            "ok": False,
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def check_redis() -> dict[str, Any]:
    queue_provider = settings.queue_provider.lower().strip()
    broker_url = settings.celery_broker_url or settings.redis_url
    required = settings.celery_enabled and queue_provider == "celery"

    if not broker_url:
        return {
            "ok": not required,
            "required": required,
            "configured": False,
            "error": "No Redis or Celery broker URL configured." if required else None,
        }

    try:
        client = Redis.from_url(
            broker_url,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        client.ping()
        return {
            "ok": True,
            "required": required,
            "configured": True,
            "url": _redact_url(broker_url),
        }
    except Exception as exc:  # pragma: no cover - depends on runtime broker failures
        return {
            "ok": False,
            "required": required,
            "configured": True,
            "url": _redact_url(broker_url),
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def check_worker() -> dict[str, Any]:
    queue_provider = settings.queue_provider.lower().strip()
    required = settings.celery_enabled and queue_provider == "celery"

    if not required:
        return {
            "ok": True,
            "required": False,
            "workers": [],
        }

    if not (settings.celery_broker_url or settings.redis_url):
        return {
            "ok": False,
            "required": True,
            "workers": [],
            "error": "Celery is enabled but no broker is configured.",
        }

    try:
        responses = celery_app.control.inspect(timeout=3).ping() or {}
    except Exception as exc:  # pragma: no cover - depends on runtime worker failures
        return {
            "ok": False,
            "required": True,
            "workers": [],
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    workers = sorted(str(name) for name in responses.keys())
    return {
        "ok": bool(workers),
        "required": True,
        "workers": workers,
        "error": None if workers else "No Celery workers responded to ping.",
    }


def check_github_app_config() -> dict[str, Any]:
    app_id = settings.github_app_id.strip()
    secret_present = bool(settings.github_webhook_secret.strip())
    key_path = settings.github_private_key_path.strip()
    required = settings.app_env.lower() == "production"

    configured = bool(app_id and key_path and secret_present)
    if not configured:
        return {
            "ok": not required,
            "required": required,
            "configured": False,
            "app_id_present": bool(app_id),
            "webhook_secret_present": secret_present,
            "private_key_exists": bool(key_path) and Path(key_path).exists(),
            "private_key_readable": False,
            "error": None if not required else "GitHub App credentials are incomplete.",
        }

    path = Path(key_path).expanduser()
    key_exists = path.exists()
    if not key_exists:
        return {
            "ok": False,
            "required": required,
            "configured": True,
            "app_id_present": True,
            "webhook_secret_present": True,
            "private_key_exists": False,
            "private_key_readable": False,
            "error": "GitHub App private key file is missing.",
        }

    try:
        path.read_text()
    except OSError as exc:
        return {
            "ok": False,
            "required": required,
            "configured": True,
            "app_id_present": True,
            "webhook_secret_present": True,
            "private_key_exists": True,
            "private_key_readable": False,
            "error": f"GitHub App private key is not readable: {exc}",
        }

    if not required:
        return {
            "ok": True,
            "required": False,
            "configured": True,
            "app_id_present": True,
            "webhook_secret_present": True,
            "private_key_exists": True,
            "private_key_readable": True,
            "error": None,
        }

    try:
        app_payload = build_github_client().get_authenticated_app()
    except GitHubWritebackError as exc:
        return {
            "ok": False,
            "required": True,
            "configured": True,
            "app_id_present": True,
            "webhook_secret_present": True,
            "private_key_exists": True,
            "private_key_readable": True,
            "error": str(exc),
        }

    return {
        "ok": True,
        "required": True,
        "configured": True,
        "app_id_present": True,
        "webhook_secret_present": True,
        "private_key_exists": True,
        "private_key_readable": True,
        "app_slug": app_payload.get("slug"),
        "error": None,
    }


def build_readiness_status() -> dict[str, Any]:
    components = {
        "database": check_database(),
        "redis": check_redis(),
        "worker": check_worker(),
        "github_app": check_github_app_config(),
    }
    ready = all(bool(component.get("ok")) for component in components.values())
    return {
        "status": "ok" if ready else "degraded",
        "environment": settings.app_env,
        "components": components,
    }
