import json

import pytest

from skillpipeline.extract import EXTRACT_TOPICS_TOOL
from skillpipeline.llm import (
    INPUT_COST_PER_MTOK,
    MODEL,
    OUTPUT_COST_PER_MTOK,
    FakeLLMClient,
    GroqLLMClient,
    LLMResponse,
    ToolCall,
    _to_groq_tool,
    compute_cost_usd,
)


class TestCostComputation:
    def test_zero_cost(self):
        assert compute_cost_usd(0, 0) == 0.0

    def test_groq_free_tier_rates_are_zero(self):
        # Groq free tier: both rates are 0.00, so any usage costs $0.
        assert INPUT_COST_PER_MTOK == 0.0
        assert OUTPUT_COST_PER_MTOK == 0.0
        assert compute_cost_usd(1_000_000, 0) == 0.0
        assert compute_cost_usd(0, 1_000_000) == 0.0

    def test_combined_cost_matches_rates(self):
        cost = compute_cost_usd(100_000, 50_000)
        expected = (100_000 / 1_000_000) * INPUT_COST_PER_MTOK + (
            50_000 / 1_000_000
        ) * OUTPUT_COST_PER_MTOK
        assert abs(cost - expected) < 0.0001


class TestFakeLLMClient:
    @pytest.fixture
    def valid_extract_response(self):
        with open("tests/fixtures/extract_response_valid.json") as f:
            return json.load(f)

    @pytest.fixture
    def relate_response(self):
        with open("tests/fixtures/relate_response_valid.json") as f:
            return json.load(f)

    @pytest.mark.asyncio
    async def test_basic_call(self, valid_extract_response):
        client = FakeLLMClient([valid_extract_response])
        response = await client.call(
            tool={"name": "test"},
            user_prompt="Test prompt",
        )

        assert response.input_tokens == 150
        assert response.output_tokens == 80
        assert response.model == "fake-model"

    @pytest.mark.asyncio
    async def test_cycled_responses(self, valid_extract_response, relate_response):
        client = FakeLLMClient([valid_extract_response, relate_response])

        # First call gets extract response
        r1 = await client.call(tool={"name": "test"}, user_prompt="A")
        assert r1.input_tokens == 150

        # Second call gets relate response
        r2 = await client.call(tool={"name": "test"}, user_prompt="B")
        assert r2.input_tokens == 200

    @pytest.mark.asyncio
    async def test_empty_responses(self):
        client = FakeLLMClient([])
        response = await client.call(tool={"name": "test"}, user_prompt="Test")

        assert response.input_tokens == 0
        assert response.output_tokens == 0

    @pytest.mark.asyncio
    async def test_text_only_response(self):
        client = FakeLLMClient([{"text_only": True, "text": "Here is some text"}])
        response = await client.call(tool={"name": "test"}, user_prompt="Test")

        assert len(response.content) == 1
        assert response.content[0]["type"] == "text"
        assert response.content[0]["text"] == "Here is some text"

    def test_get_tool_calls(self, valid_extract_response):
        client = FakeLLMClient([valid_extract_response])

        # Simulate getting the response first
        response = client._responses[0]
        response_mock = type("obj", (object,), {
            "content": [{
                "type": "tool_use",
                "id": "toolu_123",
                "name": "record_topics",
                "input": response["tool_use"]["input"],
            }]
        })

        calls = client.get_tool_calls(response_mock)
        assert len(calls) == 1
        assert calls[0].name == "record_topics"
        assert "topics" in calls[0].input

    @pytest.mark.asyncio
    async def test_set_responses_mid_stream(self):
        client = FakeLLMClient([{"text_only": True, "text": "A"}])
        await client.call(tool={}, user_prompt="")

        client.set_responses([{"text_only": True, "text": "B"}])
        r2 = await client.call(tool={}, user_prompt="")

        assert r2.content[0]["text"] == "B"


class TestGroqLLMClient:
    def test_init_with_api_key(self):
        # Should not raise with provided key
        client = GroqLLMClient(api_key="test-key")
        assert client.model == MODEL

    def test_init_defaults(self, monkeypatch):
        # Should read from env when no key provided
        monkeypatch.setenv("GROQ_API_KEY", "env-key")
        client = GroqLLMClient()
        assert client.model == MODEL

    def test_custom_config(self):
        client = GroqLLMClient(
            api_key="test-key",
            model="llama-3.1-8b-instant",
            temperature=0.5,
            max_tokens=2048,
        )
        assert client.model == "llama-3.1-8b-instant"
        assert client.temperature == 0.5
        assert client.max_tokens == 2048

    def test_tool_translation_to_groq_format(self):
        # Anthropic-style input_schema becomes Groq's function "parameters".
        groq_tool = _to_groq_tool(EXTRACT_TOPICS_TOOL)
        assert groq_tool["type"] == "function"
        fn = groq_tool["function"]
        assert fn["name"] == "record_topics"
        assert fn["description"] == EXTRACT_TOPICS_TOOL["description"]
        assert fn["parameters"] is EXTRACT_TOPICS_TOOL["input_schema"]

    def test_get_tool_calls_maps_tool_use_blocks(self):
        client = GroqLLMClient(api_key="test-key")
        response = LLMResponse(
            content=[
                {"type": "tool_use", "id": "call_1", "name": "record_topics", "input": {"topics": []}},
                {"type": "text", "text": "ignored"},
            ],
            input_tokens=10,
            output_tokens=5,
            model=MODEL,
        )
        calls = client.get_tool_calls(response)
        assert len(calls) == 1
        assert calls[0].name == "record_topics"
        assert calls[0].input == {"topics": []}
        assert calls[0].id == "call_1"


class TestToolCall:
    def test_tool_call_creation(self):
        tc = ToolCall(name="test_tool", input={"key": "value"}, id="call_123")
        assert tc.name == "test_tool"
        assert tc.input == {"key": "value"}
        assert tc.id == "call_123"

    def test_tool_call_optional_id(self):
        tc = ToolCall(name="test_tool", input={"key": "value"})
        assert tc.id is None
