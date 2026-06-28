from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response, status

from server.config import settings

PBKDF2_HASH_NAME = "sha256"
PBKDF2_ITERATIONS = 600_000
MIN_SESSION_SECRET_LENGTH = 32
PLACEHOLDER_PREFIXES = ("replace-", "change-me", "example-", "your-")
PLACEHOLDER_VALUES = {
    "replace-me",
    "replace-with-generated-hash",
    "replace-with-long-random-secret",
    "change-me",
}


@dataclass(slots=True)
class SessionPrincipal:
    username: str
    expires_at: int


def validate_admin_auth_settings() -> None:
    is_production = settings.app_env.lower() == "production"
    if is_production and not settings.admin_auth_enabled:
        raise RuntimeError("ADMIN_AUTH_ENABLED must remain true when APP_ENV=production.")
    if not settings.admin_auth_enabled:
        return
    if not settings.admin_username.strip():
        raise RuntimeError("ADMIN_USERNAME must not be empty when ADMIN_AUTH_ENABLED=true.")
    if not settings.session_secret.strip():
        raise RuntimeError("SESSION_SECRET is required when ADMIN_AUTH_ENABLED=true.")
    if len(settings.session_secret.strip()) < MIN_SESSION_SECRET_LENGTH:
        raise RuntimeError(
            f"SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} characters long."
        )
    if _looks_like_placeholder(settings.session_secret):
        raise RuntimeError("SESSION_SECRET must be replaced with a real random value.")
    if is_production and settings.admin_password.strip():
        raise RuntimeError(
            "ADMIN_PASSWORD is not allowed when APP_ENV=production. Use ADMIN_PASSWORD_HASH."
        )
    if not (settings.admin_password_hash.strip() or settings.admin_password.strip()):
        raise RuntimeError(
            "Either ADMIN_PASSWORD_HASH or ADMIN_PASSWORD is required when ADMIN_AUTH_ENABLED=true."
        )
    if is_production and not settings.admin_password_hash.strip():
        raise RuntimeError("ADMIN_PASSWORD_HASH is required when APP_ENV=production.")
    if settings.admin_password_hash.strip() and _looks_like_placeholder(settings.admin_password_hash):
        raise RuntimeError("ADMIN_PASSWORD_HASH still contains a placeholder value.")
    if settings.admin_password.strip() and _looks_like_placeholder(settings.admin_password):
        raise RuntimeError("ADMIN_PASSWORD still contains a placeholder value.")


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("Password must not be empty.")
    if iterations < 100_000:
        raise ValueError("PBKDF2 iteration count is too low.")
    resolved_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_HASH_NAME,
        password.encode("utf-8"),
        resolved_salt,
        iterations,
    )
    return (
        f"pbkdf2_{PBKDF2_HASH_NAME}${iterations}$"
        f"{_urlsafe_b64encode(resolved_salt)}${_urlsafe_b64encode(digest)}"
    )


def verify_password_hash(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    try:
        scheme, iterations_raw, salt_encoded, digest_encoded = stored_hash.split("$", maxsplit=3)
        if scheme != f"pbkdf2_{PBKDF2_HASH_NAME}":
            return False
        iterations = int(iterations_raw)
        salt = _urlsafe_b64decode(salt_encoded)
        expected_digest = _urlsafe_b64decode(digest_encoded)
    except (TypeError, ValueError):
        return False

    computed_digest = hashlib.pbkdf2_hmac(
        PBKDF2_HASH_NAME,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(computed_digest, expected_digest)


def build_session_cookie(username: str) -> str:
    issued_at = int(time.time())
    payload = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + settings.session_ttl_seconds,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_json,
        hashlib.sha256,
    ).digest()
    return f"{_urlsafe_b64encode(payload_json)}.{_urlsafe_b64encode(signature)}"


def parse_session_cookie(cookie_value: str | None) -> SessionPrincipal | None:
    if not cookie_value or not settings.session_secret.strip():
        return None
    try:
        payload_part, signature_part = cookie_value.split(".", maxsplit=1)
        payload_json = _urlsafe_b64decode(payload_part)
        provided_signature = _urlsafe_b64decode(signature_part)
    except ValueError:
        return None

    expected_signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload_json,
        hashlib.sha256,
    ).digest()
    if not secrets.compare_digest(provided_signature, expected_signature):
        return None

    try:
        payload = json.loads(payload_json.decode("utf-8"))
        username = str(payload["sub"])
        issued_at = int(payload.get("iat", 0))
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if expires_at <= int(time.time()):
        return None
    if issued_at and issued_at < settings.session_not_before_epoch:
        return None

    return SessionPrincipal(username=username, expires_at=expires_at)


def set_session_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=build_session_cookie(username),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def get_current_session(request: Request) -> SessionPrincipal | None:
    if not settings.admin_auth_enabled:
        return None
    validate_admin_auth_settings()
    return parse_session_cookie(request.cookies.get(settings.session_cookie_name))


def require_admin_session(request: Request) -> SessionPrincipal | None:
    if not settings.admin_auth_enabled:
        return None
    session = get_current_session(request)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return session


def enforce_same_origin_admin_request(request: Request) -> None:
    if not settings.admin_auth_enabled:
        return

    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-site admin requests are not allowed.",
        )

    source_host = _normalized_netloc(source)
    allowed_hosts = {_normalized_host_header(request.headers.get("host", ""))}
    allowed_hosts.update(_configured_dashboard_hosts())

    if source_host and source_host in allowed_hosts:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Cross-site admin requests are not allowed.",
    )


def verify_login_credentials(username: str, password: str) -> bool:
    if not settings.admin_auth_enabled:
        return True
    validate_admin_auth_settings()
    if not secrets.compare_digest(username, settings.admin_username):
        return False

    if settings.admin_password_hash.strip():
        return verify_password_hash(password, settings.admin_password_hash.strip())

    if settings.admin_password.strip():
        return secrets.compare_digest(password, settings.admin_password)

    return False


def _looks_like_placeholder(value: str) -> bool:
    stripped = value.strip().lower()
    return stripped in PLACEHOLDER_VALUES or stripped.startswith(PLACEHOLDER_PREFIXES)


def _configured_dashboard_hosts() -> set[str]:
    hosts: set[str] = set()
    for origin in settings.dashboard_allowed_origins.split(","):
        normalized = _normalized_netloc(origin.strip())
        if normalized:
            hosts.add(normalized)
    return hosts


def _normalized_host_header(value: str) -> str:
    return value.strip().lower()


def _normalized_netloc(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return parsed.netloc.strip().lower() if parsed.netloc else ""


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)
