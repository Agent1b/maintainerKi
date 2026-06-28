from __future__ import annotations

from scripts.generate_admin_auth import _dotenv_literal


def test_dotenv_literal_wraps_values_in_single_quotes() -> None:
    assert _dotenv_literal("pbkdf2_sha256$600000$salt$hash") == "'pbkdf2_sha256$600000$salt$hash'"


def test_dotenv_literal_rejects_embedded_single_quotes() -> None:
    try:
        _dotenv_literal("bad'value")
    except ValueError as exc:
        assert "single quote" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected _dotenv_literal to reject embedded single quotes.")
