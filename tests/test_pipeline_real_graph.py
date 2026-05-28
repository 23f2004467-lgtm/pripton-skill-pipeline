"""Real-graph end-to-end test — the one that exercises the live path.

Unlike test_pipeline_e2e.py (which mocks create_graph), this compiles the REAL
LangGraph, opens a REAL AsyncSqliteSaver against a tmp_path, and drives it with
ainvoke, swapping only the LLM boundary for a FakeLLMClient. It would have caught
all three live-path bugs: the checkpointer context-manager misuse, sync invoke()
on async nodes, and the sync SqliteSaver under async.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

from skillpipeline.llm import FakeLLMClient
from skillpipeline.pipeline import run

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_real_graph_async_run_produces_skill_map(tmp_path, monkeypatch):
    # The stages load prompts via a cwd-relative path, so mirror them under the
    # tmp working dir to keep the test isolated from the repo's runs/ output.
    shutil.copytree(
        REPO_ROOT / "src/skillpipeline/prompts",
        tmp_path / "src/skillpipeline/prompts",
    )
    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "doc.md"
    input_file.write_text("# Section One\n\nContent about A and B.", encoding="utf-8")

    # One extract response (2 topics) then one relate response (1 clean edge).
    # A single-section doc means exactly one extract call then one relate call.
    fake = FakeLLMClient([
        {"tool_use": {"name": "record_topics", "input": {"topics": [
            {"id": "topic-a", "name": "Topic A", "description": "About A",
             "category": "core", "difficulty": "beginner"},
            {"id": "topic-b", "name": "Topic B", "description": "About B",
             "category": "core", "difficulty": "intermediate"},
        ]}}, "input_tokens": 50, "output_tokens": 20},
        {"tool_use": {"name": "record_relationships", "input": {"relationships": [
            {"from_id": "topic-a", "to_id": "topic-b",
             "type": "prerequisite", "rationale": "A is needed before B"},
        ]}}, "input_tokens": 40, "output_tokens": 15},
    ])

    # Swap only the LLM boundary; the graph, checkpointer, and persistence are real.
    with patch("skillpipeline.pipeline.GroqLLMClient", return_value=fake):
        result = run(str(input_file), always_review=False, no_cache=True)

    # Completed (not paused for review) and wrote a real report.
    assert "report.html" in result

    run_dirs = list((tmp_path / "runs").glob("run_*"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    # The async checkpointer actually persisted state to disk.
    assert (run_dir / "state.sqlite").exists()

    # A well-formed SkillMap was produced.
    skill_map = json.loads((run_dir / "skill_map.json").read_text(encoding="utf-8"))
    assert {t["id"] for t in skill_map["topics"]} == {"topic-a", "topic-b"}
    assert len(skill_map["relationships"]) == 1
    assert skill_map["relationships"][0]["from_id"] == "topic-a"
    assert skill_map["metadata"]["status"] == "complete"

    assert (run_dir / "report.html").exists()
    assert (Path("runs") / "index.html").exists()
