"""Provider-boundary test: parse a REAL Groq response shape.

The real-graph integration test (test_pipeline_real_graph) drives the graph with
FakeLLMClient, so it never exercises how GroqLLMClient parses an actual Groq
response. That's the same class of bug we got burned by — a boundary that's green
in tests but never ran for real — one layer down. These tests build a genuine
`groq.types.chat.ChatCompletion` from the SDK's own types and run the parsing in
GroqLLMClient.call against it (the network call is mocked). If Groq renames a
field or changes `function.arguments` from a JSON string, these fail at construction
or assertion instead of silently breaking the live path.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock

import pytest
from groq.types import CompletionUsage
from groq.types.chat.chat_completion import ChatCompletion, Choice
from groq.types.chat.chat_completion_message import ChatCompletionMessage
from groq.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from skillpipeline.extract import EXTRACT_TOPICS_TOOL
from skillpipeline.llm import GroqLLMClient


def _groq_completion(
    *,
    tool_name: Optional[str] = None,
    arguments: Optional[str] = None,
    content: Optional[str] = None,
    prompt_tokens: int = 12,
    completion_tokens: int = 7,
) -> ChatCompletion:
    """Build a real Groq ChatCompletion via the SDK types (mirrors live output)."""
    tool_calls = None
    if tool_name is not None:
        tool_calls = [
            ChatCompletionMessageToolCall(
                id="call_abc123",
                type="function",
                function=Function(name=tool_name, arguments=arguments or "{}"),
            )
        ]
    message = ChatCompletionMessage(role="assistant", content=content, tool_calls=tool_calls)
    return ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=0,
        model="llama-3.3-70b-versatile",
        choices=[Choice(finish_reason="stop", index=0, message=message)],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _client_returning(completion: ChatCompletion) -> GroqLLMClient:
    client = GroqLLMClient(api_key="test-key")
    client._client.chat.completions.create = AsyncMock(return_value=completion)
    return client


@pytest.mark.asyncio
async def test_parses_tool_call_into_tool_use_block():
    """function.arguments (a JSON string) is parsed into the tool_use input dict."""
    completion = _groq_completion(
        tool_name="record_topics",
        arguments='{"topics": [{"id": "rest", "name": "REST"}]}',
    )
    client = _client_returning(completion)

    resp = await client.call(tool=EXTRACT_TOPICS_TOOL, user_prompt="x", system_prompt="s")

    # Token usage maps from the real usage fields.
    assert resp.input_tokens == 12
    assert resp.output_tokens == 7
    assert resp.model == "llama-3.3-70b-versatile"

    calls = client.get_tool_calls(resp)
    assert len(calls) == 1
    assert calls[0].name == "record_topics"
    assert calls[0].id == "call_abc123"
    # arguments arrived as a JSON STRING and were parsed to a dict.
    assert calls[0].input == {"topics": [{"id": "rest", "name": "REST"}]}


@pytest.mark.asyncio
async def test_text_only_response_yields_no_tool_calls():
    """No tool_calls (model replied in prose) -> a text block, zero tool calls.

    This is the path that triggers MISSING_TOOL_USE in the extract validator.
    """
    completion = _groq_completion(tool_name=None, content="Here are some topics in prose.")
    client = _client_returning(completion)

    resp = await client.call(tool=EXTRACT_TOPICS_TOOL, user_prompt="x")

    assert client.get_tool_calls(resp) == []
    assert resp.content and resp.content[0]["type"] == "text"


@pytest.mark.asyncio
async def test_malformed_arguments_degrade_to_empty_input():
    """Malformed JSON in function.arguments -> empty input (retryable downstream)."""
    completion = _groq_completion(tool_name="record_topics", arguments="{not valid json")
    client = _client_returning(completion)

    resp = await client.call(tool=EXTRACT_TOPICS_TOOL, user_prompt="x")

    calls = client.get_tool_calls(resp)
    assert len(calls) == 1
    assert calls[0].input == {}
