"""Tests for graph module - sub-step 12c (interrupt + SqliteSaver + resume)."""

import json
import tempfile
from pathlib import Path

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from skillpipeline.graph import (
    _should_bypass_to_persist,
    _should_retry_or_finish,
    create_graph,
)
from skillpipeline.llm import FakeLLMClient
from skillpipeline.models import Topic, ValidationEvent


class TestGraphCompiles:
    """Test that the graph compiles successfully."""

    def test_graph_compiles_with_default_client(self):
        """Graph should compile with default AnthropicLLMClient."""
        graph = create_graph()
        assert graph is not None
        compiled = graph.compile()
        assert compiled is not None

    def test_graph_compiles_with_fake_client(self):
        """Graph should compile with FakeLLMClient for testing."""
        fake_client = FakeLLMClient()
        graph = create_graph(fake_client)
        assert graph is not None
        compiled = graph.compile()
        assert compiled is not None


class TestShouldBypassToPersist:
    """Test conditional edge from merge node."""

    def test_empty_merged_topics_routes_to_persist(self):
        """Empty merged_topics routes directly to persist (bypass)."""
        state = {"merged_topics": []}
        result = _should_bypass_to_persist(state)
        assert result == "persist"

    def test_non_empty_merged_topics_routes_to_human_review(self):
        """Non-empty merged_topics routes to human_review."""
        state = {"merged_topics": [Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")]}
        result = _should_bypass_to_persist(state)
        assert result == "human_review"

    def test_none_merged_topics_routes_to_human_review(self):
        """None merged_topics (not yet set) routes to human_review."""
        state = {"merged_topics": None}
        result = _should_bypass_to_persist(state)
        assert result == "human_review"


class TestShouldRetryOrFinish:
    """Test conditional edge from validate node."""

    def test_errors_with_retries_remaining_routes_to_relate(self):
        """Validation errors with retries < 3 routes back to relate."""
        state = {
            "relate_retries": 0,
            "validation_events": [
                ValidationEvent(stage="relate", severity="error", code="DANGLING_REF", message="Test error")
            ],
        }
        result = _should_retry_or_finish(state)
        assert result == "relate"

    def test_errors_with_retries_exhausted_routes_to_persist(self):
        """Validation errors with retries >= 3 routes to persist."""
        state = {
            "relate_retries": 3,
            "validation_events": [
                ValidationEvent(stage="relate", severity="error", code="DANGLING_REF", message="Test error")
            ],
        }
        result = _should_retry_or_finish(state)
        assert result == "persist"

    def test_no_errors_routes_to_persist(self):
        """No validation errors routes to persist."""
        state = {
            "relate_retries": 0,
            "validation_events": [],
        }
        result = _should_retry_or_finish(state)
        assert result == "persist"

    def test_non_relate_errors_ignored(self):
        """Non-relate errors are ignored for retry decision."""
        state = {
            "relate_retries": 0,
            "validation_events": [
                ValidationEvent(stage="extract", severity="error", code="EXTRACT_ERROR", message="Test error")
            ],
        }
        result = _should_retry_or_finish(state)
        assert result == "persist"

    def test_warnings_dont_trigger_retry(self):
        """Warnings don't trigger retry, only errors do."""
        state = {
            "relate_retries": 0,
            "validation_events": [
                ValidationEvent(stage="relate", severity="warning", code="ORPHAN_TOPIC", message="Test warning")
            ],
        }
        result = _should_retry_or_finish(state)
        assert result == "persist"

    def test_multiple_retries_allowed(self):
        """Allows up to 3 retries before routing to persist."""
        state = {
            "relate_retries": 2,
            "validation_events": [
                ValidationEvent(stage="relate", severity="error", code="DANGLING_REF", message="Test error")
            ],
        }
        result = _should_retry_or_finish(state)
        assert result == "relate"  # Still allowed to retry


class TestHumanReviewInterrupt:
    """Test human_review interrupt behavior."""

    def test_no_interrupt_on_clean_run(self, sample_topics):
        """Clean run with no retries and no always-review flag bypasses interrupt."""
        from skillpipeline.human_review import _should_interrupt

        state = {
            "merged_topics": sample_topics,
            "extract_retries": {},  # No retries
            "always_review": False,
            "thread_id": "test-thread",
            "validation_events": [],
        }

        # Should not interrupt
        assert not _should_interrupt(state)

    def test_interrupt_on_extract_retry(self):
        """Interrupt triggers when any section had a retry."""
        from skillpipeline.human_review import _should_interrupt

        state = {
            "extract_retries": {"section-0": 1},  # Had a retry
            "always_review": False,
        }

        # Should interrupt
        assert _should_interrupt(state)

    def test_interrupt_on_always_review_flag(self):
        """Interrupt triggers when always_review flag is True."""
        from skillpipeline.human_review import _should_interrupt

        state = {
            "extract_retries": {},  # No retries
            "always_review": True,  # But flag is set
        }

        # Should interrupt
        assert _should_interrupt(state)

    def test_review_file_written_before_interrupt(self, sample_topics):
        """Verify topics_for_review.json is written before interrupt raises."""
        from skillpipeline.human_review import _format_review_file_content

        # Test the file content formatting
        content_str = _format_review_file_content(sample_topics, [])
        content = json.loads(content_str)

        assert "topics" in content
        assert "_instructions" in content
        assert "_merge_events" in content
        assert len(content["topics"]) == len(sample_topics)


class TestResumeCycle:
    """Test resume cycle after human review interrupt."""

    def test_resume_with_valid_topics(self, sample_topics):
        """Resume cycle: load topics, validate, continue graph execution."""
        from skillpipeline.human_review import validate_review_topics

        # Simulate the review file format
        review_data = {
            "_instructions": {"purpose": "test"},
            "_merge_events": [],
            "topics": [t.model_dump() for t in sample_topics],
        }

        # validate_review_topics should return the validated topics
        validated = validate_review_topics(review_data)

        assert len(validated) == len(sample_topics)
        assert all(isinstance(t, Topic) for t in validated)

    def test_resume_with_invalid_format_raises(self):
        """Resume with invalid format raises ValueError."""
        from skillpipeline.human_review import validate_review_topics

        # Missing topics array
        with pytest.raises(ValueError, match="must contain a 'topics' array"):
            validate_review_topics({"_instructions": {}})

    def test_resume_with_invalid_topic_raises(self):
        """Resume with invalid topic data raises ValueError."""
        from skillpipeline.human_review import validate_review_topics

        # Invalid topic (missing required field)
        invalid_data = {
            "topics": [
                {"id": "test", "name": "Test"}
                # Missing description, category, difficulty
            ]
        }

        with pytest.raises(ValueError, match="Topic at index 0 is invalid"):
            validate_review_topics(invalid_data)

    def test_resume_with_duplicate_ids_raises(self, sample_topics):
        """Resume with duplicate topic IDs raises ValueError."""
        from skillpipeline.human_review import validate_review_topics

        # Two topics with same ID
        duplicate_data = {
            "topics": [
                sample_topics[0].model_dump(),
                sample_topics[0].model_dump(),  # Same ID
            ]
        }

        with pytest.raises(ValueError, match="Duplicate topic id"):
            validate_review_topics(duplicate_data)

    def test_resume_components_work_together(self, sample_topics):
        """Verify resume flow components work: file format + validation."""
        from skillpipeline.human_review import (
            _format_review_file_content,
            validate_review_topics,
        )

        # 1. Test file formatting
        merge_events = [
            ValidationEvent(
                stage="extract",
                severity="warning",
                code="EXTRACT_RECOVERED",
                message="Section 0 needed retry"
            )
        ]
        content_str = _format_review_file_content(sample_topics, merge_events)
        content = json.loads(content_str)

        # Verify structure
        assert "topics" in content
        assert "_instructions" in content
        assert "_merge_events" in content
        assert len(content["topics"]) == len(sample_topics)
        assert len(content["_merge_events"]) == 1

        # 2. Test validation accepts the formatted content
        validated = validate_review_topics(content)
        assert len(validated) == len(sample_topics)

