from __future__ import annotations

from server.config import settings
from server.duplicates.embedder import build_embedding_result
from server.duplicates.models import DuplicateCandidate, DuplicateDetectionResult, EmbeddingResult
from server.repository import list_repository_duplicate_candidates
from server.scorer.models import ContributionInput


def detect_duplicates(contribution: ContributionInput) -> tuple[EmbeddingResult, DuplicateDetectionResult]:
    embedding_result = build_embedding_result(contribution)
    existing_records = list_repository_duplicate_candidates(
        contribution.repository,
        exclude_number=contribution.number,
    )

    candidates: list[DuplicateCandidate] = []
    for record in existing_records:
        similarity = cosine_similarity(embedding_result.embedding, record["embedding"])
        candidates.append(
            DuplicateCandidate(
                contribution_id=record["id"],
                repository=record["repository"],
                kind=record["kind"],
                number=record["number"],
                title=record["title"],
                html_url=record.get("html_url"),
                similarity=round(similarity, 4),
            )
        )

    candidates.sort(key=lambda item: item.similarity, reverse=True)
    top_candidates = candidates[: settings.duplicate_max_candidates]
    top_similarity = top_candidates[0].similarity if top_candidates else None
    threshold = settings.duplicate_similarity_threshold
    possible_duplicate = bool(top_similarity is not None and top_similarity >= threshold)

    return embedding_result, DuplicateDetectionResult(
        provider=embedding_result.provider,
        model=embedding_result.model,
        threshold=threshold,
        possible_duplicate=possible_duplicate,
        top_similarity=top_similarity,
        candidates=top_candidates,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    similarity = sum(left_value * right_value for left_value, right_value in zip(left, right))
    if similarity < 0:
        return 0.0
    if similarity > 1:
        return 1.0
    return float(similarity)
