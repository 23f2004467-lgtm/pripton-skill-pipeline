"""Tests for report generator."""

from datetime import UTC, datetime

from skillpipeline.models import (
    Relationship,
    RunMetadata,
    SkillMap,
    StageTelemetry,
    Topic,
    ValidationEvent,
)
from skillpipeline.report import generate_report


def test_generate_report_basic():
    """Basic report generation with minimal data."""
    topics = [
        Topic(
            id="python",
            name="Python",
            description="A programming language",
            category="backend",
            difficulty="beginner",
        ),
        Topic(
            id="django",
            name="Django",
            description="A web framework",
            category="backend",
            difficulty="intermediate",
        ),
    ]

    relationships = [
        Relationship(
            from_id="python",
            to_id="django",
            type="prerequisite",
            rationale="Django requires Python knowledge",
        )
    ]

    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="complete",
        total_cost_usd=0.0123,
        total_input_tokens=1000,
        total_output_tokens=500,
        stage_telemetry=[],
        validation_events=[],
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=topics,
        relationships=relationships,
        metadata=metadata,
    )

    source_text = "# Python\n\nPython is a programming language."

    html = generate_report(skill_map, source_text, "test.md")

    # Verify key elements are present
    assert "test-thread" in html
    assert "test.md" in html
    assert "complete" in html
    assert "$0.0123" in html
    assert "Python" in html
    assert "Django" in html


def test_generate_report_with_validation_events():
    """Report includes validation events table."""
    events = [
        ValidationEvent(
            stage="extract",
            severity="warning",
            code="EXTRACT_RECOVERED",
            message="Section 0 needed retry",
            retry_number=1,
        ),
        ValidationEvent(
            stage="relate",
            severity="error",
            code="DANGLING_REF",
            message="Invalid reference",
            retry_number=0,
        ),
    ]

    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="flagged",
        total_cost_usd=0.0123,
        total_input_tokens=1000,
        total_output_tokens=500,
        stage_telemetry=[],
        validation_events=events,
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=[],
        relationships=[],
        metadata=metadata,
    )

    html = generate_report(skill_map, "# Test", "test.md")

    assert "EXTRACT_RECOVERED" in html
    assert "DANGLING_REF" in html
    assert "severity-warning" in html
    assert "severity-error" in html
    assert "flagged" in html


def test_generate_report_with_stage_telemetry():
    """Report includes stage telemetry table."""
    telemetry = [
        StageTelemetry(
            stage="extract",
            started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
            ended_at=datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC).isoformat(),
            duration_ms=30000,
            llm_calls=3,
            input_tokens=1500,
            output_tokens=600,
            estimated_cost_usd=0.01,
        ),
        StageTelemetry(
            stage="relate",
            started_at=datetime(2024, 1, 1, 12, 0, 31, tzinfo=UTC).isoformat(),
            ended_at=datetime(2024, 1, 1, 12, 0, 45, tzinfo=UTC).isoformat(),
            duration_ms=14000,
            llm_calls=1,
            input_tokens=800,
            output_tokens=300,
            estimated_cost_usd=0.005,
        ),
    ]

    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="complete",
        total_cost_usd=0.015,
        total_input_tokens=2300,
        total_output_tokens=900,
        stage_telemetry=telemetry,
        validation_events=[],
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=[],
        relationships=[],
        metadata=metadata,
    )

    html = generate_report(skill_map, "# Test", "test.md")

    assert "extract" in html
    assert "relate" in html
    assert "30.0s" in html
    assert "14.0s" in html
    assert "$0.0100" in html
    assert "$0.0050" in html


def test_generate_report_with_non_prerequisite_relationships():
    """Report includes non-prerequisite relationships table."""
    topics = [
        Topic(id="a", name="A", description="Topic A", category="cat", difficulty="beginner"),
        Topic(id="b", name="B", description="Topic B", category="cat", difficulty="beginner"),
        Topic(id="c", name="C", description="Topic C", category="cat", difficulty="beginner"),
    ]

    relationships = [
        Relationship(from_id="a", to_id="b", type="related", rationale="Related concepts"),
        Relationship(from_id="a", to_id="c", type="subtopic", rationale="C is part of A"),
    ]

    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="complete",
        total_cost_usd=0.01,
        total_input_tokens=1000,
        total_output_tokens=500,
        stage_telemetry=[],
        validation_events=[],
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=topics,
        relationships=relationships,
        metadata=metadata,
    )

    html = generate_report(skill_map, "# Test", "test.md")

    assert "Other Relationships" in html
    assert "related" in html
    assert "subtopic" in html
    assert "Related concepts" in html


def test_generate_report_empty_topics():
    """Report handles empty topics gracefully."""
    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="flagged",
        total_cost_usd=0.0,
        total_input_tokens=0,
        total_output_tokens=0,
        stage_telemetry=[],
        validation_events=[],
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=[],
        relationships=[],
        metadata=metadata,
    )

    html = generate_report(skill_map, "# Empty", "empty.md")

    assert "No topics extracted" in html
    assert "flagged" in html


def test_generate_report_truncates_source():
    """Report truncates source text to 2000 characters."""
    metadata = RunMetadata(
        thread_id="test-thread",
        source_id="abc123",
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
        ended_at=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC).isoformat(),
        status="complete",
        total_cost_usd=0.01,
        total_input_tokens=1000,
        total_output_tokens=500,
        stage_telemetry=[],
        validation_events=[],
    )

    skill_map = SkillMap(
        source_id="abc123",
        topics=[],
        relationships=[],
        metadata=metadata,
    )

    # Create source longer than 2000 chars
    long_source = "# Test\n\n" + "x" * 2500

    html = generate_report(skill_map, long_source, "long.md")

    assert "truncated" in html
    assert "..." in html


def test_mermaid_skill_map_generation():
    """Skill map Mermaid generation produces valid graph."""
    from skillpipeline.report import _generate_skill_map_mermaid

    topics = [
        Topic(id="a", name="A", description="Topic A", category="cat", difficulty="beginner"),
        Topic(id="b", name="B", description="Topic B", category="cat", difficulty="beginner"),
    ]

    relationships = [
        Relationship(from_id="a", to_id="b", type="prerequisite"),
    ]

    skill_map = SkillMap(
        source_id="abc123",
        topics=topics,
        relationships=relationships,
        metadata=RunMetadata(
            thread_id="test",
            source_id="abc123",
            started_at="2024-01-01T12:00:00Z",
            status="complete",
        ),
    )

    mermaid = _generate_skill_map_mermaid(skill_map)

    # Node ids are prefixed (n_) so they never start with a Mermaid reserved word.
    assert "graph TD" in mermaid
    assert 'n_a["' in mermaid
    assert 'n_b["' in mermaid
    assert "n_a ==>|prerequisite| n_b" in mermaid


def test_mermaid_skill_map_reserved_word_id():
    """Topic ids starting with a reserved word (e.g. 'end') must not break the graph."""
    from skillpipeline.report import _generate_skill_map_mermaid

    skill_map = SkillMap(
        source_id="abc123",
        topics=[
            Topic(id="unit-testing", name="Unit Testing", description="d",
                  category="qa", difficulty="beginner"),
            Topic(id="end-to-end-testing", name="End-to-End Testing", description="d",
                  category="qa", difficulty="intermediate"),
        ],
        relationships=[
            Relationship(from_id="unit-testing", to_id="end-to-end-testing", type="prerequisite"),
        ],
        metadata=RunMetadata(
            thread_id="test", source_id="abc123",
            started_at="2024-01-01T12:00:00Z", status="complete",
        ),
    )

    mermaid = _generate_skill_map_mermaid(skill_map)
    # The raw id (which starts with the reserved word "end") is prefixed.
    assert "n_end-to-end-testing[" in mermaid
    assert "n_unit-testing ==>|prerequisite| n_end-to-end-testing" in mermaid


def test_mermaid_pipeline_generation():
    """Pipeline Mermaid generation produces valid graph."""
    from skillpipeline.report import _generate_pipeline_mermaid

    state = {
        "thread_id": "test-thread",
        "validation_events": [],
        "stage_telemetry": [],
    }

    mermaid = _generate_pipeline_mermaid(state)

    assert "graph LR" in mermaid
    assert "ingest" in mermaid
    assert "extract" in mermaid
    assert "merge" in mermaid
    assert "persist" in mermaid
