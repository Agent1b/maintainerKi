from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from server.auth import hash_password


def _dotenv_literal(value: str) -> str:
    if "'" in value:
        raise ValueError("Generated auth value unexpectedly contained a single quote.")
    return f"'{value}'"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate maintainerKi admin auth values for .env.production.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Optional plaintext password. If omitted, you will be prompted twice.",
    )
    parser.add_argument(
        "--secret-bytes",
        type=int,
        default=32,
        help="Number of random bytes used for SESSION_SECRET output.",
    )
    args = parser.parse_args()

    password = args.password or _prompt_for_password()
    print(f"ADMIN_PASSWORD_HASH={_dotenv_literal(hash_password(password))}")
    print(f"SESSION_SECRET={_dotenv_literal(secrets.token_urlsafe(args.secret_bytes))}")
    return 0


def _prompt_for_password() -> str:
    first = getpass.getpass("Admin password: ")
    second = getpass.getpass("Repeat password: ")
    if not first:
        raise SystemExit("Password must not be empty.")
    if first != second:
        raise SystemExit("Passwords did not match.")
    return first


if __name__ == "__main__":
    raise SystemExit(main())
