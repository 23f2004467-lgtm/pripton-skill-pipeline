"""Tests for cache module."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillpipeline.cache import Cache, CacheEntry, get_cache
from skillpipeline.models import Relationship, RunMetadata, SkillMap, Topic, ValidationEvent


@pytest.fixture(autouse=True)
def reset_cache_singleton():
    """Reset the cache singleton between tests."""
    import skillpipeline.cache
    skillpipeline.cache._default_cache = None
    yield
    skillpipeline.cache._default_cache = None


@pytest.fixture
def sample_cache(tmp_path):
    """Create a cache instance in a temp directory."""
    return Cache(tmp_path / "cache")


@pytest.fixture
def sample_skill_map():
    """Create a sample skill map for testing."""
    return SkillMap(
        source_id="test-source-id",
        topics=[
            Topic(
                id="topic-a",
                name="Topic A",
                description="First topic",
                category="test",
                difficulty="beginner",
                source_section_id="section-0",
            ),
            Topic(
                id="topic-b",
                name="Topic B",
                description="Second topic",
                category="test",
                difficulty="intermediate",
                source_section_id="section-1",
            ),
        ],
        relationships=[
            Relationship(from_id="topic-a", to_id="topic-b", type="prerequisite")
        ],
        metadata=RunMetadata(
            thread_id="test-thread",
            source_id="test-source-id",
            started_at=datetime.now(UTC).isoformat(),
            ended_at=datetime.now(UTC).isoformat(),
            status="complete",
        ),
    )


@pytest.fixture
def sample_metadata():
    """Create sample run metadata."""
    return RunMetadata(
        thread_id="test-thread",
        source_id="test-source-id",
        started_at=datetime.now(UTC).isoformat(),
        ended_at=datetime.now(UTC).isoformat(),
        status="complete",
        total_cost_usd=0.01,
        total_input_tokens=100,
        total_output_tokens=50,
    )


class TestCacheEntry:
    """Test CacheEntry data structure."""

    def test_creates_entry_from_skill_map_and_metadata(self, sample_skill_map, sample_metadata):
        """CacheEntry serializes skill_map and metadata."""
        entry = CacheEntry(sample_skill_map, sample_metadata)

        assert "topics" in entry.skill_map
        assert "status" in entry.run_metadata
        assert entry.cached_at is not None


class TestCache:
    """Test cache operations."""

    def test_cache_dir_created_on_init(self, tmp_path):
        """Cache directory is created if it doesn't exist."""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        Cache(cache_dir)
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_get_returns_none_on_miss(self, sample_cache):
        """get returns None when source_id is not cached."""
        result = sample_cache.get("nonexistent-id")
        assert result is None

    def test_put_and_get_roundtrip(self, sample_cache, sample_skill_map, sample_metadata):
        """put stores entry that can be retrieved with get."""
        source_id = "test-source-id"

        sample_cache.put(source_id, sample_skill_map, sample_metadata)
        result = sample_cache.get(source_id)

        assert result is not None
        assert result.skill_map.source_id == source_id
        assert len(result.skill_map.topics) == 2
        assert result.run_metadata.status == "complete"
        assert result.cached_at is not None

    def test_get_reconstructs_objects(self, sample_cache, sample_skill_map, sample_metadata):
        """get reconstructs SkillMap and RunMetadata objects."""
        source_id = "test-source-id"

        sample_cache.put(source_id, sample_skill_map, sample_metadata)
        entry = sample_cache.get(source_id)

        # Check that entry.skill_map is a SkillMap object, not a dict
        assert isinstance(entry.skill_map, SkillMap)
        assert isinstance(entry.run_metadata, RunMetadata)
        assert entry.skill_map.source_id == source_id

    def test_corrupt_cache_returns_none(self, sample_cache, tmp_path):
        """Corrupt cache file is treated as a miss."""
        source_id = "corrupt-id"
        cache_path = sample_cache._get_cache_path(source_id)

        # Write invalid JSON
        cache_path.write_text("invalid json {{{", encoding="utf-8")

        result = sample_cache.get(source_id)
        assert result is None

    def test_multiple_entries(self, sample_cache, sample_skill_map, sample_metadata):
        """Cache handles multiple entries correctly."""
        id1 = "source-1"
        id2 = "source-2"

        sample_cache.put(id1, sample_skill_map, sample_metadata)
        sample_cache.put(id2, sample_skill_map, sample_metadata)

        assert sample_cache.get(id1) is not None
        assert sample_cache.get(id2) is not None
        assert sample_cache.get("nonexistent") is None

    def test_should_cache_complete_runs(self, sample_cache, sample_metadata):
        """Complete runs should be cached."""
        sample_metadata.status = "complete"
        assert sample_cache.should_cache(sample_metadata) is True

    def test_should_not_cache_flagged_runs(self, sample_cache, sample_metadata):
        """Flagged runs should not be cached."""
        sample_metadata.status = "flagged"
        assert sample_cache.should_cache(sample_metadata) is False

    def test_should_not_cache_awaiting_review_runs(self, sample_cache, sample_metadata):
        """Awaiting_review runs should not be cached."""
        sample_metadata.status = "awaiting_review"
        assert sample_cache.should_cache(sample_metadata) is False

    def test_should_not_cache_running_runs(self, sample_cache, sample_metadata):
        """Running runs should not be cached."""
        sample_metadata.status = "running"
        assert sample_cache.should_cache(sample_metadata) is False

    def test_should_not_cache_failed_runs(self, sample_cache, sample_metadata):
        """Failed runs should not be cached."""
        sample_metadata.status = "failed"
        assert sample_cache.should_cache(sample_metadata) is False

    def test_clear_removes_all_entries(self, sample_cache, sample_skill_map, sample_metadata):
        """clear removes all cache entries."""
        sample_cache.put("id1", sample_skill_map, sample_metadata)
        sample_cache.put("id2", sample_skill_map, sample_metadata)

        assert sample_cache.get("id1") is not None
        assert sample_cache.get("id2") is not None

        sample_cache.clear()

        assert sample_cache.get("id1") is None
        assert sample_cache.get("id2") is None

    def test_list_entries(self, sample_cache, sample_skill_map, sample_metadata):
        """list_entries returns metadata for all cached entries."""
        sample_cache.put("source-1", sample_skill_map, sample_metadata)
        sample_cache.put("source-2", sample_skill_map, sample_metadata)

        entries = sample_cache.list_entries()

        assert len(entries) == 2
        source_ids = {e["source_id"] for e in entries}
        assert "source-1" in source_ids
        assert "source-2" in source_ids

        # Each entry should have required fields
        for entry in entries:
            assert "source_id" in entry
            assert "cached_at" in entry
            assert "status" in entry

    def test_list_entries_skips_corrupt(self, sample_cache, sample_skill_map, sample_metadata, tmp_path):
        """list_entries skips corrupt entries."""
        sample_cache.put("good-id", sample_skill_map, sample_metadata)

        # Create a corrupt file
        (sample_cache.cache_dir / "corrupt-id.json").write_text("invalid {{{")

        entries = sample_cache.list_entries()

        assert len(entries) == 1
        assert entries[0]["source_id"] == "good-id"


class TestGetCache:
    """Test default cache singleton."""

    def test_get_cache_returns_singleton(self):
        """get_cache returns the same instance on subsequent calls."""
        cache1 = get_cache()
        cache2 = get_cache()

        assert cache1 is cache2

    def test_get_cache_with_custom_dir(self, tmp_path):
        """get_cache uses custom dir on first call."""
        custom_dir = tmp_path / "custom_cache"
        cache = get_cache(custom_dir)

        assert cache.cache_dir == custom_dir
