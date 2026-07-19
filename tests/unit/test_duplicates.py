from __future__ import annotations

import pytest

from server.duplicates.detector import cosine_similarity, detect_duplicates
from server.duplicates.embedder import (
    build_duplicate_text,
    build_embedding_result,
    normalize_duplicate_text,
)
from server.scorer.models import ContributionInput


def test_normalize_duplicate_text_collapses_common_issue_variants() -> None:
    text = "Login button doesn't work on phones\n\n```js\nthrow new Error()\n```"
    normalized = normalize_duplicate_text(text)

    assert "login" in normalized
    assert "broken" in normalized
    assert "mobile" in normalized
    assert "throw new error" not in normalized


def test_build_duplicate_text_combines_title_and_body() -> None:
    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Login button broken",
        body="Happens on phones only.",
        repository="example/repo",
        author="octocat",
        number=10,
    )

    combined = build_duplicate_text(contribution)

    assert "Login button broken" in combined
    assert "Happens on phones only." in combined


def test_cosine_similarity_for_identical_vectors_is_one() -> None:
    assert cosine_similarity([0.5, 0.5], [0.5, 0.5]) == pytest.approx(1.0)


def test_cosine_similarity_for_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_for_zero_vector_is_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_for_mismatched_lengths_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_similarity_normalizes_unnormalized_vectors() -> None:
    assert cosine_similarity([2.0, 0.0], [4.0, 0.0]) == 1.0


def test_detect_duplicates_flags_high_similarity(monkeypatch) -> None:
    monkeypatch.setattr("server.duplicates.embedder.settings.duplicate_embedding_provider", "hashing")
    monkeypatch.setattr("server.duplicates.detector.settings.duplicate_max_candidates", 3)
    monkeypatch.setattr("server.duplicates.detector.settings.duplicate_similarity_threshold", 0.8)
    monkeypatch.setattr("server.duplicates.embedder.settings.duplicate_hash_dimensions", 384)
    prior_contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Login button doesn't work on mobile",
        body="Users cannot sign in from a phone browser.",
        repository="example/repo",
        author="octocat",
        number=1,
    )
    prior_embedding = build_embedding_result(prior_contribution).embedding
    monkeypatch.setattr(
        "server.duplicates.detector.list_repository_duplicate_candidates",
        lambda repository, exclude_number=None: [
            {
                "id": 1,
                "repository": repository,
                "kind": "issue",
                "number": 1,
                "title": "Login button doesn't work on mobile",
                "html_url": "https://github.com/example/repo/issues/1",
                "embedding": prior_embedding,
            }
        ],
    )

    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="The login button is broken on phones",
        body="Users cannot sign in from their mobile browser.",
        repository="example/repo",
        author="octocat",
        number=2,
    )

    embedding_result, duplicate_result = detect_duplicates(contribution)

    assert embedding_result.embedding
    assert duplicate_result.possible_duplicate is True
    assert duplicate_result.candidates
    assert duplicate_result.candidates[0].number == 1
