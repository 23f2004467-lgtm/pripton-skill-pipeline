"""Tests for human_review stage."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skillpipeline.human_review import (
    _format_review_file_content,
    _should_interrupt,
    human_review_node,
    validate_review_topics,
)
from skillpipeline.models import Topic, ValidationEvent


class TestShouldInterrupt:
    """Test interrupt condition logic."""

    def test_no_interrupt_no_retries_no_flag(self):
        """No interrupt when no retries and no always-review flag."""
        state = {
            "extract_retries": {},
            "always_review": False,
        }
        assert not _should_interrupt(state)

    def test_no_interrupt_on_first_try_success(self):
        """A value of 1 means one attempt (no retry), so no interrupt."""
        state = {
            "extract_retries": {"section-0": 1, "section-1": 1},
            "always_review": False,
        }
        assert not _should_interrupt(state)

    def test_interrupt_on_any_retry(self):
        """Interrupt when any section needed at least one retry (attempts > 1)."""
        state = {
            "extract_retries": {"section-0": 2, "section-1": 1},
            "always_review": False,
        }
        assert _should_interrupt(state)

    def test_interrupt_on_always_review_flag(self):
        """Interrupt when always_review flag is True, even with no retries."""
        state = {
            "extract_retries": {},
            "always_review": True,
        }
        assert _should_interrupt(state)

    def test_interrupt_on_both_conditions(self):
        """Interrupt when both conditions are true."""
        state = {
            "extract_retries": {"section-0": 2},
            "always_review": True,
        }
        assert _should_interrupt(state)


class TestFormatReviewFileContent:
    """Test review file content formatting."""

    def test_includes_instructions(self):
        """Review file includes editing instructions."""
        topics = [
            Topic(
                id="react",
                name="React",
                description="A JS library",
                category="frontend",
                difficulty="intermediate",
                source_section_id="section-0",
            )
        ]
        content = _format_review_file_content(topics, [])
        data = json.loads(content)

        assert "_instructions" in data
        assert "purpose" in data["_instructions"]
        assert "how_to_edit" in data["_instructions"]
        assert "validation_rules" in data["_instructions"]

    def test_includes_merge_events(self):
        """Review file includes merge-related validation events."""
        topics = [Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")]
        events = [
            ValidationEvent(stage="merge", severity="info", code="DUPLICATE_TOPIC_MERGED", message="Test message"),
            ValidationEvent(stage="extract", severity="warning", code="EXTRACT_RECOVERED", message="Another message"),
        ]
        content = _format_review_file_content(topics, events)
        data = json.loads(content)

        assert "_merge_events" in data
        assert len(data["_merge_events"]) == 2
        assert data["_merge_events"][0]["code"] == "DUPLICATE_TOPIC_MERGED"
        assert data["_merge_events"][1]["code"] == "EXTRACT_RECOVERED"

    def test_includes_topics(self):
        """Review file includes the actual topic data."""
        topics = [
            Topic(
                id="python",
                name="Python",
                description="A language",
                category="backend",
                difficulty="beginner",
                source_section_id="section-0",
            ),
            Topic(
                id="django",
                name="Django",
                description="A framework",
                category="backend",
                difficulty="intermediate",
                source_section_id="section-1",
            ),
        ]
        content = _format_review_file_content(topics, [])
        data = json.loads(content)

        assert "topics" in data
        assert len(data["topics"]) == 2
        assert data["topics"][0]["id"] == "python"
        assert data["topics"][1]["id"] == "django"


class TestValidateReviewTopics:
    """Test review file validation on resume."""

    def test_valid_topics_list(self):
        """Valid topics list passes validation."""
        topics_data = [
            {
                "id": "react",
                "name": "React",
                "description": "A JS library",
                "category": "frontend",
                "difficulty": "intermediate",
            }
        ]
        topics = validate_review_topics(topics_data)
        assert len(topics) == 1
        assert topics[0].id == "react"

    def test_valid_full_format(self):
        """Full format with _instructions and topics passes validation."""
        topics_data = {
            "_instructions": {"purpose": "test"},
            "_merge_events": [],
            "topics": [
                {
                    "id": "python",
                    "name": "Python",
                    "description": "A language",
                    "category": "backend",
                    "difficulty": "beginner",
                }
            ],
        }
        topics = validate_review_topics(topics_data)
        assert len(topics) == 1
        assert topics[0].id == "python"

    def test_missing_topics_array_raises(self):
        """Missing topics array raises ValueError."""
        with pytest.raises(ValueError, match="must contain a 'topics' array"):
            validate_review_topics({"_instructions": {"purpose": "test"}})

    def test_topics_not_array_raises(self):
        """topics not being an array raises ValueError."""
        with pytest.raises(ValueError, match="'topics' must be an array"):
            validate_review_topics({"topics": "not-an-array"})

    def test_invalid_topic_raises(self):
        """Invalid topic data raises ValueError with index."""
        topics_data = [
            {
                "id": "Invalid ID!",  # Has invalid characters
                "name": "Test",
                "description": "Test",
                "category": "test",
                "difficulty": "beginner",
            }
        ]
        with pytest.raises(ValueError, match="Topic at index 0"):
            validate_review_topics(topics_data)

    def test_duplicate_ids_raises(self):
        """Duplicate topic IDs raise ValueError."""
        topics_data = [
            {
                "id": "duplicate",
                "name": "First",
                "description": "First",
                "category": "test",
                "difficulty": "beginner",
            },
            {
                "id": "duplicate",
                "name": "Second",
                "description": "Second",
                "category": "test",
                "difficulty": "beginner",
            },
        ]
        with pytest.raises(ValueError, match="Duplicate topic id: 'duplicate'"):
            validate_review_topics(topics_data)

    def test_neither_list_nor_dict_raises(self):
        """Invalid root type raises ValueError."""
        with pytest.raises(ValueError, match="must contain a 'topics' array or be a list"):
            validate_review_topics("invalid")


class TestHumanReviewNode:
    """Test the human_review node function."""

    @pytest.mark.asyncio
    async def test_skip_interrupt_no_retries(self, tmp_path):
        """Skip interrupt when no retries - topics pass through."""
        topics = [
            Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")
        ]
        state = {
            "merged_topics": topics,
            "extract_retries": {},
            "always_review": False,
            "thread_id": "test-run",
            "validation_events": [],
        }

        result = await human_review_node(state)

        assert result["approved_topics"] == topics
        assert "awaiting_review" not in result

    @pytest.mark.asyncio
    async def test_trigger_interrupt_on_retries(self, tmp_path):
        """Trigger interrupt when retries occurred."""
        import os

        topics = [
            Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")
        ]
        state = {
            "merged_topics": topics,
            "extract_retries": {"section-0": 2},  # 2 attempts = one retry fired
            "always_review": False,
            "thread_id": "test-run",
            "validation_events": [],
        }

        # Temporarily change to tmp_path for runs directory
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            # Mock interrupt() to avoid needing LangGraph context
            with patch("skillpipeline.human_review.interrupt", return_value=topics):
                result = await human_review_node(state)

                # After mock, interrupt returns the topics (simulating resume)
                assert result["approved_topics"] == topics

                # Check file was written BEFORE interrupt was called
                review_file = Path(tmp_path) / "runs" / "test-run" / "topics_for_review.json"
                assert review_file.exists()

                content = review_file.read_text()
                data = json.loads(content)
                assert "topics" in data
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_trigger_interrupt_on_always_review(self, tmp_path):
        """Trigger interrupt when always_review flag is set."""
        import os

        topics = [
            Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")
        ]
        state = {
            "merged_topics": topics,
            "extract_retries": {},
            "always_review": True,
            "thread_id": "test-run",
            "validation_events": [],
        }

        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            # Mock interrupt() to avoid needing LangGraph context
            with patch("skillpipeline.human_review.interrupt", return_value=topics):
                result = await human_review_node(state)

                # After mock, interrupt returns the topics (simulating resume)
                assert result["approved_topics"] == topics
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_empty_merged_topics(self, tmp_path):
        """Handle empty merged topics gracefully."""
        state = {
            "merged_topics": [],
            "extract_retries": {},
            "always_review": False,
            "thread_id": "test-run",
            "validation_events": [],
        }

        result = await human_review_node(state)
        assert result["approved_topics"] == []
