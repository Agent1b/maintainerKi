from __future__ import annotations

import hashlib
import hmac

GITHUB_SHA256_PREFIX = "sha256="


def build_github_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{GITHUB_SHA256_PREFIX}{digest}"


def verify_github_signature(
    secret: str,
    payload: bytes,
    signature_header: str | None,
) -> bool:
    if not secret or not signature_header:
        return False

    if not signature_header.startswith(GITHUB_SHA256_PREFIX):
        return False

    expected_signature = build_github_signature(secret, payload)
    return hmac.compare_digest(expected_signature, signature_header)

