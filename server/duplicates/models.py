from __future__ import annotations

from pydantic import BaseModel, Field


class EmbeddingResult(BaseModel):
    provider: str
    model: str
    normalized_text: str
    embedding: list[float] = Field(default_factory=list)


class DuplicateCandidate(BaseModel):
    contribution_id: int
    repository: str
    kind: str
    number: int
    title: str
    html_url: str | None = None
    similarity: float = Field(ge=0.0, le=1.0)


class DuplicateDetectionResult(BaseModel):
    provider: str
    model: str
    threshold: float = Field(ge=0.0, le=1.0)
    possible_duplicate: bool
    top_similarity: float | None = None
    candidates: list[DuplicateCandidate] = Field(default_factory=list)
