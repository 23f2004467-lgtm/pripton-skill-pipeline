"""Stage 5 — Relate. Extract typed relationships between approved topics."""

import asyncio
import time
from pathlib import Path
from typing import Optional

from skillpipeline.llm import LLMClient, ToolCall
from skillpipeline.models import (
    PipelineState,
    Relationship,
    StageTelemetry,
    Topic,
    ValidationEvent,
)
from skillpipeline.retry import MAX_RELATE_RETRIES, format_feedback

# Tool definition for relate (Section 5.5)
EXTRACT_RELATIONSHIPS_TOOL = {
    "name": "record_relationships",
    "description": "Record typed relationships between the given topics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_id": {"type": "string"},
                        "to_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["prerequisite", "related", "subtopic"],
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["from_id", "to_id", "type"],
                },
            }
        },
        "required": ["relationships"],
    },
}


class RelateValidationError(Exception):
    """Raised when relate response fails validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def validate_relate_response(tool_calls: list[ToolCall]) -> list[Relationship]:
    """Validate the LLM response and extract relationships.

    Args:
        tool_calls: List of tool_use blocks from the LLM response.

    Returns:
        List of validated Relationship objects.

    Raises:
        RelateValidationError: If validation fails.
    """
    if not tool_calls:
        raise RelateValidationError(
            "MISSING_TOOL_USE",
            "You must respond by calling the record_relationships tool, not in free-form text.",
        )

    if len(tool_calls) > 1:
        raise RelateValidationError(
            "MULTIPLE_TOOLS",
            "You must call the record_relationships tool exactly once.",
        )

    call = tool_calls[0]

    if call.name != "record_relationships":
        raise RelateValidationError(
            "WRONG_TOOL",
            f"You must call the record_relationships tool, not {call.name}.",
        )

    relationships_input = call.input

    if "relationships" not in relationships_input:
        raise RelateValidationError(
            "MISSING_RELATIONSHIPS",
            "Tool response must include a 'relationships' field",
        )

    relationships_data = relationships_input["relationships"]

    if not isinstance(relationships_data, list):
        raise RelateValidationError(
            "RELATIONSHIPS_NOT_ARRAY",
            "'relationships' must be an array",
        )

    # Validate each relationship
    relationships: list[Relationship] = []
    for i, rel_data in enumerate(relationships_data):
        # Validate via Pydantic
        try:
            rel = Relationship.model_validate(rel_data)
        except Exception as e:
            raise RelateValidationError(
                "INVALID_RELATIONSHIP",
                f"Relationship at index {i} failed validation: {e}",
            )

        relationships.append(rel)

    return relationships


async def relate_topics(
    approved_topics: list[Topic],
    llm_client: LLMClient,
    system_prompt: str,
    user_prompt_template: str,
    feedback: Optional[str] = None,
) -> tuple[list[Relationship], int, list[ValidationEvent]]:
    """Extract relationships from approved topics with retry logic.

    Args:
        approved_topics: The list of topics to extract relationships from.
        llm_client: The LLM client to use.
        system_prompt: The system prompt for the LLM.
        user_prompt_template: The user prompt template (str.format compatible).
        feedback: Optional feedback from a previous failed attempt.

    Returns:
        (relationships, attempts_used, validation_events) tuple.

    Note:
        Returns empty list and flagged event if max retries exhausted.
    """
    validation_events: list[ValidationEvent] = []

    # Build topics list for the prompt
    topics_list = "\n".join(
        f"- {t.id}: {t.name} ({t.category}, {t.difficulty})"
        for t in approved_topics
    )

    # Build the user prompt
    user_prompt = user_prompt_template.format(
        topics=topics_list,
        feedback=format_feedback(feedback) if feedback else "",
    )

    for attempt in range(MAX_RELATE_RETRIES):
        try:
            response = await llm_client.call(
                tool=EXTRACT_RELATIONSHIPS_TOOL,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
            )

            tool_calls = llm_client.get_tool_calls(response)
            relationships = validate_relate_response(tool_calls)

            # Success
            severity = "info" if attempt == 0 else "warning"
            code = "RELATE_OK" if attempt == 0 else "RELATE_RECOVERED"
            validation_events.append(
                ValidationEvent(
                    stage="relate",
                    severity=severity,
                    code=code,
                    message=f"Extracted {len(relationships)} relationships",
                    retry_number=attempt,
                )
            )

            return relationships, attempt + 1, validation_events

        except RelateValidationError as e:
            # Record the validation error and retry
            validation_events.append(
                ValidationEvent(
                    stage="relate",
                    severity="warning",
                    code=e.code,
                    message=e.message,
                    retry_number=attempt,
                )
            )

            # Build feedback for next attempt
            feedback = e

            # Small delay before retry
            await asyncio.sleep(0.2)

    # Max retries exhausted
    validation_events.append(
        ValidationEvent(
            stage="relate",
            severity="error",
            code="MAX_RETRIES_EXCEEDED",
            message=f"Relationship extraction failed after {MAX_RELATE_RETRIES} attempts",
            retry_number=MAX_RELATE_RETRIES,
            flagged=True,
        )
    )

    return [], MAX_RELATE_RETRIES, validation_events


def make_relate_node(llm_client: LLMClient):
    """Create the LangGraph node function for the relate stage.

    Args:
        llm_client: The LLM client to use for relationship extraction.

    Returns:
        A LangGraph node function.
    """

    # Load prompts
    system_prompt = Path("src/skillpipeline/prompts/system.txt").read_text()
    user_prompt_template = Path(
        "src/skillpipeline/prompts/extract_relationships.txt"
    ).read_text()

    async def relate_node(state: PipelineState) -> dict:
        """LangGraph node function for relate stage."""
        approved_topics: Optional[list[Topic]] = state.get("approved_topics")
        relate_feedback: Optional[str] = state.get("relate_feedback")
        relate_retries: int = state.get("relate_retries", 0)

        if not approved_topics:
            return {
                "relationships": [],
                "validation_events": [
                    ValidationEvent(
                        stage="relate",
                        severity="error",
                        code="NO_TOPICS",
                        message="No approved topics found in state",
                    )
                ],
                "stage_telemetry": [],
            }

        # Record telemetry
        started_at = time.time()
        started_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at))

        # Run relationship extraction
        relationships, attempts_used, validation_events = await relate_topics(
            approved_topics=approved_topics,
            llm_client=llm_client,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            feedback=relate_feedback,
        )

        ended_at = time.time()
        duration_ms = int((ended_at - started_at) * 1000)
        ended_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended_at))

        telemetry = StageTelemetry(
            stage="relate",
            started_at=started_at_iso,
            ended_at=ended_at_iso,
            duration_ms=duration_ms,
            llm_calls=attempts_used,
        )

        return {
            "relationships": relationships,
            "validation_events": validation_events,
            "stage_telemetry": [telemetry],
        }

    return relate_node
