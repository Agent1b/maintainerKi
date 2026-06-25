from __future__ import annotations

from server.scorer.models import ContributionInput

PROMPT_VERSION = "phase2-v1"


def build_scoring_messages(contribution: ContributionInput) -> list[dict[str, str]]:
    body = contribution.body.strip() or "(no description provided)"
    files_changed = (
        str(contribution.files_changed)
        if contribution.files_changed is not None
        else "unknown"
    )
    account_age_days = (
        str(contribution.author_account_age_days)
        if contribution.author_account_age_days is not None
        else "unknown"
    )
    previous_contributions = (
        str(contribution.author_previous_contributions)
        if contribution.author_previous_contributions is not None
        else "unknown"
    )

    system = (
        "You are maintainerKi, an open source triage scoring assistant. "
        "Score GitHub issues and pull requests for maintainers. "
        "Be conservative, practical, and consistent. "
        "Return scores from 0 to 100 where suspicion means 0 is not suspicious and 100 is highly suspicious. "
        "Keep the summary to one sentence."
    )
    user = f"""
Analyze this GitHub contribution and return structured scoring.

Kind: {contribution.kind}
Action: {contribution.action}
Repository: {contribution.repository}
Number: {contribution.number}
Author: {contribution.author or "unknown"}
Author account age (days): {account_age_days}
Previous contributions: {previous_contributions}
Files changed: {files_changed}
Title: {contribution.title}
Body:
{body}

Scoring rules:
- quality: craftsmanship and signal of the contribution itself
- relevance: fit for the repository and likely usefulness
- completeness: clarity of title/body and enough detail to triage
- suspicion: signs of spam, slop, or low-trust behavior

Return exactly one valid JSON object with this shape:
{{
  "quality": 0,
  "relevance": 0,
  "completeness": 0,
  "suspicion": 0,
  "summary": "one sentence",
  "suggested_labels": ["zero or more labels"]
}}

Rules for output:
- Use integers from 0 to 100 for all scores.
- Always include all six keys.
- summary must be one sentence.
- suggested_labels must always be a JSON array, even when empty.
- Do not include markdown fences.
- Do not include explanations before or after the JSON.
""".strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
