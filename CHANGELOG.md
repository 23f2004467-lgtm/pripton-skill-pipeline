# Build Change Log

This file tracks all changes made during the build process, enabling resumption in a new terminal session.

---

## Session: 2026-05-28

### Completed Steps

#### Step 1-5: Previously Complete
- Project skeleton, models, LLM client, ingest stage, extract stage (already implemented)

#### Step 6: Merge Stage ✅ (2026-05-28 ~11:20 AM)

**Files Created:**
- `src/skillpipeline/merge.py` — Deduplication and conflict resolution
- `tests/test_merge.py` — 9 tests

**Files Modified:**
- `src/skillpipeline/models.py` — Added `section_id: str | None = None` to `ValidationEvent`
- `src/skillpipeline/extract.py` — Sets `source_section_id` after validation
- `tests/test_extract.py` — Fixed test expectation

#### Step 7: Validate Stage ✅ (2026-05-28 ~11:30 AM)

**Files Created:**
- `src/skillpipeline/validate.py` — Business rule validation for relationships
- `tests/test_validate.py` — 17 tests

**Implementation Details:**
- Validates 7 rule types:
  - `SCHEMA_VIOLATION` (error) — No approved topics
  - `DANGLING_FROM_REF` (error) — from_id not in topic set
  - `DANGLING_TO_REF` (error) — to_id not in topic set
  - `SELF_LOOP` (error) — from_id == to_id (also caught by Pydantic)
  - `DUPLICATE_EDGE` (error) — duplicate (from_id, to_id, type) tuple
  - `CYCLE_IN_PREREQUISITES` (error) — cycles in prerequisite subgraph (networkx)
  - `ORPHAN_TOPIC` (warning) — topic not in any relationship
- Decision logic:
  - No errors → proceed to persist
  - Errors with retries < 3 → increment counter, format feedback, route to relate
  - Errors with retries >= 3 → flag, filter to valid relationships only

**Test Results:**
- 99 tests pass (models: 25, ingest: 18, extract: 16, merge: 9, validate: 17)

---

### Pending Steps (as of 2026-05-28 ~11:30 AM)

#### Step 8: Retry Helper ❌
- File: `src/skillpipeline/retry.py`
- Tests: `tests/test_retry.py`
- Spec: PLAN.md Section 6
- Note: format_feedback() already implemented in validate.py

#### Step 9: Relate Stage ❌
- File: `src/skillpipeline/relate.py`
- Prompt: `src/skillpipeline/prompts/extract_relationships.txt`
- Tests: part of graph/e2e tests
- Spec: PLAN.md Section 5.5

#### Step 10: Human-Review Stage ❌
- File: `src/skillpipeline/human_review.py`
- Spec: PLAN.md Section 5.4

#### Step 11: Cache ❌
- File: `src/skillpipeline/cache.py`
- Tests: `tests/test_cache.py`
- Spec: PLAN.md Section 10

#### Step 12-21: Graph, Report, Index, Pipeline, CLI, E2E, CI ❌

---

### Current Directory Structure

```
src/skillpipeline/
  __init__.py
  models.py          ✅
  llm.py             ✅
  ingest.py          ✅
  extract.py         ✅
  merge.py           ✅
  validate.py        ✅
  prompts/
    system.txt       ✅
    extract_topics.txt ✅
    extract_relationships.txt ❌
  templates/
    report.html.j2   ❌
    index.html.j2    ❌

tests/
  test_models.py     ✅
  test_ingest.py     ✅
  test_extract.py    ✅
  test_merge.py      ✅
  test_validate.py   ✅
  fixtures/          ✅
```

---

### Resumption Commands

```bash
cd /Users/dheeraj/Desktop/outputs
python3 -m pytest tests/ -v  # Run all tests
python3 -m pytest tests/test_validate.py -v  # Run specific test
```

---

### Next Immediate Action

Implement **Step 8: Retry Helper** (`retry.py`) OR **Step 9: Relate Stage**.

Note: `format_feedback()` is already implemented in `validate.py` and can be reused.
