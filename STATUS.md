# Build Status Dashboard

## Implementation Progress: 35% Complete

### ✅ DONE (7/21 Steps)
```
Step 1: Project Skeleton       [████████████████████] 100%
Step 2: Domain Models          [████████████████████] 100%
Step 3: LLM Client Wrapper    [████████████████████] 100%
Step 4: Ingest Stage          [████████████████████] 100%
Step 5: Extract Stage         [████████████████████] 100%
Step 6: Merge Stage           [████████████████████] 100%
Step 7: Validate Stage        [████████████████████] 100%
```

### ⏳ IN PROGRESS (21 Steps)
```
Step 1:  Project Skeleton       [████████████████████] 100%
Step 2:  Domain Models          [████████████████████] 100%
Step 3:  LLM Client Wrapper    [████████████████████] 100%
Step 4:  Ingest Stage          [████████████████████] 100%
Step 5:  Extract Stage         [████████████████████] 100%
Step 6:  Merge Stage           [████████████████████] 100%
Step 7:  Validate Stage        [████████████████████] 100%
Step 8:  Retry Helper          [██████            ] 40%  (implemented inline across extract/validate)
Step 9:  Relate Stage          [                    ] 0%
Step 10: Human-Review Stage    [                    ] 0%
Step 11: Cache                 [                    ] 0%
Step 12: Graph Orchestration   [                    ] 0%   (needs all stages)
Step 13: Report Generator      [                    ] 0%
Step 14: Runs-Index Generator  [                    ] 0%
Step 15: Pipeline Orchestrator [                    ] 0%   (needs 12, 13, 14)
Step 16: Stats Command         [                    ] 0%
Step 17: CLI                   [                    ] 0%   (needs 15, 16)
Step 18: E2E Test              [█████             ] 25%  (basic stage tests exist)
Step 19: CI Configuration      [                    ] 0%
Step 20: Sample Inputs         [████████████████████] 100%
Step 21: Live Run Pass         [                    ] 0%
```

---

## Files by Category

### Documentation & Config ✅
- ✅ PLAN.md, DESIGN.md, RESEARCH.md, README.md, AGENTS.md
- ✅ pyproject.toml (with all deps)
- ✅ .env.example, .python-version, .gitignore
- ✅ Directory structure (src/, tests/, runs/, samples/, .cache/)

### Implementation Modules ❌ (16 files needed)
```
src/skillpipeline/
  ❌ llm.py                    (LLMClient protocol, AnthropicLLMClient, FakeLLMClient)
  ❌ ingest.py                 (document ingestion + section splitting)
  ❌ extract.py                (parallel LLM extraction per section)
  ❌ merge.py                  (deduplication + normalization)
  ❌ validate.py               (business rule validation, cycle detection)
  ❌ retry.py                  (retry-with-feedback utilities)
  ❌ relate.py                 (LLM relationship extraction)
  ❌ human_review.py           (interrupt + resume logic)
  ❌ cache.py                  (content-addressed cache)
  ❌ graph.py                  (LangGraph state machine)
  ❌ report.py                 (HTML report generation)
  ❌ index.py                  (Runs-index HTML generation)
  ❌ pipeline.py               (high-level orchestration)
  ❌ stats.py                  (statistics command)
  ❌ cli.py                    (argparse CLI)
  ❌ __main__.py               (entry point)
```

### Prompts ✅/❌ (3 files)
```
src/skillpipeline/prompts/
  ✅ system.txt                (system role for LLM)
  ✅ extract_topics.txt        (section → topics extraction prompt)
  ❌ extract_relationships.txt  (topics → relationships extraction prompt)
```

### Templates ❌ (2 Jinja2 files)
```
src/skillpipeline/templates/
  ❌ report.html.j2            (per-run HTML report)
  ❌ index.html.j2             (runs-index operator dashboard)
```

### Tests ✅/❌ (9+ test modules + fixtures)
```
tests/
  ✅ test_models.py
  ✅ test_ingest.py
  ✅ test_extract.py
  ✅ test_llm.py
  ✅ test_merge.py
  ✅ test_validate.py
  ❌ test_retry.py
  ❌ test_cache.py
  ❌ test_graph.py
  ❌ test_pipeline_e2e.py

  fixtures/
```    ❌ *_response.json          (mock LLM responses for FakeLLMClient)
```

### CI ❌ (1 file)
```
.github/workflows/
  ❌ ci.yml                    (lint, type-check, test on push)
```

### Samples ✅ (3 files present)
```
samples/
  ✅ clean_roadmap.md          (well-formed input)
  ✅ messy_tutorial.md         (triggers retries)
  ✅ adversarial_prose.md      (triggers flags)
```

---

## Critical Path

The **gate** blocking everything is **Step 3: LLM Client Wrapper** (`llm.py`).

Once Step 3 is done:
- Steps 4, 6, 7, 8, 11 can run in parallel (deterministic, no LLM calls)
- Steps 5, 9 can run in parallel (LLM-calling stages, now unblocked)
- Step 10 (human_review) can be tested in Step 12

```
Step 3 (LLM wrapper)
  ├─→ Steps 4, 6, 7, 8, 11 (parallel)
  └─→ Steps 5, 9 (parallel, after Step 3)
        ├─→ Step 10 (has its own test deps)
        └─→ Step 12 (graph, needs all stages)
              └─→ Step 15 (pipeline)
                    └─→ Step 17 (CLI)
                          └─→ Step 18 (E2E)
                                └─→ Step 19 (CI)
                                      └─→ Step 21 (live run)
```

---

## Verification Checklist

| Item | Status | Notes |
|------|--------|-------|
| Models compile | ✅ | Pydantic + TypedDict present in models.py |
| Dependencies pinned | ✅ | All runtime + dev deps in pyproject.toml |
| Prompts directory exists | ✅ | Empty; needs 3 files |
| Templates directory exists | ✅ | Empty; needs 2 files |
| Samples directory exists | ✅ | All 3 files present (clean, messy, adversarial) |
| Tests directory exists | ✅ | Has fixtures/; needs test_*.py files |
| Runs directory exists | ✅ | Empty; will hold thread outputs |
| Cache directory exists | ✅ | Empty; will hold cached responses |

---

## Next Immediate Action

**Recommended:** Implement Step 3 (llm.py) to unblock the rest of the pipeline.

See PLAN.md Section 12 Step 3 for the spec.

