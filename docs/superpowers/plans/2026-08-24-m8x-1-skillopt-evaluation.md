# M8X-1 Microsoft SkillOpt Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine, with evidence, whether Microsoft SkillOpt can improve this project's tailoring prompts — without letting it touch the deterministic pipeline, the approved dependency list, or the user's data before that is justified.

**Architecture:** SkillOpt lives entirely outside `src/`, in a gitignored, separately-virtualenv'd `tools/skillopt/` working area. Its adapter shells out to this repository's existing CLIs and never imports `src/`. Candidate prompts are versioned proposal artifacts; promotion is a single reviewed commit behind a nine-condition gate.

**Tech Stack:** Documentation first. Later phases add an isolated Python 3.10+ virtualenv containing `skillopt` (MIT, PyPI) — never the project venv, never `pyproject.toml`.

**Spec:** `docs/superpowers/specs/2026-08-24-m8x-1-skillopt-evaluation-design.md`

**Can implementation start before M8P-3R merges?** Task 1 (documentation) yes, immediately. Tasks 2–3 require user approval. Tasks 4–7 require M8P-8 complete and at least 60 labelled applications.

## Global Constraints

- **Do not add `skillopt` (or anything else) to `pyproject.toml`.** Ever, in this milestone.
- **Do not clone, install, or execute SkillOpt before Task 3, and not then without explicit user approval.**
- `pytest -q` must pass on a machine where SkillOpt is not installed, at every point in this milestone. A test asserts no module under `src/`, `scripts/`, or `tests/` imports `skillopt`.
- **Never edit** any file under `docs/prompts/` or `config/` in Tasks 1–6. Task 7 (promotion) edits exactly one prompt file, in one commit, only after the §5 gate passes.
- **Never write** to `data/jobs.db`. Never import `src/` from adapter code.
- `tools/` is gitignored in its entirety before any SkillOpt file is written there.
- Real resume or feedback data is sent to a model provider only after a user decision recorded in `docs/DECISIONS.md` that names the provider.
- Every experiment enforces an agreed model-call budget and reports actual usage.
- Sourced facts and architectural inference stay visibly separated in every document this milestone produces.
- Baseline DB SHA-256: `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- Do not edit `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md` except in Tasks 3, 5, and 7 where explicitly instructed.

## Predecessor contracts and blockers

- **Blocker B1 (Tasks 4–7):** M8P-8 complete, with a recorded cost report and ≥ 60 labelled applications in `data/feedback/`. Thirty is enough to prove the adapter works; it is not enough to promote a prompt.
- **Blocker B2 (Task 3+):** explicit user approval to install a third-party package into an isolated environment.
- **Blocker B3 (Task 5+):** a recorded user decision permitting real resume/JD/feedback content to reach the chosen model provider.
- **Blocker B4 (Task 7):** all nine §5 gate conditions met and recorded.

## Target files

Create: `docs/superpowers/reports/2026-08-24-skillopt-feasibility.md`,
`docs/superpowers/reports/2026-08-24-skillopt-pinning.md`,
`docs/superpowers/reports/skillopt-baseline.md`,
`docs/superpowers/reports/skillopt-evaluation.md`,
`tests/test_no_skillopt_dependency.py`.

Create under gitignored `tools/skillopt/` (Task 3+): the virtualenv, the env package,
and run artifacts. None of it is committed.

Modify: `.gitignore` (Task 3, add `tools/`), and exactly one file under
`docs/prompts/` (Task 7 only).

## Privacy boundaries

Rollout trajectories would contain JD text and the user's resume bullets. All of it
stays under gitignored `tools/skillopt/`. The adapter reuses the existing
privacy-minimised stage projections, so the optimizer sees no `identity`, `education`,
`evidence`, `defense`, `interview_risk`, `metric_ledger`, or `known_gaps`. Task 3 runs
on synthetic data only.

---

### Task 1: Feasibility and compatibility memo (documentation only)

**Files:**
- Create: `docs/superpowers/reports/2026-08-24-skillopt-feasibility.md`
- Create: `tests/test_no_skillopt_dependency.py`

**Interfaces:**
- Consumes: the published Microsoft material cited in the design §2, and the repository's own contracts.
- Produces: a memo answering the design's eight §6 questions.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_no_skillopt_dependency.py
"""M8X-1 must never make the project depend on SkillOpt."""
from pathlib import Path

import pytest

ROOTS = ("src", "scripts", "tests")


def test_pyproject_does_not_declare_skillopt():
    assert "skillopt" not in Path("pyproject.toml").read_text(encoding="utf-8").casefold()


@pytest.mark.parametrize("root", ROOTS)
def test_no_module_imports_skillopt(root):
    offenders = [
        str(path)
        for path in Path(root).rglob("*.py")
        if "import skillopt" in path.read_text(encoding="utf-8")
        or "from skillopt" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_tools_directory_is_not_committed():
    """tools/ holds a third-party venv and trajectories containing resume content."""
    tracked = Path(".gitignore").read_text(encoding="utf-8")
    if Path("tools").exists():
        assert "tools/" in tracked
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_no_skillopt_dependency.py -q`

Expected: the first two tests PASS immediately (nothing depends on SkillOpt today) and
the third passes vacuously because `tools/` does not exist. This test is a **guard**,
not a red-then-green cycle — its job is to fail later if someone adds the dependency.
Confirm it is collected and green before continuing.

- [ ] **Step 3: Write the memo**

`docs/superpowers/reports/2026-08-24-skillopt-feasibility.md` with these sections:

1. **Sourced facts** — copy the design's §2 verbatim, with the four Microsoft URLs.
2. **Answers to the eight §6 questions** — each answered from published material or
   from reading the public repository, or explicitly recorded as `UNRESOLVED — needs
   the repository read / needs a maintainer answer`. Do not guess.
3. **Mapping** — which prompt file is the highest-value target and why (S3 first, G2
   second, per the design §3.1).
4. **The reward problem** — restate the design §3.2 composite-reward argument in this
   project's concrete terms, naming the exact `FeedbackRecord` fields.
5. **Recommendation** — proceed to Task 2, or stop, with the reason.

Every inference in the memo is prefixed `INFERENCE:` so a later reader can separate it
from sourced fact.

- [ ] **Step 4: Verify**

```bash
.venv/bin/python -m pytest -q
git diff --check
git status --short
shasum -a 256 data/jobs.db
```

Expected: full suite green, no source change, checksum unchanged.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/reports/2026-08-24-skillopt-feasibility.md tests/test_no_skillopt_dependency.py
git commit -m "docs(m8): assess SkillOpt feasibility for tailoring prompts"
```

---

### Task 2: Pin the upstream version and specify the adapter boundary (still no install)

**Files:**
- Create: `docs/superpowers/reports/2026-08-24-skillopt-pinning.md`

**Blocker:** the user accepted Task 1's recommendation.

- [ ] **Step 1: Record the pin**

Read `https://github.com/microsoft/SkillOpt/releases` and record in the document: the
exact release tag to be used, its commit SHA, its publication date, the declared
Python floor, and the license. Do not clone. Do not install.

- [ ] **Step 2: Specify the adapter**

Document, without writing code:

- the directory layout from the design §3.3;
- the adapter's exact subprocess invocation
  (`python -m scripts.tailor_pilot run --job-id <id> --only s3 --prompt-template <candidate>`);
- the reward function: `0.0` if static G1 fails, L7 fails, or any
  `unsupported_claims` entry exists; otherwise a weighted combination of
  `would_submit`, `visual_quality`, `company_alignment`, and the inverse edit-budget
  ratio, with the exact weights written down;
- the frozen split format: a JSON file naming train and validation job ids plus the
  feedback record revision used as the label for each;
- the call-budget enforcement point and the abort behaviour when it is exceeded;
- the six reproducibility fields from the design §3.6.

- [ ] **Step 3: Verify and commit**

```bash
.venv/bin/python -m pytest -q
git status --short
```

```bash
git add docs/superpowers/reports/2026-08-24-skillopt-pinning.md
git commit -m "docs(m8): pin SkillOpt version and specify its adapter boundary"
```

---

### Task 3: Isolated synthetic-data mechanics experiment

**Files:**
- Modify: `.gitignore` (add `tools/`)
- Create under gitignored `tools/skillopt/`: the venv, the env package, and run artifacts (not committed)

**Blockers:** Tasks 1–2 accepted **and** explicit user approval to install.

- [ ] **Step 1: Gitignore the working area before creating it**

```bash
printf 'tools/\n' >> .gitignore
git add .gitignore && git commit -m "chore(m8): ignore the isolated SkillOpt working area"
```

- [ ] **Step 2: Create the isolated environment**

```bash
python3 -m venv tools/skillopt/.venv
tools/skillopt/.venv/bin/pip install "skillopt==<PINNED VERSION FROM TASK 2>"
tools/skillopt/.venv/bin/pip freeze > tools/skillopt/requirements.lock
```

Then prove the project is unaffected:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -c "import importlib.util; assert importlib.util.find_spec('skillopt') is None; print('project venv is clean')"
git status --short
```

Expected: full suite green, `skillopt` absent from the project venv, working tree clean
apart from nothing (everything new is under gitignored `tools/`).

- [ ] **Step 3: Build the env package against synthetic data**

Create a synthetic profile and three synthetic JDs under
`tools/skillopt/fixtures/`. Write `adapter.py`, `data.py`, and `score.py` per Task 2's
specification. The target model is a **stub** that returns a canned S3 response — this
task proves the plumbing, not the optimization.

- [ ] **Step 4: Run one tiny optimization and report**

Budget: a hard cap agreed with the user in advance, enforced in `score.py`. Record:
calls used, whether the validation gate accepted any edit, and where trajectories were
written.

- [ ] **Step 5: Verify isolation and record the outcome**

```bash
.venv/bin/python -m pytest -q
git status --short
shasum -a 256 data/jobs.db
git diff --stat -- config docs/prompts pyproject.toml
```

Expected: suite green; clean tree; checksum unchanged; **empty diff** for `config/`,
`docs/prompts/`, and `pyproject.toml`.

- [ ] **Step 6: Commit the record only**

```bash
git add docs/DECISIONS.md
git commit -m "docs(m8): record the isolated SkillOpt mechanics experiment"
```

The `docs/DECISIONS.md` entry records: the pinned version, the user's install
approval, the synthetic-only data scope, the call budget and actual usage, and the
proof that `pyproject.toml`, `config/`, `docs/prompts/`, and the database were
untouched.

---

### Task 4: Deterministic baseline from the M8P-8 corpus

**Files:**
- Create: `docs/superpowers/reports/skillopt-baseline.md`

**Blocker B1:** M8P-8 complete.

- [ ] **Step 1: Compute the baseline read-only**

```bash
.venv/bin/python -m scripts.tailor_pilot cost --root applications
.venv/bin/python -m scripts.tailor_g3 summarize
```

- [ ] **Step 2: Record it**

The report contains: gate pass rates (G1, G2 verdict distribution, L7), G2 round
distribution, edit-budget ratio distribution, model calls per application, wall-clock
per application, and the full feedback statistics — plus the repository commit and the
target model id used to produce them. Without the last two the baseline is not
reproducible.

- [ ] **Step 3: Freeze the split**

Write `tools/skillopt/split.json` naming train and validation job ids and the feedback
record revision used as each label. **The validation ids are never shown to the
optimizer.** Record the split's SHA-256 in the report.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/python -m pytest -q
shasum -a 256 data/jobs.db
git add docs/superpowers/reports/skillopt-baseline.md
git commit -m "docs(m8): record the deterministic tailoring baseline"
```

---

### Task 5: Baseline-versus-SkillOpt evaluation

**Files:**
- Create: `docs/superpowers/reports/skillopt-evaluation.md`

**Blockers:** Tasks 3–4 complete; ≥ 60 labelled applications; blocker B3 (recorded data-provider decision).

- [ ] **Step 1: Confirm the corpus size**

```bash
.venv/bin/python -c "
from src.tailor.feedback import load_feedback_index
rows = load_feedback_index()
jobs = {r['job_id'] for r in rows}
print(f'{len(rows)} records across {len(jobs)} jobs')
assert len(jobs) >= 60, 'promotion needs at least 60 labelled applications'
"
```

If this raises, STOP. Report the shortfall. Do not run the optimization on a smaller
corpus and caveat the result — the design §3.8 explains why that number would not mean
anything.

- [ ] **Step 2: Run one optimization on the train split only**

Enforce the agreed call budget. Record every reproducibility field from the design
§3.6 before starting.

- [ ] **Step 3: Score the candidate on the held-out validation split**

Composite reward per Task 2's specification. Report per-condition numbers, not a single
scalar.

- [ ] **Step 4: Human re-review of the validation set**

The user reviews the validation resumes produced by the candidate prompt, using the
same G3 packet and feedback form. This is required: §5 conditions 3 and 5 cannot be
computed any other way.

- [ ] **Step 5: Write the report and verify isolation**

```bash
.venv/bin/python -m pytest -q
git diff --stat -- config docs/prompts pyproject.toml
shasum -a 256 data/jobs.db
```

Expected: suite green; **empty diff** for `config/`, `docs/prompts/`, and
`pyproject.toml`; checksum unchanged. The candidate prompt lives only under
`tools/skillopt/runs/`.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/reports/skillopt-evaluation.md
git commit -m "docs(m8): compare SkillOpt against the deterministic baseline"
```

---

### Task 6: Evaluate the promotion gate

**Files:**
- Modify: `docs/DECISIONS.md`

- [ ] **Step 1: Evaluate all nine conditions**

Walk the design §5 conditions one by one, recording the observed value and pass/fail
for each. Condition 6 (the candidate still carries its stage's structural contract —
response shape, marker token, untrusted-data instruction) is checked by running the
stage's existing prompt tests against the candidate file.

- [ ] **Step 2: Record the outcome**

Whether the gate passes or fails, record it. A failed gate is a real result and is
worth as much as a passing one.

- [ ] **Step 3: Commit**

```bash
git add docs/DECISIONS.md
git commit -m "docs(m8): record the SkillOpt promotion-gate outcome"
```

---

### Task 7: Promotion (only if the gate passed)

**Files:**
- Modify: exactly one file under `docs/prompts/`

- [ ] **Step 1: Show the user the diff**

```bash
diff -u docs/prompts/tailoring_s3.md tools/skillopt/runs/<run>/candidates/<candidate>.md
```

Get explicit written approval with that diff visible. No approval, no promotion.

- [ ] **Step 2: Promote in one commit**

```bash
cp tools/skillopt/runs/<run>/candidates/<candidate>.md docs/prompts/tailoring_s3.md
.venv/bin/python -m pytest -q
git add docs/prompts/tailoring_s3.md
git commit -m "feat(m8): adopt the SkillOpt-optimized S3 prompt"
```

One file, one commit. Rollback is `git revert` of that commit.

- [ ] **Step 3: Run the D2 drift discipline**

Re-run G1 and G2 on the archived golden applications with the promoted prompt. Any
previously passing gate that now fails is a drift finding: revert immediately and
investigate.

- [ ] **Step 4: Final verification**

```bash
.venv/bin/python -m pytest -q
git status --short
shasum -a 256 data/jobs.db
```

---

## Acceptance criteria

- The feasibility memo answers all eight design §6 questions or records them as unresolved, with sourced facts and inference visibly separated.
- The pinning report names an exact release tag and commit SHA before anything is installed.
- `skillopt` never appears in `pyproject.toml`; no module under `src/`, `scripts/`, or `tests/` imports it; `pytest -q` passes on a machine without it, at every point.
- The mechanics experiment runs on synthetic data, in an isolated venv, under an enforced call budget, and leaves `pyproject.toml`, `config/`, `docs/prompts/`, and `data/jobs.db` provably untouched.
- The baseline report is reproducible: repository commit, target model id, split SHA-256, and every distribution recorded.
- The evaluation uses a held-out validation split the optimizer never saw, with at least 40 train and 20 validation applications, and includes a human re-review.
- No prompt is promoted without all nine gate conditions recorded, a user approval with the diff visible, a single-file commit, and a D2 drift re-run.
- The deterministic gates remain the hard admissibility floor throughout; no gate is replaced by a learned one.

## Verification commands

```bash
.venv/bin/python -m pytest tests/test_no_skillopt_dependency.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -c "import importlib.util; assert importlib.util.find_spec('skillopt') is None; print('project venv clean')"
git diff --stat -- config docs/prompts pyproject.toml
git diff --check
git status --short
shasum -a 256 data/jobs.db
```

## Stop conditions

- Any instruction to add `skillopt` to `pyproject.toml` → refuse; it is an unapproved dependency under AGENTS.md prime directive 4 and this milestone explicitly forbids it.
- Any instruction to install or run SkillOpt before Task 3's approval → stop and ask.
- Fewer than 60 labelled applications at Task 5 → stop; do not run and caveat.
- Real resume, JD, or feedback data would reach a provider without a recorded decision → stop and ask.
- The call budget is exceeded → abort the run and report; do not raise the budget mid-run.
- A candidate prompt improves the reward by weakening its stage's structural contract → reject; that is the optimizer gaming the verifier, which is the exact failure mode the gate exists to catch.
- `pytest -q` fails on a machine without SkillOpt at any point → stop; isolation has been broken.

## Documentation deltas (for the integrator)

Handled inline by Tasks 3, 5, 6, and 7, which are the only points where this milestone
writes to `docs/DECISIONS.md` or `docs/prompts/`. `docs/ROADMAP.md` gains one M8X-1
line only when the milestone terminates — whether by promotion or by a recorded
decision not to adopt.
