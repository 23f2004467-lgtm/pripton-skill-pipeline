"""LangGraph StateGraph for the skill pipeline.

Three sub-step implementation:
12a: Linear graph with 7 nodes (no conditional edges, no interrupt)
12b: Add conditional edges
12c: Add interrupt and SqliteSaver

See PLAN.md Sections 2.1 and 12 Step 12 for the full specification.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from skillpipeline.extract import make_extract_node
from skillpipeline.human_review import human_review_node
from skillpipeline.ingest import make_ingest_node
from skillpipeline.llm import GroqLLMClient, LLMClient
from skillpipeline.merge import merge_topics
from skillpipeline.models import PipelineState
from skillpipeline.relate import make_relate_node
from skillpipeline.validate import validate_relationships

if TYPE_CHECKING:
    from langgraph.graph import CompiledStateGraph


def _persist_node(state: PipelineState) -> dict:
    """Persist node - placeholder for now.

    The actual persist logic will be implemented in pipeline.py (Step 15).

    Args:
        state: Current pipeline state

    Returns:
        State update with status
    """
    return {"status": "complete"}


def _should_bypass_to_persist(state: PipelineState) -> Literal["persist", "human_review"]:
    """Conditional edge from merge: empty extraction bypass.

    If len(merged_topics) == 0, route directly to persist (flagged).
    Otherwise, route to human_review.

    Args:
        state: Current pipeline state

    Returns:
        Next node name: "persist" or "human_review"
    """
    merged_topics = state.get("merged_topics")
    if merged_topics is not None and len(merged_topics) == 0:
        return "persist"
    return "human_review"


def _should_retry_or_finish(state: PipelineState) -> Literal["relate", "persist"]:
    """Conditional edge from validate: retry logic.

    If errors and relate_retries < 3, route back to relate with feedback.
    Otherwise, route to persist.

    Args:
        state: Current pipeline state

    Returns:
        Next node name: "relate" or "persist"
    """
    relate_retries = state.get("relate_retries", 0)
    max_retries = 3  # From PLAN.md Section 6.2

    # Check if validation found errors
    validation_events = state.get("validation_events", [])
    relate_errors = [e for e in validation_events if e.stage == "relate" and e.severity == "error"]

    if relate_errors and relate_retries < max_retries:
        # Need to retry
        return "relate"
    return "persist"


def create_graph(
    llm_client: Optional[LLMClient] = None,
    thread_id: Optional[str] = None,
) -> CompiledStateGraph:
    """Create the LangGraph StateGraph for the skill pipeline.

    Sub-step 12c: Adds SqliteSaver for state persistence.

    INGEST -> EXTRACT -> MERGE -> [conditional] -> HUMAN_REVIEW -> RELATE -> VALIDATE -> [conditional] -> PERSIST -> END

    Conditional edges:
    - From merge: if len(merged_topics) == 0, route to persist (bypass), else to human_review
    - From validate: if errors and relate_retries < 3, route to relate (retry), else to persist

    Args:
        llm_client: LLM client for extract and relate nodes. If None, creates GroqLLMClient.
        thread_id: Thread ID for this run. If provided, configures SqliteSaver at
                   runs/{thread_id}/state.sqlite. The directory is created if needed.

    Returns:
        Compiled StateGraph ready for invocation (with checkpointer if thread_id provided)
    """
    # Create LLM client if not provided
    if llm_client is None:
        llm_client = GroqLLMClient()

    # Set up SqliteSaver if thread_id is provided
    checkpointer = None
    if thread_id is not None:
        run_dir = Path("runs") / thread_id
        run_dir.mkdir(parents=True, exist_ok=True)
        db_path = run_dir / "state.sqlite"
        checkpointer = SqliteSaver.from_conn_string(str(db_path))

    # Create the graph with PipelineState as the state type
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("ingest", make_ingest_node())
    graph.add_node("extract", make_extract_node(llm_client))
    graph.add_node("merge", merge_topics)
    graph.add_node("human_review", human_review_node)
    graph.add_node("relate", make_relate_node(llm_client))
    graph.add_node("validate", validate_relationships)
    graph.add_node("persist", _persist_node)

    # Set entry point
    graph.set_entry_point("ingest")

    # Add edges (linear up to merge)
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "merge")

    # Conditional edge from merge
    graph.add_conditional_edges(
        "merge",
        _should_bypass_to_persist,
        {
            "persist": "persist",
            "human_review": "human_review",
        },
    )

    graph.add_edge("human_review", "relate")

    # Conditional edge from validate (retry loop)
    graph.add_conditional_edges(
        "validate",
        _should_retry_or_finish,
        {
            "relate": "relate",
            "persist": "persist",
        },
    )

    graph.add_edge("persist", END)

    # Compile with checkpointer
    # checkpointer is passed to compile(), not StateGraph.__init__()
    return graph.compile(checkpointer=checkpointer)
