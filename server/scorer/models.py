from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContributionInput(BaseModel):
    kind: str
    action: str
    title: str
    body: str = ""
    repository: str
    author: str | None = None
    number: int
    html_url: str | None = None
    files_changed: int | None = None
    author_account_age_days: int | None = None
    author_previous_contributions: int | None = None

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "ContributionInput":
        return cls(
            kind=event["kind"],
            action=event["action"],
            title=event["title"] or "",
            body=event.get("body") or "",
            repository=event["repository"] or "unknown/unknown",
            author=event.get("author"),
            number=event["number"],
            html_url=event.get("html_url"),
        )


class RawScorecard(BaseModel):
    quality: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    suspicion: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=400)
    suggested_labels: list[str] = Field(default_factory=list)

    @field_validator("quality", "relevance", "completeness", "suspicion", mode="before")
    @classmethod
    def normalize_score(cls, value: Any) -> int:
        numeric = int(round(float(value)))
        return max(0, min(100, numeric))

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("summary must not be empty")
        return cleaned

    @field_validator("suggested_labels", mode="before")
    @classmethod
    def normalize_labels(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item).strip() for item in value if str(item).strip()]


class ScoreResult(BaseModel):
    quality: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    suspicion: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=400)
    suggested_labels: list[str] = Field(default_factory=list)
    provider: str
    model: str
    prompt_version: str

