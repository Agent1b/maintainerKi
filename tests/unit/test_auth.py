from __future__ import annotations

import time

from server.auth import build_session_cookie, hash_password, parse_session_cookie, verify_password_hash


def test_password_hash_round_trip() -> None:
    stored_hash = hash_password("correct horse battery staple")
    assert verify_password_hash("correct horse battery staple", stored_hash) is True
    assert verify_password_hash("wrong password", stored_hash) is False


def test_session_cookie_round_trip(monkeypatch) -> None:
    monkeypatch.setattr("server.config.settings.session_secret", "super-secret-session-key")
    token = build_session_cookie("admin")
    principal = parse_session_cookie(token)
    assert principal is not None
    assert principal.username == "admin"


def test_session_cookie_rejects_tampering(monkeypatch) -> None:
    monkeypatch.setattr("server.config.settings.session_secret", "super-secret-session-key")
    token = build_session_cookie("admin")
    payload_part, signature_part = token.split(".", maxsplit=1)
    tampered_signature = ("a" if signature_part[0] != "a" else "b") + signature_part[1:]
    tampered = f"{payload_part}.{tampered_signature}"
    assert parse_session_cookie(tampered) is None


def test_session_cookie_honors_not_before_epoch(monkeypatch) -> None:
    monkeypatch.setattr("server.config.settings.session_secret", "super-secret-session-key")
    monkeypatch.setattr("server.config.settings.session_not_before_epoch", 0)
    token = build_session_cookie("admin")
    monkeypatch.setattr("server.config.settings.session_not_before_epoch", int(time.time()) + 1)
    assert parse_session_cookie(token) is None
