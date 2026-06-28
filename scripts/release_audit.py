from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SNAPSHOT_PREFIX = "maintainerKi-source"
MAX_REPORTED_PATHS = 10


def resolve_tool(repo_root: Path, preferred_relative_path: str | None, fallback_name: str) -> str:
    if preferred_relative_path:
        preferred = repo_root / preferred_relative_path
        if preferred.exists():
            return str(preferred)
    resolved = shutil.which(fallback_name)
    if resolved:
        return resolved
    preferred_text = f"{preferred_relative_path} or " if preferred_relative_path else ""
    raise RuntimeError(f"Required executable not found: expected {preferred_text}{fallback_name}.")


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    label: str,
    capture_output: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> None:
    print(f"→ {label}", flush=True)
    try:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=capture_output,
            capture_output=capture_output,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="", flush=True)
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr, flush=True)
        raise
    print(f"✓ {label}", flush=True)


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def _parse_git_path_list(stdout: str) -> list[Path]:
    return [Path(item) for item in stdout.split("\0") if item]


def list_tracked_files(repo_root: Path) -> list[Path]:
    return _parse_git_path_list(_run_git(repo_root, "ls-files", "-z").stdout)


def list_untracked_files(repo_root: Path) -> list[Path]:
    return _parse_git_path_list(_run_git(repo_root, "ls-files", "--others", "--exclude-standard", "-z").stdout)


def ensure_clean_worktree(repo_root: Path) -> None:
    status = _run_git(repo_root, "status", "--porcelain").stdout.strip()
    if status:
        raise RuntimeError("Working tree is not clean. Commit or stash changes before running a release audit.")


def is_secret_risk_path(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in {"id_rsa", "id_ed25519"}:
        return True
    return name.endswith((".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".der", ".db", ".sqlite", ".sqlite3"))


def is_allowed_tracked_secret_risk(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(".env") and name.endswith(".example")


def find_secret_risk_files(paths: Sequence[Path]) -> tuple[list[Path], list[Path]]:
    allowed: list[Path] = []
    unexpected: list[Path] = []
    for path in paths:
        if not is_secret_risk_path(path):
            continue
        if is_allowed_tracked_secret_risk(path):
            allowed.append(path)
        else:
            unexpected.append(path)
    return sorted(allowed), sorted(unexpected)


def verify_snapshot_archive(
    *,
    archive_path: Path,
    tracked_files: Sequence[Path],
    snapshot_prefix: str,
    disallowed_files: Sequence[Path] = (),
) -> None:
    expected_members = {f"{snapshot_prefix}/{path.as_posix()}" for path in tracked_files}
    with tarfile.open(archive_path, "r:gz") as archive:
        actual_members = {member.name for member in archive.getmembers() if member.isfile()}

    blocked_members = {f"{snapshot_prefix}/{path.as_posix()}" for path in disallowed_files}
    leaked = sorted(actual_members & blocked_members)
    if leaked:
        raise RuntimeError(
            "Source snapshot included unsafe untracked files: "
            + ", ".join(leaked[:MAX_REPORTED_PATHS])
        )

    missing = sorted(expected_members - actual_members)
    extra = sorted(actual_members - expected_members)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing={missing[:MAX_REPORTED_PATHS]}")
        if extra:
            details.append(f"extra={extra[:MAX_REPORTED_PATHS]}")
        raise RuntimeError(
            "Source snapshot contents did not match tracked git files: " + "; ".join(details)
        )


def _audit_tracked_secret_risk_files(repo_root: Path) -> list[Path]:
    tracked_files = list_tracked_files(repo_root)
    allowed, unexpected = find_secret_risk_files(tracked_files)
    if unexpected:
        joined = ", ".join(path.as_posix() for path in unexpected[:MAX_REPORTED_PATHS])
        raise RuntimeError(f"Tracked secret-risk files must not ship in source releases: {joined}")
    if allowed:
        joined = ", ".join(path.as_posix() for path in allowed)
        print(f"✓ tracked secret-risk files: safe examples only ({joined})", flush=True)
    else:
        print("✓ tracked secret-risk files: none found", flush=True)
    return tracked_files


def _verify_safe_source_snapshot(
    repo_root: Path,
    *,
    python_executable: str,
    tracked_files: Sequence[Path],
    allow_dirty: bool,
) -> None:
    print("→ safe source snapshot export", flush=True)
    risky_untracked_files = [path for path in list_untracked_files(repo_root) if is_secret_risk_path(path)]
    with tempfile.TemporaryDirectory(prefix="maintainerki-release-audit-") as temp_dir:
        snapshot_path = Path(temp_dir) / "maintainerki-source-snapshot.tar.gz"
        try:
            subprocess.run(
                [
                python_executable,
                "-m",
                "scripts.export_source_snapshot",
                "--output",
                str(snapshot_path),
                "--prefix",
                SOURCE_SNAPSHOT_PREFIX,
                *(["--allow-dirty"] if allow_dirty else []),
            ],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            if exc.stdout:
                print(exc.stdout, end="", flush=True)
            if exc.stderr:
                print(exc.stderr, end="", file=sys.stderr, flush=True)
            raise
        verify_snapshot_archive(
            archive_path=snapshot_path,
            tracked_files=tracked_files,
            snapshot_prefix=SOURCE_SNAPSHOT_PREFIX,
            disallowed_files=risky_untracked_files,
        )
    print("✓ safe source snapshot export", flush=True)


def run_release_audit(*, repo_root: Path = REPO_ROOT, allow_dirty: bool = False) -> int:
    print("maintainerKi release audit", flush=True)
    print("=========================", flush=True)

    python_executable = resolve_tool(repo_root, ".venv/bin/python", "python3")
    pytest_executable = resolve_tool(repo_root, ".venv/bin/pytest", "pytest")
    pip_audit_executable = resolve_tool(repo_root, ".venv/bin/pip-audit", "pip-audit")
    npm_executable = resolve_tool(repo_root, None, "npm")
    docker_executable = resolve_tool(repo_root, None, "docker")

    if not allow_dirty:
        ensure_clean_worktree(repo_root)
        print("✓ working tree is clean", flush=True)
    else:
        print("! skipping clean-tree release check (--allow-dirty)", flush=True)

    tracked_files = _audit_tracked_secret_risk_files(repo_root)

    _run_command([pytest_executable, "-q"], cwd=repo_root, label="backend tests")
    _run_command([npm_executable, "run", "lint"], cwd=repo_root / "dashboard", label="dashboard lint")
    _run_command([npm_executable, "run", "build"], cwd=repo_root / "dashboard", label="dashboard build")
    _run_command(
        [pip_audit_executable, "-r", "requirements.txt"],
        cwd=repo_root,
        label="Python dependency audit",
    )
    _run_command(
        [npm_executable, "audit", "--omit=dev", "--audit-level=high"],
        cwd=repo_root / "dashboard",
        label="dashboard production dependency audit",
    )
    _run_command(
        [
            docker_executable,
            "compose",
            "--env-file",
            ".env.production.example",
            "-f",
            "docker-compose.production.yml",
            "-f",
            "docker-compose.hosted.yml",
            "config",
        ],
        cwd=repo_root,
        label="hosted compose render with .env.production.example",
        capture_output=True,
        env_overrides={"MAINTAINERKI_ENV_FILE": ".env.production.example"},
    )
    _verify_safe_source_snapshot(
        repo_root,
        python_executable=python_executable,
        tracked_files=tracked_files,
        allow_dirty=allow_dirty,
    )

    print("Release audit passed.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a one-command release hygiene audit for self-hosted open-source maintainerKi releases.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Skip the clean working tree requirement while validating an in-progress checkout.",
    )
    args = parser.parse_args()
    try:
        return run_release_audit(allow_dirty=args.allow_dirty)
    except Exception as exc:  # pragma: no cover - exercised via CLI
        print(f"Release audit failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
