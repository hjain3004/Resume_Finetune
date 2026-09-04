# M8N-0b — S2/S3 Gate Corrections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the two deterministic validators the M8N-0 benchmark surfaced — S2's
compound-term coverage check and S3's length gate — so the tailoring chain can complete on
real jobs, without weakening any fabrication guard, without touching the model command, and
without an agent ever editing `config/master_profile.yaml`. Then re-run the three benchmark
jobs live on `claude -p` with the user and record the honest result.

**Architecture:** S2 coverage matching splits a compound must-have term into components and
requires an exact `keywords_hit` per non-baseline component; baseline terms come from a new
`config/assumed_baseline_terms.txt` threaded into the S2 request like `banned_words.txt` is
threaded into G1. S3's `len(after) > len(before)` becomes
`len(after) > len(before) + max(len(motivating_term))` — growth bounded by the mirrored term,
with the unchanged uncited-vocabulary guard ensuring the added characters can only be that
term. Two one-sentence prompt edits (S2, S3) under N12. Everything else stays.

**Tech Stack:** Python 3.11+, existing `src/tailor` package, `claude -p` tool-disabled
invocation via `src/tailor/invoke.py` (unchanged), pdflatex (local), pytest. No new
dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-m8n-0b-s2-s3-gate-corrections-design.md`
(read all of it; §3 decisions B1–B9, §4 S2 detail, §5 S3 detail, §6 boundary, §7 tests,
§8 acceptance).

**Prerequisites:** `main` at `c065756` (merged M8N-0); `pdflatex` and `claude` CLI 2.1.x on
PATH; a working tree with a discardable unscoped edit from a prior agent (Task 0 removes it).

## Global Constraints

- One milestone: M8N-0b only. Do not start M8N-1.
- Record `data/jobs.db` SHA-256 before starting and verify it is unchanged at closeout:
  it must stay `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
  Never open it except through the read-only `export-jd` helper.
- **`config/master_profile.yaml` is never edited.** Baseline terms go in
  `config/assumed_baseline_terms.txt`.
- **`src/tailor/invoke.py` and `scripts/score_batch.py` are never edited.** `DEFAULT_CLAUDE_CMD`
  stays `("claude","-p","--tools","","--no-session-persistence","--")`. No model switch.
- **Do not touch** `src/tailor/g1.py`, `src/tailor/g2.py`, `src/tailor/g3.py`,
  `src/render/l7.py`, `src/tailor/s1.py`, S0/S1/G2/G3 prompts, or any M8N-0 lane/CLI code
  except the config-path threading in `run_stages` / `run_manual_application`.
- The only permitted prompt edits are the two single sentences in Task 3 (`tailoring_s2.md`)
  and Task 4 (`tailoring_s3.md`), approved by the user at M8N-0b kickoff under spec N12, each
  recorded in `docs/DECISIONS.md`. No rule sentence outside those two changes.
- The S3 uncited-vocabulary guard, numeric-token guard, and leading-verb guard are unchanged.
- Never stage `data/`, `inbox/`, `applications/`, `applications_manual/`,
  `profile/` (except `profile/template.tex`), `docs/sampleJD.md`, or `inbox/urls.txt`.
- Tests never touch the network, the production DB, or a model.
- Run tests with the project interpreter: `.venv/bin/python -m pytest ...`.
- Work in a git worktree (`superpowers:using-git-worktrees`) or on `main` per the executor's
  standard; commit after every task with `feat(m8n0b): ...` / `fix(m8n0b): ...` /
  `test(m8n0b): ...` / `docs(m8n0b): ...`. No push.
- If a job still fails a gate after Tasks 2 and 4, that is the recorded benchmark result
  (spec B9). Do not loosen a third gate; stop and report.

---

## File structure

| File | Task | Responsibility |
|---|---|---|
| `config/assumed_baseline_terms.txt` | 1 | new; the reviewed baseline-term list (one per line, `#` comments) |
| `src/tailor/profile_views.py` | 1 | `SelectionCatalog.assumed_baseline_terms`; `selection_to_dict` / `parse_selection` |
| `src/tailor/s2.py` | 1, 2 | request builder threads the list (1); `_split_term` + `covered`-branch rewrite (2) |
| `src/tailor/s3.py` | 1, 4 | synthetic catalog gains `assumed_baseline_terms=()` (1); bounded length rule (4) |
| `src/tailor/pilot.py` | 1 | `assumed_baseline_terms_path` param on `run_stages` / `run_application`, beside `banned_words_path` |
| `src/tailor/lane.py` | 1 | mirror the new path in `run_manual_application` if it enumerates config paths |
| `src/tailor/preflight.py` | 1 | `_SyntheticShapeContext` catalog gains `assumed_baseline_terms=()` if it constructs one |
| `docs/prompts/tailoring_s2.md` | 3 | one sentence, N12 |
| `docs/prompts/tailoring_s3.md` | 4 | one sentence, N12 |
| `tests/tailor/test_s2.py` | 2 | `_split_term` table + coverage cases (spec §7) |
| `tests/tailor/test_s3.py` / `tests/tailor/test_trace_replay.py` | 4 | bounded-grow accept, B7 regression, uncited-still-bites |
| `tests/tailor/test_preflight.py` | 3 | prompt-invariants stay clean after the S2 edit |
| `tests/tailor/test_lane.py`, `tests/tailor/test_pilot.py`, `tests/test_m8p2_contracts.py` (and any other test that constructs a `SelectionCatalog`) | 1 | add `assumed_baseline_terms=()` to constructors |
| `tests/fixtures/tailor/traces/m8n0b_*_{225,119,211}_accepted.txt` | 5 | replay fixtures from the live re-benchmark |
| `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md` | 5 | record B1–B9 and the honest M8N-0 §11 benchmark result |

---

### Task 0: Discard the abandoned working tree; establish the clean baseline

**Files:** none created. Reverts uncommitted changes from a prior agent's unscoped attempt.

- [ ] **Step 1: Record the baseline**
  ```bash
  shasum -a 256 data/jobs.db | tee /tmp/m8n0b-db-before.txt
  git log --oneline -1          # expect c065756
  git status --short
  ```
  The status shows the prior agent's uncommitted edits to `config/master_profile.yaml`,
  `docs/prompts/tailoring_{g2,s2,s3}.md`, `scripts/score_batch.py`, `src/profile.py`,
  `src/tailor/{g1,g2,invoke,preflight,profile_views,s2,s3}.py`,
  `tests/tailor/{test_publish,test_s2,test_trace_replay}.py`, plus untracked `scratch/`,
  `applications_manual/`, `inbox/jd/`, and
  `tests/fixtures/tailor/traces/m8n0_*_citadel_accepted.txt`. The user-owned `inbox/urls.txt`
  and `docs/sampleJD.md` are pre-existing and are preserved.

- [ ] **Step 2: Restore the tracked files the prior agent changed, leaving `inbox/urls.txt` alone**
  ```bash
  git checkout -- config/master_profile.yaml docs/prompts/tailoring_g2.md \
    docs/prompts/tailoring_s2.md docs/prompts/tailoring_s3.md scripts/score_batch.py \
    src/profile.py src/tailor/g1.py src/tailor/g2.py src/tailor/invoke.py \
    src/tailor/preflight.py src/tailor/profile_views.py src/tailor/s2.py src/tailor/s3.py \
    tests/tailor/test_publish.py tests/tailor/test_s2.py tests/tailor/test_trace_replay.py
  ```
  Do **not** `git checkout -- .` and do **not** touch `inbox/urls.txt`.

- [ ] **Step 3: Remove the untracked artifacts from the discarded attempt**
  ```bash
  rm -rf scratch/ applications_manual/ inbox/jd/
  rm -f tests/fixtures/tailor/traces/m8n0_g2_citadel_accepted.txt \
        tests/fixtures/tailor/traces/m8n0_s0_citadel_accepted.txt \
        tests/fixtures/tailor/traces/m8n0_s1_citadel_accepted.txt \
        tests/fixtures/tailor/traces/m8n0_s2_citadel_accepted.txt \
        tests/fixtures/tailor/traces/m8n0_s3_citadel_accepted.txt
  ```
  Keep `data/traces/` (gitignored run history) unless the user asks otherwise.

- [ ] **Step 4: Confirm the clean baseline**
  ```bash
  git status --short          # expect only ` M inbox/urls.txt` and `?? docs/sampleJD.md`
  .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
  ```
  Expected: `1916 passed, 1 deselected` (or `1916 passed` plus only a pre-existing unrelated
  date-sensitive failure). If any other test fails, the checkout was incomplete — stop.
  ```bash
  shasum -a 256 data/jobs.db   # must equal /tmp/m8n0b-db-before.txt
  ```

- [ ] **Step 5: No commit.** Task 0 only restores the tree.

---

### Task 1: Thread `assumed_baseline_terms` through the S2 request (no behavior change yet)

**Files:** create `config/assumed_baseline_terms.txt`; modify `src/tailor/profile_views.py`,
`src/tailor/s2.py` (builder only), `src/tailor/s3.py` (synthetic catalog only),
`src/tailor/pilot.py`, `src/tailor/lane.py`, `src/tailor/preflight.py`; update every test that
constructs a `SelectionCatalog`.

**Interfaces:**
- `SelectionCatalog` gains `assumed_baseline_terms: tuple[str, ...]` as its last field.
- `selection_to_dict` emits `"assumed_baseline_terms": [...]`.
- `parse_selection` requires the key (not optional); missing key → `ProfileViewError`.
- `load_assumed_baseline_terms(path: Path) -> tuple[str, ...]` (new helper, in `s2.py` or a
  small `src/tailor/config_lists.py` — executor's call, match how `load_banned_terms` lives in
  `g1.py`): reads one term per line, strips, drops blank lines and `#` comments, de-dups
  case-insensitively preserving first-seen order. Missing file → `()`.
- `run_stages` / `run_application` gain
  `assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt")`, passed to
  wherever `build_s2_request` / the S2 catalog is assembled.

- [ ] **Step 1: Create `config/assumed_baseline_terms.txt`**
  Seed list (the user reviews and may trim/extend at kickoff):
  ```
  # Terms a CS-graduate resume is not expected to keyword-match (spec M8N-0b B2).
  # One term per line; matched case-insensitively after whitespace collapse.
  data structures
  algorithms
  data structures and algorithms
  object-oriented programming
  object oriented programming
  oop
  git
  version control
  unit testing
  debugging
  ```

- [ ] **Step 2: Write the failing tests**
  In `tests/tailor/test_s2.py` (or `test_m8p2_contracts.py`, wherever `parse_selection` is
  covered), assert:
  - `parse_selection` on a dict without `assumed_baseline_terms` raises `ProfileViewError`.
  - `selection_to_dict(catalog)` round-trips through `parse_selection` with the field intact.
  - `load_assumed_baseline_terms` on a temp file with blanks + `#` comments + a dup returns
    the de-duped ordered tuple; on a missing path returns `()`.
  Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_s2.py -k baseline`
  Expected: FAIL (`AttributeError` / missing key / missing function).

- [ ] **Step 3: Implement the plumbing**
  Add the field, the dict I/O, the loader, and the `run_stages` / `run_application` /
  `run_manual_application` path parameter. In `src/tailor/s3.py` `_synthetic_s2_request`, pass
  `assumed_baseline_terms=()` to the `SelectionCatalog(...)` call. In
  `src/tailor/preflight.py` `_SyntheticShapeContext`, add `assumed_baseline_terms=()` to any
  `SelectionCatalog` / synthetic catalog it builds. Do **not** change `validate_s2_selection`
  yet.

- [ ] **Step 4: Fix every `SelectionCatalog(...)` construction in the test suite**
  Grep for `SelectionCatalog(` across `tests/` and add `assumed_baseline_terms=()` (or a small
  list where a test needs one). This is a mechanical, same-shape edit — batch it.

- [ ] **Step 5: Run the suites**
  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/ tests/test_m8p2_contracts.py
  .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
  ```
  Expected: green (baseline count + the new baseline tests). `validate_s2_selection` behavior
  is still byte-identical to `c065756` — Task 1 is pure plumbing.

- [ ] **Step 6: Commit**
  ```bash
  git add config/assumed_baseline_terms.txt src/tailor/profile_views.py src/tailor/s2.py \
    src/tailor/s3.py src/tailor/pilot.py src/tailor/lane.py src/tailor/preflight.py \
    tests/tailor tests/test_m8p2_contracts.py
  git commit -m "feat(m8n0b): thread assumed_baseline_terms into the S2 request"
  ```

---

### Task 2: Compound-term component matching in `validate_s2_selection`

**Files:** modify `src/tailor/s2.py`; add tests to `tests/tailor/test_s2.py`.

**Interfaces:**
- `_split_term(term: str) -> list[str]` — pure. Splits on (case-insensitive)
  `,\s+and\s+`, `,\s+or\s+`, `;\s*`, `\s+/\s+`, `,\s*`, `\s+and\s+`, `\s+or\s+`; strips each
  part; drops empties. A term with no separator returns `[term]`.
- `validate_s2_selection` `covered` branch rewritten per spec §4 steps 1–6. Error message for
  the failing case stays exactly `"covered term has no exact keyword hit"`. New message for
  the B3 all-baseline-with-no-bullet case:
  `"all-baseline covered term must still cite a selected bullet"`.

- [ ] **Step 1: Write the failing tests** (spec §7 S2 list). At minimum:
  - `_split_term` table: `"a, b, and c"` → `["a","b","c"]`; `"a and b"` → `["a","b"]`;
    `"a; b"` → `["a","b"]`; `"a / b"` → `["a","b"]`; `"single term"` → `["single term"]`;
    `"a,b"` → `["a","b"]`; `" a ,  b  "` → `["a","b"]`.
  - job-225 case: `must_have=(Requirement("data structures, algorithms, and distributed systems", quote=...),)`,
    catalog `assumed_baseline_terms=("data structures","algorithms")`, a selected bullet whose
    `keywords_hit` includes `"distributed systems"`, coverage entry `covered` citing that
    bullet → `parse_s2_response` accepts.
  - same but the cited bullet has no `"distributed systems"` hit → `S2ValidationError` match
    `"covered term has no exact keyword hit"`.
  - `must_have=("data structures and algorithms",)`, both baseline, coverage `covered` with
    `bullet_ids=[]` → `S2ValidationError` match `"all-baseline covered term must still cite"`.
  - same, coverage `gap` with `bullet_ids=[]` → accepted.
  - a `do_not_claim` term (e.g. `"Kubernetes and Helm"`) marked `covered` → still
    `S2ValidationError` `"do_not_claim term covered"`.
  - a plain single term with an exact `keywords_hit` → accepted; without → rejected
    (regression, identical to `c065756`).
  Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_s2.py`
  Expected: FAIL on the new cases.

- [ ] **Step 2: Implement `_split_term` + the `covered` branch** per spec §4. Keep the rest of
  `validate_s2_selection` byte-identical.

- [ ] **Step 3: Run S2 + dependents**
  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_s2.py \
    tests/tailor/test_s3.py tests/tailor/test_trace_replay.py tests/test_m8p2_contracts.py \
    tests/test_m8p3_integration.py
  ```
  Expected: green. If a pre-existing S2 test encoded the old whole-string rule, update it to
  the component rule with an inline comment citing B1 — do not delete the assertion.

- [ ] **Step 4: Full suite** `.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3`
  Expected: green apart from any pre-existing unrelated failure.

- [ ] **Step 5: Commit**
  ```bash
  git add src/tailor/s2.py tests/tailor/test_s2.py
  git commit -m "fix(m8n0b): match S2 compound-term coverage per component"
  ```

---

### Task 3: S2 prompt sentence (N12)

**Files:** modify `docs/prompts/tailoring_s2.md`, `docs/DECISIONS.md`; assert in
`tests/tailor/test_preflight.py`.

- [ ] **Step 0: Confirm approval.** The user approved the two M8N-0b prompt edits at kickoff
  under spec N12. If not, stop.

- [ ] **Step 1: Replace one sentence.** In `docs/prompts/tailoring_s2.md`, replace:
  > `A \`covered\` entry has one or more selected bullets whose \`keywords_hit\` contains the exact normalized term; use \`gap\` with an empty bullet_ids array when no exact mapping exists.`

  with:
  > `A \`covered\` entry names one or more selected bullets and, for each part of the term (a comma / "and" / "or" / "/"-separated list counts as multiple parts), some named bullet's \`keywords_hit\` contains that part exactly — except parts drawn from \`assumed_baseline_terms\`, which need no keyword hit. Use \`gap\` with an empty \`bullet_ids\` array when a non-baseline part has no exact keyword hit, and prefer \`gap\` for a requirement that is only computer-science fundamentals.`

  Change nothing else. Keep the response-shape block and every other sentence.

- [ ] **Step 2: Verify the preflight stays clean**
  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_preflight.py
  .venv/bin/python -m scripts.tailor_now preflight --skip-render
  ```
  Expected: `check_prompt_invariants` returns `()`;
  `run_preflight(..., skip_render=True).passed` is `True`. If `_shape_passes` rejects the S2
  block, adjust only wording (never a rule) until the structural parser accepts it. Add/keep a
  test asserting `check_prompt_invariants(Path("docs/prompts")) == ()`.

- [ ] **Step 3: Record the approval in `docs/DECISIONS.md`**
  ```
  ## 2026-09-03 — M8N-0b S2 coverage-rule sentence (approved, N12)

  `docs/prompts/tailoring_s2.md`: the `covered` sentence now describes per-component keyword
  matching and the `config/assumed_baseline_terms.txt` exemption, matching the corrected
  `validate_s2_selection` (spec M8N-0b B1–B4). No other sentence changed; response shape
  unchanged; `check_prompt_invariants(docs/prompts)` returns no findings. Approved by the user
  at M8N-0b kickoff.
  ```

- [ ] **Step 4: Commit**
  ```bash
  git add docs/prompts/tailoring_s2.md docs/DECISIONS.md tests/tailor/test_preflight.py
  git commit -m "docs(m8n0b): align the S2 prompt with per-component coverage"
  ```

---

### Task 4: S3 length gate bounded by the mirrored term (+ prompt sentence, N12)

**Files:** modify `src/tailor/s3.py`, `docs/prompts/tailoring_s3.md`, `docs/DECISIONS.md`;
tests in `tests/tailor/test_s3.py` / `tests/tailor/test_trace_replay.py`.

- [ ] **Step 1: Write the failing tests** (spec §7 S3 list + B7):
  - a `sepsis_b3`-style edit whose only growth is one covered `motivating_term`'s surface
    form (mirrors a term ~15 chars longer, tightens nothing) with
    `len(after) == len(before) + len(that term)` → `parse_s3_response` accepts.
  - `tests/fixtures/tailor/traces/s3_length_growth_rejected.txt` → **still**
    `S3SemanticError` match `"length grew"` (compute its `len(after) - len(before)` against
    `max(len(motivating_term))` in a comment; it must exceed the budget — if it does not,
    B5 is wrong, stop).
  - an edit with `len(after) = len(before) + max(len(motivating_term)) + 1` → rejected.
  - an edit within the length budget that introduces an uncited word → still rejected by the
    unchanged uncited-vocabulary guard (`match="uncited vocabulary"`).
  Run: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_s3.py tests/tailor/test_trace_replay.py`
  Expected: FAIL on the bounded-accept case; the B7 regression and uncited case should already
  pass and must keep passing.

- [ ] **Step 2: Implement the bound** in `_validate_bullet_edit` per spec §5:
  ```python
  budget = max(len(term) for term in edit.motivating_terms)
  if len(plain_after) > len(source.plain_text) + budget:
      raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: plain-text length grew beyond the mirrored term")
  ```
  Leave the uncited-vocabulary, numeric-token, and leading-verb checks exactly as they are.

- [ ] **Step 3: Replace one prompt sentence.** In `docs/prompts/tailoring_s3.md`, after
  `Preserve each leading action verb and the complete numeric-token multiset.` add:
  > `When a covered term's surface form is longer than the wording it replaces, tighten elsewhere in the same bullet so the edit stays as close to the original length as possible.`

  Change nothing else. Keep the response-shape block and the `{{S3_REQUEST_JSON}}` marker;
  do **not** add a `{{S3_REVISION_JSON}}` marker.

- [ ] **Step 4: Run S3 + dependents + preflight**
  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_s3.py \
    tests/tailor/test_trace_replay.py tests/test_m8p3_integration.py \
    tests/test_m8p4_integration.py tests/tailor/test_preflight.py
  .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
  ```
  Expected: green. Update any pre-existing test that encoded `len(after) > len(before)` exactly
  to the bounded rule with an inline comment citing B5 — do not delete the assertion.

- [ ] **Step 5: Record the approval in `docs/DECISIONS.md`**
  ```
  ## 2026-09-03 — M8N-0b S3 length gate + prompt sentence (approved, N12)

  `src/tailor/s3.py`: an edited bullet may exceed the original length by at most the longest
  `motivating_term` (spec M8N-0b B5); the uncited-vocabulary, numeric-token, and leading-verb
  guards are unchanged, so the extra characters can only be the mirrored covered term.
  `docs/prompts/tailoring_s3.md`: one sentence added asking the model to tighten elsewhere when
  mirroring a longer term. `s3_length_growth_rejected.txt` still rejects (B7). Approved by the
  user at M8N-0b kickoff.
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add src/tailor/s3.py docs/prompts/tailoring_s3.md docs/DECISIONS.md \
    tests/tailor/test_s3.py tests/tailor/test_trace_replay.py
  git commit -m "fix(m8n0b): bound the S3 length gate by the mirrored term"
  ```

---

### Task 5: Docs, then the user-supervised re-benchmark and closeout

**Files:** modify `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md`;
create (committed) `tests/fixtures/tailor/traces/m8n0b_*_{225,119,211}_accepted.txt` and their
replay tests; create (gitignored, not committed) `inbox/jd/*.txt`, `applications_manual/...`.

**Interfaces:** consumes `scripts/tailor_now.py` from M8N-0.

- [ ] **Step 1: Pre-benchmark checks**
  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3        # green
  grep -n 'DEFAULT_CLAUDE_CMD' src/tailor/invoke.py                        # unchanged from c065756
  git diff --stat c065756..HEAD -- config/master_profile.yaml src/tailor/g1.py \
    src/tailor/g2.py src/tailor/g3.py src/render/l7.py scripts/score_batch.py  # empty
  shasum -a 256 data/jobs.db                                              # matches /tmp/m8n0b-db-before.txt
  ```

- [ ] **Step 2: User-supervised benchmark (live model calls; spec B8, M8N-0 spec §11)**
  Only with the user present. For each job, export then run on the default `claude -p`:
  ```bash
  .venv/bin/python -m scripts.tailor_now export-jd --job-id 225 --out inbox/jd/225.txt
  .venv/bin/python -m scripts.tailor_now run --jd inbox/jd/225.txt --company "Notion" \
    --title "Software Engineer – Early Career - AI" --variant backend
  ```
  Repeat for 119 (`--variant ml`, title from `export-jd`) and 211 (`--variant backend`). On a
  failed stage, read the bounded error and the trace under `data/traces/<date>/`, then use the
  printed retry command **once**. Do not edit a prompt or a validator to get past a failure
  (spec B9) — record it.

  Collect, per job, from `applications_manual/`:

  | Job | coverage covered/total (`s2_response.json`) | G2 C1–C5 + verdict (`g2_bundle.json`) | L7 violations (`render_result.json`) | pages | model calls (`run_manifest.json`) | rejected/ present |
  |---|---|---|---|---|---|---|

  Compare 225 and 119 with the pilot's `applications/*/s2_response.json` / `g2_bundle.json`.
  Pass conditions are M8N-0 spec §11 (M8N-0 row).

- [ ] **Step 3: Record replay fixtures from the live traces**
  For one accepted S1, S0, S2, S3, and G2 trace per job, extract fixtures (the recorder
  refuses any output containing identity values):
  ```bash
  .venv/bin/python -m scripts.record_trace_fixture data/traces/<date>/<trace>.json m8n0b_<stage>_<job>_accepted
  ```
  Add one replay test per fixture to `tests/tailor/test_trace_replay.py` following that file's
  pattern. Run:
  `.venv/bin/python -m pytest -q -p no:cacheprovider tests/tailor/test_trace_replay.py`.

- [ ] **Step 4: Walk the user through the review packets**
  Open each `applications_manual/<dir>/review.md` and PDF with the user. Time the 225 review.
  Capture the decision (approve / reject with reason). Do not fill `feedback_form.yaml` on the
  user's behalf.

- [ ] **Step 5: Verify the DB and the suite**
  ```bash
  shasum -a 256 data/jobs.db; cat /tmp/m8n0b-db-before.txt          # identical
  .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3  # green
  git diff --check
  ```

- [ ] **Step 6: Closeout docs and commit**
  Append to `docs/DECISIONS.md` a `## 2026-09-03 — M8N-0b closeout` entry: the commit list,
  the per-job §11 benchmark table from Step 2 (pass or documented fail), the user's job-225
  decision and review time, the recorded fixture names, and `data/jobs.db` SHA-256 unchanged.
  Update `docs/ROADMAP.md` and `docs/IMPLEMENTATION_PLAN.md` M8N status: M8N-0 lane infra
  COMPLETE (`c065756`); M8N-0b gate corrections COMPLETE `<date>` with `<benchmark outcome>`;
  M8N-1 / M8N-2 not started. If a job still fails a gate, say so plainly and name it as the
  next scoped milestone.
  ```bash
  git add docs/DECISIONS.md docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md \
    tests/fixtures/tailor/traces tests/tailor/test_trace_replay.py
  git commit -m "docs(m8n0b): close the S2/S3 gate corrections with benchmark results"
  ```
  Do not push.

---

## Self-review against the spec

- B1 component matching → Task 2 (`_split_term`, `covered` branch), Task 3 (prompt sentence).
- B2 baseline list in `config/` → Task 1 (`config/assumed_baseline_terms.txt`, loader, threading).
- B3 all-baseline still needs a bullet → Task 2 (rule + tests).
- B4 S2 prompt sentence, N12 → Task 3.
- B5 S3 bounded length → Task 4 (Step 2).
- B6 S3 prompt sentence, N12 → Task 4 (Step 3).
- B7 `s3_length_growth_rejected.txt` still rejects → Task 4 (Step 1 regression).
- B8 live re-benchmark on `claude -p`, user present, fixtures recorded → Task 5.
- B9 no third-gate loosening → Global Constraints + Task 5 Step 2.
- §6 boundary: `master_profile.yaml`, `invoke.py`, `score_batch.py`, `g1/g2/g3.py`, `l7.py`,
  `s1.py` all in the "never" list → Global Constraints + Task 5 Step 1 diff check.
- §8 acceptance: DB hash unchanged, `DEFAULT_CLAUDE_CMD` byte-identical, suite green,
  preflight clean, both prompt edits single sentences → Tasks 3–5 verification steps.
