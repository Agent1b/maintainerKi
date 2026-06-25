from __future__ import annotations

import hashlib
import math
import re
from threading import Lock
from typing import Protocol

from server.config import settings
from server.duplicates.models import EmbeddingResult
from server.scorer.models import ContributionInput

_WHITESPACE_RE = re.compile(r"\s+")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

_NORMALIZATION_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bphones?\b"), "mobile"),
    (re.compile(r"\biphone\b|\bandroid\b|\bcell ?phone\b"), "mobile"),
    (re.compile(r"\bdoesn['’]?t work\b|\bdoes not work\b|\bnot working\b"), "broken"),
    (re.compile(r"\bbroken\b|\bfailing\b|\bfails\b|\bfail\b|\bcrash(?:es|ed|ing)?\b"), "broken"),
    (re.compile(r"\blog ?in\b"), "login"),
]

_sentence_transformer_model = None
_sentence_transformer_lock = Lock()


class DuplicateEmbeddingError(RuntimeError):
    pass


class DuplicateEmbeddingProvider(Protocol):
    provider_name: str
    model_name: str

    def embed(self, text: str) -> list[float]: ...


class HashingEmbeddingProvider:
    provider_name = "hashing"

    def __init__(self, *, dimensions: int) -> None:
        self.dimensions = dimensions
        self.model_name = f"hashing-{dimensions}d"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        if not text:
            return vector

        tokens = _tokenize(text)
        if not tokens:
            return vector

        weighted_terms = tokens + _char_ngrams(text, min_n=3, max_n=5)
        for term in weighted_terms:
            digest = hashlib.sha256(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        return _normalize_vector(vector)


class SentenceTransformerEmbeddingProvider:
    provider_name = "sentence-transformers"

    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        model = _load_sentence_transformer(self.model_name)
        vector = model.encode(
            [text],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )[0]
        return [float(value) for value in vector.tolist()]


def build_embedding_result(contribution: ContributionInput) -> EmbeddingResult:
    provider = get_duplicate_embedding_provider()
    normalized_text = normalize_duplicate_text(build_duplicate_text(contribution))
    embedding = provider.embed(normalized_text)
    return EmbeddingResult(
        provider=provider.provider_name,
        model=provider.model_name,
        normalized_text=normalized_text,
        embedding=embedding,
    )


def build_duplicate_text(contribution: ContributionInput) -> str:
    parts = [contribution.title.strip()]
    if contribution.body.strip():
        parts.append(contribution.body.strip())
    return "\n\n".join(part for part in parts if part)


def normalize_duplicate_text(text: str) -> str:
    stripped = _CODE_FENCE_RE.sub(" ", text)
    stripped = stripped.replace("`", " ")
    stripped = _MARKDOWN_LINK_RE.sub(r"\1 \2", stripped)
    stripped = stripped.lower()
    for pattern, replacement in _NORMALIZATION_RULES:
        stripped = pattern.sub(replacement, stripped)
    stripped = _WHITESPACE_RE.sub(" ", stripped).strip()
    return stripped


def get_duplicate_embedding_provider() -> DuplicateEmbeddingProvider:
    provider_name = settings.duplicate_embedding_provider.lower().strip()
    if provider_name in {"hash", "hashing"}:
        return HashingEmbeddingProvider(dimensions=settings.duplicate_hash_dimensions)
    if provider_name in {"sentence-transformers", "sentence_transformers", "sbert"}:
        return SentenceTransformerEmbeddingProvider(model_name=settings.duplicate_embedding_model)
    raise DuplicateEmbeddingError(
        f"Unsupported duplicate embedding provider '{settings.duplicate_embedding_provider}'."
    )


def _load_sentence_transformer(model_name: str):
    global _sentence_transformer_model

    if _sentence_transformer_model is not None:
        return _sentence_transformer_model

    with _sentence_transformer_lock:
        if _sentence_transformer_model is not None:
            return _sentence_transformer_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise DuplicateEmbeddingError(
                "sentence-transformers is not installed. Install it or switch DUPLICATE_EMBEDDING_PROVIDER=hashing."
            ) from exc

        _sentence_transformer_model = SentenceTransformer(settings.duplicate_embedding_model)
        return _sentence_transformer_model


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text)


def _char_ngrams(text: str, *, min_n: int, max_n: int) -> list[str]:
    compact = text.replace(" ", "_")
    grams: list[str] = []
    for n in range(min_n, max_n + 1):
        for index in range(max(0, len(compact) - n + 1)):
            grams.append(compact[index : index + n])
    return grams


def _normalize_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
