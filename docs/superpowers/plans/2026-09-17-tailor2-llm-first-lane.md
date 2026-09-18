# Phased Implementation Plan: LLM-First Tailoring Lane (Tailor2)

**Date:** 2026-09-17  
**Status:** DRAFT / PENDING REVIEW  
**Feature Branch:** `feat/tailor2-lane`  
**Base Commit:** `e14f363022e62f770a716b38da45384b4d376b59`  
**Related Spec:** `docs/superpowers/specs/2026-09-17-tailor2-llm-first-lane-design.md`

---

## 1. File-Level Responsibilities

```
src/tailor2/
├── __init__.py                # Package marker
├── models.py                  # Dataclasses & enums for all 4 stages, schemas, serializations
├── prompts.py                 # Pure functions constructing draft, audit, repair, re-audit prompts
├── validators.py              # Objectively falsifiable deterministic validation rules
├── render.py                  # RenderDoc adapter, LaTeX compilation, and L7 validation integration
├── invoker.py                 # Tool-free model invoker, trace logger, provider enforcement
└── lane.py                    # End-to-end 4-stage pipeline orchestrator, budgeting, artifact publisher

scripts/
└── tailor2.py                 # CLI entry point (run, preflight, status)

tests/tailor2/
├── __init__.py
├── conftest.py                # Test fixtures (sample JDs, master profile mock, fake responses)
├── test_models.py             # Schema parsing, serialization, validation errors
├── test_validators.py         # Deterministic validation unit tests (quotes, numbers, Amdocs, do-not-claim)
├── test_prompts.py            # Prompt structure, evidence filtering, information isolation assertions
├── test_invoker.py            # Provider checks, explicit model requirements, trace logging
├── test_lane.py               # Workflow orchestration: happy path (2 calls), repair path (4 calls), fail-closed
├── test_fixtures.py           # Class 2: Byte-exact, immutable recorded model fixtures
└── test_cli.py                # Command line interface tests, error handling, help text
```

---

## 2. Phased Implementation Roadmap (Test-First)

### Phase 1: Data Contracts & Strict Models (`src/tailor2/models.py`)
- **Deliverables:**
  - `AtomicRequirement`, `DraftBullet`, `AmdocsOmission`, `DraftResponse`
  - `DimensionScore`, `BulletAuditEvaluation`, `AuditResponse`
  - `RepairedBullet`, `RepairResponse`
  - `ReAuditResponse`
  - `Tailor2Manifest`, `Tailor2RunResult`
  - Strict JSON parsers stripping markdown code fences (` ```json `).
- **Tests (`test_models.py`):**
  - Verify JSON round-tripping.
  - Verify rejection of missing keys, invalid types, unparseable strings.

### Phase 2: Deterministic Validators (`src/tailor2/validators.py`)
- **Deliverables:**
  - `validate_draft_response`:
    * Quote exact substring check (`quote in jd_text`).
    * Evidence ID resolution in `master_profile.yaml`.
    * Numeric token subset check with `~` approximations.
    * `do_not_claim` check (zero occurrences of `Kubernetes`).
    * Amdocs 7-bullet accounting: each of the 7 canonical Amdocs bullet IDs must appear either in `bullets` or in `amdocs_omission_ledger`.
    * Proportions and section bounds check.
    * Duplicate checks (no duplicate bullet texts, no duplicate IDs).
  - `validate_audit_response`:
    * All 9 dimensions evaluated per bullet.
    * Score 1 => Mandatory `REJECT`.
    * Factual/guarantee issues => Mandatory `REJECT`.
  - `validate_repair_response`:
    * Only rejected bullets addressed.
    * Repaired text passes numeric and `do_not_claim` checks.
  - `validate_re_audit_response`:
    * All 9 dimensions evaluated for repaired bullets.
- **Tests (`test_validators.py`):**
  - High-coverage matrix testing every valid and invalid case.

### Phase 3: Prompt Construction & Information Isolation (`src/tailor2/prompts.py`)
- **Deliverables:**
  - `build_draft_prompt`: Provides JD, full evidence catalog with tags & metrics, taste guidelines, and STAR/XYZ instructions.
  - `build_audit_prompt`: Provides ONLY JD, bullets, and cited evidence. Zero drafter CoT or strategy.
  - `build_repair_prompt`: Provides ONLY rejected bullets, cited evidence, and specific audit critiques.
  - `build_re_audit_prompt`: Provides ONLY repaired bullets, cited evidence, and JD.
- **Tests (`test_prompts.py`):**
  - Assert that auditor prompt contains no drafter rationale or CoT.
  - Assert that repair prompt contains only rejected bullets.
  - Assert that re-audit prompt contains only repaired bullets.

### Phase 4: Model Invocation & Safety Boundaries (`src/tailor2/invoker.py`)
- **Deliverables:**
  - `Tailor2Invoker`: Wraps safe command execution / HTTP requests.
  - Requires explicit `--provider` and `--model` for live execution; raises `ValueError` on missing or defaulted model.
  - Records I11 trace for every call via `src.llm_trace.write_trace`.
  - Zero tools, zero file permissions.
- **Tests (`test_invoker.py`):**
  - Verify error when model is omitted.
  - Verify trace file creation and payload contents.

### Phase 5: Rendering & L7 Integration (`src/tailor2/render.py`)
- **Deliverables:**
  - Maps accepted `DraftResponse` to `RenderDoc` (hydrates identity, education, skills).
  - Invokes `src.render.latex.render_latex` and `compile_latex`.
  - Executes `src.render.tailored.run_l7_tailored`.
  - Verifies single-page PDF output.
- **Tests (`test_render.py`):**
  - Renders valid draft to LaTeX and compiles to PDF in tmp directory.
  - Confirms L7 passes and page count is 1.

### Phase 6: Orchestration Pipeline & Budget Enforcement (`src/tailor2/lane.py`)
- **Deliverables:**
  - `run_tailor2_lane`: Coordinates the 4 stages.
  - Call budget enforcement:
    * 2 calls if Audit passes.
    * 4 calls if Audit rejects ≥1 bullet and Repair/Re-audit succeeds.
    * Maximum 4 calls total. Zero retry loops.
    * Fails closed if Re-audit rejects any repaired bullet.
  - Atomic publication to `applications_manual/{company}-{slug}-tailor2/`:
    * `job_description.txt`, `draft.json`, `audit.json`, `repair.json` (if any), `re_audit.json` (if any), `resume.tex`, `resume.pdf`, `run_manifest.json`.
- **Tests (`test_lane.py`):**
  - End-to-end orchestration with mock invokers covering all paths (Happy path, Repair path, Re-audit failure, Validation failure).

### Phase 7: CLI Entry Point (`scripts/tailor2.py`)
- **Deliverables:**
  - `scripts/tailor2.py run`: Runs the lane.
  - `scripts/tailor2.py preflight`: Validates environment credentials and pdflatex.
  - `scripts/tailor2.py status`: Inspects previous run artifacts.
- **Tests (`test_cli.py`):**
  - CLI argument parsing, missing argument errors, exit codes.

### Phase 8: Immutable Fixtures & Verification (`tests/tailor2/test_fixtures.py`)
- **Deliverables:**
  - Record and test byte-exact immutable fixtures under `tests/fixtures/tailor2/`.
  - Ensure zero live model calls during normal `pytest` execution.

---

## 3. Test Classes Strategy

1. **Class 1: Deterministic Unit Tests (Mocked)**
   - Tests execute with explicit, deterministic fake model responses.
   - Zero network, zero external dependencies.
   - Fast, run under standard `pytest -q`.
2. **Class 2: Immutable Recorded Fixtures**
   - Frozen, byte-exact recorded responses for real job postings.
   - Assert exact end-to-end pipeline determinism and artifact creation.
3. **Class 3: Optional Live Integration Tests**
   - Gated behind `@pytest.mark.live` (deselected by default).
   - Only executed when explicitly requested and approved by the user.

---

## 4. Forbidden Patterns Verification Checklist

- [ ] Zero `PYTEST_CURRENT_TEST` branches.
- [ ] Zero test-only production bypasses.
- [ ] Zero per-bullet-ID hardcoded exceptions.
- [ ] Zero mutating recorded responses with `.replace()`.
- [ ] Zero reality-based failures marked `xfail`.
- [ ] Zero weakening of validation to pass tests.
- [ ] Zero JD-specific phrase allowlists.
- [ ] Zero importing test modules from production code.
- [ ] Ingestion and scoring pipelines completely untouched.
- [ ] Legacy tailoring lane (`src/tailor/`, `scripts/tailor_now.py`) completely untouched.
