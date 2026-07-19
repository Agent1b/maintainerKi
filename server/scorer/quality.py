from __future__ import annotations

from server.config import settings
from server.triage import get_triage_thresholds
from server.scorer.models import ContributionInput, RawScorecard, ScoreResult
from server.scorer.prompts import PROMPT_VERSION
from server.scorer.providers import ScoringProvider, get_scoring_provider


def compute_overall_score(scorecard: RawScorecard) -> int:
    weighted_score = (
        (scorecard.quality * 0.35)
        + (scorecard.relevance * 0.35)
        + (scorecard.completeness * 0.20)
        + ((100 - scorecard.suspicion) * 0.10)
    )
    return max(0, min(100, int(round(weighted_score))))


def derive_labels(scorecard: RawScorecard, overall_score: int) -> list[str]:
    labels: list[str] = []

    thresholds = get_triage_thresholds()
    suspicious_threshold = thresholds.suspicious_score
    needs_info_threshold = thresholds.needs_info_completeness
    review_first_threshold = thresholds.review_first
    worth_a_look_threshold = thresholds.worth_a_look

    if scorecard.suspicion >= suspicious_threshold:
        labels.append("maintainerki:suspicious")
    if scorecard.completeness < needs_info_threshold:
        labels.append("maintainerki:needs-info")
    if overall_score >= review_first_threshold:
        labels.append("maintainerki:review-first")
    elif overall_score >= worth_a_look_threshold:
        labels.append("maintainerki:worth-a-look")
    else:
        labels.append("maintainerki:low-priority")

    for label in scorecard.suggested_labels:
        normalized = label.strip()
        if normalized and normalized not in labels:
            labels.append(normalized)
    return labels


def apply_velocity_suspicion_floor(
    scorecard: RawScorecard,
    contribution: ContributionInput,
) -> RawScorecard:
    """Raise the suspicion score to a deterministic floor for flooding authors.

    This runs after the LLM scores the contribution so a flood of low-effort
    submissions is caught even if the provider is fooled by individually
    plausible-looking content.
    """
    if (
        contribution.author_recent_contributions is not None
        and contribution.author_recent_contributions >= settings.velocity_suspicion_count_threshold
    ):
        floored_suspicion = max(scorecard.suspicion, settings.velocity_suspicion_floor)
        if floored_suspicion != scorecard.suspicion:
            return scorecard.model_copy(update={"suspicion": floored_suspicion})
    return scorecard


def score_contribution(
    contribution: ContributionInput,
    *,
    provider: ScoringProvider | None = None,
) -> ScoreResult:
    resolved_provider = provider or get_scoring_provider()
    scorecard = resolved_provider.score(contribution)
    scorecard = apply_velocity_suspicion_floor(scorecard, contribution)
    overall_score = compute_overall_score(scorecard)

    return ScoreResult(
        quality=scorecard.quality,
        relevance=scorecard.relevance,
        completeness=scorecard.completeness,
        suspicion=scorecard.suspicion,
        overall_score=overall_score,
        summary=scorecard.summary,
        suggested_labels=derive_labels(scorecard, overall_score),
        provider=resolved_provider.provider_name,
        model=resolved_provider.model_name,
        prompt_version=PROMPT_VERSION,
    )
