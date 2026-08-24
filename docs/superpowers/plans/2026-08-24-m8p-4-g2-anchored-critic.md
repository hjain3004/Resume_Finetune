# M8P-4 G2 Anchored Critic and Bounded Revision Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an anchored adversarial critic that can find quality defects the deterministic gates cannot, plus a two-round revision loop in which only the existing bounded S3 contract may change resume text.

**Architecture:** The critic receives a privacy-minimised, diff-centred request derived entirely from deterministic artifacts, and returns only anchored findings with no replacement text. Revisions go back through S3's existing edit contract and are re-validated by static G1 in full; the pre-revision bundle is preserved unconditionally.

**Tech Stack:** Python 3.11+, frozen dataclasses, stdlib `json`/`enum`/`pathlib`, existing `invoke_text_model` / `write_trace` / `write_json_atomic`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-m8p-4-g2-anchored-critic-design.md`

**Can implementation start before M8P-3R merges?** M8P-3R **merged at `560ad8d`**, so this milestone is unblocked and may start now. Create branch `m8p-4-g2` from `main`. (The dependency was real: Task 4 modifies `src/tailor/s3.py` and `src/tailor/s3_pipeline.py`, and Tasks 1/5 consume the repaired bundle parser.)

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/TAILORING_METHODOLOGY.md` §4, the spec above, and the merged M8P-3R code before editing.
- Implement M8P-4 only. Do not start G3, rendering, L7, application archival, DB mutation, Company Bank integration, a live model call, a pilot, or SkillOpt.
- No new dependency. Tests never call a real model, the network, or `pdflatex`.
- Frozen dataclasses at boundaries; pure parsing/validation separated from I/O.
- Reuse `invoke_text_model`, `write_trace`, `write_json_atomic`. Do not fork them.
- Open SQLite read-only. Raw SQL stays in `src/db.py`.
- One model attempt per round; no retries inside a round; no shell, no tools, no session persistence.
- Bound every diagnostic containing model or JD content to 200 characters.
- Maximum 2 critic rounds. Maximum 8 findings per response. Maximum 8 bullet edits per S3 response (unchanged from M8P-3).
- Verdict rule verbatim: `PASS ⟺ C1 == 3 AND min(C2..C5) >= 2`.
- Baseline DB SHA-256: `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- TDD per task: focused RED, minimal GREEN, regression, commit.
- Do not edit `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md`. Leave deltas in the section at the end of this plan for the integrator.

## Predecessor contracts and blockers

Consumed from merged M8P-3R (do not modify):

```python
# src/tailor/s3.py
S3Request, S3Response, TailoredDraft, DraftBullet, ChangeEntry, EditBudget
BulletEdit(bullet_id, after, motivating_terms, rule)
SkillAddition(category, term, motivating_term)
parse_s3_response(raw_output: str, request: S3Request) -> S3Response
hydrate_s3(request: S3Request, response: S3Response) -> TailoredDraft
derive_change_log(request, response, draft) -> tuple[ChangeEntry, ...]
derive_unified_diff(request, draft) -> str
calculate_edit_budget(request, draft) -> EditBudget
build_s3_prompt(template: str, request: S3Request) -> str
S3ParseError, S3SemanticError, S3HydrationError

# src/tailor/g1.py
run_static_g1(request, response, draft, banned_terms) -> G1Report
load_banned_terms(path: Path) -> tuple[str, ...]
G1Report(status, violations, edit_budget, render_line_check)

# src/tailor/s3_pipeline.py
S3Bundle, S3Outcome, S3OutcomeKind, run_s3_invocation(...), s3_bundle_to_dict(bundle)
# M8P-3R strict authoritative parser -- VERIFIED signature, src/tailor/s3_pipeline.py:155.
# It recomputes response validation, hydration, change log, diff, budget, and static G1
# from `request` and requires every persisted derived field to match. Callers must first
# rebuild the authoritative S3Request from the upstream chain; there is no load-only path.
parse_s3_bundle(raw: object, request: S3Request, banned_terms: tuple[str, ...]) -> S3Bundle
S3BundleError
```

**Blocker B1: RESOLVED.** M8P-3R merged at `560ad8d`; the parser is
`parse_s3_bundle(raw, request, banned_terms)` and the post-merge baseline is
**1381 passed, 1 deselected**. Every "full suite green" step in this plan means at
least that count.

**Blocker B2:** decision D2 in the umbrella design (revision goes back through S3, not
through G2) must be confirmed by the user before Task 4. If the user chooses the
opposite, stop and re-plan Tasks 4–5; do not improvise.

## Target files

Create: `src/tailor/g2.py`, `src/tailor/g2_pipeline.py`, `docs/prompts/tailoring_g2.md`,
`scripts/tailor_g2.py`, `tests/tailor/test_g2.py`, `tests/tailor/test_g2_pipeline.py`,
`tests/test_tailor_g2_cli.py`, `tests/test_m8p4_integration.py`,
`tests/fixtures/tailor/m8p4_builders.py`.

Modify (Task 4 only, additive): `src/tailor/s3.py`, `src/tailor/s3_pipeline.py`.

## Privacy boundaries

The `G2Request` JSON must never contain: raw JD text, `identity`, `education`,
`evidence`, `defense`, `interview_risk`, `metric_ledger`, `known_gaps`, Company Bank
data, absolute file paths, or the S2/S3 deliberation. Only verbatim JD *quotes*
already validated by S1 may appear. Task 1's test asserts this by substring scan over
the serialized request.

---

### Task 1: G2 typed contracts and strict parsers

**Files:**
- Create: `src/tailor/g2.py`
- Create: `tests/tailor/test_g2.py`
- Create: `tests/fixtures/tailor/m8p4_builders.py`

**Interfaces:**
- Consumes: `S3Request`, `S3Response`, `TailoredDraft`, `ChangeEntry`, `S3Bundle`, `S0Response`, `S1Response`, `S2Response` from merged M8P-3R.
- Produces:

```python
G2_REQUEST_MARKER = "{{G2_REQUEST_JSON}}"
MAX_FINDINGS = 8
MAX_ROUNDS = 2

class G2ParseError(ValueError): ...
class G2SemanticError(ValueError): ...

class G2Dimension(str, Enum):
    C1 = "C1"; C2 = "C2"; C3 = "C3"; C4 = "C4"; C5 = "C5"

class G2TargetKind(str, Enum):
    BULLET = "bullet"; SKILL_ADDITION = "skill_addition"

RULE_VOCABULARY: dict[G2Dimension, frozenset[str]]

@dataclass(frozen=True)
class ChangedBulletView:
    bullet_id: str
    before_plain: str
    after_plain: str
    motivating_terms: tuple[str, ...]
    motivating_jd_quotes: tuple[str, ...]
    rule: str

@dataclass(frozen=True)
class SkillAdditionView:
    category: str
    term: str
    motivating_jd_quote: str

@dataclass(frozen=True)
class UnchangedBulletView:
    bullet_id: str
    plain_text: str

@dataclass(frozen=True)
class G2Finding:
    dimension: G2Dimension
    rule_id: str
    target_kind: G2TargetKind
    target_id: str
    quoted_line: str
    explanation: str

@dataclass(frozen=True)
class G2Request:
    job_id: int
    company: str
    title: str
    context_mode: str            # always "jd_only"
    round_index: int             # 1 or 2
    positioning: S0Response
    must_have: tuple[tuple[str, str], ...]     # (term, jd_quote)
    nice_to_have: tuple[tuple[str, str], ...]
    coverage: tuple[tuple[str, str, tuple[str, ...]], ...]   # (term, status, bullet_ids)
    changed_bullets: tuple[ChangedBulletView, ...]
    skill_additions: tuple[SkillAdditionView, ...]
    unchanged_bullets: tuple[UnchangedBulletView, ...]
    unified_diff: str
    banned_terms: tuple[str, ...]
    taste_lessons: tuple[str, ...]
    prior_findings: tuple[G2Finding, ...]
    alignment_fingerprint: str
    bundle_schema_version: str

@dataclass(frozen=True)
class G2Response:
    scores: tuple[tuple[G2Dimension, int], ...]   # exactly C1..C5, in order
    findings: tuple[G2Finding, ...]

def load_taste_lessons(path: Path) -> tuple[str, ...]: ...
def build_g2_request(s3_request: S3Request, bundle: S3Bundle, *,
                     round_index: int, banned_terms: tuple[str, ...],
                     taste_lessons: tuple[str, ...],
                     prior_findings: tuple[G2Finding, ...] = ()) -> G2Request: ...
def g2_request_to_dict(request: G2Request) -> dict[str, object]: ...
def parse_g2_request(raw: object) -> G2Request: ...
def build_g2_prompt(template: str, request: G2Request) -> str: ...
def parse_g2_response(raw_output: str, request: G2Request) -> G2Response: ...
def g2_response_to_dict(response: G2Response) -> dict[str, object]: ...
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/fixtures/tailor/m8p4_builders.py
"""Synthetic M8P-4 inputs. No network, no model, no real profile mutation."""
from src.tailor.g2 import G2Dimension, G2Finding, G2TargetKind


def valid_scores(**overrides) -> dict[str, int]:
    base = {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}
    base.update(overrides)
    return base


def finding_dict(**overrides) -> dict[str, str]:
    base = {
        "dimension": "C5",
        "rule_id": "C5.template_phrasing",
        "target_kind": "bullet",
        "target_id": "b_edited",
        "quoted_line": "improved throughput",
        "explanation": "reads as template output",
    }
    base.update(overrides)
    return base
```

```python
# tests/tailor/test_g2.py
import json
import pytest
from src.tailor.g2 import (
    G2ParseError, G2SemanticError, build_g2_request, g2_request_to_dict,
    parse_g2_request, parse_g2_response,
)
from tests.fixtures.tailor.m8p4_builders import finding_dict, valid_scores


def test_request_round_trips_and_omits_private_fields(s3_pair_with_bundle):
    s3_request, bundle = s3_pair_with_bundle
    request = build_g2_request(s3_request, bundle, round_index=1,
                               banned_terms=("spearheaded",), taste_lessons=())
    rendered = json.dumps(g2_request_to_dict(request))
    for forbidden in ("jd_text", "identity", "education", "evidence",
                      "defense", "interview_risk", "metric_ledger", "known_gaps"):
        assert forbidden not in rendered
    assert parse_g2_request(json.loads(rendered)) == request


def test_response_rejects_quote_absent_from_target(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C5=2),
        "findings": [finding_dict(quoted_line="text that is not in the bullet")],
    })
    with pytest.raises(G2SemanticError, match="quoted_line"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_finding_targeting_unchanged_bullet(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C4=2),
        "findings": [finding_dict(dimension="C4", rule_id="C4.signal_below_fold",
                                  target_id="b_unchanged")],
    })
    with pytest.raises(G2SemanticError, match="out of scope"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_low_score_without_finding(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(C2=2), "findings": []})
    with pytest.raises(G2SemanticError, match="C2"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_finding_on_dimension_scored_three(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(), "findings": [finding_dict()]})
    with pytest.raises(G2SemanticError, match="C5"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_rule_id_from_another_dimension(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C2=2),
        "findings": [finding_dict(dimension="C2", rule_id="C5.template_phrasing")],
    })
    with pytest.raises(G2SemanticError, match="rule_id"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_markdown_fence(g2_request_one_edit):
    raw = "```json\n{\"scores\": {}, \"findings\": []}\n```"
    with pytest.raises(G2ParseError):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_boolean_score(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(C1=True), "findings": []})
    with pytest.raises(G2ParseError, match="C1"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_more_than_eight_findings(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C5=2),
        "findings": [finding_dict(explanation=f"issue {i}") for i in range(9)],
    })
    with pytest.raises(G2ParseError, match="findings"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_unexpected_field(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(), "findings": [],
                      "revised_bullet": "any text at all"})
    with pytest.raises(G2ParseError):
        parse_g2_response(raw, g2_request_one_edit)
```

Add the two fixtures `s3_pair_with_bundle` and `g2_request_one_edit` to
`tests/tailor/conftest.py` (create it if absent), building a synthetic `S3Request`
plus an `S3Bundle` with exactly one edited bullet `b_edited` and one unchanged bullet
`b_unchanged`, reusing the existing M8P-3 test builders.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_g2.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tailor.g2'`.

- [ ] **Step 3: Implement `src/tailor/g2.py`**

Mirror the structure of `src/tailor/s3.py`: module-level `_object`, `_string`,
`_string_array` helpers that raise `G2ParseError`; a strict `json.loads` with no
fence stripping and no repair; `isinstance(value, bool)` rejected before
`isinstance(value, int)` for scores. Build `changed_bullets` from
`bundle.change_log` and `bundle.draft`, never from `bundle.response` directly, so the
critic sees only deterministically derived text. `RULE_VOCABULARY` is a module-level
frozen mapping with the closed rule ids for each dimension, e.g.

```python
RULE_VOCABULARY = {
    G2Dimension.C1: frozenset({"C1.claim_beyond_profile", "C1.evidence_mismatch"}),
    G2Dimension.C2: frozenset({"C2.register_shift", "C2.metric_replaced_by_adjective"}),
    G2Dimension.C3: frozenset({"C3.keyword_chasing", "C3.edit_not_in_coverage"}),
    G2Dimension.C4: frozenset({"C4.signal_below_fold", "C4.impact_diluted"}),
    G2Dimension.C5: frozenset({"C5.template_phrasing", "C5.generic_bullet"}),
}
```

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_g2.py -q
.venv/bin/python -m pytest tests/tailor tests/test_m8p3_integration.py -q
```

Expected: all pass; the M8P-3 suite is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/tailor/g2.py tests/tailor/test_g2.py tests/tailor/conftest.py tests/fixtures/tailor/m8p4_builders.py
git commit -m "feat(m8): add anchored G2 critic contract"
```

---

### Task 2: Verdict rule and finding-resolution checks

**Files:**
- Modify: `src/tailor/g2.py`
- Modify: `tests/tailor/test_g2.py`

**Interfaces:**
- Produces:

```python
class G2Verdict(str, Enum):
    PASS = "pass"; REVISE = "revise"; OPEN_FLAGS = "open_flags"

def evaluate_verdict(response: G2Response, *, round_index: int,
                     max_rounds: int = MAX_ROUNDS) -> G2Verdict: ...
def unresolved_findings(prior: tuple[G2Finding, ...],
                        revised_text_by_target: dict[str, str]) -> tuple[G2Finding, ...]: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.g2 import G2Verdict, evaluate_verdict, unresolved_findings


def test_pass_requires_c1_exactly_three(make_response):
    assert evaluate_verdict(make_response(C1=3, C2=2, C3=2, C4=2, C5=2),
                            round_index=1) is G2Verdict.PASS
    assert evaluate_verdict(make_response(C1=2, C2=3, C3=3, C4=3, C5=3),
                            round_index=1) is G2Verdict.REVISE


def test_any_dimension_at_one_fails(make_response):
    assert evaluate_verdict(make_response(C1=3, C2=1, C3=3, C4=3, C5=3),
                            round_index=1) is G2Verdict.REVISE


def test_final_round_failure_becomes_open_flags(make_response):
    assert evaluate_verdict(make_response(C1=2, C2=3, C3=3, C4=3, C5=3),
                            round_index=2) is G2Verdict.OPEN_FLAGS


def test_unresolved_findings_detects_untouched_quote(one_finding):
    still = unresolved_findings((one_finding,),
                                {"b_edited": "improved throughput by 40%"})
    assert still == (one_finding,)


def test_unresolved_findings_clears_when_quote_gone(one_finding):
    assert unresolved_findings((one_finding,),
                               {"b_edited": "raised throughput 40%"}) == ()
```

`make_response` builds a `G2Response` with one synthetic finding per sub-3 dimension
so the §5 score/finding agreement rule is satisfied.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_g2.py -q -k "verdict or unresolved"`

Expected: FAIL — `ImportError: cannot import name 'evaluate_verdict'`.

- [ ] **Step 3: Implement**

```python
def evaluate_verdict(response, *, round_index, max_rounds=MAX_ROUNDS):
    scores = dict(response.scores)
    passed = scores[G2Dimension.C1] == 3 and min(
        scores[d] for d in (G2Dimension.C2, G2Dimension.C3,
                            G2Dimension.C4, G2Dimension.C5)) >= 2
    if passed:
        return G2Verdict.PASS
    return G2Verdict.OPEN_FLAGS if round_index >= max_rounds else G2Verdict.REVISE
```

`unresolved_findings` returns each prior finding whose `quoted_line` is still an
exact substring of the revised text for its `target_id` (missing target ⇒ resolved).

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_g2.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/g2.py tests/tailor/test_g2.py
git commit -m "feat(m8): add G2 verdict rule and finding resolution"
```

---

### Task 3: Protected G2 prompt

**Files:**
- Create: `docs/prompts/tailoring_g2.md`
- Modify: `tests/tailor/test_g2.py`

**Interfaces:**
- Consumes: `build_g2_prompt`, `G2_REQUEST_MARKER`.
- Produces: the on-disk prompt template.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
from src.tailor.g2 import G2_REQUEST_MARKER, RULE_VOCABULARY, build_g2_prompt

PROMPT = Path("docs/prompts/tailoring_g2.md")


def test_prompt_has_exactly_one_marker():
    assert PROMPT.read_text(encoding="utf-8").count(G2_REQUEST_MARKER) == 1


def test_prompt_documents_every_rule_id():
    text = PROMPT.read_text(encoding="utf-8")
    for ids in RULE_VOCABULARY.values():
        for rule_id in ids:
            assert rule_id in text


def test_prompt_forbids_replacement_text():
    text = PROMPT.read_text(encoding="utf-8").casefold()
    assert "do not propose replacement text" in text


def test_build_prompt_rejects_template_without_marker(g2_request_one_edit):
    import pytest
    with pytest.raises(ValueError):
        build_g2_prompt("no marker here", g2_request_one_edit)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_g2.py -q -k prompt`

Expected: FAIL — `FileNotFoundError: docs/prompts/tailoring_g2.md`.

- [ ] **Step 3: Write the prompt**

Sections, in order: role statement (a fresh critic with no access to the tailor's
reasoning); the untrusted-data delimiter instruction; the five BARS anchors copied
from `TAILORING_METHODOLOGY.md` §4 with C2's anchor examples drawn from the user's
own flagship bullets; the closed `rule_id` table; the exact JSON response shape from
the spec §5; the sentence `Do not propose replacement text.`; the anchoring rule
(`quoted_line` must be an exact substring of the target); the scope rule (findings may
only target changed bullets and accepted skill additions); and the single
`{{G2_REQUEST_JSON}}` marker.

- [ ] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/tailor/test_g2.py -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/prompts/tailoring_g2.md tests/tailor/test_g2.py
git commit -m "feat(m8): add anchored G2 critic prompt"
```

---

### Task 4: Additive S3 revision context (post-M8P-3R integration)

**Files:**
- Modify: `src/tailor/s3.py` (additive only)
- Modify: `src/tailor/s3_pipeline.py` (additive only)
- Create: `tests/tailor/test_s3_revision.py`

**Interfaces:**
- Consumes: `G2Finding` from Task 1; existing `S3Request`, `S3Response`, `parse_s3_response`, `hydrate_s3`, `run_static_g1`.
- Produces:

```python
# src/tailor/s3.py
S3_REVISION_MARKER = "{{S3_REVISION_JSON}}"

@dataclass(frozen=True)
class S3RevisionContext:
    round_index: int
    findings: tuple["G2Finding", ...]

def build_s3_revision_prompt(template: str, request: S3Request,
                             context: S3RevisionContext) -> str: ...
def validate_revision_scope(response: S3Response, previous: S3Response,
                            context: S3RevisionContext) -> None: ...   # raises S3SemanticError

# src/tailor/s3_pipeline.py
def run_s3_revision(request: S3Request, previous: S3Response, *,
                    context: S3RevisionContext,
                    prompt_template_path: Path, request_path: Path,
                    banned_terms: tuple[str, ...],
                    claude_cmd=DEFAULT_CLAUDE_CMD,
                    timeout: float = DEFAULT_TIMEOUT_SECONDS,
                    trace_dir: Path = Path("data/traces")) -> S3Outcome: ...
```

**Stop condition:** if M8P-3R has not merged, do not start this task. Verify with
`git log --oneline -5 main` showing the M8P-3R closing commit.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from src.tailor.s3 import S3RevisionContext, S3SemanticError, validate_revision_scope


def test_revision_may_not_edit_a_bullet_no_finding_named(prev_response, ctx_one_finding,
                                                         make_response_editing):
    revised = make_response_editing("b_untouched")
    with pytest.raises(S3SemanticError, match="outside revision scope"):
        validate_revision_scope(revised, prev_response, ctx_one_finding)


def test_revision_may_edit_a_previously_edited_bullet(prev_response, ctx_one_finding,
                                                      make_response_editing):
    validate_revision_scope(make_response_editing("b_edited"),
                            prev_response, ctx_one_finding)


def test_revision_may_edit_a_bullet_a_finding_named(prev_response, ctx_names_b_flagged,
                                                    make_response_editing):
    validate_revision_scope(make_response_editing("b_flagged"),
                            prev_response, ctx_names_b_flagged)


def test_revision_prompt_requires_its_marker(s3_request, ctx_one_finding):
    from src.tailor.s3 import build_s3_revision_prompt
    with pytest.raises(ValueError):
        build_s3_revision_prompt("{{S3_REQUEST_JSON}} only", s3_request, ctx_one_finding)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_s3_revision.py -q`

Expected: FAIL — `ImportError: cannot import name 'S3RevisionContext'`.

- [ ] **Step 3: Implement, additively**

Append to `src/tailor/s3.py` without touching any existing function body.
`validate_revision_scope` raises `S3SemanticError` when a revised edit's `bullet_id`
is neither in `{e.bullet_id for e in previous.bullet_edits}` nor in
`{f.target_id for f in context.findings if f.target_kind is bullet}`.
`build_s3_revision_prompt` requires both `S3_REQUEST_MARKER` and
`S3_REVISION_MARKER` exactly once each.

Append `run_s3_revision` to `src/tailor/s3_pipeline.py`, reusing the existing
`_trace` helper and the identical parse → `validate_revision_scope` → hydrate →
`run_static_g1` sequence. Do not modify `run_s3_invocation`.

- [ ] **Step 4: Run GREEN and full M8P-3 regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_s3_revision.py -q
.venv/bin/python -m pytest tests/tailor tests/test_tailor_s3_cli.py tests/test_m8p3_integration.py -q
```

Expected: the entire pre-existing M8P-3/M8P-3R suite still passes unchanged. If any
M8P-3R test fails, the change was not additive — revert and re-derive.

- [ ] **Step 5: Commit**

```bash
git add src/tailor/s3.py src/tailor/s3_pipeline.py tests/tailor/test_s3_revision.py
git commit -m "feat(m8): add additive S3 revision context for G2"
```

---

### Task 5: Bounded revision loop, outcome taxonomy, and bundle publication

**Files:**
- Create: `src/tailor/g2_pipeline.py`
- Create: `tests/tailor/test_g2_pipeline.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4 plus `parse_s3_bundle`, `s3_bundle_to_dict`, `write_trace`, `write_json_atomic`, `invoke_text_model`.
- Produces:

```python
TRACE_INVOCATION_TYPE = "tailoring_g2"

class G2OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"
    PARSE_FAILURE = "parse_failure"
    SEMANTIC_FAILURE = "semantic_failure"
    REVISION_INVOCATION_FAILURE = "revision_invocation_failure"
    REVISION_PARSE_FAILURE = "revision_parse_failure"
    REVISION_SEMANTIC_FAILURE = "revision_semantic_failure"
    REVISION_NOOP = "revision_noop"
    REVISION_G1_FAILURE = "revision_g1_failure"
    PASSED_ROUND_1 = "passed_round_1"
    PASSED_ROUND_2 = "passed_round_2"
    OPEN_FLAGS = "open_flags"

@dataclass(frozen=True)
class G2Round:
    round_index: int
    response: G2Response
    verdict: G2Verdict
    trace_path: Path | None

@dataclass(frozen=True)
class G2Bundle:
    schema_version: str          # "m8p4.g2_bundle.v1"
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str
    accepted_s3_bundle: S3Bundle
    rounds: tuple[G2Round, ...]
    verdict: G2Verdict
    open_findings: tuple[G2Finding, ...]
    rounds_used: int
    model_calls: int

@dataclass(frozen=True)
class G2Outcome:
    kind: G2OutcomeKind
    bundle: G2Bundle | None
    error: str | None
    trace_paths: tuple[Path, ...]

def run_g2_loop(s3_request, s3_bundle, *, prompt_template_path, s3_prompt_template_path,
                request_path, banned_terms, taste_lessons, claude_cmd=DEFAULT_CLAUDE_CMD,
                timeout=DEFAULT_TIMEOUT_SECONDS, trace_dir=Path("data/traces"),
                max_rounds=MAX_ROUNDS) -> G2Outcome: ...
def g2_bundle_to_dict(bundle: G2Bundle) -> dict[str, object]: ...
def parse_g2_bundle(raw: object) -> G2Bundle: ...
```

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pathlib import Path
from src.tailor.g2 import G2Verdict
from src.tailor.g2_pipeline import G2OutcomeKind, run_g2_loop


def test_pass_on_round_one_uses_one_model_call(loop_kwargs, mock_invoke_pass):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_1
    assert outcome.bundle.model_calls == 1
    assert outcome.bundle.rounds_used == 1
    assert outcome.bundle.verdict is G2Verdict.PASS


def test_revision_accepted_then_pass_on_round_two(loop_kwargs, mock_invoke_revise_then_pass):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_2
    assert outcome.bundle.rounds_used == 2
    assert outcome.bundle.model_calls == 3   # critic, revision, critic


def test_open_flags_after_two_failing_rounds(loop_kwargs, mock_invoke_always_fail):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.OPEN_FLAGS
    assert outcome.bundle.open_findings


def test_noop_revision_short_circuits_without_second_critic_call(loop_kwargs, mock_invoke_noop_revision):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_NOOP
    assert outcome.bundle is None
    assert mock_invoke_noop_revision.call_count == 2   # critic + revision only


def test_revision_failing_g1_preserves_original_bundle(loop_kwargs, tmp_path,
                                                       mock_invoke_revision_breaks_g1,
                                                       original_bundle_bytes):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE
    assert (tmp_path / "s3_bundle.json").read_bytes() == original_bundle_bytes


def test_invocation_failure_writes_trace_when_raw_output_exists(loop_kwargs, mock_invoke_error_with_stdout):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_paths and outcome.trace_paths[0].exists()


def test_edit_budget_is_recomputed_against_canonical_not_round_one(loop_kwargs,
                                                                  mock_invoke_ratcheting_revision):
    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE


def test_bundle_round_trips_strictly(passing_bundle):
    from src.tailor.g2_pipeline import g2_bundle_to_dict, parse_g2_bundle
    assert parse_g2_bundle(g2_bundle_to_dict(passing_bundle)) == passing_bundle
```

All `mock_invoke_*` fixtures monkeypatch `src.tailor.g2_pipeline.invoke_text_model`
and `src.tailor.s3_pipeline.invoke_text_model` with scripted stdout strings and a
`call_count`. No fixture reaches the network.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_g2_pipeline.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tailor.g2_pipeline'`.

- [ ] **Step 3: Implement**

Follow the exact control flow in the spec §7. Order matters: build the request, call,
trace-if-raw-output, parse, evaluate verdict, and only then decide whether to revise.
Compute `unresolved_findings` **before** spending the second critic call. Recompute
`calculate_edit_budget(request, revised_draft)` against the canonical alignment
inside `run_static_g1`, which already does so — do not add a second budget path.

Publication is the caller's job (Task 6); `run_g2_loop` returns a value and writes
nothing except traces.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_g2_pipeline.py -q
.venv/bin/python -m pytest tests/tailor -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/g2_pipeline.py tests/tailor/test_g2_pipeline.py
git commit -m "feat(m8): add bounded G2 revision loop"
```

---

### Task 6: Fail-closed CLI

**Files:**
- Create: `scripts/tailor_g2.py`
- Create: `tests/test_tailor_g2_cli.py`

**Interfaces:**
- Consumes: `run_g2_loop`, `g2_bundle_to_dict`, `parse_s3_bundle`, `build_g2_request`, `load_banned_terms`, `load_taste_lessons`, `write_json_atomic`, and the same chain revalidation `scripts/tailor_s3.py` already performs.
- Produces: `g2_request.json` and `g2_bundle.json` under `--output`.

- [ ] **Step 1: Write the failing tests**

```python
import json
import subprocess
import sys


def _run(*args, cwd):
    return subprocess.run([sys.executable, "-m", "scripts.tailor_g2", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_prepare_rejects_bundle_with_wrong_fingerprint(tmp_repo, tampered_bundle):
    result = _run("prepare", "--job-id", "1", "--db", str(tmp_repo.db), ...,
                  "--bundle", str(tampered_bundle), "--output", str(tmp_repo.out),
                  cwd=tmp_repo.root)
    assert result.returncode == 1
    assert "fingerprint" in result.stderr
    assert not (tmp_repo.out / "g2_request.json").exists()


def test_prepare_rejects_prohibited_job(tmp_repo):
    result = _run("prepare", "--job-id", "279", "--db", str(tmp_repo.db), ...,
                  cwd=tmp_repo.root)
    assert result.returncode == 1
    assert "prohibited" in result.stderr


def test_invoke_dry_run_makes_no_call_and_no_artifact(tmp_repo, g2_request_file):
    result = _run("invoke", "--request", str(g2_request_file), "--dry-run",
                  "--output", str(tmp_repo.out), cwd=tmp_repo.root)
    assert result.returncode == 0
    assert not (tmp_repo.out / "g2_bundle.json").exists()
    assert not (tmp_repo.root / "data" / "traces").exists()


def test_invoke_failure_preserves_existing_bundle(tmp_repo, existing_g2_bundle_bytes):
    result = _run("invoke", "--request", ..., "--output", str(tmp_repo.out),
                  cwd=tmp_repo.root)
    assert result.returncode == 1
    assert (tmp_repo.out / "g2_bundle.json").read_bytes() == existing_g2_bundle_bytes
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_tailor_g2_cli.py -q`

Expected: FAIL — `No module named scripts.tailor_g2`.

- [ ] **Step 3: Implement**

Mirror `scripts/tailor_s3.py` exactly: `_read`, `_fail`, `cmd_prepare`, `cmd_invoke`,
argparse subcommands, `db.get_readonly_connection`, full chain revalidation, then
`parse_s3_bundle` and a fingerprint equality check against the freshly derived
alignment. Print to stderr on failure and return 1; never print model content beyond
200 characters.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/test_tailor_g2_cli.py -q
.venv/bin/python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/tailor_g2.py tests/test_tailor_g2_cli.py
git commit -m "feat(m8): add one-job G2 CLI"
```

---

### Task 7: Adversarial integration coverage

**Files:**
- Create: `tests/test_m8p4_integration.py`

**Interfaces:**
- Consumes: the real `config/master_profile.yaml`, synthetic upstream artifacts, and mocked invocations.

- [ ] **Step 1: Write the failing tests**

```python
def test_critic_cannot_smuggle_replacement_text(real_profile_chain, mock_invoke_factory):
    """Every field the critic can write is validated; none reaches the draft."""
    smuggle = json.dumps({
        "scores": {"C1": 3, "C2": 2, "C3": 3, "C4": 3, "C5": 3},
        "findings": [{"dimension": "C2", "rule_id": "C2.register_shift",
                      "target_kind": "bullet", "target_id": "b_edited",
                      "quoted_line": "<exact substring>",
                      "explanation": "Replace with: Architected a fault-tolerant K8s mesh"}],
    })
    outcome = run_g2_loop(**real_profile_chain, ...)
    accepted = outcome.bundle.accepted_s3_bundle if outcome.bundle else None
    if accepted:
        for bullet in accepted.draft.bullets:
            assert "fault-tolerant" not in bullet.plain_text
            assert "K8s" not in bullet.plain_text


def test_revision_reintroducing_banned_word_is_rejected(real_profile_chain, mock_invoke_factory):
    ...
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE


def test_revision_dropping_a_metric_is_rejected(real_profile_chain, mock_invoke_factory):
    ...
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE


def test_revision_adding_do_not_claim_term_is_rejected(real_profile_chain, mock_invoke_factory):
    """'Kubernetes' is the real do_not_claim entry in config/master_profile.yaml."""
    ...
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE


def test_no_sqlite_write_occurs(real_profile_chain, db_checksum_before):
    ...
    assert db_checksum_after == db_checksum_before
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_m8p4_integration.py -q`

Expected: FAIL until the scenarios are wired; each must fail for the stated reason,
not from a fixture error.

- [ ] **Step 3: Implement the fixtures**

Reuse `tests/test_m8p3_integration.py`'s approach for building the real-profile
chain. Do not modify that file.

- [ ] **Step 4: Full verification**

```bash
.venv/bin/python -m pytest -q
git diff --check
shasum -a 256 data/jobs.db
```

Expected: full suite green with the M8P-3R baseline plus the new tests; clean
whitespace; checksum `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_m8p4_integration.py
git commit -m "test(m8): cover G2 adversarial contract end to end"
```

---

## Acceptance criteria

- All seven tasks complete; full suite green; `git diff --check` clean; DB checksum unchanged.
- The critic cannot: quote text absent from its target; target an unchanged bullet, project, experience, or the ordering; score a dimension below 3 without a finding; attach a finding to a dimension scored 3; use a `rule_id` from another dimension; emit more than eight findings; or place any replacement text in a field that reaches the draft.
- The verdict function matches `PASS ⟺ C1 == 3 AND min(C2..C5) >= 2` with boundary tests.
- Revisions pass every existing S3 semantic rule, stay within revision scope, must resolve at least one prior finding, must pass full static G1, and are budgeted against the canonical alignment.
- Every terminal outcome preserves prior artifacts byte-for-byte.
- Model-call counts are exact and reported for cost accounting.
- No PDF, no L7, no DB write, no live call, no dependency added.

## Verification commands

```bash
.venv/bin/python -m pytest tests/tailor/test_g2.py tests/tailor/test_g2_pipeline.py tests/tailor/test_s3_revision.py tests/test_tailor_g2_cli.py tests/test_m8p4_integration.py -q
.venv/bin/python -m pytest -q
git diff --check
git status --short
shasum -a 256 data/jobs.db
```

## Stop conditions

- (Resolved — M8P-3R merged at `560ad8d`.) If a rebase ever moves `main` behind that commit, stop: Tasks 1/4/5 all depend on the repaired bundle parser.
- Decision D2 (revision routed through S3) is not confirmed → stop before Task 4 and ask.
- Any pre-existing M8P-3R test fails after Task 4 → the change was not additive; revert and re-derive.
- The DB checksum changes at any point → stop, restore, and report.
- A task cannot be completed without editing an M8P-3R-owned test → stop and ask.

## Documentation deltas (for the integrator, not this branch)

- `docs/ROADMAP.md`: record M8P-4 complete offline; state explicitly that G2 is an anchored critic over the diff and that rendering, L7, `render_line_check`, G3, and both pilots remain incomplete.
- `docs/IMPLEMENTATION_PLAN.md`: add the M8P-4 entry with its commits and verification counts.
- `docs/DECISIONS.md`: record (a) D2's resolution, (b) that §5 of `2026-07-30-m8-tailor-critic-design.md` is superseded, (c) that `docs/prompts/tailoring_g2.md` becomes PROTECTED only after the first accepted live pilot run.
