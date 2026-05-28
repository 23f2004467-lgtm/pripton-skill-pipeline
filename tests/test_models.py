import pytest
from pydantic import ValidationError

from skillpipeline.models import (
    Document,
    Relationship,
    RunMetadata,
    Section,
    SkillMap,
    StageTelemetry,
    Topic,
    ValidationEvent,
)


class TestTopic:
    def test_valid_topic(self):
        t = Topic(
            id="react-hooks",
            name="React Hooks",
            description="A feature for using state and lifecycle in functional components",
            category="frontend",
            difficulty="beginner",
        )
        assert t.id == "react-hooks"
        assert t.difficulty == "beginner"

    def test_id_must_match_pattern(self):
        with pytest.raises(ValidationError, match="pattern"):
            Topic(
                id="React_Hooks",  # underscores not allowed, only lowercase letters, numbers, hyphens
                name="React Hooks",
                description="A feature",
                category="frontend",
                difficulty="beginner",
            )

    def test_id_must_be_lowercase_hyphens(self):
        with pytest.raises(ValidationError, match="pattern"):
            Topic(
                id="ReactHooks",  # uppercase not allowed
                name="React Hooks",
                description="A feature",
                category="frontend",
                difficulty="beginner",
            )

    def test_name_min_length(self):
        with pytest.raises(ValidationError, match="at least 1 character"):
            Topic(
                id="empty",
                name="",  # empty name
                description="A feature",
                category="frontend",
                difficulty="beginner",
            )

    def test_name_max_length(self):
        with pytest.raises(ValidationError, match="at most 120 characters"):
            Topic(
                id="long",
                name="x" * 121,  # max 120
                description="A feature",
                category="frontend",
                difficulty="beginner",
            )

    def test_description_bounds(self):
        # min length
        with pytest.raises(ValidationError, match="at least 1 character"):
            Topic(
                id="t",
                name="Topic",
                description="",  # empty
                category="cat",
                difficulty="beginner",
            )
        # max length
        with pytest.raises(ValidationError, match="at most 500 characters"):
            Topic(
                id="t",
                name="Topic",
                description="x" * 501,  # max 500
                category="cat",
                difficulty="beginner",
            )

    def test_category_bounds(self):
        with pytest.raises(ValidationError, match="at least 1 character"):
            Topic(
                id="t",
                name="Topic",
                description="A feature",
                category="",  # empty
                difficulty="beginner",
            )
        with pytest.raises(ValidationError, match="at most 80 characters"):
            Topic(
                id="t",
                name="Topic",
                description="A feature",
                category="x" * 81,  # max 80
                difficulty="beginner",
            )

    def test_difficulty_must_be_valid(self):
        with pytest.raises(ValidationError):
            Topic(
                id="t",
                name="Topic",
                description="A feature",
                category="cat",
                difficulty="invalid",  # must be beginner/intermediate/advanced
            )

    def test_source_section_id_optional(self):
        t = Topic(
            id="t",
            name="Topic",
            description="A feature",
            category="cat",
            difficulty="beginner",
            source_section_id="section-0",
        )
        assert t.source_section_id == "section-0"


class TestRelationship:
    def test_valid_relationship(self):
        r = Relationship(
            from_id="javascript",
            to_id="react",
            type="prerequisite",
            rationale="React requires JS knowledge",
        )
        assert r.from_id == "javascript"
        assert r.to_id == "react"
        assert r.type == "prerequisite"

    def test_self_loop_rejected(self):
        with pytest.raises(ValidationError, match="self-referential"):
            Relationship(
                from_id="topic",
                to_id="topic",  # same as from_id
                type="prerequisite",
            )

    def test_rationale_optional(self):
        r = Relationship(
            from_id="a",
            to_id="b",
            type="related",
        )
        assert r.rationale is None

    def test_type_must_be_valid(self):
        with pytest.raises(ValidationError):
            Relationship(
                from_id="a",
                to_id="b",
                type="invalid",  # must be prerequisite/related/subtopic
            )


class TestSection:
    def test_valid_section(self):
        s = Section(
            id="section-0",
            heading="Introduction",
            body="This is the intro",
            order=0,
        )
        assert s.id == "section-0"
        assert s.heading == "Introduction"

    def test_heading_optional(self):
        s = Section(
            id="section-0",
            heading=None,
            body="Body text",
            order=0,
        )
        assert s.heading is None


class TestDocument:
    def test_valid_document(self):
        doc = Document(
            source_id="abc123",
            source_path="test.md",
            raw_text="# Test\n\nContent",
            sections=[
                Section(id="s0", heading="Test", body="Content", order=0)
            ],
        )
        assert doc.source_id == "abc123"
        assert len(doc.sections) == 1


class TestValidationEvent:
    def test_valid_validation_event(self):
        e = ValidationEvent(
            stage="extract",
            severity="error",
            code="MALFORMED_OUTPUT",
            message="Failed to parse",
            retry_number=1,
            flagged=True,
        )
        assert e.stage == "extract"
        assert e.flagged is True

    def test_defaults(self):
        e = ValidationEvent(
            stage="relate",
            severity="warning",
            code="CYCLE_DETECTED",
            message="Cycle found",
        )
        assert e.retry_number == 0
        assert e.flagged is False


class TestStageTelemetry:
    def test_valid_telemetry(self):
        t = StageTelemetry(
            stage="extract",
            started_at="2024-01-01T00:00:00Z",
            ended_at="2024-01-01T00:00:05Z",
            duration_ms=5000,
            llm_calls=3,
            input_tokens=1000,
            output_tokens=500,
            estimated_cost_usd=0.01,
        )
        assert t.stage == "extract"
        assert t.duration_ms == 5000


class TestRunMetadata:
    def test_valid_metadata(self):
        m = RunMetadata(
            thread_id="run_123",
            source_id="abc123",
            started_at="2024-01-01T00:00:00Z",
            status="running",
        )
        assert m.thread_id == "run_123"
        assert m.status == "running"

    def test_status_is_required(self):
        """Status must be provided explicitly; no default."""
        m = RunMetadata(
            thread_id="run_123",
            source_id="abc123",
            started_at="2024-01-01T00:00:00Z",
            status="running",
        )
        assert m.status == "running"


class TestSkillMap:
    def test_valid_skill_map(self):
        sm = SkillMap(
            source_id="abc123",
            topics=[
                Topic(
                    id="react",
                    name="React",
                    description="A JS library",
                    category="frontend",
                    difficulty="intermediate",
                )
            ],
            relationships=[
                Relationship(
                    from_id="javascript",
                    to_id="react",
                    type="prerequisite",
                )
            ],
            metadata=RunMetadata(
                thread_id="run_123",
                source_id="abc123",
                started_at="2024-01-01T00:00:00Z",
                status="complete",
            ),
        )
        assert len(sm.topics) == 1
        assert len(sm.relationships) == 1
        assert sm.metadata.status == "complete"
