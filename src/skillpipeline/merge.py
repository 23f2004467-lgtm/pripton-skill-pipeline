"""Stage 3: Merge deduplicates topics across sections and assigns final IDs."""

from collections import Counter, defaultdict
from typing import Literal

from skillpipeline.models import (
    PipelineState,
    Topic,
    ValidationEvent,
)


def _normalize_name(name: str) -> str:
    """Normalize topic name for deduplication key."""
    return name.strip().lower()


def _difficulty_rank(difficulty: Literal["beginner", "intermediate", "advanced"]) -> int:
    """Lower number = easier (conservative choice)."""
    return {"beginner": 0, "intermediate": 1, "advanced": 2}[difficulty]


def _section_order_key(topic: Topic) -> tuple:
    """Sort key for first-occurrence by section order.

    Topics from the same section have source_section_id set.
    Sort by source_section_id, then by topic id for tiebreaking.
    """
    # Use source_section_id if available (set by extract.py)
    # Otherwise fall back to topic.id as a stable tiebreaker
    section_part = topic.source_section_id or topic.id
    # Extract numeric suffix if present (e.g. "section-2" -> 2)
    # This ensures section-10 comes after section-2, not before
    if "-" in section_part:
        prefix, num = section_part.rsplit("-", 1)
        if num.isdigit():
            return (0, prefix, int(num), topic.id)
    return (1, section_part, topic.id)


def merge_topics(state: PipelineState) -> PipelineState:
    """
    Deduplicate topics across sections and assign final IDs.

    Implements Section 5.3 of PLAN.md:
    1. Normalize topic names and group by normalized name
    2. For each group, pick canonical record and log conflicts
    3. Assign final canonical IDs (canonical record's ID wins)
    4. source_section_id is inherited from canonical record
    """
    extracted_topics: list[Topic] = state["extracted_topics"]

    if not extracted_topics:
        # No topics extracted - empty extraction short-circuit
        event = ValidationEvent(
            stage="merge",
            severity="error",
            code="EMPTY_EXTRACTION",
            message="No topics extracted from any section; cannot proceed to relationship extraction.",
            flagged=True,
        )
        return {
            "merged_topics": [],
            "validation_events": [event],
        }

    # Group by normalized name
    groups: dict[str, list[Topic]] = defaultdict(list)
    for topic in extracted_topics:
        key = _normalize_name(topic.name)
        groups[key].append(topic)

    validation_events: list[ValidationEvent] = []
    merged_topics: list[Topic] = []

    for normalized_name, group in groups.items():
        if len(group) == 1:
            # No duplicate - use as-is, source_section_id already set by extract.py
            merged_topics.append(group[0])
        else:
            # Duplicate detected - log merge
            validation_events.append(
                ValidationEvent(
                    stage="merge",
                    severity="info",
                    code="DUPLICATE_TOPIC_MERGED",
                    message=f"Merged {len(group)} topics with normalized name '{normalized_name}'",
                )
            )

            # Pick canonical: longest description, then by first source section order
            canonical = max(group, key=lambda t: (len(t.description), _section_order_key(t)))

            # Check difficulty conflict
            difficulties = {t.difficulty for t in group}
            if len(difficulties) > 1:
                # Pick lowest difficulty (conservative)
                canonical_difficulty = min(group, key=lambda t: _difficulty_rank(t.difficulty)).difficulty
                validation_events.append(
                    ValidationEvent(
                        stage="merge",
                        severity="warning",
                        code="DIFFICULTY_CONFLICT",
                        message=f"Topic '{normalized_name}' has conflicting difficulties: {sorted(set(difficulties))}. Using '{canonical_difficulty}' (conservative).",
                    )
                )
                canonical = canonical.model_copy(update={"difficulty": canonical_difficulty})

            # Check category conflict
            categories = [t.category for t in group]
            unique_categories = set(categories)
            if len(unique_categories) > 1:
                # Pick most frequent
                most_common = Counter(categories).most_common(1)[0][0]
                validation_events.append(
                    ValidationEvent(
                        stage="merge",
                        severity="warning",
                        code="CATEGORY_CONFLICT",
                        message=f"Topic '{normalized_name}' has conflicting categories: {sorted(set(unique_categories))}. Using '{most_common}'.",
                    )
                )
                canonical = canonical.model_copy(update={"category": most_common})

            # source_section_id is inherited from canonical record (set by extract.py)
            merged_topics.append(canonical)

    return {
        "merged_topics": merged_topics,
        "validation_events": validation_events,
    }
