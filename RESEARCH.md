# Research & Analysis — Challenges of Building Reliable AI-Assisted Processing Workflows

This is the Part 2 deliverable. The companion DESIGN.md covers what was built. This document zooms out: what is actually hard about building reliable AI-assisted workflow systems, what engineering patterns address those challenges, what the relevant tool landscape looks like, and where the tradeoffs sit.

The prototype I built is one point in a much larger design space. Most of the choices I made are defensible at prototype scale and indefensible at production scale, and vice versa. The point of this document is to explain that landscape with enough specificity that the choices in either direction can be made deliberately, not by inertia.

---

## 1. Framing the problem

A "reliable AI-assisted workflow" is a system in which an LLM (or several) participates as one component of a longer pipeline, and the system as a whole produces useful output despite the LLM being unreliable in well-known ways. The LLM is the source of variance. The rest of the system is the reliability scaffolding around it.

Three properties make this category of system distinct from classical software:

1. **The core component is non-deterministic.** Even at `temperature=0`, the same input can produce different outputs. Outputs can be malformed. Outputs can be confidently wrong. Classical software engineering assumes deterministic primitives; AI workflows do not.

2. **Failure is partial, not binary.** A traditional service either responds correctly or returns an error. An LLM service responds with something — almost always — and that something might be correct, partially correct, structurally valid but semantically wrong, or completely fabricated. The system has to grade the response, not just check whether one arrived.

3. **The cost surface is unusual.** Each call to an LLM costs real money, scales with token count, and varies by model. Architectures that work for "free-after-deployment" services break down when each component is metered per-use.

These three properties together explain why "just call the API in a loop" produces brittle systems. The engineering is in everything between the loop and the model.

---

## 2. What actually goes wrong

A reliable workflow has to handle these specific failure modes. They are not equally common or equally severe.

### Hallucination

The model produces output that looks plausible but is factually wrong. In the skill-extraction case: a topic that wasn't in the source, a prerequisite relationship that contradicts the actual learning order. Hallucination is the failure mode that most resists structural mitigation, because the output passes every schema check; it's wrong at a level only domain knowledge can detect.

The defenses are partial: ground the model in source text (so it has less to invent), keep prompts narrow (so the failure surface is small), use temperature=0 (less variance, though not less hallucination), and validate semantically with a second LLM call (LLM-as-judge) or a human (HITL). None of these eliminates hallucination. They reduce its rate and route the residue to review.

### Malformed structured output

The model is asked for JSON and returns text. The model returns JSON with the wrong shape. The model omits a required field. The model invents enum values that weren't in the schema. This is the category that tool-use / function-calling APIs largely solve. By declaring a JSON Schema at the API level, the provider enforces structural conformance server-side. Pydantic validation on the client side catches the remaining edge cases.

The category that survives even tool-use is when the model produces structurally valid but business-rule-invalid output: edges that reference IDs not in the topic set, prerequisite cycles, duplicate entries. These need application-level validation, which is the layer most candidates skip.

### Tool-use refusal

A subtler failure: the model declines to call the tool and writes a text response instead. This is rare with current Claude but possible. The standard handling is to treat it as a validation failure and feed back to the model: "You must respond by calling the tool." Adds two lines per stage and prevents a confusing crash.

### Non-determinism

The same input on different runs produces different outputs. Even at temperature=0, sampling can vary slightly due to provider-side implementation details. The defenses are caching (so the second-and-subsequent runs of identical input return identical output, deterministically) and pinning the model version (so the LLM behavior doesn't drift under your feet between deploys).

### Drift across model versions

The provider releases a new model checkpoint; your prompts that worked yesterday produce different output today. This is one of the most pernicious failure modes because it can be silent: nothing breaks, the output just shifts. Defenses: pin model versions (don't use rolling aliases), build an eval set (so you can detect drift quantitatively), and version your prompts alongside your code (so prompt changes are reviewable).

### Rate limits and transport failures

The API returns HTTP 429 or 5xx. These are operational, not semantic. Handled by an outer retry layer with exponential backoff and jitter, separated from the validation-retry layer above. The two layers should not be conflated.

### Latency variability

LLM responses can take seconds. Long documents take longer. Long-running workflows compound. At interactive scale, this drives the choice toward async APIs with progress feedback. At batch scale, this drives the choice toward queue-based execution with timeouts and budgets.

### Cost runaway

A misconfigured retry loop or a runaway agent can rack up thousands of dollars before anyone notices. Defenses: bounded retries (always), token budgets per request (the `max_tokens` parameter), per-run cost telemetry surfaced on a dashboard, and at scale, hard budget alerts that pause the system above a threshold.

---

## 3. Engineering patterns that work

These are the patterns that recur across reliable workflow implementations. Each one solves a specific failure mode from Section 2.

### Schema-constrained output

Forcing the model to emit JSON that conforms to a declared schema is the single most reliable structural mitigation available. Implementation varies: Anthropic's tool-use, OpenAI's function-calling / structured outputs, Google's controlled generation, or constrained sampling at the token level for local models (Outlines, llama.cpp grammar). Tool-use is materially more reliable than prompting for JSON in free-form text — and the prompt for "please return JSON" trick is the single most common avoidable mistake in early LLM code.

### Validation as a first-class layer

Schema validation catches structural errors. Business-rule validation catches the remaining structurally-valid-but-wrong outputs. They should be separate layers, separately testable, separately reportable. In the prototype: Pydantic validation gates the schema layer; a per-rule check function with explicit error codes gates the business-rule layer; a separate `ValidationEvent` object captures both for surfacing in the report. This separation is what lets the system distinguish "the LLM produced malformed output" (retry with feedback) from "the LLM produced output that contradicts our constraints" (still retry with feedback, but the feedback is different and more interpretable).

### Retry with feedback (self-correction)

Naive retry repeats the same failure. The same prompt produces the same kind of mistake. Including the specific validation error in the next prompt — "Your previous response failed validation because field X had value Y; valid values are [...]" — typically succeeds on the second attempt. This is the single most underrated reliability technique. The cost is one extra LLM call on the retry path; the benefit is that most validation failures recover automatically.

There is a literature on this under names like Self-Refine, Reflexion, and Constitutional AI. The core idea is the same: the model can usually fix its own output if told what went wrong.

### Flag-don't-fail

When retries are exhausted, the workflow should not crash. Partial output with a flag is more useful than no output. The flag becomes a triage signal for a human reviewer. The runs-index in the prototype makes flagged runs visually obvious so an operator can intervene without searching.

This is also the right design at scale. A pipeline processing 10,000 documents with a 2% error rate that fails the whole pipeline produces zero output. The same pipeline with flag-don't-fail produces 9,800 clean outputs and 200 flagged ones for review. The triage workload is bounded; the throughput is not.

### LLM-as-judge for semantic validation

The pattern: a second LLM call evaluates the first one's output. The evaluator model can be the same or a different model. It is asked to produce a structured assessment — "is this output correct, partially correct, or wrong, and why?" — that the workflow can act on.

This is the natural extension when schema validation isn't enough. It catches a meaningful fraction of hallucinations and semantic errors that pass all structural checks. The costs are real: it doubles per-run LLM spend, it inherits the evaluator model's own biases, and it needs its own evaluation set to verify the evaluator is calibrated.

In the prototype I did not implement this, partly for cost and partly because building it well is a project of its own. It's the highest-leverage upgrade for the next iteration.

### Idempotency through content addressing

Cache by a hash of the input content, not by a request ID. Two callers sending the same content get the same answer; a single caller re-running the same input gets the same answer; a retry after a partial failure converges on the same answer. This sidesteps LLM non-determinism for all runs after the first.

The discipline is to make the input definition stable. If the cache key is computed over content that changes between runs (timestamps, request IDs, anything the LLM doesn't actually see), the cache hit rate collapses.

### Determinism where possible

`temperature=0` doesn't make the model fully deterministic, but it reduces variance. Pinning the model version eliminates one source of drift. Pinning prompt strings eliminates another. Logging the (model_version, prompt_hash, input_hash) tuple per call makes drift detectable post-hoc.

### Observability stack

LLM workflows need everything traditional services need — structured logs, metrics, traces — plus three categories specific to the LLM layer: per-call prompt/response capture, token usage telemetry, and cost tracking. The prototype's per-run HTML report and runs-index are the minimum viable version of this; at scale you'd ship the same data to a centralized aggregator.

The tooling for LLM-specific observability is young and converging. LangSmith is the obvious choice if you're already on LangGraph (native integration, zero extra code). Langfuse is the open-source alternative, vendor-neutral. Helicone provides observability via a proxy in front of the LLM provider — useful if you can't modify the calling code. Arize Phoenix is eval-focused, valuable when you have a regression suite. OpenTelemetry traces are the standard substrate, and most of the above integrate with it.

### Bounded retries, separately for transport and validation

Transport retries (network failures, rate limits) and validation retries (content failures) are different concerns. Transport retries should use exponential backoff with jitter; validation retries should use feedback injection and short fixed delays. Both must be bounded — unbounded retry loops are the canonical source of cost runaway.

### Human escalation as part of the workflow, not as a failure

The most operationally serious change in recent AI workflow practice is treating human review as a first-class workflow stage, not as the failure mode. The prototype's conditional HITL interrupt is one form of this. The shape that scales is: the workflow has explicit human-review nodes, they have queues, humans pick work off the queue, the workflow resumes durably. Tools like LangGraph (with checkpointing) and Temporal (with signals) support this natively. Without durable execution, the human becomes a process-uptime hostage.

---

## 4. The tool landscape

For each category, I evaluate the relevant options against the prototype's needs and against a hypothetical production deployment. The criterion is not "which is best in some absolute sense" but "which is best for which shape of problem."

### Orchestration

**LangGraph.** State-graph orchestration with built-in interrupt/checkpoint primitives. Distinct from the broader LangChain framework. Strengths: durable HITL is its sweet spot; the state model is explicit and inspectable; integrates natively with LangSmith for observability. Weaknesses: ergonomics are still rough in places (conditional edges are verbose); the documentation lags the library; using it for purely linear workflows is over-engineering. **Choose when:** you have conditional flow, branching, or durable interrupts and a single-process or single-tenant scope. The prototype uses it for these reasons.

**Temporal.** Durable execution platform with worker processes, replay-based recovery, and rich client SDKs. Strengths: production-grade durability — workflows survive process crashes, version upgrades, network partitions; the programming model is straightforward once you internalize it; supports human-in-the-loop via signals; the operator UI is good. Weaknesses: heavyweight to deploy — needs a Temporal server (or Temporal Cloud), workers, persistence layer; the SDK constraints (deterministic workflow functions, mandatory activity boundaries) take time to internalize. **Choose when:** workflows span hours or days, must survive crashes, and reliability is a hard requirement. This is what I'd reach for if the prototype became a real production system.

**Airflow.** Scheduled DAG orchestration. Strengths: the operator UI is the industry reference; mature, widely deployed; rich ecosystem of operators; good for time-triggered batch jobs. Weaknesses: built for static DAGs and scheduled runs, not event-driven workflows; the scheduler/executor/database/UI footprint is heavy; human-in-the-loop is bolted-on (manual operator with timeouts), not native; the AI use case is awkward. **Choose when:** the workload is genuinely scheduled batch (nightly ETL) and your team already runs Airflow. Don't choose for AI workflows specifically. The prototype borrows Airflow's grid-view aesthetic for its runs-index page without adopting any of its infrastructure.

**Prefect.** Workflow orchestration with scheduling and retries, primarily for data engineering. Similar shape to Airflow but more Pythonic and easier to host. Strengths: ergonomics are better than Airflow; Prefect Cloud handles the infrastructure; supports both scheduled and event-driven flows. Weaknesses: like Airflow, the primary domain is data pipelines, not AI inference; the AI orchestration story (via the ControlFlow library) is layered on top.

**Inngest, Trigger.dev, Restate.** Modern durable-function platforms, JS-leaning but expanding. The conceptual shape is "write a function, the platform handles durability and retries." Strengths: lightweight to start; good observability built-in; the JavaScript ergonomics are clean. Weaknesses: less mature than Temporal; smaller ecosystem; Python support is variable. **Worth watching** as the durable-execution space matures.

**Plain Python.** No framework at all. Strengths: zero abstraction tax; every line is inspectable. Weaknesses: durable execution requires re-implementation; observability requires building from scratch. **Choose when:** the workflow is linear, fits in one process, and is small enough that the framework's value doesn't pay for its complexity. I considered this for the prototype and rejected it because the durable HITL requirement was load-bearing.

### Structured output

**Anthropic tool-use / OpenAI function-calling / structured outputs.** Native provider APIs that force schema conformance. The right answer for hosted models. Strengths: maximum reliability; server-side enforcement; works with any schema. Weaknesses: slightly more verbose than free-form JSON prompts; the schema must be expressible in JSON Schema (no recursive types in some implementations).

**Groq's OpenAI-compatible function-calling.** Groq hosts open-source models (Llama, Mixtral, Qwen) behind an OpenAI-compatible API. Tool-use semantics match OpenAI's. Strengths: free tier exists, latency is roughly 5–10× lower than hosted Claude/GPT for similar-size models, and the API surface is identical to OpenAI's — so the LLMClient abstraction can swap between providers with no schema changes. Weaknesses: open-source models are less reliable at strict tool-use than Claude or GPT-4-class models — expect a higher rate of MISSING_TOOL_USE and schema-violation failures in the tail; free tier is rate-limited (TPM and daily token caps), which bites bursty workloads like parallel-fan-out extraction. This project migrated mid-build from Anthropic to Groq when API costs became a constraint; the migration touched only `llm.py` and its tests, which validated the protocol-based LLM abstraction.

**Pydantic.** Python's de facto runtime validation library. Strengths: Pydantic v2 is fast; integrates with FastAPI, LangChain, Instructor; generates JSON Schema directly from type annotations. Used at every stage boundary in the prototype.

**Instructor.** Library that wraps OpenAI/Anthropic to return Pydantic models directly. Strengths: ergonomic; handles retries with re-asking; a one-line replacement for `client.messages.create()`. Weaknesses: hides the underlying tool-use mechanism. **Choose when:** writing a lot of LLM-calling code in an existing codebase and you want consistency. **Skip when:** the tool-use mechanism is something you want explicit ownership of, as in this prototype where it's a defensible engineering decision in itself.

**PydanticAI.** Similar to Instructor, by the Pydantic team. Strengths: native Pydantic integration; clean API; good ergonomics for agentic patterns. Weaknesses: newer, less battle-tested. **Worth choosing** for new projects, especially Pydantic-heavy ones.

**Guardrails AI.** Validation framework with its own RAIL spec language for declaring constraints. Strengths: built-in validators for common cases (toxicity, PII, format); re-asking on validation failure is built in. Weaknesses: the RAIL DSL is a separate thing to learn; the underlying mechanism (re-asking with validation feedback) is what we already implemented manually; the abstraction can be in the way as often as it helps. **Choose when:** the validation library has validators you want to reuse and the DSL ergonomics fit your team.

**Outlines.** Constrained generation library that constrains token sampling to match a grammar or schema. Powerful for local models. Strengths: works at the token level — the model literally cannot emit non-conforming output. Weaknesses: requires access to the sampling process, so doesn't work with hosted APIs that don't expose it. **Choose when:** running local models and you need hard guarantees.

**DSPy.** Programmatic prompt optimization framework. Compiles prompts via search over a training set. Strengths: novel approach, can substantially improve prompt quality. Weaknesses: orthogonal to structured output specifically — DSPy is about *what* prompt to send, not about *how to validate the response*. **Different category** that gets conflated with this one. **Choose when:** prompt quality is the bottleneck and you have data to optimize against.

### Job queues and async processing

**Celery.** The classic Python distributed task queue. Strengths: mature, widely deployed, supports multiple brokers (Redis, RabbitMQ). Weaknesses: configuration is non-trivial; the default ergonomics are dated; debugging across workers is harder than single-process. **Choose when:** you need to scale workers and have Celery expertise on the team.

**Redis Queue (RQ).** Lightweight Python job queue on Redis. Strengths: simpler than Celery; one fewer service if you already have Redis. Weaknesses: less feature-rich; smaller ecosystem.

**Dramatiq, Arq.** Modern alternatives to Celery. Strengths: better ergonomics; cleaner async support. Weaknesses: smaller communities. **Worth considering** for new Python projects that need a job queue.

**Kafka.** Event streaming platform, often miscategorized as a queue. Different semantics — events are not consumed-and-deleted, they persist on a topic, multiple consumers can read independently. Strengths: massive scale; durable event log; multiple consumer patterns. Weaknesses: heavy operationally; wrong shape for "one-shot job execution"; Kafka Streams adds a separate complexity. **Choose when:** you have event-driven architecture, multiple downstream consumers per event, and the scale to justify the infrastructure.

**SQS, Pub/Sub, Service Bus.** Managed queue services on the major clouds. Strengths: zero operational overhead; pay-as-you-go; FIFO and at-least-once semantics. Weaknesses: vendor lock-in; less flexible than self-hosted. **Choose when:** already on the cloud and the managed service's semantics fit.

**Nothing.** For a single-process prototype processing one document at a time, no queue is needed. Adding one would be over-engineering. This was the prototype's decision.

### Observability for LLMs

**LangSmith.** Hosted observability platform by the LangChain team. Strengths: native integration with LangGraph (set an env var, traces appear); good prompt-management features; built-in evaluation. Weaknesses: vendor-specific; pricing scales with volume. **Choose when:** already on LangGraph and you want zero-effort tracing.

**Langfuse.** Open-source LLM observability. Strengths: self-hostable; vendor-neutral; growing ecosystem. Weaknesses: less polished than LangSmith; integrations require explicit instrumentation. **Choose when:** vendor neutrality matters and you can run the service.

**Helicone.** Proxy-based observability — sit between your code and the LLM provider, capture everything. Strengths: zero code changes; works with any provider. Weaknesses: an extra hop in the network path; less flexible than instrumented integration. **Choose when:** you can't modify the calling code (third-party app) or you want quick coverage.

**Arize Phoenix.** Eval-focused observability. Strengths: strong evaluation features; good for offline analysis. Weaknesses: less of an operational dashboard, more of an analysis tool. **Choose when:** evaluation is a primary concern.

**OpenTelemetry.** The open standard for distributed tracing. Strengths: vendor-neutral; works with any backend (Honeycomb, Datadog, Jaeger, etc.); LLM-specific semantic conventions exist (`gen_ai.*` attributes). Weaknesses: requires explicit instrumentation; the LLM conventions are still stabilizing. **Choose when:** building observability for the long term and integrating with existing OTel infrastructure.

**structlog + plain logging.** Structured JSON logs to stdout, aggregated downstream. Strengths: free; works everywhere; no vendor dependency. Weaknesses: no built-in dashboard. **Choose when:** starting simple. This is what the prototype uses.

---

## 5. Tradeoff analysis

A few cross-cutting questions worth naming explicitly.

### Framework reach vs custom code

Every framework in the previous section is a tradeoff between "the framework handles a concern for me" and "I have one more dependency whose semantics I need to understand and whose changes I need to track." The decision rule I use: a framework earns its keep when its primary abstraction matches a concern you actually have. LangGraph's StateGraph matches "I have conditional flow with durable interrupts." If you don't have that concern, LangGraph is overhead. The same test applies to Guardrails, Celery, Temporal, anything.

The failure mode in both directions is real. Under-framing produces code that reinvents primitives badly (the "I'll just write my own queue" disaster). Over-framing produces code where the framework is doing more than the application — the application is a thin layer over framework conventions. The healthy zone is using a framework for its primary concern and writing custom code for everything else.

### Async vs sync, realtime vs batch

A request-response API in front of an LLM workflow has user-perceived latency as its primary constraint. The architecture pushes toward async APIs, streaming responses, and aggressive caching. A batch workflow processing documents in the background has throughput and cost as primary constraints. The architecture pushes toward queues, parallel processing, and bounded budgets per job.

These are different systems even when the LLM part is the same. The mistake is treating them as the same and getting an architecture that's bad at both. The prototype is firmly in the batch shape: CLI invocation, per-document processing, no synchronous API. Building a realtime version would be a different project.

### Structured outputs vs free-text outputs

Structured outputs (tool use) are the right choice when you know what shape the response should take. Free-text outputs are the right choice when you don't — open-ended generation, summarization, creative writing. The middle ground — "structured output where the model also explains its reasoning" — is handled by adding a `rationale` field to the schema, which is what the prototype does for relationships.

A failure mode worth flagging: structured outputs can mask interesting failures. If the model says "here's a topic" with full confidence even when the source contains no topic at all, the structured output looks fine. The free-text alternative ("there are no topics in this section") is sometimes more honest. The defense is either explicit allowance for empty outputs in the schema, or LLM-as-judge to evaluate whether the structured output is appropriate.

### Reliability through redundancy vs reliability through validation

One school says: run multiple samples and take the majority. Another says: run one sample and validate it thoroughly. Both work. The redundancy approach (self-consistency, ensemble methods) is simpler to implement but more expensive at runtime. The validation approach is harder to implement well but cheaper per call. For high-stakes outputs, both together is the right answer; for the prototype, validation alone is enough.

---

## 6. What I would do differently at production scale

A short bridge from the prototype to a hypothetical production system, in priority order.

**1. LLM-as-judge for semantic validation.** A second LLM call after relate, evaluating whether the proposed skill map is plausible. Disagreements between the judge and the original output escalate to human review. Doubles per-run cost; substantially improves output quality. This is the single biggest reliability upgrade available.

**2. Confidence-driven HITL.** Replace the binary "any retry → review" trigger with a confidence score derived from the judge model's assessment, model-reported logprobs, or sampling-based agreement. Review threshold becomes tunable. Reviewer load becomes predictable.

**3. Durable execution beyond minutes.** Move from LangGraph's AsyncSqliteSaver to Temporal. Workflows survive process crashes, can be paused for days, can be inspected and intervened on through Temporal's UI. The operational story becomes drastically better at scale.

**4. Cross-document concept resolution.** Embed every extracted topic, look up against a vector store of previously-seen topics, deduplicate at the system level. Unlocks the value of building a knowledge base across many documents. Today each document is independent; at scale, the same topic ("React Hooks") should resolve to one canonical entity.

**5. Queue and concurrent processing.** Replace inline CLI invocation with a managed queue (SQS, Cloud Tasks, or self-hosted Celery). Workers pull jobs concurrently with a rate-limit-aware concurrency cap. Surface queue depth and worker health on the operator dashboard.

**6. Centralized observability.** Logs to a SIEM, traces via OpenTelemetry to Honeycomb or Datadog, LLM-specific telemetry to LangSmith or Langfuse. The runs-index HTML page is the prototype's substitute for this stack; in production it would be a fallback view, not the primary one.

**7. Cost control and budget enforcement.** Per-tenant and per-workflow budgets with hard limits and alerts. Model routing — easy sections to a cheap model (Haiku), hard sections to a premium model (Sonnet or Opus). Periodic cost-review automation. Anthropic publishes per-MTok rates; build the model that consumes them.

**8. Multi-tenancy and authentication.** Tenant isolation across runs, caches, credentials. SSO for the operator dashboard. Audit trail of who edited which review file.

Each of these is a real project, not a feature flag. Sequenced over months, not days.

---

## 7. Closing observations

A few opinions, offered with the understanding that some of them will look wrong in two years.

**The LLM is rarely the bottleneck of reliability.** When an AI workflow misbehaves, the most common cause is the surrounding code: a retry loop that retries the wrong thing, a validation rule that's too permissive, a cache key that doesn't account for prompt changes, a state machine that loses state across an exception. The model itself, with tool-use and validation in front of it, is one of the more predictable components in most systems I've seen.

**Tool sprawl is the second most common failure.** Teams reach for LangChain because they heard about it, then Guardrails because it was mentioned in a blog post, then a vector store because the architecture diagram had one, then LangSmith because the LangChain docs suggest it. Each addition seems reasonable; the aggregate is a Frankenstein of frameworks where no one understands the seams. The discipline of saying "we have this concern, here's the one tool that addresses it, here's the line of code that uses it" is undervalued.

**Observability is the most undervalued layer.** Teams will spend weeks tuning prompts and zero hours on per-run telemetry. The result is workflows that produce 95% good output but no one knows which 5% is bad and why. Adding cost, token usage, and validation events to a structured log per call costs an afternoon and pays back forever. The operator-facing view (the prototype's runs-index page) is a small step from that, and it's the part the operator's leadership will look at.

**Durable HITL is the next big primitive.** "Human review as a workflow stage" is the pattern that turns AI tools from demos into systems people trust. LangGraph's interrupt API and Temporal's signals are both early versions of this. Expect the abstractions to keep improving. Expect the operational practice of "queue of items awaiting human review" to become as standard as the queue of items awaiting processing.

**The right architecture is rarely the latest one.** Plain Python, Pydantic, an LLM SDK, and structlog will produce a defensible LLM workflow today. Adding LangGraph buys you state machines and HITL. Adding Temporal buys you durable execution. Adding LangSmith buys you tracing. Each addition is justified by a concern. Most teams should add one at a time, in the order the concerns appear, and resist the pressure to adopt the whole stack on day one.

The prototype this document accompanies is a deliberate effort to do exactly that: minimum viable additions, each one earning its keep, with the rest discussed honestly here rather than dragged into the build.

A coda from this project specifically: we migrated LLM providers once during the build (Anthropic → Groq, for cost). The contained-edit scope was a function of one design decision made early: the LLM lives behind a `Protocol`, and stage modules call into the Protocol, not the concrete client. The abstraction was not speculative — it earned its keep the first time we needed to change something below it. That experience is the strongest argument for the "minimum viable abstraction" rule: don't build an abstraction until you have a concrete second use case, but when you have one, build it cleanly. The flip side is also worth naming: the abstraction shielded the application code from the provider switch, but the test infrastructure had to adapt (Groq's SDK validates the API key eagerly at constructor time, whereas Anthropic's deferred it; this broke seven tests that relied on default-construction without a key). The lesson: protocols abstract the call surface but not the lifecycle.
