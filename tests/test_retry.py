"""Tests for retry helper module."""

import pytest

from skillpipeline.retry import (
    MAX_EXTRACT_ATTEMPTS,
    MAX_RELATE_RETRIES,
    format_feedback,
)


class TestRetryConstants:
    """Test retry bounds match PLAN.md Section 6.2."""

    def test_max_extract_attempts(self):
        """Per-section extract retries: max 3 attempts."""
        assert MAX_EXTRACT_ATTEMPTS == 3

    def test_max_relate_retries(self):
        """Relate retries: max 3 attempts."""
        assert MAX_RELATE_RETRIES == 3


class TestFormatFeedback:
    """Test shared feedback prompt template."""

    def test_single_error(self):
        """Format a single validation error message."""
        result = format_feedback("Topic ID 'Foo Bar' does not match pattern")
        assert "Topic ID 'Foo Bar' does not match pattern" in result
        assert "failed validation with the following error" in result
        assert "ID-format and reference-integrity rules" in result

    def test_multiple_errors_joined(self):
        """Format multiple error messages passed as a single string."""
        result = format_feedback(
            "Topic ID 'Foo Bar' does not match pattern\n"
            "Topic name is too long"
        )
        assert "Topic ID 'Foo Bar' does not match pattern" in result
        assert "Topic name is too long" in result

    def test_template_matches_spec(self):
        """Template matches PLAN.md Section 6.1 verbatim."""
        result = format_feedback("TEST_ERROR")

        # Check for the exact phrases from the spec
        assert "A previous attempt at this task failed validation with the following error(s):" in result
        assert "TEST_ERROR" in result
        assert "Please correct these issues and try again." in result
        assert "Pay particular attention to the" in result
        assert "ID-format and reference-integrity rules." in result

    def test_multiline_feedback_preserved(self):
        """Multiline error messages are preserved."""
        multiline = """Line 1: First error
Line 2: Second error
Line 3: Third error"""
        result = format_feedback(multiline)
        assert "Line 1: First error" in result
        assert "Line 2: Second error" in result
        assert "Line 3: Third error" in result

    def test_empty_feedback(self):
        """Even empty feedback gets wrapped in the template."""
        result = format_feedback("")
        assert "A previous attempt at this task failed validation with the following error(s):" in result
        assert "Please correct these issues and try again." in result
