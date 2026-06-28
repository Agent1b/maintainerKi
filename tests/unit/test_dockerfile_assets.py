from __future__ import annotations

from pathlib import Path


def test_backend_dockerfile_copies_alembic_assets() -> None:
    dockerfile = Path("Dockerfile").read_text()

    assert "COPY db_migrations ./db_migrations" in dockerfile
    assert "COPY alembic.ini ./" in dockerfile
