# M8N-0 Apply-Now Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A file-fed operator lane that runs the full validated tailoring chain (S1→S0→S2→S3→G1→G2→RENDER+L7→G3) from a pasted job description to a reviewed one-page PDF, without opening `data/jobs.db`, so the user can apply to live postings now.

**Architecture:** The chain body is extracted from `src/tailor/pilot.run_application` into `run_stages`, which both the DB-fed pilot and the new `src/tailor/lane.py` composer call. The lane owns JD normalization, a negative deterministic job id, a lane manifest, preflight gating, model-command construction, and a `rejected/` output on L7 failure. Three self-contained commits from `m8v-1-verification` (L7 wrap fix, model-free preflight, trace-fixture recorder) are cherry-picked first; the two documented-shape defects in the S1/S0 prompts are fixed so preflight can pass.

**Tech Stack:** Python 3.11+, existing `src/tailor` package, `claude -p` tool-disabled invocation via `src/tailor/invoke.py`, pdflatex (local), pdfminer.six, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md` (read all of it; §2 verified facts, §3 decisions N1–N12, §6 boundary, §7 M8N-0 design, §11 bar, §12 tests)

**Prerequisites:** `main` at or after `eec2c18`; branch `m8v-1-verification` present locally; `pdflatex` on PATH; `claude` CLI 2.1.x on PATH; `.venv/bin/python -m pytest -q` shows only the pre-existing `tests/test_firecrawl_budget.py::test_budget_reserve_exhausts_monthly` failure.

## Global Constraints

- One milestone: M8N-0 only. Do not start M8N-1 (screen brief, company view, hiring-manager read) or M8N-2.
- Work in a git worktree (`superpowers:using-git-worktrees`). Commit after every task with `feat(m8n0): ...`, `fix(m8n0): ...`, `test(m8n0): ...`, or `docs(m8n0): ...`.
- Never open `data/jobs.db` except through `db.get_readonly_connection` in the `export-jd` helper. Record its SHA-256 before starting and verify it is unchanged at closeout: `shasum -a 256 data/jobs.db`.
- Never stage `data/`, `inbox/`, `applications/`, `applications_manual/`, `profile/` (except `profile/template.tex`), `docs/sampleJD.md`, or `inbox/urls.txt`.
- Tests never touch the network, the production DB, or a model. `pytest -q` must be green apart from the pre-existing Firecrawl budget failure, which is out of scope.
- No new dependencies. No SQL outside `src/db.py`. Type hints everywhere; dataclasses at module boundaries; `logging`, never `print`, inside `src/`.
- Prompt files: the only edits permitted in this milestone are the two documented-shape fixes in Task 2, which require the user's explicit approval at kickoff (spec N12) and a `docs/DECISIONS.md` entry.
- Run tests with the project interpreter: `.venv/bin/python -m pytest ...`. Operator scripts run as `PYTHONPATH=. .venv/bin/python -m scripts.<name>` or `.venv/bin/python -m scripts.<name>` from the repo root.
- Every model call in the live benchmark (Task 7) is user-supervised. The default model is whatever `claude -p` uses; `--model` selects another.

---

## File structure

| File | Responsibility |
|---|---|
| `src/tailor/preflight.py` (cherry-picked) | model-free checks: `do_not_claim` leaks, prompt invariants, variant render |
| `src/render/l7.py` (cherry-picked fix) | L7 checks that survive line wraps and split bold runs |
| `scripts/record_trace_fixture.py` (cherry-picked) | extract a real model response from an I11 trace into a committed fixture behind the identity privacy gate |
| `src/tailor/publish.py` (modify) | `render_and_publish` gains `directory` and `reject_dir`; `_write_rejected` helper |
| `src/tailor/pilot.py` (modify) | `run_application` = feedback refusal + DB prepare + directory resolution; `run_stages` = the chain; `_prepare_failure` helper |
| `src/tailor/lane.py` (create) | JD normalization, lane job id, lane manifest, claude command builder, `run_manual_application` |
| `scripts/tailor_now.py` (create) | CLI: `preflight`, `run`, `status`, `export-jd` |
| `docs/prompts/tailoring_s1.md`, `docs/prompts/tailoring_s0.md` (modify, approved) | documented-shape fixes only |
| `docs/reference/linkedin_hiring_manager_prompt.md` (move) | reference material, not a runtime prompt |
| `.gitignore` (modify) | `applications_manual/`, `inbox/jd/` |
| `tests/tailor/test_preflight.py` (modify), `tests/tailor/test_publish.py` (modify), `tests/tailor/test_pilot.py` (modify), `tests/tailor/test_lane.py` (create), `tests/test_tailor_now_cli.py` (create) | tests |
| `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`, `CLAUDE.md`, `AGENTS.md` (modify) | status and command docs |

---

### Task 1: Cherry-pick the verification-branch fixes

**Files:**
- Create (via cherry-pick): `src/tailor/preflight.py`, `scripts/tailor_preflight.py`, `tests/tailor/test_preflight.py`, `scripts/record_trace_fixture.py`, `tests/fixtures/tailor/traces/*`, `tests/tailor/test_trace_replay.py`, `tests/fixtures/render/real_resume_backend.pdf`
- Modify (via cherry-pick): `src/render/l7.py`, `tests/render/test_l7_tailored.py`

**Interfaces:**
- Produces: `src.tailor.preflight.run_preflight(profile_path: Path, template: Path, prompt_dir: Path, workdir: Path, *, skip_render: bool = False) -> PreflightReport` where `PreflightReport(findings: tuple[PreflightFinding, ...], passed: bool)` and `PreflightFinding(check: str, surface: str, message: str)`.
- Produces: `src.render.l7.check_emphasis_rendered` and `check_bullets_survive` tolerant of wrapped lines (used by `render_and_publish` unchanged).

- [ ] **Step 1: Record the baseline**

Run:
```bash
shasum -a 256 data/jobs.db > /tmp/m8n0-db-before.txt && cat /tmp/m8n0-db-before.txt
```
Run:
```bash
.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
```
Expected: `1 failed, 1851 passed, 1 deselected` with the single failure being `tests/test_firecrawl_budget.py::test_budget_reserve_exhausts_monthly`.

- [ ] **Step 2: Cherry-pick in chronological order**

Run:
```bash
git cherry-pick ee035d0 30bc989 deb1f9d
```
Expected: three new commits, no conflicts (verified in design with `git merge-tree --write-tree`). If any conflict appears, stop and report; do not resolve by hand.

- [ ] **Step 3: Run the suite**

Run:
```bash
.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_preflight.py tests/tailor/test_trace_replay.py tests/render/test_l7_tailored.py
```
Expected: PASS. Note that `test_real_prompts_have_exactly_the_two_known_shape_defects` and `test_run_preflight_against_the_real_repo_surfaces_exactly_the_known_shape_findings` pass only while the two prompt defects exist; Task 2 flips them. If the worktree contains `docs/prompts/resume_prompt.md` (an untracked file in the user's main checkout, absent from a fresh worktree), the second test fails with a `marker ... found 0` finding for that file; Task 2 moves it.

Run:
```bash
.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
```
Expected: only the pre-existing Firecrawl budget failure.

- [ ] **Step 4: No commit needed**

The cherry-picks are the commits. Verify with `git log --oneline -3` that the three subjects match `feat(m8v): add model-free tailoring preflight`, `test(m8v): replay recorded model output in parser tests`, `fix(m8v): validate L7 against a real wrapped resume`.

---

### Task 2: Fix the two documented-shape defects in the S1 and S0 prompts (user-approved)

**Files:**
- Modify: `docs/prompts/tailoring_s1.md` (the `nice_to_have` example entry inside "Required response shape")
- Modify: `docs/prompts/tailoring_s0.md` (the `points` example)
- Modify: `tests/tailor/test_preflight.py` (two tests)
- Move: `docs/prompts/resume_prompt.md` → `docs/reference/linkedin_hiring_manager_prompt.md` (main checkout; see Step 6)
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Produces: `check_prompt_invariants(Path("docs/prompts"))` returns `()` and `run_preflight(..., skip_render=True)` on the real repo returns `passed is True`. Task 5 depends on this.

Why: `src/tailor/preflight._shape_passes` runs each prompt's documented JSON example through that stage's own structural parser. `tailoring_s1.md` uses the identical placeholder term in `must_have` and `nice_to_have`, tripping `_check_no_duplicate_terms` (structural). `tailoring_s0.md` shows one `points` entry while `parse_s0_response` requires two to four (structural). Semantic checks (quote anchoring) are tolerated by the preflight, so placeholder text elsewhere is fine.

- [ ] **Step 0: Confirm approval**

Confirm in the session that the user approved these two prompt edits (spec N12). If not, stop.

- [ ] **Step 1: Flip the two tests to expect zero findings**

In `tests/tailor/test_preflight.py`, replace `test_real_prompts_have_exactly_the_two_known_shape_defects` with:

```python
def test_real_prompts_have_no_invariant_findings():
    """M8N-0 fixed the two documented-shape defects M8V-1 discovered
    (S1 duplicate placeholder term across must_have/nice_to_have; S0
    single-point example against its own two-to-four rule). The real
    prompt directory must now be clean: no fence, no marker defect, no
    shape defect, for every runtime prompt."""
    findings = check_prompt_invariants(Path("docs/prompts"))
    assert findings == (), [f.message for f in findings]
```

and replace `test_run_preflight_against_the_real_repo_surfaces_exactly_the_known_shape_findings` with:

```python
def test_run_preflight_against_the_real_repo_passes_without_render(tmp_path):
    report = run_preflight(
        Path("config/master_profile.yaml"), Path("profile/template.tex"),
        Path("docs/prompts"), tmp_path, skip_render=True,
    )
    assert report.passed is True, [f.message for f in report.findings]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_preflight.py -k "no_invariant_findings or passes_without_render"`
Expected: FAIL, both, with findings naming `tailoring_s0.md` and `tailoring_s1.md`.

- [ ] **Step 3: Fix the S1 example**

In `docs/prompts/tailoring_s1.md`, inside the "Required response shape" object, change the `nice_to_have` entry from

```
  "nice_to_have": [
    {"term": "<exact JD surface form>", "quote": "<exact JD substring containing the term>"}
  ],
```

to

```
  "nice_to_have": [
    {"term": "<exact JD surface form of a preferred item>", "quote": "<exact JD substring containing the preferred item>"}
  ],
```

Change nothing else in the file.

- [ ] **Step 4: Fix the S0 example**

In `docs/prompts/tailoring_s0.md`, change the `points` example from a single object to two objects:

```
  "points": [
    {
      "sentence": "one advisory strategy sentence",
      "profile_ids": ["exact supplied project or experience id"],
      "requirement_terms": ["exact supplied S1 must_have or nice_to_have term"],
      "jd_quotes": ["exact supplied S1 evidence-pool quote"]
    },
    {
      "sentence": "a second, different advisory strategy sentence",
      "profile_ids": ["another exact supplied project or experience id"],
      "requirement_terms": ["another exact supplied S1 term"],
      "jd_quotes": ["another exact supplied S1 evidence-pool quote"]
    }
  ]
```

Change nothing else in the file. (The parser rejects duplicate normalized sentences and duplicate citations within a point, so the second point must differ in every field.)

- [ ] **Step 5: Run the preflight tests**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_preflight.py`
Expected: PASS (all). If `_shape_passes` still rejects a block, print the findings and adjust only the example text until the structural parser accepts it; never change a rule sentence.

- [ ] **Step 6: Move the LinkedIn prompt out of the runtime prompt directory**

The file `docs/prompts/resume_prompt.md` is untracked in the user's main checkout. Create `docs/reference/linkedin_hiring_manager_prompt.md` in the worktree with this header followed by the prompt text copied verbatim from the main checkout's file:

```
# Reference: LinkedIn "senior hiring manager" prompt (not a runtime prompt)

Kept for reference only. Per spec N6 (`docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md`
§3), this prompt is not used by any stage. Its intent is implemented as the anchored screen
brief and hiring-manager read stages in M8N-1. `docs/prompts/` holds runtime templates only;
the preflight's prompt-invariant check scans every `*.md` there.

---

```

Then tell the user to delete `docs/prompts/resume_prompt.md` from the main checkout at merge time (it is theirs and untracked; do not delete files outside the worktree).

- [ ] **Step 7: Record the approval**

Append to `docs/DECISIONS.md`:

```
## 2026-09-01 — M8N-0 prompt documented-shape fixes (approved)

`docs/prompts/tailoring_s1.md`: the `nice_to_have` example term no longer duplicates the
`must_have` placeholder (the structural duplicate-term guard rejected the prompt's own
example). `docs/prompts/tailoring_s0.md`: the example now shows two `points` entries,
matching the prompt's own two-to-four rule. No rule sentence changed. Approved by the user
at M8N-0 kickoff under spec N12; `check_prompt_invariants(docs/prompts)` now returns no
findings. The LinkedIn hiring-manager prompt moved to
`docs/reference/linkedin_hiring_manager_prompt.md` (spec N6).
```

- [ ] **Step 8: Commit**

```bash
git add docs/prompts/tailoring_s1.md docs/prompts/tailoring_s0.md tests/tailor/test_preflight.py docs/reference/linkedin_hiring_manager_prompt.md docs/DECISIONS.md
git commit -m "fix(m8n0): repair documented S1/S0 response shapes so preflight passes"
```

---

### Task 3: `render_and_publish` directory override and rejected output

**Files:**
- Modify: `src/tailor/publish.py:122-200` (`render_and_publish`) plus a new `_write_rejected` helper above it
- Test: `tests/tailor/test_publish.py` (append)

**Interfaces:**
- Produces: `render_and_publish(profile, draft, *, root: Path, template_path: Path, canonical_text_by_id: dict[str, str], s3_bundle_schema_version: str, directory: Path | None = None, reject_dir: Path | None = None) -> RenderOutcome`. With both new arguments `None`, behavior is byte-identical to today.
- Produces: `_write_rejected(reject_dir: Path, tmp_pdf: Path, pdf_name: str, violations: tuple[str, ...]) -> None` writes `resume.tex`, `<pdf_name>`, and `l7_report.json` (a JSON list of violation strings) into `reject_dir`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/tailor/test_publish.py`:

```python
# ---------------------------------------------------------------------------
# M8N-0: explicit directory override and rejected output on L7 failure
# ---------------------------------------------------------------------------


def test_directory_override_is_used_instead_of_derived_dir(profile, real_draft, tmp_path, stub_render_good_pdf):
    target = tmp_path / "custom" / "acme-fixture_role-second"
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1",
                                 directory=target)
    assert outcome.kind is RenderOutcomeKind.VALID
    assert (target / "render_result.json").exists()
    assert not application_dir(tmp_path, "Acme", "Fixture Role").exists()


def test_l7_failure_writes_rejected_artifacts_and_no_marker(profile, real_draft, tmp_path, stub_render_bad_pdf):
    target = tmp_path / "acme-fixture_role"
    reject = target / "rejected"
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1",
                                 directory=target, reject_dir=reject)
    assert outcome.kind is RenderOutcomeKind.L7_FAILURE
    assert outcome.violations
    assert (reject / "resume.tex").exists()
    assert (reject / profile.ats["filename_pattern"]).exists()
    assert json.loads((reject / "l7_report.json").read_text(encoding="utf-8")) == list(outcome.violations)
    assert not (target / "render_result.json").exists()


def test_l7_failure_without_reject_dir_writes_nothing(profile, real_draft, tmp_path, stub_render_bad_pdf):
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.L7_FAILURE
    assert not list(tmp_path.rglob("rejected"))
    assert not list(tmp_path.rglob("*.tex"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_publish.py -k "directory_override or rejected_artifacts or without_reject_dir"`
Expected: FAIL with `TypeError: render_and_publish() got an unexpected keyword argument 'directory'` for the first two; the third passes already (it asserts existing behavior) and stays as a regression guard.

- [ ] **Step 3: Implement**

In `src/tailor/publish.py`, add above `render_and_publish`:

```python
def _write_rejected(reject_dir: Path, tmp_pdf: Path, pdf_name: str, violations: tuple[str, ...]) -> None:
    """Copy a render that failed L7 somewhere a human can look at it. Never
    writes render_result.json; the accepted marker stays absent."""
    reject_dir = Path(reject_dir)
    reject_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmp_pdf.with_suffix(".tex"), reject_dir / "resume.tex")
    shutil.copy(tmp_pdf, reject_dir / pdf_name)
    write_json_atomic(reject_dir / "l7_report.json", list(violations))
```

Change the signature and the two affected lines of `render_and_publish`:

```python
def render_and_publish(
    profile, draft, *, root: Path, template_path: Path,
    canonical_text_by_id: dict[str, str], s3_bundle_schema_version: str,
    directory: Path | None = None, reject_dir: Path | None = None,
) -> RenderOutcome:
    ...
    directory = Path(directory) if directory is not None else application_dir(root, draft.company, draft.title)
    ...
        violations = tuple(run_l7_tailored(doc, parsed, pages, modified_ids))
        if violations:
            if reject_dir is not None:
                _write_rejected(Path(reject_dir), tmp_pdf, profile.ats["filename_pattern"], violations)
            return RenderOutcome(RenderOutcomeKind.L7_FAILURE, None, violations, None)
```

Everything else in the function stays as is (the `marker_path`, `pdf_name`, copy, and `RenderResult` code already use the local `directory`).

- [ ] **Step 4: Run the publish tests**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_publish.py tests/test_tailor_render_cli.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tailor/publish.py tests/tailor/test_publish.py
git commit -m "feat(m8n0): add directory override and rejected output to render_and_publish"
```

---

### Task 4: Extract `run_stages` from the pilot and thread the model command

**Files:**
- Modify: `src/tailor/pilot.py:268-660` (`run_application`)
- Test: `tests/tailor/test_pilot.py` (append)

**Interfaces:**
- Consumes: `render_and_publish(..., directory=, reject_dir=)` from Task 3; `DEFAULT_CLAUDE_CMD` from `src/tailor/invoke.py`.
- Produces:

```python
def run_stages(
    s1_request: S1Request, variant: str, *,
    directory: Path, profile_path: Path, root: Path,
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    reject_dir: Path | None = None,
    retry_prefix: str | None = None,
) -> RunOutcome
```

  `run_stages` performs the PREPARE artifact write/completeness check (`s1_request.json`) and every stage after it, exactly as `run_application` does today, writing `run_manifest.json` into `directory` unless `dry_run`. `retry_prefix` defaults to `f"python -m scripts.tailor_pilot run --job-id {s1_request.job_id}"`; the retry command is `f"{retry_prefix} --only {stage}"`.
- Produces: `_prepare_failure(job_id: int, outcome_kind: str, error: str, started: str) -> RunOutcome` returning a `RunOutcome` whose manifest has one FAILED PREPARE record, empty company/title, and `failed_stage=Stage.PREPARE`, with `retry_command=None`.
- `run_application` keeps its exact signature and behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/tailor/test_pilot.py`:

```python
# ---------------------------------------------------------------------------
# M8N-0: run_stages is the shared chain; run_application delegates to it
# ---------------------------------------------------------------------------

from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.pilot import run_stages
from src.tailor.s1 import S1Request


def _lane_request(job_id=PILOT_JOB_ID):
    return S1Request(job_id=job_id, company="Example", title="Engineer", jd_text="Python", jd_quality="ats")


def test_run_stages_matches_run_application_stage_states(tmp_repo, mock_all_stages_pass):
    via_pilot = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                                root=tmp_repo.applications)
    other_root = tmp_repo.root / "applications_b"
    from src.tailor.publish import application_dir
    via_stages = run_stages(_lane_request(), "ml", directory=application_dir(other_root, "Example", "Engineer"),
                            profile_path=tmp_repo.profile, root=other_root)
    assert [(r.stage, r.state) for r in via_stages.manifest.stages] == \
           [(r.stage, r.state) for r in via_pilot.manifest.stages]
    assert via_stages.manifest.total_model_calls == via_pilot.manifest.total_model_calls
    assert via_stages.failed_stage is None


def test_run_stages_threads_claude_cmd_to_every_runner(tmp_repo, monkeypatch):
    chain = _build_valid_chain()
    seen: dict[str, tuple] = {}

    def fake_s1(request, **kwargs):
        seen["s1"] = kwargs.get("claude_cmd")
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        seen["s0"] = kwargs.get("claude_cmd")
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        seen["s2"] = kwargs.get("claude_cmd")
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        seen["s3"] = kwargs.get("claude_cmd")
        return S3Outcome(kind=S3OK.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        seen["g2"] = kwargs.get("claude_cmd")
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1)
    monkeypatch.setattr("src.tailor.pilot.run_s0_invocation", fake_s0)
    monkeypatch.setattr("src.tailor.pilot.run_s2_invocation", fake_s2)
    monkeypatch.setattr("src.tailor.pilot.run_s3_invocation", fake_s3)
    monkeypatch.setattr("src.tailor.pilot.run_g2_loop", fake_g2)
    cmd = ("claude", "-p", "--model", "sonnet", "--tools", "", "--no-session-persistence", "--")
    run_stages(_lane_request(), "ml", directory=tmp_repo.root / "app", profile_path=tmp_repo.profile,
               root=tmp_repo.root, claude_cmd=cmd, stop_after=Stage.G2)
    assert seen == {"s1": cmd, "s0": cmd, "s2": cmd, "s3": cmd, "g2": cmd}


def test_run_stages_default_command_is_the_pilot_constant(tmp_repo, monkeypatch):
    chain = _build_valid_chain()
    seen = {}

    def fake_s1(request, **kwargs):
        seen["s1"] = kwargs.get("claude_cmd")
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1)
    run_stages(_lane_request(), "ml", directory=tmp_repo.root / "app", profile_path=tmp_repo.profile,
               root=tmp_repo.root, stop_after=Stage.S1)
    assert seen["s1"] == DEFAULT_CLAUDE_CMD


def test_run_stages_passes_directory_and_reject_dir_to_render(tmp_repo, mock_all_stages_pass, monkeypatch):
    captured = {}
    original = __import__("src.tailor.pilot", fromlist=["render_and_publish"]).render_and_publish

    def spy_render(profile, draft, *, root, **kwargs):
        captured.update(kwargs)
        return original(profile, draft, root=root, **kwargs)

    monkeypatch.setattr("src.tailor.pilot.render_and_publish", spy_render)
    target = tmp_repo.root / "apps" / "example-engineer"
    run_stages(_lane_request(), "ml", directory=target, profile_path=tmp_repo.profile,
               root=tmp_repo.root / "apps", reject_dir=target / "rejected")
    assert captured["directory"] == target
    assert captured["reject_dir"] == target / "rejected"


def test_run_stages_retry_prefix_shapes_the_retry_command(tmp_repo, monkeypatch):
    def failing_s1(request, **kwargs):
        return S1Outcome(kind=S1OutcomeKind.INVOCATION_FAILURE, response=None, error="down", trace_path=None)

    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", failing_s1)
    outcome = run_stages(_lane_request(), "ml", directory=tmp_repo.root / "app", profile_path=tmp_repo.profile,
                         root=tmp_repo.root, retry_prefix="python -m scripts.tailor_now run --jd jd.txt")
    assert outcome.failed_stage is Stage.S1
    assert outcome.retry_command == "python -m scripts.tailor_now run --jd jd.txt --only s1"


def test_run_stages_negative_job_id_round_trips_through_artifacts(tmp_repo, mock_all_stages_pass):
    """Lane job ids are negative (spec §7.7). Every envelope and completeness
    check must accept them."""
    directory = tmp_repo.root / "neg"
    first = run_stages(_lane_request(job_id=-424242), "ml", directory=directory,
                       profile_path=tmp_repo.profile, root=tmp_repo.root, stop_after=Stage.S2)
    assert first.failed_stage is None
    second = run_stages(_lane_request(job_id=-424242), "ml", directory=directory,
                        profile_path=tmp_repo.profile, root=tmp_repo.root, stop_after=Stage.S2)
    by_stage = {r.stage: r.state for r in second.manifest.stages}
    assert by_stage[Stage.S1] is StageState.SKIPPED_COMPLETE
    assert by_stage[Stage.S2] is StageState.SKIPPED_COMPLETE
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_pilot.py -k run_stages`
Expected: FAIL with `ImportError: cannot import name 'run_stages'`.

- [ ] **Step 3: Implement the extraction**

In `src/tailor/pilot.py`:

1. Add `from src.tailor.invoke import DEFAULT_CLAUDE_CMD` to the imports.
2. Add the helper:

```python
def _prepare_failure(job_id: int, outcome_kind: str, error: str, started: str) -> RunOutcome:
    record = StageRecord(
        stage=Stage.PREPARE, state=StageState.FAILED, outcome_kind=outcome_kind, artifact_path=None,
        model_calls=0, trace_paths=(), started_at=started, ended_at=_now(), error=bounded(error),
    )
    manifest = RunManifest(
        schema_version=MANIFEST_SCHEMA, job_id=job_id, company="", title="", alignment_fingerprint=None,
        stages=(record,), total_model_calls=0, db_mutations=0, submissions=0,
    )
    return RunOutcome(manifest=manifest, failed_stage=Stage.PREPARE, retry_command=None)
```

3. Rewrite `run_application` so that everything up to and including the directory resolution stays, and the rest moves:

```python
def run_application(
    job_id: int, *, db_path: Path, profile_path: Path,
    root: Path = APPLICATIONS_ROOT,
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    feedback_dir: Path = DEFAULT_FEEDBACK_DIR,
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None,
    only: Stage | None = None,
    dry_run: bool = False,
    allow_rerun_after_feedback: bool = False,
) -> RunOutcome:
    started = _now()
    if not allow_rerun_after_feedback:
        if any(entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)):
            return _prepare_failure(
                job_id, "feedback_recorded",
                "feedback already recorded for this job; rerun refused (use --allow-rerun-after-feedback)", started,
            )

    conn = db.get_readonly_connection(db_path)
    try:
        try:
            s1_request = db.prepare_tailoring_request(conn, job_id)
            variant = db.tailoring_base_variant(conn, job_id)
        except Exception as exc:
            return _prepare_failure(job_id, "prepare_failure", str(exc), started)
    finally:
        conn.close()

    directory = application_dir(root, s1_request.company, s1_request.title)
    if allow_rerun_after_feedback and any(
        entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)
    ):
        n = 1
        while (directory / f"rerun-{n}").exists():
            n += 1
        directory = directory / f"rerun-{n}"

    return run_stages(
        s1_request, variant, directory=directory, profile_path=profile_path, root=root,
        template_path=template_path, banned_words_path=banned_words_path, taste_path=taste_path,
        trace_dir=trace_dir, prompt_dir=prompt_dir, stop_after=stop_after, only=only, dry_run=dry_run,
    )
```

4. Create `run_stages` with the signature in Interfaces. Its body is the existing code from `stage_records: list[StageRecord] = []` through the final `return finish(None)`, with these edits and no others:
   - `job_id = s1_request.job_id` and `company, title = s1_request.company, s1_request.title` at the top; `directory` is the parameter (drop the `directory: Path | None = None` local and the `application_dir`/`rerun-N` block, which moved to `run_application`).
   - `finish` computes `prefix = retry_prefix or f"python -m scripts.tailor_pilot run --job-id {job_id}"` and `retry_command = f"{prefix} --only {failed_stage.value}" if failed_stage is not None else None`.
   - Every `run_s1_invocation`, `run_s0_invocation`, `run_s2_invocation`, `run_s3_invocation`, and `run_g2_loop` call gains `claude_cmd=claude_cmd`.
   - The `render_and_publish` call gains `directory=directory, reject_dir=reject_dir`.
   - The PREPARE early-return that previously used `record(...)`/`finish(...)` for the DB failure is gone; the PREPARE block that begins at `prepare_exists = artifact_path(directory, Stage.PREPARE).exists()` stays and is the first thing `run_stages` does after the `started = _now()` line.

- [ ] **Step 4: Run the pilot suite and the integration tests**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_pilot.py tests/test_m8p7_integration.py tests/test_tailor_pilot_cli.py`
Expected: PASS, including every pre-existing pilot test unchanged.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3`
Expected: only the pre-existing Firecrawl budget failure.

- [ ] **Step 6: Commit**

```bash
git add src/tailor/pilot.py tests/tailor/test_pilot.py
git commit -m "feat(m8n0): extract run_stages from the pilot and thread the model command"
```

---

### Task 5: The lane composer (`src/tailor/lane.py`)

**Files:**
- Create: `src/tailor/lane.py`
- Modify: `.gitignore`
- Test: `tests/tailor/test_lane.py`

**Interfaces:**
- Consumes: `run_stages` (Task 4), `run_preflight` (Task 1), `application_dir`, `slugify` (`src/tailor/publish.py`), `write_json_atomic`, `load_profile`, `S1Request`, `s1_request_to_dict`.
- Produces:

```python
LANE_MANIFEST_SCHEMA = "m8n0.lane_manifest.v1"
APPLICATIONS_MANUAL_ROOT = Path("applications_manual")
JD_MIN_CHARS = 300
JD_MAX_CHARS = 40_000

class LaneError(ValueError): ...

def normalize_jd(raw: str) -> str            # strip BOM, CRLF->LF; raises LaneError outside bounds
def lane_job_id(jd_text: str) -> int         # negative deterministic id (spec §7.7)
def build_claude_cmd(model: str | None) -> tuple[str, ...]
def lane_directory(root: Path, company: str, title: str, suffix: str | None) -> Path

@dataclass(frozen=True)
class LaneManifest:
    schema_version: str; job_id: int; jd_sha256: str; jd_path: str; company: str; title: str
    variant: str; model: str | None; claude_cmd: tuple[str, ...]; jd_quality: str; created_at: str

def lane_manifest_to_dict(m: LaneManifest) -> dict[str, object]
def parse_lane_manifest(raw: object) -> LaneManifest   # exact key set, raises LaneError

def run_manual_application(
    jd_path: Path, *, company: str, title: str, variant: str,
    root: Path = APPLICATIONS_MANUAL_ROOT, model: str | None = None, suffix: str | None = None,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
) -> RunOutcome
```

- [ ] **Step 1: Write the failing tests**

Create `tests/tailor/test_lane.py`:

```python
"""Apply-Now lane composer (M8N-0). No model, no network, no DB. Stage
runners are faked at the src.tailor.pilot seam exactly as the pilot tests
do; the lane's own logic (JD normalization, job id, manifest, preflight
gate, model command, rejected output) is what is under test."""
import json
from pathlib import Path

import pytest

from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    JD_MAX_CHARS,
    JD_MIN_CHARS,
    LANE_MANIFEST_SCHEMA,
    LaneError,
    build_claude_cmd,
    lane_directory,
    lane_job_id,
    lane_manifest_to_dict,
    normalize_jd,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import Stage, StageState
from src.tailor.preflight import PreflightFinding, PreflightReport
from src.tailor.publish import RenderOutcome, RenderOutcomeKind
from tests.tailor.test_pilot import PILOT_JOB_ID, _build_valid_chain

PROFILE = Path("config/master_profile.yaml")
JD_TEXT = "Python " * 60  # 420 chars, above JD_MIN_CHARS


@pytest.fixture
def jd_file(tmp_path):
    path = tmp_path / "jd.txt"
    path.write_text(JD_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def passing_preflight(monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight",
                        lambda *a, **k: PreflightReport(findings=(), passed=True))


@pytest.fixture
def pinned_job_id(monkeypatch):
    """The fake chain below carries job_id 225; pin the lane's id to it so
    completeness checks bind."""
    monkeypatch.setattr("src.tailor.lane.lane_job_id", lambda jd_text: PILOT_JOB_ID)


class _Spy:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []


@pytest.fixture
def fake_chain(monkeypatch):
    from src.tailor.g2_pipeline import G2Outcome, G2OutcomeKind
    from src.tailor.g3 import G3Outcome, G3OutcomeKind, packet_to_dict
    from src.tailor.publish import render_result_to_dict
    from src.tailor.s0_pipeline import S0Outcome, S0OutcomeKind
    from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind
    from src.tailor.s2_pipeline import S2Outcome, S2OutcomeKind
    from src.tailor.s3_pipeline import S3Outcome, S3OutcomeKind

    chain = _build_valid_chain()
    spy = _Spy()

    def fake_s1(request, **kwargs):
        spy.calls.append(("s1", kwargs.get("claude_cmd")))
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        spy.calls.append(("s0", kwargs.get("claude_cmd")))
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        spy.calls.append(("s2", kwargs.get("claude_cmd")))
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        spy.calls.append(("s3", kwargs.get("claude_cmd")))
        return S3Outcome(kind=S3OutcomeKind.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        spy.calls.append(("g2", kwargs.get("claude_cmd")))
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    def fake_render(profile, draft, *, root, directory=None, reject_dir=None, **kwargs):
        spy.calls.append(("render", (directory, reject_dir)))
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render_result.json").write_text(
            json.dumps(render_result_to_dict(chain.render_result)), encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.VALID, result=chain.render_result, violations=(), error=None)

    def fake_g3(packet, changed_bullet_ids, directory):
        spy.calls.append(("g3", ()))
        Path(directory).mkdir(parents=True, exist_ok=True)
        (Path(directory) / "packet.json").write_text(json.dumps(packet_to_dict(packet)), encoding="utf-8")
        return G3Outcome(kind=G3OutcomeKind.BUILT, packet=packet, error=None)

    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1)
    monkeypatch.setattr("src.tailor.pilot.run_s0_invocation", fake_s0)
    monkeypatch.setattr("src.tailor.pilot.run_s2_invocation", fake_s2)
    monkeypatch.setattr("src.tailor.pilot.run_s3_invocation", fake_s3)
    monkeypatch.setattr("src.tailor.pilot.run_g2_loop", fake_g2)
    monkeypatch.setattr("src.tailor.pilot.render_and_publish", fake_render)
    monkeypatch.setattr("src.tailor.pilot.publish_packet", fake_g3)
    return spy


# --- pure helpers -----------------------------------------------------------

def test_normalize_jd_strips_bom_and_crlf_only():
    raw = "\ufeffLine one\r\nLine two  \r\n" + "x" * JD_MIN_CHARS
    out = normalize_jd(raw)
    assert out.startswith("Line one\nLine two  \n")
    assert "\r" not in out and "\ufeff" not in out


def test_normalize_jd_rejects_short_and_long():
    with pytest.raises(LaneError, match="at least"):
        normalize_jd("x" * (JD_MIN_CHARS - 1))
    with pytest.raises(LaneError, match="at most"):
        normalize_jd("x" * (JD_MAX_CHARS + 1))


def test_lane_job_id_is_negative_deterministic_and_content_bound():
    a = lane_job_id("hello world " * 30)
    assert a < 0 and a == lane_job_id("hello world " * 30)
    assert a != lane_job_id("hello world " * 30 + "!")


def test_build_claude_cmd_default_and_model():
    assert build_claude_cmd(None) == DEFAULT_CLAUDE_CMD
    assert build_claude_cmd("sonnet") == ("claude", "-p", "--model", "sonnet", "--tools", "", "--no-session-persistence", "--")


def test_build_claude_cmd_rejects_flag_like_model():
    with pytest.raises(LaneError):
        build_claude_cmd("--dangerously-skip-permissions")


def test_lane_directory_with_and_without_suffix(tmp_path):
    assert lane_directory(tmp_path, "Twitch", "Software Engineer", None).name == "twitch-software_engineer"
    assert lane_directory(tmp_path, "Twitch", "Software Engineer", "Req 2").name == "twitch-software_engineer-req_2"


def test_lane_manifest_round_trips_strictly():
    raw = {
        "schema_version": LANE_MANIFEST_SCHEMA, "job_id": -5, "jd_sha256": "a" * 64, "jd_path": "inbox/jd/x.txt",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": None,
        "claude_cmd": list(DEFAULT_CLAUDE_CMD), "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00",
    }
    manifest = parse_lane_manifest(raw)
    assert lane_manifest_to_dict(manifest) == raw
    with pytest.raises(LaneError):
        parse_lane_manifest({**raw, "extra": 1})
    with pytest.raises(LaneError):
        parse_lane_manifest({k: v for k, v in raw.items() if k != "variant"})


# --- composer ---------------------------------------------------------------

def test_unknown_variant_is_refused_before_any_write(tmp_path, jd_file, passing_preflight):
    with pytest.raises(LaneError, match="variant"):
        run_manual_application(jd_file, company="Example", title="Engineer", variant="nope",
                               root=tmp_path / "apps", profile_path=PROFILE)
    assert not (tmp_path / "apps").exists()


def test_preflight_failure_stops_before_any_model_call(tmp_path, jd_file, fake_chain, monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(
        findings=(PreflightFinding("prompt_invariants", "tailoring_s1.md", "bad"),), passed=False))
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "preflight_failure"
    assert "tailoring_s1.md" in outcome.manifest.stages[0].error
    assert fake_chain.calls == []
    assert not (tmp_path / "apps").exists()


def test_full_run_writes_jd_snapshot_manifest_and_reaches_g3(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE, model="sonnet")
    assert outcome.failed_stage is None
    directory = tmp_path / "apps" / "example-engineer"
    assert (directory / "jd.txt").read_text(encoding="utf-8") == normalize_jd(JD_TEXT)
    manifest = parse_lane_manifest(json.loads((directory / "lane_manifest.json").read_text(encoding="utf-8")))
    assert manifest.model == "sonnet" and manifest.claude_cmd == build_claude_cmd("sonnet")
    assert manifest.jd_quality == "ats" and manifest.variant == "ml"
    assert (directory / "s1_request.json").exists() and (directory / "packet.json").exists()
    assert (directory / "run_manifest.json").exists()
    assert outcome.manifest.db_mutations == 0 and outcome.manifest.submissions == 0
    model_calls = [cmd for name, cmd in fake_chain.calls if name in {"s1", "s0", "s2", "s3", "g2"}]
    assert model_calls and all(cmd == build_claude_cmd("sonnet") for cmd in model_calls)
    render_args = next(args for name, args in fake_chain.calls if name == "render")
    assert render_args == (directory, directory / "rejected")


def test_second_identical_run_makes_zero_model_calls(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    fake_chain.calls.clear()
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is None
    assert outcome.manifest.total_model_calls == 0
    assert [name for name, _ in fake_chain.calls] == []


def test_mismatched_jd_for_same_directory_is_refused(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    other = tmp_path / "jd2.txt"
    other.write_text(JD_TEXT + " Go", encoding="utf-8")
    fake_chain.calls.clear()
    outcome = run_manual_application(other, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "lane_manifest_mismatch"
    assert "--suffix" in outcome.manifest.stages[0].error
    assert fake_chain.calls == []


def test_mismatched_variant_for_same_directory_is_refused(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="backend",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "lane_manifest_mismatch"


def test_suffix_separates_two_postings(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE, suffix="req-a")
    assert (tmp_path / "apps" / "example-engineer-req_a" / "lane_manifest.json").exists()


def test_dry_run_writes_nothing_and_calls_nothing(tmp_path, jd_file, fake_chain, passing_preflight):
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE, dry_run=True)
    assert outcome.failed_stage is None
    assert fake_chain.calls == []
    assert not (tmp_path / "apps").exists()


def test_l7_failure_surfaces_rejected_path_in_error(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id, monkeypatch):
    def failing_render(profile, draft, *, root, directory=None, reject_dir=None, **kwargs):
        Path(reject_dir).mkdir(parents=True, exist_ok=True)
        (Path(reject_dir) / "l7_report.json").write_text('["L7 bullet: x did not survive"]', encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.L7_FAILURE, result=None,
                             violations=("L7 bullet: x did not survive",), error=None)

    monkeypatch.setattr("src.tailor.pilot.render_and_publish", failing_render)
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.RENDER
    assert (tmp_path / "apps" / "example-engineer" / "rejected" / "l7_report.json").exists()
    assert outcome.retry_command.startswith("python -m scripts.tailor_now run --jd ")
    assert outcome.retry_command.endswith("--only render")


def test_real_preflight_passes_on_the_repo(tmp_path):
    """The lane's PREPARE gate against the real prompts and profile, no render."""
    from src.tailor.lane import _preflight_findings
    assert _preflight_findings(PROFILE, Path("profile/template.tex"), Path("docs/prompts")) == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_lane.py`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'src.tailor.lane'`.

- [ ] **Step 3: Implement `src/tailor/lane.py`**

```python
"""Apply-Now lane (M8N-0): a file-fed entry to the validated tailoring
chain. Reads a pasted JD, never opens data/jobs.db, and delegates every
stage to src.tailor.pilot.run_stages. Spec:
docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md §7."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.profile import load_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.pilot import (
    DEFAULT_PROMPT_DIR,
    RunOutcome,
    Stage,
    _now,
    _prepare_failure,
    run_stages,
)
from src.tailor.preflight import PreflightFinding, run_preflight
from src.tailor.publish import application_dir, slugify
from src.tailor.s1 import S1Request

log = logging.getLogger(__name__)

LANE_MANIFEST_SCHEMA = "m8n0.lane_manifest.v1"
APPLICATIONS_MANUAL_ROOT = Path("applications_manual")
JD_MIN_CHARS = 300
JD_MAX_CHARS = 40_000
LANE_MANIFEST_NAME = "lane_manifest.json"
JD_SNAPSHOT_NAME = "jd.txt"


class LaneError(ValueError):
    """Operator input the lane refuses (bad JD, unknown variant, bad model name)."""


def normalize_jd(raw: str) -> str:
    text = raw[1:] if raw.startswith("\ufeff") else raw
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) < JD_MIN_CHARS:
        raise LaneError(f"jd text must be at least {JD_MIN_CHARS} characters, got {len(text)}")
    if len(text) > JD_MAX_CHARS:
        raise LaneError(f"jd text must be at most {JD_MAX_CHARS} characters, got {len(text)}")
    return text


def _jd_sha256(jd_text: str) -> str:
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()


def lane_job_id(jd_text: str) -> int:
    """Negative, deterministic, content-bound (spec §7.7). Negative ids cannot
    collide with DB ids and mark every artifact as lane-issued."""
    return -(int(_jd_sha256(jd_text)[:12], 16) % 10**9) - 1


def build_claude_cmd(model: str | None) -> tuple[str, ...]:
    """`--tools ""` must never be last and the trailing `--` keeps the prompt
    positional (see src/tailor/invoke.py)."""
    if model is None:
        return DEFAULT_CLAUDE_CMD
    if not model.strip() or model.startswith("-") or any(ch.isspace() for ch in model):
        raise LaneError(f"model must be a bare model name, got {model!r}")
    return ("claude", "-p", "--model", model, "--tools", "", "--no-session-persistence", "--")


def lane_directory(root: Path, company: str, title: str, suffix: str | None) -> Path:
    base = application_dir(root, company, title)
    if suffix is None or not suffix.strip():
        return base
    return base.with_name(f"{base.name}-{slugify(suffix)}")


@dataclass(frozen=True)
class LaneManifest:
    schema_version: str
    job_id: int
    jd_sha256: str
    jd_path: str
    company: str
    title: str
    variant: str
    model: str | None
    claude_cmd: tuple[str, ...]
    jd_quality: str
    created_at: str


_LANE_MANIFEST_KEYS = {
    "schema_version", "job_id", "jd_sha256", "jd_path", "company", "title", "variant", "model",
    "claude_cmd", "jd_quality", "created_at",
}


def lane_manifest_to_dict(m: LaneManifest) -> dict[str, object]:
    return {
        "schema_version": m.schema_version, "job_id": m.job_id, "jd_sha256": m.jd_sha256,
        "jd_path": m.jd_path, "company": m.company, "title": m.title, "variant": m.variant,
        "model": m.model, "claude_cmd": list(m.claude_cmd), "jd_quality": m.jd_quality,
        "created_at": m.created_at,
    }


def parse_lane_manifest(raw: object) -> LaneManifest:
    if not isinstance(raw, dict) or set(raw) != _LANE_MANIFEST_KEYS:
        raise LaneError("lane_manifest.json: unexpected or missing fields")
    if raw["schema_version"] != LANE_MANIFEST_SCHEMA:
        raise LaneError(f"lane_manifest.json: unsupported schema {raw['schema_version']!r}")
    if isinstance(raw["job_id"], bool) or not isinstance(raw["job_id"], int):
        raise LaneError("lane_manifest.json: job_id must be an integer")
    if not isinstance(raw["claude_cmd"], list) or not all(isinstance(x, str) for x in raw["claude_cmd"]):
        raise LaneError("lane_manifest.json: claude_cmd must be a list of strings")
    if raw["model"] is not None and not isinstance(raw["model"], str):
        raise LaneError("lane_manifest.json: model must be a string or null")
    for key in ("jd_sha256", "jd_path", "company", "title", "variant", "jd_quality", "created_at"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise LaneError(f"lane_manifest.json: {key} must be a nonempty string")
    return LaneManifest(
        schema_version=raw["schema_version"], job_id=raw["job_id"], jd_sha256=raw["jd_sha256"],
        jd_path=raw["jd_path"], company=raw["company"], title=raw["title"], variant=raw["variant"],
        model=raw["model"], claude_cmd=tuple(raw["claude_cmd"]), jd_quality=raw["jd_quality"],
        created_at=raw["created_at"],
    )


def _preflight_findings(profile_path: Path, template_path: Path, prompt_dir: Path) -> tuple[PreflightFinding, ...]:
    with tempfile.TemporaryDirectory(prefix="apply-now-preflight-") as workdir:
        report = run_preflight(Path(profile_path), Path(template_path), Path(prompt_dir), Path(workdir), skip_render=True)
    return report.findings


def _manifest_mismatch(existing: LaneManifest, *, jd_sha256: str, company: str, title: str, variant: str) -> str | None:
    if existing.jd_sha256 != jd_sha256:
        return "jd text differs from the JD this directory was created from"
    if (existing.company, existing.title) != (company, title):
        return "company/title differ from this directory's lane manifest"
    if existing.variant != variant:
        return f"variant {variant!r} differs from this directory's variant {existing.variant!r}"
    return None


def run_manual_application(
    jd_path: Path, *, company: str, title: str, variant: str,
    root: Path = APPLICATIONS_MANUAL_ROOT, model: str | None = None, suffix: str | None = None,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
) -> RunOutcome:
    started = _now()
    jd_path = Path(jd_path)
    jd_text = normalize_jd(jd_path.read_text(encoding="utf-8"))
    claude_cmd = build_claude_cmd(model)
    profile = load_profile(profile_path)
    if variant not in profile.base_variants:
        raise LaneError(f"unknown base variant {variant!r}; expected one of {sorted(profile.base_variants)}")

    job_id = lane_job_id(jd_text)
    jd_sha256 = _jd_sha256(jd_text)
    directory = lane_directory(Path(root), company, title, suffix)
    retry_prefix = (
        f"python -m scripts.tailor_now run --jd {jd_path} --company {company!r} --title {title!r} --variant {variant}"
        + (f" --suffix {suffix!r}" if suffix else "") + (f" --model {model}" if model else "")
    )

    manifest_path = directory / LANE_MANIFEST_NAME
    if manifest_path.exists():
        try:
            existing = parse_lane_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            return _prepare_failure(job_id, "lane_manifest_unreadable", str(exc), started)
        reason = _manifest_mismatch(existing, jd_sha256=jd_sha256, company=company, title=title, variant=variant)
        if reason is not None:
            return _prepare_failure(
                job_id, "lane_manifest_mismatch",
                f"{reason}; use --suffix for a different posting or remove {directory} by hand", started,
            )
        job_id = existing.job_id

    findings = _preflight_findings(profile_path, template_path, prompt_dir)
    if findings:
        joined = "; ".join(f"{f.surface}: {f.message}" for f in findings)
        return _prepare_failure(job_id, "preflight_failure", joined, started)

    s1_request = S1Request(job_id=job_id, company=company, title=title, jd_text=jd_text, jd_quality="ats")

    if not dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / JD_SNAPSHOT_NAME
        if not snapshot.exists():
            snapshot.write_text(jd_text, encoding="utf-8")
        if not manifest_path.exists():
            write_json_atomic(manifest_path, lane_manifest_to_dict(LaneManifest(
                schema_version=LANE_MANIFEST_SCHEMA, job_id=job_id, jd_sha256=jd_sha256, jd_path=str(jd_path),
                company=company, title=title, variant=variant, model=model, claude_cmd=claude_cmd,
                jd_quality="ats", created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )))
        log.info("apply-now lane: job %d (%s / %s) -> %s", job_id, company, title, directory)

    return run_stages(
        s1_request, variant, directory=directory, profile_path=profile_path, root=Path(root),
        template_path=template_path, banned_words_path=banned_words_path, taste_path=taste_path,
        trace_dir=trace_dir, prompt_dir=prompt_dir, stop_after=stop_after, only=only, dry_run=dry_run,
        claude_cmd=claude_cmd, reject_dir=directory / "rejected", retry_prefix=retry_prefix,
    )
```

Note on `dry_run`: `run_stages` in dry-run records PENDING stages without writing, so the root never gets created; the test asserts that.

- [ ] **Step 4: Add the gitignore entries**

Append to `.gitignore`:

```
# M8N-0: lane outputs embed the same identity PII as applications/; JD
# snapshots are third-party text. Same treatment as applications/.
applications_manual/
inbox/jd/
```

- [ ] **Step 5: Run the lane tests, then the suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_lane.py`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3`
Expected: only the pre-existing Firecrawl budget failure.

- [ ] **Step 6: Commit**

```bash
git add src/tailor/lane.py tests/tailor/test_lane.py .gitignore
git commit -m "feat(m8n0): add the file-fed Apply-Now lane composer"
```

---

### Task 6: Operator CLI (`scripts/tailor_now.py`)

**Files:**
- Create: `scripts/tailor_now.py`
- Test: `tests/test_tailor_now_cli.py`

**Interfaces:**
- Consumes: `run_manual_application`, `LaneError`, `parse_lane_manifest`, `APPLICATIONS_MANUAL_ROOT`, `LANE_MANIFEST_NAME` (Task 5); `run_preflight` (Task 1); `_discover_run_manifests`, `Stage`, `STAGE_ARTIFACT` (`src/tailor/pilot.py`); `db.get_readonly_connection`.
- Produces: `python -m scripts.tailor_now {preflight,run,status,export-jd}`; `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tailor_now_cli.py`:

```python
"""tailor_now CLI: a thin shell around src.tailor.lane and read-only DB
export. No model, no network; the DB is a seeded temp file."""
import json
from pathlib import Path

import pytest

import scripts.tailor_now as cli
from src.tailor.pilot import MANIFEST_SCHEMA, Stage, StageState, rebuild_manifest, manifest_to_dict, RunOutcome
from src.tailor.preflight import PreflightFinding, PreflightReport
from tests.fixtures.tailor.m8p7_chain import write_chain
from tests.tailor.test_pilot import _seed_db

JD = "Python " * 60


def test_export_jd_writes_text_and_prints_metadata(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD, base_variant="backend")
    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == JD
    printed = capsys.readouterr().out
    assert "Notion" in printed and "SWE" in printed and "backend" in printed and "ats" in printed


def test_export_jd_unknown_job_fails_closed(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "999", "--out", str(tmp_path / "x.txt")])
    assert rc == 1
    assert "999" in capsys.readouterr().err
    assert not (tmp_path / "x.txt").exists()


def test_run_success_prints_pdf_path(tmp_path, monkeypatch, capsys):
    directory = write_chain(tmp_path / "apps" / "acme-engineer", job_id=-1, fingerprint="fp", through="g3")
    (directory / "render_result.json").write_text(json.dumps({
        "job_id": -1, "alignment_fingerprint": "fp", "pdf_path": str(directory / "Himanshu_Jain_Resume.pdf")}),
        encoding="utf-8")
    manifest = rebuild_manifest(directory, job_id=-1, company="Acme", title="Engineer")

    def fake_run(jd_path, **kwargs):
        return RunOutcome(manifest=manifest, failed_stage=None, retry_command=None)

    monkeypatch.setattr(cli, "run_manual_application", fake_run)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "backend",
                   "--root", str(tmp_path / "apps")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "completed" in out and "Himanshu_Jain_Resume.pdf" in out


def test_run_failure_prints_stage_error_and_retry(tmp_path, monkeypatch, capsys):
    from src.tailor.pilot import _prepare_failure
    outcome = _prepare_failure(-1, "preflight_failure", "tailoring_s1.md: bad", "2026-09-01T00:00:00+00:00")
    monkeypatch.setattr(cli, "run_manual_application", lambda jd_path, **kwargs: outcome)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "backend"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "failed at stage prepare" in err and "tailoring_s1.md" in err


def test_run_lane_error_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    from src.tailor.lane import LaneError

    def boom(jd_path, **kwargs):
        raise LaneError("unknown base variant 'x'")

    monkeypatch.setattr(cli, "run_manual_application", boom)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "x"])
    assert rc == 1
    assert "unknown base variant" in capsys.readouterr().err


def test_preflight_reports_findings_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_preflight", lambda *a, **k: PreflightReport(
        findings=(PreflightFinding("prompt_invariants", "tailoring_s0.md", "shape"),), passed=False))
    assert cli.main(["preflight"]) == 1
    assert "tailoring_s0.md" in capsys.readouterr().out
    monkeypatch.setattr(cli, "run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    assert cli.main(["preflight"]) == 0


def test_status_lists_lane_applications(tmp_path, capsys):
    directory = write_chain(tmp_path / "apps" / "acme-engineer", job_id=-9, fingerprint="fp", through="s2")
    manifest = rebuild_manifest(directory, job_id=-9, company="Acme", title="Engineer")
    (directory / "run_manifest.json").write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")
    (directory / "lane_manifest.json").write_text(json.dumps({
        "schema_version": "m8n0.lane_manifest.v1", "job_id": -9, "jd_sha256": "a" * 64, "jd_path": "x",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": "sonnet",
        "claude_cmd": ["claude"], "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00"}), encoding="utf-8")
    rc = cli.main(["status", "--root", str(tmp_path / "apps")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme-engineer" in out and "sonnet" in out and "s2" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_tailor_now_cli.py`
Expected: FAIL at import with `ModuleNotFoundError: No module named 'scripts.tailor_now'`.

- [ ] **Step 3: Implement `scripts/tailor_now.py`**

```python
"""Apply-Now lane operator CLI (M8N-0): preflight, run, status, export-jd.
A thin argparse shell around src/tailor/lane.py; it parses, validates,
and hydrates nothing itself. The only DB access in this file is the
read-only export-jd helper used for the spec §11 benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    LANE_MANIFEST_NAME,
    LaneError,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import DEFAULT_PROMPT_DIR, Stage, StageState, _discover_run_manifests
from src.tailor.preflight import run_preflight

DEFAULT_PROFILE = Path("config/master_profile.yaml")
DEFAULT_TEMPLATE = Path("profile/template.tex")


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_now {label}: {exc}", file=sys.stderr)
    return 1


def cmd_preflight(args) -> int:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="apply-now-preflight-") as workdir:
        report = run_preflight(
            Path(args.profile or DEFAULT_PROFILE), Path(args.template or DEFAULT_TEMPLATE),
            Path(args.prompt_dir or DEFAULT_PROMPT_DIR), Path(workdir), skip_render=args.skip_render,
        )
    for finding in report.findings:
        print(f"{finding.check} [{finding.surface}]: {finding.message}")
    print(f"preflight: {'PASS' if report.passed else 'FAIL'} ({len(report.findings)} finding(s))")
    return 0 if report.passed else 1


def cmd_run(args) -> int:
    try:
        stop_after = Stage(args.stop_after) if args.stop_after else None
        only = Stage(args.only) if args.only else None
        outcome = run_manual_application(
            Path(args.jd), company=args.company, title=args.title, variant=args.variant,
            root=Path(args.root) if args.root else APPLICATIONS_MANUAL_ROOT,
            model=args.model, suffix=args.suffix,
            profile_path=Path(args.profile or DEFAULT_PROFILE),
            template_path=Path(args.template or DEFAULT_TEMPLATE),
            trace_dir=Path(args.trace_dir) if args.trace_dir else Path("data/traces"),
            prompt_dir=Path(args.prompt_dir or DEFAULT_PROMPT_DIR),
            stop_after=stop_after, only=only, dry_run=args.dry_run,
        )
    except LaneError as exc:
        return _fail("run", exc)
    except Exception as exc:  # noqa: BLE001 - operator CLI reports, never crashes
        return _fail("run", exc)

    if outcome.failed_stage is not None:
        record = next((r for r in outcome.manifest.stages if r.stage is outcome.failed_stage), None)
        error_text = record.error if record is not None else "unknown failure"
        print(f"tailor_now run: job {outcome.manifest.job_id} failed at stage "
              f"{outcome.failed_stage.value}: {error_text}", file=sys.stderr)
        if outcome.retry_command:
            print(f"retry with: {outcome.retry_command}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"[dry-run] job {outcome.manifest.job_id}: chain composes; no model call, no write.")
        return 0
    render_record = next((r for r in outcome.manifest.stages if r.stage is Stage.RENDER), None)
    pdf_path = ""
    if render_record is not None and render_record.artifact_path:
        try:
            pdf_path = json.loads(Path(render_record.artifact_path).read_text(encoding="utf-8")).get("pdf_path", "")
        except (OSError, ValueError):
            pdf_path = ""
    print(f"job {outcome.manifest.job_id}: completed ({outcome.manifest.total_model_calls} model calls)")
    if pdf_path:
        print(f"pdf: {pdf_path}")
    return 0


def cmd_status(args) -> int:
    root = Path(args.root) if args.root else APPLICATIONS_MANUAL_ROOT
    rows = []
    for directory, manifest in _discover_run_manifests(root):
        model = ""
        lane_path = directory / LANE_MANIFEST_NAME
        if lane_path.exists():
            try:
                model = parse_lane_manifest(json.loads(lane_path.read_text(encoding="utf-8"))).model or "default"
            except (OSError, ValueError):
                model = "?"
        reached = [r.stage.value for r in manifest.stages
                   if r.state in (StageState.COMPLETE, StageState.SKIPPED_COMPLETE)]
        last = reached[-1] if reached else "-"
        rows.append((directory.name, manifest.company, manifest.title, last, model, manifest.total_model_calls))
    for name, company, title, last, model, calls in sorted(rows):
        print(f"{name}  {company} — {title}  last_complete={last}  model={model}  calls={calls}")
    print(f"{len(rows)} application(s) under {root}")
    return 0


def cmd_export_jd(args) -> int:
    conn = None
    try:
        conn = db.get_readonly_connection(args.db)
        row = conn.execute(
            "SELECT id, company, title, jd_text, jd_quality, base_variant, status FROM jobs WHERE id = ?",
            (args.job_id,),
        ).fetchone()
        if row is None:
            raise LaneError(f"job {args.job_id}: no such row")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(row["jd_text"] or "", encoding="utf-8")
        print(f"wrote {out} ({len(row['jd_text'] or '')} chars)")
        print(f"company: {row['company']}")
        print(f"title: {row['title']}")
        print(f"base_variant: {row['base_variant']}")
        print(f"jd_quality: {row['jd_quality']}")
        print(f"status: {row['status']}")
        return 0
    except Exception as exc:  # noqa: BLE001
        return _fail("export-jd", exc)
    finally:
        if conn is not None:
            conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_now")
    sub = parser.add_subparsers(dest="command", required=True)
    stage_choices = [stage.value for stage in Stage]

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--profile")
    preflight.add_argument("--template")
    preflight.add_argument("--prompt-dir")
    preflight.add_argument("--skip-render", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    run = sub.add_parser("run")
    run.add_argument("--jd", required=True)
    run.add_argument("--company", required=True)
    run.add_argument("--title", required=True)
    run.add_argument("--variant", required=True, choices=["backend", "ml"])
    run.add_argument("--model")
    run.add_argument("--suffix")
    run.add_argument("--root")
    run.add_argument("--profile")
    run.add_argument("--template")
    run.add_argument("--prompt-dir")
    run.add_argument("--trace-dir")
    run.add_argument("--stop-after", choices=stage_choices)
    run.add_argument("--only", choices=stage_choices)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    status.add_argument("--root")
    status.set_defaults(func=cmd_status)

    export = sub.add_parser("export-jd")
    export.add_argument("--db", default="data/jobs.db")
    export.add_argument("--job-id", type=int, required=True)
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export_jd)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

The SQL string in `cmd_export_jd` violates the "no SQL outside `src/db.py`" rule. Move it: add to `src/db.py`

```python
def job_row_for_export(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    """Read-only single-row read for the Apply-Now benchmark export (M8N-0)."""
    return conn.execute(
        "SELECT id, company, title, jd_text, jd_quality, base_variant, status FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
```

and call `db.job_row_for_export(conn, args.job_id)` from the CLI instead of the inline query. Add a test in `tests/test_db.py`:

```python
def test_job_row_for_export_returns_row_or_none(tmp_path):
    from tests.tailor.test_pilot import _seed_db
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text="Python " * 60)
    conn = db.get_readonly_connection(db_path)
    try:
        row = db.job_row_for_export(conn, 225)
        assert row["company"] == "Notion" and row["jd_quality"] == "ats"
        assert db.job_row_for_export(conn, 999) is None
    finally:
        conn.close()
```

(Confirm `tests/test_db.py` imports `db` as `from src import db`; match its style.)

- [ ] **Step 4: Run the CLI tests and the suite**

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_tailor_now_cli.py tests/test_db.py`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3`
Expected: only the pre-existing Firecrawl budget failure.

- [ ] **Step 5: Smoke the real preflight and a dry run (no model call)**

Run:
```bash
.venv/bin/python -m scripts.tailor_now preflight
```
Expected: `preflight: PASS (0 finding(s))` after both variants render (needs pdflatex; takes a few seconds).

Run:
```bash
mkdir -p inbox/jd && .venv/bin/python -m scripts.tailor_now export-jd --job-id 225 --out inbox/jd/225.txt
```
Expected: prints `company: Notion`, `title: Software Engineer – Early Career - AI`, `base_variant: backend`, `jd_quality: ats`.

Run:
```bash
.venv/bin/python -m scripts.tailor_now run --jd inbox/jd/225.txt --company "Notion" --title "Software Engineer – Early Career - AI" --variant backend --dry-run
```
Expected: `[dry-run] job -<n>: chain composes; no model call, no write.` and no `applications_manual/` directory created.

- [ ] **Step 6: Commit**

```bash
git add scripts/tailor_now.py tests/test_tailor_now_cli.py src/db.py tests/test_db.py
git commit -m "feat(m8n0): add the tailor_now operator CLI with read-only JD export"
```

---

### Task 7: Documentation, then the user-supervised benchmark and closeout

**Files:**
- Modify: `docs/ARCHITECTURE.md` (§11), `docs/ROADMAP.md` (Phase 3 M8N paragraph), `docs/IMPLEMENTATION_PLAN.md` (M8N section status), `CLAUDE.md` and `AGENTS.md` (Commands), `docs/DECISIONS.md` (closeout entry)
- Create (gitignored, not committed): `inbox/jd/225.txt`, `inbox/jd/119.txt`, `inbox/jd/211.txt`, `applications_manual/...`
- Create (committed): `tests/fixtures/tailor/traces/m8n0_*.txt` recorded with `scripts/record_trace_fixture.py`

**Interfaces:**
- Consumes: the CLI from Task 6.

- [ ] **Step 1: Documentation edits**

`docs/ARCHITECTURE.md` §11, add after the "Agentic source scout" bullet:

```
- **Apply-Now tailoring lane** (M8N, 2026-09-01): `scripts/tailor_now.py` is a file-fed entry
  to the same S1→S0→S2→S3→G1→G2→RENDER+L7→G3 chain the DB-fed pilot runs
  (`src/tailor/pilot.run_stages`). Input is a pasted JD plus company, title, and base
  variant; job ids are negative and content-derived; outputs land under gitignored
  `applications_manual/`. The lane never reads or writes `data/jobs.db` for tailoring
  (`export-jd` is a read-only benchmark helper). Design:
  `docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md`.
```

`CLAUDE.md` and `AGENTS.md` Commands, add:

```
- Apply-Now lane: `python -m scripts.tailor_now run --jd inbox/jd/<name>.txt --company "<Co>"
  --title "<Title>" --variant {backend,ml} [--model NAME] [--suffix TEXT]`; `preflight`,
  `status`, `export-jd --job-id N --out PATH` (read-only)
```

`docs/ROADMAP.md`: in the M8N paragraph, change "design approved 2026-09-01, not implemented" to "M8N-0 COMPLETE <date>; M8N-1/M8N-2 not started" and add one sentence with the benchmark outcome from Step 3.

`docs/IMPLEMENTATION_PLAN.md`: in the M8N section, change the Status line to "M8N-0 COMPLETE <date> (commits listed below); M8N-1/M8N-2 NOT STARTED" and list the task commits.

- [ ] **Step 2: Commit the docs before the live run**

```bash
git add docs/ARCHITECTURE.md CLAUDE.md AGENTS.md
git commit -m "docs(m8n0): document the Apply-Now lane entry point and commands"
```

- [ ] **Step 3: User-supervised benchmark (live model calls; spec §11)**

Only with the user present. For each job, export then run:

```bash
.venv/bin/python -m scripts.tailor_now export-jd --job-id 225 --out inbox/jd/225.txt
.venv/bin/python -m scripts.tailor_now export-jd --job-id 119 --out inbox/jd/119.txt
.venv/bin/python -m scripts.tailor_now export-jd --job-id 211 --out inbox/jd/211.txt
```

Then, using the company, title, and base_variant each export printed:

```bash
.venv/bin/python -m scripts.tailor_now run --jd inbox/jd/225.txt --company "Notion" --title "Software Engineer – Early Career - AI" --variant backend
```

Repeat for 119 (`--variant ml`) and 211 (`--variant backend`). On a failed stage, read the bounded error and the trace under `data/traces/<date>/`, then use the printed retry command. Do not edit prompts to get past a failure; report it.

Collect, per job, from the artifacts under `applications_manual/`:

| Job | coverage covered/total (`s2_response.json`) | G2 C1–C5 + verdict (`g2_bundle.json`) | L7 violations (`render_result.json`) | pages | model calls (`run_manifest.json`) | rejected/ present |
|---|---|---|---|---|---|---|

Compare 225 and 119 with the pilot's `applications/*/s2_response.json` and `g2_bundle.json`. Pass conditions are in spec §11 (M8N-0 row).

- [ ] **Step 4: Record replay fixtures from the live traces**

For one accepted S1, S0, S2, S3, and G2 trace from the 225 run, extract fixtures (the recorder refuses any output containing identity values):

```bash
.venv/bin/python -m scripts.record_trace_fixture data/traces/<date>/<s1 trace>.json m8n0_s1_notion_accepted
```

Repeat for s0, s2, s3, g2 with names `m8n0_<stage>_notion_accepted`. If a run produced a rejected response (parse or semantic), record it as `m8n0_<stage>_<reason>_rejected` too. Add one replay test per recorded fixture to `tests/tailor/test_trace_replay.py` following that file's existing pattern (parse the fixture through the stage's parser against the recorded request context and assert accepted or the exact rejection class).

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_trace_replay.py`
Expected: PASS.

- [ ] **Step 5: Walk the user through the review packets**

Open each `applications_manual/<dir>/review.md` and the PDF with the user. Time the 225 review. Capture the decision (approve / reject with reason) in the closeout entry. Do not fill `feedback_form.yaml` on the user's behalf.

- [ ] **Step 6: Verify the DB is untouched and the suite is green**

Run:
```bash
shasum -a 256 data/jobs.db; cat /tmp/m8n0-db-before.txt
```
Expected: identical digests.

Run: `.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3`
Expected: only the pre-existing Firecrawl budget failure.

- [ ] **Step 7: Closeout docs and commit**

Append to `docs/DECISIONS.md`:

```
## <date> — M8N-0 Apply-Now lane closeout

Commits: <list>. Benchmark (spec §11, M8N-0 row): <table from Step 3, one line per job>.
User review of job 225: <approved / rejected: reason>, <n> seconds. Replay fixtures recorded:
<names>. `data/jobs.db` SHA-256 unchanged at <digest>. M8N-1 (screen brief, company view,
hiring-manager read) and M8N-2 not started.
```

Update `docs/ROADMAP.md` and `docs/IMPLEMENTATION_PLAN.md` per Step 1, then:

```bash
git add docs/DECISIONS.md docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md tests/fixtures/tailor/traces tests/tailor/test_trace_replay.py
git commit -m "docs(m8n0): close the Apply-Now lane milestone with benchmark results"
```

Then follow `superpowers:finishing-a-development-branch` to merge the worktree branch into `main`. Do not push (origin is public; see the user's standing instruction).

---

## Self-review against the spec

- §7.1 inputs → Task 5 (`normalize_jd`, bounds, `--variant` required, `--model`, `--suffix`) and Task 6 (flags).
- §7.2 CLI → Task 6 (`preflight`, `run`, `status`, `export-jd`).
- §7.3 extraction → Task 4 (`run_stages`, `_prepare_failure`, pilot unchanged, `directory` passed to render and packet).
- §7.4 composer → Task 5 (steps 1–7, `lane_manifest.json` fields exact).
- §7.5 preflight → Task 1 (cherry-pick), Task 2 (prompt fixes so it passes), Task 5 (`_preflight_findings` gate, spy test).
- §7.6 model threading → Task 4 (spy test), Task 5 (`build_claude_cmd`).
- §7.7 job identity → Task 5 (`lane_job_id`), Task 4 (negative-id round-trip test).
- §7.8 rejected renders → Task 3, exercised in Task 5's L7 test.
- §7.9 idempotency → Task 5 (zero-call rerun, mismatch refusal, dry-run).
- §6 boundary → Task 5 `.gitignore`; `export-jd` is the only DB read, via `db.job_row_for_export` (Task 6).
- §11 bar → Task 7 Step 3 table; §12 tests → Tasks 3–6 and Task 7 Step 4 fixtures; §14 docs → Task 7.
- N6 file move → Task 2 Step 6. N12 approvals → Task 2 Steps 0 and 7.
