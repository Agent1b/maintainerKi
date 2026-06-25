from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from server.github_client import GitHubAppClient, GitHubWritebackError


@dataclass(slots=True)
class WizardConfig:
    app_id: str
    private_key_path: str
    webhook_secret: str
    github_api_base_url: str
    monitored_repositories: list[str]
    suspicious_score_threshold: int
    needs_info_completeness_threshold: int
    review_first_threshold: int
    worth_a_look_threshold: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive setup wizard for maintainerKi.",
    )
    parser.add_argument("--output", default=".env.local", help="Where to write the generated env file.")
    parser.add_argument("--app-id", default=os.getenv("GITHUB_APP_ID", ""))
    parser.add_argument("--private-key-path", default=os.getenv("GITHUB_PRIVATE_KEY_PATH", ""))
    parser.add_argument("--webhook-secret", default=os.getenv("GITHUB_WEBHOOK_SECRET", ""))
    parser.add_argument(
        "--github-api-base-url",
        default=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com"),
    )
    parser.add_argument(
        "--monitored-repositories",
        default=os.getenv("MONITORED_REPOSITORIES", ""),
        help="Comma-separated owner/repo values. Use 'all' for all installed repos.",
    )
    parser.add_argument(
        "--suspicious-threshold",
        type=int,
        default=int(os.getenv("SUSPICIOUS_SCORE_THRESHOLD", "70")),
    )
    parser.add_argument(
        "--needs-info-threshold",
        type=int,
        default=int(os.getenv("NEEDS_INFO_COMPLETENESS_THRESHOLD", "40")),
    )
    parser.add_argument(
        "--review-first-threshold",
        type=int,
        default=int(os.getenv("REVIEW_FIRST_THRESHOLD", "80")),
    )
    parser.add_argument(
        "--worth-a-look-threshold",
        type=int,
        default=int(os.getenv("WORTH_A_LOOK_THRESHOLD", "55")),
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when required values are missing.",
    )
    args = parser.parse_args()

    print("maintainerKi setup wizard")
    print("=========================")

    app_id = required_text(
        "GitHub App ID",
        args.app_id,
        non_interactive=args.non_interactive,
    )
    private_key_path = required_text(
        "Private key path",
        args.private_key_path,
        non_interactive=args.non_interactive,
    )
    webhook_secret = required_text(
        "Webhook secret",
        args.webhook_secret,
        non_interactive=args.non_interactive,
    )
    github_api_base_url = prompt_text(
        "GitHub API base URL",
        args.github_api_base_url,
        non_interactive=args.non_interactive,
    )

    client = GitHubAppClient(
        app_id=app_id,
        private_key_path=private_key_path,
        base_url=github_api_base_url,
    )

    app_payload = client.get_authenticated_app()
    app_name = str(app_payload.get("name") or app_payload.get("slug") or "unknown-app")
    installations = client.list_installations()
    repo_choices = discover_repo_choices(client, installations)

    print(f"\nConnected to GitHub App: {app_name}")
    print(f"Installations found: {len(installations)}")
    if repo_choices:
        print("Accessible repositories:")
        for index, repo_name in enumerate(repo_choices, start=1):
            print(f"  {index}. {repo_name}")
    else:
        print("No installed repositories were returned by GitHub yet.")

    monitored_repositories = resolve_monitored_repositories(
        initial_value=args.monitored_repositories,
        repo_choices=repo_choices,
        non_interactive=args.non_interactive,
    )

    suspicious_threshold = prompt_int(
        "Suspicious score threshold",
        args.suspicious_threshold,
        non_interactive=args.non_interactive,
    )
    needs_info_threshold = prompt_int(
        "Needs-info completeness threshold",
        args.needs_info_threshold,
        non_interactive=args.non_interactive,
    )
    review_first_threshold = prompt_int(
        "Review-first overall score threshold",
        args.review_first_threshold,
        non_interactive=args.non_interactive,
    )
    worth_a_look_threshold = prompt_int(
        "Worth-a-look overall score threshold",
        args.worth_a_look_threshold,
        non_interactive=args.non_interactive,
    )

    if worth_a_look_threshold > review_first_threshold:
        raise SystemExit("WORTH_A_LOOK_THRESHOLD cannot be greater than REVIEW_FIRST_THRESHOLD.")

    output_path = Path(args.output)
    output_path.write_text(
        render_env(
            WizardConfig(
                app_id=app_id,
                private_key_path=private_key_path,
                webhook_secret=webhook_secret,
                github_api_base_url=github_api_base_url,
                monitored_repositories=monitored_repositories,
                suspicious_score_threshold=suspicious_threshold,
                needs_info_completeness_threshold=needs_info_threshold,
                review_first_threshold=review_first_threshold,
                worth_a_look_threshold=worth_a_look_threshold,
            )
        )
    )

    repo_summary = ", ".join(monitored_repositories) if monitored_repositories else "all installed repos"
    print(f"\nWrote setup to {output_path}")
    print(f"Monitoring: {repo_summary}")
    print("Next step: restart the API and worker so the new settings are picked up.")


def discover_repo_choices(
    client: GitHubAppClient,
    installations: list[dict[str, object]],
) -> list[str]:
    repo_names: set[str] = set()
    for installation in installations:
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            continue
        try:
            repositories = client.list_installation_repositories(installation_id)
        except GitHubWritebackError:
            continue
        for repository in repositories:
            full_name = repository.get("full_name")
            if isinstance(full_name, str) and full_name.strip():
                repo_names.add(full_name.strip())
    return sorted(repo_names, key=str.lower)


def resolve_monitored_repositories(
    *,
    initial_value: str,
    repo_choices: list[str],
    non_interactive: bool,
) -> list[str]:
    normalized_initial = initial_value.strip()
    if normalized_initial.lower() == "all":
        return []
    if normalized_initial:
        return normalize_repo_list(normalized_initial.split(","))
    if non_interactive:
        return []

    if not repo_choices:
        manual_value = prompt_text(
            "Monitored repositories (comma-separated owner/repo, blank = all)",
            "",
            non_interactive=False,
        )
        return normalize_repo_list(manual_value.split(",")) if manual_value.strip() else []

    raw_selection = prompt_text(
        "Choose repos by number (e.g. 1,3) or leave blank for all installed repos",
        "",
        non_interactive=False,
    ).strip()
    if not raw_selection:
        return []

    indexes = []
    for item in raw_selection.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        if not cleaned.isdigit():
            raise SystemExit(f"Invalid repo selection: {cleaned!r}")
        indexes.append(int(cleaned))

    selected: list[str] = []
    for index in indexes:
        if index < 1 or index > len(repo_choices):
            raise SystemExit(f"Repo selection {index} is out of range.")
        repo_name = repo_choices[index - 1]
        if repo_name not in selected:
            selected.append(repo_name)
    return selected


def normalize_repo_list(items: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def required_text(label: str, default: str, *, non_interactive: bool) -> str:
    value = prompt_text(label, default, non_interactive=non_interactive).strip()
    if not value:
        raise SystemExit(f"{label} is required.")
    return value


def prompt_text(label: str, default: str, *, non_interactive: bool) -> str:
    if non_interactive:
        return default
    suffix = f" [{default}]" if default else ""
    entered = input(f"{label}{suffix}: ").strip()
    return entered or default


def prompt_int(label: str, default: int, *, non_interactive: bool) -> int:
    raw_value = prompt_text(label, str(default), non_interactive=non_interactive)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"{label} must be an integer.") from exc
    if value < 0 or value > 100:
        raise SystemExit(f"{label} must be between 0 and 100.")
    return value


def render_env(config: WizardConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    monitored = ",".join(config.monitored_repositories)
    return "\n".join(
        [
            f"# Generated by maintainerKi setup wizard on {timestamp}",
            "GITHUB_APP_ID=" + config.app_id,
            "GITHUB_PRIVATE_KEY_PATH=" + config.private_key_path,
            "GITHUB_WEBHOOK_SECRET=" + config.webhook_secret,
            "GITHUB_API_BASE_URL=" + config.github_api_base_url,
            "MONITORED_REPOSITORIES=" + monitored,
            "SUSPICIOUS_SCORE_THRESHOLD=" + str(config.suspicious_score_threshold),
            "NEEDS_INFO_COMPLETENESS_THRESHOLD=" + str(
                config.needs_info_completeness_threshold
            ),
            "REVIEW_FIRST_THRESHOLD=" + str(config.review_first_threshold),
            "WORTH_A_LOOK_THRESHOLD=" + str(config.worth_a_look_threshold),
            "",
        ]
    )


if __name__ == "__main__":
    main()
