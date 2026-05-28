# PLAN.md — Pripton Skill Pipeline Build Spec

**Audience:** the AI coding agent (Antigravity / Claude Code / Cursor) building this prototype, and Dheeraj driving the build.
**Source of truth:** this document. If anything during the build is ambiguous, the answer lives here. If the answer is *not* here, stop and ask before guessing.

---

## How to use this document

This file is split into two halves:

1. **The Spec** (Sections 1–11): comprehensive technical specification of what the prototype must do. Always referenceable. Do not deviate without explicit human approval.
2. **The Build Checklist** (Section 12): an ordered list of build steps. The agent should implement one step at a time. Each step references the spec section it's built from. Dheeraj reviews each step's output before the next step starts.

**Critical rule:** the agent does not skip ahead. Do not implement step N+1 while building step N. If a step needs a detail the spec doesn't cover, the agent stops and asks rather than inventing.

---

## 1. Goal and Non-goals

**Goal.** A working Python prototype that takes a markdown learning document and produces a validated, structured skill map (topics + typed relationships) using an LLM-driven extraction pipeline. The pipeline is reliable in the face of malformed LLM outputs: it validates, retries with feedback, supports human-in-the-loop review, is idempotent under repeated input, and is observable through structured logs and HTML reports.

**In scope.**
- Multi-stage pipeline (seven nodes: ingest, extract, merge, human_review, relate, validate, persist) orchestrated by LangGraph with a conditional retry edge (relate→validate) and a conditional human-review interrupt.
- Per-section parallel extraction via asyncio, with per-section retries internal to the extract node (not graph edges).
- Pydantic-validated outputs at every stage.
- Anthropic API with tool-use for structured output.
- Content-hash caching for idempotency.
- Three test inputs (clean, messy, adversarial) with committed sample outputs.
- Per-run HTML report (input + skill-map graph + execution log + validation events + cost).
- Runs-index HTML page (Airflow-grid-style operator view).
- `pipeline run`, `pipeline review`, `pipeline resume`, `pipeline stats` CLI commands.
- Tests that pass without an API key (LLM client mocked at the boundary).
- GitHub Actions CI: lint + type-check + tests.

**Out of scope.** Web UI, database, message queues, vector stores, multi-provider LLM abstraction, Docker, deployment, authentication, multi-tenancy, OpenTelemetry, real-time streaming. These are research-doc topics, not prototype features.

---

## 2. Architecture overview

### 2.1 Pipeline as a state graph

```
        ┌────────┐
        │ INGEST │
        └───┬────┘
            │
            ▼
       ┌─────────┐    fan-out per section (async)
       │ EXTRACT │    per-section retries internal to node
       └────┬────┘    (not graph edges)
            │
            ▼
        ┌───────┐
        │ MERGE │
        └───┬───┘
            │
            │  if merged_topics is empty:
            │  ─── skip directly to PERSIST (flagged) ───►
            ▼
   ┌────────────────┐  conditional interrupt
   │  HUMAN_REVIEW  │  (only if any section retried
   │                │   or --always-review)
   └────────┬───────┘
            │ (resume)
            ▼
        ┌────────┐
        │ RELATE │ ◄──────── retry-with-feedback ◄─┐
        └───┬────┘                                 │
            │                                      │
            ▼                                      │
       ┌──────────┐                                │
       │ VALIDATE ├────────────────────────────────┘
       └─────┬────┘   if invalid && relate_retries < 3
             │
             │ if valid, OR retries exhausted (flag)
             ▼
       ┌─────────┐
       │ PERSIST │
       └─────────┘
```

Implemented as a LangGraph `StateGraph` with a single shared `PipelineState` (Section 4). The single retry edge is `validate → relate`. The single interrupt point is `human_review`. The empty-extraction bypass is a conditional edge from `merge`. `SqliteSaver` persists state to `runs/{thread_id}/state.sqlite` so runs survive process exit.

### 2.2 Why LangGraph (defense)

The load-bearing reason is durable human-in-the-loop. LangGraph's `interrupt()` + `SqliteSaver` is the primitive that lets the pipeline pause for human review, persist state across process exit, and resume from the same point later — possibly days later. Reimplementing that pattern in plain Python would be reinventing LangGraph badly.

Secondary benefits: the `validate → relate` retry edge expresses naturally as a conditional graph edge with a counter on state, and the `merge → persist` short-circuit on empty topics is another conditional edge in the same machinery.

Per-section extract retries are deliberately NOT graph edges. They live inside the extract node as an asyncio loop, because section-level fan-out plus per-section retry-with-feedback would require `Send()` API branching that adds ceremony without clarity. The loss is visibility — the graph trace sees one extract step, not N — and we accept that loss in exchange for simpler code, mitigated by logging each per-section retry as a `ValidationEvent` visible in the report.

### 2.3 Why not Airflow / Temporal / Celery

- **Airflow:** built for scheduled batch ETL with static DAGs and a heavyweight scheduler/worker/DB/UI footprint. Wrong shape for event-driven AI workflows with dynamic retries. We borrowed its monitoring-UX mindset (the runs-index page) without its infrastructure.
- **Temporal:** the production answer for durable execution at scale, but requires a separate server and steep SDK ergonomics. Overkill for a prototype on one document at a time.
- **Celery / RQ / SQS / Kafka:** distributed task queues. There is no queue here — single document, single process. These belong in the research doc as scaling concerns.

All four get a real comparison in `RESEARCH.md`.

---

## 3. Repository structure

```
pripton-skill-pipeline/
├── README.md                        # Plain-English front door
├── DESIGN.md                        # Submission design notes
├── RESEARCH.md                      # Part 2 deliverable
├── PLAN.md                          # This file (kept for transparency)
├── pyproject.toml                   # Project config (deps, ruff, mypy, pytest)
├── .python-version                  # 3.11
├── .gitignore                       # Excludes runs/, .cache/, .env, etc.
├── .env.example                     # ANTHROPIC_API_KEY=...
├── .github/
│   └── workflows/
│       └── ci.yml                   # ruff + mypy + pytest
├── src/
│   └── skillpipeline/
│       ├── __init__.py
│       ├── __main__.py              # `python -m skillpipeline` CLI dispatch
│       ├── cli.py                   # Argparse / Typer command definitions
│       ├── models.py                # Pydantic models + LangGraph State TypedDict
│       ├── llm.py                   # Anthropic client wrapper with tool-use
│       ├── ingest.py                # Stage 1 node
│       ├── extract.py               # Stage 2 node (async fan-out)
│       ├── merge.py                 # Stage 3 node
│       ├── human_review.py          # Interrupt logic + review file IO
│       ├── relate.py                # Stage 4 node
│       ├── validate.py              # Stage 5 node + business rules
│       ├── retry.py                 # Retry-with-feedback helper
│       ├── cache.py                 # Content-hash cache
│       ├── graph.py                 # StateGraph construction
│       ├── pipeline.py              # High-level run/review/resume orchestration
│       ├── report.py                # Per-run HTML report generator
│       ├── index.py                 # runs-index HTML generator
│       ├── stats.py                 # `pipeline stats` aggregator
│       ├── prompts/
│       │   ├── system.txt
│       │   ├── extract_topics.txt
│       │   └── extract_relationships.txt
│       └── templates/
│           ├── report.html.j2       # Per-run report
│           └── index.html.j2        # Runs-index grid
├── samples/
│   ├── clean_roadmap.md
│   ├── messy_tutorial.md
│   └── adversarial_prose.md
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures (mock LLM client, sample docs)
│   ├── fixtures/
│   │   ├── extract_response_valid.json
│   │   ├── extract_response_malformed.json
│   │   ├── relate_response_valid.json
│   │   └── relate_response_bad_refs.json
│   ├── test_models.py
│   ├── test_ingest.py
│   ├── test_merge.py
│   ├── test_validate.py
│   ├── test_retry.py
│   ├── test_cache.py
│   ├── test_graph.py
│   └── test_pipeline_e2e.py
├── runs/                            # Generated, gitignored except .gitkeep
│   └── .gitkeep
└── .cache/                          # Generated, gitignored except .gitkeep
    └── .gitkeep
```

### 3.1 Dependencies

`pyproject.toml` declares exactly these and no others. Pin to the major versions current at build time.

**Runtime:**
- `langgraph` — state-graph orchestration
- `langgraph-checkpoint-sqlite` — `SqliteSaver` for durable state
- `anthropic` — official Anthropic SDK
- `pydantic` (>=2) — validation + JSON Schema generation
- `networkx` — graph algorithms (cycle detection, topo sort)
- `structlog` — structured JSON logging
- `rich` — pretty terminal output
- `jinja2` — HTML template rendering

**Dev:**
- `pytest` — test runner
- `pytest-asyncio` — async test support (extract node fan-out)
- `ruff` — linter
- `mypy` — static type checker

Anything outside this list — including the broader `langchain` package, `tenacity`, `loguru`, `langsmith`, `langchain-community`, FastAPI, Flask, requests, httpx, openai — is out of scope and must not be added. See Section 14.

---

## 4. Data models

All models live in `src/skillpipeline/models.py`. Pydantic v2.

### 4.1 Domain models

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

Difficulty = Literal["beginner", "intermediate", "advanced"]
RelationshipType = Literal["prerequisite", "related", "subtopic"]


class Section(BaseModel):
    """A chunk of the source document. Sections are extracted in parallel."""
    id: str                          # e.g. "section-0"
    heading: Optional[str]           # H1/H2 heading text, None if no heading
    body: str                        # Section body markdown
    order: int                       # Position in source document


class Document(BaseModel):
    """The ingested source document."""
    source_id: str                   # SHA-256 of raw bytes — the idempotency key
    source_path: Optional[str]       # Original file path if loaded from disk
    raw_text: str
    sections: list[Section]


class Topic(BaseModel):
    """A single extracted topic. The atomic node in the skill graph."""
    id: str = Field(..., pattern=r"^[a-z0-9-]+$")   # slug, lowercase, hyphens
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., min_length=1, max_length=80)
    difficulty: Difficulty
    source_section_id: Optional[str] = None         # Set during merge


class Relationship(BaseModel):
    """A typed edge between two Topic ids."""
    from_id: str
    to_id: str
    type: RelationshipType
    rationale: Optional[str] = None  # Optional LLM-supplied justification

    @field_validator("to_id")
    @classmethod
    def no_self_loops(cls, v: str, info) -> str:
        if "from_id" in info.data and info.data["from_id"] == v:
            raise ValueError("Relationship cannot be self-referential")
        return v


class SkillMap(BaseModel):
    """The final output artifact."""
    source_id: str
    topics: list[Topic]
    relationships: list[Relationship]
    metadata: "RunMetadata"


class ValidationEvent(BaseModel):
    """Recorded during pipeline execution. Surfaced in the HTML report."""
    stage: str                       # "extract" | "relate" | "merge"
    severity: Literal["error", "warning", "info"]
    code: str                        # e.g. "DANGLING_REFERENCE", "CYCLE_DETECTED"
    message: str
    retry_number: int = 0
    flagged: bool = False


class StageTelemetry(BaseModel):
    """Per-stage timing and cost."""
    stage: str
    started_at: str                  # ISO 8601
    ended_at: str
    duration_ms: int
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class RunMetadata(BaseModel):
    """Top-level metadata for a run; lives in the SkillMap and the report."""
    thread_id: str                   # LangGraph thread; also the run directory name
    source_id: str
    started_at: str
    ended_at: Optional[str]
    status: Literal["complete", "awaiting_review", "flagged", "running", "failed"]
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    stage_telemetry: list[StageTelemetry] = []
    validation_events: list[ValidationEvent] = []
    cache_hit: bool = False
```

### 4.2 LangGraph state

```python
from typing import TypedDict, Annotated
import operator


class PipelineState(TypedDict):
    # Inputs
    source_path: Optional[str]
    raw_text: Optional[str]

    # Stage outputs (each populated by its stage)
    document: Optional[Document]
    extracted_topics: Annotated[list[Topic], operator.add]   # Accumulates across sections
    merged_topics: Optional[list[Topic]]
    approved_topics: Optional[list[Topic]]                   # Set by human_review
    relationships: Optional[list[Relationship]]
    skill_map: Optional[SkillMap]

    # Flow-control state
    extract_retries: dict[str, int]                          # section_id -> count
    relate_retries: int
    extract_feedback: dict[str, str]                         # section_id -> last error
    relate_feedback: Optional[str]
    flagged_sections: list[str]
    flagged_relations: bool

    # Metadata accumulators
    validation_events: Annotated[list[ValidationEvent], operator.add]
    stage_telemetry: Annotated[list[StageTelemetry], operator.add]

    # Config (carried for downstream nodes)
    always_review: bool
    thread_id: str
```

Notes:
- `operator.add` on list fields means LangGraph appends on update rather than overwriting. Important for fan-out (extracted_topics) and accumulators (validation_events, stage_telemetry).
- `extract_feedback` keyed by section_id because each parallel extraction has its own retry context.

---

## 5. Stage specifications

For each stage: purpose, input, output, LLM contract (if any), validation, retry policy, failure mode.

### 5.0 LLM configuration (shared across extract and relate)

All LLM-calling stages share configuration declared as constants in `src/skillpipeline/llm.py`:

```python
MODEL = "claude-sonnet-4-5"            # Pin to the explicit version string at build time.
TEMPERATURE = 0.0                      # Determinism; same input → (almost) same output.
MAX_TOKENS = 4096                      # Per-response cap.

# Cost rates — verify against current Anthropic pricing at build time.
INPUT_COST_PER_MTOK = 3.00             # USD per million input tokens
OUTPUT_COST_PER_MTOK = 15.00           # USD per million output tokens
```

Cost computation:
```python
cost_usd = (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK \
         + (output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK
```

Every LLM call records `input_tokens`, `output_tokens`, and computed `cost_usd` into a `StageTelemetry` entry. Aggregates roll up to `RunMetadata.total_cost_usd` and into the runs-index banner.

The model and rates are constants, not configuration. If they need to change, the agent edits these constants — the change is one place, surface area is small. Multi-provider abstraction is out of scope.

### 5.1 Stage 1 — `ingest`

**Purpose.** Load the markdown source, compute the idempotency key, split into sections.

**Input.** `source_path` (str) or `raw_text` (str) from state.

**Output.** `Document` written to `state.document`. Records `stage_telemetry`.

**LLM.** None. Pure parsing.

**Logic.**
1. Read raw bytes; if `source_path`, also stash `source_path` in the document.
2. Compute `source_id = sha256(raw_bytes).hexdigest()`.
3. Decode to UTF-8 (replace errors).
4. Split by markdown headings. Strategy: split on `^#{1,2} ` (H1 or H2) lines. Each section captures the heading line plus all body content up to the next H1/H2. If the document contains no H1/H2 headings, emit a single section with `heading=None` and the whole text as body.
5. Assign `id = f"section-{order}"` and `order` starting at 0.
6. Construct and return `Document`.

**Validation.** Section bodies must be non-empty (strip whitespace). Empty sections are dropped (logged as info-severity event).

**Retry.** N/A (deterministic).

**Failure mode.** If the file cannot be read, raise; this is a setup error, not a workflow error.

### 5.2 Stage 2 — `extract`

**Purpose.** For each section, call the LLM to extract topics. Run sections in parallel.

**Input.** `state.document`, `state.extract_retries`, `state.extract_feedback`.

**Output.** Appends to `state.extracted_topics`. May append to `state.flagged_sections` and `state.validation_events`. Records `stage_telemetry`.

**LLM.** Tool-use call per section. Tool definition:

```python
EXTRACT_TOPICS_TOOL = {
    "name": "record_topics",
    "description": "Record the technical topics found in the given section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":          {"type": "string", "pattern": "^[a-z0-9-]+$"},
                        "name":        {"type": "string", "minLength": 1, "maxLength": 120},
                        "description": {"type": "string", "minLength": 1, "maxLength": 500},
                        "category":    {"type": "string", "minLength": 1, "maxLength": 80},
                        "difficulty":  {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
                    },
                    "required": ["id", "name", "description", "category", "difficulty"],
                },
            }
        },
        "required": ["topics"],
    },
}
```

System prompt (`prompts/system.txt`): brief, sets the assistant's role as a technical-content extractor.

User prompt for extract (`prompts/extract_topics.txt`, templated):
- Includes the section heading and body.
- States rules: extract only topics that appear in the source; don't invent; difficulty reflects how foundational the topic is; category groups related topics; ID is a lowercase hyphenated slug derived from the name.
- If `extract_feedback[section_id]` is present (retry case), include it verbatim under a "Previous attempt failed validation with this error" header.

**Validation (per section, inside the extract node).**
- The Anthropic response must contain exactly one `tool_use` block.
  - If text-only (no `tool_use`), validation failure with code `MISSING_TOOL_USE` and feedback `"You must respond by calling the record_topics tool, not in free-form text."`
  - If multiple `tool_use` blocks are present, validation failure with code `MULTIPLE_TOOLS` and feedback `"You must call the record_topics tool exactly once."` The API permits multiple tool_use blocks; our prompt discourages but doesn't prevent it.
  - If the `tool_use` block names a tool other than `record_topics`, validation failure with code `WRONG_TOOL` and feedback `"You must call the record_topics tool, not <other_name>."`
- Tool input must parse as `list[Topic]` via Pydantic.
- Topic IDs within the section must be unique.
- Topic names within the section must be unique (case-insensitive).

**Retry policy (internal to the extract node — NOT graph edges).** Each section runs its own async retry loop inside the extract node:

```
async def extract_one_section(section, llm_client):
    for attempt in range(MAX_EXTRACT_ATTEMPTS):  # MAX_EXTRACT_ATTEMPTS = 3
        result = await llm_client.call(EXTRACT_TOPICS_TOOL, build_prompt(section, feedback))
        try:
            topics = validate_extract_response(result, section)
            log_event("extract", "info" if attempt == 0 else "warning",
                      code="EXTRACT_OK" if attempt == 0 else "EXTRACT_RECOVERED",
                      retry_number=attempt, section_id=section.id)
            return topics, attempts_used=attempt + 1
        except ExtractValidationError as e:
            feedback = format_feedback(e)
            log_event("extract", "warning", code=e.code,
                      retry_number=attempt, section_id=section.id, message=str(e))
            await asyncio.sleep(0.2)
    # max retries exhausted
    log_event("extract", "error", code="MAX_RETRIES_EXCEEDED",
              retry_number=MAX_EXTRACT_ATTEMPTS, section_id=section.id, flagged=True)
    return [], attempts_used=MAX_EXTRACT_ATTEMPTS  # accept empty
```

Sections run in parallel via `asyncio.gather(*[extract_one_section(s, ...) for s in sections])`. The node aggregates all returned topics into `state.extracted_topics`, records per-section `attempts_used` into `state.extract_retries`, and adds flagged section IDs to `state.flagged_sections`.

**Failure mode.** A section that hits max retries is *flagged*, not fatal. Its topics list may be empty; downstream stages proceed with what's available. The graph sees one successful transition `extract → merge` regardless; retry visibility lives in `ValidationEvent`s.

### 5.3 Stage 3 — `merge`

**Purpose.** Deduplicate topics across sections, assign final IDs, attach back-references.

**Input.** `state.extracted_topics`.

**Output.** `state.merged_topics`. May append `validation_events`.

**LLM.** None.

**Logic.**
1. Normalize each topic name (`name.strip().lower()`) — this is the dedup key.
2. Group topics by normalized name. For each group with size > 1:
   - Log an info-severity `ValidationEvent` with code `DUPLICATE_TOPIC_MERGED`.
   - Pick the canonical record: longest description wins; if tied, first by source section order.
   - If `difficulty` differs across the group, log a warning-severity event with code `DIFFICULTY_CONFLICT` and pick the lowest (beginner < intermediate < advanced) — conservative choice favoring learners.
   - If `category` differs, log a warning event and pick the most-frequent (ties broken by first-occurrence).
3. Assign final canonical IDs. If two topics had the same name but different IDs, the canonical record's ID wins; downstream relationships will reference the canonical ID. (Relate runs *after* merge, so it only ever sees the merged IDs.)
4. Populate `source_section_id` on each merged topic with the section where it was first seen.

**Validation.** None beyond logging.

**Retry.** N/A (deterministic).

**Empty-extraction short-circuit.** If `len(merged_topics) == 0` after merge (every section flagged with empty topics, or the document was structurally degenerate), the graph routes directly from `merge` to `persist`, skipping `human_review`, `relate`, and `validate`. Before routing, log a `ValidationEvent`:

```
stage="merge", severity="error", code="EMPTY_EXTRACTION",
message="No topics extracted from any section; cannot proceed to relationship extraction.",
flagged=True
```

`RunMetadata.status` is set to `flagged`. The skill map is persisted with empty `topics` and empty `relationships`; the report and runs-index surface the flag prominently. This is the routing decision implemented as a conditional edge in the graph (Section 12 Step 12).

### 5.4 Stage 4 — `human_review` (conditional interrupt)

**Purpose.** Allow a human to inspect and edit the merged topic set before relationship extraction. Only triggered when the pipeline shows signs of uncertainty, or when `--always-review` is passed.

**Input.** `state.merged_topics`, `state.flagged_sections`, `state.extract_retries`, `state.always_review`.

**Output.** Sets `state.approved_topics`. Updates `RunMetadata.status` to `awaiting_review` when paused.

**Interrupt condition.** Interrupt iff any of:
- `any(count > 0 for count in state.extract_retries.values())` — any section needed at least one retry (an uncertainty signal; flagged sections are a subset of retried sections so we don't list them separately)
- `state.always_review is True`

If neither holds, skip the interrupt path: set `approved_topics = merged_topics`, return immediately, and the graph proceeds to `relate`.

**Interrupt behavior — precise LangGraph semantics.**
1. Inside the `human_review` node, write `runs/{thread_id}/topics_for_review.json`. Contents: the merged topics in pretty-printed JSON, plus an `"_instructions"` block at the top explaining how to edit, plus a `"_merge_events"` block listing relevant validation events (so the reviewer sees why review was triggered).
2. Set `RunMetadata.status = "awaiting_review"` and persist it as part of the state update.
3. Call `langgraph.types.interrupt(payload)` where `payload` is a small dict containing the review file path and thread_id. `interrupt()` raises `GraphInterrupt`, which propagates up to the caller. The graph's `invoke()` / `stream()` returns with the interrupt payload. State is already persisted in `runs/{thread_id}/state.sqlite` via `SqliteSaver` — no explicit save call.
4. The CLI prints the thread_id and the path to `topics_for_review.json`, then exits 0.

**Resume behavior.**
1. `pipeline resume {thread_id}` loads `runs/{thread_id}/topics_for_review.json`.
2. Validates: parses as JSON, conforms to `list[Topic]` via Pydantic, IDs unique, no self-loops. If validation fails, exit non-zero with the specific error.
3. Calls `graph.invoke(Command(resume=approved_topics_list), config={"configurable": {"thread_id": thread_id}})`. LangGraph re-enters the `human_review` node at the line right after `interrupt()`; the return value of that `interrupt()` call is now `approved_topics_list`.
4. The node assigns `state.approved_topics = approved_topics_list`, returns, and the graph proceeds to `relate`.

**Retry.** N/A on the graph side. Human review either succeeds (validation passes) or the human fixes their file and re-runs `resume` — re-running with a still-invalid file just re-prints the same error.

### 5.5 Stage 5 — `relate`

**Purpose.** Identify typed relationships between approved topics.

**Input.** `state.approved_topics`, `state.relate_retries`, `state.relate_feedback`.

**Output.** `state.relationships`.

**LLM.** Single tool-use call with the full topic set. Tool definition:

```python
EXTRACT_RELATIONSHIPS_TOOL = {
    "name": "record_relationships",
    "description": "Record typed relationships between the given topics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_id":   {"type": "string"},
                        "to_id":     {"type": "string"},
                        "type":      {"type": "string", "enum": ["prerequisite", "related", "subtopic"]},
                        "rationale": {"type": "string"},
                    },
                    "required": ["from_id", "to_id", "type"],
                },
            }
        },
        "required": ["relationships"],
    },
}
```

User prompt: provides the list of approved topics (id, name, description, category, difficulty). Specifies that `from_id` and `to_id` MUST be drawn from this list — no other IDs are valid. Defines the three relationship types in one sentence each. If `relate_feedback` is present, includes it under "Previous attempt failed validation."

**Tool-use fallback.** Same three checks as extract, swapping the tool name:
- `MISSING_TOOL_USE` — text-only response.
- `MULTIPLE_TOOLS` — more than one tool_use block.
- `WRONG_TOOL` — calls a tool other than `record_relationships`.
Feedback messages mirror the extract versions with `record_relationships` substituted. Each becomes the feedback that goes back into the prompt on the next attempt.

**Validation.** Handled by Stage 6.

**Retry.** See Stage 6. The relate retry IS a graph edge (the only retry edge in the graph).

### 5.6 Stage 6 — `validate`

**Purpose.** Apply schema and business-rule validation to the relationships. Decide whether to accept, retry, or flag.

**Input.** `state.approved_topics`, `state.relationships`, `state.relate_retries`.

**Output.** Either proceeds to `persist`, loops back to `relate` (with feedback), or flags and proceeds.

**LLM.** None.

**Validation rules.**

| Code | Severity | Rule |
|---|---|---|
| `SCHEMA_VIOLATION` | error | Pydantic parsing failed |
| `DANGLING_FROM_REF` | error | `from_id` not in approved topic set |
| `DANGLING_TO_REF` | error | `to_id` not in approved topic set |
| `SELF_LOOP` | error | `from_id == to_id` |
| `DUPLICATE_EDGE` | error | (from_id, to_id, type) tuple appears more than once |
| `CYCLE_IN_PREREQUISITES` | error | The subgraph induced by `type == "prerequisite"` contains a cycle (use `networkx.simple_cycles`) |
| `ORPHAN_TOPIC` | warning | A topic appears in no relationships (info-only — does not trigger retry) |

**Decision logic.**
- If no errors: proceed to `persist`.
- If errors and `relate_retries < 3`: increment counter, format errors into `relate_feedback`, route back to `relate`.
- If errors and `relate_retries >= 3`: set `flagged_relations = True`, retain whatever valid relationships exist (drop the invalid ones), proceed to `persist`. The run is marked `flagged`.

**Cycle detection details.** Build a directed graph using `networkx.DiGraph` containing only `prerequisite`-typed edges. Call `list(networkx.simple_cycles(g))`. If non-empty, report each cycle in the feedback message.

### 5.7 Stage 7 — `persist`

**Purpose.** Write all outputs. Update run metadata. Regenerate runs-index.

**Input.** All state.

**Topic source of truth.** The persisted `SkillMap.topics` always uses `state.approved_topics`, which equals `state.merged_topics` when no human interaction occurred and reflects the human's edits when it did. `state.merged_topics` is preserved in `run_log.json` for audit (so the report can show "before review" vs "after review" if they differ).

**Output.** Files on disk:
- `runs/{thread_id}/skill_map.json` — the `SkillMap` Pydantic model serialized. Topics from `state.approved_topics`, relationships from `state.relationships` (filtered to drop any rejected at validate-time if flagged).
- `runs/{thread_id}/run_log.json` — full `RunMetadata` including `validation_events`, `stage_telemetry`, and the pre-review `merged_topics` for audit.
- `runs/{thread_id}/report.html` — per-run report (Section 7).
- `runs/{thread_id}/skill_map.mmd` — Mermaid source for the skill graph (also embedded in report.html).
- `.cache/{source_id}.json` — cache entry, written only if `RunMetadata.status == "complete"` (flagged runs are NOT cached; see Section 10).
- `runs/index.html` — regenerated runs-index (Section 8).

Sets `RunMetadata.status` to `complete` or `flagged`.

---

## 6. Retry-with-feedback

### 6.1 Mechanism — two distinct retry layers

**Layer 1 — Per-section extract retries (internal to the extract node).** When per-section validation fails inside the extract node's async loop:
1. The validation error is captured as a human-readable string.
2. The error string is stored in a local variable (the inner loop's `feedback`), not in graph state, because no graph traversal is involved.
3. The next iteration of the async loop builds a new prompt that prepends the feedback block (below) and re-calls the LLM.
4. Each attempt logs a `ValidationEvent` with `retry_number` and `section_id`.

**Layer 2 — Relate retries (graph edge — the only retry edge in the graph).** When the validate node finds errors:
1. The validation error is captured as a human-readable string.
2. The error is written to `state.relate_feedback`, and `state.relate_retries` is incremented.
3. A conditional edge routes the graph back to the `relate` node.
4. The relate node's prompt builder reads `state.relate_feedback` and prepends the feedback block.
5. Each attempt logs a `ValidationEvent` with `retry_number` and stage `"relate"`.

**Shared feedback prompt block** used by both layers:

```
A previous attempt at this task failed validation with the following error(s):

{feedback}

Please correct these issues and try again. Pay particular attention to the
ID-format and reference-integrity rules.
```

### 6.2 Bounds

- Per-section extract retries: max 3 attempts total (inside the extract node).
- Relate retries: max 3 attempts total (across the graph edge).
- No exponential backoff between validation-retry attempts: these are validation errors, not rate limits. A short fixed delay (200ms) for politeness only.
- Transport-level failures (HTTP 429, 5xx, network errors) are handled separately by the `llm.py` wrapper with its own retry (max 5, exponential backoff with jitter, base 1s). This wrapper is independent of validation retries.

### 6.3 Flag-don't-fail

When retries are exhausted:
- The pipeline does NOT raise.
- It records a flagged `ValidationEvent` with code `MAX_RETRIES_EXCEEDED`.
- It marks the run status as `flagged`.
- It proceeds with whatever partial output exists.
- The HTML report highlights the flagged sections / relationships in red.

This is the central reliability decision: partial output with flags is more useful than no output. The runs-index makes flagged runs visually obvious so an operator can intervene.

---

## 7. Per-run HTML report

Generated by `report.py` from the Jinja2 template at `templates/report.html.j2`.

**Mostly self-contained HTML.** All CSS and JS for layout, color, and filtering is inline. Single external dependency: the Mermaid JavaScript library loaded from a public CDN (`cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js` or equivalent). This is the only resource that requires an internet connection at view-time. For offline review, the skill map is also written as `skill_map.mmd` — the reviewer can paste it into any Mermaid renderer (mermaid.live, VS Code preview, GitHub README). Calling the file "self-contained" would be a lie; "mostly self-contained, with one CDN script for graph rendering" is accurate.

**Sections (top to bottom).**

1. **Header.** Run thread_id, source file name, started_at / ended_at, status pill (color-coded), total cost.
2. **Pipeline diagram.** Mermaid `graph LR` of the pipeline itself, with each node styled by what happened (completed=green, retried=yellow, interrupted=orange, flagged=red).
3. **Skill map.** Mermaid `graph TD` of the extracted topics and their prerequisite relationships. Other relationship types listed in a table below.
4. **Stage telemetry.** Table of stages with duration, LLM calls, tokens (in/out), estimated cost.
5. **Validation events.** Table of events ordered by occurrence. Columns: stage, severity, code, message, retry #. Errors red, warnings yellow, info gray.
6. **Source.** Collapsed `<details>` showing the input markdown (truncated to 2000 chars with a "full source at samples/..." link).
7. **Footer.** Generated-at timestamp, pipeline version.

---

## 8. Runs-index HTML page

Generated by `index.py` from `templates/index.html.j2`. Regenerated at the end of every run.

**Layout.** Airflow-grid-inspired operator view.

- **Top stats banner.** Total runs, success rate, flag rate, awaiting-review count, total spend across all runs.
- **Filter bar.** Status (all / complete / flagged / awaiting-review), date range. Filtering is client-side via tiny inline JS (~30 lines, no framework).
- **Grid table.** Rows are runs (newest first). Columns:
  - Thread ID (link to per-run report).
  - Source file.
  - Started at.
  - Duration.
  - Status pill.
  - Per-stage status cells (Ingest / Extract / Merge / Human Review / Relate / Validate / Persist) — colored: green (completed cleanly), yellow (retried then succeeded), orange (currently awaiting review), red (flagged at this stage), gray (not yet run / N/A).
  - Cost.

Pure HTML + inline CSS + minimal JS for filtering. No build step. Looks like an operator tool, not a dev artifact.

---

## 9. CLI surface

Implemented in `cli.py` using `argparse` (stdlib — no Typer/Click dependency).

```
python -m skillpipeline run <input.md> [--always-review] [--no-cache]
python -m skillpipeline review <thread_id>
python -m skillpipeline resume <thread_id>
python -m skillpipeline stats [--json]
python -m skillpipeline cache list
python -m skillpipeline cache clear
```

**`run`.**
- Computes source_id from input.
- If cache hit and not `--no-cache`: copy cached skill_map to a new `runs/{thread_id}/`, regenerate report, mark `cache_hit=True`, exit 0.
- Otherwise: create thread_id (`run_{YYYYMMDD-HHMMSS}_{short-hash}`), start the LangGraph state machine.
- If the machine interrupts at human_review: print thread_id and the path to `topics_for_review.json`, exit 0.
- If the machine completes: print path to report.html, exit 0.
- If a flag fires at max retries: still exit 0 (it's expected behavior), but include a `flagged` banner in the printed output.

**`review`.**
- Looks up `runs/{thread_id}/topics_for_review.json`.
- If `$EDITOR` is set, opens it.
- Otherwise prints the file path and a hint.

**`resume`.**
- Loads the LangGraph checkpoint for `thread_id`.
- Validates `topics_for_review.json` (Section 5.4 validation rules).
- Continues the state machine from the human_review interrupt.

**`stats`.**
- Walks `runs/`, loads each `run_log.json`.
- Prints a Rich table with aggregate metrics (or JSON if `--json`).

**`cache list` / `cache clear`.**
- Trivial; manage `.cache/` directory.

---

## 10. Idempotency design

**Idempotency key:** `source_id = sha256(raw_input_bytes).hexdigest()`.

**Cache layout:** `.cache/{source_id}.json`. Contents: the serialized `SkillMap`, the `RunMetadata` from the original successful run, and a `cached_at` timestamp.

**Cache semantics.**
- Hit: a new `runs/{thread_id}/` directory is still created (so the runs-index reflects the request), but the skill_map is copied from cache, no LLM calls are made, `cache_hit=True` is recorded.
- Miss: pipeline runs normally; on completion, cache is populated.
- Flagged runs are NOT cached. Reason: a flagged run represents partial success; a human reviewer may want to re-run it later when the source or model has improved. Caching the flagged output would prevent that.
- Runs in `awaiting_review` state are NOT cached until resumed and completed.
- `--no-cache` flag bypasses both read and write.

**Determinism.** Anthropic API calls use `temperature=0`. This minimizes but does not eliminate variability. The cache is what makes the *observable* behavior deterministic: same input bytes → same output, regardless of LLM-side variability, after the first run.

**Idempotency vs caching — interview answer.** Idempotency is a property of the operation: applying it N times has the same effect as applying it once. Caching is one *mechanism* that achieves this. The cache here is keyed by input content, not by request ID; it's a *content-addressed* cache. Two distinct request IDs with the same input content produce the same output via the cache. That is idempotency in its strict sense.

---

## 11. Testing

### 11.1 What's tested without an API key

Everything except live LLM calls. The `llm.py` module exposes an abstract `LLMClient` protocol and a concrete `AnthropicLLMClient` implementation. Tests inject a `FakeLLMClient` that returns canned responses from `tests/fixtures/*.json`.

### 11.2 Test list

- `test_models.py` — Pydantic models accept valid inputs and reject invalid inputs. Self-loop validator. Pattern enforcement on Topic.id.
- `test_ingest.py` — Splitting on headings; single-section fallback; source_id deterministic; UTF-8 with replacement.
- `test_merge.py` — Dedup by normalized name; difficulty conflict resolution (lowest wins); validation events emitted.
- `test_validate.py` — Each business rule code is triggered by a constructed bad-input. Cycle detection across `prerequisite` edges only. Orphan topics are warnings, not errors.
- `test_retry.py` — Retry-with-feedback formats the error correctly into the next prompt. Max retries triggers flag.
- `test_cache.py` — Hit returns cached; miss runs pipeline and populates cache; `--no-cache` bypasses; flagged runs do not populate cache.
- `test_graph.py` — StateGraph compiles. Interrupt triggers on retry/flag conditions. Resume validates `topics_for_review.json`.
- `test_pipeline_e2e.py` — Full pipeline end-to-end with FakeLLMClient, asserting the final SkillMap structure for the clean sample, retry behavior for the messy sample, flag behavior for the adversarial sample.

### 11.3 CI workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy src
      - run: pytest -v
```

---

## 12. Build Checklist (sequential)

Each step is an atomic unit of work for the coding agent. **Implement one step, stop, let Dheeraj review, then proceed.** If a step's spec section is ambiguous, stop and ask before guessing.

- [ ] **Step 1 — Project skeleton.** Create directory structure (Section 3), `pyproject.toml` with all dependencies pinned to current major versions, `.gitignore`, `.env.example`, `.python-version`, empty `__init__.py` files. No source code yet.
- [ ] **Step 2 — Models.** Implement `src/skillpipeline/models.py` per Section 4. Add `tests/test_models.py` covering every validator. CI not yet wired.
- [ ] **Step 3 — LLM client wrapper.** Implement `src/skillpipeline/llm.py` with an `LLMClient` Protocol, an `AnthropicLLMClient` concrete class (uses `anthropic` SDK with tool-use, reads `ANTHROPIC_API_KEY` from env), and a `FakeLLMClient` that returns fixture data. Transport-level retries implemented inline (no external retry library): max 5 attempts, exponential backoff with jitter, base delay 1s; retried only on `anthropic.APIStatusError` with status >= 500 or `anthropic.RateLimitError`. All other exceptions propagate immediately.
- [ ] **Step 4 — Ingest stage.** Implement `src/skillpipeline/ingest.py` per Section 5.1. Implement section splitting carefully. Add `tests/test_ingest.py`.
- [ ] **Step 5 — Extract stage.** Implement `src/skillpipeline/extract.py` per Section 5.2. Async fan-out via `asyncio.gather` inside the node function. Include the prompt files at `prompts/system.txt` and `prompts/extract_topics.txt`. Tests use `FakeLLMClient`.
- [ ] **Step 6 — Merge stage.** Implement `src/skillpipeline/merge.py` per Section 5.3. Add `tests/test_merge.py` covering dedup and conflict resolution.
- [ ] **Step 7 — Validate stage.** Implement `src/skillpipeline/validate.py` per Section 5.6. All seven validation codes. Cycle detection with `networkx`. Add `tests/test_validate.py`.
- [ ] **Step 8 — Retry-with-feedback helper.** Implement `src/skillpipeline/retry.py` per Section 6 — formatting helpers for injecting validation errors into prompts, max-retries logic. Add `tests/test_retry.py`.
- [ ] **Step 9 — Relate stage.** Implement `src/skillpipeline/relate.py` per Section 5.5. Include `prompts/extract_relationships.txt`.
- [ ] **Step 10 — Human-review stage.** Implement `src/skillpipeline/human_review.py` per Section 5.4. Interrupt condition logic; review-file IO; resume-time validation.
- [ ] **Step 11 — Cache.** Implement `src/skillpipeline/cache.py` per Section 10. Add `tests/test_cache.py`.
- [ ] **Step 12 — Graph.** Implement `src/skillpipeline/graph.py` per Sections 2.1 and 5.4. The LangGraph `StateGraph` has nodes `ingest`, `extract`, `merge`, `human_review`, `relate`, `validate`, `persist`. Two conditional edges: (a) from `merge` — if `len(merged_topics) == 0`, route to `persist` (flagged), else route to `human_review`; (b) from `validate` — if errors and `relate_retries < 3`, route to `relate` with `relate_feedback` populated, else route to `persist`. `human_review` uses LangGraph's `interrupt()` API (Section 5.4) conditionally on retry/always-review signals. Configure `SqliteSaver` with the DB file at `runs/{thread_id}/state.sqlite`. Add `tests/test_graph.py` covering: compilation, the empty-extraction short-circuit, interrupt-trigger conditions (no retry/no always-review → no interrupt; one retry → interrupt; always-review → interrupt), and the resume cycle with a validated `topics_for_review.json`.
- [ ] **Step 13 — Report generator.** Implement `src/skillpipeline/report.py` and `templates/report.html.j2` per Section 7.
- [ ] **Step 14 — Runs-index generator.** Implement `src/skillpipeline/index.py` and `templates/index.html.j2` per Section 8.
- [ ] **Step 15 — Pipeline orchestrator.** Implement `src/skillpipeline/pipeline.py` — high-level `run`, `review`, `resume` functions that wire the graph, cache, persistence, and report generation together.
- [ ] **Step 16 — Stats command.** Implement `src/skillpipeline/stats.py` per Section 9 (`stats` subcommand).
- [ ] **Step 17 — CLI.** Implement `src/skillpipeline/cli.py` and `__main__.py` per Section 9. All subcommands wired.
- [ ] **Step 18 — End-to-end test.** Add `tests/test_pipeline_e2e.py` covering clean / messy / adversarial flows with the `FakeLLMClient`.
- [ ] **Step 19 — CI.** Add `.github/workflows/ci.yml` per Section 11.3. Ensure all checks pass locally first.
- [ ] **Step 20 — Sample inputs.** Add the three markdown files to `samples/` per the inputs described in DESIGN.md (sourced separately).
- [ ] **Step 21 — Live run pass.** Run `python -m skillpipeline run samples/clean_roadmap.md` and the other two against the real Anthropic API. Commit the resulting `runs/` outputs for the reviewer. Capture screenshots of the report and index for DESIGN.md.

---

## 13. Interview-defense notes (per major decision)

Quick reference for Dheeraj. Each decision below has a one-paragraph defense.

**Why LangGraph and not plain Python.** The load-bearing reason is durable human-in-the-loop. LangGraph's `interrupt()` + `SqliteSaver` is the primitive that lets the pipeline pause for human review, persist state across process exit, and resume from the same point later — possibly days later, with no in-memory continuation. Reimplementing that durably in plain Python means hand-rolling state serialization, version compatibility, and resume semantics — effectively reinventing LangGraph badly. The relate→validate retry edge and the merge→persist empty-extraction short-circuit are secondary benefits that fit naturally into the same graph machinery. Per-section extract retries are deliberately NOT graph edges — they live inside the extract node's async loop because section-level fan-out plus per-section retry-with-feedback would require `Send()`-style branching that adds ceremony without clarity. One durable interrupt, one retry edge, one short-circuit, and shared state — that's what LangGraph is paying for.

**Why not Airflow.** Airflow is built for scheduled batch ETL with static DAGs and a heavyweight scheduler/worker/DB footprint. The shape doesn't match an event-driven AI workflow with dynamic retries and dynamic interrupts. The good idea I took from Airflow is the operator-UI mindset: the runs-index page is essentially "the Airflow grid view, scaled down to one workflow."

**Why not Temporal.** Temporal is the right answer at production scale for durable execution — and I'd reach for it if workflows ran for hours or days with strict durability across crashes. For a prototype processing one document at a time, Temporal's infrastructure cost (separate server, SDK ergonomics) outweighs its benefits.

**Why Pydantic and tool-use instead of free-text JSON.** Anthropic's tool-use forces the model output to conform to a declared JSON Schema; Pydantic generates the schema and validates the parsed result. Two layers of structural protection. The remaining failure mode — schema-valid but business-rule-invalid output — is handled by Stage 6's business-rule validators.

**Why retry-with-feedback rather than just retry.** Plain retry assumes the failure was transient. Validation failures are not transient — the LLM will likely make the same mistake unless given the specific error. Including the validation error in the next prompt is a form of self-correction; in practice it usually succeeds on attempt 2.

**Why flag-don't-fail at max retries.** Partial output with flags is more useful than no output at all. The runs-index makes flagged runs visually obvious so an operator can intervene. This is also the design that scales: at 1000 documents, "fail on any error" is unacceptable; "flag the 5% that need attention" is the correct operational posture.

**Why content-hash idempotency.** Idempotency is the property of an operation producing the same effect when applied multiple times. The cache is keyed by the SHA-256 of the input bytes, making it content-addressed. Two distinct requests with the same content collapse to the same answer. This sidesteps LLM non-determinism for the second-and-subsequent runs of the same input.

**Why temperature=0.** Reduces sampling variance. Doesn't make LLMs fully deterministic, but combined with caching, makes the observable behavior of the pipeline deterministic.

**Why conditional HITL.** Always-interrupt is wasteful at scale — a human reviewer becomes the bottleneck. We interrupt only when the pipeline shows uncertainty signals (retries fired, sections flagged) or when the operator opts in via `--always-review`. This is the operational discipline that makes HITL scalable.

**Why a separate runs-index page.** The interviewer's stated need is to monitor workflows at scale without deep technical context. The index is the page he'd look at first. It's an Airflow-grid-style operator view tailored to this single pipeline. It's regenerated at the end of every run from filesystem state — no database, no daemon.

**Why no Docker / no FastAPI / no DB.** Each would add setup friction without earning its complexity at this scale. The prototype is a single CLI with file-system state. Production deployment is a research-doc concern, not a prototype concern.

**Why three test inputs (clean / messy / adversarial).** The clean one demonstrates the happy path. The messy one exercises the retry-with-feedback loop. The adversarial one exercises flag-don't-fail. Each is committed with its expected output so the reviewer sees the system handle three different shapes of input. This is the substance of the Results & Observations section.

---

## 14. What the agent must NOT do

- Do not add LangChain. Only the `langgraph` package, not the broader LangChain stack.
- Do not add tenacity, backoff, stamina. Inline the retry logic.
- Do not add a database (SQLite for LangGraph checkpoint is the only exception, and it's filesystem-based).
- Do not add a web server, FastAPI, Flask, etc.
- Do not add Docker, docker-compose.
- Do not add a vector store, embedding model, or RAG.
- Do not add additional LLM providers beyond Anthropic.
- Do not add OpenTelemetry. structlog only.
- Do not refactor the architecture mid-build. If a step seems wrong, stop and surface it; don't quietly redesign.
- Do not implement steps out of order.
- Do not skip writing tests for any step that has them listed.

---

**End of PLAN.md.** Build proceeds from Step 1. Dheeraj reviews every step's output before the next step begins.
