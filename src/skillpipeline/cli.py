"""CLI interface for skill pipeline.

Uses argparse (stdlib) per PLAN.md Section 9.
"""

from __future__ import annotations

import argparse
import sys

from skillpipeline.cache import get_cache
from skillpipeline.pipeline import resume, review
from skillpipeline.pipeline import run as pipeline_run
from skillpipeline.stats import stats


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = argparse.ArgumentParser(
        description="Pripton Skill Pipeline — Extract structured skill maps from markdown documents.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Run the pipeline on a markdown file")
    run_parser.add_argument("input", help="Path to input markdown file")
    run_parser.add_argument(
        "--always-review",
        action="store_true",
        help="Force human review even without retries",
    )
    run_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache read/write",
    )

    # review command
    review_parser = subparsers.add_parser("review", help="Open topics for review in $EDITOR")
    review_parser.add_argument("thread_id", help="Thread ID to review")

    # resume command
    resume_parser = subparsers.add_parser("resume", help="Resume a pipeline run after review")
    resume_parser.add_argument("thread_id", help="Thread ID to resume")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show pipeline statistics")
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of Rich table",
    )

    # cache subcommand
    cache_parser = subparsers.add_parser("cache", help="Manage the content-addressed cache")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command", help="Cache commands")

    cache_subparsers.add_parser("list", help="List cache entries")
    cache_subparsers.add_parser("clear", help="Clear all cache entries")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    match args.command:
        case "run":
            return _handle_run(args)
        case "review":
            return _handle_review(args)
        case "resume":
            return _handle_resume(args)
        case "stats":
            stats(json_output=args.json)
            return 0
        case "cache":
            return _handle_cache(args)
        case _:
            parser.print_help()
            return 1


def _handle_run(args: argparse.Namespace) -> int:
    """Handle the run command.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    from rich.console import Console

    console = Console()

    try:
        result = pipeline_run(
            args.input,
            always_review=args.always_review,
            no_cache=args.no_cache,
        )

        console.print(result)

        # Check if result mentions "flagged" and add a banner
        if "flagged" in result.lower():
            console.print()
            console.print("[yellow]Run completed with warnings. Check the report for details.[/yellow]")

        return 0

    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _handle_review(args: argparse.Namespace) -> int:
    """Handle the review command.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    from rich.console import Console

    console = Console()

    try:
        result = review(args.thread_id)
        console.print(result)
        return 0
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _handle_resume(args: argparse.Namespace) -> int:
    """Handle the resume command.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    from rich.console import Console

    console = Console()

    try:
        result = resume(args.thread_id)
        console.print(result)
        return 0
    except FileNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


def _handle_cache(args: argparse.Namespace) -> int:
    """Handle the cache subcommand.

    Args:
        args: Parsed arguments

    Returns:
        Exit code
    """
    from rich.console import Console

    console = Console()
    cache = get_cache()

    match args.cache_command:
        case "list":
            entries = cache.list_entries()
            if not entries:
                console.print("[yellow]Cache is empty[/yellow]")
                return 0

            for entry in entries:
                console.print(
                    f"{entry['source_id'][:8]}... - {entry['cached_at']} - {entry['status']}"
                )
            return 0

        case "clear":
            cache.clear()
            console.print("[green]Cache cleared[/green]")
            return 0

        case _:
            console.print("[red]Unknown cache command[/red]")
            return 1


if __name__ == "__main__":
    sys.exit(main())
