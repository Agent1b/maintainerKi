from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_e2e_uses_absolute_workspace_python_path() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["dashboard-e2e"]["steps"]
    e2e_step = next(step for step in steps if step.get("name") == "Run dashboard E2E")

    assert e2e_step["working-directory"] == "dashboard"
    assert e2e_step["env"]["PW_PYTHON"] == "${{ github.workspace }}/.venv/bin/python"


def test_release_workflow_marks_hyphenated_versions_as_prereleases() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/release.yml").read_text())
    steps = workflow["jobs"]["release"]["steps"]
    publish_step = next(step for step in steps if step.get("name") == "Publish GitHub release")
    script = publish_step["run"]

    assert '[[ "$GITHUB_REF_NAME" == *-* ]]' in script
    assert "release_args+=(--prerelease)" in script


def test_production_smoke_key_is_readable_by_non_root_container() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["production-stack-smoke"]["steps"]
    smoke_step = next(
        step for step in steps if step.get("name") == "Boot production-like stack and run smoke test"
    )

    assert 'chmod 0644 "$github_key_host_path"' in smoke_step["run"]
