from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from scripts import release_audit


def test_find_secret_risk_files_allows_env_examples_and_flags_real_risks() -> None:
    allowed, unexpected = release_audit.find_secret_risk_files(
        [
            Path(".env.example"),
            Path(".env.production.example"),
            Path("private-key.pem"),
            Path("state/maintainerki.sqlite3"),
            Path("README.md"),
        ]
    )

    assert allowed == [Path(".env.example"), Path(".env.production.example")]
    assert unexpected == [Path("private-key.pem"), Path("state/maintainerki.sqlite3")]


def test_resolve_tool_prefers_repo_local_binary(tmp_path, monkeypatch) -> None:
    tool_path = tmp_path / ".venv/bin/pip-audit"
    tool_path.parent.mkdir(parents=True)
    tool_path.write_text("")
    monkeypatch.setattr(release_audit.shutil, "which", lambda _: "/usr/local/bin/pip-audit")

    resolved = release_audit.resolve_tool(tmp_path, ".venv/bin/pip-audit", "pip-audit")

    assert resolved == str(tool_path)


def test_resolve_tool_falls_back_to_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(release_audit.shutil, "which", lambda _: "/usr/local/bin/npm")

    resolved = release_audit.resolve_tool(tmp_path, None, "npm")

    assert resolved == "/usr/local/bin/npm"


def test_ensure_clean_worktree_raises_on_dirty_checkout(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        release_audit,
        "_run_git",
        lambda repo_root, *args: type("Result", (), {"stdout": " M README.md\n"})(),
    )

    with pytest.raises(RuntimeError, match="Working tree is not clean"):
        release_audit.ensure_clean_worktree(tmp_path)


def test_verify_snapshot_archive_accepts_exact_tracked_files(tmp_path) -> None:
    archive_path = tmp_path / "snapshot.tar.gz"
    tracked_files = [Path("README.md"), Path("server/main.py")]
    prefix = "maintainerKi-source"

    with tarfile.open(archive_path, "w:gz") as archive:
        for relative_path in tracked_files:
            source_path = tmp_path / relative_path
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(relative_path.as_posix())
            archive.add(source_path, arcname=f"{prefix}/{relative_path.as_posix()}")

    release_audit.verify_snapshot_archive(
        archive_path=archive_path,
        tracked_files=tracked_files,
        snapshot_prefix=prefix,
        disallowed_files=[Path(".env")],
    )


def test_verify_snapshot_archive_rejects_unsafe_untracked_files(tmp_path) -> None:
    archive_path = tmp_path / "snapshot.tar.gz"
    tracked_files = [Path("README.md")]
    prefix = "maintainerKi-source"

    readme_path = tmp_path / "README.md"
    readme_path.write_text("readme")
    env_path = tmp_path / ".env"
    env_path.write_text("secret")

    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(readme_path, arcname=f"{prefix}/README.md")
        archive.add(env_path, arcname=f"{prefix}/.env")

    with pytest.raises(RuntimeError, match="unsafe untracked files"):
        release_audit.verify_snapshot_archive(
            archive_path=archive_path,
            tracked_files=tracked_files,
            snapshot_prefix=prefix,
            disallowed_files=[Path(".env")],
        )
