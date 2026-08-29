# M8V-1 — Verification Strategy Repair

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop discovering deterministic defects by spending model calls. Replace
self-authored fixtures with recorded reality, and run every model-free check before the
first model call.

**Family letter:** `V` = verification, following the `M9F` / `M8X` precedent of a distinct
letter for a cross-cutting concern. M8V-1 repairs the verification strategy behind
M8P-1..M8P-7; it adds no pipeline stage.

**Date:** 2026-08-27 · **Predecessor:** `c4b7b10`, suite 1,638 passed / 1 deselected

---

## 1. The problem this fixes

Eight live failures were found by running the pipeline. Seven were in **our** artifacts:

| # | Failure | Owner | Model-free detectable? |
|---|---|---|---|
| 1 | Fenced JSON rejected | prompt | yes - replay a real trace |
| 2 | JD injected twice | code | yes - prompt invariant |
| 3 | `do_not_claim` term in a flagship bullet | profile | **yes - set intersection** |
| 4 | Two pages + heading bleed | profile | **yes - one `pdflatex` run** |
| 5 | Curly apostrophe rejected | prompt | yes - replay a real trace |
| 6 | `sepsis_b5` "did not survive PDF extraction" | template | **yes - render + L7** |
| 7 | Three emphasis false positives | checker | **yes - render + L7** |
| 8 | `scikit-learn` length growth | model | no - guard worked correctly |

Four were free to detect and were instead found after 4-5 model calls each.

**Root cause.** Every fixture in the tailoring and render layers was authored by the same
process that authored the code. `tests/tailor/conftest.py` builds synthetic requests; the
G2 tests feed hand-written JSON to a parser written beside them; L7 runs against four
hand-compiled PDFs of short, non-wrapping text. So 1,638 passing tests prove
self-consistency, not correspondence with what a real model emits or what a real resume
PDF looks like. The verifier and the verified share an author, and therefore share blind
spots - which is why `check_emphasis_rendered` cannot see wrapped bold runs and
`check_bullets_survive` cannot see an interleaved date range.

The ingestion layer solved this in M1 with `scripts/record_fixture.py`, which records real
responses. The tailoring layer never adopted the pattern.

## 2. Non-goals

No new pipeline stage. No change to G1/G2/S3 semantics. No change to
`config/master_profile.yaml`. No model call from any test. No new dependency. No DB write.
No pilot run. This milestone makes existing guarantees checkable; it does not add
guarantees.

## Global Constraints

- Read `AGENTS.md`, `docs/TAILORING_METHODOLOGY.md` section 4, and this document first.
- **Never `git push`.** `origin` is public.
- No new dependency. No SQLite write. No model call anywhere, including tests.
- Do not edit `config/master_profile.yaml`, `profile/template.tex`, `src/tailor/s3.py`,
  `g1.py`, `g2.py`, or any stage pipeline. M8V-1 adds checks and fixtures; it does not
  change contracts.
- Baseline DB SHA-256: `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`
- Do not edit `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md`;
  leave deltas for the integrator.
- TDD per task: focused RED, minimal GREEN, regression, commit.

---

### Task 1: Model-free preflight

**Files:** create `src/tailor/preflight.py`, `scripts/tailor_preflight.py`,
`tests/tailor/test_preflight.py`.

**Produces:**

```python
@dataclass(frozen=True)
class PreflightFinding:
    check: str          # "profile_do_not_claim" | "render_l7" | "prompt_invariants"
    surface: str
    message: str

@dataclass(frozen=True)
class PreflightReport:
    findings: tuple[PreflightFinding, ...]
    passed: bool

def check_profile_do_not_claim(profile) -> tuple[PreflightFinding, ...]: ...
def check_prompt_invariants(prompt_dir: Path) -> tuple[PreflightFinding, ...]: ...
def check_variants_render(profile, template: Path, workdir: Path) -> tuple[PreflightFinding, ...]: ...
def run_preflight(profile_path: Path, template: Path, prompt_dir: Path,
                  workdir: Path, *, skip_render: bool = False) -> PreflightReport: ...
```

`check_profile_do_not_claim` must scan **every rendered surface**, not the two G1 covers.
Failure #3 escaped because L6 inspects only bullet plain text and the skills mapping,
while `tech_line` and `display_title` also render:

```python
SURFACES = ("bullet_phrasings", "skills", "tech_line", "display_title", "project_name")
```

`check_prompt_invariants`, per prompt in `docs/prompts/`: zero lines beginning with a
triple backtick; its substitution marker appearing **exactly once** (failure #2 was a
marker appearing twice against a `.replace()` that replaces all); and the documented
response shape parsing through that stage's own parser.

- [ ] **Step 1: Write the failing tests**

```python
def test_do_not_claim_in_tech_line_is_found(tmp_profile_with_dnc_in_tech_line):
    findings = check_profile_do_not_claim(tmp_profile_with_dnc_in_tech_line)
    assert any(f.surface == "tech_line" for f in findings)

def test_do_not_claim_in_display_title_is_found(tmp_profile_with_dnc_in_title):
    assert any(f.surface == "display_title" for f in check_profile_do_not_claim(tmp_profile_with_dnc_in_title))

def test_clean_real_profile_passes(real_profile):
    assert check_profile_do_not_claim(real_profile) == ()

def test_duplicate_marker_is_found(tmp_prompt_dir_with_duplicate_marker):
    findings = check_prompt_invariants(tmp_prompt_dir_with_duplicate_marker)
    assert any("exactly once" in f.message for f in findings)

def test_fenced_prompt_is_found(tmp_prompt_dir_with_fence):
    assert any("fence" in f.message for f in check_prompt_invariants(tmp_prompt_dir_with_fence))

def test_real_prompts_pass_invariants():
    assert check_prompt_invariants(Path("docs/prompts")) == ()

def test_preflight_makes_no_model_call():
    src = Path("src/tailor/preflight.py").read_text()
    assert "src.tailor.invoke" not in src and "src.llm_trace" not in src

def test_skip_render_omits_the_render_check(tmp_path):
    report = run_preflight(Path("config/master_profile.yaml"), Path("profile/template.tex"),
                           Path("docs/prompts"), tmp_path, skip_render=True)
    assert not any(f.check == "render_l7" for f in report.findings)
```

Render tests are gated with `@pytest.mark.skipif(shutil.which("pdflatex") is None, ...)`,
matching the precedent in `tests/render/test_l7_oracle.py`.

- [ ] **Step 2: Run RED** - `pytest tests/tailor/test_preflight.py -q`; expect
  `ModuleNotFoundError`.
- [ ] **Step 3: Implement.** `run_preflight` aggregates the three checks and returns
  `passed = not findings`. The CLI prints each finding and exits non-zero on failure.
- [ ] **Step 4: Run it against the live repo.** It must pass today - failures #2, #3, #4,
  #6, #7 are all fixed. If it finds something, that is a real defect: report it.
- [ ] **Step 5: Commit** - `feat(m8v): add model-free tailoring preflight`

---

### Task 2: Replay real model output as parser fixtures

**Files:** create `scripts/record_trace_fixture.py`,
`tests/fixtures/tailor/traces/*.txt`, `tests/tailor/test_trace_replay.py`.

The I11 traces under `data/traces/` hold raw stdout from real invocations, including the
two that broke us: a fenced S1 response and one with a curly apostrophe. `data/` is
gitignored, so the traces must be **extracted** into committed fixtures.

**Produces:** `record_trace_fixture.py <trace.json> <name>` writing
`tests/fixtures/tailor/traces/<name>.txt` containing only `raw_output`.

**Privacy gate - mandatory.** Traces embed the JD and profile content. The recorder must
refuse to write a fixture containing the user's phone, email, or LinkedIn/GitHub URLs
from `config/master_profile.yaml` `identity`, and must print what it refused. A test
asserts no committed fixture contains any identity value.

- [ ] **Step 1: Write the failing tests**

```python
def test_recorder_refuses_identity_leakage(trace_with_phone, tmp_path):
    with pytest.raises(ValueError, match="identity"):
        record_trace_fixture(trace_with_phone, tmp_path / "leaky.txt")

def test_no_committed_fixture_contains_identity():
    from src.profile import load_profile
    values = [v for v in load_profile("config/master_profile.yaml").identity.values() if v]
    for f in Path("tests/fixtures/tailor/traces").glob("*.txt"):
        text = f.read_text()
        for v in values:
            assert v not in text, f"{f.name} leaks {v!r}"

def test_recorded_fenced_response_is_rejected_by_the_parser(s1_request_fixture):
    raw = (FIXTURES / "s1_fenced_rejected.txt").read_text()
    with pytest.raises(S1ParseError):
        parse_s1_response(raw, s1_request_fixture.jd_text)

def test_recorded_curly_apostrophe_response_is_rejected(s1_request_fixture):
    raw = (FIXTURES / "s1_curly_apostrophe_rejected.txt").read_text()
    with pytest.raises(S1SemanticError, match="exact substring"):
        parse_s1_response(raw, s1_request_fixture.jd_text)

def test_recorded_valid_responses_parse(stage, raw_fixture, request_fixture):
    """Every recorded accepted response must still parse. This is the regression
    guard that self-authored fixtures could never provide."""
    assert parse_for(stage)(raw_fixture, request_fixture) is not None
```

- [ ] **Step 2: Run RED** - expect missing module and missing fixtures.
- [ ] **Step 3: Record the fixtures** from `data/traces/` - at minimum: the fenced S1
  rejection, the curly-apostrophe S1 rejection, one accepted S1, one accepted S0, one
  accepted S2, one accepted S3, one accepted G2, and the `scikit-learn` S3 response that
  failed the length guard.
- [ ] **Step 4: Implement and run.**
- [ ] **Step 5: Commit** - `test(m8v): replay recorded model output in parser tests`

---

### Task 3: Validate L7 against a real rendered resume

**Files:** modify `src/render/l7.py` (additive), create
`tests/fixtures/render/real_resume_backend.pdf`, modify
`tests/render/test_l7_tailored.py`.

Two confirmed checker defects, both invisible to the existing four toy fixtures because
their text does not wrap:

**3a - `check_emphasis_rendered` does not stitch bold runs across a line wrap.** A bold
phrase split by a wrap becomes two `bold_run_texts` entries on two `RenderedLine`s, and
the substring test fails. Fix: concatenate consecutive bold runs across adjacent lines
within the same entry before matching. Confirmed false positives:
`am_b01_dlq_consolidation`, `cm_b1` (x2).

**3b - `check_bullets_survive` breaks when a date range interleaves.** `sepsis_b5`'s two
wrapped physical lines are separated in extraction order by the project's
`Feb. 2026 - Apr. 2026`, so the normalized bullet text is not a contiguous substring.
Fix: match against text with intervening right-aligned date-range lines removed, or match
per-line with gaps allowed. **Do not** simply loosen to token-subset matching - that
would stop detecting genuine truncation, which is the check's entire purpose.

**Add `check_no_do_not_claim_in_pdf`.** Belt-and-braces against failure #3 at the far end:
no `do_not_claim` term may appear in the extracted PDF text, regardless of which surface
put it there.

- [ ] **Step 1: Record the fixture** - render the real backend variant and commit it via
  `scripts/record_render_fixture.py` as `real_resume_backend`. This fixture has wrapped
  bullets, interleaved dates, and split bold runs - the conditions the toy fixtures
  cannot produce.
- [ ] **Step 2: Write the failing tests**

```python
def test_emphasis_survives_a_line_wrap(real_resume_doc):
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert check_emphasis_rendered(real_resume_doc, pages) == []

def test_bullet_survives_an_interleaved_date_range(real_resume_doc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_bullets_survive(real_resume_doc, parsed) == []

def test_genuine_truncation_is_still_detected(doc_claiming_absent_tail):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_bullets_survive(doc_claiming_absent_tail, parsed)

def test_genuinely_unbolded_text_is_still_detected(doc_claiming_false_emphasis):
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert check_emphasis_rendered(doc_claiming_false_emphasis, pages)

def test_do_not_claim_term_in_pdf_is_detected(doc_with_dnc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_no_do_not_claim_in_pdf(doc_with_dnc, parsed)

def test_real_resume_passes_the_full_tailored_l7(real_resume_doc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert run_l7_tailored(real_resume_doc, parsed, pages, frozenset()) == []
```

The two "still detected" tests are the important ones: they prove the fixes narrow false
positives without blinding the checks.

- [ ] **Step 3: Run RED**, **Step 4: Implement**, **Step 5: Regression** -
  `pytest tests/render -q` must stay green.
- [ ] **Step 6: Commit** - `fix(m8v): validate L7 against a real wrapped resume`

---

### Task 4: Shakedown mode

**Files:** modify `src/tailor/pilot.py`, `scripts/tailor_pilot.py`, `tests/tailor/test_pilot.py`.

M8P-7 assumed a working pipeline with a human reviewing output. It is being used as a
debugger, which it is not shaped for. Separate the two.

**Produces:** `tailor_pilot shakedown --job-id ID` which runs `run_preflight` first,
refuses to make any model call if preflight fails, and on stage failure prints the stage,
outcome kind, bounded diagnostic, trace path, and retry command - framed as a bug report
rather than a pilot result. It writes under `--root` like any run, so a later real pilot
run resumes completed stages at zero cost.

Also: `run_application` calls `run_preflight(skip_render=True)` before its first model
call and fails closed on findings. Render is skipped there because a full render per run
is wasteful; `shakedown` runs the complete preflight including render.

- [ ] **Step 1: Write the failing tests**

```python
def test_shakedown_refuses_to_call_the_model_when_preflight_fails(tmp_repo, broken_profile, spy):
    outcome = shakedown(225, profile_path=broken_profile, ...)
    assert spy.call_count == 0
    assert outcome.preflight_findings

def test_run_application_fails_closed_on_preflight(tmp_repo, broken_profile, spy):
    result = run_application(225, profile_path=broken_profile, ...)
    assert spy.call_count == 0
    assert result.failed_stage is Stage.PREPARE

def test_shakedown_artifacts_are_reusable_by_a_later_run(tmp_repo, mock_all_pass, spy):
    shakedown(225, root=tmp_repo.root, ...)
    spy.reset()
    run_application(225, root=tmp_repo.root, ...)
    assert spy.call_count == 0
```

- [ ] **Step 2: RED**, **Step 3: Implement**, **Step 4: Full suite**, **Step 5: Commit** -
  `feat(m8v): add shakedown mode gated on preflight`

---

## Acceptance criteria

- `tailor_preflight` catches, with zero model calls, a `do_not_claim` term on any of five
  rendered surfaces; a duplicated or missing prompt marker; a fenced prompt; a documented
  response shape that its own parser rejects; and a variant that renders to two pages or
  fails L7.
- Recorded real model output is committed as fixtures and replayed by the parser tests,
  including both responses that broke S1 live. No fixture contains any identity value.
- `check_emphasis_rendered` and `check_bullets_survive` pass on a real wrapped resume
  **and** still detect genuine unbolded text and genuine truncation.
- `check_no_do_not_claim_in_pdf` exists and is in `run_l7_tailored`.
- `run_application` cannot make a model call when preflight fails.
- No test invokes a model or the network; `pdflatex`-dependent tests are `skipif`-gated.
- Full suite green (>=1,638 + new); `git diff --check` clean; DB SHA-256 unchanged.

## Verification

```bash
.venv/bin/python -m scripts.tailor_preflight --profile config/master_profile.yaml \
  --template profile/template.tex --prompts docs/prompts
.venv/bin/python -m pytest -q
git diff --check && git status --short && shasum -a 256 data/jobs.db
```

## Stop conditions

- Preflight finds a defect in the current repo -> report it; do not fix it inside M8V-1.
- A recorded trace cannot be de-identified -> do not commit it; use a different trace.
- A fix to 3a or 3b would blind the check to genuine truncation or genuine missing bold ->
  stop and ask. Narrowing false positives is the goal; loosening the check is not.
- Any task appears to need a contract change in `s3.py`, `g1.py`, or `g2.py` -> stop.

## Documentation deltas (for the integrator)

`ROADMAP.md` / `IMPLEMENTATION_PLAN.md`: record M8V-1. `DECISIONS.md`: record that
tailoring fixtures are now recorded from real invocations rather than authored, following
the `scripts/record_fixture.py` precedent set in M1; that preflight gates every model
call; and that L7's emphasis and survival checks were narrowed against a real wrapped
resume without weakening truncation detection.
