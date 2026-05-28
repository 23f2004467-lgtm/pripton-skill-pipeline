# CLAUDE.md

This project's behavioral guidelines live in **[AGENTS.md](AGENTS.md)** — read it before writing any code. It is the authoritative spec wrapper (four principles, dependency allow/deny lists, surgical-change discipline). The implementation spec is **[PLAN.md](PLAN.md)** (21-step checklist in Section 12).

Do not edit `PLAN.md`, `DESIGN.md`, `RESEARCH.md`, or `README.md` without explicit approval — they are submission deliverables.

## Project: Pripton Skill Pipeline

A workflow system that turns a markdown learning document into a structured skill map (topics + typed relationships) using an LLM. LangGraph orchestration, Anthropic tool-use for structured output, Pydantic validation, networkx cycle detection, Jinja2 reports. CLI-only, single LLM provider (Anthropic).

## Current state (verified 2026-05-28)

The build is **complete** — all 21 steps in the checklist are implemented and committed (latest: `step 19: CI workflow`). `STATUS.md` is **stale** (says 35%); trust the code and git log, not STATUS.md.

- Source: `src/skillpipeline/` (one file per pipeline stage, mirrors the workflow diagram)
- `214 tests pass` via `pytest` — no API key needed (LLM mocked at the boundary via `FakeLLMClient`)
- Per-run output lands in `runs/`; `runs/index.html` is the operator dashboard

## Commands

- `python3 -m pytest -q` — full test suite (no API key)
- `ruff check .` — lint
- `mypy src` — type check (strict)
- `python3 -m skillpipeline run samples/clean_roadmap.md` — run the pipeline (needs `ANTHROPIC_API_KEY`)

`python` is not on PATH — use `python3`.
