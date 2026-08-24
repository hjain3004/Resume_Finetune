# M8P-6 G3 Human Review Packet and Feedback Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a two-minute human review packet from already-validated artifacts, and capture the user's judgement as an immutable, versioned, strictly validated feedback record.

**Architecture:** Everything is deterministic derivation — no model call. The packet is Markdown plus a typed JSON twin; the feedback form is YAML the user edits and a strict parser validates against the packet it came from. Records are append-only and revision-numbered so earlier feedback can never be lost or rewritten.

**Tech Stack:** Python 3.11+, frozen dataclasses, stdlib `json`/`datetime`/`pathlib`, existing PyYAML, existing `write_json_atomic`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-m8p-6-g3-packet-feedback-design.md`

**Can implementation start before M8P-3R merges?** M8P-3R **merged at `560ad8d`**. Tasks 1–3 (the feedback contract, storage, and taste derivation) were parallel-safe regardless and can start now. Tasks 4–6 still require M8P-4 and M8P-5 merged, because the packet embeds their types.

## Global Constraints

- Read `AGENTS.md`, `docs/TAILORING_METHODOLOGY.md` §4–§5, `docs/TAILORING_SPEC.md` §5, the spec above, and the merged M8P-4/M8P-5 code before Task 4.
- Implement M8P-6 only. Do not start the golden set, the D2 drift harness, gap aggregation, `applications/by-date/`, DB mutation, Company Bank integration, a model call, a pilot, or SkillOpt.
- **No web UI, no server, no frontend dependency.** The packet is Markdown; the form is YAML.
- **No model call anywhere in this milestone.** A test asserts no module in `src/tailor/g3.py` or `src/tailor/feedback.py` imports `src.tailor.invoke` or `src.llm_trace`.
- **Never write** `config/taste.md`, `config/banned_words.txt`, or any file under `docs/prompts/`. A test asserts their bytes are unchanged after the full suite.
- **Never edit** `src/tailor/s3.py`, `g1.py`, `s3_pipeline.py`, `scripts/tailor_s3.py`, `src/tailor/g2*.py`, `src/tailor/publish.py`, `src/render/*`, or their tests. Import read-only.
- No new dependency. No network. No SQLite write.
- Feedback lives under `data/feedback/`; `data/` is already gitignored. Tests use `tmp_path`.
- Frozen dataclasses at boundaries; parsing separated from I/O.
- Baseline DB SHA-256: `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- TDD per task: focused RED, minimal GREEN, regression, commit.
- Do not edit `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md`.

## Predecessor contracts and blockers

Tasks 1–3 consume only plain values: `job_id: int`, `alignment_fingerprint: str`,
`changed_bullet_ids: frozenset[str]`, and `bullet_plain_text_by_id: dict[str, str]`.
That is deliberate — it is what makes them parallel-safe.

Tasks 4–6 additionally consume:

```python
# src/tailor/s3_pipeline.py   (M8P-3R)
S3Bundle(schema_version, job_id, company, title, alignment_fingerprint, response,
         draft, change_log, unified_diff, edit_budget, g1)
parse_s3_bundle(raw, request: S3Request, banned_terms: tuple[str, ...]) -> S3Bundle
#   VERIFIED signature (src/tailor/s3_pipeline.py:155). Three arguments, not one:
#   it recomputes every derived field from the authoritative request, so a caller must
#   first rebuild the S3Request from the upstream chain.

# src/tailor/g2_pipeline.py   (M8P-4)
G2Bundle(schema_version, job_id, company, title, alignment_fingerprint,
         accepted_s3_bundle, rounds, verdict, open_findings, rounds_used, model_calls)
parse_g2_bundle(raw) -> G2Bundle

# src/tailor/publish.py       (M8P-5)
RenderResult(...)  ;  parse_render_result(raw) -> RenderResult

# src/tailor/s1.py / s0.py / s2.py
S1Response, S0Response, S2Response and their strict parsers
```

**Blocker B1:** Tasks 4–6 do not start until `git log --oneline main` shows both the
M8P-4 and M8P-5 closing commits.

**Blocker B2:** if M8P-4 or M8P-5 named a type differently, use the merged name and
note the deviation in the Documentation deltas section. Do not add aliases.

## Target files

Create: `src/tailor/feedback.py`, `src/tailor/g3.py`, `scripts/tailor_g3.py`,
`tests/tailor/test_feedback.py`, `tests/tailor/test_g3.py`,
`tests/test_tailor_g3_cli.py`, `tests/test_m8p6_integration.py`,
`tests/fixtures/tailor/m8p6_forms.py`.

Modify: nothing outside the created set.

## Privacy boundaries

The packet contains the company, title, JD quotes, and the user's own resume text. It
is written into the gitignored `applications/` directory beside the PDF. Feedback
records go under gitignored `data/feedback/`. No packet, form, or record is ever
written into a git-tracked path. A test asserts the default feedback directory
resolves under `data/`.

---

### Task 1: Feedback record contract and strict form parsing

**Files:**
- Create: `src/tailor/feedback.py`
- Create: `tests/tailor/test_feedback.py`
- Create: `tests/fixtures/tailor/m8p6_forms.py`

**Interfaces:**
- Consumes: PyYAML, stdlib only.
- Produces:

```python
FEEDBACK_SCHEMA = "m8p6.feedback_record.v1"

class FeedbackParseError(ValueError): ...
class FeedbackValidationError(ValueError): ...

class Accept(str, Enum):        ACCEPT = "accept"; REJECT = "reject"
class WouldSubmit(str, Enum):   YES = "yes"; NO = "no"; NOT_AS_IS = "not_as_is"
class YesNo(str, Enum):         YES = "yes"; NO = "no"
class BulletVerdict(str, Enum): KEEP = "keep"; REWORD = "reword"; REVERT = "revert"

@dataclass(frozen=True)
class BulletFeedback:
    bullet_id: str
    verdict: BulletVerdict
    comment: str

@dataclass(frozen=True)
class UnsupportedClaim:
    bullet_id: str
    quoted_text: str
    why: str

@dataclass(frozen=True)
class FeedbackRecord:
    schema_version: str
    job_id: int
    alignment_fingerprint: str
    reviewed_at: str                     # YYYY-MM-DD
    accept: Accept
    would_submit: WouldSubmit
    needs_another_revision: YesNo
    company_alignment: int               # 1..3
    visual_quality: int                  # 1..3
    bullet_feedback: tuple[BulletFeedback, ...]
    missing_skills: tuple[str, ...]
    overemphasized_skills: tuple[str, ...]
    unsupported_claims: tuple[UnsupportedClaim, ...]
    free_form: str

def build_feedback_form(job_id: int, alignment_fingerprint: str,
                        changed_bullet_ids: tuple[str, ...]) -> str: ...
def parse_feedback_form(text: str, *, job_id: int, alignment_fingerprint: str,
                        changed_bullet_ids: frozenset[str],
                        bullet_plain_text_by_id: dict[str, str]) -> FeedbackRecord: ...
def feedback_record_to_dict(record: FeedbackRecord) -> dict[str, object]: ...
def parse_feedback_record(raw: object) -> FeedbackRecord: ...
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/fixtures/tailor/m8p6_forms.py
"""Synthetic feedback forms for M8P-6. No model, no network, no DB."""
import yaml

BASE = {
    "schema_version": "m8p6.feedback_record.v1",
    "job_id": 225,
    "alignment_fingerprint": "fp0123456789ab",
    "reviewed_at": "2026-08-24",
    "accept": "accept",
    "would_submit": "yes",
    "needs_another_revision": "no",
    "company_alignment": 3,
    "visual_quality": 3,
    "bullet_feedback": [{"bullet_id": "b1", "verdict": "keep", "comment": ""}],
    "missing_skills": [],
    "overemphasized_skills": [],
    "unsupported_claims": [],
    "free_form": "",
}


def form(**overrides) -> str:
    data = {**BASE, **overrides}
    return yaml.safe_dump(data, sort_keys=False)
```

```python
# tests/tailor/test_feedback.py
import pytest
from src.tailor.feedback import (
    Accept, FeedbackParseError, FeedbackValidationError, WouldSubmit,
    build_feedback_form, feedback_record_to_dict, parse_feedback_form,
    parse_feedback_record,
)
from tests.fixtures.tailor.m8p6_forms import form

KW = dict(job_id=225, alignment_fingerprint="fp0123456789ab",
          changed_bullet_ids=frozenset({"b1"}),
          bullet_plain_text_by_id={"b1": "Cut p99 latency 40% by sharding the write path"})


def test_emitted_form_parses_after_the_required_fields_are_filled():
    blank = build_feedback_form(225, "fp0123456789ab", ("b1",))
    assert "bullet_id: b1" in blank
    with pytest.raises(FeedbackValidationError):
        parse_feedback_form(blank, **KW)      # empty enums must not default


def test_valid_form_round_trips():
    record = parse_feedback_form(form(), **KW)
    assert record.accept is Accept.ACCEPT
    assert parse_feedback_record(feedback_record_to_dict(record)) == record


def test_accept_with_would_not_submit_is_preserved():
    record = parse_feedback_form(form(would_submit="no"), **KW)
    assert record.accept is Accept.ACCEPT and record.would_submit is WouldSubmit.NO


def test_empty_required_enum_is_rejected():
    with pytest.raises(FeedbackValidationError, match="accept"):
        parse_feedback_form(form(accept=""), **KW)


def test_out_of_range_score_is_rejected():
    with pytest.raises(FeedbackValidationError, match="visual_quality"):
        parse_feedback_form(form(visual_quality=4), **KW)


def test_boolean_score_is_rejected():
    with pytest.raises(FeedbackValidationError, match="company_alignment"):
        parse_feedback_form(form(company_alignment=True), **KW)


def test_malformed_date_is_rejected():
    with pytest.raises(FeedbackValidationError, match="reviewed_at"):
        parse_feedback_form(form(reviewed_at="24-08-2026"), **KW)


def test_missing_bullet_feedback_entry_is_rejected():
    with pytest.raises(FeedbackValidationError, match="bullet_feedback"):
        parse_feedback_form(form(bullet_feedback=[]), **KW)


def test_extra_bullet_feedback_entry_is_rejected():
    extra = [{"bullet_id": "b1", "verdict": "keep", "comment": ""},
             {"bullet_id": "b_unknown", "verdict": "keep", "comment": ""}]
    with pytest.raises(FeedbackValidationError, match="b_unknown"):
        parse_feedback_form(form(bullet_feedback=extra), **KW)


def test_duplicate_bullet_feedback_entry_is_rejected():
    dup = [{"bullet_id": "b1", "verdict": "keep", "comment": ""},
           {"bullet_id": "b1", "verdict": "reword", "comment": "x"}]
    with pytest.raises(FeedbackValidationError, match="duplicate"):
        parse_feedback_form(form(bullet_feedback=dup), **KW)


def test_unsupported_claim_quote_must_be_an_exact_substring():
    claim = [{"bullet_id": "b1", "quoted_text": "never appeared", "why": "misleading"}]
    with pytest.raises(FeedbackValidationError, match="quoted_text"):
        parse_feedback_form(form(unsupported_claims=claim), **KW)


def test_unsupported_claim_with_a_real_substring_is_accepted():
    claim = [{"bullet_id": "b1", "quoted_text": "sharding the write path", "why": "I only tuned it"}]
    record = parse_feedback_form(form(unsupported_claims=claim), **KW)
    assert record.unsupported_claims[0].bullet_id == "b1"


def test_fingerprint_disagreement_is_rejected():
    with pytest.raises(FeedbackValidationError, match="fingerprint"):
        parse_feedback_form(form(alignment_fingerprint="different"), **KW)


def test_unknown_schema_version_is_rejected():
    with pytest.raises(FeedbackValidationError, match="schema_version"):
        parse_feedback_form(form(schema_version="m8p6.feedback_record.v99"), **KW)


def test_non_mapping_yaml_is_a_parse_error():
    with pytest.raises(FeedbackParseError):
        parse_feedback_form("- just\n- a list\n", **KW)


def test_duplicate_missing_skill_terms_are_rejected():
    with pytest.raises(FeedbackValidationError, match="missing_skills"):
        parse_feedback_form(form(missing_skills=["Go", "go"]), **KW)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_feedback.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tailor.feedback'`.

- [ ] **Step 3: Implement**

Use `yaml.safe_load`. Reject non-mapping documents with `FeedbackParseError`; every
content rule raises `FeedbackValidationError`. Check `isinstance(value, bool)` before
`isinstance(value, int)`. Validate the date with
`datetime.date.fromisoformat(value)` inside a `try`. Deduplicate skill terms under
casefolded, whitespace-collapsed comparison and reject collisions rather than
silently merging.

`build_feedback_form` emits the exact YAML in the spec §5 with one `bullet_feedback`
entry per changed bullet id, in the given order, and every enum value empty.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_feedback.py -q
.venv/bin/python -m pytest tests/tailor -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/feedback.py tests/tailor/test_feedback.py tests/fixtures/tailor/m8p6_forms.py
git commit -m "feat(m8): add validated human feedback contract"
```

---

### Task 2: Immutable append-only feedback storage and summary

**Files:**
- Modify: `src/tailor/feedback.py`
- Modify: `tests/tailor/test_feedback.py`

**Interfaces:**
- Consumes: `FeedbackRecord`, `write_json_atomic`.
- Produces:

```python
DEFAULT_FEEDBACK_DIR = Path("data/feedback")

class FeedbackOutcomeKind(str, Enum):
    PARSE_FAILURE = "parse_failure"
    VALIDATION_FAILURE = "validation_failure"
    ALREADY_RECORDED = "already_recorded"
    RECORDED = "recorded"

@dataclass(frozen=True)
class FeedbackOutcome:
    kind: FeedbackOutcomeKind
    path: Path | None
    revision: int | None
    error: str | None

@dataclass(frozen=True)
class FeedbackSummary:
    total: int
    accepted: int
    rejected: int
    would_submit_yes: int
    would_submit_no: int
    would_submit_not_as_is: int
    needs_revision: int
    mean_company_alignment: float
    mean_visual_quality: float
    distinct_jobs: int

def store_feedback(record: FeedbackRecord, *, feedback_dir: Path = DEFAULT_FEEDBACK_DIR) -> FeedbackOutcome: ...
def load_feedback_index(feedback_dir: Path = DEFAULT_FEEDBACK_DIR) -> tuple[dict[str, object], ...]: ...
def summarize_feedback(feedback_dir: Path = DEFAULT_FEEDBACK_DIR, *, job_id: int | None = None) -> FeedbackSummary: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from src.tailor.feedback import (
    FeedbackOutcomeKind, DEFAULT_FEEDBACK_DIR, load_feedback_index,
    store_feedback, summarize_feedback,
)


def test_default_feedback_dir_is_under_gitignored_data():
    assert DEFAULT_FEEDBACK_DIR.parts[0] == "data"


def test_first_record_is_revision_one(tmp_path, record):
    outcome = store_feedback(record, feedback_dir=tmp_path)
    assert outcome.kind is FeedbackOutcomeKind.RECORDED
    assert outcome.revision == 1
    assert outcome.path.name.endswith("-r1.json")
    assert len(load_feedback_index(tmp_path)) == 1


def test_identical_rerecord_is_idempotent(tmp_path, record):
    store_feedback(record, feedback_dir=tmp_path)
    before = (tmp_path / "index.jsonl").read_bytes()
    outcome = store_feedback(record, feedback_dir=tmp_path)
    assert outcome.kind is FeedbackOutcomeKind.ALREADY_RECORDED
    assert (tmp_path / "index.jsonl").read_bytes() == before


def test_differing_second_assessment_creates_r2_and_preserves_r1(tmp_path, record, revised_record):
    first = store_feedback(record, feedback_dir=tmp_path)
    original = first.path.read_bytes()
    second = store_feedback(revised_record, feedback_dir=tmp_path)
    assert second.revision == 2
    assert first.path.read_bytes() == original
    assert len(load_feedback_index(tmp_path)) == 2


def test_records_for_different_fingerprints_do_not_collide(tmp_path, record, other_fingerprint_record):
    store_feedback(record, feedback_dir=tmp_path)
    other = store_feedback(other_fingerprint_record, feedback_dir=tmp_path)
    assert other.revision == 1


def test_summary_counts_match_the_records(tmp_path, mixed_records):
    for item in mixed_records:
        store_feedback(item, feedback_dir=tmp_path)
    summary = summarize_feedback(tmp_path)
    assert summary.total == len(mixed_records)
    assert summary.accepted + summary.rejected == summary.total
    assert 1.0 <= summary.mean_visual_quality <= 3.0


def test_summary_can_filter_by_job(tmp_path, mixed_records):
    for item in mixed_records:
        store_feedback(item, feedback_dir=tmp_path)
    assert summarize_feedback(tmp_path, job_id=225).total < summarize_feedback(tmp_path).total


def test_summary_is_read_only(tmp_path, record):
    store_feedback(record, feedback_dir=tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    summarize_feedback(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_feedback.py -q -k "store or summar or index"`

Expected: FAIL — `ImportError: cannot import name 'store_feedback'`.

- [ ] **Step 3: Implement**

The record filename is
`f"{record.job_id}-{record.alignment_fingerprint[:12]}-r{revision}.json"`. Determine
the next revision by globbing `f"{job_id}-{fp12}-r*.json"` and taking `max + 1`. Read
the highest existing revision and compare serialized dicts for the idempotency check
before writing anything. Write the record with `write_json_atomic`, then append one
line to `index.jsonl` with an `"a"`-mode open and an explicit `\n`.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_feedback.py -q
.venv/bin/python -m pytest tests/tailor -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/feedback.py tests/tailor/test_feedback.py
git commit -m "feat(m8): store human feedback immutably"
```

---

### Task 3: Taste-candidate derivation (pure, writes nothing)

**Files:**
- Modify: `src/tailor/feedback.py`
- Modify: `tests/tailor/test_feedback.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class TasteCandidate:
    date: str
    lesson: str
    mechanically_enforceable: bool
    evidence: str

def derive_taste_candidates(record: FeedbackRecord) -> tuple[TasteCandidate, ...]: ...
```

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
from src.tailor.feedback import derive_taste_candidates


def test_reword_with_comment_yields_a_candidate(record_with_reword):
    candidates = derive_taste_candidates(record_with_reword)
    assert any("reword" in c.evidence for c in candidates)
    assert all(c.date == record_with_reword.reviewed_at for c in candidates)


def test_reword_without_comment_yields_nothing(record_with_empty_reword_comment):
    assert derive_taste_candidates(record_with_empty_reword_comment) == ()


def test_overemphasized_skill_is_mechanically_enforceable(record_overemphasized):
    candidate = next(c for c in derive_taste_candidates(record_overemphasized)
                     if "overemphas" in c.evidence)
    assert candidate.mechanically_enforceable is True


def test_unsupported_claim_is_not_mechanically_enforceable(record_unsupported):
    candidate = next(c for c in derive_taste_candidates(record_unsupported)
                     if "unsupported" in c.evidence)
    assert candidate.mechanically_enforceable is False


def test_derivation_writes_nothing(record_with_reword):
    taste_before = Path("config/taste.md").read_bytes()
    banned_before = Path("config/banned_words.txt").read_bytes()
    derive_taste_candidates(record_with_reword)
    assert Path("config/taste.md").read_bytes() == taste_before
    assert Path("config/banned_words.txt").read_bytes() == banned_before


def test_derivation_is_deterministic(record_with_reword):
    assert derive_taste_candidates(record_with_reword) == derive_taste_candidates(record_with_reword)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_feedback.py -q -k taste`

Expected: FAIL — `ImportError: cannot import name 'derive_taste_candidates'`.

- [ ] **Step 3: Implement**

One candidate per non-empty `reword` comment (`mechanically_enforceable=False`), one
per `overemphasized_skills` term (`True`, because the term itself could join a lint
list), and one per `unsupported_claims` entry (`False`). Sort deterministically by
`(evidence, lesson)`.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_feedback.py -q
.venv/bin/python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/feedback.py tests/tailor/test_feedback.py
git commit -m "feat(m8): derive taste candidates from feedback"
```

---

### Task 4: Rebase and confirm M8P-4 and M8P-5 are merged

**Files:** none created; integration checkpoint.

- [ ] **Step 1: Confirm both predecessors merged**

```bash
git log --oneline -20 main | grep -E "G2|render"
```

Expected: both the M8P-4 and M8P-5 closing commits are present. If not, STOP.

- [ ] **Step 2: Rebase and verify the consumed types exist**

```bash
git rebase main
.venv/bin/python -c "
from src.tailor.g2_pipeline import G2Bundle, parse_g2_bundle
from src.tailor.publish import RenderResult, parse_render_result
from src.tailor.s3_pipeline import S3Bundle, parse_s3_bundle
print('predecessor types present')
"
```

- [ ] **Step 3: Re-run everything**

```bash
.venv/bin/python -m pytest -q
shasum -a 256 data/jobs.db
```

---

### Task 5: Review packet builder

**Files:**
- Create: `src/tailor/g3.py`
- Create: `tests/tailor/test_g3.py`

**Interfaces:**
- Consumes: `S3Bundle`, `G2Bundle`, `RenderResult`, `S1Response`, `S0Response`, `S2Response`, `FeedbackRecord` helpers.
- Produces:

```python
PACKET_SCHEMA = "m8p6.review_packet.v1"
MAX_LISTED_REQUIREMENTS = 12

class G3Error(ValueError): ...

class G3OutcomeKind(str, Enum):
    INPUT_MISMATCH = "input_mismatch"
    ALREADY_BUILT = "already_built"
    CONFLICT = "conflict"
    BUILT = "built"

@dataclass(frozen=True)
class ReviewPacket:
    schema_version: str
    job_id: int
    company: str
    title: str
    base_variant: str
    alignment_fingerprint: str
    pdf_path: str
    gate_status_line: str
    warnings: tuple[str, ...]
    requirements: tuple[tuple[str, str], ...]        # (term, jd_quote)
    requirements_omitted: int
    selection_reasons: tuple[tuple[str, str], ...]   # (project_id, reason)
    positioning: tuple[str, ...]                     # S0 brief sentences, verbatim
    changes: tuple[tuple[str, str, str, str, str], ...]  # location, before, after, quote, rule
    coverage: tuple[tuple[str, str, tuple[str, ...]], ...]
    edit_budget: tuple[int, int, float]
    g1_violations: tuple[str, ...]
    g2_rounds: tuple[tuple[int, tuple[tuple[str, int], ...], tuple[str, ...]], ...]
    l7_violations: tuple[str, ...]
    line_counts: tuple[tuple[str, int], ...]
    unified_diff: str

@dataclass(frozen=True)
class G3Outcome:
    kind: G3OutcomeKind
    packet: ReviewPacket | None
    error: str | None

def build_review_packet(s3_bundle, g2_bundle, render_result, s1, s0, s2) -> ReviewPacket: ...
def render_review_markdown(packet: ReviewPacket) -> str: ...
def packet_to_dict(packet: ReviewPacket) -> dict[str, object]: ...
def parse_packet(raw: object) -> ReviewPacket: ...
def publish_packet(packet: ReviewPacket, changed_bullet_ids: tuple[str, ...],
                   directory: Path) -> G3Outcome: ...
```

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from src.tailor.g3 import (
    G3OutcomeKind, MAX_LISTED_REQUIREMENTS, build_review_packet, packet_to_dict,
    parse_packet, publish_packet, render_review_markdown,
)


def test_markdown_sections_appear_in_fixed_order(full_inputs):
    text = render_review_markdown(build_review_packet(*full_inputs))
    order = ["## Warnings and open flags", "## What this job asks for",
             "## What was selected and why", "## What changed", "## Coverage",
             "## Gate detail", "## Full diff"]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_empty_warnings_render_as_none_not_omitted(clean_inputs):
    text = render_review_markdown(build_review_packet(*clean_inputs))
    section = text.split("## Warnings and open flags", 1)[1].split("##", 1)[0]
    assert "None." in section


def test_long_requirement_list_is_capped_explicitly(many_requirements_inputs):
    packet = build_review_packet(*many_requirements_inputs)
    assert len(packet.requirements) == MAX_LISTED_REQUIREMENTS
    assert packet.requirements_omitted > 0
    assert f"(+{packet.requirements_omitted} more)" in render_review_markdown(packet)


def test_markdown_is_byte_identical_across_runs(full_inputs):
    packet = build_review_packet(*full_inputs)
    assert render_review_markdown(packet) == render_review_markdown(packet)


def test_packet_round_trips_strictly(full_inputs):
    packet = build_review_packet(*full_inputs)
    assert parse_packet(packet_to_dict(packet)) == packet


def test_fingerprint_disagreement_between_inputs_fails_closed(mismatched_inputs):
    from src.tailor.g3 import G3Error
    with pytest.raises(G3Error, match="fingerprint"):
        build_review_packet(*mismatched_inputs)


def test_gap_terms_and_open_findings_appear_in_warnings(gap_and_flag_inputs):
    packet = build_review_packet(*gap_and_flag_inputs)
    joined = " ".join(packet.warnings)
    assert "GAP" in joined
    assert "C5" in joined


def test_publish_refuses_to_overwrite_a_different_packet(full_inputs, tmp_path, other_inputs):
    packet = build_review_packet(*full_inputs)
    publish_packet(packet, ("b1",), tmp_path)
    before = (tmp_path / "packet.json").read_bytes()
    outcome = publish_packet(build_review_packet(*other_inputs), ("b1",), tmp_path)
    assert outcome.kind is G3OutcomeKind.CONFLICT
    assert (tmp_path / "packet.json").read_bytes() == before


def test_publish_is_idempotent_for_the_same_packet(full_inputs, tmp_path):
    packet = build_review_packet(*full_inputs)
    publish_packet(packet, ("b1",), tmp_path)
    assert publish_packet(packet, ("b1",), tmp_path).kind is G3OutcomeKind.ALREADY_BUILT


def test_publish_emits_all_three_files(full_inputs, tmp_path):
    publish_packet(build_review_packet(*full_inputs), ("b1",), tmp_path)
    for name in ("review.md", "packet.json", "feedback_form.yaml"):
        assert (tmp_path / name).exists()


def test_g3_module_makes_no_model_call():
    from pathlib import Path
    source = Path("src/tailor/g3.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in source and "src.llm_trace" not in source
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/tailor/test_g3.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.tailor.g3'`.

- [ ] **Step 3: Implement**

`build_review_packet` first checks that `s3_bundle.alignment_fingerprint`,
`g2_bundle.alignment_fingerprint`, and `render_result.alignment_fingerprint` are all
equal and that all three carry the same `job_id`; otherwise raise `G3Error`.

`render_review_markdown` writes plain GitHub-flavoured Markdown with a fixed heading
set and a table for the change log. No timestamps, no absolute paths, no random
ordering — the byte-identical test depends on that.

`publish_packet` writes `review.md`, `packet.json` (via `write_json_atomic`), and
`feedback_form.yaml` (from `feedback.build_feedback_form`), branching to
`ALREADY_BUILT`/`CONFLICT` on an existing `packet.json`.

- [ ] **Step 4: Run GREEN and regression**

```bash
.venv/bin/python -m pytest tests/tailor/test_g3.py -q
.venv/bin/python -m pytest tests/tailor tests/render -q
```

- [ ] **Step 5: Commit**

```bash
git add src/tailor/g3.py tests/tailor/test_g3.py
git commit -m "feat(m8): build the G3 human review packet"
```

---

### Task 6: CLI and integration coverage

**Files:**
- Create: `scripts/tailor_g3.py`
- Create: `tests/test_tailor_g3_cli.py`
- Create: `tests/test_m8p6_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `build`, `record`, and `summarize` subcommands.

- [ ] **Step 1: Write the failing tests**

```python
import subprocess
import sys


def _run(*args, cwd):
    return subprocess.run([sys.executable, "-m", "scripts.tailor_g3", *args],
                          capture_output=True, text=True, cwd=cwd)


def test_build_writes_the_three_packet_files(tmp_repo, bundles):
    result = _run("build", "--bundle", str(bundles.s3), "--g2-bundle", str(bundles.g2),
                  "--render-result", str(bundles.render), "--s1", str(bundles.s1),
                  "--s0", str(bundles.s0), "--s2", str(bundles.s2),
                  "--output", str(tmp_repo.app_dir), cwd=tmp_repo.root)
    assert result.returncode == 0
    for name in ("review.md", "packet.json", "feedback_form.yaml"):
        assert (tmp_repo.app_dir / name).exists()


def test_build_rejects_mismatched_fingerprints(tmp_repo, mismatched_bundles):
    result = _run("build", "--bundle", str(mismatched_bundles.s3), ..., cwd=tmp_repo.root)
    assert result.returncode == 1
    assert "fingerprint" in result.stderr


def test_record_rejects_an_invalid_form_and_stores_nothing(tmp_repo, built_packet, bad_form):
    result = _run("record", "--form", str(bad_form), "--packet", str(built_packet),
                  "--feedback-dir", str(tmp_repo.feedback), cwd=tmp_repo.root)
    assert result.returncode == 1
    assert not list(tmp_repo.feedback.glob("*.json"))


def test_record_then_summarize(tmp_repo, built_packet, good_form):
    assert _run("record", "--form", str(good_form), "--packet", str(built_packet),
                "--feedback-dir", str(tmp_repo.feedback), cwd=tmp_repo.root).returncode == 0
    result = _run("summarize", "--feedback-dir", str(tmp_repo.feedback), cwd=tmp_repo.root)
    assert result.returncode == 0
    assert "total: 1" in result.stdout


def test_summarize_writes_nothing(tmp_repo, recorded_feedback):
    before = sorted(p.name for p in tmp_repo.feedback.iterdir())
    _run("summarize", "--feedback-dir", str(tmp_repo.feedback), cwd=tmp_repo.root)
    assert sorted(p.name for p in tmp_repo.feedback.iterdir()) == before
```

```python
# tests/test_m8p6_integration.py
def test_protected_config_files_are_never_written(tmp_repo, bundles, good_form):
    """M8P-6 derives taste candidates; it never edits taste.md or banned_words.txt."""
    from pathlib import Path
    before = {p: Path(p).read_bytes() for p in ("config/taste.md", "config/banned_words.txt")}
    # run build + record end to end
    ...
    for path, content in before.items():
        assert Path(path).read_bytes() == content


def test_no_sqlite_write(db_checksum_before, bundles, good_form):
    ...
    assert db_checksum_after == db_checksum_before


def test_second_differing_assessment_preserves_the_first(tmp_repo, built_packet, good_form, revised_form):
    ...
    assert first_record_bytes_unchanged
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_tailor_g3_cli.py tests/test_m8p6_integration.py -q`

Expected: FAIL — `No module named scripts.tailor_g3`.

- [ ] **Step 3: Implement**

Mirror `scripts/tailor_s3.py`'s structure: `_read`, `_fail`, one `cmd_*` per
subcommand, argparse subparsers, stderr on failure with return code 1.

- [ ] **Step 4: Full verification**

```bash
.venv/bin/python -m pytest -q
git diff --check
shasum -a 256 data/jobs.db
```

- [ ] **Step 5: Commit**

```bash
git add scripts/tailor_g3.py tests/test_tailor_g3_cli.py tests/test_m8p6_integration.py
git commit -m "feat(m8): add G3 packet and feedback CLI"
```

---

## Acceptance criteria

- The packet renders every section in fixed order, prints `None.` for empty sections, caps long lists with an explicit `(+N more)`, and is byte-identical across runs.
- Every packet input is fingerprint- and job-id-bound; a disagreement fails closed.
- The form parser rejects each of the fourteen invalid cases enumerated in the design §12.
- `accept` + `would_submit == no` is preserved as a distinct signal.
- Feedback storage is immutable and append-only; a differing second assessment becomes `r2` with `r1` byte-identical; an identical re-record is `ALREADY_RECORDED` and appends no index line.
- `summarize` is read-only and reports the counts M8P-8's gate consumes.
- `derive_taste_candidates` writes nothing; `config/taste.md` and `config/banned_words.txt` are byte-identical after the full suite.
- No web UI, no server, no model call, no dependency, no SQLite write.
- Full suite green; `git diff --check` clean; DB SHA-256 unchanged.

## Verification commands

```bash
.venv/bin/python -m pytest tests/tailor/test_feedback.py tests/tailor/test_g3.py tests/test_tailor_g3_cli.py tests/test_m8p6_integration.py -q
.venv/bin/python -m pytest -q
git diff --check
git status --short
shasum -a 256 data/jobs.db
```

## Stop conditions

- Tasks 4–6 started before both M8P-4 and M8P-5 merged → stop.
- A task appears to need a web UI, a server, or a new dependency → stop and ask; the design forbids all three.
- A task appears to need writes to `config/taste.md`, `config/banned_words.txt`, or `docs/prompts/` → stop; that belongs to M8P-7.
- The DB checksum changes → stop, restore, report.

## Documentation deltas (for the integrator, not this branch)

- `docs/ROADMAP.md`: record M8P-6 complete; state that G3 is a deterministic Markdown packet plus a YAML feedback contract, with no web UI and no model call, and that both pilots remain incomplete.
- `docs/IMPLEMENTATION_PLAN.md`: add the M8P-6 entry with commits and verification counts.
- `docs/ARCHITECTURE.md` §2: add `data/feedback/` (gitignored) and the new `src/tailor/` modules.
- `docs/DECISIONS.md`: record that the G3 review surface is files rather than a web UI; that feedback records are immutable and revision-numbered; and that `accept` and `would_submit` are deliberately separate fields.
