"""Stage 2 — Extract. For each section, call LLM in parallel to extract topics."""

import asyncio
import time
from pathlib import Path
from typing import Optional

from skillpipeline.llm import LLMClient, TokenUsage, ToolCall
from skillpipeline.models import Section, StageTelemetry, Topic, ValidationEvent
from skillpipeline.retry import MAX_EXTRACT_ATTEMPTS, format_feedback

# Tool definition for extract (Section 5.2)
EXTRACT_TOPICS_TOOL = {
    "name": "record_topics",
    "description": "Record the technical topics found in the given section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z0-9-]+$"},
                        "name": {"type": "string", "minLength": 1, "maxLength": 120},
                        "description": {"type": "string", "minLength": 1, "maxLength": 500},
                        "category": {"type": "string", "minLength": 1, "maxLength": 80},
                        "difficulty": {
                            "type": "string",
                            "enum": ["beginner", "intermediate", "advanced"],
                        },
                    },
                    "required": ["id", "name", "description", "category", "difficulty"],
                },
            },
        },
        "required": ["topics"],
    },
}


class ExtractValidationError(Exception):
    """Raised when extract response fails validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def validate_extract_response(tool_calls: list[ToolCall]) -> list[Topic]:
    """Validate the LLM response and extract topics.

    Args:
        tool_calls: List of tool_use blocks from the LLM response.

    Returns:
        List of validated Topic objects.

    Raises:
        ExtractValidationError: If validation fails.
    """
    if not tool_calls:
        raise ExtractValidationError(
            "MISSING_TOOL_USE",
            "You must respond by calling the record_topics tool, not in free-form text.",
        )

    if len(tool_calls) > 1:
        raise ExtractValidationError(
            "MULTIPLE_TOOLS",
            f"Expected exactly one tool call, got {len(tool_calls)}",
        )

    call = tool_calls[0]

    if call.name != "record_topics":
        raise ExtractValidationError(
            "WRONG_TOOL",
            f"Expected record_topics tool, got {call.name}",
        )

    topics_input = call.input

    if "topics" not in topics_input:
        raise ExtractValidationError(
            "MISSING_TOPICS",
            "Tool response must include a 'topics' field",
        )

    topics_data = topics_input["topics"]

    if not isinstance(topics_data, list):
        raise ExtractValidationError(
            "TOPICS_NOT_ARRAY",
            "'topics' must be an array",
        )

    # Validate each topic and check for uniqueness within the section
    topics: list[Topic] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for i, topic_data in enumerate(topics_data):
        # Validate via Pydantic
        try:
            topic = Topic.model_validate(topic_data)
        except Exception as e:
            raise ExtractValidationError(
                "INVALID_TOPIC",
                f"Topic at index {i} failed validation: {e}",
            )

        # Check uniqueness within this section
        if topic.id in seen_ids:
            raise ExtractValidationError(
                "DUPLICATE_ID",
                f"Duplicate topic id '{topic.id}' within this section",
            )

        name_lower = topic.name.lower()
        if name_lower in seen_names:
            raise ExtractValidationError(
                "DUPLICATE_NAME",
                f"Duplicate topic name '{topic.name}' (case-insensitive) within this section",
            )

        seen_ids.add(topic.id)
        seen_names.add(name_lower)
        topics.append(topic)

    return topics


async def extract_one_section(
    section: Section,
    llm_client: LLMClient,
    system_prompt: str,
    user_prompt_template: str,
    feedback: Optional[str] = None,
) -> tuple[list[Topic], int, list[ValidationEvent], TokenUsage]:
    """Extract topics from a single section with retry logic.

    Args:
        section: The section to extract from.
        llm_client: The LLM client to use.
        system_prompt: The system prompt for the LLM.
        user_prompt_template: The user prompt template (str.format compatible).
        feedback: Optional feedback from a previous failed attempt.

    Returns:
        (topics, attempts_used, validation_events, usage) tuple. `usage` sums
        token counts and cost across every LLM call made for this section,
        including attempts that later failed validation (we still paid for them).

    Note:
        Returns empty list and flagged event if max retries exhausted.
    """
    validation_events: list[ValidationEvent] = []
    usage = TokenUsage()

    # Build the user prompt
    user_prompt = user_prompt_template.format(
        heading=section.heading or "Untitled",
        body=section.body,
        feedback=format_feedback(feedback) if feedback else "",
    )

    for attempt in range(MAX_EXTRACT_ATTEMPTS):
        try:
            response = await llm_client.call(
                tool=EXTRACT_TOPICS_TOOL,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
            )
            usage += TokenUsage(
                response.input_tokens, response.output_tokens, response.estimated_cost_usd
            )

            tool_calls = llm_client.get_tool_calls(response)
            topics = validate_extract_response(tool_calls)

            # Set source_section_id on each topic to track origin
            topics = [t.model_copy(update={"source_section_id": section.id}) for t in topics]

            # Success
            severity = "info" if attempt == 0 else "warning"
            code = "EXTRACT_OK" if attempt == 0 else "EXTRACT_RECOVERED"
            validation_events.append(
                ValidationEvent(
                    stage="extract",
                    severity=severity,
                    code=code,
                    message=f"Section '{section.heading or section.id}' extracted {len(topics)} topics",
                    retry_number=attempt,
                    section_id=section.id,
                )
            )

            return topics, attempt + 1, validation_events, usage

        except ExtractValidationError as e:
            # Record the validation error and retry
            validation_events.append(
                ValidationEvent(
                    stage="extract",
                    severity="warning",
                    code=e.code,
                    message=e.message,
                    retry_number=attempt,
                    section_id=section.id,
                )
            )

            # Build feedback for next attempt
            feedback = e

            # Small delay before retry (Section 6.2: short fixed delay)
            await asyncio.sleep(0.2)

    # Max retries exhausted
    validation_events.append(
        ValidationEvent(
            stage="extract",
            severity="error",
            code="MAX_RETRIES_EXCEEDED",
            message=f"Section '{section.heading or section.id}' failed after {MAX_EXTRACT_ATTEMPTS} attempts",
            retry_number=MAX_EXTRACT_ATTEMPTS,
            section_id=section.id,
            flagged=True,
        )
    )

    return [], MAX_EXTRACT_ATTEMPTS, validation_events, usage


async def extract_sections_parallel(
    sections: list[Section],
    llm_client: LLMClient,
    system_prompt: str,
    user_prompt_template: str,
    initial_retries: dict[str, int],
    initial_feedback: dict[str, str],
) -> tuple[list[Topic], dict[str, int], dict[str, str], list[ValidationEvent], TokenUsage]:
    """Extract topics from all sections in parallel.

    Args:
        sections: List of sections to process.
        llm_client: The LLM client to use.
        system_prompt: The system prompt.
        user_prompt_template: The user prompt template.
        initial_retries: Existing retry counts (for resume scenarios).
        initial_feedback: Existing feedback messages (for resume scenarios).

    Returns:
        (all_topics, retry_counts, feedback_messages, all_validation_events) tuple.
    """
    # Build tasks for each section, passing in any existing feedback
    tasks = [
        extract_one_section(
            section=section,
            llm_client=llm_client,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            feedback=initial_feedback.get(section.id),
        )
        for section in sections
    ]

    # Run all extractions in parallel
    results = await asyncio.gather(*tasks)

    # Aggregate results
    all_topics: list[Topic] = []
    retry_counts: dict[str, int] = initial_retries.copy()
    feedback_messages: dict[str, str] = initial_feedback.copy()
    all_validation_events: list[ValidationEvent] = []
    total_usage = TokenUsage()

    for section, (topics, attempts, events, usage) in zip(sections, results):
        all_topics.extend(topics)
        retry_counts[section.id] = attempts
        all_validation_events.extend(events)
        total_usage += usage

        # Keep the last feedback message for this section (for potential resume)
        if events and events[-1].severity in ("warning", "error"):
            feedback_messages[section.id] = events[-1].message

    return all_topics, retry_counts, feedback_messages, all_validation_events, total_usage


def make_extract_node(llm_client: LLMClient):
    """Create the LangGraph node function for the extract stage.

    Args:
        llm_client: The LLM client to use for extraction.

    Returns:
        A LangGraph node function.
    """

    # Load prompts
    system_prompt = Path("src/skillpipeline/prompts/system.txt").read_text()
    user_prompt_template = Path("src/skillpipeline/prompts/extract_topics.txt").read_text()

    async def extract_node(state: dict) -> dict:
        """LangGraph node function for extract stage."""
        document = state.get("document")
        if not document:
            return {
                "extracted_topics": [],
                "validation_events": [
                    ValidationEvent(
                        stage="extract",
                        severity="error",
                        code="NO_DOCUMENT",
                        message="No document found in state",
                    )
                ],
                "stage_telemetry": [],
            }

        sections = document.sections
        extract_retries = state.get("extract_retries", {})
        extract_feedback = state.get("extract_feedback", {})

        # Record telemetry
        started_at = time.time()
        started_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at))

        # Run parallel extraction
        topics, retry_counts, feedback_messages, validation_events, usage = await extract_sections_parallel(
            sections=sections,
            llm_client=llm_client,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            initial_retries=extract_retries,
            initial_feedback=extract_feedback,
        )

        ended_at = time.time()
        duration_ms = int((ended_at - started_at) * 1000)
        ended_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended_at))

        # Count total LLM calls
        total_llm_calls = sum(retry_counts.values())

        telemetry = StageTelemetry(
            stage="extract",
            started_at=started_at_iso,
            ended_at=ended_at_iso,
            duration_ms=duration_ms,
            llm_calls=total_llm_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            estimated_cost_usd=usage.cost_usd,
        )

        # Identify flagged sections (those that hit max retries)
        flagged_sections = [
            section.id
            for section in sections
            if retry_counts.get(section.id, 0) >= MAX_EXTRACT_ATTEMPTS
        ]

        return {
            "extracted_topics": topics,
            "extract_retries": retry_counts,
            "extract_feedback": feedback_messages,
            "flagged_sections": flagged_sections,
            "validation_events": validation_events,
            "stage_telemetry": [telemetry],
        }

    return extract_node
