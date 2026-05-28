"""Pipeline statistics aggregator.

Walks runs/ and prints aggregate metrics.

See PLAN.md Section 9.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from skillpipeline.models import RunMetadata


def collect_stats() -> list[RunMetadata]:
    """Collect RunMetadata from all run_log.json files in runs/.

    Returns:
        List of RunMetadata objects, one per run
    """
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return []

    stats = []
    for run_dir in runs_dir.glob("run_*"):
        log_file = run_dir / "run_log.json"
        if not log_file.exists():
            continue

        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            # Extract metadata from run_log.json structure
            # The file contains {metadata: {...}, merged_topics: [...], ...}
            if "metadata" in data:
                metadata = RunMetadata(**data["metadata"])
                stats.append(metadata)
        except (json.JSONDecodeError, KeyError, TypeError):
            # Skip corrupt logs
            continue

    return stats


def print_stats_table(stats: list[RunMetadata]) -> None:
    """Print stats as a Rich table.

    Args:
        stats: List of RunMetadata objects
    """
    console = Console()

    # Calculate aggregates
    total_runs = len(stats)
    if total_runs == 0:
        console.print("[yellow]No runs found in runs/[/yellow]")
        return

    complete = sum(1 for s in stats if s.status == "complete")
    flagged = sum(1 for s in stats if s.status == "flagged")
    awaiting_review = sum(1 for s in stats if s.status == "awaiting_review")
    failed = sum(1 for s in stats if s.status == "failed")
    total_spend = sum(s.total_cost_usd for s in stats)

    # Print summary banner
    console.print()
    console.print(f"[bold]Pipeline Statistics[/bold] ({total_runs} runs)")
    console.print()

    # Summary table
    summary = Table(title=None, show_header=False, box=None)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value")

    success_rate = (complete / total_runs * 100) if total_runs > 0 else 0
    flag_rate = (flagged / total_runs * 100) if total_runs > 0 else 0

    summary.add_row("Complete", f"{complete} ({success_rate:.1f}%)")
    summary.add_row("Flagged", f"[yellow]{flagged}[/yellow] ({flag_rate:.1f}%)")
    summary.add_row("Awaiting Review", f"[orange]{awaiting_review}[/orange]")
    if failed > 0:
        summary.add_row("Failed", f"[red]{failed}[/red]")
    summary.add_row("Total Spend", f"${total_spend:.4f}")

    console.print(summary)
    console.print()

    # Detailed table
    table = Table(title="Run Details")
    table.add_column("Thread ID", style="cyan")
    table.add_column("Status")
    table.add_column("Cost", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cache", justify="center")

    for s in sorted(stats, key=lambda x: x.started_at, reverse=True):
        # Style status
        status_style = {
            "complete": "[green]complete[/green]",
            "flagged": "[yellow]flagged[/yellow]",
            "awaiting_review": "[orange]awaiting_review[/orange]",
            "failed": "[red]failed[/red]",
            "running": "[blue]running[/blue]",
        }.get(s.status, s.status)

        total_tokens = s.total_input_tokens + s.total_output_tokens
        cache_status = "[green]H[/green]" if s.cache_hit else "-"

        table.add_row(
            s.thread_id,
            status_style,
            f"${s.total_cost_usd:.4f}",
            f"{total_tokens:,}",
            cache_status,
        )

    console.print(table)


def print_stats_json(stats: list[RunMetadata]) -> None:
    """Print stats as JSON.

    Args:
        stats: List of RunMetadata objects
    """
    import sys

    output = [s.model_dump() for s in stats]
    json.dump(output, sys.stdout, indent=2)


def stats(json_output: bool = False) -> None:
    """Main entry point for stats command.

    Args:
        json_output: If True, output JSON instead of Rich table
    """
    collected = collect_stats()

    if json_output:
        print_stats_json(collected)
    else:
        print_stats_table(collected)
