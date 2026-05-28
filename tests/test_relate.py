"""Tests for relate stage."""

import pytest

from skillpipeline.llm import FakeLLMClient, ToolCall
from skillpipeline.models import Relationship, Topic, ValidationEvent
from skillpipeline.relate import (
    relate_topics,
    validate_relate_response,
)
from skillpipeline.retry import MAX_RELATE_RETRIES, format_feedback


@pytest.fixture
def sample_topics():
    """Standard set of topics for testing."""
    return [
        Topic(
            id="python",
            name="Python",
            description="A programming language",
            category="backend",
            difficulty="beginner",
            source_section_id="section-0",
        ),
        Topic(
            id="django",
            name="Django",
            description="A web framework",
            category="backend",
            difficulty="intermediate",
            source_section_id="section-1",
        ),
        Topic(
            id="flask",
            name="Flask",
            description="Another web framework",
            category="backend",
            difficulty="intermediate",
            source_section_id="section-2",
        ),
    ]


@pytest.fixture
def sample_client():
    """Create a fake LLM client for testing."""
    return FakeLLMClient()


class TestValidateRelateResponse:
    def test_valid_response(self, sample_client):
        """Valid relationship response passes validation."""
        tool_calls = [
            {
                "id": "toolu_123",
                "name": "record_relationships",
                "input": {
                    "relationships": [
                        {
                            "from_id": "python",
                            "to_id": "django",
                            "type": "prerequisite",
                            "rationale": "Django requires Python",
                        }
                    ]
                },
            }
        ]
        result = validate_relate_response(
            [ToolCall(name=t["name"], input=t["input"], id=t.get("id")) for t in tool_calls]
        )
        assert len(result) == 1
        assert result[0].from_id == "python"
        assert result[0].to_id == "django"
        assert result[0].type == "prerequisite"

    def test_missing_tool_use(self, sample_client):
        """Text-only response triggers MISSING_TOOL_USE."""
        from skillpipeline.relate import RelateValidationError

        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response([])
        assert exc_info.value.code == "MISSING_TOOL_USE"

    def test_multiple_tools(self, sample_client):
        """Multiple tool_use blocks triggers MULTIPLE_TOOLS."""
        from skillpipeline.relate import RelateValidationError

        tool_calls = [
            ToolCall(name="record_relationships", input={"relationships": []}, id="toolu_1"),
            ToolCall(name="record_relationships", input={"relationships": []}, id="toolu_2"),
        ]
        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response(tool_calls)
        assert exc_info.value.code == "MULTIPLE_TOOLS"

    def test_wrong_tool(self, sample_client):
        """Wrong tool name triggers WRONG_TOOL."""
        from skillpipeline.relate import RelateValidationError

        tool_calls = [
            ToolCall(name="wrong_tool", input={"relationships": []}, id="toolu_1")
        ]
        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response(tool_calls)
        assert exc_info.value.code == "WRONG_TOOL"

    def test_missing_relationships_field(self, sample_client):
        """Missing relationships field triggers error."""
        from skillpipeline.relate import RelateValidationError

        tool_calls = [ToolCall(name="record_relationships", input={}, id="toolu_1")]
        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response(tool_calls)
        assert exc_info.value.code == "MISSING_RELATIONSHIPS"

    def test_relationships_not_array(self, sample_client):
        """relationships not being an array triggers error."""
        from skillpipeline.relate import RelateValidationError

        tool_calls = [
            ToolCall(name="record_relationships", input={"relationships": "not_an_array"}, id="toolu_1")
        ]
        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response(tool_calls)
        assert exc_info.value.code == "RELATIONSHIPS_NOT_ARRAY"

    def test_invalid_relationship_schema(self, sample_client):
        """Invalid relationship data triggers error."""
        from skillpipeline.relate import RelateValidationError

        tool_calls = [
            ToolCall(
                name="record_relationships",
                input={"relationships": [{"from_id": "python"}]},  # Missing to_id and type
                id="toolu_1",
            )
        ]
        with pytest.raises(RelateValidationError) as exc_info:
            validate_relate_response(tool_calls)
        assert exc_info.value.code == "INVALID_RELATIONSHIP"


class TestFormatFeedback:
    def test_basic_feedback(self):
        """Formats basic error message into feedback using shared helper."""
        from skillpipeline.relate import RelateValidationError

        error = RelateValidationError("TEST_CODE", "Test error message")
        feedback = format_feedback(error.message)

        assert "Test error message" in feedback
        assert "ID-format" in feedback
        assert "reference-integrity" in feedback


class TestRelateTopics:
    @pytest.mark.asyncio
    async def test_successful_extraction(self, sample_topics, sample_client):
        """Successful relationship extraction."""
        response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {
                    "relationships": [
                        {
                            "from_id": "python",
                            "to_id": "django",
                            "type": "prerequisite",
                            "rationale": "Django requires Python",
                        }
                    ]
                },
            },
            "input_tokens": 100,
            "output_tokens": 50,
        }
        sample_client.set_responses([response])

        system_prompt = "You are a relater."
        user_template = "# Topics\n{topics}\n{feedback}"

        relationships, attempts, events = await relate_topics(
            approved_topics=sample_topics,
            llm_client=sample_client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert len(relationships) == 1
        assert attempts == 1
        assert any(e.code == "RELATE_OK" for e in events)

    @pytest.mark.asyncio
    async def test_retry_then_success(self, sample_topics, sample_client):
        """First response fails validation, second succeeds."""
        bad_response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {
                    "relationships": [
                        {
                            "from_id": "python",
                            # Missing to_id and type
                        }
                    ]
                },
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }
        good_response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {
                    "relationships": [
                        {
                            "from_id": "python",
                            "to_id": "django",
                            "type": "prerequisite",
                            "rationale": "Django requires Python",
                        }
                    ]
                },
            },
            "input_tokens": 100,
            "output_tokens": 50,
        }
        sample_client.set_responses([bad_response, good_response])

        system_prompt = "You are a relater."
        user_template = "# Topics\n{topics}\n{feedback}"

        relationships, attempts, events = await relate_topics(
            approved_topics=sample_topics,
            llm_client=sample_client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert len(relationships) == 1
        assert attempts == 2
        assert any(e.code == "RELATE_RECOVERED" for e in events)

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, sample_topics, sample_client):
        """All responses fail validation; returns empty list."""
        bad_response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {"relationships": "not_an_array"},
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }
        sample_client.set_responses([bad_response] * 10)

        system_prompt = "You are a relater."
        user_template = "# Topics\n{topics}\n{feedback}"

        relationships, attempts, events = await relate_topics(
            approved_topics=sample_topics,
            llm_client=sample_client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert len(relationships) == 0
        assert attempts == MAX_RELATE_RETRIES
        assert any(e.code == "MAX_RETRIES_EXCEEDED" for e in events)
        assert any(e.flagged for e in events)

    @pytest.mark.asyncio
    async def test_feedback_included_on_retry(self, sample_topics, sample_client):
        """Feedback from previous attempt is included in next prompt."""
        bad_response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {"relationships": "not_an_array"},
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }
        good_response = {
            "tool_use": {
                "name": "record_relationships",
                "input": {
                    "relationships": [
                        {
                            "from_id": "python",
                            "to_id": "django",
                            "type": "prerequisite",
                        }
                    ]
                },
            },
            "input_tokens": 100,
            "output_tokens": 50,
        }
        sample_client.set_responses([bad_response, good_response])

        system_prompt = "You are a relater."
        user_template = "# Topics\n{topics}\n{feedback}"

        # First call to capture the feedback that would be generated
        _, _, first_events = await relate_topics(
            approved_topics=sample_topics,
            llm_client=sample_client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        # Get the error message from the first attempt
        error_msg = [e.message for e in first_events if e.code == "RELATIONSHIPS_NOT_ARRAY"][0]

        # Second call with explicit feedback - reset client to only return good response
        sample_client.set_responses([good_response])
        feedback = f"A previous attempt failed: {error_msg}"
        relationships, attempts, events = await relate_topics(
            approved_topics=sample_topics,
            llm_client=sample_client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
            feedback=feedback,
        )

        assert len(relationships) == 1
        assert attempts == 1  # Only one attempt since we provided feedback on a fresh call
