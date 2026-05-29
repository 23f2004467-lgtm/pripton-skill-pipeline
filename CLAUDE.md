# CLAUDE.md

This project's behavioral guidelines live in **[AGENTS.md](AGENTS.md)** — read it before writing any code. It is the authoritative spec wrapper (four principles, dependency allow/deny lists, surgical-change discipline). The implementation spec is **[PLAN.md](PLAN.md)** (21-step checklist in Section 12).

Do not edit `PLAN.md`, `DESIGN.md`, `RESEARCH.md`, or `README.md` without explicit approval — they are submission deliverables.

## Project: Pripton Skill Pipeline

A workflow system that turns a markdown learning document into a structured skill map (topics + typed relationships) using an LLM. LangGraph orchestration, tool-use / function-calling for structured output, Pydantic validation, networkx cycle detection, Jinja2 reports. CLI-only. The LLM provider is **Groq** (`llama-3.3-70b-versatile`), behind a swappable `LLMClient` protocol (originally Anthropic, migrated to Groq mid-build — see DESIGN.md §8).

## Current state

The build is **complete** — all 21 checklist steps implemented and committed, plus post-build hardening (token telemetry, content-cache key, async/checkpointer fixes, bounded extract concurrency, prompt-injection mitigation, a provider-response-parsing test). `STATUS.md` reflects this.

- Source: `src/skillpipeline/` (one file per pipeline stage, mirrors the workflow diagram).
- **231 tests pass** via `pytest` — no API key needed (LLM mocked at the boundary via `FakeLLMClient`).
- Per-run output lands in `runs/`; `runs/index.html` is the operator dashboard.

## Commands

- `python3 -m pytest -q` — full test suite (no API key).
- `ruff check .` — lint (gated in CI).
- `mypy src` — type check, run locally only (intentionally **not** gated in CI; pre-existing type debt — see `.github/workflows/ci.yml`).
- `set -a && source .env && set +a` — load `GROQ_API_KEY` (the code does not auto-load `.env`).
- `python3 -m skillpipeline run samples/clean_roadmap.md` — run the pipeline (needs `GROQ_API_KEY`).

`python` is not on PATH — use `python3`. Run from the repo root.
