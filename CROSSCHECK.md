# Parallel Cross-Check: Specification vs. Implementation

**Last updated:** Current session  
**Source spec:** PLAN.md (21-step build checklist, Sections 1–14)  
**Workspace root:** `/Users/dheeraj/Desktop/outputs/`

---

## Executive Summary

**Project Status:** ~35% implementation. The core stages up through validation are implemented; orchestration, relationship extraction, human review, persistence, CLI, report/index, and CI remain.

| Category | Required | Exists | % Complete |
|----------|----------|--------|------------|
| **Documentation & Config** | 9 files | 9 files | ✅ 100% |
| **Domain Models** | 1 file (`models.py`) | 1 file | ✅ 100% |
| **LLM & Transport** | 1 file | ✅ | 100% |
| **Pipeline Stages** | 7 files (ingest, extract, merge, relate, validate, human_review) | 5 files | ✅ 71% |
| **Helpers & Cache** | 2 files (retry.py, cache.py) | 0 files | ❌ 0% |
| **Graph Orchestration** | 1 file (`graph.py`) | 0 files | ❌ 0% |
| **Reports & UI** | 3 files (report.py, index.py, + 2 templates) | 0 files | ❌ 0% |
| **CLI & Main** | 2 files (`cli.py`, `__main__.py`) | 0 files | ❌ 0% |
| **Stats** | 1 file (`stats.py`) | 0 files | ❌ 0% |
| **Tests** | 9+ test files | 6 files | ✅ 67% |
| **Prompts** | 2–3 prompt files | 2 files | ✅ 67% |
| **Templates** | 2 Jinja2 templates | 0 files | ❌ 0% |

---

## ✅ COMPLETED (Step 1 + Step 2 Partial)

### Documentation & Setup Files
- [x] `.env.example` – ANTHROPIC_API_KEY placeholder
- [x] `.python-version` – Python 3.11
- [x] `.gitignore` – Standard Python ignores
- [x] `pyproject.toml` – All dependencies pinned (langgraph, anthropic, pydantic, networkx, structlog, rich, jinja2); dev deps (pytest, pytest-asyncio, ruff, mypy); CLI entry point defined as `skillpipeline = "skillpipeline.__main__:main"`
- [x] `PLAN.md` – Full 21-step spec
- [x] `AGENTS.md` – Behavioral guidelines for the agent
- [x] `DESIGN.md` – Design rationale (read separately)
- [x] `README.md` – Getting-started guide
- [x] `RESEARCH.md` – Tool landscape & reliability discussion

### Directory Structure
- [x] `src/skillpipeline/__init__.py` – Empty (correct)
- [x] `src/skillpipeline/prompts/` – Directory exists, empty
- [x] `src/skillpipeline/templates/` – Directory exists, empty
- [x] `tests/__init__.py` – Empty (correct)
- [x] `tests/fixtures/` – Directory exists (will hold mock LLM responses)
- [x] `runs/` – Directory exists, will hold thread outputs
- [x] `.cache/` – Directory exists, will hold content-addressed cache
- [x] `samples/` – Directory exists; should contain 3 markdown test inputs

### Domain Models (Step 2)
- [x] `src/skillpipeline/models.py` – **Complete per Section 4**
  - `Section` (section id, heading, body, order)
  - `Document` (source_id [SHA-256], raw_text, sections)
  - `Topic` (id pattern validation, name/description/category/difficulty, source_section_id)
  - `Relationship` (from_id, to_id, type, rationale, no-self-loops validator)
  - `ValidationEvent` (stage, severity, code, message, retry_number, flagged)
  - `StageTelemetry` (stage, timing, LLM calls, tokens, cost)
  - `RunMetadata` (thread_id, status, cost rollup, telemetry, events)
  - `SkillMap` (topics, relationships, metadata)
  - `PipelineState` (TypedDict with operator.add for accumulator fields)

---

## ❌ NOT STARTED

### Step 3: LLM Client Wrapper (`src/skillpipeline/llm.py`)
**Spec: Section 5.0 + Section 12 Step 3**

Required:
- [ ] `LLMClient` protocol (abstract base)
- [ ] `AnthropicLLMClient` (concrete implementation)
  - Reads `ANTHROPIC_API_KEY` from env
  - Tool-use calls via anthropic SDK
  - Transport-level retry: max 5, exponential backoff + jitter, base 1s, only on 5xx or RateLimitError
  - Tracks input_tokens, output_tokens, cost_usd per call
- [ ] `FakeLLMClient` (for tests without API key)
  - Returns fixture responses from `tests/fixtures/*.json`
  - No actual API calls

Constants:
- [ ] `MODEL = "claude-sonnet-4-5"`
- [ ] `TEMPERATURE = 0.0`
- [ ] `MAX_TOKENS = 4096`
- [ ] `INPUT_COST_PER_MTOK = 3.00`
- [ ] `OUTPUT_COST_PER_MTOK = 15.00`

---

### Step 4: Ingest Stage (`src/skillpipeline/ingest.py`)
**Spec: Section 5.1 + Section 12 Step 4**

Required:
- [ ] `ingest_node(state)` → state.document
- [ ] Heading split logic: `^#{1,2} ` regex or equivalent
- [ ] Single-section fallback if no headings
- [ ] source_id = SHA-256(raw_bytes)
- [ ] Section ID assignment: `f"section-{order}"`
- [ ] Empty-section filtering

Tests (`tests/test_ingest.py`):
- [ ] Heading split edge cases
- [ ] Single-section fallback
- [ ] source_id determinism
- [ ] UTF-8 with replacement

---

### Step 5: Extract Stage (`src/skillpipeline/extract.py`)
**Spec: Section 5.2 + Section 12 Step 5**

Required:
- [ ] `extract_node(state, llm_client)` → appends to state.extracted_topics
- [ ] Async fan-out: `asyncio.gather(*[extract_one_section(...) for s in sections])`
- [ ] Per-section retry loop (max 3):
  - Tool-use call with EXTRACT_TOPICS_TOOL
  - Pydantic parsing of response
  - Validation: unique IDs, unique names, tool-use block present
  - Retry on validation error; feedback into next prompt
  - Max retries → flag + accept empty list
- [ ] Populates state.extract_retries (section_id → count) and state.extract_feedback (section_id → error)
- [ ] Logs `ValidationEvent` per retry attempt
- [ ] Tracks LLM tokens and cost in state.stage_telemetry

Prompt files:
- [ ] `prompts/system.txt` – Role of the assistant
- [ ] `prompts/extract_topics.txt` – User prompt with section content + retry feedback

Tests (`tests/test_extract.py`):
- [ ] Valid extraction
- [ ] Malformed tool response
- [ ] Retry with feedback
- [ ] Max retries → flag
- [ ] Empty section output

---

### Step 6: Merge Stage (`src/skillpipeline/merge.py`)
**Spec: Section 5.3 + Section 12 Step 6**

Required:
- [ ] `merge_node(state)` → state.merged_topics
- [ ] Dedup by normalized name (strip + lowercase)
- [ ] Canonical record selection (longest description; lowest difficulty)
- [ ] Category conflict resolution (most-frequent)
- [ ] Logs `ValidationEvent` for duplicates and conflicts
- [ ] Empty-extraction short-circuit flag (`len(merged_topics) == 0`)
- [ ] Sets source_section_id on merged topics

Tests (`tests/test_merge.py`):
- [ ] Dedup on normalized name
- [ ] Difficulty/category conflict resolution
- [ ] Logs appropriate validation events

---

### Step 7: Validate Stage (`src/skillpipeline/validate.py`)
**Spec: Section 5.6 + Section 12 Step 7**

Required:
- [ ] `validate_node(state)` → either proceeds or routes back to relate
- [ ] Seven validation codes (SCHEMA_VIOLATION, DANGLING_FROM_REF, DANGLING_TO_REF, SELF_LOOP, DUPLICATE_EDGE, CYCLE_IN_PREREQUISITES, ORPHAN_TOPIC)
- [ ] Cycle detection via `networkx.simple_cycles` on prerequisite edges only
- [ ] Decision logic:
  - No errors → proceed to persist
  - Errors and `relate_retries < 3` → increment, set feedback, route back to relate
  - Errors and `relate_retries >= 3` → flag, drop invalid rels, proceed to persist

Tests (`tests/test_validate.py`):
- [ ] Each validation code triggered by constructed bad input
- [ ] Cycle detection (prerequisite only)
- [ ] Orphan topics (warning, not error)

---

### Step 8: Retry-with-Feedback Helper (`src/skillpipeline/retry.py`)
**Spec: Section 6 + Section 12 Step 8**

Required:
- [ ] Feedback formatting for prompts (both extract and relate layers)
- [ ] Max-retries constants and decision logic
- [ ] Fixed delay between retries (0.2s)

Tests (`tests/test_retry.py`):
- [ ] Feedback prompt construction
- [ ] Max retries bound

---

### Step 9: Relate Stage (`src/skillpipeline/relate.py`)
**Spec: Section 5.5 + Section 12 Step 9**

Required:
- [ ] `relate_node(state, llm_client)` → state.relationships
- [ ] Tool-use call with EXTRACT_RELATIONSHIPS_TOOL
- [ ] Validation: IDs must be in approved topic set
- [ ] Retry feedback on validation error
- [ ] Tracks LLM cost and tokens

Prompt files:
- [ ] `prompts/extract_relationships.txt` – User prompt with topic list

Tests (integrated in test_graph or separate test_relate):
- [ ] Valid relationship extraction
- [ ] Retry with feedback

---

### Step 10: Human-Review Stage (`src/skillpipeline/human_review.py`)
**Spec: Section 5.4 + Section 12 Step 10**

Required:
- [ ] `human_review_node(state)` – conditional interrupt
- [ ] Interrupt if: any retries occurred OR always_review=True
- [ ] Writes `runs/{thread_id}/topics_for_review.json`
- [ ] Sets status to `awaiting_review`
- [ ] Calls `langgraph.types.interrupt(payload)` conditionally
- [ ] Resume logic: validates topics_for_review.json, resumes graph

Tests (test_graph):
- [ ] No interrupt when no retries and no always-review
- [ ] Interrupt when retries present
- [ ] Interrupt when always-review=True
- [ ] Resume with validation

---

### Step 11: Cache (`src/skillpipeline/cache.py`)
**Spec: Section 10 + Section 12 Step 11**

Required:
- [ ] `.cache/{source_id}.json` read/write
- [ ] Cache hit → copy cached skill_map, no LLM calls, cache_hit=True
- [ ] Cache miss → run pipeline, populate cache on completion
- [ ] Flagged and awaiting-review runs NOT cached
- [ ] `--no-cache` bypass both read and write

Tests (`tests/test_cache.py`):
- [ ] Hit returns cached
- [ ] Miss runs pipeline
- [ ] Flagged runs don't populate cache
- [ ] --no-cache bypasses

---

### Step 12: Graph Orchestration (`src/skillpipeline/graph.py`)
**Spec: Sections 2.1, 5.4, 12 Step 12**

Required:
- [ ] LangGraph `StateGraph` with 7 nodes: ingest, extract, merge, human_review, relate, validate, persist
- [ ] Conditional edges:
  - `merge → persist` if `len(merged_topics) == 0` (short-circuit)
  - `validate → relate` if errors and `relate_retries < 3` (retry loop)
- [ ] `human_review` uses `interrupt()` conditionally on retries/always-review
- [ ] `SqliteSaver` at `runs/{thread_id}/state.sqlite`
- [ ] State fully serializable

Tests (`tests/test_graph.py`):
- [ ] Graph compiles
- [ ] Empty-extraction short-circuit
- [ ] Interrupt conditions (no retry/no always-review → skip; one retry → interrupt; always-review → interrupt)
- [ ] Resume with validated topics_for_review.json

---

### Step 13: Report Generator (`src/skillpipeline/report.py` + `templates/report.html.j2`)
**Spec: Section 7 + Section 12 Step 13**

Required:
- [ ] Jinja2 render of report.html.j2
- [ ] Sections: header, pipeline diagram, skill map, stage telemetry, validation events, source, footer
- [ ] Mermaid for pipeline diagram (colored by outcome: green/yellow/orange/red) and skill map (prerequisite edges)
- [ ] Inline CSS + JS; single external CDN (Mermaid script)

---

### Step 14: Runs-Index (`src/skillpipeline/index.py` + `templates/index.html.j2`)
**Spec: Section 8 + Section 12 Step 14**

Required:
- [ ] Regenerated at end of every run
- [ ] Airflow-grid-style operator view
- [ ] Top stats banner (total runs, success rate, flag rate, awaiting-review count, total spend)
- [ ] Filter bar (status, date range) with client-side JS filtering
- [ ] Grid table: thread_id, source, started_at, duration, status, per-stage cells (green/yellow/orange/red), cost
- [ ] Pure HTML + inline CSS + minimal JS

---

### Step 15: Pipeline Orchestrator (`src/skillpipeline/pipeline.py`)
**Spec: Section 12 Step 15**

Required:
- [ ] High-level `run()`, `review()`, `resume()` functions
- [ ] Wires graph, cache, persistence, report generation

---

### Step 16: Stats Command (`src/skillpipeline/stats.py`)
**Spec: Section 9 + Section 12 Step 16**

Required:
- [ ] `stats` subcommand
- [ ] Walks `runs/`, loads `run_log.json`, aggregates metrics
- [ ] Prints Rich table (or `--json`)

---

### Step 17: CLI (`src/skillpipeline/cli.py` + `src/skillpipeline/__main__.py`)
**Spec: Section 9 + Section 12 Step 17**

Required:
- [ ] Argparse subcommands:
  - `run <input.md> [--always-review] [--no-cache]`
  - `review <thread_id>`
  - `resume <thread_id>`
  - `stats [--json]`
  - `cache list` / `cache clear`
- [ ] Prints thread_id + report path
- [ ] Exits on interrupt with clean message

---

### Step 18: End-to-End Test (`tests/test_pipeline_e2e.py`)
**Spec: Section 12 Step 18**

Required:
- [ ] Full pipeline with FakeLLMClient
- [ ] Test all three samples: clean (happy path), messy (retries), adversarial (flagged)
- [ ] Assert final SkillMap structure

---

### Step 19: CI Configuration (`.github/workflows/ci.yml`)
**Spec: Section 11.3 + Section 12 Step 19**

Required:
- [ ] Lint, type-check, tests on push
- [ ] `ruff check .`
- [ ] `mypy src`
- [ ] `pytest -v`

---

### Step 20: Sample Inputs (`samples/`)
**Spec: Section 12 Step 20**

Required:
- [ ] `clean_roadmap.md` – Happy-path markdown (well-formed, few extractions issues)
- [ ] `messy_tutorial.md` – Triggers retries; tests retry-with-feedback
- [ ] `adversarial_prose.md` – Triggers flags; tests max-retries behavior

Status: **samples/ directory exists; files should be committed**

---

### Step 21: Live Run Pass
**Spec: Section 12 Step 21**

Required:
- [ ] Run full pipeline against real Anthropic API
- [ ] Generate runs/outputs for reviewer
- [ ] Screenshots of report.html and index.html in DESIGN.md

---

## Build Order Dependencies

```
Step 1 (Skeleton) ✅
  ↓
Step 2 (Models) ✅
  ↓
Step 3 (LLM Client) → Step 4, 5, 9
  ↓
Step 4 (Ingest) → Step 5 (can write tests after)
  ↓
Step 5 (Extract) → Step 6 (needs merged_topics)
  ↓
Step 6 (Merge) → Step 7, 10
  ↓
[Step 8 (Retry Helper) can run in parallel with Steps 5–7]
  ↓
Step 7 (Validate) → Step 12 (graph)
  ↓
Step 9 (Relate) → Step 12
  ↓
Step 10 (Human Review) → Step 12
  ↓
Step 11 (Cache) → Step 15
  ↓
Step 12 (Graph) → Step 15
  ↓
Step 13 (Report) → Step 15
  ↓
Step 14 (Runs-Index) → Step 15
  ↓
Step 15 (Pipeline) → Step 17
  ↓
Step 16 (Stats) → Step 17
  ↓
Step 17 (CLI) → Step 18
  ↓
Step 18 (E2E Test)
  ↓
Step 19 (CI)
  ↓
Step 20 (Samples)
  ↓
Step 21 (Live Run)
```

---

## Files to Create / Populate

### Core Implementation (`src/skillpipeline/`)
```
llm.py                    (new)
ingest.py                 (new)
extract.py                (new)
merge.py                  (new)
validate.py               (new)
retry.py                  (new)
relate.py                 (new)
human_review.py           (new)
cache.py                  (new)
graph.py                  (new)
report.py                 (new)
index.py                  (new)
pipeline.py               (new)
stats.py                  (new)
cli.py                    (new)
__main__.py               (new)
```

### Prompts (`src/skillpipeline/prompts/`)
```
system.txt                (new)
extract_topics.txt        (new)
extract_relationships.txt (new)
```

### Templates (`src/skillpipeline/templates/`)
```
report.html.j2            (new)
index.html.j2             (new)
```

### Tests (`tests/`)
```
test_models.py            (new)
test_ingest.py            (new)
test_extract.py           (new)
test_merge.py             (new)
test_validate.py          (new)
test_retry.py             (new)
test_cache.py             (new)
test_graph.py             (new)
test_pipeline_e2e.py      (new)
```

### Test Fixtures (`tests/fixtures/`)
```
clean_extract_response.json         (mock extract response)
messy_extract_response_1.json       (mock response that retries)
messy_extract_response_2.json       (recovery after retry)
adversarial_extract_response.json   (triggers max-retries flag)
relate_response.json                (mock relationship extraction)
```

### CI (`github/workflows/`)
```
ci.yml                    (new)
```

### Samples (`samples/`)
```
clean_roadmap.md          (exists? should be checked)
messy_tutorial.md         (exists? should be checked)
adversarial_prose.md      (exists? should be checked)
```

---

## Dependency Status

✅ All required dependencies pinned in `pyproject.toml`:
- langgraph >= 0.2
- langgraph-checkpoint-sqlite >= 0.2
- anthropic >= 0.40
- pydantic >= 2
- networkx >= 3
- structlog >= 25
- rich >= 13
- jinja2 >= 3
- (dev) pytest >= 8
- (dev) pytest-asyncio >= 0.24
- (dev) ruff >= 0.8
- (dev) mypy >= 1

No excluded dependencies detected (tenacity, Docker, FastAPI, etc. absent ✓).

---

## Suggested Next Steps

1. **Immediate (Step 3):** Implement `src/skillpipeline/llm.py` with `LLMClient` protocol, `AnthropicLLMClient`, and `FakeLLMClient`. This is the gateway for all LLM-calling stages.

2. **Then (Steps 4–11 in parallel, with shared test fixtures):**
   - Ingest (deterministic, can test standalone)
   - Extract (needs llm.py, async, retries)
   - Merge (deterministic)
   - Validate (deterministic)
   - Retry helpers (utilities for 5.2 and 5.5)
   - Relate (needs llm.py)
   - Human-review (needs graph structure, but node logic testable)
   - Cache (filesystem, deterministic)

3. **Then (Step 12):** Wire the graph once all stages are implemented.

4. **Then (Steps 13–17):** Reports, index, CLI.

5. **Finally (Steps 18–21):** E2E tests, CI, live validation.

---

## Validation Checklist

- [ ] All 21 steps completed and reviewed
- [ ] `pytest -v` passes (all tests green)
- [ ] `ruff check .` clean
- [ ] `mypy src` clean
- [ ] Full pipeline runs against real Anthropic API on all three samples
- [ ] Per-run reports generated and human-reviewed
- [ ] Runs-index HTML renders correctly and is visually correct
- [ ] DESIGN.md includes screenshots of report and index
- [ ] `git log` shows atomic commits per step (or per logical unit)

