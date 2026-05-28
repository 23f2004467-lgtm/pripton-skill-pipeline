"""Stage 4 — Human Review. Conditional interrupt for topic inspection and editing.

This stage triggers when:
- Any section needed at least one retry (uncertainty signal)
- --always-review flag is passed

When triggered, writes topics_for_review.json and interrupts for human editing.
When not triggered, passes merged_topics through as approved_topics.

See PLAN.md Section 5.4 for the full specification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from skillpipeline.models import PipelineState, Topic, ValidationEvent


def _should_interrupt(state: PipelineState) -> bool:
    """Determine whether human review interrupt should trigger.

    Interrupt iff:
    - Any section needed at least one retry, OR
    - always_review flag is True
    """
    extract_retries = state.get("extract_retries") or {}
    always_review = state.get("always_review", False)

    # Check if any section needed at least one retry
    any_retried = any(count > 0 for count in extract_retries.values())

    return any_retried or always_review


def _format_review_file_content(
    merged_topics: list[Topic],
    merge_events: list[ValidationEvent],
) -> str:
    """Format the contents of topics_for_review.json.

    Includes:
    - _instructions: how to edit the file
    - _merge_events: validation events from merge (why review was triggered)
    - topics: the actual topic data
    """
    instructions = {
        "_instructions": {
            "purpose": "Review and edit the extracted topics before relationship extraction.",
            "how_to_edit": [
                "Edit the 'topics' array below.",
                "Add, remove, or modify topics as needed.",
                "Each topic must have: id (lowercase-hyphens), name, description, category, difficulty.",
                "Save the file and run 'pipeline resume {thread_id}' to continue.",
            ],
            "validation_rules": [
                "id must match pattern: ^[a-z0-9-]+$ (lowercase, hyphens only)",
                "name: 1-120 characters, required",
                "description: 1-500 characters, required",
                "category: 1-80 characters, required",
                "difficulty: 'beginner' | 'intermediate' | 'advanced', required",
                "All topic IDs must be unique.",
            ],
        },
        "_merge_events": [
            {
                "stage": e.stage,
                "severity": e.severity,
                "code": e.code,
                "message": e.message,
            }
            for e in merge_events
        ],
        "topics": [t.model_dump() for t in merged_topics],
    }
    return json.dumps(instructions, indent=2)


async def human_review_node(state: PipelineState) -> dict:
    """Human review node for LangGraph.

    If interrupt condition is met:
    - Write topics_for_review.json
    - Set status to "awaiting_review"
    - Trigger interrupt

    If no interrupt condition:
    - Set approved_topics = merged_topics
    - Return immediately (graph proceeds to relate)

    Args:
        state: Current pipeline state

    Returns:
        State update dict with approved_topics and/or status
    """
    merged_topics = state.get("merged_topics")
    if not merged_topics:
        # No topics to review - should not happen given merge short-circuit,
        # but handle gracefully
        return {"approved_topics": []}

    if not _should_interrupt(state):
        # Skip interrupt - pass topics through
        return {"approved_topics": merged_topics}

    # Interrupt path - write review file and trigger interrupt
    thread_id = state.get("thread_id", "unknown")

    # Gather merge-related validation events
    validation_events = state.get("validation_events", [])
    merge_events = [e for e in validation_events if e.stage in ("extract", "merge")]

    # Create runs directory if needed
    run_dir = Path("runs") / thread_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write topics_for_review.json
    review_file = run_dir / "topics_for_review.json"
    content = _format_review_file_content(merged_topics, merge_events)
    review_file.write_text(content, encoding="utf-8")

    # Update status to awaiting_review
    # Note: The interrupt() call will happen in the graph layer, not here.
    # This node just prepares the state and signals that interrupt is needed.
    # The graph's conditional edge will handle the actual interrupt() call.
    return {
        "approved_topics": None,  # Will be set on resume
        "awaiting_review": True,  # Signal to graph to trigger interrupt
        "review_file_path": str(review_file),
    }


def validate_review_topics(topics_data: list | dict) -> list[Topic]:
    """Validate topics_for_review.json content on resume.

    Args:
        topics_data: Parsed JSON content from the review file

    Returns:
        List of validated Topic objects

    Raises:
        ValueError: If validation fails with specific error message
    """
    # Handle both the full file format and direct topics list
    if isinstance(topics_data, dict):
        # Full format with _instructions, _merge_events, topics
        if "topics" not in topics_data:
            raise ValueError("Review file must contain a 'topics' array")
        topics_list = topics_data["topics"]
    elif isinstance(topics_data, list):
        # Direct topics list (simplified format)
        topics_list = topics_data
    else:
        raise ValueError("Review file must contain a 'topics' array or be a list of topics")

    if not isinstance(topics_list, list):
        raise ValueError("'topics' must be an array")

    # Validate each topic with Pydantic
    topics: list[Topic] = []
    seen_ids: set[str] = set()

    for i, topic_data in enumerate(topics_list):
        try:
            topic = Topic(**topic_data)
        except Exception as e:
            raise ValueError(f"Topic at index {i} is invalid: {e}")

        # Check for duplicate IDs
        if topic.id in seen_ids:
            raise ValueError(f"Duplicate topic id: '{topic.id}'")
        seen_ids.add(topic.id)

        topics.append(topic)

    return topics
