"""Tests for pipeline orchestrator."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from skillpipeline.cache import CacheEntry
from skillpipeline.models import (
    RunMetadata,
    SkillMap,
    Topic,
)
from skillpipeline.pipeline import (
    _compute_source_id,
    _generate_thread_id,
    resume,
    review,
    run,
)


def test_compute_source_id():
    """SHA-256 hash of input bytes is computed correctly."""
    raw_bytes = b"Hello, world!"
    source_id = _compute_source_id(raw_bytes)
    # Verify it's a 64-char hex string
    assert len(source_id) == 64
    assert all(c in "0123456789abcdef" for c in source_id)


def test_compute_source_id_consistent():
    """Same input produces same source_id."""
    raw_bytes = b"Consistent input"
    source_id1 = _compute_source_id(raw_bytes)
    source_id2 = _compute_source_id(raw_bytes)
    assert source_id1 == source_id2


def test_generate_thread_id_format():
    """Thread ID follows the correct format."""
    source_id = "a" * 64  # Full SHA-256
    thread_id = _generate_thread_id(source_id)
    assert thread_id.startswith("run_")
    # Format: run_{YYYYMMDD-HHMMSS}_{short-hash}
    parts = thread_id.split("_")
    assert len(parts) == 3
    assert parts[0] == "run"
    assert "-" in parts[1]  # Timestamp has dash
    assert len(parts[2]) == 8  # Short hash


def test_run_creates_output_files(tmp_path):
    """Run creates expected output files."""
    # Create a test input file
    input_file = tmp_path / "test.md"
    input_file.write_text("# Test\n\nTest content.", encoding="utf-8")

    # Mock graph execution to return a simple state
    with patch("skillpipeline.pipeline.create_graph") as mock_graph:
        mock_compiled = Mock()
        mock_graph.return_value = mock_compiled

        # Mock invoke to return completed state
        mock_compiled.invoke.return_value = {
            "approved_topics": [
                Topic(
                    id="test",
                    name="Test",
                    description="Test topic",
                    category="test",
                    difficulty="beginner",
                )
            ],
            "relationships": [],
            "status": "complete",
            "source_id": _compute_source_id(b"# Test\n\nTest content."),
            "stage_telemetry": [],
            "validation_events": [],
            "merged_topics": [],
        }

        _ = run(str(input_file), always_review=False, no_cache=True)

        # Verify output files were created
        runs_dir = Path("runs")
        assert runs_dir.exists()

        # Find the created run directory
        run_dirs = list(runs_dir.glob("run_*"))
        assert len(run_dirs) > 0

        run_dir = run_dirs[0]
        assert (run_dir / "skill_map.json").exists()
        assert (run_dir / "run_log.json").exists()
        assert (run_dir / "report.html").exists()
        assert (run_dir / "skill_map.mmd").exists()

        # Verify runs/index.html was created
        assert (runs_dir / "index.html").exists()


def test_run_cache_hit(tmp_path):
    """Cache hit skips LLM calls and copies cached results."""
    # Create test input file
    input_file = tmp_path / "test.md"
    input_file.write_text("# Test\n\nTest content.", encoding="utf-8")

    source_id = _compute_source_id(b"# Test\n\nTest content.")

    # Create a cached skill_map
    cached_skill_map = SkillMap(
        source_id=source_id,
        topics=[Topic(id="test", name="Test", description="Test", category="test", difficulty="beginner")],
        relationships=[],
        metadata=RunMetadata(
            thread_id="cached-run",
            source_id=source_id,
            started_at="2024-01-01T12:00:00Z",
            status="complete",
            total_cost_usd=0.01,
        ),
    )

    # Mock the cache to return a CacheEntry (not a bare SkillMap)
    cache_entry = CacheEntry.__new__(CacheEntry)
    cache_entry.skill_map = cached_skill_map
    cache_entry.run_metadata = cached_skill_map.metadata
    cache_entry.cached_at = "2024-01-01T12:00:00Z"

    mock_cache = Mock()
    mock_cache.get.return_value = cache_entry

    with patch("skillpipeline.pipeline.get_cache", return_value=mock_cache):
        result = run(str(input_file), always_review=False, no_cache=False)

        # Should use cache
        assert "cache hit" in result.lower()
        mock_cache.get.assert_called_once_with(source_id)


def test_review_opens_editor(tmp_path):
    """Review command opens file in EDITOR if set."""
    import os

    # Create test run with review file
    thread_id = "test-review-run"
    run_dir = tmp_path / "runs" / thread_id
    run_dir.mkdir(parents=True)

    review_file = run_dir / "topics_for_review.json"
    review_file.write_text('{"topics": [{"id": "test", "name": "Test", "description": "Test", "category": "test", "difficulty": "beginner"}]}', encoding="utf-8")

    # Mock subprocess.call
    with patch("skillpipeline.pipeline.subprocess.call") as mock_call:
        with patch.dict(os.environ, {"EDITOR": "vim"}):
            # Change to tmp_path for the test
            old_cwd = os.getcwd()
            os.chdir(tmp_path)

            try:
                _ = review(thread_id)

                # Verify editor was called
                mock_call.assert_called_once()
                assert "vim" in str(mock_call.call_args)
            finally:
                os.chdir(old_cwd)


def test_review_no_editor(tmp_path):
    """Review command returns file path when EDITOR not set."""
    import os

    # Create test run with review file
    thread_id = "test-review-run"
    run_dir = tmp_path / "runs" / thread_id
    run_dir.mkdir(parents=True)

    review_file = run_dir / "topics_for_review.json"
    review_file.write_text('{"topics": []}', encoding="utf-8")

    # Ensure EDITOR is not set
    with patch.dict(os.environ, {}, clear=True):
        # Change to tmp_path for the test
        old_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            result = review(thread_id)

            # Should return file path message
            assert "topics_for_review.json" in result
        finally:
            os.chdir(old_cwd)


def test_resume_loads_and_continues(tmp_path):
    """Resume loads review file and continues graph execution."""

    # Create test run with review file and run log
    thread_id = "test-resume-run"
    run_dir = tmp_path / "runs" / thread_id
    run_dir.mkdir(parents=True)

    # Create review file
    review_file = run_dir / "topics_for_review.json"
    review_data = {
        "_instructions": {"purpose": "test"},
        "_merge_events": [],
        "topics": [
            {
                "id": "test",
                "name": "Test",
                "description": "Test topic",
                "category": "test",
                "difficulty": "beginner",
            }
        ],
    }
    review_file.write_text(json.dumps(review_data), encoding="utf-8")

    # Create run log
    run_log_file = run_dir / "run_log.json"
    run_log_file.write_text(
        json.dumps({
            "metadata": {
                "thread_id": thread_id,
                "source_id": "abc123",
                "started_at": "2024-01-01T12:00:00Z",
                "status": "awaiting_review",
            },
            "merged_topics": [],
            "source_path": "test.md",
        }),
        encoding="utf-8",
    )

    # Create source file
    (tmp_path / "test.md").write_text("# Test", encoding="utf-8")

    # Mock graph execution
    with patch("skillpipeline.pipeline.create_graph") as mock_graph:
        mock_compiled = Mock()
        mock_graph.return_value = mock_compiled

        # Mock invoke to return completed state
        mock_compiled.invoke.return_value = {
            "approved_topics": [],
            "relationships": [],
            "status": "complete",
            "source_id": "abc123",
            "stage_telemetry": [],
            "validation_events": [],
            "merged_topics": [],
        }

        # Change to tmp_path for the test
        import os
        old_cwd = os.getcwd()
        os.chdir(tmp_path)

        try:
            _ = resume(thread_id)

            # Verify graph was called with resume Command
            mock_compiled.invoke.assert_called_once()
            call_args = mock_compiled.invoke.call_args
            assert call_args[0][0].resume is not None
            assert len(call_args[0][0].resume) == 1
            assert call_args[0][0].resume[0].id == "test"

        finally:
            os.chdir(old_cwd)


def test_resume_invalid_review_file(tmp_path):
    """Resume with invalid review file returns error."""
    thread_id = "test-invalid-resume"
    run_dir = tmp_path / "runs" / thread_id
    run_dir.mkdir(parents=True)

    # Create invalid review file
    review_file = run_dir / "topics_for_review.json"
    review_file.write_text("invalid json", encoding="utf-8")

    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        result = resume(thread_id)
        assert "error" in result.lower()
    finally:
        os.chdir(old_cwd)


def test_resume_missing_review_file():
    """Resume with missing review file returns error."""
    result = resume("nonexistent-thread")
    assert "error" in result.lower() or "no review file found" in result.lower()
