from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _ensure_clean_worktree() -> None:
    status = _run_git("status", "--porcelain").stdout.strip()
    if status:
        raise SystemExit(
            "Working tree is not clean. Commit or stash changes before exporting a source release."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a safe source snapshot from tracked git files.")
    parser.add_argument(
        "--output",
        default="dist/maintainerki-source-snapshot.tar.gz",
        help="Where to write the tar.gz archive.",
    )
    parser.add_argument(
        "--prefix",
        default="maintainerKi-source",
        help="Top-level folder name inside the archive.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow exporting from HEAD even when the working tree has uncommitted changes.",
    )
    args = parser.parse_args()

    try:
        _run_git("rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "No git commit exists yet. Create a tracked source snapshot commit before exporting a source release."
        ) from exc

    if not args.allow_dirty:
        _ensure_clean_worktree()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix={args.prefix}/",
            "-o",
            str(output_path),
            "HEAD",
        ],
        check=True,
    )

    print(f"Wrote safe source snapshot to {output_path}")

if __name__ == "__main__":
    main()
