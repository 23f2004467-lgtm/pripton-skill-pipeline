"""LangGraph StateGraph for the skill pipeline.

Three sub-step implementation:
12a: Linear graph with 7 nodes (no conditional edges, no interrupt)
12b: Add conditional edges
12c: Add interrupt and SqliteSaver

See PLAN.md Sections 2.1 and 12 Step 12 for the full specification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Interrupt, interrupt

from skillpipeline.extract import make_extract_node
from skillpipeline.human_review import human_review_node
from skillpipeline.ingest import make_ingest_node
from skillpipeline.llm import AnthropicLLMClient, LLMClient
from skillpipeline.merge import merge_topics
from skillpipeline.models import PipelineState
from skillpipeline.relate import make_relate_node
from skillpipeline.validate import validate_relationships


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


def create_graph(llm_client: LLMClient | None = None) -> StateGraph:
    """Create the LangGraph StateGraph for the skill pipeline.

    Sub-step 12b: Linear graph with two conditional edges.

    INGEST -> EXTRACT -> MERGE -> [conditional] -> HUMAN_REVIEW -> RELATE -> VALIDATE -> [conditional] -> PERSIST -> END

    Conditional edges:
    - From merge: if len(merged_topics) == 0, route to persist (bypass), else to human_review
    - From validate: if errors and relate_retries < 3, route to relate (retry), else to persist

    Args:
        llm_client: LLM client for extract and relate nodes. If None, creates AnthropicLLMClient.

    Returns:
        Configured StateGraph ready for invocation
    """
    # Create LLM client if not provided
    if llm_client is None:
        llm_client = AnthropicLLMClient()

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

    return graph
