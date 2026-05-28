"""LLM client wrapper with tool-use support and transport-level retries.

Provider: Groq (OpenAI-compatible function-calling). Migrated from Anthropic by
explicit human approval; the `LLMClient` Protocol kept the change contained to
this module. The stages still define tools in the `name`/`description`/
`input_schema` shape; `_to_groq_tool` translates that into Groq's function form.
"""

import json
import os
import random
import time
from typing import Any, NamedTuple, Optional, Protocol, cast

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    RateLimitError,
)

# LLM configuration constants (Section 5.0)
MODEL = "llama-3.3-70b-versatile"
TEMPERATURE = 0.0
MAX_TOKENS = 4096

# Cost rates (USD per million tokens). Groq's free tier is $0; set to the paid
# on-demand rates here if running on a billed tier.
INPUT_COST_PER_MTOK = 0.00
OUTPUT_COST_PER_MTOK = 0.00


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost in USD for a given token usage."""
    return (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK + (
        output_tokens / 1_000_000
    ) * OUTPUT_COST_PER_MTOK


class TokenUsage(NamedTuple):
    """Accumulated token usage and cost across one or more LLM calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":  # type: ignore[override]
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


class LLMResponse:
    """Response from an LLM call."""

    def __init__(
        self,
        content: list[dict[str, Any]],
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> None:
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.estimated_cost_usd = compute_cost_usd(input_tokens, output_tokens)


class ToolCall:
    """A single tool use block from an LLM response."""

    def __init__(self, name: str, input: dict[str, Any], id: Optional[str] = None) -> None:
        self.name = name
        self.input = input
        self.id = id


class LLMClient(Protocol):
    """Protocol for LLM clients — enables swapping implementations for tests."""

    async def call(
        self,
        tool: dict[str, Any],
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Call the LLM with a tool-use prompt and return the response.

        Args:
            tool: Tool definition with name, description, input_schema.
            user_prompt: The user prompt content.
            system_prompt: Optional system prompt.

        Returns:
            LLMResponse with content blocks and token usage.

        Raises:
            TransportError: If the API call fails after retries.
        """
        ...

    def get_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        """Extract tool_use blocks from an LLM response."""
        ...


class TransportError(Exception):
    """Raised when the LLM API fails after all transport retries."""

    def __init__(self, message: str, original_error: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.original_error = original_error


def _to_groq_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Translate a tool dict (name/description/input_schema) into Groq function form."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


class GroqLLMClient:
    """Concrete Groq LLM client with function-calling and transport retries.

    Groq is OpenAI-compatible. This client forces a single function call and maps
    the result back into the `{"type": "tool_use", ...}` content blocks the
    extract/relate stages expect, so those stages need no changes.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = MODEL,
        temperature: float = TEMPERATURE,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = AsyncGroq(api_key=api_key or os.environ.get("GROQ_API_KEY"))

    async def call(
        self,
        tool: dict[str, Any],
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Call the Groq API with forced function-calling, with transport retries.

        Transport retries (Section 6.2):
        - Max 5 attempts
        - Exponential backoff with jitter
        - Base delay 1s
        - Retried only on APIStatusError (status >= 500) or RateLimitError
        """
        groq_tool = _to_groq_tool(tool)
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        last_error: Optional[Exception] = None

        for attempt in range(5):
            try:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    messages=cast(Any, messages),
                    tools=cast(Any, [groq_tool]),
                    tool_choice=cast(
                        Any,
                        {"type": "function", "function": {"name": tool["name"]}},
                    ),
                )

                message = response.choices[0].message
                content_blocks: list[dict[str, Any]] = []
                for tc in message.tool_calls or []:
                    try:
                        parsed_input = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        # Malformed JSON — surface as empty tool_use; downstream
                        # validation treats it as a retryable error.
                        parsed_input = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": parsed_input,
                    })
                # No tool call → text-only response (triggers MISSING_TOOL_USE).
                if not content_blocks and message.content:
                    content_blocks.append({"type": "text", "text": message.content})

                usage = response.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0

                return LLMResponse(
                    content=content_blocks,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=response.model,
                )

            except RateLimitError as e:
                last_error = e
                # Retry with exponential backoff + jitter
            except APIStatusError as e:
                if e.status_code and e.status_code >= 500:
                    last_error = e
                    # Retry with exponential backoff + jitter
                else:
                    # Don't retry 4xx errors (except 429 which is RateLimitError)
                    raise TransportError(f"API error: {e}") from e
            except (APITimeoutError, APIConnectionError) as e:
                last_error = e
                # Retry network errors

            # Exponential backoff with jitter: base * 2^attempt + random(0, 0.5)
            delay = 1.0 * (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)

        # All retries exhausted
        raise TransportError("Transport retries exhausted after 5 attempts") from last_error

    def get_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        """Extract tool_use blocks from a Groq response."""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.get("type") == "tool_use" and "name" in block and "input" in block:
                tool_calls.append(ToolCall(
                    name=block["name"],
                    input=block["input"],
                    id=block.get("id"),
                ))
        return tool_calls


class FakeLLMClient:
    """Fake LLM client for testing. Returns canned responses from fixture data."""

    def __init__(self, responses: Optional[list[dict[str, Any]]] = None) -> None:
        """Initialize with a list of canned responses.

        Each response dict should have:
        - tool_use: dict with "name", "input" keys
        - input_tokens: int
        - output_tokens: int
        - optional: text_only (bool) to simulate a text-only response instead of tool_use
        """
        self._responses = responses or []
        self._call_count = 0

    def set_responses(self, responses: list[dict[str, Any]]) -> None:
        """Set a new list of canned responses."""
        self._responses = responses
        self._call_count = 0

    async def call(
        self,
        tool: Optional[dict[str, Any]] = None,
        user_prompt: str = "",
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Return the next canned response, cycling if needed."""
        if not self._responses:
            # Empty response simulating no data
            return LLMResponse(
                content=[],
                input_tokens=0,
                output_tokens=0,
                model="fake-model",
            )

        response_data = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1

        if response_data.get("text_only"):
            # Simulate a text-only response (no tool_use) - for testing validation failures
            return LLMResponse(
                content=[{"type": "text", "text": response_data.get("text", "Here is some text")}],
                input_tokens=response_data.get("input_tokens", 0),
                output_tokens=response_data.get("output_tokens", 0),
                model="fake-model",
            )

        tool_use = response_data.get("tool_use", {})
        return LLMResponse(
            content=[{
                "type": "tool_use",
                "id": response_data.get("id", f"toolu_{self._call_count}"),
                "name": tool_use.get("name", "unknown_tool"),
                "input": tool_use.get("input", {}),
            }],
            input_tokens=response_data.get("input_tokens", 0),
            output_tokens=response_data.get("output_tokens", 0),
            model="fake-model",
        )

    def get_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        """Extract tool_use blocks from a fake response."""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.get("type") == "tool_use" and "name" in block and "input" in block:
                tool_calls.append(ToolCall(
                    name=block["name"],
                    input=block["input"],
                    id=block.get("id"),
                ))
        return tool_calls
