"""LangGraph StateGraph for the skill pipeline.

Three sub-step implementation:
12a: Linear graph with 7 nodes (no conditional edges, no interrupt)
12b: Add conditional edges
12c: Add interrupt and SqliteSaver

See PLAN.md Sections 2.1 and 12 Step 12 for the full specification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import operator
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


def create_graph(llm_client: LLMClient | None = None) -> StateGraph:
    """Create the LangGraph StateGraph for the skill pipeline.

    Sub-step 12a: Linear graph with 7 nodes.

    INGEST -> EXTRACT -> MERGE -> HUMAN_REVIEW -> RELATE -> VALIDATE -> PERSIST -> END

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

    # Add nodes (linear flow for now)
    graph.add_node("ingest", make_ingest_node())
    graph.add_node("extract", make_extract_node(llm_client))
    graph.add_node("merge", merge_topics)
    graph.add_node("human_review", human_review_node)
    graph.add_node("relate", make_relate_node(llm_client))
    graph.add_node("validate", validate_relationships)
    graph.add_node("persist", _persist_node)

    # Set entry point
    graph.set_entry_point("ingest")

    # Add edges (linear)
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "merge")
    graph.add_edge("merge", "human_review")
    graph.add_edge("human_review", "relate")
    graph.add_edge("relate", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)

    return graph
