# M8P-7 / M8P-8 Pilot Operator and Scale-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compose the validated stage pipelines into one resumable, idempotent, cost-accounted operator; run the three-resume human pilot; and — only behind an explicit numeric acceptance gate — scale to thirty.

**Architecture:** The operator owns no parsing, validation, or hydration. It re-derives each stage's request from upstream artifacts, skips stages whose accepted artifact already matches, refuses on any fingerprint conflict, and never retries. Every artifact lives in one gitignored per-application directory; the run manifest is rebuilt from artifacts, never trusted as the source of truth.

**Tech Stack:** Python 3.11+, frozen dataclasses, stdlib `json`/`enum`/`pathlib`/`datetime`, existing stage pipelines, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-m8p-7-pilot-operator-design.md`

**Can implementation start before M8P-3R merges?** **No.** M8P-7 requires M8P-3R, M8P-4, M8P-5, and M8P-6 all merged. Tasks 1–6 are M8P-7; Tasks 7–9 are M8P-8 and additionally require the §6 gate to pass and decision D1 to be resolved.

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/TAILORING_METHODOLOGY.md` §3–§5, the spec above, and every merged stage module before editing.
- **No automatic application submission.** No `requests`, `urllib`, `smtplib`, `webbrowser`, Playwright, Crawl4AI, or Firecrawl import may appear in operator code. A test enforces this.
- **No SQLite write.** The only DB contact is `db.get_readonly_connection` plus `db.prepare_tailoring_request`.
- The operator composes existing stage functions. It defines no parser, validator, hydrator, lint, or renderer of its own.
- Never retry a stage automatically. Every stage pipeline is one-attempt by design.
- Never overwrite an accepted artifact or any feedback record.
- **Never edit** `src/tailor/s3.py`, `g1.py`, `s3_pipeline.py`, `g2.py`, `g2_pipeline.py`, `publish.py`, `g3.py`, `feedback.py`, `src/render/*`, `scripts/tailor_s{1,3}.py`, `scripts/tailor_s0_s2.py`, `scripts/tailor_g{2,3}.py`, or their tests.
- `config/taste.md` and `config/banned_words.txt` are written **only** in Task 6, only under explicit user instruction, and only after the pilot.
- No new dependency. Tests never call a model, the network, or `pdflatex`.
- Jobs 229 and 279 prohibited; eligibility re-checked live every run.
- All artifacts under gitignored `applications/`; tests use `tmp_path`.
- Baseline DB SHA-256: `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- TDD per task: focused RED, minimal GREEN, regression, commit.
- Do not edit `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md` except where Task 6 and Task 9 explicitly say so — those two are the integration milestones and are the only place central docs change.

## Predecessor contracts and blockers

```python
from src.db import get_readonly_connection, prepare_tailoring_request, tailoring_base_variant
from src.tailor.s1_pipeline  import run_s1_invocation
from src.tailor.s0_pipeline  import run_s0_invocation
from src.tailor.s2_pipeline  import run_s2_invocation
from src.tailor.s3_pipeline  import run_s3_invocation, parse_s3_bundle, s3_bundle_to_dict
#   parse_s3_bundle(raw, request, banned_terms) -- VERIFIED three-argument signature
#   (src/tailor/s3_pipeline.py:155). The operator already rebuilds each stage's request
#   from upstream artifacts, so it has the S3Request the parser needs.
from src.tailor.g2_pipeline  import run_g2_loop, parse_g2_bundle, g2_bundle_to_dict
from src.tailor.publish      import render_and_publish, parse_render_result, application_dir, slugify
from src.tailor.g3           import build_review_packet, publish_packet, parse_packet
from src.tailor.feedback     import load_feedback_index, summarize_feedback
from src.tailor.artifacts    import write_json_atomic
```

**Blocker B1:** all four predecessor milestones merged. M8P-3R is done (`560ad8d`,
post-merge baseline **1381 passed, 1 deselected**); M8P-4, M8P-5, and M8P-6 are not.
Verify with `git log --oneline -30 main` before Task 1.

**Blocker B2 (M8P-8 only):** decision D1 resolved and a read-only query proving ≥ 30
distinct eligible JDs. Do not start Task 7 without both.

**Blocker B3 (M8P-8 only):** `scripts/tailor_pilot.py gate` exits 0.

## Target files

Create: `src/tailor/pilot.py`, `scripts/tailor_pilot.py`, `tests/tailor/test_pilot.py`,
`tests/test_tailor_pilot_cli.py`, `tests/test_m8p7_integration.py`,
`tests/fixtures/tailor/m8p7_chain.py`.

Modify in Task 6 only: `config/taste.md`, `config/banned_words.txt`, `docs/ROADMAP.md`,
`docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`.
Modify in Task 9 only: the same central docs.

## Privacy boundaries

Every artifact contains the JD, the user's resume text, and (in the PDF) the user's
name, phone, and email. All of it stays under gitignored `applications/`. The operator
never prints more than 200 characters of model or JD content to stdout/stderr, and
never writes any artifact into a git-tracked path. A test asserts the default root is
`applications/` and that `applications/` is gitignored.

---

### Task 1: Stage table, run manifest, and skip/conflict logic

**Files:**
- Create: `src/tailor/pilot.py`
- Create: `tests/tailor/test_pilot.py`
- Create: `tests/fixtures/tailor/m8p7_chain.py`

**Interfaces:**
- Produces:

```python
MANIFEST_SCHEMA = "m8p7.run_manifest.v1"
APPLICATIONS_ROOT = Path("applications")

class Stage(str, Enum):
    PREPARE = "prepare"; S1 = "s1"; S0 = "s0"; S2 = "s2"
    S3 = "s3"; G2 = "g2"; RENDER = "render"; G3 = "g3"

STAGE_ORDER: tuple[Stage, ...]
STAGE_ARTIFACT: dict[Stage, str]          # Stage -> accepted artifact filename

class StageState(str, Enum):
    PENDING = "pending"; SKIPPED_COMPLETE = "skipped_complete"
    COMPLETE = "complete"; CONFLICT = "conflict"; FAILED = "failed"

@dataclass(frozen=True)
class StageRecord:
    stage: Stage
    state: StageState
    outcome_kind: str
    artifact_path: str | None
    model_calls: int
    trace_paths: tuple[str, ...]
    started_at: str            # UTC ISO-8601
    ended_at: str
    error: str | None          # bounded to 200 chars

@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str | None
    stages: tuple[StageRecord, ...]
    total_model_calls: int
    db_mutations: int          # always 0
    submissions: int           # always 0

def artifact_path(directory: Path, stage: Stage) -> Path: ...
def stage_is_complete(directory: Path, stage: Stage, *, job_id: int,
                      alignment_fingerprint: str | None) -> bool: ...
def rebuild_manifest(directory: Path, *, job_id: int, company: str, title: str) -> RunManifest: ...
def manifest_to_dict(manifest: RunManifest) -> dict[str, object]: ...
def parse_manifest(raw: object) -> RunManifest: ...
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/fixtures/tailor/m8p7_chain.py
"""Synthetic per-application artifact trees for M8P-7. No model, no network, no DB."""
import json
from pathlib import Path


def write_chain(directory: Path, *, job_id: int = 225, fingerprint: str = "fp1",
                through: str = "s3") -> Path:
    """Write valid-looking accepted artifacts up to and including `through`."""
    directory.mkdir(parents=True, exist_ok=True)
    stages = ["s1", "s0", "s2", "s3", "g2", "render", "g3"]
    files = {"s1": "s1_response.json", "s0": "s0_response.json", "s2": "s2_response.json",
             "s3": "s3_bundle.json", "g2": "g2_bundle.json",
             "render": "render_result.json", "g3": "packet.json"}
    for stage in stages[: stages.index(through) + 1]:
        payload = {"job_id": job_id}
        if stage in {"s2", "s3", "g2", "render", "g3"}:
            payload["alignment_fingerprint"] = fingerprint
        (directory / files[stage]).write_text(json.dumps(payload), encoding="utf-8")
    return directory
```

```python
# tests/tailor/test_pilot.py
import pytest
from src.tailor.pilot import (
    STAGE_ORDER, MANIFEST_SCHEMA, Stage, StageState, artifact_path,
    manifest_to_dict, parse_manifest, rebuild_manifest, stage_is_complete,
)
from tests.fixtures.tailor.m8p7_chain import write_chain


def test_stage_order_matches_the_documented_chain():
    assert [s.value for s in STAGE_ORDER] == [
        "prepare", "s1", "s0", "s2", "s3", "g2", "render", "g3"]


def test_complete_stage_with_matching_identity_is_detected(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")


def test_stage_with_mismatched_fingerprint_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp2")


def test_stage_with_mismatched_job_id_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=999, alignment_fingerprint="fp1")


def test_absent_artifact_is_not_complete(tmp_path):
    write_chain(tmp_path, through="s1")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")


def test_manifest_is_rebuilt_from_artifacts_not_from_a_stale_manifest(tmp_path):
    write_chain(tmp_path, through="s2")
    (tmp_path / "run_manifest.json").write_text('{"schema_version": "lies"}', encoding="utf-8")
    manifest = rebuild_manifest(tmp_path, job_id=225, company="Notion", title="SWE")
    assert manifest.schema_version == MANIFEST_SCHEMA
    by_stage = {r.stage: r.state for r in manifest.stages}
    assert by_stage[Stage.S2] is StageState.SKIPPED_COMPLETE
    assert by_stage[Stage.S3] is StageState.PENDING


def test_manifest_always_asserts_zero_mutations_and_submissions(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s1"), job_id=225,
                                company="Notion", title="SWE")
    assert manifest.db_mutations == 0 and manifest.submissions == 0


def test_manifest_round_trips_strictly(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s3"), job_id=225,
                                company="Notion", title="SWE")
    assert parse_manifest(manifest_to_dict(manifest)) == manifest


def test_artifact_path_is_deterministic(tmp_path):
    assert artifact_path(tmp_path, Stage.S3).name == "s3_bundle.json"
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_pilot.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tailor.pilot'`.

- [ ] **Step 3: Implement**

`stage_is_complete` reads the artifact with `json.loads`, compares `job_id`, and — for
`S2` onward — compares `alignment_fingerprint`. Any read or parse error means "not
complete", never a crash. `rebuild_manifest` walks `STAGE_ORDER` and never reads
`run_manifest.json`.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_pilot.py -q
.venv/bin/python -m pytest tests/tailor -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/pilot.py tests/tailor/test_pilot.py tests/fixtures/tailor/m8p7_chain.py
git commit -m "feat(m8): add pilot stage table and run manifest"
```

---

### Task 2: Chain driver with cost accounting and fail-closed diagnostics

**Files:**
- Modify: `src/tailor/pilot.py`
- Modify: `tests/tailor/test_pilot.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class RunOutcome:
    manifest: RunManifest
    failed_stage: Stage | None
    retry_command: str | None

def run_application(job_id: int, *, db_path: Path, profile_path: Path,
                    root: Path = APPLICATIONS_ROOT,
                    template_path: Path = Path("profile/template.tex"),
                    banned_words_path: Path = Path("config/banned_words.txt"),
                    taste_path: Path = Path("config/taste.md"),
                    trace_dir: Path = Path("data/traces"),
                    stop_after: Stage | None = None,
                    only: Stage | None = None,
                    dry_run: bool = False,
                    allow_rerun_after_feedback: bool = False) -> RunOutcome: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.pilot import Stage, StageState, run_application


def test_dry_run_makes_no_model_call_and_writes_no_artifact(tmp_repo, spy_invocations):
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root, dry_run=True)
    assert spy_invocations.call_count == 0
    assert outcome.manifest.total_model_calls == 0
    assert not list(tmp_repo.root.rglob("s1_response.json"))


def test_full_run_reports_five_to_seven_model_calls(tmp_repo, mock_all_stages_pass):
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root)
    assert 5 <= outcome.manifest.total_model_calls <= 7
    assert all(r.state in (StageState.COMPLETE, StageState.SKIPPED_COMPLETE)
               for r in outcome.manifest.stages)


def test_rerun_of_a_complete_application_costs_zero_calls(tmp_repo, mock_all_stages_pass, spy_invocations):
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    spy_invocations.reset()
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root)
    assert spy_invocations.call_count == 0
    assert outcome.manifest.total_model_calls == 0


def test_rerun_produces_byte_identical_artifacts(tmp_repo, mock_all_stages_pass):
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    before = {p: p.read_bytes() for p in tmp_repo.root.rglob("*.json")}
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert {p: p.read_bytes() for p in tmp_repo.root.rglob("*.json")} == before


def test_tampered_upstream_artifact_produces_conflict_and_changes_nothing(tmp_repo, mock_all_stages_pass):
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    bundle = next(tmp_repo.root.rglob("s3_bundle.json"))
    bundle.write_text(bundle.read_text().replace('"fp', '"tampered_fp'), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_repo.root.rglob("*.json") if p != bundle}
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root)
    assert outcome.failed_stage is Stage.S3
    assert {p: p.read_bytes() for p in tmp_repo.root.rglob("*.json") if p != bundle} == before


def test_mid_chain_failure_resumes_at_the_failed_stage(tmp_repo, mock_g2_fails_then_passes, spy_invocations):
    first = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert first.failed_stage is Stage.G2
    spy_invocations.reset()
    second = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert second.failed_stage is None
    assert spy_invocations.call_count <= 3      # only G2 (and its revision) re-ran


def test_failure_reports_a_retry_command_and_a_trace_path(tmp_repo, mock_s3_fails):
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert outcome.retry_command and "--only s3" in outcome.retry_command
    record = next(r for r in outcome.manifest.stages if r.stage is Stage.S3)
    assert record.trace_paths


def test_no_automatic_retry_on_failure(tmp_repo, mock_s3_fails, spy_invocations):
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert spy_invocations.calls_for("s3") == 1


def test_rerun_after_feedback_is_refused_by_default(tmp_repo, mock_all_stages_pass, recorded_feedback):
    outcome = run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root)
    assert outcome.failed_stage is Stage.PREPARE
    assert "feedback" in (outcome.manifest.stages[0].error or "")


def test_rerun_after_feedback_with_flag_writes_to_a_rerun_subdirectory(tmp_repo, mock_all_stages_pass,
                                                                      recorded_feedback):
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                    root=tmp_repo.root, allow_rerun_after_feedback=True)
    assert list(tmp_repo.root.rglob("rerun-1/s3_bundle.json"))


def test_prohibited_job_is_refused(tmp_repo, mock_all_stages_pass):
    outcome = run_application(279, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.root)
    assert outcome.failed_stage is Stage.PREPARE
    assert "prohibited" in (outcome.manifest.stages[0].error or "")


def test_operator_defines_no_parsing_or_validation_of_its_own():
    from pathlib import Path
    source = Path("src/tailor/pilot.py").read_text(encoding="utf-8")
    for forbidden in ("def parse_", "def validate_", "def hydrate_", "def build_prompt"):
        assert forbidden not in source


def test_operator_cannot_submit_an_application():
    from pathlib import Path
    source = Path("src/tailor/pilot.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "urllib", "smtplib", "webbrowser",
                      "playwright", "crawl4ai", "firecrawl"):
        assert forbidden not in source


def test_no_sqlite_write_occurs(tmp_repo, mock_all_stages_pass, db_checksum):
    before = db_checksum()
    run_application(225, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert db_checksum() == before
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_pilot.py -q -k run_application`

Expected: FAIL — `ImportError: cannot import name 'run_application'`.

- [ ] **Step 3: Implement**

Walk `STAGE_ORDER`. For each stage: re-derive the request from upstream artifacts,
check `stage_is_complete`, and either skip, run, or conflict. Accumulate
`StageRecord`s. Write `run_manifest.json` with `write_json_atomic` at the end of every
run, including failing ones. Truncate every error to 200 characters. Build
`retry_command` as
`f"python -m scripts.tailor_pilot run --job-id {job_id} --only {stage.value}"`.

`dry_run` performs every re-derivation and every completeness check but calls no stage
pipeline and writes nothing, so it proves the chain composes at zero cost.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_pilot.py -q
.venv/bin/python -m pytest tests/tailor tests/render -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/pilot.py tests/tailor/test_pilot.py
git commit -m "feat(m8): drive the full tailoring chain per application"
```

---

### Task 3: Read-only pilot-job selection

**Files:**
- Modify: `src/tailor/pilot.py`
- Modify: `tests/tailor/test_pilot.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class PilotCandidate:
    job_id: int
    company: str
    title: str
    base_variant: str
    jd_length: int
    content_group: str        # sha256 of normalized jd_text
    reasons: tuple[str, ...]

def eligible_candidates(conn) -> tuple[PilotCandidate, ...]: ...
def select_pilot_jobs(candidates: tuple[PilotCandidate, ...], count: int = 3) -> tuple[PilotCandidate, ...]: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.pilot import eligible_candidates, select_pilot_jobs


def test_eligible_candidates_excludes_prohibited_and_non_ats(seeded_conn):
    ids = {c.job_id for c in eligible_candidates(seeded_conn)}
    assert 279 not in ids and 229 not in ids
    assert all(c.jd_length > 0 for c in eligible_candidates(seeded_conn))


def test_selection_never_returns_two_rows_from_one_content_group(candidates_with_duplicates):
    picked = select_pilot_jobs(candidates_with_duplicates, count=3)
    assert len({c.content_group for c in picked}) == 3


def test_selection_covers_both_base_variants(candidates_mixed):
    picked = select_pilot_jobs(candidates_mixed, count=3)
    assert {c.base_variant for c in picked} >= {"backend", "ml"}


def test_selection_spreads_jd_length(candidates_mixed):
    lengths = sorted(c.jd_length for c in select_pilot_jobs(candidates_mixed, count=3))
    assert lengths[0] < 3000 and lengths[-1] > 12000


def test_every_pick_carries_a_reason(candidates_mixed):
    assert all(c.reasons for c in select_pilot_jobs(candidates_mixed, count=3))


def test_selection_is_deterministic(candidates_mixed):
    assert select_pilot_jobs(candidates_mixed, 3) == select_pilot_jobs(candidates_mixed, 3)


def test_selection_raises_when_criteria_cannot_be_met(candidates_all_backend):
    import pytest
    with pytest.raises(ValueError, match="base variant"):
        select_pilot_jobs(candidates_all_backend, count=3)


def test_selection_is_read_only(seeded_conn, db_checksum):
    before = db_checksum()
    eligible_candidates(seeded_conn)
    assert db_checksum() == before
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_pilot.py -q -k candidate or select`

Expected: FAIL — `ImportError: cannot import name 'eligible_candidates'`.

- [ ] **Step 3: Implement**

No new SQL is needed and none may be written outside `src/db.py`. `db.rows_by_status`
(`src/db.py:451`) issues `SELECT * FROM jobs WHERE status = ? ORDER BY id`, so it already
returns `id`, `company`, `title`, `base_variant`, `jd_quality`, and `jd_text`. Call it with
`Status.SHORTLISTED` over a read-only connection and apply every eligibility filter in
`pilot.py`. If a future criterion genuinely needs a column this helper does not return,
STOP and ask rather than adding SQL outside `db.py`.

`content_group` is `sha256(" ".join(jd_text.split()).casefold())`. Selection applies
criteria 2–6 from the design in order, raising `ValueError` naming the unmet criterion
rather than silently returning a weaker set.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_pilot.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/pilot.py tests/tailor/test_pilot.py
git commit -m "feat(m8): select diverse pilot jobs read-only"
```

---

### Task 4: Cost accounting and the acceptance gate

**Files:**
- Modify: `src/tailor/pilot.py`
- Modify: `tests/tailor/test_pilot.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class CostReport:
    applications: int
    total_model_calls: int
    calls_by_stage: tuple[tuple[str, int], ...]
    mean_calls_per_application: float
    g2_round_distribution: tuple[tuple[int, int], ...]

@dataclass(frozen=True)
class GateCondition:
    name: str
    threshold: str
    observed: str
    passed: bool

@dataclass(frozen=True)
class GateReport:
    conditions: tuple[GateCondition, ...]
    passed: bool

def cost_report(root: Path = APPLICATIONS_ROOT) -> CostReport: ...
def acceptance_gate(root: Path = APPLICATIONS_ROOT,
                    feedback_dir: Path = Path("data/feedback"),
                    expected_runs: int = 3) -> GateReport: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.pilot import acceptance_gate, cost_report


def test_cost_report_aggregates_manifests(three_completed_applications):
    report = cost_report(three_completed_applications)
    assert report.applications == 3
    assert report.total_model_calls == sum(n for _, n in report.calls_by_stage)
    assert 5.0 <= report.mean_calls_per_application <= 7.0


def test_gate_fails_on_any_unsupported_claim(pilot_root, feedback_with_one_unsupported_claim):
    report = acceptance_gate(pilot_root, feedback_with_one_unsupported_claim)
    condition = next(c for c in report.conditions if c.name == "unsupported_claims")
    assert not condition.passed and not report.passed


def test_gate_fails_when_fewer_than_two_would_submit(pilot_root, feedback_one_yes):
    assert not acceptance_gate(pilot_root, feedback_one_yes).passed


def test_gate_fails_on_any_l7_failure(pilot_root_with_l7_failure, good_feedback):
    assert not acceptance_gate(pilot_root_with_l7_failure, good_feedback).passed


def test_gate_fails_when_more_than_one_needs_revision(pilot_root, feedback_two_revisions):
    assert not acceptance_gate(pilot_root, feedback_two_revisions).passed


def test_gate_fails_when_a_run_did_not_reach_a_packet(pilot_root_incomplete, good_feedback):
    assert not acceptance_gate(pilot_root_incomplete, good_feedback).passed


def test_gate_passes_only_when_every_condition_passes(pilot_root, good_feedback):
    report = acceptance_gate(pilot_root, good_feedback)
    assert report.passed and all(c.passed for c in report.conditions)


def test_gate_reports_observed_values_for_every_condition(pilot_root, good_feedback):
    assert all(c.observed for c in acceptance_gate(pilot_root, good_feedback).conditions)


def test_gate_and_cost_are_read_only(pilot_root, good_feedback):
    before = sorted(str(p) for p in pilot_root.rglob("*"))
    acceptance_gate(pilot_root, good_feedback)
    cost_report(pilot_root)
    assert sorted(str(p) for p in pilot_root.rglob("*")) == before
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_pilot.py -q -k "cost or gate"`

Expected: FAIL — `ImportError: cannot import name 'acceptance_gate'`.

- [ ] **Step 3: Implement**

Implement the seven conditions from the design §6 exactly, each producing a
`GateCondition` with its threshold and observed value. `passed` is the conjunction.
Read manifests and `render_result.json` files for the run/L7 conditions and
`summarize_feedback` plus the stored records for the feedback conditions.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_pilot.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/pilot.py tests/tailor/test_pilot.py
git commit -m "feat(m8): add pilot cost accounting and acceptance gate"
```

---

### Task 5: Operator CLI

**Files:**
- Create: `scripts/tailor_pilot.py`
- Create: `tests/test_tailor_pilot_cli.py`
- Create: `tests/test_m8p7_integration.py`

**Interfaces:**
- Subcommands: `select`, `run`, `cost`, `gate`, `index`.

- [ ] **Step 1: Write the failing tests**

```python
import subprocess
import sys
from pathlib import Path


def _run(*args, cwd):
    return subprocess.run([sys.executable, "-m", "scripts.tailor_pilot", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_select_is_read_only_and_prints_reasons(tmp_repo, db_checksum):
    before = db_checksum()
    result = _run("select", "--count", "3", "--db", str(tmp_repo.db), cwd=tmp_repo.root)
    assert result.returncode == 0
    assert result.stdout.count("reason:") == 3
    assert db_checksum() == before


def test_run_dry_run_writes_nothing(tmp_repo):
    result = _run("run", "--job-id", "225", "--dry-run", "--db", str(tmp_repo.db),
                  "--root", str(tmp_repo.applications), cwd=tmp_repo.root)
    assert result.returncode == 0
    assert not tmp_repo.applications.exists()


def test_run_prohibited_job_exits_nonzero(tmp_repo):
    result = _run("run", "--job-id", "279", "--db", str(tmp_repo.db),
                  "--root", str(tmp_repo.applications), cwd=tmp_repo.root)
    assert result.returncode == 1
    assert "prohibited" in result.stderr


def test_gate_exits_nonzero_when_a_condition_fails(tmp_repo, failing_feedback):
    result = _run("gate", "--root", str(tmp_repo.applications),
                  "--feedback-dir", str(failing_feedback), cwd=tmp_repo.root)
    assert result.returncode == 1
    assert "unsupported_claims" in result.stdout


def test_index_regenerates_applications_index(tmp_repo, three_completed_applications):
    assert _run("index", "--root", str(tmp_repo.applications), cwd=tmp_repo.root).returncode == 0
    text = (tmp_repo.applications / "INDEX.md").read_text(encoding="utf-8")
    assert text.count("|") >= 3
    assert "INDEX.md" in Path(".gitignore").read_text(encoding="utf-8") or \
           "applications/" in Path(".gitignore").read_text(encoding="utf-8")


def test_cli_never_prints_more_than_200_chars_of_model_content(tmp_repo, mock_s3_fails_verbosely):
    result = _run("run", "--job-id", "225", "--db", str(tmp_repo.db),
                  "--root", str(tmp_repo.applications), cwd=tmp_repo.root)
    assert max(len(line) for line in result.stderr.splitlines()) <= 260
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_tailor_pilot_cli.py -q`

Expected: FAIL — `No module named scripts.tailor_pilot`.

- [ ] **Step 3: Implement**

Mirror `scripts/tailor_s3.py`'s structure. `index` regenerates
`applications/INDEX.md` from the manifests and render results — a deterministic table
of date, company, role, gate statuses, model calls, and PDF path. The
`applications/by-date/` symlink view from `TAILORING_METHODOLOGY.md` §3 is **not**
built here; `INDEX.md` is the fallback the methodology already sanctions.

- [ ] **Step 4: Run GREEN and full verification**

```bash
.venv/bin/python -m pytest -q
git diff --check
shasum -a 256 data/jobs.db
```

- [ ] **Step 5: Commit**

```bash
git add scripts/tailor_pilot.py tests/test_tailor_pilot_cli.py tests/test_m8p7_integration.py
git commit -m "feat(m8): add the one-job pilot operator CLI"
```

---

### Task 6: Live three-resume pilot (with the user)

**Files:**
- Modify (only under explicit user instruction): `config/taste.md`, `config/banned_words.txt`
- Modify: `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`

**This task is executed live, with the user present. It cannot be run by an unattended agent.**

- [ ] **Step 1: Back up and record the baseline**

```bash
cp data/jobs.db /tmp/jobs.db.pre-m8p7.bak
shasum -a 256 data/jobs.db
.venv/bin/python -m pytest -q
```

- [ ] **Step 2: Select and confirm the three jobs**

```bash
.venv/bin/python -m scripts.tailor_pilot select --count 3 --db data/jobs.db
```

Show the user the three picks with their reasons and get explicit confirmation. If
`select` raises because the criteria cannot be met, STOP and present the shortfall —
do not relax a criterion silently.

- [ ] **Step 3: Dry-run each job**

```bash
.venv/bin/python -m scripts.tailor_pilot run --job-id <ID> --dry-run --db data/jobs.db
```

Expected: zero model calls, planned call count printed, nothing written.

- [ ] **Step 4: Run job 1 live, then review**

```bash
.venv/bin/python -m scripts.tailor_pilot run --job-id <ID1> --db data/jobs.db
```

The user reads `applications/<slug>/review.md`, opens the PDF, fills
`feedback_form.yaml`, then:

```bash
.venv/bin/python -m scripts.tailor_g3 record --form applications/<slug>/feedback_form.yaml --packet applications/<slug>/packet.json
```

- [ ] **Step 5: Repeat for jobs 2 and 3**

One at a time. Do not start the next job before the previous one's feedback is
recorded — the point of the pilot is to learn between runs, not to batch three
identical mistakes.

- [ ] **Step 6: Summarize, cost, and gate**

```bash
.venv/bin/python -m scripts.tailor_g3 summarize
.venv/bin/python -m scripts.tailor_pilot cost --root applications
.venv/bin/python -m scripts.tailor_pilot gate --root applications
```

- [ ] **Step 7: Taste incorporation (user-directed only)**

Present `derive_taste_candidates` output. The user chooses which lessons become dated
lines in `config/taste.md` and which literal terms join `config/banned_words.txt`.
After any change to either file, re-run G1 and G2 on the three archived applications
and confirm no previously passing gate now fails. If one does, that is a drift finding
and must be resolved before M8P-8.

- [ ] **Step 8: Verify nothing was mutated and close the milestone**

```bash
shasum -a 256 data/jobs.db      # must equal the baseline
git status --short              # applications/ and data/ must not appear
.venv/bin/python -m pytest -q
```

Then update `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, and `docs/DECISIONS.md`
with: the three job ids and why they were chosen, the per-job outcomes, the exact
model-call counts, the gate report verbatim, every taste/banned-word change made, and
the user's explicit decision about whether to proceed to M8P-8.

- [ ] **Step 9: Commit**

```bash
git add docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md docs/DECISIONS.md config/taste.md config/banned_words.txt
git commit -m "docs(m8): close the three-resume human pilot"
```

---

### Task 7: M8P-8 corpus preparation (blocked on decision D1)

**Files:** none in this repository until D1 is resolved.

**Do not start without:** the user's explicit approval of D1, a database backup, and a
separate approved maintenance step authorising `scripts/import_scores.py` to write.

- [ ] **Step 1: Verify the shortfall from live data**

```bash
.venv/bin/python - <<'PY'
import hashlib, sqlite3
con = sqlite3.connect("file:data/jobs.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT id, jd_text FROM jobs WHERE status='SHORTLISTED' AND jd_quality='ats'").fetchall()
groups = {hashlib.sha256(" ".join(r["jd_text"].split()).casefold().encode()).hexdigest()
          for r in rows if r["id"] not in (229, 279)}
print(f"{len(rows)} rows -> {len(groups)} distinct eligible JDs (need 30)")
PY
```

- [ ] **Step 2: If the count is below 30, STOP and present D1 to the user**

Do not proceed to Task 8. The scoring batch that would create the corpus writes to
SQLite and is out of scope for every milestone in this plan.

- [ ] **Step 3: After D1 is executed and approved, re-run Step 1**

Proceed only when the count is ≥ 30, and record the new count and the new DB SHA-256
in the M8P-8 decision entry.

---

### Task 8: Resumable batch queue with circuit breaker

**Files:**
- Modify: `src/tailor/pilot.py`, `scripts/tailor_pilot.py`
- Modify: `tests/tailor/test_pilot.py`, `tests/test_tailor_pilot_cli.py`

**Interfaces:**
- Produces:

```python
class BatchAbortReason(str, Enum):
    CONSECUTIVE_FAILURES = "consecutive_failures"
    L7_FAILURE = "l7_failure"
    CALL_BUDGET_EXCEEDED = "call_budget_exceeded"

@dataclass(frozen=True)
class BatchResult:
    completed: tuple[int, ...]
    failed: tuple[int, ...]
    remaining: tuple[int, ...]
    aborted: BatchAbortReason | None
    total_model_calls: int

def run_batch(job_ids: tuple[int, ...], *, db_path: Path, profile_path: Path,
              root: Path = APPLICATIONS_ROOT, max_calls: int | None = None,
              max_consecutive_failures: int = 3) -> BatchResult: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.pilot import BatchAbortReason, run_batch


def test_batch_runs_one_job_to_completion_before_the_next(tmp_repo, ordered_spy):
    run_batch((1, 2, 3), db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert ordered_spy.interleaved is False


def test_batch_skips_completed_applications_at_zero_cost(tmp_repo, one_completed, spy_invocations):
    spy_invocations.reset()
    result = run_batch((1,), db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert spy_invocations.call_count == 0 and result.completed == (1,)


def test_batch_aborts_after_three_consecutive_failures(tmp_repo, mock_all_fail):
    result = run_batch(tuple(range(1, 11)), db_path=tmp_repo.db,
                       profile_path=tmp_repo.profile, root=tmp_repo.root)
    assert result.aborted is BatchAbortReason.CONSECUTIVE_FAILURES
    assert len(result.failed) == 3 and result.remaining


def test_batch_aborts_on_any_l7_failure(tmp_repo, mock_l7_fails_on_second):
    result = run_batch((1, 2, 3), db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                       root=tmp_repo.root)
    assert result.aborted is BatchAbortReason.L7_FAILURE


def test_batch_aborts_when_the_call_budget_is_exceeded(tmp_repo, mock_expensive_runs):
    result = run_batch((1, 2, 3), db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                       root=tmp_repo.root, max_calls=8)
    assert result.aborted is BatchAbortReason.CALL_BUDGET_EXCEEDED


def test_abort_leaves_completed_applications_intact(tmp_repo, mock_l7_fails_on_second):
    result = run_batch((1, 2, 3), db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                       root=tmp_repo.root)
    assert (tmp_repo.root / "co1-role").exists()


def test_interrupted_batch_resumes_where_it_stopped(tmp_repo, mock_all_stages_pass, mock_all_fail):
    first = run_batch((1, 2, 3), db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.root)
    second = run_batch(first.remaining, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                       root=tmp_repo.root)
    assert set(first.completed) & set(second.completed) == set()
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_pilot.py -q -k batch`

Expected: FAIL — `ImportError: cannot import name 'run_batch'`.

- [ ] **Step 3: Implement**

`run_batch` loops `run_application`, accumulating counts and checking the three
circuit-breaker conditions after each job. `max_calls` defaults to
`7 * len(remaining)`. Add the `run-batch` subcommand to the CLI.

- [ ] **Step 4: Run GREEN and full verification**

```bash
.venv/bin/python -m pytest -q
git diff --check
shasum -a 256 data/jobs.db
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/pilot.py scripts/tailor_pilot.py tests/tailor/test_pilot.py tests/test_tailor_pilot_cli.py
git commit -m "feat(m8): add resumable batch queue with circuit breaker"
```

---

### Task 9: Live thirty-resume dry run (with the user)

**This task is executed live, with the user present, in three review batches of ten.**

- [ ] **Step 1: Confirm the gate and the corpus**

```bash
.venv/bin/python -m scripts.tailor_pilot gate --root applications
```

Expected: exit 0. If it exits non-zero, STOP — fix and re-run the three, do not scale
with a caveat. Re-run Task 7 Step 1 and confirm ≥ 30 distinct eligible JDs.

- [ ] **Step 2: Batch 1 — ten jobs**

```bash
.venv/bin/python -m scripts.tailor_pilot run-batch --job-ids-file /tmp/batch1.txt --db data/jobs.db --root applications
```

- [ ] **Step 3: Review batch 1 and re-check the statistics**

The user reviews all ten packets and records feedback for each, then:

```bash
.venv/bin/python -m scripts.tailor_g3 summarize
.venv/bin/python -m scripts.tailor_pilot cost --root applications
```

If batch 1's statistics fall below the §6 thresholds, STOP. Do not run batches 2 and 3
until the cause is found and fixed.

- [ ] **Step 4: Batches 2 and 3**

Repeat Steps 2–3 for the remaining twenty jobs, ten at a time.

- [ ] **Step 5: Final verification and baseline record**

```bash
shasum -a 256 data/jobs.db
.venv/bin/python -m pytest -q
git status --short
```

Record in `docs/DECISIONS.md`: the thirty job ids, the complete cost report (this is
the deterministic baseline M8X-1 must beat), the aggregate feedback statistics, every
circuit-breaker event, and the confirmation that no application was submitted and no
row was mutated.

- [ ] **Step 6: Commit**

```bash
git add docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md docs/DECISIONS.md
git commit -m "docs(m8): close the thirty-resume dry run"
```

---

## Acceptance criteria

See the design's §9 in full. In summary: the operator composes and never reimplements;
every skip/conflict/failure path is tested; a completed application re-runs at zero
cost with byte-identical artifacts; feedback is never overwritten; selection is
read-only, deterministic, and refuses duplicate JD content groups; no code path can
submit an application; the DB checksum is unchanged; three live runs are reviewed and
gated; and M8P-8 runs only behind a passing gate, a resolved D1, and a resumable,
circuit-broken queue reviewed ten at a time.

## Verification commands

```bash
.venv/bin/python -m pytest tests/tailor/test_pilot.py tests/test_tailor_pilot_cli.py tests/test_m8p7_integration.py -q
.venv/bin/python -m pytest -q
git diff --check
git status --short
shasum -a 256 data/jobs.db
.venv/bin/python -m scripts.tailor_pilot gate --root applications
```

## Stop conditions

- Any predecessor milestone unmerged → do not start Task 1.
- `select` cannot satisfy the six criteria → stop and present the shortfall; never relax a criterion silently.
- A stage needs raw SQL outside `src/db.py` → stop and ask.
- The DB checksum changes at any point → stop, restore from `/tmp/jobs.db.pre-m8p7.bak`, report.
- The acceptance gate fails → stop; fix and re-run the three.
- Fewer than 30 distinct eligible JDs → stop at Task 7 Step 2 and present D1.
- Any batch's circuit breaker fires → stop the batch, investigate, do not increase the limits to push through.
- Any request to submit an application automatically → refuse; that is outside every milestone in this plan.
