# AGENTS.md — Behavioral guidelines for the coding agent building this project

This file applies to any AI coding agent operating on this repository — Antigravity, Claude Code, Cursor, Codex, anything. The repo's implementation spec is `PLAN.md`. This file is the *behavioral wrapper* around that spec: how to interpret it, how to execute it, and how not to drift.

If you are the agent reading this: read this file before writing any code. Read `PLAN.md` next. Then begin Step 1.

If you are the human reviewing the agent's output: this file is also the standard you hold the agent to. If the agent violates any rule below, push back. The same applies to me, the author of `PLAN.md` — if a rule here contradicts something in `PLAN.md`, surface the contradiction rather than guess which one to follow.

The four principles below are adapted from [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT-licensed), which derives them from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on common LLM coding pitfalls. The structure is theirs; the project-specific applications are mine.

---

## How to work with PLAN.md

This project has an unusually detailed implementation spec at `PLAN.md`, containing a 21-step build checklist (Section 12) and the rationale for every architectural decision (Sections 1–11, 13, 14). Both you and the human reviewer rely on it.

The discipline:

1. **Implement one checklist step at a time.** Do not begin Step N+1 until Step N is reviewed and accepted by the human.
2. **Re-read the spec section referenced by the current step** before writing any code for that step. The references are explicit (e.g., "Step 12 — Graph. Implement per Sections 2.1 and 5.4").
3. **If the spec is ambiguous, stop and ask.** Do not invent. Do not assume the "reasonable default." The author of the spec is one chat message away.
4. **If the spec contradicts itself**, surface the contradiction before resolving it. This file exists partly to catch the case where you would otherwise silently pick a side.
5. **After each step, run the relevant tests.** Section 11 of `PLAN.md` lists which tests cover which steps. Tests must pass before the step is considered complete.
6. **Do not modify `PLAN.md`, `DESIGN.md`, `RESEARCH.md`, or `README.md`** without explicit human approval. These are the submission deliverables and their content is reviewed separately.

---

## Principle 1: Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before writing code for any step:

- **State your assumptions.** If `PLAN.md` says "split on H1/H2 headings" and you are about to write a regex, state what edge cases your regex handles (consecutive headings, headings with formatting, headings at the very end of the file) and which it does not.
- **Present interpretations rather than picking silently.** If the spec says "log a validation event" and you are unsure whether the event should include the full LLM response or just the error string, ask. Do not pick.
- **Push back when a simpler approach exists.** If `PLAN.md` proposes a pattern that is more complex than it needs to be for the actual requirement, say so before implementing. The author would rather hear it than discover it in review.
- **Stop when confused.** Name what is unclear in plain language and ask. "I don't understand how X relates to Y" is acceptable. Quietly building the wrong thing is not.

**Concrete examples in this project where you should NOT silently decide:**

- How to handle markdown that contains code blocks with `#` characters that look like headings but aren't. The spec doesn't address it explicitly.
- Whether `Topic.id` should be derived from `Topic.name` deterministically (slugify) or allowed to come from the LLM verbatim. The spec implies the latter but doesn't say.
- How to format the `extract_feedback` string when multiple validation errors apply to the same retry. The spec mentions "joined with newlines" but not the exact prefix format.

When in doubt, the spec wins; when the spec is silent, ask.

---

## Principle 2: Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and 50 would do, rewrite it.

**Concrete applications to this project:**

- **The retry helper is not a framework.** `src/skillpipeline/retry.py` is a few functions, not a class hierarchy. If you find yourself writing `class RetryStrategy(ABC):` — stop. The spec wants two retry layers, both small, both inline.
- **Pydantic models are data, not behavior.** Do not add methods, computed properties, or validators beyond those listed in Section 4 of `PLAN.md`. If a transformation is needed, put it in the stage module that does the transformation, not on the model.
- **The CLI is plain argparse.** Section 9 specifies argparse; do not introduce Typer, Click, or Fire. They are not better here — they are different.
- **Prompts are plain text with `str.format`.** Section 5 specifies `prompts/*.txt` files with Python format placeholders. Do not introduce Jinja2 for prompt templating, or LangChain's `PromptTemplate`, or any other layer. Jinja2 is for HTML only.
- **The cache is a directory of JSON files.** Do not introduce `diskcache`, Redis, or SQLite for the cache. `.cache/{hash}.json` is the cache.

### Hard allow / deny lists for dependencies

`PLAN.md` Section 3.1 lists exactly which runtime and dev dependencies belong. Do not add anything outside that list. The expanded deny list, with reasons:

| Tempting addition | Why NOT in this project |
|---|---|
| `langchain` (the broad package) | We use `langgraph` only. The broader LangChain framework has chains, agents, retrievers, memory — none of which we need. |
| `langchain-community` | Same reason. We do not use community integrations. |
| `tenacity`, `backoff`, `stamina` | The two retry loops are 10-line inline implementations. Tenacity adds a decorator-config tax for no marginal value. |
| `loguru` | `structlog` is the structured-logging pick for this project. Pick one and stop. |
| `langsmith` | LangSmith is discussed in `RESEARCH.md`. We do not wire it in. If the agent wants tracing, that's a separate scope conversation. |
| `instructor`, `pydantic-ai`, `marvin` | These wrap the tool-use API we are deliberately using directly. The directness is the point. |
| `guardrails` | The validation layer is intentionally in our own code so the rules are visible. |
| `fastapi`, `flask`, `starlette`, `uvicorn` | No web server. The interface is a CLI. |
| `httpx`, `requests`, `aiohttp` | The Groq SDK is our HTTP client. We do not make raw HTTP calls. |
| `redis`, `celery`, `rq`, `dramatiq`, `kafka-python` | No queue. Single-process workflow. |
| `sqlalchemy`, `psycopg2`, `pymongo` | No database. Filesystem state. The one exception is `langgraph-checkpoint-sqlite` which is the LangGraph checkpointer. |
| `openai`, `anthropic`, `google-generativeai`, `litellm`, `cohere` | Single LLM provider: Groq (migrated from Anthropic mid-build; see DESIGN.md Section 8). |
| `pytest-mock`, `responses`, `respx`, `vcr.py` | The LLM client is mocked at the application boundary via `FakeLLMClient`. No HTTP-level mocking needed. |
| `docker`, `kubernetes` | Out of scope. |
| `streamlit`, `gradio` | No UI. |

If the agent believes a dependency outside this list is required, the agent stops and surfaces the reason. Adding a dependency is a spec change, not an implementation detail.

---

## Principle 3: Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When implementing a checklist step:

- **Do not modify files belonging to other steps.** If you are on Step 5 (extract), do not edit `models.py` (Step 2) or `merge.py` (Step 6). If Step 5 reveals a bug in Step 2's models, stop and surface it — do not patch silently.
- **Do not "improve" adjacent code.** If you open `ingest.py` to read a function and notice the docstring could be clearer, leave it. Document the observation in chat; do not change the file.
- **Match existing style.** If the codebase uses snake_case for function names, use snake_case. If it uses 4-space indentation, use 4-space. Even if you would do it differently.
- **Don't refactor things that aren't broken.** If something works and isn't part of the current step, it stays.

**When your changes create orphans:**

- Remove imports / variables / functions that *your* changes made unused.
- Do not remove pre-existing dead code. If you notice it, mention it; do not delete.

**The trace test:** Every changed line should trace directly to the current checklist step. If a changed line cannot be explained by the current step, revert it.

**Concrete applications:**

- If you finish Step 4 (ingest) and realize the Section model needs an extra field for Step 5 (extract), do not add the field as part of Step 4. Finish Step 4 with what the spec says. Then propose the field addition explicitly at the start of Step 5.
- If you write a test and notice another test in the same file is brittle, do not "fix" the other test. The other test is not in your scope.

---

## Principle 4: Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals. Every checklist step in `PLAN.md` has implicit or explicit success criteria; surface them before writing code, then loop until met.

| Instead of... | Transform to... |
|---|---|
| "Implement the extract stage" | "Implement `extract_one_section` and `extract_node`; write `tests/test_extract.py` with cases for valid output, malformed output, max retries, and empty output; all tests pass" |
| "Add cycle detection" | "Write a test where prerequisite edges form a cycle and assert that `validate_relationships` returns an error with code `CYCLE_IN_PREREQUISITES`; make it pass" |
| "Implement the runs-index" | "Write a script that generates `runs/index.html` from a hand-crafted directory of mock runs; verify by opening the file in a browser and checking that the grid renders, the filter works, and the stats banner sums correctly" |

For multi-step work within a checklist step, write a short plan and verify each piece:

```
Step 7 — Validate stage
1. Write the seven validation functions (one per error code) → unit tests pass
2. Wire them into `validate_relationships(topics, relationships)` → integration test passes
3. Add cycle detection via networkx.simple_cycles → cycle test passes
```

**Strong success criteria let you loop independently.** Weak criteria ("make it work") require constant clarification from the human.

**The test discipline for this project:**

- `pytest` must pass after every step that adds tests.
- `ruff check .` must pass after every step.
- `mypy src` must pass after every step (once Step 19 wires CI).
- The full pipeline must run end-to-end against the three samples before submission (Step 21).

---

## The vibecoding antidote

The author of this project was previously criticized for "vibecoding" — producing code without internalizing the design well enough to defend it. The discipline below exists to make that failure mode structurally hard.

**For the human reviewer:**

1. **Read every file the agent produces before saying "continue".** Not skim. Read.
2. **For any line you don't understand, ask the agent to explain it in the context of the spec section.** Generic explanations are insufficient. "Why is this `await asyncio.sleep(0.2)` here?" should get an answer that references `PLAN.md` Section 6.2.
3. **If the explanation is hand-wavy or pattern-matches to "best practice" without justification, push back.** Best-practice reasoning is exactly what loses interviews.
4. **If you find yourself accepting code you don't fully understand, stop the build.** Come back with the file and the question. Re-derive it from first principles together.

**For the agent:**

1. **Volunteer explanations along with code.** When you produce a file, write a short summary of what each non-obvious decision does and why, with reference to the relevant spec section. Do not wait to be asked.
2. **Flag your own uncertainty.** If a line of code is something you would expect to be questioned on, annotate it with a `# NOTE: ...` comment explaining the choice. This is acceptable noise; silent over-engineering is not.
3. **Resist the pull toward generality.** The temptation to make a function "more reusable" or an abstraction "more flexible" is the vibecoding failure mode. Solve exactly the problem in front of you.

---

## Project context — what's special about this codebase

A few non-obvious things the agent should know:

- **The role this code is auditioning for** is an AI Workflow Engineering position. The reviewer cares about workflow reasoning more than feature count. Code that is small, well-justified, and easily explained beats code that is large, novel, or impressive.
- **The interviewer is not deeply technical.** The README and DESIGN.md are written to be read by them. Do not introduce technical jargon into those files. The agent may not edit them anyway (see "How to work with PLAN.md" rule 6).
- **HITL is the spine, not a feature.** The conditional human-review interrupt is the most defensible piece of the architecture. Do not implement it as a quick `input()` call — it must use LangGraph's `interrupt()` + `SqliteSaver` per Section 5.4.
- **Observability is a deliverable.** The runs-index HTML page is the operator-facing artifact. Treat it as a first-class output, not a nice-to-have.
- **The LLM provider has changed once mid-build.** We initially built against Anthropic (`claude-sonnet-4-5`), then migrated to Groq (`llama-3.3-70b-versatile`) when API costs became a constraint. The migration was contained to `llm.py` and its tests, which is the validation of the `LLMClient` protocol earning its keep. The deny list above reflects the current state — `anthropic` is now denied because we don't want it accidentally reintroduced; `groq` is the only allowed provider until a new explicit spec change.

---

## Tradeoff note

These guidelines bias toward **caution over speed.** For trivial tasks (renaming a variable, fixing a typo), use judgment — full discipline is overhead.

The goal is reducing costly mistakes on non-trivial work, not slowing down obvious work.

---

## Attribution

The four-principle structure is from [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). The project-specific applications, deny lists, and discipline rules are written for this codebase.

## Where to put this file

- **Antigravity:** drop this file at the repo root as `AGENTS.md`. Antigravity reads it automatically.
- **Claude Code:** copy / symlink to `CLAUDE.md` at the repo root.
- **Cursor:** copy to `.cursor/rules/agents.mdc` (with a frontmatter `description:` if your version requires it).
- **Other agents:** the standard root-level filename most agents now read is `AGENTS.md`.
