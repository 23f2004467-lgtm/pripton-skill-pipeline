# Design Notes — Pripton Skill Pipeline

This document is the design rationale for the prototype. It covers what the system does, how it is built, what choices were made and why, what is deliberately missing, and what was observed when running it against real inputs. A glossary at the end defines every acronym used.

The companion PLAN.md is the implementation-level spec used to build the prototype. The companion RESEARCH.md addresses Part 2 of the assignment — a broader analysis of reliable AI-assisted workflow engineering. This file is the bridge between them: it explains the prototype to a reader who wants to understand the design choices without reading the code or the implementation spec.

---

## 1. What this system does, in plain language

The system takes a piece of written learning material — a tutorial, a roadmap, a set of course notes — and produces a structured skill map: a list of topics with metadata, plus typed relationships between those topics (prerequisite, related, subtopic). The skill map is rendered both as machine-readable JSON and as a visual graph diagram.

The interesting engineering is not the call to the language model. It is everything around that call: how the system catches the model's mistakes, decides whether to retry or escalate to a human, persists state across human review, and makes its own behavior visible to an operator monitoring many runs.

The reader who wants to understand the system in 90 seconds should read this section and section 2 below, then look at one of the per-run HTML reports in `runs/`.

---

## 2. The workflow at a glance

The pipeline has seven nodes, organized as a state graph. Five of them do work; one handles human review; one writes the output.

```
  Ingest  →  Extract  →  Merge  →  Human Review  →  Relate  →  Validate  →  Persist
   (split   (per-section  (dedupe   (conditional   (typed     (rules +     (write
   into     parallel      and       interrupt,     edges      retry        files,
   sections) LLM calls)   reconcile) durable)      via LLM)    edge)        report)
```

The orchestration is built with **LangGraph**, a Python library for stateful graph-based workflows. The choice is intentional and discussed below.

There are two places in the graph where the flow is not strictly linear:

The first is a **conditional human-review interrupt** between Merge and Relate. If any section needed at least one retry during extraction, or if the operator explicitly opts in with a flag, the graph pauses, writes the current topic list to a file the human can edit, and exits. The graph state is persisted to disk. A second invocation of the pipeline (`resume`) picks up exactly where it left off, with the human's edits as the new approved topic list. Clean runs skip the interrupt entirely — the human is brought in only when the system itself is uncertain.

The second is a **conditional retry edge** between Validate and Relate. If the Relate node produces relationships that fail validation (referencing nonexistent topic IDs, introducing cycles, duplicating edges), the graph routes back to Relate with the specific validation errors injected into the next prompt. This loop is bounded at three attempts. After that, the pipeline flags the run and continues with whatever valid output exists.

A third behavior worth flagging is an **empty-extraction short-circuit** from Merge to Persist: if every section flagged with zero topics extracted, there is nothing to relate, so the graph skips relate and validate entirely, writes a flagged empty skill map, and moves on.

These three flow-control concerns are the reason LangGraph earns its place in the dependency list. They would all be possible in plain Python, but durable resume across process exits (the human-review interrupt) is genuinely hard to implement correctly without a checkpoint primitive, and LangGraph provides exactly that primitive.

---

## 3. Processing stages, one by one

### Ingest

The source markdown is read, its raw bytes are hashed with SHA-256 (this hash becomes the idempotency key for the entire run), and the text is split on H1 and H2 headings into sections. A document with no headings becomes a single section. Empty sections are dropped. This stage is pure parsing; no language model is involved.

### Extract

Each section is sent to the language model independently and in parallel via `asyncio.gather`. The model is asked, via Anthropic's tool-use API, to return a list of topics with five fields each: id (a slug), name, short description, category, and difficulty (beginner / intermediate / advanced). The tool-use mechanism is materially more reliable than asking the model for JSON in free-form text — the response is validated against a declared schema by the API itself, then re-validated against the corresponding Pydantic model on our side.

When validation fails for a section — whether because the model violated a schema rule, produced duplicate topics, or returned a text-only response with no tool call — the extract node retries that section in an internal async loop, prepending the validation error to the next prompt. Three attempts maximum per section. A section that exhausts retries is *flagged* but does not crash the pipeline; whatever topics were extracted (possibly zero) are passed downstream.

Per-section retries are deliberately internal to the extract node, not graph edges. Section-level branching at the LangGraph level would require the Send API and add ceremony out of proportion to its value. Retry visibility is preserved by logging each attempt as a structured event that appears in the per-run report.

### Merge

The model is permitted to invent IDs independently in each section, so the same conceptual topic may be extracted twice with different IDs and slightly different descriptions. Merge deduplicates by normalized topic name (stripped and lowercased). When duplicates collapse, the canonical record is chosen by simple deterministic rules: longest description wins; on difficulty conflict, the more conservative value wins (beginner over intermediate over advanced) on the principle that learners should not be told a topic is harder than it might be; on category conflict, the most-frequent category wins, with ties broken by first occurrence. Every merge decision is logged as a structured event so a human reviewer can see what reconciliation was applied.

### Human Review (conditional)

If the pipeline shows signs of uncertainty — any section needed at least one retry, or the operator passed `--always-review` — the graph writes the merged topic list to `runs/{thread_id}/topics_for_review.json`, persists its own state to a SQLite checkpoint file, prints a thread ID, and exits. The reviewer edits the JSON file directly: they can remove topics, add topics, change metadata, fix IDs. A subsequent `pipeline resume {thread_id}` command validates the edited file (Pydantic schema, unique IDs, no self-loops) and re-enters the graph at the same node with the human's edits as the new approved topic set.

The reason this design uses durable resume rather than an inline prompt is that the role this prototype is auditioning for is one where a non-technical operator will monitor many of these workflows at scale. A pipeline that requires the original process to stay alive while a human reads through topics is not operationally realistic. A pipeline that exits cleanly, writes a file, and can be resumed an hour or a day later is.

### Relate

The full approved topic list is sent to the model in a single call, with a tool that asks for typed relationships between topic IDs. The prompt constrains valid IDs to those in the list. The model returns relationships with from_id, to_id, type (prerequisite / related / subtopic), and an optional rationale. If the response is text-only, missing required fields, or violates the schema, the standard validation-feedback loop kicks in.

### Validate

Schema-level validation is done by Pydantic during deserialization. Business-rule validation is done in code:

- **Dangling references.** Any from_id or to_id that is not in the approved topic set is an error.
- **Self-loops.** A relationship where from_id equals to_id is an error.
- **Duplicate edges.** The same (from_id, to_id, type) tuple appearing twice is an error.
- **Cycles in prerequisites.** The subgraph induced by the prerequisite-typed edges must be acyclic. This is detected using `networkx.simple_cycles`. A cycle is an error because it means there is no valid learning order.
- **Orphan topics.** A topic appearing in no relationship is a *warning*, not an error — it might be a valid leaf concept.

If errors exist and the retry counter is below three, the graph routes back to Relate with the errors prepended to the prompt. Above three, the run is marked flagged and the valid subset of relationships is retained.

### Persist

The final skill map (using the approved topic list and the surviving validated relationships) is written to disk as JSON. A run log captures every validation event, every stage's telemetry, total token usage, estimated cost. An HTML report is rendered from a Jinja2 template. A Mermaid `.mmd` file holds the graph for offline rendering. The runs-index page is regenerated to include the new run.

Cache writes happen only for runs that complete cleanly — flagged runs are not cached, because their incomplete output should not be served on a future re-run.

---

## 4. Validation and retry, treated as a first-class concern

The single most important reliability decision in this design is that the system never crashes on bad LLM output. It validates, retries with feedback, and at the limit flags-and-continues. The failure mode of an LLM pipeline that crashes on malformed output is worse than the failure mode of one that produces partial output marked for human review. Partial output is something an operator can triage. A crash is something an operator has to debug.

Two layers of retry coexist in the system, addressing different concerns:

**Validation retries** — these are about content correctness. The model produced output that does not satisfy our schema or business rules. The fix is to send the model the specific error and ask again. We do this up to three times per failing unit (per section in extract, per attempt in relate), with a short fixed delay between attempts. There is no exponential backoff because the failure is not a rate limit; backing off does not help.

**Transport retries** — these are about network and rate-limit failures. The Anthropic API returned a 429 or a 5xx, or the request timed out. These are handled in the LLM client wrapper with a separate retry loop, with exponential backoff and jitter, capped at five attempts. The validation logic does not see these failures.

Separating these two layers makes both easier to reason about. Mixing them — putting transport retries inside the validation loop — would muddy the semantics and make the bounds hard to defend in an interview.

The validation retry mechanism deserves one specific note. We do not simply re-call the model with the original prompt. We *include the validation error in the next prompt*: "Your previous response failed validation with this error: [error]. Please correct and try again." This pattern — sometimes called self-correction or self-refinement in the LLM literature — is markedly more effective than blind retry. A blind retry tends to produce the same mistake. A feedback-augmented retry usually succeeds on attempt two.

---

## 5. Idempotency and reliability considerations

This section maps directly to the assignment's explicit "Idempotency & Reliability Considerations" deliverable.

### Handling duplicate or repeated processing

The system computes a SHA-256 hash of the input bytes on ingest. This hash is the idempotency key. A content-addressed cache at `.cache/{hash}.json` holds the output of any previously completed run.

When a run begins, the cache is checked. On a hit, the cached skill map is used as the answer; no LLM calls are made; a new `runs/{thread_id}/` directory is still created so the runs-index reflects the request, but with `cache_hit=true` recorded. The operator sees the run completed, knows it was cached, and incurs zero cost.

Two runs with the same input content thus collapse to the same answer, regardless of when or where they are invoked. That is idempotency in its strict sense: the operation can be applied N times and produce the same observable result.

Idempotency and caching are not synonyms. Caching is one mechanism that achieves idempotency. The cache here is content-addressed, not request-ID-addressed, which is why it works as an idempotency mechanism rather than just a performance optimization. Two callers who happen to send the same content get the same answer even though they have no shared request ID.

### Safe retry management

Retries are bounded at three attempts per validation failure and five per transport failure. Each attempt is logged with a `retry_number`, making the retry behavior observable. After the bound is exceeded, validation retries flag-and-continue rather than crash. Transport retries fail the LLM call and surface the failure to the caller, who treats it as a validation failure and applies the validation-retry policy on top.

A retry that itself causes a side effect would not be safe — for example, retrying a database insert without an idempotency token can produce duplicates. The retries in this system are confined to LLM calls, which are pure reads as far as our system is concerned (the LLM provider is stateless from our perspective). The only persistent side effect we make is writing the final skill map to disk, and that happens exactly once, after all retries have settled.

### Validation under inconsistent output

The model is non-deterministic by nature, and even at `temperature=0` may produce slightly different output across calls. Our validation layer normalizes this variance:

- **Schema validation** rejects outputs that do not conform to the declared structure. Tool-use API enforcement plus Pydantic re-validation gives two layers of structural protection.
- **Business-rule validation** rejects outputs that conform structurally but violate domain rules — dangling references, cycles, duplicates, self-loops.
- **Determinism via caching** ensures that after the first successful run on a given input, all subsequent runs return that same successful output, sidestepping LLM variance entirely.

There is one form of inconsistency the system explicitly does NOT catch: *semantic* inconsistency. If the model says "Variables" is a prerequisite of "Functions" in one run and "Functions" is a prerequisite of "Variables" in another, both are schema-valid and rule-valid, but they cannot both be correct. We treat this as an explicitly acknowledged gap, addressed in Section 7 below.

### Assumptions

- **Inputs are markdown.** Other formats (HTML, plain text, PDF) are out of scope.
- **Inputs fit in a single LLM context window.** Documents exceeding that bound would need chunking strategies beyond H1/H2 splitting.
- **One Anthropic model.** We pin a specific Claude model version. Multi-provider abstraction is deliberately not built.
- **Single process per run.** No concurrency between runs is required; LangGraph's checkpointer is keyed by thread_id, so concurrent runs of different inputs are safe, but we do not test or guarantee it.
- **Filesystem-based state.** No database is required; `runs/` and `.cache/` directories are the only persistence.
- **Operator trusted.** Anyone with `pipeline resume` access can edit `topics_for_review.json` arbitrarily. Authentication and authorization are out of scope for the prototype.

### Reliability problems at larger scale

The prototype handles one document at a time in a single process. At scale, the following problems become real and would need addressing:

- **Concurrency across runs.** Many documents arriving simultaneously would saturate API rate limits. A queue with concurrency limits — Celery, RQ, or a managed service like SQS — would replace the inline CLI invocation.
- **Cross-document concept deduplication.** Today each document's skill map is independent. At scale, the same topic ("React Hooks") extracted from different documents should resolve to a single canonical entity. This requires embeddings and a vector store (Qdrant, pgvector, Pinecone) for semantic deduplication.
- **Durable execution beyond minutes.** LangGraph's SqliteSaver is fine for human review that takes hours. Workflows spanning days, with strict crash-recovery semantics, would benefit from Temporal or a similar durable-execution platform.
- **Centralized observability.** Today, the runs-index HTML page is the operator dashboard. At scale, structured logs would ship to a SIEM (Datadog, Honeycomb, Grafana Loki), traces to an OpenTelemetry collector, and LLM-specific telemetry to LangSmith, Langfuse, or Phoenix.
- **Cost control.** A flat per-MTok rate stops scaling reasoning past a certain point. At volume, you'd want model routing (cheaper models for easy sections, premium models for hard ones), budget alerts, and per-tenant cost attribution.
- **Multi-tenancy.** Today there is one set of files. A multi-tenant system would partition runs, caches, and credentials by tenant.

These are not deficiencies of the prototype. They are explicitly out of scope. Each one is a different problem that deserves its own design — and several are discussed in RESEARCH.md, which covers the broader landscape of AI workflow reliability.

---

## 6. Observability and the operator experience

The submission is being prepared with one specific operator profile in mind: someone who will monitor many of these workflows at scale, without deep technical context for each one. The observability layer of the prototype is built around what that person needs to see at a glance.

**Per-run HTML report.** Every run produces a single HTML file containing: the pipeline diagram with each node colored by what happened (clean, retried, flagged, interrupted), the skill map rendered as a Mermaid graph, a stage-by-stage table of timings and token usage and cost, a full log of validation events with severity color-coding, and a collapsed view of the source input. This file is the artifact a reviewer or operator opens to understand a specific run.

**Runs-index page.** At the end of every run, a top-level `runs/index.html` is regenerated. It is laid out as a grid: rows are runs (newest first), columns are pipeline stages, cells are colored by status. At the top is a banner of aggregate stats — total runs, success rate, flag rate, awaiting-review count, total spend. The aesthetic is deliberately reminiscent of Airflow's grid view, because that visual matches the mental model a non-technical operator already has of "monitoring workflows." Filtering by status and date range is supported through inline JavaScript — no framework, no build step.

**Structured logs.** Every event the pipeline produces — stage entry, LLM call, validation result, retry, interrupt — is emitted as a structured JSON log via `structlog`. In production these would ship to a centralized aggregator; for the prototype they live in the run log.

**Cost telemetry.** Token usage is captured from every Anthropic response. Costs are computed per stage and rolled up per run. The runs-index banner aggregates spend across all runs. A non-technical operator can answer "how much did this cost us today?" without leaving the index page.

**Stats command.** A `pipeline stats` command walks the runs directory and prints aggregate metrics — success rate, retry rate, flag rate, average cost — as a Rich-formatted terminal table or as machine-readable JSON. Useful for piping into a downstream monitoring dashboard.

---

## 7. Assumptions, tradeoffs, and what's deliberately missing

This section is the one most likely to be probed in a review. Every decision here was made deliberately.

**Single LLM provider.** The Anthropic SDK is called directly; there is no provider-abstraction layer. The tradeoff is that swapping providers later requires touching the LLM client module. The benefit is that the code is shorter, more legible, and the tool-use mechanism (which differs between providers) is visible at the call site. At production scale, a `LiteLLM`-style abstraction would earn its keep; at prototype scale, it would be a layer of indirection without payoff.

**Plain text prompts in files, not a prompt framework.** Prompts live in `prompts/*.txt` and are interpolated with Python's `str.format`. No PromptTemplate, no Guardrails RAIL, no Jinja2 in prompts. The tradeoff is that more complex prompt logic (few-shot example selection, conditional sections) would push toward a framework. The benefit is that the prompts are inspectable as plain text and editable without understanding a templating language.

**No semantic validation.** The validation layer catches structural and business-rule errors but cannot tell whether the model's extracted topics or proposed relationships are *correct*. A wrong prerequisite (X claimed to require Y when Y actually requires X) passes all our checks. The natural extension is **LLM-as-judge**: a second LLM call that evaluates the first one's output for plausibility. We do not implement it because (a) it doubles the cost per run and (b) implementing it well requires its own evaluation set, which is out of scope. It is the most important "would do at scale" item and is discussed in RESEARCH.md.

**No vector store, no cross-document concept resolution.** Within a single document, duplicates are merged by exact name match. Across documents, the same concept extracted from two sources will appear as two unrelated topics. Resolving this requires embeddings. At single-document scale, the gap is invisible.

**No persistent queue or workflow durability beyond minutes.** LangGraph's SqliteSaver handles human-review checkpoints that take hours. Workflows that need to survive process crashes for days, or that need centralized job tracking, would benefit from Temporal. Discussed in RESEARCH.md.

**Filesystem state, no database.** All persistent state lives in `runs/` and `.cache/` directories. A multi-machine deployment would replace this with object storage (S3) for files and a database for run metadata. For a single-machine prototype, the filesystem is the right answer.

**Plain Python sequential orchestration outside the LangGraph nodes.** The CLI is a single-threaded process. Multiple documents are processed by invoking the CLI multiple times, not by a worker pool. A worker pool would be required at scale and is discussed in RESEARCH.md.

**No web UI for human review.** The reviewer edits a JSON file in their `$EDITOR`. A more polished system would have a web form. The tradeoff is build complexity versus reviewer comfort. The JSON-file approach has the operational benefit of being trivially scriptable — a CI bot could approve runs by writing the JSON file directly.

**No authentication, no multi-tenancy, no audit log of who-edited-what.** This is a prototype on one machine.

---

## 8. Results and observations

*This section will be filled with concrete observations from running the prototype against the three test inputs. The reader of this draft should treat it as a placeholder.*

### Test inputs

Three markdown inputs in `samples/`, chosen to exercise different parts of the system.

**`clean_roadmap.md`** — a structured backend development roadmap with clear H1/H2 sections and explicit topic enumeration. Designed to exercise the happy path. Expected behavior: the system extracts ~30–40 topics, produces a prerequisite graph that topologically sorts, completes without retries, does not interrupt for human review.

**`messy_tutorial.md`** — a narrative React Hooks tutorial with mixed prose, code blocks, and headings. Topics are present but not always heading-titled. Designed to exercise the retry-with-feedback path. Expected behavior: one or two sections produce malformed or ambiguous output on the first attempt; retries with feedback succeed; the human-review interrupt may trigger.

**`adversarial_prose.md`** — a personal essay on engineering culture, with no formal structure and topics buried in narrative. Designed to exercise flag-don't-fail. Expected behavior: several sections produce low-quality extractions or hit max retries; the run completes in a flagged state with partial output.

### Observations

*[To be completed after the first live run. Notes to capture:*

- *Per-input retry counts, flag counts, completion status.*
- *Specific examples of validation errors that triggered retries and whether the retry succeeded.*
- *Total token usage and cost per input.*
- *Subjective quality of the extracted topics and relationships — does the prerequisite graph look defensible?*
- *Edge cases or unexpected behaviors discovered.*
- *Anything that worked better than expected, or worse.]*

### Limitations of the current approach

The two most important limitations have been called out above and bear repeating: structural validation does not catch semantic errors, and cross-document concept resolution does not exist. A third limitation, less discussed: the system has no concept of *confidence*. Every extracted topic is treated as equally certain. A real production system would surface confidence signals — model self-reported confidence, agreement across multiple sampling runs, or LLM-as-judge scores — and use them to route low-confidence items to human review more aggressively than retried-once items.

### How this would improve

Concretely, the three highest-leverage upgrades would be:

1. **LLM-as-judge semantic validation.** A second pass that asks a separate model to evaluate the proposed skill map's correctness, with disagreements escalated to human review. Doubles cost; substantially improves quality.
2. **Confidence-driven human review.** Replace the binary "any retry → review" trigger with a confidence score and a tunable threshold.
3. **Cross-document concept resolution.** Embed topic names, look them up against a vector store of previously-seen topics, deduplicate at the system level. Unlocks the value of building a knowledge base across many documents.

---

## 9. Glossary

**API** — Application Programming Interface.

**CDN** — Content Delivery Network. Used here to load the Mermaid script in the HTML report.

**DAG** — Directed Acyclic Graph. The prerequisite subgraph of the skill map must be a DAG; otherwise there is no valid learning order. The pipeline itself is also a DAG of stages.

**HITL** — Human-In-The-Loop. A workflow pattern where a human reviews or approves output at a checkpoint.

**Idempotency** — A property of an operation whereby applying it N times has the same effect as applying it once. Achieved here through content-hash caching.

**LangGraph** — A Python library by the LangChain team for building stateful agentic workflows as graphs. Distinct from the broader LangChain framework.

**LLM** — Large Language Model. The Anthropic Claude model used for extraction and relationship identification.

**LLM-as-judge** — An evaluation pattern where one language model is used to assess the output of another.

**MTok** — One million tokens. Used in cost computation; Anthropic's pricing is denominated in dollars per MTok.

**Pydantic** — A Python library for runtime data validation via type annotations. Used at every stage boundary.

**RAG** — Retrieval-Augmented Generation. A pattern where an LLM is given retrieved context to ground its output. Not used here because the input is already the full document.

**Schema validation** — Checking that data conforms to a declared structure. Distinct from semantic validation, which checks correctness of content.

**SHA-256** — A cryptographic hash function. Used here to compute the idempotency key from input bytes.

**SqliteSaver** — LangGraph's built-in checkpointer that persists state to a SQLite file. Used here for durable human-review interrupts.

**Temperature** — A language-model sampling parameter. `temperature=0` produces the highest-probability token at each step, minimizing variance.

**Tool-use** — Anthropic's structured-output API mechanism. The model is given a tool with a JSON Schema and emits output that conforms to that schema. Distinct from prompting the model to produce JSON in free-form text.
