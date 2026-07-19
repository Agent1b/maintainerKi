from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urlsplit, urlunsplit

from redis import Redis

from server.config import settings
from server.db import get_database_status, get_engine
from server.github_client import GitHubAppClient, GitHubWritebackError
from worker.celery_app import celery_app

T = TypeVar("T")

# Fixed (short) TTL for a *failed* GitHub readiness check, so a transient
# GitHub outage does not keep /readyz reporting unready long after GitHub
# recovers. Successful checks use the (longer) settings.github_readiness_cache_seconds.
_GITHUB_READINESS_FAILURE_CACHE_SECONDS = 30.0

# Bounds how long the worker/inspect probe waits for a Celery ping reply,
# independent of the total time it may take to establish the broker
# connection (which celery's own `timeout=` kwarg does not cover).
_CELERY_INSPECT_TIMEOUT_SECONDS = 5.0

_github_readiness_lock = threading.Lock()
_github_readiness_cache: dict[str, Any] | None = None
_github_readiness_checked_at: float = 0.0


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


def _now() -> float:
    """Monotonic clock indirection so tests can fake the passage of time
    without touching the real `time` module (which concurrent.futures also
    relies on for its own timeout bookkeeping)."""
    return time.monotonic()


def _call_with_timeout(func: Callable[[], T], *, timeout_seconds: float, thread_name: str) -> T:
    """Run `func` on a worker thread and bound the *total* wait time.

    A per-request HTTP timeout only bounds a single attempt; it does not
    bound retry loops inside `func`. Running the call on its own thread and
    giving up on `future.result()` after `timeout_seconds` bounds the whole
    operation from the caller's perspective, even if the worker thread is
    still retrying in the background. Raises concurrent.futures.TimeoutError
    if `func` does not complete in time.
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name)
    try:
        future = executor.submit(func)
        return future.result(timeout=timeout_seconds)
    finally:
        # Do not block shutdown on a still-running (e.g. still retrying)
        # call; let it finish in the background and be garbage collected.
        executor.shutdown(wait=False)


def _build_github_readiness_client() -> GitHubAppClient:
    """Factory for the GitHub client used by the readiness probe.

    Deliberately separate from build_github_client(): that helper always
    uses settings.github_writeback_timeout_seconds (30s, tuned for
    label/comment write-backs), which is far too long for a readiness probe.
    This uses the short settings.github_readiness_timeout_seconds instead.
    Kept as its own function so tests can monkeypatch it and count calls.
    """
    return GitHubAppClient(
        app_id=settings.github_app_id,
        private_key_path=settings.github_private_key_path,
        base_url=settings.github_api_base_url,
        timeout_seconds=settings.github_readiness_timeout_seconds,
        auto_create_labels=settings.github_auto_create_labels,
    )


def _perform_github_readiness_check() -> dict[str, Any]:
    try:
        app_payload = _call_with_timeout(
            lambda: _build_github_readiness_client().get_authenticated_app(),
            timeout_seconds=settings.github_readiness_timeout_seconds,
            thread_name="readyz-github",
        )
    except FutureTimeoutError:
        return {
            "ok": False,
            "app_slug": None,
            "error": (
                "Timed out waiting for GitHub App authentication check "
                f"after {settings.github_readiness_timeout_seconds}s."
            ),
        }
    except GitHubWritebackError as exc:
        return {
            "ok": False,
            "app_slug": None,
            "error": str(exc),
        }
    return {
        "ok": True,
        "app_slug": app_payload.get("slug"),
        "error": None,
    }


def _cached_github_readiness_check() -> dict[str, Any]:
    """Return the cached GitHub readiness result, refreshing it if the cache
    is empty or older than its TTL. Guarded by a lock only around the cache
    read/write, never around the (slow, network-bound) refresh itself, so
    concurrent probes are not serialized behind one slow GitHub call."""
    global _github_readiness_cache, _github_readiness_checked_at

    with _github_readiness_lock:
        cached = _github_readiness_cache
        checked_at = _github_readiness_checked_at

    if cached is not None:
        ttl = (
            settings.github_readiness_cache_seconds
            if cached["ok"]
            else _GITHUB_READINESS_FAILURE_CACHE_SECONDS
        )
        if _now() - checked_at < ttl:
            return cached

    result = _perform_github_readiness_check()
    with _github_readiness_lock:
        _github_readiness_cache = result
        _github_readiness_checked_at = _now()
    return result


def _reset_github_readiness_cache() -> None:
    """Test hook: clear the cached GitHub readiness probe result."""
    global _github_readiness_cache, _github_readiness_checked_at
    with _github_readiness_lock:
        _github_readiness_cache = None
        _github_readiness_checked_at = 0.0


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
        responses = _call_with_timeout(
            lambda: celery_app.control.inspect(timeout=3).ping() or {},
            timeout_seconds=_CELERY_INSPECT_TIMEOUT_SECONDS,
            thread_name="readyz-celery",
        )
    except FutureTimeoutError:
        return {
            "ok": False,
            "required": True,
            "workers": [],
            "error": f"Celery worker check timed out after {_CELERY_INSPECT_TIMEOUT_SECONDS}s.",
        }
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

    live_check = _cached_github_readiness_check()
    if not live_check["ok"]:
        return {
            "ok": False,
            "required": True,
            "configured": True,
            "app_id_present": True,
            "webhook_secret_present": True,
            "private_key_exists": True,
            "private_key_readable": True,
            "error": live_check["error"],
        }

    return {
        "ok": True,
        "required": True,
        "configured": True,
        "app_id_present": True,
        "webhook_secret_present": True,
        "private_key_exists": True,
        "private_key_readable": True,
        "app_slug": live_check["app_slug"],
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
