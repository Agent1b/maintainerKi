from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import sys
import uuid
from typing import Any

import httpx


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _build_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _require_ok_json(
    client: httpx.Client,
    label: str,
    url: str,
    *,
    expected_status: int = 200,
) -> dict[str, Any]:
    response = client.get(url)
    response.raise_for_status()
    if response.status_code != expected_status:
        raise RuntimeError(f"{label} returned HTTP {response.status_code}, expected {expected_status}.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} did not return a JSON object.")
    print(f"✓ {label}: {url}")
    return payload


def _login_if_needed(
    client: httpx.Client,
    *,
    base_url: str,
    admin_username: str | None,
    admin_password: str | None,
) -> None:
    session = _require_ok_json(client, "auth session", _join_url(base_url, "/api/auth/session"))
    if not session.get("auth_enabled"):
        return
    if session.get("authenticated"):
        return
    resolved_username = admin_username or os.getenv("MAINTAINERKI_ADMIN_USERNAME")
    resolved_password = admin_password or os.getenv("MAINTAINERKI_ADMIN_PASSWORD")
    if resolved_username and not resolved_password and sys.stdin.isatty():
        resolved_password = getpass.getpass("Admin password: ")
    if not resolved_username or not resolved_password:
        raise RuntimeError(
            "Admin auth is enabled, but admin credentials were not provided. Use --admin-username plus an interactive password prompt or set MAINTAINERKI_ADMIN_USERNAME / MAINTAINERKI_ADMIN_PASSWORD."
        )
    response = client.post(
        _join_url(base_url, "/api/auth/login"),
        json={"username": resolved_username, "password": resolved_password},
    )
    response.raise_for_status()
    confirmed_session = _require_ok_json(
        client,
        "auth session after login",
        _join_url(base_url, "/api/auth/session"),
    )
    if not confirmed_session.get("authenticated"):
        raise RuntimeError("Admin login did not establish an authenticated session.")
    print("✓ admin login")


def run_smoke_test(
    *,
    base_url: str,
    timeout_seconds: float,
    webhook_secret: str | None,
    admin_username: str | None = None,
    admin_password: str | None = None,
) -> int:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        _login_if_needed(
            client,
            base_url=base_url,
            admin_username=admin_username,
            admin_password=admin_password,
        )
        health = _require_ok_json(client, "healthz", _join_url(base_url, "/healthz"))
        if health.get("status") != "ok":
            raise RuntimeError(f"/healthz returned unexpected status: {health}")

        readiness = _require_ok_json(client, "readyz", _join_url(base_url, "/readyz"))
        if readiness.get("status") != "ok":
            raise RuntimeError(f"/readyz is not ready: {json.dumps(readiness, indent=2)}")

        repos = _require_ok_json(client, "api repos", _join_url(base_url, "/api/repos"))
        if "repositories" not in repos:
            raise RuntimeError("/api/repos did not include a repositories field.")

        if webhook_secret:
            payload = b'{"zen":"maintainerKi production smoke test"}'
            headers = {
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": f"smoke-{uuid.uuid4()}",
                "X-Hub-Signature-256": _build_signature(webhook_secret, payload),
                "Content-Type": "application/json",
            }
            webhook_response = client.post(
                _join_url(base_url, "/webhooks/github"),
                content=payload,
                headers=headers,
            )
            webhook_response.raise_for_status()
            webhook_payload = webhook_response.json()
            if webhook_payload.get("event") != "ping":
                raise RuntimeError(
                    f"Webhook ping returned unexpected payload: {json.dumps(webhook_payload, indent=2)}"
                )
            print(f"✓ webhook ping: {_join_url(base_url, '/webhooks/github')}")

    print("Production smoke test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a maintainerKi deployment.")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL for the deployment, for example https://maintainerki.example.com",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--webhook-secret",
        default=os.getenv("MAINTAINERKI_WEBHOOK_SECRET"),
        help="Optional GitHub webhook secret used to send a signed ping request. Can also come from MAINTAINERKI_WEBHOOK_SECRET.",
    )
    parser.add_argument(
        "--admin-username",
        default=os.getenv("MAINTAINERKI_ADMIN_USERNAME"),
        help="Admin username for deployments with dashboard auth enabled. Can also come from MAINTAINERKI_ADMIN_USERNAME.",
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv("MAINTAINERKI_ADMIN_PASSWORD"),
        help="Admin password for deployments with dashboard auth enabled. Can also come from MAINTAINERKI_ADMIN_PASSWORD.",
    )
    args = parser.parse_args()

    try:
        return run_smoke_test(
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            webhook_secret=args.webhook_secret,
            admin_username=args.admin_username,
            admin_password=args.admin_password,
        )
    except Exception as exc:  # pragma: no cover - exercised via CLI
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
