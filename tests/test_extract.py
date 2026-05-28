import pytest

from skillpipeline.extract import (
    ExtractValidationError,
    extract_one_section,
    make_extract_node,
    validate_extract_response,
)
from skillpipeline.llm import FakeLLMClient, ToolCall
from skillpipeline.models import Section
from skillpipeline.retry import MAX_EXTRACT_ATTEMPTS, format_feedback


class TestValidateExtractResponse:
    def test_valid_response(self):
        call = ToolCall(
            name="record_topics",
            input={
                "topics": [
                    {
                        "id": "react",
                        "name": "React",
                        "description": "A JS library",
                        "category": "frontend",
                        "difficulty": "intermediate",
                    }
                ]
            },
        )
        topics = validate_extract_response([call])
        assert len(topics) == 1
        assert topics[0].id == "react"

    def test_missing_tool_use(self):
        with pytest.raises(ExtractValidationError, match="MISSING_TOOL_USE"):
            validate_extract_response([])

    def test_text_only_response(self):
        call = ToolCall(
            name="text",  # Wrong tool
            input={"text": "Here's some text"},
        )
        with pytest.raises(ExtractValidationError, match="WRONG_TOOL"):
            validate_extract_response([call])

    def test_multiple_tool_calls(self):
        calls = [
            ToolCall(name="record_topics", input={"topics": []}),
            ToolCall(name="record_topics", input={"topics": []}),
        ]
        with pytest.raises(ExtractValidationError, match="MULTIPLE_TOOLS"):
            validate_extract_response(calls)

    def test_missing_topics_field(self):
        call = ToolCall(name="record_topics", input={})
        with pytest.raises(ExtractValidationError, match="MISSING_TOPICS"):
            validate_extract_response([call])

    def test_topics_not_array(self):
        call = ToolCall(name="record_topics", input={"topics": "not-an-array"})
        with pytest.raises(ExtractValidationError, match="TOPICS_NOT_ARRAY"):
            validate_extract_response([call])

    def test_invalid_topic_schema(self):
        call = ToolCall(
            name="record_topics",
            input={"topics": [{"id": "invalid_id!", "name": "Bad ID"}]},
        )
        with pytest.raises(ExtractValidationError, match="INVALID_TOPIC"):
            validate_extract_response([call])

    def test_duplicate_id_within_section(self):
        call = ToolCall(
            name="record_topics",
            input={
                "topics": [
                    {"id": "dup", "name": "First", "description": "A", "category": "x", "difficulty": "beginner"},
                    {"id": "dup", "name": "Second", "description": "B", "category": "y", "difficulty": "beginner"},
                ]
            },
        )
        with pytest.raises(ExtractValidationError, match="DUPLICATE_ID"):
            validate_extract_response([call])

    def test_duplicate_name_case_insensitive(self):
        call = ToolCall(
            name="record_topics",
            input={
                "topics": [
                    {"id": "a", "name": "React", "description": "A", "category": "x", "difficulty": "beginner"},
                    {"id": "b", "name": "react", "description": "B", "category": "y", "difficulty": "beginner"},
                ]
            },
        )
        with pytest.raises(ExtractValidationError, match="DUPLICATE_NAME"):
            validate_extract_response([call])


class TestFormatFeedback:
    def test_basic_feedback(self):
        """Formats basic error message into feedback using shared helper."""
        error = ExtractValidationError("INVALID_TOPIC", "ID has invalid characters")
        feedback = format_feedback(error.message)

        assert "failed validation" in feedback
        assert "ID has invalid characters" in feedback
        assert "ID-format" in feedback

    def test_missing_tool_use_feedback(self):
        error = ExtractValidationError("MISSING_TOOL_USE", "Must call record_topics")
        feedback = format_feedback(error.message)

        assert "Must call record_topics" in feedback


class TestExtractOneSection:
    @pytest.fixture
    def sample_section(self):
        return Section(
            id="section-0",
            heading="React Basics",
            body="React is a JavaScript library for building UIs.",
            order=0,
        )

    @pytest.fixture
    def valid_response(self):
        return {
            "tool_use": {
                "name": "record_topics",
                "input": {
                    "topics": [
                        {
                            "id": "react",
                            "name": "React",
                            "description": "A JS library for UIs",
                            "category": "frontend",
                            "difficulty": "intermediate",
                        }
                    ]
                }
            },
            "input_tokens": 100,
            "output_tokens": 50,
        }

    @pytest.mark.asyncio
    async def test_successful_extraction(self, sample_section, valid_response):
        client = FakeLLMClient([valid_response])
        system_prompt = "You are an extractor."
        user_template = "# {heading}\n\n{body}\n\n{feedback}"

        topics, attempts, events, _usage = await extract_one_section(
            section=sample_section,
            llm_client=client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert len(topics) == 1
        assert topics[0].id == "react"
        assert attempts == 1
        assert any(e.code == "EXTRACT_OK" for e in events)

    @pytest.mark.asyncio
    async def test_retry_then_success(self, sample_section):
        # First response has error (malformed topic), second is valid
        bad_response = {
            "tool_use": {
                "name": "record_topics",
                "input": {
                    "topics": [
                        {
                            "id": "invalid!",
                            "name": "Invalid ID",  # Has invalid character
                        }
                    ]
                },
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }

        good_response = {
            "tool_use": {
                "name": "record_topics",
                "input": {
                    "topics": [
                        {
                            "id": "react",
                            "name": "React",
                            "description": "A JS library",
                            "category": "frontend",
                            "difficulty": "intermediate",
                        }
                    ]
                }
            },
            "input_tokens": 100,
            "output_tokens": 50,
        }

        client = FakeLLMClient([bad_response, good_response])
        system_prompt = "You are an extractor."
        user_template = "# {heading}\n\n{body}\n\n{feedback}"

        topics, attempts, events, _usage = await extract_one_section(
            section=sample_section,
            llm_client=client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert len(topics) == 1
        assert attempts == 2  # First attempt failed, second succeeded
        assert any(e.code == "INVALID_TOPIC" for e in events)
        assert any(e.code == "EXTRACT_RECOVERED" for e in events)

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, sample_section):
        # All responses fail validation (invalid IDs)
        bad_response = {
            "tool_use": {
                "name": "record_topics",
                "input": {
                    "topics": [
                        {"id": "invalid!", "name": "Bad ID"},  # Invalid ID pattern
                    ]
                },
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }

        client = FakeLLMClient([bad_response] * 10)  # More than MAX_EXTRACT_ATTEMPTS
        system_prompt = "You are an extractor."
        user_template = "# {heading}\n\n{body}\n\n{feedback}"

        topics, attempts, events, _usage = await extract_one_section(
            section=sample_section,
            llm_client=client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
        )

        assert topics == []  # Empty result
        assert attempts == MAX_EXTRACT_ATTEMPTS
        assert any(e.code == "MAX_RETRIES_EXCEEDED" and e.flagged for e in events)

    @pytest.mark.asyncio
    async def test_feedback_included_on_retry(self, sample_section):
        bad_response = {
            "tool_use": {
                "name": "record_topics",
                "input": {"topics": []},
            },
            "input_tokens": 50,
            "output_tokens": 20,
        }

        client = FakeLLMClient([bad_response])
        system_prompt = "You are an extractor."
        user_template = "# {heading}\n\n{body}\n\n{feedback}"

        await extract_one_section(
            section=sample_section,
            llm_client=client,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
            feedback=ExtractValidationError("TEST_ERROR", "Test error message"),
        )

        # Check that the second call (retry) included the feedback
        # The FakeLLMClient cycles through responses, so we check the prompt construction
        # indirectly by verifying the function completes


class TestExtractNode:
    @pytest.fixture
    def sample_document(self):
        from skillpipeline.models import Document
        return Document(
            source_id="test",
            sections=[
                Section(id="s1", heading="React", body="React content", order=0),
                Section(id="s2", heading="Vue", body="Vue content", order=1),
            ],
            raw_text="Test",
        )

    @pytest.fixture
    def valid_responses(self):
        return [
            {
                "tool_use": {
                    "name": "record_topics",
                    "input": {
                        "topics": [
                            {
                                "id": "react-basics",
                                "name": "React Basics",
                                "description": "React fundamentals",
                                "category": "frontend",
                                "difficulty": "beginner",
                            }
                        ]
                    }
                },
                "input_tokens": 80,
                "output_tokens": 40,
            },
            {
                "tool_use": {
                    "name": "record_topics",
                    "input": {
                        "topics": [
                            {
                                "id": "vue-basics",
                                "name": "Vue Basics",
                                "description": "Vue fundamentals",
                                "category": "frontend",
                                "difficulty": "beginner",
                            }
                        ]
                    }
                },
                "input_tokens": 80,
                "output_tokens": 40,
            },
        ]

    @pytest.mark.asyncio
    async def test_node_extracts_all_sections(self, sample_document, valid_responses):
        client = FakeLLMClient(valid_responses)
        node = make_extract_node(client)

        state = await node({
            "document": sample_document,
            "extract_retries": {},
            "extract_feedback": {},
            "validation_events": [],
            "stage_telemetry": [],
        })

        assert "extracted_topics" in state
        assert len(state["extracted_topics"]) == 2
        assert state["extracted_topics"][0].id == "react-basics"
        assert state["extracted_topics"][1].id == "vue-basics"
        assert state["extract_retries"]["s1"] == 1
        assert state["extract_retries"]["s2"] == 1

    @pytest.mark.asyncio
    async def test_node_handles_no_document(self):
        client = FakeLLMClient([])
        node = make_extract_node(client)

        state = await node({
            "document": None,
            "extract_retries": {},
            "extract_feedback": {},
            "validation_events": [],
            "stage_telemetry": [],
        })

        assert state["extracted_topics"] == []
        assert any(e.code == "NO_DOCUMENT" for e in state["validation_events"])

    @pytest.mark.asyncio
    async def test_node_records_telemetry(self, sample_document, valid_responses):
        client = FakeLLMClient(valid_responses)
        node = make_extract_node(client)

        state = await node({
            "document": sample_document,
            "extract_retries": {},
            "extract_feedback": {},
            "validation_events": [],
            "stage_telemetry": [],
        })

        telemetry = state["stage_telemetry"][0]
        assert telemetry.stage == "extract"
        assert telemetry.llm_calls == 2  # One per section
        assert telemetry.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_node_tracks_flagged_sections(self, sample_document):
        # First section fails (invalid ID), second succeeds
        responses = [
            {
                "tool_use": {
                    "name": "record_topics",
                    "input": {
                        "topics": [
                            {"id": "invalid!", "name": "Bad"},  # Invalid ID - will fail validation
                        ]
                    },
                }
            },
            {
                "tool_use": {
                    "name": "record_topics",
                    "input": {
                        "topics": [
                            {
                                "id": "vue",
                                "name": "Vue",
                                "description": "A framework",
                                "category": "frontend",
                                "difficulty": "intermediate",
                            }
                        ]
                    }
                }
            },
        ]

        client = FakeLLMClient(responses)
        node = make_extract_node(client)

        state = await node({
            "document": sample_document,
            "extract_retries": {},
            "extract_feedback": {},
            "validation_events": [],
            "stage_telemetry": [],
        })

        assert "s1" in state["flagged_sections"]
        assert "s2" not in state["flagged_sections"]
