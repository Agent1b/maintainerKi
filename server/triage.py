from __future__ import annotations

from dataclasses import dataclass

from server.config import settings


@dataclass(frozen=True, slots=True)
class TriageThresholds:
    suspicious_score: int
    needs_info_completeness: int
    review_first: int
    worth_a_look: int


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def get_triage_thresholds() -> TriageThresholds:
    review_first = _clamp_score(settings.review_first_threshold)
    worth_a_look = min(_clamp_score(settings.worth_a_look_threshold), review_first)
    return TriageThresholds(
        suspicious_score=_clamp_score(settings.suspicious_score_threshold),
        needs_info_completeness=_clamp_score(settings.needs_info_completeness_threshold),
        review_first=review_first,
        worth_a_look=worth_a_look,
    )


def triage_bucket_from_values(
    *,
    status: str,
    possible_duplicate: bool,
    suspicion_score: int | None,
    overall_score: int | None,
) -> str:
    thresholds = get_triage_thresholds()
    if status == "pending":
        return "pending"
    if possible_duplicate:
        return "duplicate"
    if (suspicion_score or 0) >= thresholds.suspicious_score:
        return "suspicious"
    if (overall_score or 0) >= thresholds.review_first:
        return "review-first"
    if (overall_score or 0) >= thresholds.worth_a_look:
        return "worth-a-look"
    return "low-priority"


def score_distribution_bucket(overall_score: int | None) -> str | None:
    if overall_score is None:
        return None
    thresholds = get_triage_thresholds()
    if overall_score >= thresholds.review_first:
        return "high"
    if overall_score >= thresholds.worth_a_look:
        return "medium"
    return "low"
