"""Per-run HTML report generator.

Generates runs/{thread_id}/report.html from the Jinja2 template at
templates/report.html.j2.

See PLAN.md Section 7 for the full specification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from jinja2 import Template

from skillpipeline.models import PipelineState, SkillMap


def _generate_pipeline_mermaid(state: PipelineState) -> str:
    """Generate Mermaid graph LR of the pipeline with node status colors.

    Node colors:
    - completed (green): default fill:#90EE90
    - retried (yellow): fill:#FFD700
    - interrupted (orange): fill:#FFA500
    - flagged (red): fill:#FFB6C1
    - skipped (gray): fill:#D3D3D3

    Args:
        state: Pipeline state after run completion

    Returns:
        Mermaid graph LR source
    """
    validation_events = state.get("validation_events", [])

    # Determine status for each stage
    def _get_stage_status(stage: str) -> str:
        # Check for errors at this stage
        errors = [e for e in validation_events if e.stage == stage and e.severity == "error"]
        if errors:
            return "flagged"
        # Check for retries at this stage
        retries = [e for e in validation_events if e.stage == stage and e.retry_number > 0]
        if retries:
            return "retried"
        return "completed"

    # Build node list with styles
    nodes = []
    stages = ["ingest", "extract", "merge", "human_review", "relate", "validate", "persist"]

    # Determine if human_review was interrupted
    # Signal: topics_for_review.json exists AND approved_topics is None/empty
    thread_id = state.get("thread_id", "")
    review_file = Path(f"runs/{thread_id}/topics_for_review.json")
    human_review_interrupted = review_file.exists() and not state.get("approved_topics")

    for stage in stages:
        status = "completed"
        if stage == "human_review" and human_review_interrupted:
            status = "interrupted"
        elif stage in ["ingest", "extract", "merge", "relate", "validate", "persist"]:
            status = _get_stage_status(stage)

        # Node fills are applied via the classDef styles below (stage{status}).
        nodes.append(f'{stage}("{stage}"):::stage{status}')

    # Define styles
    styles = """
    classDef stagecompleted fill:#90EE90,stroke:#4CAF50,stroke-width:2px;
    classDef stageretried fill:#FFD700,stroke:#FFA500,stroke-width:2px;
    classDef stageinterrupted fill:#FFA500,stroke:#FF8C00,stroke-width:2px;
    classDef stageflagged fill:#FFB6C1,stroke:#FF6B6B,stroke-width:2px;
    classDef stageskipped fill:#D3D3D3,stroke:#9E9E9E,stroke-width:2px;
    """

    # Apply classes based on status
    class_defs = []
    for stage in stages:
        if stage == "human_review" and human_review_interrupted:
            class_defs.append(f" class {stage} stageinterrupted")
        elif stage in ["ingest", "extract", "merge", "relate", "validate", "persist"]:
            status = _get_stage_status(stage)
            class_defs.append(f" class {stage} stage{status}")
        else:
            class_defs.append(f" class {stage} stagecompleted")

    # Build edges
    edges = [
        "ingest --> extract",
        "extract --> merge",
        "merge -->|bypass| persist",
        "merge --> human_review",
        "human_review --> relate",
        "relate --> validate",
        "validate -->|retry| relate",
        "validate --> persist",
    ]

    # Filter conditional edges based on what actually happened
    # (simplified for now - showing all potential paths)
    final_edges = edges

    mermaid = "graph LR\n" + "\n".join(nodes) + "\n" + "\n".join(final_edges) + "\n" + styles + "\n".join(class_defs)
    return mermaid


def _generate_skill_map_mermaid(skill_map: SkillMap) -> str:
    """Generate Mermaid graph TD of topics and prerequisite relationships.

    Args:
        skill_map: The skill map with topics and relationships

    Returns:
        Mermaid graph TD source
    """
    if not skill_map.topics:
        return "graph TD\n    Empty[\"No topics extracted\"]"

    # Build nodes for each topic
    nodes = []
    for topic in skill_map.topics:
        # Escape quotes in topic name
        safe_name = topic.name.replace('"', "'")
        nodes.append(f'    {topic.id}["{safe_name} ({topic.difficulty})"]')

    # Build edges for prerequisite relationships
    edges = []
    for rel in skill_map.relationships:
        if rel.type == "prerequisite":
            edges.append(f"    {rel.from_id} ==>|prerequisite| {rel.to_id}")

    if not edges:
        edges.append("    %% No prerequisite relationships")

    mermaid = "graph TD\n" + "\n".join(nodes) + "\n" + "\n".join(edges)
    return mermaid


def _generate_non_prereq_relationships(
    skill_map: SkillMap,
) -> list[dict]:
    """Extract non-prerequisite relationships for table display.

    Args:
        skill_map: The skill map with topics and relationships

    Returns:
        List of dicts with from_name, to_name, type, rationale
    """
    if not skill_map.topics:
        return []

    # Build topic lookup
    topic_by_id = {t.id: t for t in skill_map.topics}

    non_prereqs = []
    for rel in skill_map.relationships:
        if rel.type != "prerequisite":
            from_topic = topic_by_id.get(rel.from_id)
            to_topic = topic_by_id.get(rel.to_id)
            if from_topic and to_topic:
                non_prereqs.append({
                    "from_name": from_topic.name,
                    "to_name": to_topic.name,
                    "type": rel.type,
                    "rationale": rel.rationale or "",
                })

    return non_prereqs


def _format_cost_usd(cost: float) -> str:
    """Format cost in USD with 4 decimal places."""
    return f"${cost:.4f}"


def _format_duration_ms(duration_ms: int) -> str:
    """Format duration in human-readable string."""
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    elif duration_ms < 60000:
        return f"{duration_ms / 1000:.1f}s"
    else:
        minutes = duration_ms // 60000
        seconds = (duration_ms % 60000) / 1000
        return f"{minutes}m {seconds:.0f}s"


def generate_report(
    skill_map: SkillMap,
    source_text: str,
    source_path: Optional[str] = None,
) -> str:
    """Generate the per-run HTML report.

    Args:
        skill_map: The skill map with topics, relationships, and metadata
        source_text: The original input markdown
        source_path: Optional source file path for display

    Returns:
        HTML report as a string
    """
    # Load template (templates/ is at repo root, not src/skillpipeline/)
    # __file__ is src/skillpipeline/report.py, so parent.parent.parent is repo root
    template_path = Path(__file__).parent.parent.parent / "templates" / "report.html.j2"
    template_content = template_path.read_text(encoding="utf-8")
    template = Template(template_content)

    # Extract pipeline state info from metadata
    metadata = skill_map.metadata
    thread_id = metadata.thread_id
    status = metadata.status

    # Build context for template
    context = {
        "thread_id": thread_id,
        "source_name": source_path or "unknown",
        "started_at": metadata.started_at,
        "ended_at": metadata.ended_at or "In progress",
        "status": status,
        "total_cost_usd": _format_cost_usd(metadata.total_cost_usd),
        "total_input_tokens": metadata.total_input_tokens,
        "total_output_tokens": metadata.total_output_tokens,
        "pipeline_mermaid": _generate_pipeline_mermaid({"thread_id": thread_id, "validation_events": metadata.validation_events, "stage_telemetry": metadata.stage_telemetry}),
        "skill_map_mermaid": _generate_skill_map_mermaid(skill_map),
        "non_prereq_relationships": _generate_non_prereq_relationships(skill_map),
        "stage_telemetry": metadata.stage_telemetry,
        "validation_events": metadata.validation_events,
        "source_text": source_text[:2000] + "..." if len(source_text) > 2000 else source_text,
        "source_truncated": len(source_text) > 2000,
        "generated_at": datetime.now(UTC).isoformat(),
        "format_cost": _format_cost_usd,
        "format_duration": _format_duration_ms,
    }

    return template.render(**context)
