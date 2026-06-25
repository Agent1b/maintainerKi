from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from server.scorer.models import ContributionInput, RawScorecard
from server.scorer.prompts import build_scoring_messages
from server.scorer.providers import (
    MlxScoringProvider,
    MockScoringProvider,
    OllamaScoringProvider,
    ScoringProviderError,
)
from server.scorer.quality import compute_overall_score, derive_labels, score_contribution


def test_build_scoring_messages_contains_expected_fields() -> None:
    contribution = ContributionInput(
        kind="pull_request",
        action="opened",
        title="Fix login redirect bug",
        body="Adds a guard around the redirect path and includes tests.",
        repository="example/repo",
        author="octocat",
        number=12,
        files_changed=3,
        author_account_age_days=450,
        author_previous_contributions=9,
    )

    messages = build_scoring_messages(contribution)

    assert len(messages) == 2
    assert "Fix login redirect bug" in messages[1]["content"]
    assert "example/repo" in messages[1]["content"]
    assert "Files changed: 3" in messages[1]["content"]


def test_compute_overall_score_penalizes_suspicion() -> None:
    scorecard = RawScorecard(
        quality=90,
        relevance=85,
        completeness=80,
        suspicion=70,
        summary="Strong signal but suspicious submission pattern.",
        suggested_labels=[],
    )

    assert compute_overall_score(scorecard) == 80


def test_derive_labels_maps_priority_buckets() -> None:
    scorecard = RawScorecard(
        quality=88,
        relevance=82,
        completeness=32,
        suspicion=74,
        summary="Needs more detail and looks risky.",
        suggested_labels=["custom:watch"],
    )

    labels = derive_labels(scorecard, overall_score=76)

    assert labels == [
        "maintainerki:suspicious",
        "maintainerki:needs-info",
        "maintainerki:worth-a-look",
        "custom:watch",
    ]


def test_derive_labels_respects_configured_thresholds(monkeypatch) -> None:
    monkeypatch.setattr("server.scorer.quality.settings.suspicious_score_threshold", 85)
    monkeypatch.setattr("server.scorer.quality.settings.needs_info_completeness_threshold", 20)
    monkeypatch.setattr("server.scorer.quality.settings.review_first_threshold", 90)
    monkeypatch.setattr("server.scorer.quality.settings.worth_a_look_threshold", 70)
    scorecard = RawScorecard(
        quality=88,
        relevance=82,
        completeness=32,
        suspicion=74,
        summary="Looks useful.",
        suggested_labels=[],
    )

    labels = derive_labels(scorecard, overall_score=76)

    assert labels == ["maintainerki:worth-a-look"]


def test_score_contribution_with_mock_provider_returns_valid_result() -> None:
    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Crash in settings page",
        body="Steps to reproduce included. Happens on macOS 15.",
        repository="example/repo",
        author="octocat",
        number=5,
    )

    result = score_contribution(contribution, provider=MockScoringProvider())

    assert 0 <= result.overall_score <= 100
    assert result.provider == "mock"
    assert result.model == "heuristic-v1"
    assert result.prompt_version == "phase2-v1"
    assert result.suggested_labels


def test_ollama_provider_parses_structured_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "qwen3.6:27b"
        assert payload["stream"] is False
        assert payload["format"]["type"] == "object"
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "quality": 83,
                            "relevance": 79,
                            "completeness": 68,
                            "suspicion": 12,
                            "summary": "Useful contribution with enough context to review.",
                            "suggested_labels": ["custom:human-review"],
                        }
                    )
                }
            },
        )

    provider = OllamaScoringProvider(
        base_url="http://localhost:11434",
        model_name="qwen3.6:27b",
        timeout_seconds=5,
        temperature=0.1,
        keep_alive="5m",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    contribution = ContributionInput(
        kind="pull_request",
        action="opened",
        title="Add retry around webhook replay fetch",
        body="Improves resilience and includes basic tests.",
        repository="example/repo",
        author="octocat",
        number=8,
    )

    scorecard = provider.score(contribution)

    assert scorecard.quality == 83
    assert scorecard.suggested_labels == ["custom:human-review"]


def test_ollama_provider_raises_on_invalid_payload() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": '{"quality": "nope"}'}})

    provider = OllamaScoringProvider(
        base_url="http://localhost:11434",
        model_name="qwen3.6:27b",
        timeout_seconds=5,
        temperature=0.1,
        keep_alive="5m",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Broken build",
        body="The workflow fails on ubuntu-latest.",
        repository="example/repo",
        author="octocat",
        number=9,
    )

    with pytest.raises(ScoringProviderError):
        provider.score(contribution)


def test_mlx_provider_parses_json_output(monkeypatch) -> None:
    def fake_run(command, check, capture_output, text, timeout):  # noqa: ANN001
        assert command[0] == "./.venv-mlx/bin/mlx_lm.generate"
        assert "--model" in command
        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 60
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "quality": 81,
                    "relevance": 76,
                    "completeness": 69,
                    "suspicion": 14,
                    "summary": "Solid contribution with enough detail for maintainer triage.",
                    "suggested_labels": ["custom:mlx"],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("server.scorer.providers.subprocess.run", fake_run)
    provider = MlxScoringProvider(
        command="./.venv-mlx/bin/mlx_lm.generate",
        model_path="/tmp/mlx-model",
        timeout_seconds=60,
        temperature=0.1,
        max_tokens=300,
        use_default_chat_template=False,
    )
    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Settings panel crash",
        body="Repro steps included in the issue.",
        repository="example/repo",
        author="octocat",
        number=77,
    )

    scorecard = provider.score(contribution)

    assert scorecard.quality == 81
    assert scorecard.suggested_labels == ["custom:mlx"]


def test_mlx_provider_extracts_embedded_json(monkeypatch) -> None:
    def fake_run(command, check, capture_output, text, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='Here is the result: {"quality":72,"relevance":75,"completeness":61,"suspicion":20,"summary":"Looks useful and reasonably clear.","suggested_labels":["custom:trim"]}',
            stderr="",
        )

    monkeypatch.setattr("server.scorer.providers.subprocess.run", fake_run)
    provider = MlxScoringProvider(
        command="./.venv-mlx/bin/mlx_lm.generate",
        model_path="/tmp/mlx-model",
        timeout_seconds=60,
        temperature=0.1,
        max_tokens=300,
        use_default_chat_template=False,
    )
    contribution = ContributionInput(
        kind="pull_request",
        action="opened",
        title="Reduce webhook retries",
        body="Adds a backoff cap and small tests.",
        repository="example/repo",
        author="octocat",
        number=78,
    )

    scorecard = provider.score(contribution)

    assert scorecard.relevance == 75


def test_mlx_provider_prefers_last_json_object(monkeypatch) -> None:
    def fake_run(command, check, capture_output, text, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='I will return {"ok": true} first and then the real answer.\n{"quality":72,"relevance":75,"completeness":61,"suspicion":20,"summary":"Looks useful and reasonably clear.","suggested_labels":["custom:last"]}',
            stderr="",
        )

    monkeypatch.setattr("server.scorer.providers.subprocess.run", fake_run)
    provider = MlxScoringProvider(
        command="./.venv-mlx/bin/mlx_lm.generate",
        model_path="/tmp/mlx-model",
        timeout_seconds=60,
        temperature=0.1,
        max_tokens=300,
        use_default_chat_template=False,
    )
    contribution = ContributionInput(
        kind="pull_request",
        action="opened",
        title="Reduce duplicate retry noise",
        body="Small follow-up patch.",
        repository="example/repo",
        author="octocat",
        number=80,
    )

    scorecard = provider.score(contribution)

    assert scorecard.suggested_labels == ["custom:last"]


def test_mlx_provider_raises_on_missing_json(monkeypatch) -> None:
    def fake_run(command, check, capture_output, text, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(command, 0, stdout="not json at all", stderr="")

    monkeypatch.setattr("server.scorer.providers.subprocess.run", fake_run)
    provider = MlxScoringProvider(
        command="./.venv-mlx/bin/mlx_lm.generate",
        model_path="/tmp/mlx-model",
        timeout_seconds=60,
        temperature=0.1,
        max_tokens=300,
        use_default_chat_template=False,
    )
    contribution = ContributionInput(
        kind="issue",
        action="opened",
        title="Docs typo",
        body="Simple docs change.",
        repository="example/repo",
        author="octocat",
        number=79,
    )

    with pytest.raises(ScoringProviderError):
        provider.score(contribution)
