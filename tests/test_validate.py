"""Tests for validate stage."""

import pytest

from skillpipeline.models import Relationship, Topic, ValidationEvent
from skillpipeline.validate import (
    CYCLE_IN_PREREQUISITES,
    DANGLING_FROM_REF,
    DANGLING_TO_REF,
    DUPLICATE_EDGE,
    MAX_RELATE_RETRIES,
    ORPHAN_TOPIC,
    SCHEMA_VIOLATION,
    SELF_LOOP,
    _validate_relationships,
    format_feedback,
    validate_relationships as validate_node,
)


@pytest.fixture
def sample_topics():
    """Standard set of topics for testing."""
    return [
        Topic(id="python", name="Python", description="A language", category="backend", difficulty="beginner"),
        Topic(id="django", name="Django", description="A framework", category="backend", difficulty="intermediate"),
        Topic(id="flask", name="Flask", description="Another framework", category="backend", difficulty="intermediate"),
        Topic(id="sql", name="SQL", description="Database query language", category="database", difficulty="beginner"),
    ]


@pytest.fixture
def sample_state():
    """Base pipeline state for validate tests."""
    return {
        "approved_topics": [],
        "relationships": [],
        "relate_retries": 0,
        "relate_feedback": None,
        "flagged_relations": False,
        "validation_events": [],
    }


class TestValidateRelationships:
    def test_no_relationships(self, sample_state, sample_topics):
        """Empty relationship list passes validation."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = []
        result = validate_node(sample_state)

        assert len(result["validation_events"]) == 0

    def test_valid_relationships(self, sample_state, sample_topics):
        """Valid relationships pass validation."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
            Relationship(from_id="python", to_id="flask", type="related"),
        ]
        result = validate_node(sample_state)

        errors = [e for e in result["validation_events"] if e.severity == "error"]
        assert len(errors) == 0

    def test_self_loop_detected(self, sample_state, sample_topics):
        """Self-loop relationship is rejected.

        Note: The Relationship model's Pydantic validator catches this at creation time,
        so validate_stage never sees a self-loop. This test documents that the model
        enforces this constraint, and validate_stage provides a redundant check.
        """
        # Creating a self-loop via Pydantic fails
        with pytest.raises(Exception, match="self-referential"):
            Relationship(from_id="python", to_id="python", type="prerequisite")

        # If somehow bypassed Pydantic (e.g. raw dict), validate would catch it
        # For completeness, we verify the helper function works
        # Use model_construct to bypass Pydantic validation
        bad_rel = Relationship.model_construct(
            from_id="python", to_id="python", type="prerequisite"
        )
        events = _validate_relationships([bad_rel], sample_topics)
        assert any(e.code == SELF_LOOP for e in events)

    def test_dangling_from_ref(self, sample_state, sample_topics):
        """from_id not in topic set is rejected."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="nonexistent", to_id="python", type="prerequisite"),
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        assert any(e.code == DANGLING_FROM_REF for e in events)

    def test_dangling_to_ref(self, sample_state, sample_topics):
        """to_id not in topic set is rejected."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="nonexistent", type="prerequisite"),
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        assert any(e.code == DANGLING_TO_REF for e in events)

    def test_duplicate_edge_detected(self, sample_state, sample_topics):
        """Duplicate (from_id, to_id, type) tuples are rejected."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
            Relationship(from_id="python", to_id="django", type="prerequisite"),
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        assert any(e.code == DUPLICATE_EDGE for e in events)

    def test_different_types_not_duplicate(self, sample_state, sample_topics):
        """Same from/to but different types is allowed."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
            Relationship(from_id="python", to_id="django", type="related"),
        ]
        result = validate_node(sample_state)

        errors = [e for e in result["validation_events"] if e.severity == "error"]
        assert len(errors) == 0

    def test_cycle_in_prerequisites(self, sample_state, sample_topics):
        """Cycles in prerequisite relationships are detected."""
        # Create a cycle: python -> django -> flask -> python
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
            Relationship(from_id="django", to_id="flask", type="prerequisite"),
            Relationship(from_id="flask", to_id="python", type="prerequisite"),
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        cycle_events = [e for e in events if e.code == CYCLE_IN_PREREQUISITES]
        assert len(cycle_events) >= 1
        assert "cycle" in cycle_events[0].message.lower()

    def test_orphan_topic_warning(self, sample_state, sample_topics):
        """Topics not referenced by any relationship generate warnings (not errors)."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
            # sql is not referenced
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        orphan_events = [e for e in events if e.code == ORPHAN_TOPIC]
        assert len(orphan_events) >= 1
        assert orphan_events[0].severity == "warning"

    def test_no_errors_proceeds_to_persist(self, sample_state, sample_topics):
        """No errors means no retry or flag."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),
        ]
        sample_state["relate_retries"] = 0
        result = validate_node(sample_state)

        # Should not set feedback or increment retries
        assert result.get("relate_feedback") is None
        assert result.get("relate_retries", 0) == 0
        assert result.get("flagged_relations", False) is False

    def test_errors_with_retries_remaining(self, sample_state, sample_topics):
        """Errors with retries < 3 triggers retry with feedback."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="nonexistent", type="prerequisite"),
        ]
        sample_state["relate_retries"] = 0
        result = validate_node(sample_state)

        # Should increment retries and provide feedback
        assert result["relate_retries"] == 1
        assert result["relate_feedback"] is not None
        assert "non-existent" in result["relate_feedback"].lower()

    def test_errors_max_retries_exhausted(self, sample_state, sample_topics):
        """Errors with retries >= 3 flags and filters to valid relationships."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="prerequisite"),  # Valid
            Relationship(from_id="python", to_id="nonexistent", type="prerequisite"),  # Invalid
        ]
        sample_state["relate_retries"] = MAX_RELATE_RETRIES
        result = validate_node(sample_state)

        # Should flag and filter relationships
        assert result["flagged_relations"] is True
        filtered_rels = result["relationships"]
        assert len(filtered_rels) == 1
        assert filtered_rels[0].from_id == "python"
        assert filtered_rels[0].to_id == "django"

        # Should add MAX_RETRIES_EXCEEDED event
        assert any(e.code == "MAX_RETRIES_EXCEEDED" for e in result["validation_events"])

    def test_no_approved_topics_error(self, sample_state):
        """Missing approved_topics returns schema violation."""
        sample_state["approved_topics"] = None
        result = validate_node(sample_state)

        events = result["validation_events"]
        assert len(events) == 1
        assert events[0].code == SCHEMA_VIOLATION

    def test_cycle_with_non_prerequisite_edges_ignored(self, sample_state, sample_topics):
        """Cycles only checked for prerequisite type."""
        sample_state["approved_topics"] = sample_topics
        sample_state["relationships"] = [
            Relationship(from_id="python", to_id="django", type="related"),
            Relationship(from_id="django", to_id="flask", type="related"),
            Relationship(from_id="flask", to_id="python", type="related"),
        ]
        result = validate_node(sample_state)

        events = result["validation_events"]
        cycle_events = [e for e in events if e.code == CYCLE_IN_PREREQUISITES]
        assert len(cycle_events) == 0  # No cycle error for 'related' type


class TestFormatFeedback:
    def test_no_errors_returns_empty_string(self):
        """No error events means empty feedback."""
        events = [
            ValidationEvent(
                stage="validate",
                severity="warning",
                code=ORPHAN_TOPIC,
                message="Topic not referenced",
            )
        ]
        feedback = format_feedback(events)
        assert feedback == ""

    def test_formats_errors_by_code(self):
        """Groups errors by code for readability."""
        events = [
            ValidationEvent(
                stage="validate",
                severity="error",
                code=DANGLING_FROM_REF,
                message="Bad from ref: nonexistent1",
            ),
            ValidationEvent(
                stage="validate",
                severity="error",
                code=DANGLING_FROM_REF,
                message="Bad from ref: nonexistent2",
            ),
            ValidationEvent(
                stage="validate",
                severity="error",
                code=SELF_LOOP,
                message="Self-loop on python",
            ),
        ]
        feedback = format_feedback(events)

        assert "DANGLING_FROM_REF" in feedback
        assert "2 occurrence(s)" in feedback
        assert "SELF_LOOP" in feedback
        assert "1 occurrence(s)" in feedback

    def test_limits_errors_per_code(self):
        """Limits output to 5 errors per code to avoid overwhelming."""
        events = [
            ValidationEvent(
                stage="validate",
                severity="error",
                code=DANGLING_FROM_REF,
                message=f"Bad from ref: bad{i}",
            )
            for i in range(10)
        ]
        feedback = format_feedback(events)

        assert "and 5 more" in feedback
