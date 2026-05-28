"""Tests for the Groq LLM client glue (provider deviation from PLAN.md 3.1/14).

Covers the deterministic, no-network pieces: the Anthropic->Groq tool
translation, tool_use block extraction, and make_default_client provider
selection. The live API path is exercised by the Step 21 runs.
"""

from __future__ import annotations

import pytest

from skillpipeline.extract import EXTRACT_TOPICS_TOOL
from skillpipeline.llm import (
    AnthropicLLMClient,
    GroqLLMClient,
    LLMResponse,
    _anthropic_tool_to_groq,
    make_default_client,
)


def test_tool_translation_shape() -> None:
    groq_tool = _anthropic_tool_to_groq(EXTRACT_TOPICS_TOOL)
    assert groq_tool["type"] == "function"
    fn = groq_tool["function"]
    assert fn["name"] == "record_topics"
    assert fn["description"] == EXTRACT_TOPICS_TOOL["description"]
    # The Anthropic input_schema becomes the OpenAI/Groq parameters verbatim.
    assert fn["parameters"] is EXTRACT_TOPICS_TOOL["input_schema"]


def test_get_tool_calls_maps_tool_use_blocks() -> None:
    client = GroqLLMClient(api_key="gsk_test")
    response = LLMResponse(
        content=[
            {"type": "tool_use", "id": "call_1", "name": "record_topics", "input": {"topics": []}},
            {"type": "text", "text": "ignored"},
        ],
        input_tokens=10,
        output_tokens=5,
        model="llama-3.3-70b-versatile",
    )
    calls = client.get_tool_calls(response)
    assert len(calls) == 1
    assert calls[0].name == "record_topics"
    assert calls[0].input == {"topics": []}
    assert calls[0].id == "call_1"


def test_groq_response_uses_zero_cost_rates() -> None:
    """Groq free-tier cost is reported as 0.0, not Anthropic's rates."""
    response = LLMResponse(
        content=[],
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        model="llama-3.3-70b-versatile",
        estimated_cost_usd=0.0,
    )
    assert response.estimated_cost_usd == 0.0


def test_default_client_explicit_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    monkeypatch.setenv("SKILLPIPELINE_PROVIDER", "groq")
    assert isinstance(make_default_client(), GroqLLMClient)

    monkeypatch.setenv("SKILLPIPELINE_PROVIDER", "anthropic")
    assert isinstance(make_default_client(), AnthropicLLMClient)


def test_default_client_autodetects_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only GROQ_API_KEY set, auto-detection picks Groq."""
    monkeypatch.delenv("SKILLPIPELINE_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert isinstance(make_default_client(), GroqLLMClient)


def test_default_client_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILLPIPELINE_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(make_default_client(), AnthropicLLMClient)
