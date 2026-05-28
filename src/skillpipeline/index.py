"""Runs-index HTML page generator.

Generates runs/index.html from the Jinja2 template at
templates/index.html.j2. Regenerated at the end of every run.

See PLAN.md Section 8 for the full specification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from jinja2 import Template

from skillpipeline.models import RunMetadata, ValidationEvent


def _get_stage_status(
    stage: str,
    validation_events: list[ValidationEvent],
) -> str:
    """Determine the status of a single stage for the runs-index grid.

    Status colors:
    - completed (green): no errors at this stage
    - retried (yellow): had retries but succeeded
    - flagged (red): had errors that didn't recover
    - awaiting_review (orange): human_review in progress

    Args:
        stage: The stage name (e.g., "extract", "relate")
        validation_events: All validation events from the run

    Returns:
        Status string for CSS class
    """
    # Special case for human_review - check if awaiting review
    if stage == "human_review":
        # This would be determined by checking if topics_for_review.json exists
        # but for the index we don't have that context here
        # We'll rely on the run's overall status
        return "completed"

    # Check for errors at this stage
    errors = [e for e in validation_events if e.stage == stage and e.severity == "error"]
    if errors:
        return "flagged"

    # Check for retries at this stage
    retries = [e for e in validation_events if e.stage == stage and e.retry_number > 0]
    if retries:
        return "retried"

    return "completed"


def _scan_runs(runs_dir: Path) -> list[dict]:
    """Scan the runs directory and load metadata from each run.

    Args:
        runs_dir: Path to the runs/ directory

    Returns:
        List of run dicts with metadata, sorted by started_at descending
    """
    runs = []

    if not runs_dir.exists():
        return runs

    for run_path in runs_dir.iterdir():
        if not run_path.is_dir():
            continue

        run_log_path = run_path / "run_log.json"
        if not run_log_path.exists():
            continue

        try:
            import json

            data = json.loads(run_log_path.read_text(encoding="utf-8"))

            # Parse RunMetadata
            metadata = RunMetadata(**data.get("metadata", {}))

            runs.append({
                "thread_id": run_path.name,
                "metadata": metadata,
                "source_path": data.get("source_path", "unknown"),
            })
        except (json.JSONDecodeError, KeyError, TypeError):
            # Skip corrupt run logs
            continue

    # Sort by started_at descending (newest first)
    runs.sort(key=lambda r: r["metadata"].started_at or "", reverse=True)
    return runs


def _compute_stats(runs: list[dict]) -> dict:
    """Compute aggregate statistics from all runs.

    Args:
        runs: List of run dicts with metadata

    Returns:
        Dict with total_runs, success_rate, flag_rate, awaiting_review_count, total_spend
    """
    total = len(runs)
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": "0%",
            "flag_rate": "0%",
            "awaiting_review_count": 0,
            "total_spend_usd": "$0.00",
        }

    complete = sum(1 for r in runs if r["metadata"].status == "complete")
    flagged = sum(1 for r in runs if r["metadata"].status == "flagged")
    awaiting = sum(1 for r in runs if r["metadata"].status == "awaiting_review")

    success_rate = (complete / total) * 100 if total > 0 else 0
    flag_rate = (flagged / total) * 100 if total > 0 else 0

    total_spend = sum(r["metadata"].total_cost_usd for r in runs)

    return {
        "total_runs": total,
        "success_rate": f"{success_rate:.1f}%",
        "flag_rate": f"{flag_rate:.1f}%",
        "awaiting_review_count": awaiting,
        "total_spend_usd": f"${total_spend:.4f}",
    }


def _format_duration(started_at: Optional[str], ended_at: Optional[str]) -> str:
    """Format duration between two ISO timestamps.

    Args:
        started_at: ISO start timestamp
        ended_at: ISO end timestamp (None if in progress)

    Returns:
        Formatted duration string
    """
    if not started_at:
        return "N/A"

    if not ended_at:
        # Run in progress - calculate from now
        ended_at = datetime.now(UTC).isoformat()

    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        duration_ms = int((end - start).total_seconds() * 1000)

        if duration_ms < 1000:
            return f"{duration_ms}ms"
        elif duration_ms < 60000:
            return f"{duration_ms / 1000:.1f}s"
        else:
            minutes = duration_ms // 60000
            seconds = (duration_ms % 60000) / 1000
            return f"{minutes}m {seconds:.0f}s"
    except (ValueError, AttributeError):
        return "N/A"


def _get_stage_statuses(validation_events: list[ValidationEvent]) -> dict[str, str]:
    """Get status for each stage for display in the grid.

    Args:
        validation_events: All validation events from the run

    Returns:
        Dict mapping stage name to status string
    """
    stages = ["ingest", "extract", "merge", "human_review", "relate", "validate", "persist"]
    return {stage: _get_stage_status(stage, validation_events) for stage in stages}


def generate_index(runs_dir: Path = Path("runs")) -> str:
    """Generate the runs-index HTML page.

    Args:
        runs_dir: Path to the runs/ directory

    Returns:
        HTML page as a string
    """
    # Load template
    template_path = Path(__file__).parent.parent.parent / "templates" / "index.html.j2"
    template_content = template_path.read_text(encoding="utf-8")
    template = Template(template_content)

    # Scan runs
    runs = _scan_runs(runs_dir)

    # Compute stats
    stats = _compute_stats(runs)

    # Prepare run data for template
    run_data = []
    for run in runs:
        metadata = run["metadata"]
        run_data.append({
            "thread_id": run["thread_id"],
            "source_path": run["source_path"],
            "started_at": metadata.started_at or "N/A",
            "ended_at": metadata.ended_at or "In progress",
            "duration": _format_duration(metadata.started_at, metadata.ended_at),
            "status": metadata.status,
            "total_cost_usd": f"${metadata.total_cost_usd:.4f}",
            "stage_statuses": _get_stage_statuses(metadata.validation_events),
        })

    # Build context for template
    context = {
        "stats": stats,
        "runs": run_data,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    return template.render(**context)
