# M8Q-0A Resume Evidence Bank Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, fully offline contracts, validation, reporting, lookup, and atomic-promotion foundation for an early-career resume evidence bank.

**Architecture:** Private research bundles under Git-ignored `data/resume_research/` are untrusted inputs. Frozen dataclasses and strict YAML parsers validate structure; pure policy functions recompute experience, evidence anchoring, admission, duplicate detection, and editorial completeness; an atomic importer promotes only canonical metadata and derived annotations into `config/resume_evidence_bank/`. This milestone performs no live research and stops before M8Q-0B.

**Tech Stack:** Python 3.11+, standard library, frozen dataclasses, `Enum`, `pathlib`, `hashlib`, `urllib.parse`, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-early-career-resume-evidence-bank-design.md`

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and the spec in full before editing.
- One milestone only: implement M8Q-0A and stop. Do not run the three-page smoke or start M8Q-0B.
- Preserve existing user-owned changes, especially `inbox/urls.txt`, `docs/sampleJD.md`, `config/master_profile.yaml`, and tailoring prompts.
- Add no dependency. Do not import Firecrawl, Crawl4AI, requests, SQLite, or tailoring modules into `src/resume_evidence/`.
- Tests never access the network and use only synthetic/minimal fixtures.
- Do not open `data/jobs.db` for write; record its SHA-256 before and after the milestone.
- Raw research content remains under ignored `data/`; tracked fixtures may contain only synthetic names, text, dates, and outcomes.
- No LinkedIn scraping or source acquisition occurs in this milestone.
- No complete public resume, screenshot, PDF, or paid-book text is committed.
- Every parser is strict: reject unknown keys, missing keys, duplicate mapping keys, booleans where integers are required, non-string enums, unsafe URLs, and non-UTC timestamps.
- CLI exit codes are `0` success, `1` validation/contract failure, `2` unreadable/internal failure, and `3` lookup missing.
- Use TDD. Every production behavior is preceded by a focused failing test.
- End each task with the focused tests, then a scoped commit. Never push.

## File Structure

**Create:**

- `src/resume_evidence/__init__.py` — public exports only.
- `src/resume_evidence/model.py` — enums and frozen dataclasses.
- `src/resume_evidence/serde.py` — strict YAML parsing and stable serialization.
- `src/resume_evidence/experience.py` — month parsing, interval merging, 0–36-month recomputation.
- `src/resume_evidence/policy.py` — URL, evidence, privacy, doctrine, pattern, and admission validation.
- `src/resume_evidence/duplicates.py` — URL/content/signature duplicate analysis.
- `src/resume_evidence/report.py` — deterministic JSON/Markdown review report.
- `src/resume_evidence/store.py` — strict canonical loader and advisory lookup.
- `src/resume_evidence/importer.py` — whole-corpus validation and atomic promotion.
- `scripts/resume_evidence.py` — thin offline CLI.
- `tests/resume_evidence/conftest.py` — synthetic bundle builders.
- `tests/resume_evidence/test_model.py`
- `tests/resume_evidence/test_serde.py`
- `tests/resume_evidence/test_experience.py`
- `tests/resume_evidence/test_policy.py`
- `tests/resume_evidence/test_duplicates.py`
- `tests/resume_evidence/test_report.py`
- `tests/resume_evidence/test_store.py`
- `tests/resume_evidence/test_importer.py`
- `tests/test_resume_evidence_cli.py`
- `tests/fixtures/resume_evidence/` — minimal synthetic fixture bundles only.

**Modify only at closeout:**

- `docs/ARCHITECTURE.md` — add the offline advisory foundation boundary and repository layout.
- `docs/ROADMAP.md` — record M8Q-0A offline completion and M8Q-0B/live acquisition pending.
- `docs/IMPLEMENTATION_PLAN.md` — index this plan and its acceptance evidence.
- `docs/DECISIONS.md` — record schema version, experience-month convention, and explicit non-integration.

---

### Task 1: Frozen Domain Model

**Files:**

- Create: `src/resume_evidence/__init__.py`
- Create: `src/resume_evidence/model.py`
- Create: `tests/resume_evidence/__init__.py`
- Create: `tests/resume_evidence/test_model.py`

**Interfaces:**

- Produces: all enums and dataclasses consumed by every later task.
- Consumes: standard library only.

- [ ] **Step 1: Write model construction and immutability tests**

Create tests that import every exact type below, construct one valid instance, and assert mutation raises `dataclasses.FrozenInstanceError`:

```python
from dataclasses import FrozenInstanceError
import pytest

from src.resume_evidence.model import (
    AuthorityKind, CanonicalSourceRecord, ConfidenceLevel, DoctrineCandidate,
    EditorialDimension, EditorialRating, EmploymentInterval, EvidenceConfidence,
    ExperienceConfidence, OutcomeCandidate, OutcomeRecord, OutcomeTier,
    ResumeRepresentation, ResumeVersionAttribution, RoleFamily, SourceKind, SourceRecord,
)


def test_outcome_candidate_is_frozen(valid_candidate):
    with pytest.raises(FrozenInstanceError):
        valid_candidate.target_role = "changed"


def test_closed_enums_reject_unknown_values():
    with pytest.raises(ValueError):
        OutcomeTier("oa")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_model.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'src.resume_evidence'`.

- [ ] **Step 3: Implement the exact model surface**

Use `str, Enum` for all enums and `@dataclass(frozen=True)` for all records. Define:

```python
SCHEMA_VERSION = "m8q.resume_evidence.v1"

class SourceKind(str, Enum):
    HUNTR = "huntr"
    INDIVIDUAL_PUBLIC_STORY = "individual_public_story"
    OTHER_APPROVED = "other_approved"

class OutcomeTier(str, Enum):
    RECRUITER_SCREEN = "recruiter_screen"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER = "offer"

class EvidenceConfidence(str, Enum):
    PLATFORM_LOGGED = "platform_logged"
    PUBLISHER_ASSERTED = "publisher_asserted"
    SELF_REPORTED = "self_reported"

class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ResumeRepresentation(str, Enum):
    INDIVIDUAL = "individual"
    ANONYMIZED = "anonymized"
    RECONSTRUCTED = "reconstructed"
    COMPOSITE = "composite"

class ResumeVersionAttribution(str, Enum):
    EXACT = "exact"
    PUBLISHER_LINKED = "publisher_linked"
    AMBIGUOUS = "ambiguous"

class ExperienceConfidence(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    AMBIGUOUS = "ambiguous"

class RoleFamily(str, Enum):
    GENERAL_SWE = "general_swe"
    BACKEND_PLATFORM = "backend_platform"
    ML_DATA = "ml_data"
    JAVA_ENTERPRISE = "java_enterprise"
    OTHER_RELEVANT = "other_relevant"

class AuthorityKind(str, Enum):
    AUTHOR_FIRST_PARTY = "author_first_party"
    PRACTITIONER_FIRST_PARTY = "practitioner_first_party"
    INSTITUTIONAL = "institutional"
    SECONDARY = "secondary"

class DoctrineUse(str, Enum):
    RUBRIC_CANDIDATE = "rubric_candidate"
    PATTERN_CONTEXT = "pattern_context"
    ADVISORY_ONLY = "advisory_only"

class EditorialDimension(str, Enum):
    EARLY_CAREER_PRIORITIZATION = "early_career_prioritization"
    TECHNICAL_SPECIFICITY = "technical_specificity"
    OWNERSHIP_CLARITY = "ownership_clarity"
    CLAIM_CREDIBILITY = "claim_credibility"
    PROJECT_SELECTION = "project_selection"
    ROLE_ALIGNMENT = "role_alignment"
    SCANABILITY = "scanability"
    PROFESSIONAL_VOICE = "professional_voice"

@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    url: str
    title: str
    retrieved_at: datetime
    content_sha256: str
    snapshot_file: str

@dataclass(frozen=True)
class CanonicalSourceRecord:
    source_id: str
    url: str
    title: str
    retrieved_at: datetime
    content_sha256: str

@dataclass(frozen=True)
class EmploymentInterval:
    start_month: str
    end_month: str

@dataclass(frozen=True)
class EditorialRating:
    dimension: EditorialDimension
    score: int
    explanation: str

@dataclass(frozen=True)
class OutcomeCandidate:
    schema_version: str
    reference_id: str
    source_kind: SourceKind
    sources: tuple[SourceRecord, ...]
    resume_source_id: str
    outcome_source_id: str
    layout_file: str | None
    layout_sha256: str | None
    role_family: RoleFamily
    target_role: str
    target_level: str
    graduation_month: str | None
    professional_intervals: tuple[EmploymentInterval, ...]
    internship_intervals: tuple[EmploymentInterval, ...]
    professional_experience_months: int
    experience_confidence: ExperienceConfidence
    outcome_tier: OutcomeTier
    outcome_evidence_quote: str
    outcome_evidence_confidence: EvidenceConfidence
    resume_representation: ResumeRepresentation
    resume_version_attribution: ResumeVersionAttribution
    section_order: tuple[str, ...]
    feature_tags: tuple[str, ...]
    editorial_ratings: tuple[EditorialRating, ...]
    limitations: tuple[str, ...]

@dataclass(frozen=True)
class OutcomeRecord:
    schema_version: str
    reference_id: str
    source_kind: SourceKind
    sources: tuple[CanonicalSourceRecord, ...]
    resume_source_id: str
    outcome_source_id: str
    layout_sha256: str | None
    role_family: RoleFamily
    target_role: str
    target_level: str
    graduation_month: str | None
    professional_intervals: tuple[EmploymentInterval, ...]
    internship_intervals: tuple[EmploymentInterval, ...]
    professional_experience_months: int
    experience_confidence: ExperienceConfidence
    outcome_tier: OutcomeTier
    outcome_evidence_quote: str
    outcome_evidence_confidence: EvidenceConfidence
    resume_representation: ResumeRepresentation
    resume_version_attribution: ResumeVersionAttribution
    section_order: tuple[str, ...]
    feature_tags: tuple[str, ...]
    editorial_ratings: tuple[EditorialRating, ...]
    limitations: tuple[str, ...]

@dataclass(frozen=True)
class DoctrineCandidate:
    schema_version: str
    doctrine_id: str
    source: SourceRecord
    authority_kind: AuthorityKind
    principle: str
    early_career_applicability: str
    affected_dimensions: tuple[EditorialDimension, ...]
    supporting_quote: str
    conflicts_or_qualifications: tuple[str, ...]
    confidence: ConfidenceLevel
    permitted_uses: tuple[DoctrineUse, ...]

@dataclass(frozen=True)
class DoctrineRecord:
    schema_version: str
    doctrine_id: str
    source: CanonicalSourceRecord
    authority_kind: AuthorityKind
    principle: str
    early_career_applicability: str
    affected_dimensions: tuple[EditorialDimension, ...]
    supporting_quote: str
    conflicts_or_qualifications: tuple[str, ...]
    confidence: ConfidenceLevel
    permitted_uses: tuple[DoctrineUse, ...]

@dataclass(frozen=True)
class PatternCard:
    schema_version: str
    pattern_id: str
    text: str
    anti_pattern: bool
    role_families: tuple[RoleFamily, ...]
    outcome_record_ids: tuple[str, ...]
    doctrine_record_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence: ConfidenceLevel
    prohibited_uses: tuple[str, ...]
    candidate_dimensions: tuple[EditorialDimension, ...]

@dataclass(frozen=True)
class CanonicalCorpus:
    schema_version: str
    corpus_version: str
    approved_at: datetime
    approval_report_sha256: str
    outcomes: tuple[OutcomeRecord, ...]
    doctrine: tuple[DoctrineRecord, ...]
    patterns: tuple[PatternCard, ...]
```

Re-export only stable public names from `src/resume_evidence/__init__.py`.

- [ ] **Step 4: Run the model tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_model.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/resume_evidence/__init__.py src/resume_evidence/model.py tests/resume_evidence/__init__.py tests/resume_evidence/test_model.py
git commit -m "feat(m8q): add resume evidence domain contracts"
```

---

### Task 2: Strict YAML Serde

**Files:**

- Create: `src/resume_evidence/serde.py`
- Create: `tests/resume_evidence/conftest.py`
- Create: `tests/resume_evidence/test_serde.py`
- Create: `tests/fixtures/resume_evidence/valid_outcome/bundle.yaml`
- Create: `tests/fixtures/resume_evidence/valid_outcome/sources/resume.md`
- Create: `tests/fixtures/resume_evidence/valid_outcome/sources/outcome.md`

**Interfaces:**

- Consumes: Task 1 dataclasses.
- Produces:
  - `EvidenceValidationError(ValueError)`
  - `parse_outcome_candidate(path: Path) -> OutcomeCandidate`
  - `parse_outcome_record(path: Path) -> OutcomeRecord`
  - `parse_doctrine_candidate(path: Path) -> DoctrineCandidate`
  - `parse_doctrine_record(path: Path) -> DoctrineRecord`
  - `parse_pattern_card(path: Path) -> PatternCard`
  - `parse_canonical_corpus(root: Path) -> CanonicalCorpus`
  - stable `dump_*` functions returning YAML strings.

- [ ] **Step 1: Create strict-parser RED tests**

Write parameterized tests that mutate a valid raw mapping and assert the exact rejection class:

```python
@pytest.mark.parametrize("mutation,match", [
    (lambda x: x.pop("reference_id"), "missing keys.*reference_id"),
    (lambda x: x.__setitem__("unexpected", 1), "unexpected keys.*unexpected"),
    (lambda x: x.__setitem__("professional_experience_months", True), "expected integer"),
    (lambda x: x.__setitem__("outcome_tier", "oa"), "outcome_tier"),
])
def test_candidate_structure_is_strict(candidate_mapping, write_yaml, mutation, match):
    mutation(candidate_mapping)
    path = write_yaml(candidate_mapping)
    with pytest.raises(EvidenceValidationError, match=match):
        parse_outcome_candidate(path)
```

Add a literal duplicate-key fixture:

```yaml
schema_version: m8q.resume_evidence.v1
reference_id: duplicate
reference_id: hidden
```

and assert `duplicate mapping key: reference_id`.

- [ ] **Step 2: Run serde tests and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_serde.py -q`

Expected: import failure for `src.resume_evidence.serde`.

- [ ] **Step 3: Implement strict loading helpers**

Implement a `yaml.SafeLoader` subclass whose mapping constructor checks duplicate keys before
constructing the mapping. Add small helpers with field-qualified errors:

```python
def _expect_mapping(value: object, field: str) -> dict[str, object]: ...
def _expect_keys(obj: dict[str, object], required: frozenset[str], optional: frozenset[str], field: str) -> None: ...
def _expect_str(value: object, field: str) -> str: ...
def _expect_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceValidationError(f"{field}: expected integer")
    return value
def _expect_list(value: object, field: str) -> list[object]: ...
def _parse_utc(value: object, field: str) -> datetime: ...
```

`_parse_utc` accepts only `YYYY-MM-DDTHH:MM:SSZ`, returns a UTC-aware `datetime`, and rejects YAML's
implicit `datetime` object so serialization stays explicit.

Parse lists into immutable tuples. Reject duplicate IDs and case-insensitive duplicate strings
during parsing, before a `set` could hide them. Parse nested records through dedicated private
functions (`_parse_source`, `_parse_interval`, `_parse_rating`).

- [ ] **Step 4: Implement stable dumpers and round-trip tests**

Stable dump order is the dataclass field order. Use `yaml.safe_dump(..., sort_keys=False,
allow_unicode=True)` and serialize datetimes back to whole-second `Z` timestamps. Add:

```python
def test_candidate_round_trip(valid_candidate, tmp_path):
    path = tmp_path / "bundle.yaml"
    path.write_text(dump_outcome_candidate(valid_candidate), encoding="utf-8")
    assert parse_outcome_candidate(path) == valid_candidate
```

Apply the same round trip separately to staged doctrine candidates, canonical outcome/doctrine
records, pattern cards, and the canonical corpus. Assert canonical serialized records contain no
`snapshot_file` or `layout_file` key.

- [ ] **Step 5: Run serde tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_serde.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/resume_evidence/serde.py tests/resume_evidence tests/fixtures/resume_evidence
git commit -m "feat(m8q): parse resume evidence bundles strictly"
```

---

### Task 3: Deterministic Experience Calculation

**Files:**

- Create: `src/resume_evidence/experience.py`
- Create: `tests/resume_evidence/test_experience.py`

**Interfaces:**

- Consumes: `EmploymentInterval`.
- Produces:
  - `parse_month(value: str) -> int`
  - `merge_intervals(intervals: tuple[EmploymentInterval, ...]) -> tuple[tuple[int, int], ...]`
  - `professional_experience_months(intervals, graduation_month) -> int`

- [ ] **Step 1: Write the boundary matrix as failing tests**

Use conventional month deltas: `2023-01` to `2026-01` is 36 months. Endpoints are normalized as
half-open month boundaries. Merge overlaps before summing.

```python
@pytest.mark.parametrize("intervals,graduation,expected", [
    ((EmploymentInterval("2023-01", "2026-01"),), "2022-05", 36),
    ((EmploymentInterval("2023-01", "2026-02"),), "2022-05", 37),
    ((EmploymentInterval("2022-01", "2024-01"),), "2023-01", 12),
    ((EmploymentInterval("2023-01", "2024-01"), EmploymentInterval("2023-06", "2024-06")), "2022-05", 18),
])
def test_professional_month_recomputation(intervals, graduation, expected):
    assert professional_experience_months(intervals, graduation) == expected
```

Also reject invalid month strings, reversed intervals, zero-length intervals, missing graduation,
and booleans introduced through malformed construction.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_experience.py -q`

Expected: import failure for `src.resume_evidence.experience`.

- [ ] **Step 3: Implement minimal pure interval logic**

```python
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

def parse_month(value: str) -> int:
    match = _MONTH_RE.fullmatch(value)
    if not match:
        raise EvidenceValidationError(f"invalid month: {value!r}")
    year, month = map(int, match.groups())
    return year * 12 + month - 1

def professional_experience_months(intervals, graduation_month):
    graduation = parse_month(graduation_month)
    clipped = []
    for item in intervals:
        start, end = parse_month(item.start_month), parse_month(item.end_month)
        if end <= start:
            raise EvidenceValidationError("employment interval end must be after start")
        if end > graduation:
            clipped.append((max(start, graduation), end))
    return sum(end - start for start, end in _merge_pairs(clipped))
```

Keep internship intervals out of this function; their exclusion is explicit at the call site.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_experience.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/resume_evidence/experience.py tests/resume_evidence/test_experience.py
git commit -m "feat(m8q): calculate early-career experience deterministically"
```

---

### Task 4: Bundle Integrity and Admission Policy

**Files:**

- Create: `src/resume_evidence/policy.py`
- Create: `tests/resume_evidence/test_policy.py`

**Interfaces:**

- Consumes: parsed domain records and Task 3 recomputation.
- Produces:
  - `AdmissionStatus(str, Enum): ACCEPTED | NEEDS_REVIEW | REJECTED`
  - `AdmissionDecision(status, reasons, computed_experience_months)` frozen dataclass
  - `validate_outcome_bundle(candidate, bundle_dir) -> None`
  - `evaluate_admission(candidate) -> AdmissionDecision`
  - `to_outcome_record(candidate) -> OutcomeRecord`
  - `validate_doctrine_bundle(record: DoctrineCandidate, bundle_dir) -> None`
  - `to_doctrine_record(candidate: DoctrineCandidate) -> DoctrineRecord`
  - `validate_pattern_card(card, outcome_ids, doctrine_ids) -> None`

- [ ] **Step 1: Write evidence-integrity RED tests**

Create synthetic bundles and assert rejection for:

```python
@pytest.mark.parametrize("url", [
    "http://huntr.co/example",
    "https://user:pass@huntr.co/example",
    "https://huntr.co/example?token=secret",
    "https://127.0.0.1/example",
])
def test_unsafe_source_urls_fail(valid_candidate, bundle_dir, url): ...

def test_outcome_quote_must_exist_in_declared_outcome_snapshot(...): ...
def test_resume_source_must_contain_resume_sections(...): ...
def test_snapshot_hash_mismatch_fails(...): ...
def test_snapshot_path_may_not_escape_sources_directory(...): ...
def test_outcome_quote_over_25_words_fails(...): ...
def test_all_eight_editorial_dimensions_are_required_once(...): ...
```

Source IDs must resolve uniquely. `resume_source_id` and `outcome_source_id` may be equal. Every
snapshot path must resolve beneath `<bundle_dir>/sources/` and be UTF-8.

- [ ] **Step 2: Write admission RED tests**

```python
def test_36_month_recruiter_screen_is_accepted(valid_candidate): ...
def test_37_month_candidate_is_rejected(valid_candidate): ...
def test_ambiguous_experience_needs_review(valid_candidate): ...
def test_ambiguous_resume_attribution_needs_review(valid_candidate): ...
def test_oa_is_not_an_outcome_enum(): ...
def test_stored_experience_must_equal_recomputation(valid_candidate): ...
```

`NEEDS_REVIEW` is permitted in the staging report but forbidden from canonical promotion.

- [ ] **Step 3: Run policy tests and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_policy.py -q`

Expected: import failure for `src.resume_evidence.policy`.

- [ ] **Step 4: Implement URL, snapshot, quote, and privacy validation**

Use `urllib.parse.urlsplit` and `ipaddress.ip_address`. Require HTTPS, no userinfo, no IP-literal
host, no fragment credentials, and reject case-insensitive query keys containing:

```python
SENSITIVE_QUERY_KEYS = frozenset({
    "api_key", "apikey", "token", "access_token", "auth", "authorization",
    "password", "passwd", "secret", "session", "cookie",
})
```

Require SHA-256 lowercase hex and recompute it from exact UTF-8 snapshot bytes. Require 4–25 words
for outcome and doctrine excerpts and literal containment in the declared snapshot. Reject direct
PII fields in canonical mappings; source snapshots remain private and are not serialized into
canonical records.

- [ ] **Step 5: Implement admission and doctrine/pattern rules**

Admission order is deterministic:

1. structural and evidence integrity must already pass;
2. ambiguous experience or resume attribution -> `NEEDS_REVIEW`;
3. recomputed months > 36 -> `REJECTED`;
4. irrelevant role family or missing resume sections -> `REJECTED`;
5. recruiter screen or stronger with 0–36 months -> `ACCEPTED`.

Pattern cards require at least two distinct outcome IDs or at least one doctrine ID. All referenced
IDs must exist. Doctrine records must have nonempty applicability, at least one affected dimension,
at least one permitted use, and an anchored quote.

`to_outcome_record` and `to_doctrine_record` copy source provenance into
`CanonicalSourceRecord` objects and deliberately drop every private `snapshot_file` and
`layout_file` path. Preserve hashes, public URLs, bounded evidence, annotations, and the optional
layout hash only.

- [ ] **Step 6: Run policy tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_policy.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/resume_evidence/policy.py tests/resume_evidence/test_policy.py
git commit -m "feat(m8q): enforce resume evidence admission policy"
```

---

### Task 5: Duplicate Analysis and Whole-Corpus Validation

**Files:**

- Create: `src/resume_evidence/duplicates.py`
- Create: `tests/resume_evidence/test_duplicates.py`
- Create: `src/resume_evidence/importer.py`
- Create: `tests/resume_evidence/test_importer.py`

**Interfaces:**

- Produces:
  - `canonical_source_url(url: str) -> str`
  - `resume_signature(text: str) -> frozenset[str]`
  - `DuplicatePair(left_id, right_id, kind, similarity)`
  - `find_duplicates(candidates, snapshot_text_by_id) -> tuple[DuplicatePair, ...]`
  - `ValidatedCorpus(outcomes, doctrine, patterns, decisions, duplicates)`
  - `validate_corpus(inbox_root, manifest_path) -> ValidatedCorpus`

- [ ] **Step 1: Write duplicate RED tests**

Test exact URL normalization, exact content hashes, and five-word-shingle near duplicates. Strip
marketing parameters but preserve content-affecting query values. Use a fixed review threshold of
`0.90`; near duplicates are reported and block promotion rather than auto-merged.

```python
def test_tracking_parameters_do_not_create_distinct_sources(): ...
def test_exact_snapshot_hash_duplicate_is_reported(): ...
def test_near_duplicate_above_point_nine_is_reported(): ...
def test_distinct_resume_below_threshold_is_not_reported(): ...
```

- [ ] **Step 2: Implement duplicate helpers using existing primitives**

Reuse `src.textsim.shingles` and `src.textsim.jaccard_similarity`; do not duplicate the Jaccard
implementation. Remove obvious contact/header tokens before shingling so anonymized names do not
make one resume appear distinct, but do not remove employers, dates, technologies, or bullets.

- [ ] **Step 3: Write whole-corpus RED tests**

The private `manifest.yaml` is strict and contains:

```yaml
schema_version: m8q.resume_evidence.v1
corpus_version: 0.1.0
promote_outcome_ids: [outcome_a]
excluded_outcomes:
  - reference_id: outcome_b
    reason: exceeds the 36-month experience limit
expected_doctrine_ids: [doctrine_a]
expected_pattern_ids: [pattern_a]
```

Test missing expected IDs, unexpected directories/files, directory/id disagreement, duplicate IDs,
an excluded outcome without a reason, the same ID in both disposition lists, a non-accepted promoted
outcome, a structurally corrupt excluded outcome, unresolved promoted near duplicates, invalid
pattern references, and deterministic ID ordering. The synthetic fixture may contain two outcomes;
the production 50-Huntr minimum is a live M8Q-0B gate, not hardcoded into generic unit fixtures.

- [ ] **Step 4: Implement whole-corpus validation**

Expected layout:

```text
<inbox_root>/outcomes/<reference_id>/bundle.yaml
<inbox_root>/doctrine/<doctrine_id>/record.yaml
<inbox_root>/patterns/<pattern_id>/record.yaml
```

Reject every unexpected non-hidden file. Parse and validate every record, compute admission, load
snapshot text, run duplicate analysis, and return sorted immutable tuples. Every staged outcome must
appear exactly once as promoted or explicitly excluded. Excluded outcomes remain in decisions and
reports but are never converted to canonical records. Pattern cards may refer only to promoted
outcome IDs. Do not write anything.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_duplicates.py tests/resume_evidence/test_importer.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/resume_evidence/duplicates.py src/resume_evidence/importer.py tests/resume_evidence/test_duplicates.py tests/resume_evidence/test_importer.py
git commit -m "feat(m8q): validate resume evidence corpora atomically"
```

---

### Task 6: Deterministic Review Report and Approval Binding

**Files:**

- Create: `src/resume_evidence/report.py`
- Create: `tests/resume_evidence/test_report.py`
- Modify: `src/resume_evidence/importer.py`
- Modify: `tests/resume_evidence/test_importer.py`

**Interfaces:**

- Produces:
  - `ResearchReport` frozen dataclass
  - `build_report(validated: ValidatedCorpus) -> ResearchReport`
  - `report_to_dict(report) -> dict[str, object]`
  - `render_report_markdown(report) -> str`
  - `report_sha256(report) -> str`

- [ ] **Step 1: Write deterministic report RED tests**

Assert exact counts for accepted, rejected, needs-review, duplicate, source kind, role family,
outcome tier, evidence confidence, and representation. Assert byte-identical JSON/Markdown across
reordered input construction.

Report accepted/rejected/needs-review across every explicitly dispositioned staged outcome and show
the manifest disposition and exclusion reason. Canonical-count fields count only promoted records.

```python
def test_report_hash_is_order_independent(validated_corpus_reordered):
    first, second = validated_corpus_reordered
    assert report_sha256(build_report(first)) == report_sha256(build_report(second))
```

Report diagnostics must contain IDs and bounded reasons, never source snapshot text or PII.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_report.py -q`

Expected: import failure for `src.resume_evidence.report`.

- [ ] **Step 3: Implement report generation**

Canonical JSON is `json.dumps(report_to_dict(report), sort_keys=True, separators=(",", ":"),
ensure_ascii=False) + "\n"`. Hash those UTF-8 bytes. Markdown tables are sorted by enum value then
record ID. Include the approval command with the exact computed SHA-256, but do not imply approval.

- [ ] **Step 4: Bind import to the exact approved report hash**

Extend the future import interface to require:

```python
def import_corpus(
    inbox_root: Path,
    manifest_path: Path,
    bank_root: Path,
    *,
    approved_report_sha256: str,
    approved_at: datetime,
) -> ImportResult: ...
```

Recompute the report during import and fail unless its hash equals the user-supplied approval hash.
Convert only manifest-promoted `ACCEPTED` candidates into canonical records; retain excluded
candidates only in the ignored research report. This prevents an approved report from authorizing a
later-changed corpus or an implicit skip.

- [ ] **Step 5: Run report/import tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_report.py tests/resume_evidence/test_importer.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/resume_evidence/report.py src/resume_evidence/importer.py tests/resume_evidence/test_report.py tests/resume_evidence/test_importer.py
git commit -m "feat(m8q): bind corpus promotion to reviewed evidence"
```

---

### Task 7: Canonical Store, Atomic Promotion, and Lookup

**Files:**

- Create: `src/resume_evidence/store.py`
- Create: `tests/resume_evidence/test_store.py`
- Modify: `src/resume_evidence/importer.py`
- Modify: `tests/resume_evidence/test_importer.py`

**Interfaces:**

- Produces:
  - `EvidenceBank(outcomes: tuple[OutcomeRecord, ...], doctrine: tuple[DoctrineRecord, ...], patterns, corpus_version, approved_at)`
  - `load_evidence_bank(bank_root: Path) -> EvidenceBank`
  - `lookup_outcomes(bank, *, role_family=None, max_months=None, outcome_tier=None, representation=None) -> tuple[OutcomeRecord, ...]`
  - `ImportStatus.CREATED | UNCHANGED`
  - `ImportResult(status, outcome_count, doctrine_count, pattern_count, target)`

- [ ] **Step 1: Write loader and lookup RED tests**

Test filename/ID agreement, unexpected files, duplicate IDs, strict canonical parsing, stable sort,
missing bank returning an empty bank, and each advisory filter. Lookup is read-only and never loads
private snapshots.

- [ ] **Step 2: Write atomic promotion RED tests**

Test:

- first import creates `config-root/current/`;
- identical import returns `UNCHANGED` and preserves bytes;
- a differing existing bank fails rather than overwrites;
- invalid staged canonical YAML is caught by `load_evidence_bank` before promotion;
- temp staging is removed after success and failure;
- wrong approval hash writes nothing;
- simulated `os.replace` failure leaves the target absent/unchanged.

- [ ] **Step 3: Implement canonical layout and loader**

Canonical layout:

```text
<bank_root>/current/corpus.yaml
<bank_root>/current/outcomes/<reference_id>.yaml
<bank_root>/current/doctrine/<doctrine_id>.yaml
<bank_root>/current/patterns/<pattern_id>.yaml
```

`corpus.yaml` lists every canonical ID, corpus version, approval timestamp, and approval report hash.
Reject any file not named in the manifest. Return tuples sorted by ID.

- [ ] **Step 4: Implement atomic importer**

Create a sibling temp directory with `tempfile.mkdtemp(prefix=".evidence-stage-", dir=bank_root)`.
Write stable YAML, call `load_evidence_bank(stage_parent)` against the staged `current/`, compare
recursively and byte-for-byte with an existing target, then use exactly one `os.replace(stage,
target)` when the target does not exist. Always remove leftover staging in `finally`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_store.py tests/resume_evidence/test_importer.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/resume_evidence/store.py src/resume_evidence/importer.py tests/resume_evidence/test_store.py tests/resume_evidence/test_importer.py
git commit -m "feat(m8q): promote resume evidence banks atomically"
```

---

### Task 8: Offline Operator CLI

**Files:**

- Create: `scripts/resume_evidence.py`
- Create: `tests/test_resume_evidence_cli.py`
- Modify: `src/resume_evidence/__init__.py`

**Interfaces:**

- Produces CLI commands:
  - `validate-bundle PATH`
  - `validate-corpus --inbox PATH --manifest PATH`
  - `report --inbox PATH --manifest PATH --output DIR`
  - `import-corpus --inbox PATH --manifest PATH --bank-root PATH --approved-report-sha256 SHA --approved-at UTC`
  - `stats --bank-root PATH`
  - `lookup --bank-root PATH [--role-family ...] [--max-months 0..36] [--outcome-tier ...] [--representation ...]`

- [ ] **Step 1: Write CLI RED matrix**

Use direct `main(argv)` calls and `capsys`. Assert success output and the global exit contract:

```python
def test_validate_bundle_success(valid_bundle_dir, capsys): ...
def test_validate_bundle_invalid_returns_one(...): ...
def test_validate_bundle_unreadable_returns_two(...): ...
def test_lookup_missing_returns_three(...): ...
def test_report_writes_json_last_as_commit_marker(...): ...
def test_import_requires_matching_64_hex_approval_hash(...): ...
```

For report publication, write `report.md` and a temporary JSON file, then `os.replace` JSON to
`report.json` last. An existing identical report is allowed; a differing report directory is a
conflict and remains unchanged.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_resume_evidence_cli.py -q`

Expected: import failure for `scripts.resume_evidence`.

- [ ] **Step 3: Implement the thin CLI**

Keep all business logic in `src/resume_evidence`. Print concise summaries only from the script.
Bound exception messages to 300 characters and never include raw snapshots. Catch
`EvidenceValidationError` as exit 1; catch `OSError`, `UnicodeError`, and YAML parser failures as
exit 2; unexpected exceptions also return 2 with an `INTERNAL:` prefix and type name.

- [ ] **Step 4: Run CLI and all focused M8Q tests**

Run: `.venv/bin/python -m pytest tests/resume_evidence tests/test_resume_evidence_cli.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 8**

```bash
git add scripts/resume_evidence.py src/resume_evidence/__init__.py tests/test_resume_evidence_cli.py
git commit -m "feat(m8q): add offline resume evidence operator"
```

---

### Task 9: Integration Guards, Documentation, and Offline Closeout

**Files:**

- Create: `tests/test_resume_evidence_integration.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/IMPLEMENTATION_PLAN.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**

- Verifies the completed M8Q-0A boundary.
- Produces no live corpus and no canonical `config/resume_evidence_bank/current/` directory.

- [ ] **Step 1: Write integration boundary RED tests**

Assert:

```python
def test_resume_evidence_package_imports_no_network_or_tailoring_modules(): ...
def test_scripts_expose_no_fetch_or_scrape_command(): ...
def test_synthetic_corpus_round_trip_is_atomic_and_idempotent(tmp_path): ...
def test_raw_snapshot_text_never_appears_in_canonical_yaml(tmp_path): ...
def test_no_sql_strings_exist_in_resume_evidence_package(): ...
```

Use `ast` for import and SQL checks rather than fragile broad grep where practical.

- [ ] **Step 2: Run integration tests and verify any missing boundary fails**

Run: `.venv/bin/python -m pytest tests/test_resume_evidence_integration.py -q`

Expected: at least the documentation/layout or missing guard assertion fails before closeout edits.

- [ ] **Step 3: Update authoritative documentation narrowly**

Record:

- M8Q-0A is an offline advisory foundation only.
- M8Q-0B live research, three-page smoke, 50-Huntr minimum, doctrine acquisition, user approval,
  and canonical corpus adoption are pending.
- No integration with S0/S2/S3/G2/G3, SkillOpt, Company Bank, SQLite, or prompts exists.
- Raw research remains ignored and canonical records exclude complete resumes.
- The month convention is conventional half-open delta after graduation; internships excluded.

Do not mark M8, Phase 3, M8V, or the live pilot complete.

- [ ] **Step 4: Verify ignored/private state and production invariants**

Run:

```bash
git check-ignore -v data/resume_research/inbox/example/sources/resume.md
test ! -e config/resume_evidence_bank/current
shasum -a 256 data/jobs.db
git diff --check
```

Expected: research path is ignored; canonical current bank absent; DB hash matches the preflight
hash; diff check is silent.

- [ ] **Step 5: Run focused and full suites**

Run:

```bash
.venv/bin/python -m pytest tests/resume_evidence tests/test_resume_evidence_cli.py tests/test_resume_evidence_integration.py -q
.venv/bin/python -m pytest -q
```

Expected: all selected tests pass; full suite retains the repository's intentional deselection only.

- [ ] **Step 6: Commit closeout and stop**

```bash
git add tests/test_resume_evidence_integration.py docs/ARCHITECTURE.md docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md docs/DECISIONS.md
git commit -m "docs(m8q): close offline resume evidence foundation"
```

Report focused/full counts, DB hash, `git diff --check`, exact commits, and final status. Explicitly
confirm: no network, Firecrawl, Crawl4AI, model call, live research, canonical corpus, DB mutation,
prompt/profile/tailoring change, dependency, or push. Stop before M8Q-0B.
