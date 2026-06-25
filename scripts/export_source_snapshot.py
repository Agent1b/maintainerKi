from __future__ import annotations

import argparse
import subprocess
import tarfile
from pathlib import Path


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True)


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
    args = parser.parse_args()

    try:
        _run_git("rev-parse", "--verify", "HEAD")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "No git commit exists yet. Create a tracked source snapshot commit before exporting a source release."
        ) from exc

    tracked = _run_git("ls-files", "-z").stdout.split("\0")
    tracked_files = [Path(item) for item in tracked if item]
    if not tracked_files:
        raise SystemExit("No tracked files were found. Commit the project files first.")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, "w:gz") as archive:
        for path in tracked_files:
            archive.add(path, arcname=f"{args.prefix}/{path.as_posix()}")

    print(f"Wrote safe source snapshot to {output_path}")

if __name__ == "__main__":
    main()
