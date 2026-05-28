"""Stage 6: Validate relationships against schema and business rules."""

from collections import Counter
from typing import Literal, Optional

import networkx as nx

from skillpipeline.models import (
    PipelineState,
    Relationship,
    Topic,
    ValidationEvent,
)
from skillpipeline.retry import MAX_RELATE_RETRIES

# Validation codes
SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
DANGLING_FROM_REF = "DANGLING_FROM_REF"
DANGLING_TO_REF = "DANGLING_TO_REF"
SELF_LOOP = "SELF_LOOP"
DUPLICATE_EDGE = "DUPLICATE_EDGE"
CYCLE_IN_PREREQUISITES = "CYCLE_IN_PREREQUISITES"
ORPHAN_TOPIC = "ORPHAN_TOPIC"


def _validate_relationships(
    relationships: list[Relationship],
    approved_topics: list[Topic],
) -> list[ValidationEvent]:
    """Validate relationships against business rules.

    Returns a list of ValidationEvents. Errors indicate the relationship should be rejected.
    Warnings (ORPHAN_TOPIC) are informational and do not trigger rejection.
    """
    events: list[ValidationEvent] = []
    topic_ids = {t.id for t in approved_topics}

    # Track seen edges for duplicate detection
    seen_edges: set[tuple[str, str, str]] = set()

    # Build prerequisite graph for cycle detection
    prerequisite_graph = nx.DiGraph()

    for i, rel in enumerate(relationships):
        # Check: self-loop
        if rel.from_id == rel.to_id:
            events.append(
                ValidationEvent(
                    stage="validate",
                    severity="error",
                    code=SELF_LOOP,
                    message=f"Relationship at index {i} is a self-loop: {rel.from_id}",
                )
            )
            continue  # Skip further checks for this relationship

        # Check: dangling from_ref
        if rel.from_id not in topic_ids:
            events.append(
                ValidationEvent(
                    stage="validate",
                    severity="error",
                    code=DANGLING_FROM_REF,
                    message=f"Relationship at index {i} references non-existent from_id: {rel.from_id}",
                )
            )

        # Check: dangling to_ref
        if rel.to_id not in topic_ids:
            events.append(
                ValidationEvent(
                    stage="validate",
                    severity="error",
                    code=DANGLING_TO_REF,
                    message=f"Relationship at index {i} references non-existent to_id: {rel.to_id}",
                )
            )

        # Check: duplicate edge
        edge_key = (rel.from_id, rel.to_id, rel.type)
        if edge_key in seen_edges:
            events.append(
                ValidationEvent(
                    stage="validate",
                    severity="error",
                    code=DUPLICATE_EDGE,
                    message=f"Duplicate edge: ({rel.from_id}, {rel.to_id}, {rel.type})",
                )
            )
        seen_edges.add(edge_key)

        # Add to prerequisite graph for cycle detection
        if rel.type == "prerequisite" and rel.from_id in topic_ids and rel.to_id in topic_ids:
            prerequisite_graph.add_edge(rel.from_id, rel.to_id)

    # Check: cycles in prerequisites
    cycles = list(nx.simple_cycles(prerequisite_graph))
    for cycle in cycles:
        events.append(
            ValidationEvent(
                stage="validate",
                severity="error",
                code=CYCLE_IN_PREREQUISITES,
                message=f"Cycle detected in prerequisite relationships: {' -> '.join(cycle)} -> {cycle[0]}",
            )
        )

    # Check: orphan topics (warning only)
    referenced_ids: set[str] = set()
    for rel in relationships:
        referenced_ids.add(rel.from_id)
        referenced_ids.add(rel.to_id)

    orphans = topic_ids - referenced_ids
    for orphan_id in sorted(orphans):
        events.append(
            ValidationEvent(
                stage="validate",
                severity="warning",
                code=ORPHAN_TOPIC,
                message=f"Topic '{orphan_id}' appears in no relationships",
            )
        )

    return events


def format_feedback(events: list[ValidationEvent]) -> str:
    """Format validation errors into feedback for the LLM."""
    error_events = [e for e in events if e.severity == "error"]
    if not error_events:
        return ""

    # Group by code for clearer feedback
    by_code: dict[str, list[ValidationEvent]] = {}
    for event in error_events:
        by_code.setdefault(event.code, []).append(event)

    lines = ["A previous attempt at this task failed validation with the following error(s):\n"]
    for code, code_events in sorted(by_code.items()):
        lines.append(f"\n{code} ({len(code_events)} occurrence(s)):")
        for event in code_events[:5]:  # Limit to 5 per code to avoid overwhelming
            lines.append(f"  - {event.message}")
        if len(code_events) > 5:
            lines.append(f"  ... and {len(code_events) - 5} more")

    lines.append("\n\nPlease correct these issues and try again. Pay particular attention to the "
                 "ID-format and reference-integrity rules.")

    return "\n".join(lines)


def validate_relationships(state: PipelineState) -> PipelineState:
    """
    Validate relationships and decide whether to accept, retry, or flag.

    Implements Section 5.6 of PLAN.md.
    """
    approved_topics: Optional[list[Topic]] = state.get("approved_topics")
    relationships: Optional[list[Relationship]] = state.get("relationships")
    relate_retries: int = state.get("relate_retries", 0)

    if not approved_topics:
        # No topics to validate against - this shouldn't happen in normal flow
        return {
            "validation_events": [
                ValidationEvent(
                    stage="validate",
                    severity="error",
                    code=SCHEMA_VIOLATION,
                    message="No approved topics found in state",
                )
            ],
        }

    if not relationships:
        # No relationships to validate - proceed with empty
        return {"validation_events": []}

    # Run validation
    events = _validate_relationships(relationships, approved_topics)

    # Check for errors (not warnings)
    errors = [e for e in events if e.severity == "error"]

    if not errors:
        # No errors - proceed to persist
        return {"validation_events": events}

    # Has errors
    if relate_retries < MAX_RELATE_RETRIES:
        # Retry with feedback
        feedback = format_feedback(events)
        return {
            "validation_events": events,
            "relate_feedback": feedback,
            "relate_retries": relate_retries + 1,
        }
    else:
        # Max retries exhausted - flag and proceed with valid relationships only
        # Filter out relationships that have errors
        valid_relationships = _filter_valid_relationships(relationships, events, approved_topics)

        # Add a flag event
        flag_event = ValidationEvent(
            stage="validate",
            severity="error",
            code="MAX_RETRIES_EXCEEDED",
            message=f"Relationship validation failed after {MAX_RELATE_RETRIES} retries. Proceeding with {len(valid_relationships)} valid relationships.",
            flagged=True,
        )
        events.append(flag_event)

        return {
            "validation_events": events,
            "relationships": valid_relationships,
            "flagged_relations": True,
        }


def _filter_valid_relationships(
    relationships: list[Relationship],
    events: list[ValidationEvent],
    approved_topics: list[Topic],
) -> list[Relationship]:
    """Filter relationships to only those that don't have validation errors."""
    topic_ids = {t.id for t in approved_topics}
    error_indices: set[int] = set()

    # Build prerequisite graph for cycle detection
    prerequisite_graph = nx.DiGraph()
    for i, rel in enumerate(relationships):
        if rel.type == "prerequisite" and rel.from_id in topic_ids and rel.to_id in topic_ids:
            prerequisite_graph.add_edge(rel.from_id, rel.to_id)

    # Check for cycles
    cycles = list(nx.simple_cycles(prerequisite_graph))

    for i, rel in enumerate(relationships):
        # Self-loop
        if rel.from_id == rel.to_id:
            error_indices.add(i)
            continue

        # Dangling refs
        if rel.from_id not in topic_ids or rel.to_id not in topic_ids:
            error_indices.add(i)
            continue

        # Duplicate edge
        edge_key = (rel.from_id, rel.to_id, rel.type)
        is_duplicate = any(
            edge_key == (r.from_id, r.to_id, r.type)
            for j, r in enumerate(relationships)
            if j < i
        )
        if is_duplicate:
            error_indices.add(i)
            continue

        # Part of a cycle in prerequisites
        if rel.type == "prerequisite":
            for cycle in cycles:
                if rel.from_id in cycle and rel.to_id in cycle:
                    # Check if this edge is part of the cycle
                    cycle_edges = set(zip(cycle, cycle[1:] + cycle[:1]))
                    if (rel.from_id, rel.to_id) in cycle_edges:
                        error_indices.add(i)
                        break

    return [rel for i, rel in enumerate(relationships) if i not in error_indices]
