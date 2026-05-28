"""Retry-with-feedback helper for LLM validation retries.

This module provides the shared feedback prompt template and retry bounds
used by both extract and relate stages when retrying with validation errors.

See PLAN.md Section 6 for the retry specification.
"""

from __future__ import annotations


# Retry bounds (Section 6.2)
MAX_EXTRACT_ATTEMPTS: int = 3  # Per-section extract retries
MAX_RELATE_RETRIES: int = 3  # Relate retries (graph edge)


# Shared feedback prompt template (Section 6.1)
_FEEDBACK_TEMPLATE = """A previous attempt at this task failed validation with the following error(s):

{feedback}

Please correct these issues and try again. Pay particular attention to the
ID-format and reference-integrity rules."""


def format_feedback(feedback: str) -> str:
    """Format a validation error as feedback for the next LLM attempt.

    Args:
        feedback: The validation error message(s) to include.

    Returns:
        A formatted feedback string ready to inject into the next prompt.

    Example:
        >>> format_feedback("Topic ID 'Foo Bar' does not match pattern")
        "A previous attempt at this task failed validation with the following error(s):\\n\\n
        Topic ID 'Foo Bar' does not match pattern\\n\\n
        Please correct these issues and try again. Pay particular attention to the
        ID-format and reference-integrity rules."
    """
    return _FEEDBACK_TEMPLATE.format(feedback=feedback)
