"""LLM client wrapper with tool-use support and transport-level retries."""

import json
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
        estimated_cost_usd: Optional[float] = None,
    ) -> None:
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        # Providers may supply their own cost; default to Anthropic rates.
        self.estimated_cost_usd = (
            estimated_cost_usd
            if estimated_cost_usd is not None
            else compute_cost_usd(input_tokens, output_tokens)
        )


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


# Groq configuration. Groq is OpenAI-compatible, not Anthropic-compatible, so
# GroqLLMClient translates the Anthropic-style tool dict into function-calling
# format and maps the response back into the same content blocks the pipeline
# expects. NOTE: this is an approved deviation from PLAN.md 3.1/14 (single
# provider: Anthropic); used only when no Anthropic key is available.
GROQ_MODEL = "llama-3.3-70b-versatile"
# Free-tier usage is $0; reported cost is 0.0 rather than Anthropic's rates.
GROQ_INPUT_COST_PER_MTOK = 0.0
GROQ_OUTPUT_COST_PER_MTOK = 0.0


def _anthropic_tool_to_groq(tool: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic tool dict into Groq/OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }


class GroqLLMClient:
    """Groq LLM client implementing the same LLMClient protocol as Anthropic.

    Uses Groq's OpenAI-compatible function-calling to emulate Anthropic tool-use,
    returning identical `{"type": "tool_use", ...}` content blocks so the extract
    and relate stages need no changes.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GROQ_MODEL,
        temperature: float = TEMPERATURE,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        import groq

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = groq.AsyncGroq(api_key=api_key or os.environ.get("GROQ_API_KEY"))

    async def call(
        self,
        tool: dict[str, Any],
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Call the Groq API with forced function-calling, with transport retries.

        Mirrors AnthropicLLMClient's retry policy: max 5 attempts, exponential
        backoff with jitter, retried only on RateLimitError, 5xx APIStatusError,
        or network errors. All other errors propagate as TransportError.
        """
        import groq

        groq_tool = _anthropic_tool_to_groq(tool)
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
                        # Surface as an empty tool_use; downstream validation
                        # treats missing structured output as a retryable error.
                        parsed_input = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": parsed_input,
                    })
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
                    estimated_cost_usd=(
                        (input_tokens / 1_000_000) * GROQ_INPUT_COST_PER_MTOK
                        + (output_tokens / 1_000_000) * GROQ_OUTPUT_COST_PER_MTOK
                    ),
                )

            except groq.RateLimitError as e:
                last_error = e
            except groq.APIStatusError as e:
                if e.status_code and e.status_code >= 500:
                    last_error = e
                else:
                    raise TransportError(f"API error: {e}") from e
            except (groq.APITimeoutError, groq.APIConnectionError) as e:
                last_error = e

            delay = 1.0 * (2**attempt) + random.uniform(0, 0.5)
            time.sleep(delay)

        raise TransportError("Transport retries exhausted after 5 attempts") from last_error

    def get_tool_calls(self, response: LLMResponse) -> list[ToolCall]:
        """Extract tool_use blocks from a Groq response (same shape as Anthropic)."""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.get("type") == "tool_use" and "name" in block and "input" in block:
                tool_calls.append(ToolCall(
                    name=block["name"],
                    input=block["input"],
                    id=block.get("id"),
                ))
        return tool_calls


def make_default_client() -> LLMClient:
    """Construct the default LLM client based on environment.

    Selection: SKILLPIPELINE_PROVIDER ("anthropic" | "groq") wins if set;
    otherwise auto-detect — use Groq when GROQ_API_KEY is present and no
    ANTHROPIC_API_KEY is set, else Anthropic.
    """
    provider = os.environ.get("SKILLPIPELINE_PROVIDER", "").strip().lower()
    if provider == "groq":
        return GroqLLMClient()
    if provider == "anthropic":
        return AnthropicLLMClient()
    if os.environ.get("GROQ_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        return GroqLLMClient()
    return AnthropicLLMClient()


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
