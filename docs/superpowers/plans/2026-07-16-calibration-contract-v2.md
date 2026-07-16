# Calibration Contract v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned, blind two-stage calibration workflow that records metadata-only `interest_call` separately from full-JD `fit_call`, then compares 7+ model decisions only against JD-informed fit labels.

**Architecture:** A new pure `src/calibration.py` module owns typed artifacts, rendering, parsing, provenance validation, and comparison logic. `scripts/calibration_packet.py` is a thin start/reveal CLI; `scripts/calibration_report.py` becomes the thin report CLI while retaining explicit legacy parsing. Complete JDs and optional DB-backed scores are fetched read-only through helpers in `src/db.py`; no schema or scoring behavior changes.

**Tech Stack:** Python 3.11+, stdlib (`argparse`, `dataclasses`, `datetime`, `enum`, `hashlib`, `html`, `json`, `os`, `pathlib`, `tempfile`) plus already-approved PyYAML and pytest.

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, and `docs/superpowers/specs/2026-07-16-calibration-contract-v2-design.md` before editing.
- One milestone only: Calibration Contract v2. Do not start M8, M9D-1, tailoring, discovery, or a real calibration round.
- Do not change `docs/scoring_prompt.md`, `config/profile_summary.md`, `scripts/score_batch.py`, scoring aggregation, score import behavior, or `config/filters.yaml`.
- The configured shortlist threshold remains 7. This milestone reads it; it does not edit or lock a new value.
- Do not mutate `data/jobs.db`, add a DB column/table, change job status/scores, or run a live scorer. Automated tests use temporary databases.
- No new dependency and no network/browser/model call in tests or production packet/report commands.
- Raw SQL remains in `src/db.py` only.
- Preserve `data/calibration/2026-07-12.user.md` byte-for-byte.
- Preserve the user's existing modified `tests/test_scoring_stress.py` and untracked PDFs/reports. Never use `git add .` or `git add -A`.
- TDD for every behavior. Each task ends with focused tests and an exact-path commit.

---

## File structure

```text
src/
  calibration.py                         NEW: types, artifact parser/renderer, validation, comparison
  db.py                                  MODIFY: read-only canonical-job and score query helpers

scripts/
  calibration_packet.py                 NEW: start/reveal CLI only
  calibration_report.py                 REWRITE: v2 report + explicit legacy compatibility

tests/
  test_calibration_contract.py          NEW: pure artifact/model/provenance tests
  test_calibration_packet.py            NEW: CLI, atomic output, read-only reveal tests
  test_calibration_report.py            REWRITE/EXTEND: v2 truth table/report + legacy tests
  test_db.py                             MODIFY: calibration read helper tests

docs/
  PHASE2_KICKOFF.md                      MODIFY: replace obsolete one-call protocol
  ROADMAP.md                             MODIFY: contract milestone status, corrected gate
  DECISIONS.md                           MODIFY: record contract and verification
  ARCHITECTURE.md                        MODIFY only if its scoring I/O section describes calibration
```

---

### Task 1: Typed round model, deterministic selection, hashing, and atomic writes

**Files:**
- Create: `src/calibration.py`
- Create: `tests/test_calibration_contract.py`

**Interfaces:**

```python
VALID_CALLS = frozenset({"APPLY", "MAYBE", "SKIP"})
CONTRACT_VERSION = 2
DEFAULT_ROUND_LIMIT = 12

class CalibrationContractError(ValueError): ...

class CalibrationStage(str, Enum):
    INTEREST = "interest"
    FIT = "fit"
    LEGACY_INTEREST = "legacy_interest"

@dataclass(frozen=True)
class BatchJob:
    job_id: int
    row_ids: tuple[int, ...]
    company: str
    title: str
    locations: tuple[str, ...]
    flags: tuple[str, ...]
    jd_quality: str
    jd_text: str

def load_batch(path: str | Path) -> tuple[BatchJob, ...]: ...
def select_round_jobs(jobs: tuple[BatchJob, ...], limit: int = DEFAULT_ROUND_LIMIT) -> tuple[BatchJob, ...]: ...
def batch_jobs_to_json(jobs: tuple[BatchJob, ...]) -> str: ...
def sha256_bytes(value: bytes) -> str: ...
def sha256_file(path: str | Path) -> str: ...
def atomic_write_text(path: str | Path, text: str) -> None: ...
```

`load_batch` validates the exact current batch fields and types: positive integer `id`,
non-empty unique positive `row_ids` containing `id`, string company/title/JD, string lists
for locations/flags, and `jd_quality` in `ats|aggregator`. Canonical IDs and all row IDs must
be globally unique across objects. Preserve source order; serialize JSON with indent 2 and a
final newline so hashes are stable.

- [ ] Write failing tests constructing 14 valid objects and assert default selection returns
      IDs 1–12 in order, `limit=2` returns 1–2, and limits 0/negative/non-integer or greater
      than available jobs raise `CalibrationContractError` with the supplied/available count.
- [ ] Write parameterized failing tests for a non-list root, missing/extra fields, wrong
      types, empty/duplicate row IDs, canonical ID absent from `row_ids`, duplicate canonical
      IDs, and cross-group row-ID overlap.
- [ ] Write a failing stable-serialization/hash test and an atomic-write test proving an
      existing destination raises `FileExistsError` and remains byte-identical.
- [ ] Run `pytest -q tests/test_calibration_contract.py`; expected failure is import/module
      absence.
- [ ] Implement the types and functions. `atomic_write_text` must create a temporary file in
      `path.parent`, flush/close it, call `os.replace` only when the destination is absent,
      and unlink the temporary file in `finally`. Refuse pre-existing destinations before
      creating the temporary file.
- [ ] Run `pytest -q tests/test_calibration_contract.py`; expected PASS.
- [ ] Commit:

```bash
git add src/calibration.py tests/test_calibration_contract.py
git commit -m "feat(calibration): add versioned round primitives"
```

---

### Task 2: Interest worksheet rendering, parsing, and provenance validation

**Files:**
- Modify: `src/calibration.py`
- Modify: `tests/test_calibration_contract.py`

**Additional interfaces:**

```python
@dataclass(frozen=True)
class RoundMetadata:
    contract_version: int
    stage: CalibrationStage
    round_name: str
    batch_path: Path
    batch_sha256: str
    canonical_job_count: int
    created_at: str
    interest_path: Path | None = None
    interest_sha256: str | None = None

@dataclass(frozen=True)
class CalibrationLabel:
    job: BatchJob
    interest_call: str | None
    fit_call: str | None
    notes: str

@dataclass(frozen=True)
class LegacyMetadata:
    contract_version: int
    stage: CalibrationStage
    source_path: Path

@dataclass(frozen=True)
class CalibrationWorksheet:
    metadata: RoundMetadata | LegacyMetadata
    labels: tuple[CalibrationLabel, ...]

def normalize_call(value: str, *, field: str, job_id: int, required: bool) -> str | None: ...
def render_interest_worksheet(metadata: RoundMetadata, jobs: tuple[BatchJob, ...]) -> str: ...
def parse_interest_worksheet(path: str | Path, *, require_complete: bool) -> CalibrationWorksheet: ...
```

Use `yaml.safe_load` only for front matter. Reject non-mapping YAML, unsupported version,
wrong stage, missing/extra required metadata, malformed 64-character lowercase hashes,
non-UTC timestamps, and count mismatches. Resolve relative `batch_path` from repository root
(`Path(__file__).resolve().parents[1]`), not current working directory.

Table encoding is exact:

```python
def encode_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("|", "&#124;").replace("\n", "<br>")

def decode_cell(value: str) -> str:
    return html.unescape(value.replace("<br>", "\n"))
```

Render columns exactly:
`id,row_ids,company,title,locations,flags,jd_quality,interest_call,notes`.
Join row IDs with commas, locations with `; `, and flags with `; `. Only call/notes may differ
from generated batch metadata during parsing.

- [ ] Write a failing golden-fragment test proving the worksheet includes complete YAML
      metadata and the exact header/order, but contains neither any `jd_text` substring nor
      `fit_score`/`fit_call`.
- [ ] Write failing round-trip tests with company/title/notes containing `|`, `&`, and
      newlines; calls `apply`, ` MAYBE `, and `skip` normalize uppercase.
- [ ] Write failing tests for blank calls with `require_complete=False` (accepted as `None`)
      and `require_complete=True` (clear job-specific error).
- [ ] Write failing tamper tests for batch hash, metadata column, row IDs, ordering,
      duplicate/missing/extra rows, invalid call, version/stage/count, and malformed front
      matter.
- [ ] Run the focused failing tests, implement renderer/parser/validator, then run:

```bash
pytest -q tests/test_calibration_contract.py
```

- [ ] Commit:

```bash
git add src/calibration.py tests/test_calibration_contract.py
git commit -m "feat(calibration): define metadata interest worksheet"
```

---

### Task 3: Start-round CLI and atomic two-file creation

**Files:**
- Create: `scripts/calibration_packet.py`
- Create: `tests/test_calibration_packet.py`

**Interfaces:**

```python
def start_round(
    source_batch: str | Path,
    *,
    out_dir: str | Path = "data/calibration",
    round_name: str | None = None,
    limit: int = DEFAULT_ROUND_LIMIT,
    now: datetime | None = None,
) -> tuple[Path, Path]: ...

def build_parser() -> argparse.ArgumentParser: ...
def main(argv: list[str] | None = None) -> int: ...
```

CLI:

```text
python -m scripts.calibration_packet start SOURCE_BATCH
  [--out-dir DIR] [--round NAME] [--limit N]
```

Default round name is current UTC date. Output names are `<round>.batch.json` and
`<round>.interest.md`. The interest metadata points to the just-written round batch and
hashes its final bytes. Two-output atomicity means preflight both destinations before any
write. If the second write unexpectedly fails, remove the newly created batch from this
invocation; never remove a pre-existing file.

- [ ] Write failing tests for default 12, explicit limit, explicit round, UTC-derived round,
      exact output names, interest batch hash, and printed paths/count.
- [ ] Write failing CLI tests for invalid/missing batch and insufficient jobs returning 2
      with a concise `Calibration packet rejected: ...` message and no traceback.
- [ ] Write failing no-overwrite tests where either destination already exists; assert both
      pre-existing bytes and directory contents are unchanged.
- [ ] Inject/monkeypatch the second atomic write to fail and prove the newly written first
      artifact is rolled back.
- [ ] Implement the thin CLI using `src.calibration` only; `print` is allowed in scripts.
- [ ] Run:

```bash
pytest -q tests/test_calibration_packet.py tests/test_calibration_contract.py
```

- [ ] Commit:

```bash
git add scripts/calibration_packet.py tests/test_calibration_packet.py
git commit -m "feat(calibration): generate blind interest rounds"
```

---

### Task 4: Read-only complete-JD retrieval and fit worksheet reveal

**Files:**
- Modify: `src/db.py`
- Modify: `src/calibration.py`
- Modify: `scripts/calibration_packet.py`
- Modify: `tests/test_db.py`
- Modify: `tests/test_calibration_contract.py`
- Modify: `tests/test_calibration_packet.py`

**Interfaces:**

```python
# src/db.py
def calibration_jobs_by_ids(
    conn: sqlite3.Connection, job_ids: tuple[int, ...]
) -> list[sqlite3.Row]: ...

# src/calibration.py
@dataclass(frozen=True)
class FullJD:
    job_id: int
    company: str
    title: str
    jd_text: str

def render_fit_worksheet(
    metadata: RoundMetadata,
    interest: CalibrationWorksheet,
    full_jds: tuple[FullJD, ...],
) -> str: ...
def parse_fit_worksheet(path: str | Path, *, require_complete: bool) -> CalibrationWorksheet: ...

# scripts/calibration_packet.py
def reveal_fit(
    interest_path: str | Path,
    *,
    db_path: str | Path = "data/jobs.db",
    out_path: str | Path | None = None,
    now: datetime | None = None,
) -> Path: ...
```

`calibration_jobs_by_ids` returns `id,company,title,jd_text` in requested ID order. Handle an
empty tuple without invalid SQL. `reveal_fit` must call `db.get_readonly_connection`, require
a complete interest worksheet, compare company/title, reject missing/empty JDs, compute the
completed interest file hash, and default output to the same basename with `.fit.md`.

Fit columns are exact:
`id,row_ids,company,title,locations,flags,jd_quality,interest_call,fit_call,notes`.
Render all `fit_call` values blank. Append one JD section per canonical ID using the exact
markers in the design. Escape an internal source substring `<!-- CALIBRATION_JD_` as
`&lt;!-- CALIBRATION_JD_` before rendering; decode only that sequence when validating and
hash the original complete JD bytes.

- [ ] Write failing DB tests for requested order, missing IDs (caller can detect), empty
      input, and no writes/commits.
- [ ] Write failing fit-render tests with a 10,000-character JD, marker-like JD content, and
      Unicode; assert rendered/reparsed text hash equals the complete original and is not
      truncated to 6,000.
- [ ] Write failing tests proving copied interest calls are uppercase and locked; blank fit
      calls parse only when `require_complete=False`; lowercase completed fit calls normalize.
- [ ] Write tamper tests for interest hash/path, changed copied interest call, missing/extra/
      swapped JD section, marker-ID mismatch, JD hash mismatch, metadata drift, and incomplete
      fit call.
- [ ] Write reveal integration tests using a file-backed temporary DB. Hash DB bytes before
      and after; assert equality. A missing DB must fail without creating it.
- [ ] Add `reveal INTEREST [--db PATH] [--out PATH]` to CLI and test concise nonzero errors,
      output refusal, and no partial artifact.
- [ ] Implement and run:

```bash
pytest -q tests/test_db.py tests/test_calibration_contract.py tests/test_calibration_packet.py
```

- [ ] Commit:

```bash
git add src/db.py src/calibration.py scripts/calibration_packet.py tests/test_db.py tests/test_calibration_contract.py tests/test_calibration_packet.py
git commit -m "feat(calibration): reveal locked full-JD fit worksheets"
```

---

### Task 5: Legacy worksheet preservation and explicit contract parsing

**Files:**
- Modify: `src/calibration.py`
- Modify: `tests/test_calibration_contract.py`
- Do not modify: `data/calibration/2026-07-12.user.md`

**Interfaces:**

```python
def parse_legacy_interest_worksheet(text: str) -> CalibrationWorksheet: ...
def parse_calibration_worksheet(
    path: str | Path, *, require_complete: bool = True
) -> CalibrationWorksheet: ...
```

Legacy parsing recognizes the existing header containing `your call`, uses its ID/company/
title/call/notes fields, creates stage `LEGACY_INTEREST`, and leaves `fit_call=None`. It does
not invent row groups, JDs, batch hashes, or v2 provenance. `parse_calibration_worksheet`
dispatches by YAML `contract_version/stage`; no front matter dispatches to legacy.

- [ ] Record the SHA-256 of `data/calibration/2026-07-12.user.md` in the test and assert it
      remains exact. Calculate the expected constant once from the current file; do not
      regenerate it inside the assertion.
- [ ] Port current case-insensitive/rated-row legacy tests to the pure parser. Preserve blank
      legacy rows as incomplete rather than silently calling them SKIP.
- [ ] Assert legacy stage and `fit_call is None` for all 30 existing rated rows.
- [ ] Assert a legacy worksheet passed where fit ground truth is required raises:
      `legacy interest-only worksheet cannot be used as fit ground truth; start a v2 round`.
- [ ] Implement dispatcher and run `pytest -q tests/test_calibration_contract.py`.
- [ ] Run `git diff -- data/calibration/2026-07-12.user.md`; expected no output.
- [ ] Commit:

```bash
git add src/calibration.py tests/test_calibration_contract.py
git commit -m "feat(calibration): preserve legacy interest evidence"
```

---

### Task 6: Correct scored-file comparison and reporting semantics

**Files:**
- Modify: `src/db.py`
- Modify: `src/calibration.py`
- Rewrite: `scripts/calibration_report.py`
- Rewrite/extend: `tests/test_calibration_report.py`
- Modify: `tests/test_db.py`

**Interfaces:**

```python
class ComparisonKind(str, Enum):
    AGREEMENT = "agreement"
    FALSE_NEGATIVE = "false_negative"
    FALSE_POSITIVE = "false_positive"
    UNSCORED = "unscored"

@dataclass(frozen=True)
class ScoredCall:
    job_id: int
    row_ids: tuple[int, ...]
    fit_score: float

@dataclass(frozen=True)
class CalibrationComparison:
    label: CalibrationLabel
    score: float | None
    kind: ComparisonKind

@dataclass(frozen=True)
class CalibrationReport:
    comparisons: tuple[CalibrationComparison, ...]
    transition_counts: tuple[tuple[str, str, int], ...]
    complete: bool

def load_scored_file(path: str | Path, jobs: tuple[BatchJob, ...]) -> tuple[ScoredCall, ...]: ...
def compare_fit_calls(
    worksheet: CalibrationWorksheet,
    scores: tuple[ScoredCall, ...],
    *,
    threshold: float,
) -> CalibrationReport: ...

# src/db.py
def calibration_scores_by_ids(
    conn: sqlite3.Connection, job_ids: tuple[int, ...]
) -> list[sqlite3.Row]: ...
```

Scored-file validation requires a JSON list covering each canonical ID and exact `row_ids`
once; scores are numeric, not bool, and 0–10. Ignore other valid scorer fields. Reject extra,
missing, duplicate, mismatched, and overlapping coverage.

Truth table is exact: APPLY/MAYBE with score >= threshold agreement; APPLY/MAYBE below false
negative; SKIP below agreement; SKIP >= threshold false positive. Build all nine transition
matrix cells in APPLY, MAYBE, SKIP order, including zeros. `complete=False` if any score is
missing in DB mode; scored-file mode rejects missing coverage before comparison.

CLI:

```text
python -m scripts.calibration_report FIT_WORKSHEET
  [--scored-file SCORED_JSON | --db PATH]
  [--threshold N]
```

Default comparison source remains `--db data/jobs.db` only for compatibility. Opening DB is
read-only. Preferred docs/examples use `--scored-file`. CLI catches contract/file/JSON/DB
errors, prints `Calibration report rejected: ...`, and returns 2. Disagreements return 0.

- [ ] Rewrite tests with a valid v2 fit fixture containing APPLY, MAYBE, and SKIP. Assert
      MAYBE score 6.5 is a false negative and MAYBE score 7 is agreement—replacing the old
      incorrect `MAYBE never counts as disagreement` rule.
- [ ] Test both boundary directions at exactly 7, plus `--threshold 7.5` analysis override.
- [ ] Assert false negatives/positives, agreement rate, fit counts, all nine transition
      cells, changed-after-JD rows, and notes appear in deterministic output.
- [ ] Test missing DB score: listed as unscored, `complete=False`, no false classification.
- [ ] Test every scored coverage/type/range mismatch.
- [ ] Test legacy worksheet refusal and prove no query can reinterpret its calls as fit.
- [ ] Test DB-backed mode uses read-only connection and leaves DB bytes unchanged.
- [ ] Implement pure comparison, DB helper, and thin CLI. Remove old one-call semantics from
      production docstrings and output.
- [ ] Run:

```bash
pytest -q tests/test_calibration_report.py tests/test_calibration_contract.py tests/test_db.py
```

- [ ] Commit:

```bash
git add src/db.py src/calibration.py scripts/calibration_report.py tests/test_db.py tests/test_calibration_report.py
git commit -m "feat(calibration): compare shortlist scores to fit calls"
```

---

### Task 7: Integration, authoritative documentation, and milestone verification

**Files:**
- Modify: `docs/PHASE2_KICKOFF.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/ARCHITECTURE.md` only if its calibration/scoring section contains the old
  one-call contract
- Tests: all calibration tests and full suite

- [ ] Add an end-to-end temporary-directory test to `tests/test_calibration_packet.py`:
      14-object source batch -> start limit 12 -> programmatically fill interest calls ->
      reveal from temporary DB with complete long JDs -> fill fit calls -> synthetic scored
      file -> report. Assert source/round counts, blindness at each stage, MAYBE-positive
      semantics, transition matrix, and zero DB-byte change.
- [ ] Run focused tests:

```bash
pytest -q tests/test_calibration_contract.py tests/test_calibration_packet.py tests/test_calibration_report.py tests/test_db.py tests/test_export_batch.py tests/test_score_batch.py tests/test_import_scores.py
```

- [ ] Run the full suite:

```bash
pytest -q
```

- [ ] Run `git diff --check` and verify `git status --short` still shows the user's known
      files untouched.
- [ ] Update `docs/PHASE2_KICKOFF.md` Phase 2 protocol to the staged v2 workflow, exact call
      definitions, truth table, commands, default 12, and corrected evidence gate: at least
      20 fit-labeled jobs, two rounds, at least 10 per round, two consecutive zero-
      disagreement complete rounds.
- [ ] Update `docs/ROADMAP.md`: mark Calibration Contract v2 implementation complete but
      Phase 2 calibration still in progress awaiting fresh human rounds. Do not unlock M8.
- [ ] Add a dated `docs/DECISIONS.md` entry with the old-contract defect, approved semantics,
      legacy preservation, artifact/provenance design, no-scoring/no-threshold/no-DB scope,
      test evidence, and the next human action.
- [ ] Inspect `docs/ARCHITECTURE.md`; update only stale calibration-contract wording. Do not
      rewrite discovery/eligibility/tailoring sections.
- [ ] Re-run `pytest -q` after documentation-only edits only if executable examples or tests
      reference docs; always run `git diff --check`.
- [ ] Stage exact modified paths and commit:

```bash
git add docs/PHASE2_KICKOFF.md docs/ROADMAP.md docs/DECISIONS.md tests/test_calibration_packet.py
git commit -m "docs(calibration): activate contract v2"
```

If `docs/ARCHITECTURE.md` changed, add that exact path. If the end-to-end test was already
committed in an earlier task, omit it here.

- [ ] Use `superpowers:verification-before-completion`. Report all commits, focused/full test
      results, exact git status, and confirmation that no real round/scoring/import/threshold/
      DB/M8/M9D work occurred. Stop; do not generate `data/calibration/<date>.interest.md`.

## Acceptance checklist

- [ ] `interest_call` is metadata-only; `fit_call` is full-JD and score-blind.
- [ ] APPLY means would submit; MAYBE means worth human review; both are positive at 7+.
- [ ] Default rounds contain 12 canonical groups and limit is configurable.
- [ ] Interest, fit, batch, JD, and score provenance/grouping are validated strictly.
- [ ] Complete untruncated representative JDs come from a read-only database connection.
- [ ] Historical `2026-07-12.user.md` is byte-identical and explicitly interest-only.
- [ ] Report compares only fit calls, reports interest-to-fit changes separately, and treats
      valid disagreements as diagnostic success.
- [ ] Threshold stays 7; scoring behavior/config/prompt/profile and DB schema/state do not
      change.
- [ ] Tests are offline, SQL is confined to `src/db.py`, full suite is green.
- [ ] Docs keep Phase 2 in progress and M8 locked.
