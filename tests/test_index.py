"""Tests for runs-index generator."""


from skillpipeline.index import (
    _compute_stats,
    _format_duration,
    _get_stage_status,
    _get_stage_statuses,
    generate_index,
)
from skillpipeline.models import (
    RunMetadata,
    ValidationEvent,
)


def test_get_stage_status_completed():
    """Stage with no errors returns completed."""
    events = []
    status = _get_stage_status("extract", events)
    assert status == "completed"


def test_get_stage_status_retried():
    """Stage with retries but no errors returns retried."""
    events = [
        ValidationEvent(
            stage="extract",
            severity="warning",
            code="EXTRACT_RECOVERED",
            message="Retry succeeded",
            retry_number=1,
        )
    ]
    status = _get_stage_status("extract", events)
    assert status == "retried"


def test_get_stage_status_flagged():
    """Stage with errors returns flagged."""
    events = [
        ValidationEvent(
            stage="extract",
            severity="error",
            code="MAX_RETRIES",
            message="Failed",
            retry_number=3,
        )
    ]
    status = _get_stage_status("extract", events)
    assert status == "flagged"


def test_format_duration_seconds():
    """Duration under a minute formats as seconds."""
    result = _format_duration("2024-01-01T12:00:00Z", "2024-01-01T12:00:30Z")
    assert result == "30.0s"


def test_format_duration_minutes():
    """Duration over a minute formats as minutes."""
    result = _format_duration("2024-01-01T12:00:00Z", "2024-01-01T12:02:30Z")
    assert result == "2m 30s"


def test_format_duration_milliseconds():
    """Duration under a second formats as ms."""
    result = _format_duration("2024-01-01T12:00:00Z", "2024-01-01T12:00:00.500Z")
    assert result == "500ms"


def test_format_duration_no_end():
    """Duration with no end time calculates from now (returns N/A in test)."""
    result = _format_duration("2024-01-01T12:00:00Z", None)
    # In test context, this would calculate duration to now
    # The actual value depends on when test runs
    assert "m" in result or "s" in result or "ms" in result


def test_compute_stats_empty():
    """Empty runs list returns zero stats."""
    stats = _compute_stats([])
    assert stats["total_runs"] == 0
    assert stats["success_rate"] == "0%"
    assert stats["flag_rate"] == "0%"
    assert stats["awaiting_review_count"] == 0
    assert stats["total_spend_usd"] == "$0.00"


def test_compute_stats_all_complete():
    """All complete runs returns 100% success rate."""
    runs = [
        {
            "metadata": RunMetadata(
                thread_id="test1",
                source_id="abc",
                started_at="2024-01-01T12:00:00Z",
                status="complete",
                total_cost_usd=0.01,
            )
        },
        {
            "metadata": RunMetadata(
                thread_id="test2",
                source_id="def",
                started_at="2024-01-01T12:01:00Z",
                status="complete",
                total_cost_usd=0.02,
            )
        },
    ]
    stats = _compute_stats(runs)
    assert stats["total_runs"] == 2
    assert stats["success_rate"] == "100.0%"
    assert stats["flag_rate"] == "0.0%"
    assert stats["total_spend_usd"] == "$0.0300"


def test_compute_stats_mixed():
    """Mixed status runs computes correct rates."""
    runs = [
        {
            "metadata": RunMetadata(
                thread_id="test1",
                source_id="abc",
                started_at="2024-01-01T12:00:00Z",
                status="complete",
                total_cost_usd=0.01,
            )
        },
        {
            "metadata": RunMetadata(
                thread_id="test2",
                source_id="def",
                started_at="2024-01-01T12:01:00Z",
                status="flagged",
                total_cost_usd=0.015,
            )
        },
        {
            "metadata": RunMetadata(
                thread_id="test3",
                source_id="ghi",
                started_at="2024-01-01T12:02:00Z",
                status="awaiting_review",
                total_cost_usd=0.005,
            )
        },
    ]
    stats = _compute_stats(runs)
    assert stats["total_runs"] == 3
    assert stats["success_rate"] == "33.3%"  # 1/3
    assert stats["flag_rate"] == "33.3%"  # 1/3
    assert stats["awaiting_review_count"] == 1
    assert stats["total_spend_usd"] == "$0.0300"


def test_get_stage_statuses():
    """Get all stage statuses for a run."""
    events = [
        ValidationEvent(
            stage="extract",
            severity="warning",
            code="EXTRACT_RECOVERED",
            message="Retry",
            retry_number=1,
        ),
        ValidationEvent(
            stage="relate",
            severity="error",
            code="DANGLING_REF",
            message="Error",
            retry_number=0,
        ),
    ]
    statuses = _get_stage_statuses(events)
    assert statuses["extract"] == "retried"
    assert statuses["relate"] == "flagged"
    assert statuses["ingest"] == "completed"
    assert statuses["merge"] == "completed"


def test_generate_index_empty():
    """Generate index with no runs."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir)
        html = generate_index(runs_dir)

        assert "No runs found" in html
        assert "0" in html  # Total runs


def test_generate_index_with_runs():
    """Generate index with sample runs."""
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir)

        # Create two run directories with run_log.json
        run1_dir = runs_dir / "run_20240101-120000_abc"
        run1_dir.mkdir()

        metadata1 = RunMetadata(
            thread_id="run_20240101-120000_abc",
            source_id="abc123",
            started_at="2024-01-01T12:00:00Z",
            ended_at="2024-01-01T12:01:00Z",
            status="complete",
            total_cost_usd=0.01,
            total_input_tokens=1000,
            total_output_tokens=500,
            stage_telemetry=[],
            validation_events=[],
        )

        (run1_dir / "run_log.json").write_text(
            json.dumps({"metadata": metadata1.model_dump(), "source_path": "test.md"}),
            encoding="utf-8",
        )

        run2_dir = runs_dir / "run_20240101-113000_def"
        run2_dir.mkdir()

        metadata2 = RunMetadata(
            thread_id="run_20240101-113000_def",
            source_id="def456",
            started_at="2024-01-01T11:30:00Z",
            ended_at="2024-01-01T11:31:30Z",
            status="flagged",
            total_cost_usd=0.015,
            total_input_tokens=1500,
            total_output_tokens=700,
            stage_telemetry=[],
            validation_events=[
                ValidationEvent(
                    stage="extract",
                    severity="error",
                    code="MAX_RETRIES",
                    message="Failed",
                    retry_number=3,
                )
            ],
        )

        (run2_dir / "run_log.json").write_text(
            json.dumps({"metadata": metadata2.model_dump(), "source_path": "test2.md"}),
            encoding="utf-8",
        )

        html = generate_index(runs_dir)

        # Verify stats
        assert "2" in html  # Total runs
        assert "50.0%" in html  # Success rate (1/2)
        assert "50.0%" in html  # Flag rate (1/2)

        # Verify run rows
        assert "run_20240101-120000_abc" in html
        assert "run_20240101-113000_def" in html
        assert "test.md" in html
        assert "test2.md" in html

        # Verify status pills
        assert "status-complete" in html
        assert "status-flagged" in html

        # Verify stage status dots
        assert "stage-completed" in html
        assert "stage-flagged" in html


def test_generate_index_ignores_corrupt_logs():
    """Generate index ignores corrupt run_log.json files."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        runs_dir = Path(tmpdir)

        # Create a valid run
        run1_dir = runs_dir / "run_valid"
        run1_dir.mkdir()

        metadata = RunMetadata(
            thread_id="run_valid",
            source_id="abc",
            started_at="2024-01-01T12:00:00Z",
            status="complete",
            total_cost_usd=0.01,
        )

        (run1_dir / "run_log.json").write_text(
            '{"metadata": ' + metadata.model_dump_json() + ', "source_path": "test.md"}',
            encoding="utf-8",
        )

        # Create a corrupt run
        run2_dir = runs_dir / "run_corrupt"
        run2_dir.mkdir()
        (run2_dir / "run_log.json").write_text("invalid json", encoding="utf-8")

        html = generate_index(runs_dir)

        assert "1" in html  # Only valid run counted
        assert "run_valid" in html
