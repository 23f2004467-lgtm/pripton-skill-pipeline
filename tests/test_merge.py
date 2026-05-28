"""Tests for merge stage."""

import pytest

from skillpipeline.merge import merge_topics
from skillpipeline.models import Topic


@pytest.fixture
def sample_state():
    """Base pipeline state for merge tests."""
    return {
        "extracted_topics": [],
        "merged_topics": None,
        "validation_events": [],
    }


class TestMergeTopics:
    def test_no_topics_empty_extraction(self, sample_state):
        """Empty extracted topics triggers empty-extraction short-circuit."""
        sample_state["extracted_topics"] = []
        result = merge_topics(sample_state)

        assert result["merged_topics"] == []
        assert len(result["validation_events"]) == 1
        event = result["validation_events"][0]
        assert event.stage == "merge"
        assert event.severity == "error"
        assert event.code == "EMPTY_EXTRACTION"
        assert event.flagged is True

    def test_single_topic_no_merge(self, sample_state):
        """Single topic passes through unchanged."""
        topic = Topic(
            id="react",
            name="React",
            description="A JS library",
            category="frontend",
            difficulty="intermediate",
            source_section_id="section-0",
        )
        sample_state["extracted_topics"] = [topic]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 1
        merged = result["merged_topics"][0]
        assert merged.id == "react"
        assert merged.name == "React"
        assert merged.source_section_id == "section-0"
        assert len(result["validation_events"]) == 0

    def test_duplicate_names_merged(self, sample_state):
        """Topics with same normalized name are merged."""
        topic1 = Topic(
            id="react-basics",
            name="React Basics",
            description="Basic React concepts",
            category="frontend",
            difficulty="beginner",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="react-intro",
            name="REACT BASICS",  # Same normalized name
            description="Introduction to React",
            category="frontend",
            difficulty="beginner",
            source_section_id="section-1",
        )
        sample_state["extracted_topics"] = [topic1, topic2]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 1
        merged = result["merged_topics"][0]
        # Longest description wins (topic2 has longer "Introduction to React")
        assert merged.description == "Introduction to React"
        assert merged.source_section_id == "section-1"  # From canonical (topic2)

        # Info event logged for merge
        merge_events = [e for e in result["validation_events"] if e.code == "DUPLICATE_TOPIC_MERGED"]
        assert len(merge_events) == 1

    def test_difficulty_conflict_resolves_to_lowest(self, sample_state):
        """Difficulty conflict picks lowest (conservative)."""
        topic1 = Topic(
            id="python-intro",
            name="Python Intro",
            description="Short",
            category="backend",
            difficulty="advanced",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="python-basics",
            name="Python Intro",
            description="Short",  # Same length, conflict resolved by order
            category="backend",
            difficulty="beginner",
            source_section_id="section-1",
        )
        sample_state["extracted_topics"] = [topic1, topic2]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 1
        merged = result["merged_topics"][0]
        # Should pick beginner (conservative)
        assert merged.difficulty == "beginner"

        # Warning event logged
        conflict_events = [e for e in result["validation_events"] if e.code == "DIFFICULTY_CONFLICT"]
        assert len(conflict_events) == 1
        assert "beginner" in conflict_events[0].message

    def test_category_conflict_resolves_to_most_frequent(self, sample_state):
        """Category conflict picks most frequent."""
        topic1 = Topic(
            id="js-1",
            name="JavaScript",
            description="JS language",
            category="frontend",
            difficulty="intermediate",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="js-2",
            name="JavaScript",
            description="JS language fundamentals",
            category="backend",  # Different category
            difficulty="intermediate",
            source_section_id="section-1",
        )
        topic3 = Topic(
            id="js-3",
            name="JavaScript",
            description="JS language advanced topics",
            category="frontend",  # Frontend appears twice
            difficulty="advanced",
            source_section_id="section-2",
        )
        sample_state["extracted_topics"] = [topic1, topic2, topic3]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 1
        merged = result["merged_topics"][0]
        # Should pick "frontend" (most frequent)
        assert merged.category == "frontend"

        # Warning event logged
        conflict_events = [e for e in result["validation_events"] if e.code == "CATEGORY_CONFLICT"]
        assert len(conflict_events) == 1

    def test_canonical_id_wins(self, sample_state):
        """Canonical record's ID is kept after merge."""
        topic1 = Topic(
            id="original-id",
            name="Docker",
            description="Containerization basics",
            category="devops",
            difficulty="intermediate",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="other-id",
            name="Docker",
            description="Containerization basics and advanced",
            category="devops",
            difficulty="advanced",
            source_section_id="section-1",
        )
        sample_state["extracted_topics"] = [topic1, topic2]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 1
        merged = result["merged_topics"][0]
        # topic2 has longer description, so it's canonical
        assert merged.id == "other-id"
        assert merged.source_section_id == "section-1"

    def test_multiple_unique_topics_preserved(self, sample_state):
        """Multiple unique topics are all preserved."""
        topic1 = Topic(
            id="react",
            name="React",
            description="A JS library",
            category="frontend",
            difficulty="intermediate",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="vue",
            name="Vue",
            description="Another JS library",
            category="frontend",
            difficulty="intermediate",
            source_section_id="section-1",
        )
        topic3 = Topic(
            id="angular",
            name="Angular",
            description="Yet another JS library",
            category="frontend",
            difficulty="advanced",
            source_section_id="section-2",
        )
        sample_state["extracted_topics"] = [topic1, topic2, topic3]
        result = merge_topics(sample_state)

        assert len(result["merged_topics"]) == 3
        assert len(result["validation_events"]) == 0

    def test_case_insensitive_dedup(self, sample_state):
        """Name matching is case-insensitive."""
        topic1 = Topic(
            id="k8s-1",
            name="Kubernetes",
            description="Container orchestration",
            category="devops",
            difficulty="advanced",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="k8s-2",
            name="KUBERNETES",
            description="K8s basics",
            category="devops",
            difficulty="beginner",
            source_section_id="section-1",
        )
        topic3 = Topic(
            id="k8s-3",
            name="kubernetes",
            description="K8s intermediate",
            category="devops",
            difficulty="intermediate",
            source_section_id="section-2",
        )
        sample_state["extracted_topics"] = [topic1, topic2, topic3]
        result = merge_topics(sample_state)

        # All three should merge into one
        assert len(result["merged_topics"]) == 1

    def test_whitespace_in_name_normalized(self, sample_state):
        """Whitespace in names is normalized for matching."""
        topic1 = Topic(
            id="golang-1",
            name="Go",
            description="Go language",
            category="backend",
            difficulty="intermediate",
            source_section_id="section-0",
        )
        topic2 = Topic(
            id="golang-2",
            name="  Go  ",
            description="Go programming",
            category="backend",
            difficulty="beginner",
            source_section_id="section-1",
        )
        sample_state["extracted_topics"] = [topic1, topic2]
        result = merge_topics(sample_state)

        # Should merge (whitespace normalized)
        assert len(result["merged_topics"]) == 1
