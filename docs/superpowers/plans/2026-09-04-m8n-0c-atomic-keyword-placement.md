# M8N-0c — Atomic Keyword Placement Contract Repair

## Phase 1: Preparation & Approval
- [ ] Create `src/tailor/requirement_terms.py` for atomic term parsing.
- [ ] Propose prompt changes to the user for explicit approval (S1, S2, S3, TAILORING_METHODOLOGY).

## Phase 2: S1 and S2 Repair
- [ ] Update S1 parser to expand compound requirements into atomic `Requirement` objects. Add S1 tests.
- [ ] Update S2 parser and validators to work on atomic terms, enforcing real keyword hits and "gap" for baseline-only terms. Add S2 tests.

## Phase 3: S3 and G1 Alignment
- [ ] Create a shared helper module/functions for phrase normalization, dual-placement checks, and length allowance.
- [ ] Update G1 to enforce atomic covered terms and the shared length allowance.
- [ ] Add `placement_requirements` to the S3 request object and prompt input.
- [ ] Add `validate_covered_term_placement` to S3 validation.
- [ ] Add tests for S3 and G1 rules.

## Phase 4: Pipeline Halt
- [ ] Update the pipeline orchestrator to raise `NO_TAILORABLE_COVERAGE` after S2 if no actionable covered terms exist.
- [ ] Add pipeline tests.

## Phase 5: Verification & Benchmark
- [ ] Apply approved prompt changes.
- [ ] Run full test suite (`pytest -q`), preflight, and ensure no network/model calls.
- [ ] Record the TikTok and Atoms JDs in `inbox/jd/`.
- [ ] Run the live benchmark with the user on Cisco 119, TikTok A245086, and Atoms 4460204070.
- [ ] Review packets, capture replay fixtures, and record results in `docs/DECISIONS.md`.
- [ ] Update `docs/ROADMAP.md` and `docs/IMPLEMENTATION_PLAN.md`.
