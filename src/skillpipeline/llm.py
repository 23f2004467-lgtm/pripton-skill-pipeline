"""LLM client wrapper with tool-use support and transport-level retries."""

import os
import random
import time
from typing import Any, Optional, Protocol, cast

import anthropic
from anthropic.types import Message, TextBlock, ToolUseBlock

# LLM configuration constants (Section 5.0)
MODEL = "claude-sonnet-4-5"
TEMPERATURE = 0.0
MAX_TOKENS = 4096

# Cost rates (USD per million tokens) - verify against current Anthropic pricing
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00


def compute_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost in USD for a given token usage."""
    return (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK + (
        output_tokens / 1_000_000
    ) * OUTPUT_COST_PER_MTOK


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


class AnthropicLLMClient:
    """Concrete Anthropic LLM client with tool-use and transport retries."""

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
        self._client = anthropic.AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def call(
        self,
        tool: dict[str, Any],
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Call the Anthropic API with tool-use, with transport-level retries.

        Transport retries (Section 6.2):
        - Max 5 attempts
        - Exponential backoff with jitter
        - Base delay 1s
        - Retried only on APIStatusError (status >= 500) or RateLimitError
        """
        last_error: Optional[Exception] = None

        for attempt in range(5):
            try:
                # Build the create call kwargs
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "tools": [cast(Any, tool)],  # cast to satisfy mypy
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                response: Message = await self._client.messages.create(**kwargs)

                # Extract response data into simple dicts for downstream use
                content_blocks: list[dict[str, Any]] = []
                for block in response.content:
                    if isinstance(block, ToolUseBlock):
                        content_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                    elif isinstance(block, TextBlock):
                        content_blocks.append({
                            "type": "text",
                            "text": block.text,
                        })
                    else:
                        # Handle other block types generically
                        content_blocks.append({
                            "type": block.type,
                            **(block.model_dump(exclude={"type"})),
                        })

                return LLMResponse(
                    content=content_blocks,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    model=response.model,
                )

            except anthropic.RateLimitError as e:
                last_error = e
                # Retry with exponential backoff + jitter
            except anthropic.APIStatusError as e:
                if e.status_code and e.status_code >= 500:
                    last_error = e
                    # Retry with exponential backoff + jitter
                else:
                    # Don't retry 4xx errors (except 429 which is RateLimitError)
                    raise TransportError(f"API error: {e}") from e
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                last_error = e
                # Retry network errors

            # Exponential backoff with jitter: base * 2^attempt + random(0, 0.5)
            delay = 1.0 * (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)

        # All retries exhausted
        raise TransportError("Transport retries exhausted after 5 attempts") from last_error

    def get_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        """Extract tool_use blocks from an Anthropic response."""
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
