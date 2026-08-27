# M6.14 Plan — Collision-Safe Posting Identity & Targeted Priority Resolution

**Status:** OFFLINE COMPLETE — LIVE TARGETED SMOKE PENDING (2026-08-27)
**Spec:** `docs/superpowers/specs/2026-08-27-m6-14-posting-identity-priority-resolution-design.md`

---

## Plan Structure

### Task 1: Pure URL and posting-identity contracts
- Files: `src/models.py`, `tests/test_models.py`
- Implemented: `ManualUrlError`, `canonical_job_url`, `manual_url_dedup_key`, `stable_posting_identity`, `collision_dedup_key`, and `DiscoveredJob.identity_key`.
- Commit: `feat(m6.14): add deterministic posting identity contracts`

### Task 2: Collision-safe persistence
- Files: `src/db.py`, `tests/test_db.py`
- Implemented: `get_by_dedup_key`, collision escape key resolution in `insert_discovered()`, explicit `identity_key` validation.
- Commit: `fix(m6.14): prevent cross-requisition dedup collisions`

### Task 3: Safe manual inbox identity
- Files: `src/discover/inbox_manual.py`, `tests/test_inbox_manual.py`
- Implemented: `InboxInputError`, URL validation and canonicalization, setting `identity_key=manual_url_dedup_key(url)`, returning `InboxResult.url_job_ids`.
- Commit: `fix(m6.14): give manual URLs collision-safe identities`

### Task 4: Target selection and scoped gates
- Files: `src/db.py`, `src/prefilter.py`, `src/run_ingest.py`, `tests/test_db.py`, `tests/test_prefilter.py`, `tests/test_run_ingest_resolve.py`
- Implemented: `require_rows_by_ids_status`, `rows_by_ids_status`, `eligibility_rows(..., job_ids=...)`, `run_pre_resolution_gate(..., job_ids=...)`, `run_post_resolution_gate(..., job_ids=...)`, `run_resolution(..., job_ids=...)`.
- Commit: `feat(m6.14): add exact targeted resolution selection`

### Task 5: CLI fail-closed integration
- Files: `src/run_ingest.py`, `tests/test_run_ingest_lifecycle.py`
- Implemented: `--resolve-job-id` flag, mutual exclusivity validation, pre-run status validation, scoped gate and resolution orchestration.
- Commit: `feat(m6.14): expose fail-closed priority resolution CLI`

### Task 6: M6.14R Review and Repair Hardening
- Files: `src/models.py`, `src/discover/inbox_manual.py`, `src/run_ingest.py`, `tests/test_models.py`, `tests/test_inbox_manual.py`, `tests/test_run_ingest_lifecycle.py`
- Implemented:
  1. Sanitized port/authority exception handling without secret leakage (`from None`).
  2. Strict host validation and bracketed IPv6 canonicalization (`[::1]`).
  3. Conservative stable posting identity extraction (strict UUIDs for Ashby/Lever, route rejection for Workday, conflicting gh_jid rejection).
  4. Operator CLI exclusions: `--resolve-job-id` rejects `--dry-run`, `--limit`, and `--snapshot-dir`.
  5. Operator visibility: non-dry inbox runs print bounded numeric `Inbox job IDs: <id1>, <id2>`.
- Commits:
  - `fix(m6.14): harden URL identity validation`
  - `fix(m6.14): complete targeted resolution operator contract`

### Task 7: Documentation and closeout
- Files: `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`.
- Commit: `docs(m6.14): correct offline closeout after review`
