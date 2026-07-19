from __future__ import annotations

import json
import subprocess
from typing import Protocol

import httpx
from pydantic import ValidationError

from server.config import settings
from server.scorer.models import ContributionInput, RawScorecard
from server.scorer.prompts import build_scoring_messages


class ScoringProviderError(RuntimeError):
    pass


class ScoringProvider(Protocol):
    provider_name: str
    model_name: str

    def score(self, contribution: ContributionInput) -> RawScorecard: ...


class MockScoringProvider:
    provider_name = "mock"
    model_name = "heuristic-v1"

    def score(self, contribution: ContributionInput) -> RawScorecard:
        body_len = len(contribution.body.strip())
        title_len = len(contribution.title.strip())
        quality = 55 + min(20, title_len // 4)
        relevance = 70
        completeness = 25 if body_len == 0 else min(90, 35 + body_len // 8)
        suspicion = 15

        if contribution.kind == "pull_request":
            quality += 5
            relevance += 5
        if body_len == 0:
            suspicion += 10
        if title_len < 8:
            suspicion += 15
        if "ai" in contribution.body.lower() and "generated" in contribution.body.lower():
            suspicion += 20

        return RawScorecard(
            quality=max(0, min(100, quality)),
            relevance=max(0, min(100, relevance)),
            completeness=max(0, min(100, completeness)),
            suspicion=max(0, min(100, suspicion)),
            summary="Mock scorer result for local development.",
            suggested_labels=[],
        )


class OllamaScoringProvider:
    provider_name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        temperature: float,
        keep_alive: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.keep_alive = keep_alive
        self._http_client = http_client

    def score(self, contribution: ContributionInput) -> RawScorecard:
        payload = {
            "model": self.model_name,
            "messages": build_scoring_messages(contribution),
            "stream": False,
            "format": RawScorecard.model_json_schema(),
            "options": {
                "temperature": self.temperature,
            },
            "keep_alive": self.keep_alive,
        }

        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                    )
            response.raise_for_status()
            response_payload = response.json()
            content = (response_payload.get("message") or {}).get("content", "")
            if not content:
                raise ScoringProviderError("Ollama returned an empty message content.")
            return RawScorecard.model_validate_json(content)
        except httpx.HTTPError as exc:
            raise ScoringProviderError(f"Ollama request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ScoringProviderError("Ollama returned invalid JSON.") from exc
        except ValueError as exc:
            raise ScoringProviderError(f"Could not validate Ollama scorecard: {exc}") from exc


class MlxScoringProvider:
    provider_name = "mlx"

    def __init__(
        self,
        *,
        command: str,
        model_path: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
        use_default_chat_template: bool,
    ) -> None:
        self.command = command
        self.model_name = model_path
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.use_default_chat_template = use_default_chat_template

    def score(self, contribution: ContributionInput) -> RawScorecard:
        if not self.model_name:
            raise ScoringProviderError("MLX_MODEL_PATH is not configured.")

        messages = build_scoring_messages(contribution)
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        command = [
            self.command,
            "--model",
            self.model_name,
            "--system-prompt",
            system_prompt + " Never reveal analysis or chain-of-thought. Output JSON only.",
            "--prompt",
            user_prompt + "\nStart immediately after the opening brace.",
            "--prefill-response",
            "{",
            "--max-tokens",
            str(self.max_tokens),
            "--temp",
            str(self.temperature),
            "--verbose",
            "False",
        ]

        if self.use_default_chat_template:
            command.append("--use-default-chat-template")

        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ScoringProviderError(
                f"MLX command not found: {self.command}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ScoringProviderError(
                f"MLX scoring timed out after {self.timeout_seconds} seconds."
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise ScoringProviderError(
                f"MLX scoring command failed: {stderr or exc}"
            ) from exc

        output = (completed.stdout or "").strip()
        if not output:
            raise ScoringProviderError("MLX scoring returned empty output.")

        if output.startswith('"'):
            output = "{" + output

        json_text = _extract_json_object(output)
        try:
            return RawScorecard.model_validate_json(json_text)
        except ValidationError as exc:
            raise ScoringProviderError(f"Could not validate MLX scorecard: {exc}") from exc
        except ValueError as exc:
            raise ScoringProviderError(f"MLX returned invalid JSON: {exc}") from exc


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    decoder = json.JSONDecoder()
    spans: list[tuple[int, int]] = []
    candidates: list[str] = []
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            _, end_index = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        end = index + end_index
        # Skip candidates nested inside an already-accepted candidate (e.g. a
        # JSON-looking object embedded as a field's value inside the real,
        # outer scorecard object) so they cannot outrank the outer object
        # just because they were discovered later while scanning.
        if any(start <= index and end <= prior_end for start, prior_end in spans):
            continue
        spans.append((index, end))
        candidates.append(stripped[index:end])

    if not candidates:
        raise ScoringProviderError("Model output did not contain a JSON object.")
    return candidates[-1]


def get_scoring_provider() -> ScoringProvider:
    provider = settings.scorer_provider.lower().strip()
    if provider == "mock":
        return MockScoringProvider()
    if provider == "ollama":
        return OllamaScoringProvider(
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_model,
            timeout_seconds=settings.scorer_timeout_seconds,
            temperature=settings.scorer_temperature,
            keep_alive=settings.ollama_keep_alive,
        )
    if provider == "mlx":
        return MlxScoringProvider(
            command=settings.mlx_command,
            model_path=settings.mlx_model_path,
            timeout_seconds=settings.scorer_timeout_seconds,
            temperature=settings.scorer_temperature,
            max_tokens=settings.mlx_max_tokens,
            use_default_chat_template=settings.mlx_use_default_chat_template,
        )
    raise ScoringProviderError(
        f"Unsupported scorer provider '{settings.scorer_provider}'. "
        "Use 'mock', 'ollama', or 'mlx'."
    )
