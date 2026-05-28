"""Pipeline orchestrator — high-level run/review/resume functions.

Wires together the graph, cache, persistence, and report generation.

See PLAN.md Section 9 for CLI surface and Section 5.7 for persist behavior.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from skillpipeline.cache import Cache, get_cache
from skillpipeline.graph import create_graph
from skillpipeline.human_review import validate_review_topics
from skillpipeline.index import generate_index
from skillpipeline.llm import GroqLLMClient, LLMClient
from skillpipeline.models import (
    PipelineState,
    RunMetadata,
    SkillMap,
)
from skillpipeline.report import generate_report


def _compute_source_id(raw_bytes: bytes) -> str:
    """Compute SHA-256 hash of input bytes for idempotency.

    Args:
        raw_bytes: The raw input file bytes

    Returns:
        Hexadecimal SHA-256 hash
    """
    return hashlib.sha256(raw_bytes).hexdigest()


def _generate_thread_id(source_id: str) -> str:
    """Generate a unique thread ID for this run.

    Format: run_{YYYYMMDD-HHMMSS}_{short-hash}

    Args:
        source_id: The content hash of the input

    Returns:
        Unique thread ID
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    short_hash = source_id[:8]
    return f"run_{timestamp}_{short_hash}"


async def _ainvoke_graph(
    thread_id: str,
    llm_client: LLMClient,
    graph_input: Any,
) -> PipelineState:
    """Compile and async-invoke the graph under an AsyncSqliteSaver.

    The extract/relate nodes are async, so the graph must be driven via ainvoke,
    which requires an async checkpointer. AsyncSqliteSaver.from_conn_string is an
    async context manager whose connection must wrap compile+invoke, so the graph
    is built here rather than ahead of time. The sqlite file is shared across
    processes, which is what makes interrupt/resume durable.

    Args:
        thread_id: Thread ID for this run (also the runs/ subdir + db location).
        llm_client: LLM client for extract and relate nodes.
        graph_input: Either the initial state dict (run) or a Command (resume).

    Returns:
        Final pipeline state (may be incomplete if interrupted).
    """
    run_dir = Path("runs") / thread_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = run_dir / "state.sqlite"
    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        graph = create_graph(llm_client=llm_client, checkpointer=checkpointer)
        return await graph.ainvoke(graph_input, config)


def _run_graph(
    state: PipelineState,
    llm_client: LLMClient,
    thread_id: str,
) -> PipelineState:
    """Run the LangGraph state machine to completion or interrupt.

    Args:
        state: Initial pipeline state
        llm_client: LLM client for API calls
        thread_id: Thread ID for this run

    Returns:
        Final pipeline state (may be incomplete if interrupted)

    Raises:
        GraphInterrupt: If the human_review node interrupts; the caller handles it.
    """
    input_state = {
        "source_path": state.get("source_path"),
        "raw_text": state.get("raw_text"),
        "thread_id": thread_id,
        "always_review": state.get("always_review", False),
    }
    return asyncio.run(_ainvoke_graph(thread_id, llm_client, input_state))


def _persist_results(
    state: PipelineState,
    source_text: str,
    source_path: str | None,
    thread_id: str,
    cache: Cache | None = None,
) -> SkillMap:
    """Persist all outputs: skill_map, run_log, report, index, cache.

    Args:
        state: Final pipeline state
        source_text: Original input markdown
        source_path: Original source file path
        thread_id: Thread ID for this run
        cache: Cache instance (optional)

    Returns:
        The persisted SkillMap
    """
    run_dir = Path("runs") / thread_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build RunMetadata from state
    metadata = RunMetadata(
        thread_id=thread_id,
        source_id=state.get("source_id", ""),
        started_at=state.get("started_at", datetime.now(UTC).isoformat()),
        ended_at=datetime.now(UTC).isoformat(),
        status=state.get("status", "complete"),
        total_cost_usd=sum(t.estimated_cost_usd for t in state.get("stage_telemetry", [])),
        total_input_tokens=sum(t.input_tokens for t in state.get("stage_telemetry", [])),
        total_output_tokens=sum(t.output_tokens for t in state.get("stage_telemetry", [])),
        stage_telemetry=state.get("stage_telemetry", []),
        validation_events=state.get("validation_events", []),
        cache_hit=state.get("cache_hit", False),
    )

    # Build SkillMap from state
    approved_topics = state.get("approved_topics", [])
    relationships = state.get("relationships", [])

    skill_map = SkillMap(
        source_id=metadata.source_id,
        topics=approved_topics,
        relationships=relationships,
        metadata=metadata,
    )

    # Write skill_map.json
    (run_dir / "skill_map.json").write_text(
        skill_map.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # Write run_log.json with merged_topics for audit
    merged_topics = state.get("merged_topics", [])
    run_log_data = {
        "metadata": metadata.model_dump(),
        "merged_topics": [t.model_dump() for t in merged_topics],
        "source_path": source_path or "unknown",
    }
    (run_dir / "run_log.json").write_text(
        json.dumps(run_log_data, indent=2),
        encoding="utf-8",
    )

    # Generate and write report.html
    report_html = generate_report(skill_map, source_text, source_path)
    (run_dir / "report.html").write_text(report_html, encoding="utf-8")

    # Write skill_map.mmd for offline review
    from skillpipeline.report import _generate_skill_map_mermaid
    mermaid_source = _generate_skill_map_mermaid(skill_map)
    (run_dir / "skill_map.mmd").write_text(mermaid_source, encoding="utf-8")

    # Write to cache if run completed successfully
    if cache is not None and metadata.status == "complete":
        cache.put(
            source_id=metadata.source_id,
            skill_map=skill_map,
            run_metadata=metadata,
        )

    # Regenerate runs/index.html
    index_html = generate_index()
    (Path("runs") / "index.html").write_text(index_html, encoding="utf-8")

    return skill_map


def run(
    input_path: str,
    always_review: bool = False,
    no_cache: bool = False,
) -> str:
    """Run the full pipeline on an input file.

    Args:
        input_path: Path to input markdown file
        always_review: If True, always trigger human review interrupt
        no_cache: If True, bypass cache read/write

    Returns:
        Path to the generated report.html (or message if interrupted)
    """
    input_file = Path(input_path)
    raw_bytes = input_file.read_bytes()
    source_text = raw_bytes.decode("utf-8", errors="replace")

    # Compute source_id for idempotency
    source_id = _compute_source_id(raw_bytes)

    # Check cache
    cache = None if no_cache else get_cache()
    if cache is not None and not no_cache:
        cached_entry = cache.get(source_id)
        if cached_entry is not None:
            # Cache hit - create new run directory with cached results
            thread_id = _generate_thread_id(source_id)
            run_dir = Path("runs") / thread_id
            run_dir.mkdir(parents=True, exist_ok=True)

            # Copy cached skill_map
            skill_map = cached_entry.skill_map
            metadata = cached_entry.run_metadata

            # Update metadata for this run
            metadata.cache_hit = True
            metadata.thread_id = thread_id

            # Persist with cache_hit=True
            _persist_results(
                {
                    "source_id": source_id,
                    "approved_topics": skill_map.topics,
                    "relationships": skill_map.relationships,
                    "status": "complete",
                    "cache_hit": True,
                },
                source_text,
                str(input_file),
                thread_id,
                cache,
            )

            return f"runs/{thread_id}/report.html (cache hit)"

    # Cache miss or no cache - run full pipeline
    thread_id = _generate_thread_id(source_id)

    # Create LLM client
    llm_client = GroqLLMClient()

    # Create initial state
    state: PipelineState = {
        "source_path": str(input_file),
        "raw_text": source_text,
        "source_id": source_id,
        "always_review": always_review,
        "started_at": datetime.now(UTC).isoformat(),
    }

    # Run graph
    try:
        final_state = _run_graph(state, llm_client, thread_id)

        # Persist results
        _persist_results(final_state, source_text, str(input_file), thread_id, cache)

        return f"runs/{thread_id}/report.html"

    except GraphInterrupt as e:
        # Human review interrupt
        payload = e.args[0] if e.args else {}
        review_file_path = payload.get("review_file_path", "")
        return f"Review required: {review_file_path}. Run 'pipeline resume {thread_id}' after editing."


def review(thread_id: str) -> str:
    """Open topics_for_review.json in the user's editor.

    Args:
        thread_id: Thread ID of the run to review

    Returns:
        Path to the review file (or message if editor not available)
    """
    review_file = Path("runs") / thread_id / "topics_for_review.json"

    if not review_file.exists():
        return f"No review file found for thread {thread_id}"

    editor = os.environ.get("EDITOR")
    if editor:
        subprocess.call([editor, str(review_file)])
        return f"Opened {review_file} in {editor}"
    else:
        return f"Set $EDITOR to edit, or edit manually: {review_file}"


def resume(thread_id: str) -> str:
    """Resume a pipeline run from human review interrupt.

    Args:
        thread_id: Thread ID of the run to resume

    Returns:
        Path to the generated report.html (or error message)
    """
    # Load topics_for_review.json
    review_file = Path("runs") / thread_id / "topics_for_review.json"

    if not review_file.exists():
        return f"Error: No review file found for thread {thread_id}"

    # Validate review file
    try:
        review_data = json.loads(review_file.read_text(encoding="utf-8"))
        approved_topics = validate_review_topics(review_data)
    except (json.JSONDecodeError, ValueError) as e:
        return f"Error: Invalid review file: {e}"

    # Load original source text from run_log
    run_log_file = Path("runs") / thread_id / "run_log.json"
    if not run_log_file.exists():
        return f"Error: No run log found for thread {thread_id}"

    run_log_data = json.loads(run_log_file.read_text(encoding="utf-8"))
    source_path = run_log_data.get("source_path", "unknown")

    # Read source file for report generation
    try:
        source_text = Path(source_path).read_text(encoding="utf-8")
    except Exception:
        # If source file not available, use empty text
        source_text = ""

    # Create LLM client
    llm_client = GroqLLMClient()

    try:
        # Command(resume=...) passes the approved topics to the human_review node.
        # Same async path as run(): the saver reopens the existing state.sqlite.
        final_state = asyncio.run(
            _ainvoke_graph(thread_id, llm_client, Command(resume=approved_topics))
        )

        # Persist results
        _persist_results(final_state, source_text, source_path, thread_id, get_cache())

        return f"runs/{thread_id}/report.html"

    except GraphInterrupt as e:
        # Should not happen on resume, but handle gracefully
        return f"Unexpected interrupt: {e}"
