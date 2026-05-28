"""Tests for graph module - sub-step 12b (conditional edges)."""

import pytest

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

