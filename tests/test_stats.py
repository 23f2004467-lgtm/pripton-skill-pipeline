"""Tests for stats command."""

from unittest.mock import patch

from skillpipeline.models import RunMetadata
from skillpipeline.stats import collect_stats


def test_collect_stats_empty(tmp_path):
    """No runs returns empty list."""
    with patch("skillpipeline.stats.Path", return_value=tmp_path):
        stats = collect_stats()
        assert stats == []


def test_collect_stats_with_runs(tmp_path):
    """Collects metadata from run_log.json files."""
    # Create mock run directories
    run1 = tmp_path / "run_20240101-120000_abc12345"
    run1.mkdir(parents=True)

    run2 = tmp_path / "run_20240101-130000_def67890"
    run2.mkdir(parents=True)

    # Create run_log.json files
    metadata1 = RunMetadata(
        thread_id="run_20240101-120000_abc12345",
        source_id="abc12345" * 4,
        started_at="2024-01-01T12:00:00Z",
        ended_at="2024-01-01T12:01:00Z",
        status="complete",
        total_cost_usd=0.01,
    )

    (run1 / "run_log.json").write_text(
        f'{{"metadata": {metadata1.model_dump_json()}, "merged_topics": []}}',
        encoding="utf-8",
    )

    metadata2 = RunMetadata(
        thread_id="run_20240101-130000_def67890",
        source_id="def67890" * 4,
        started_at="2024-01-01T13:00:00Z",
        ended_at="2024-01-01T13:00:30Z",
        status="flagged",
        total_cost_usd=0.005,
    )

    (run2 / "run_log.json").write_text(
        f'{{"metadata": {metadata2.model_dump_json()}, "merged_topics": []}}',
        encoding="utf-8",
    )

    with patch("skillpipeline.stats.Path", return_value=tmp_path):
        stats = collect_stats()

    assert len(stats) == 2
    assert any(s.thread_id == "run_20240101-120000_abc12345" for s in stats)
    assert any(s.thread_id == "run_20240101-130000_def67890" for s in stats)


def test_collect_stats_skips_corrupt(tmp_path):
    """Skips corrupt run_log.json files."""
    run1 = tmp_path / "run_20240101-120000_abc12345"
    run1.mkdir(parents=True)

    run2 = tmp_path / "run_20240101-130000_def67890"
    run2.mkdir(parents=True)

    # Valid log
    metadata = RunMetadata(
        thread_id="run_20240101-120000_abc12345",
        source_id="abc12345" * 4,
        started_at="2024-01-01T12:00:00Z",
        status="complete",
    )

    (run1 / "run_log.json").write_text(
        f'{{"metadata": {metadata.model_dump_json()}}}',
        encoding="utf-8",
    )

    # Corrupt log
    (run2 / "run_log.json").write_text("invalid json", encoding="utf-8")

    with patch("skillpipeline.stats.Path", return_value=tmp_path):
        stats = collect_stats()

    assert len(stats) == 1
    assert stats[0].thread_id == "run_20240101-120000_abc12345"


def test_collect_stats_skips_missing_log(tmp_path):
    """Skips directories without run_log.json."""
    run1 = tmp_path / "run_20240101-120000_abc12345"
    run1.mkdir(parents=True)

    # No run_log.json created

    with patch("skillpipeline.stats.Path", return_value=tmp_path):
        stats = collect_stats()

    assert len(stats) == 0
