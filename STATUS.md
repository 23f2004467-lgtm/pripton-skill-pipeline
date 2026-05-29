# Build Status

**Complete.** All 21 build-checklist steps in [PLAN.md](PLAN.md) (Section 12) are implemented and committed, including the Step 21 live-run pass. The full pipeline runs end-to-end — ingest → extract → merge → human-review → relate → validate → persist — producing a structured skill map plus a self-contained HTML report and the runs-index dashboard. The test suite passes (231 tests, no API key required; the LLM is mocked at the boundary), `ruff check .` is clean, and CI (`.github/workflows/ci.yml`) gates `ruff` + `pytest`. See PLAN.md for the architecture and per-step detail, and `README.md` for usage.

## Notes for a reviewer landing here

- **LLM provider:** the pipeline now runs on **Groq** (`llama-3.3-70b-versatile`) via a `GroqLLMClient` behind the `LLMClient` protocol. This was a deliberate migration from Anthropic; some of the prose deliverables (DESIGN.md / RESEARCH.md) may still describe the original Anthropic design.
- **Committed run artifacts** live under `runs/` — three Step 21 samples (clean / messy / adversarial) plus one `--always-review` human-in-the-loop cycle (interrupt → resume). Open `runs/index.html` for the operator view, or any `runs/*/report.html`.
- **Type checking:** `mypy` runs locally (`mypy src`) but is intentionally not gated in CI; clearing the pre-existing type-debt is a separate cleanup pass.
