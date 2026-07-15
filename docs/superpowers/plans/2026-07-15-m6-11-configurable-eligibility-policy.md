# M6.11 Configurable Eligibility Policy v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Use
> `superpowers:test-driven-development` for every production change and
> `superpowers:verification-before-completion` before any completion claim.
> Steps use checkbox (`- [ ]`) syntax for progress tracking.

**Goal:** Replace the current regex-only post-resolution prefilter with a validated,
configuration-driven, country-first eligibility policy that supports the user's United
States-only search, 2027 full-time roles, Spring 2027 internships, and conservative
sponsorship handling without hard-coding those choices in Python.

**Architecture:** `src/eligibility.py` is the pure deterministic policy engine. It loads
typed configuration from `config/eligibility.yaml`, uses the local vocabulary in
`config/location_taxonomy.yaml`, and returns immutable decisions without touching SQLite.
`src/prefilter.py` becomes a thin orchestration adapter for two gates: a conservative
pre-resolution pass over `DISCOVERED` rows and an authoritative post-resolution pass over
`RESOLVED` rows. All reads and writes go through `src/db.py`. A separate impact command
previews legacy/live-row transitions and applies only the previewed set after an explicit,
backed-up, user-supervised gate.

**Tech stack:** Python 3.11+, stdlib (`dataclasses`, `enum`, `datetime`, `json`, `re`,
`sqlite3`, `pathlib`) plus the already-approved PyYAML and pytest. No new package, web
request, browser request, LLM call, schema migration, or discovery-source change.

**Authoritative design:**
`docs/superpowers/specs/2026-07-15-configurable-eligibility-policy-design.md`. If this plan
and that approved design appear to conflict, stop and ask the user; do not improvise a
third policy.

## Non-negotiable behavior

- Load and validate eligibility configuration before opening the production database or
  calling `db.start_run()`. Invalid configuration exits nonzero with no run row and no job
  mutation.
- Country is evaluated first. An explicit non-allowed country filters immediately; missing
  or ambiguous country evidence never becomes an invented non-US judgment.
- Run the early gate before `run_resolution()` in normal and `--resolve-only` modes. Do not
  run it in `--discover-only` mode.
- A 2027 full-time posting passes. A full-time posting with no start evidence after the JD
  is read remains eligible with `start_date_unknown`.
- An internship passes only with Spring 2027 or January-May 2027 evidence. A year-only
  `2027 internship` defers early and filters after the full JD if nothing more specific is
  found.
- Explicit no-sponsorship or US-citizens-only language filters. Silence passes. Generic
  authorization language passes with `authorization_ambiguous`.
- Eligibility choices live only in `config/eligibility.yaml`. `config/filters.yaml` retains
  only scoring configuration such as `score_threshold` after migration; there is no dual
  source of eligibility truth.
- Stable filter reasons are exactly `eligibility:country`,
  `eligibility:work_authorization`, `eligibility:opportunity_type`,
  `eligibility:start_window`, `eligibility:role_family`, and
  `eligibility:seniority`.
- Idempotency is mandatory. Repeating either pipeline gate or the approved impact apply
  must produce zero additional changes.
- Tests are offline. No test may instantiate a real network/browser client.
- Do not begin Calibration Contract v2, M8, M9D, Crawlee, or Apify in this milestone.

## Expected file changes

```text
config/
  eligibility.yaml                         NEW: sole eligibility business policy
  location_taxonomy.yaml                   NEW: deterministic country/state vocabulary
  filters.yaml                             MODIFY: retain score_threshold only

src/
  eligibility.py                           NEW: typed config + pure classifiers/evaluator
  prefilter.py                              REWRITE: DB-free policy is removed; gate adapter only
  db.py                                     MODIFY: eligibility row/transition helpers
  run_ingest.py                             MODIFY: early/post gates, validated load, accounting
  audit/__init__.py                         MODIFY: separate eligibility_config parameter
  audit/invariants_sources.py               MODIFY: I2 uses new policy
  audit/invariants_db.py                    MODIFY: I6a uses new policy
  audit/invariants_export.py                MODIFY: accept new check signature only
  audit/invariants_llm.py                   MODIFY: accept new check signature only

scripts/
  eligibility_impact.py                    NEW: read-only preview / guarded apply CLI

tests/
  test_eligibility_config.py                NEW
  test_eligibility_country.py               NEW
  test_eligibility_opportunity_dates.py     NEW
  test_eligibility.py                       NEW
  test_prefilter.py                         REWRITE for two-stage orchestration
  test_run_ingest.py                        MODIFY
  test_run_ingest_lifecycle.py              MODIFY if summary signature requires it
  test_audit_invariants_sources.py          MODIFY
  test_audit_invariants_db.py               MODIFY
  test_audit_orchestrator.py                MODIFY
  test_eligibility_impact.py                NEW
  test_idempotency.py                       MODIFY/EXTEND

docs/
  ARCHITECTURE.md                           MODIFY after offline implementation
  ROADMAP.md                                MODIFY after offline implementation and live gate
  DECISIONS.md                              MODIFY with accepted policy/evidence
```

Do not touch the user's uncommitted `tests/test_scoring_stress.py` or the untracked PDF and
report files. Stage exact paths only; never use `git add -A` or `git add .`.

---

### Task 1: Add and validate the typed configuration contract

**Files:**
- Create: `config/eligibility.yaml`
- Create: `config/location_taxonomy.yaml`
- Create: `src/eligibility.py`
- Create: `tests/test_eligibility_config.py`

**Interfaces to implement:**

```python
class EligibilityConfigError(ValueError): ...

@dataclass(frozen=True)
class DateWindow:
    earliest: date
    latest: date

@dataclass(frozen=True)
class OpportunityTypePolicy:
    enabled: bool
    start_windows: tuple[DateWindow, ...]
    allowed_seasons: tuple[str, ...]
    year_only_evidence: str | None
    unknown_start_pre_resolution: str | None
    unknown_start_post_resolution: str | None

@dataclass(frozen=True)
class EligibilityConfig:
    version: int
    # Typed fields for every key in the approved design; do not retain a raw
    # nested dict as the production boundary.

def load_eligibility_config(
    policy_path: str | Path = "config/eligibility.yaml",
    taxonomy_path: str | Path = "config/location_taxonomy.yaml",
) -> EligibilityConfig: ...
```

The initial `config/eligibility.yaml` must reproduce the exact semantic YAML in design
section 3, including `allowed: [US]`, the 2027 full-time window, the January-May Spring
internship window, disabled co-op/contract/part-time/temporary types, software-engineering
role patterns, 3-year cap, authorization precedence/patterns, and stable flag names.

`config/location_taxonomy.yaml` is data, not policy. Give it a documented schema with:

```yaml
version: 1
countries:
  US:
    names: [United States, United States of America]
    codes: [US, USA]
    aliases: [U.S., U.S.A., America]
  CA:
    names: [Canada]
    codes: [CA, CAN]
    aliases: []
  # Complete ISO-3166 country-code/name vocabulary follows.
us_states:
  AL: Alabama
  # all 50 states plus DC
```

The taxonomy must contain every ISO-3166 alpha-2 code with its canonical English country
name so changing `countries.allowed` to another valid code requires no Python edit. Common
aliases may be limited and reviewable. Do not add a package or fetch data at runtime. Treat
two-letter country codes as bounded tokens, but give an explicit US state interpretation
precedence when the location has a city/state form such as `San Diego, CA`; do not globally
interpret every bare `CA` as Canada.

- [ ] Write failing tests for a valid load and all validation failures below.
- [ ] Assert unsupported `version`, unsupported policy enum values, unknown ISO country
      codes, invalid/inverted dates, unknown classification-order/type keys, an enabled type
      with no policy, bad season references, invalid regexes (with the full YAML key path in
      the exception), a negative `years_cap`, and an empty role-family include list all raise
      `EligibilityConfigError`.
- [ ] Assert loaded collections are immutable tuples/frozen dataclasses and dates are parsed
      to `datetime.date`.
- [ ] Implement the smallest loader/validator that passes the tests. Compile each configured
      regex during validation, but store the configured strings or immutable compiled forms
      consistently.
- [ ] Run `pytest -q tests/test_eligibility_config.py`.
- [ ] Run `pytest -q tests/test_eligibility_config.py tests/test_prefilter.py` to detect an
      accidental import break before continuing.
- [ ] Commit exact files:

```bash
git add config/eligibility.yaml config/location_taxonomy.yaml src/eligibility.py tests/test_eligibility_config.py
git commit -m "feat(m6.11): add validated eligibility configuration"
```

---

### Task 2: Implement deterministic country evidence

**Files:**
- Modify: `src/eligibility.py`
- Create: `tests/test_eligibility_country.py`

**Interfaces:**

```python
class CountryEvidence(str, Enum):
    EXPLICIT_ALLOWED = "explicit_allowed"
    EXPLICIT_DISALLOWED = "explicit_disallowed"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class CountryClassification:
    evidence: CountryEvidence
    country_codes: tuple[str, ...]
    matched_text: tuple[str, ...]

def classify_country(location: str | None, config: EligibilityConfig) -> CountryClassification: ...
```

Rules are asymmetric: explicit allowed evidence wins only when there is no explicit
non-allowed country conflict; explicit disallowed evidence is safe to filter; no evidence is
unknown. `Remote` changes no country result. Normalize case/whitespace/punctuation without
substring accidents (`IN` inside `engineering`, `US` inside `Austin`, etc.).

- [ ] First write a parameterized red test for: `New York, NY`, `San Diego, CA`, `Austin,
      Texas`, `United States`, and `Remote - USA` => allowed; `Toronto, Canada`, `Remote -
      Canada`, `Vancouver, BC, Canada`, `London, United Kingdom`, and `Bengaluru, India` =>
      disallowed; bare `Remote`, empty, `Worldwide`, and an unrecognized city => unknown.
- [ ] Add collision tests proving `San Diego, CA` is US-state evidence while `Toronto,
      Canada` is Canada, and short codes do not match inside ordinary words.
- [ ] Add a config-mutability test: construct/replace config with `allowed: [CA]` and prove
      Toronto becomes allowed while New York becomes disallowed, without changing code.
- [ ] Implement normalization and vocabulary matching. Keep all vocabulary in taxonomy.
- [ ] Run `pytest -q tests/test_eligibility_config.py tests/test_eligibility_country.py`.
- [ ] Commit:

```bash
git add src/eligibility.py tests/test_eligibility_country.py
git commit -m "feat(m6.11): classify country evidence deterministically"
```

---

### Task 3: Implement opportunity type and start-window evidence

**Files:**
- Modify: `src/eligibility.py`
- Create: `tests/test_eligibility_opportunity_dates.py`

**Interfaces:**

```python
class OpportunityType(str, Enum):
    INTERNSHIP = "internship"
    CO_OP = "co_op"
    CONTRACT = "contract"
    PART_TIME = "part_time"
    TEMPORARY = "temporary"
    FULL_TIME = "full_time"

@dataclass(frozen=True)
class OpportunityClassification:
    opportunity_type: OpportunityType
    inferred: bool
    matched_text: tuple[str, ...]

@dataclass(frozen=True)
class StartEvidence:
    exact_dates: tuple[date, ...]
    month_years: tuple[tuple[int, int], ...]
    seasons: tuple[tuple[str, int], ...]
    years: tuple[int, ...]
    matched_text: tuple[str, ...]

def classify_opportunity_type(
    title: str, jd_text: str | None, config: EligibilityConfig
) -> OpportunityClassification: ...

def extract_start_evidence(text: str, config: EligibilityConfig) -> StartEvidence: ...
```

Opportunity matching follows configured `classification_order`, searches the title before
the full JD, and only uses `default_when_unmarked` when nothing matches. A specific
internship/co-op/contract/part-time/temporary marker therefore beats generic `full-time`
text elsewhere. An inferred default adds `opportunity_type_inferred` at aggregate evaluation.

Date extraction may recognize full month names and common abbreviations, ISO/numeric dates,
four-digit years, and configured season names. It must inspect start-oriented phrases and
avoid using `date_posted` (which is not even an evaluator argument), copyright years, company
founding years, or unrelated experience history as start dates. Multiple explicit starts
pass when at least one falls in a configured window.

- [ ] Write red tests proving configured classification order, title-before-JD behavior,
      default full-time inference, and disabled type recognition.
- [ ] Write red full-time tests: `New Grad 2027`, `starts in 2027`, `August 2027`, and an
      exact date in 2027 match; explicit start-only 2026 or 2028 does not; missing start is
      unknown; one of multiple starts in 2027 matches.
- [ ] Write red internship tests: `Spring 2027`, January through May 2027, and an exact date
      in the window match; `Summer 2027`, `Fall 2027`, 2026, 2028, and June 2027 do not;
      year-only `2027 internship` is insufficient.
- [ ] Add negative tests for `Founded in 2027` and `copyright 2027` so unrelated years are
      not treated as start evidence.
- [ ] Add config-mutability tests changing the full-time date window, enabled type, season
      months, and default type without a code edit.
- [ ] Implement only what these tests and the approved design require; do not introduce an
      NLP/LLM dependency.
- [ ] Run `pytest -q tests/test_eligibility_opportunity_dates.py`.
- [ ] Commit:

```bash
git add src/eligibility.py tests/test_eligibility_opportunity_dates.py
git commit -m "feat(m6.11): classify configurable role types and start windows"
```

---

### Task 4: Complete the pure two-stage policy evaluator

**Files:**
- Modify: `src/eligibility.py`
- Create: `tests/test_eligibility.py`

**Required public contract:**

```python
class EligibilityStage(str, Enum):
    PRE_RESOLUTION = "pre_resolution"
    POST_RESOLUTION = "post_resolution"

class EligibilityDisposition(str, Enum):
    PASS = "pass"
    FILTER = "filter"
    DEFER = "defer"

@dataclass(frozen=True)
class EligibilityDecision:
    disposition: EligibilityDisposition
    reason_code: str | None
    flags: tuple[str, ...]
    evidence: tuple[str, ...]

def evaluate(
    *,
    stage: EligibilityStage,
    title: str,
    location: str | None,
    jd_text: str | None,
    existing_flags: tuple[str, ...],
    config: EligibilityConfig,
) -> EligibilityDecision: ...
```

Evaluation order is exact:

- PRE: country, opportunity type, start window, role family, title seniority.
- POST: country, work authorization, opportunity type, start window, role family,
  seniority/required years, then non-rejection flags.

An explicit country mismatch returns immediately. For other unknown dimensions, continue
checking later dimensions: any explicit failure still filters; if no failure exists, return
`DEFER` pre-resolution when required evidence is missing. Post-resolution unknown behavior
comes from config (`allow_with_flag` or `reject`). Evidence strings must be concise and
deterministic; tests should assert reason codes/flags and only important evidence fragments,
not incidental formatting.

Move/adapt `_years_required` and regex matching from `src/prefilter.py` into the pure module.
Work-authorization precedence is: explicit negative/citizenship requirement, positive
sponsorship, ambiguous authorization, silence. A negative overrides both positive wording
and an existing `sponsor_likely` flag. EEO phrases such as `citizenship status` must not
become citizenship requirements.

- [ ] Write red table tests for every stable reason code and both stages.
- [ ] Prove `Toronto, Canada` filters with `eligibility:country` even if later text might
      match; monkeypatch later classifier helpers to raise if necessary to prove country
      short-circuiting.
- [ ] Prove unknown country defers at PRE and passes with `country_unknown` at POST.
- [ ] Prove full-time unknown start defers PRE and passes with `start_date_unknown` POST.
- [ ] Prove internship unknown/year-only start defers PRE and filters with
      `eligibility:start_window` POST.
- [ ] Prove Spring/Jan-May internship and 2027 full-time pass, while disabled types and
      out-of-window explicit starts filter.
- [ ] Prove role-family mismatch and senior/title/required-years cases use their exact
      reasons; change role patterns and years cap in copied config and prove outcomes follow
      config.
- [ ] Prove explicit no-sponsorship variants and citizenship-only variants filter; silence
      passes; positive sponsorship passes; authorization-only language passes with
      `authorization_ambiguous`; EEO boilerplate passes without that rejection.
- [ ] Prove flags are sorted/deduplicated and include configured names only.
- [ ] Implement evaluator and keep it SQLite/logging/I/O free.
- [ ] Run `pytest -q tests/test_eligibility*.py`.
- [ ] Commit:

```bash
git add src/eligibility.py tests/test_eligibility.py
git commit -m "feat(m6.11): evaluate two-stage eligibility policy"
```

---

### Task 5: Add idempotent database helpers and the early gate

**Files:**
- Modify: `src/db.py`
- Rewrite: `src/prefilter.py`
- Rewrite/modify: `tests/test_prefilter.py`
- Modify: `tests/test_db.py`

**DB/helper contracts:**

```python
@dataclass(frozen=True)
class EligibilityGateSummary:
    evaluated: int = 0
    filtered: int = 0
    deferred: int = 0
    passed: int = 0
    by_reason: tuple[tuple[str, int], ...] = ()
    by_flag: tuple[tuple[str, int], ...] = ()

def eligibility_rows(conn, status: Status) -> list[sqlite3.Row]: ...
def merge_job_flags(conn, job_id: int, flags: tuple[str, ...]) -> bool: ...
def mark_eligibility_filtered(conn, job_id: int, *, expected_status: Status, reason: str) -> bool: ...

# src/prefilter.py
def run_pre_resolution_gate(conn, config: EligibilityConfig) -> EligibilityGateSummary: ...
def run_post_resolution_gate(conn, config: EligibilityConfig) -> EligibilityGateSummary: ...
```

`eligibility_rows` must use stable `ORDER BY id`. `mark_eligibility_filtered` must update only
when the row still has the expected status and the target values differ, return whether a
row changed, and never overwrite a terminal status. `merge_job_flags` preserves unrelated
existing flags, stores a sorted unique JSON list, and makes no write when unchanged.

`src/prefilter.py` is retained as the orchestration module to minimize import churn, but its
old `PrefilterResult`, `evaluate`, raw SQL, and business-policy parsing are removed. It calls
the pure evaluator and DB helpers only. Each gate may commit once after its complete sweep;
no SQL string may remain outside `src/db.py`.

- [ ] Write failing DB tests for ordered selection, expected-status compare-and-set,
      preservation of terminal states, flag merging, unchanged return values, and repeated
      calls.
- [ ] Rewrite prefilter tests to seed DISCOVERED rows and prove Canadian/disabled/out-of-
      window explicit cases filter before resolution while unknown evidence remains
      DISCOVERED; seed RESOLVED rows and prove authoritative decisions/flags.
- [ ] Assert the second identical gate run has `filtered == 0`, does not change any job
      field, and produces no additional commit-visible mutation.
- [ ] Implement helpers in `src/db.py`, then the orchestration adapter.
- [ ] Run `pytest -q tests/test_db.py tests/test_prefilter.py`.
- [ ] Commit:

```bash
git add src/db.py src/prefilter.py tests/test_db.py tests/test_prefilter.py
git commit -m "feat(m6.11): add idempotent eligibility gates"
```

---

### Task 6: Wire both gates into ingestion and structured run accounting

**Files:**
- Modify: `src/run_ingest.py`
- Modify: `tests/test_run_ingest.py`
- Modify: `tests/test_run_ingest_lifecycle.py` only if its finalization fixtures need the new
  summary input

**Run-ingest changes:**

1. Add `load_eligibility_config()` as a thin call to `eligibility.load_eligibility_config`.
2. In `main`, parse/select sources, then load and validate eligibility, source, freshness,
   and browser flags needed by the run **before** `db.get_connection()` and `db.start_run()`.
   Preserve existing CLI behavior and M6.10 finalization guarantees.
3. Immediately before `run_resolution()`, run `run_pre_resolution_gate()` in normal and
   `--resolve-only` modes.
4. Run `run_post_resolution_gate()` immediately after resolution.
5. Set `filtered_count` to early plus post newly-filtered counts. Include both gate summaries
   in structured `runs.notes` under an `eligibility_summary` object with stable keys
   `pre_resolution` and `post_resolution`; no schema change.
6. Keep `--discover-only` discovery-only. It must not evaluate or mutate eligibility.
7. Do not create `PoliteSession` or browser client until after the early gate.

- [ ] Write a red test patching resolution/network construction and seed `Remote - Canada`;
      prove the row becomes FILTERED_OUT and no resolver/session/browser call occurs for it.
- [ ] Prove an unknown-location DISCOVERED row reaches the mocked resolver.
- [ ] Prove both normal and `--resolve-only` execute early then post gates in order, while
      `--discover-only` executes neither.
- [ ] Prove invalid eligibility config returns/raises through the existing CLI error model
      before connection/start-run and leaves the database absent/unchanged. Prefer a clean
      logged nonzero return rather than a traceback for a user configuration error.
- [ ] Prove run `filtered_out` equals pre+post changes and notes contain both summaries even
      on an aborted run after the early gate.
- [ ] Adjust `finalize_run`/`_run_notes` signatures with a default empty eligibility summary
      if that keeps lifecycle tests concise; do not weaken exactly-once finalization.
- [ ] Implement and run:

```bash
pytest -q tests/test_run_ingest.py tests/test_run_ingest_lifecycle.py tests/test_prefilter.py
```

- [ ] Commit:

```bash
git add src/run_ingest.py tests/test_run_ingest.py tests/test_run_ingest_lifecycle.py
git commit -m "feat(m6.11): enforce country-first eligibility during ingest"
```

If `tests/test_run_ingest_lifecycle.py` did not change, omit it from `git add`.

---

### Task 7: Migrate audit and remove the legacy policy source

**Files:**
- Modify: `config/filters.yaml`
- Modify: `src/audit/__init__.py`
- Modify: `src/audit/invariants_sources.py`
- Modify: `src/audit/invariants_db.py`
- Modify: `src/audit/invariants_export.py`
- Modify: `src/audit/invariants_llm.py`
- Modify: `src/run_ingest.py`
- Modify: `tests/test_audit_orchestrator.py`
- Modify: `tests/test_audit_invariants_sources.py`
- Modify: `tests/test_audit_invariants_db.py`
- Modify any direct invariant-call tests only to supply the new argument

`config/filters.yaml` must end with only scoring-owned keys (currently
`score_threshold: 7`). Delete `title_include`, `title_exclude`, `location_allow`,
`jd_flags`, and `years_cap` only in this task after every production consumer is migrated.

Change audit signatures uniformly to avoid hidden config merging:

```python
def run_all(
    conn,
    *,
    audit_config: dict,
    filters_config: dict,       # scoring-only threshold config
    eligibility_config: EligibilityConfig,
    freshness_config: dict,
    repo_root: Path = Path("."),
) -> AuditResult: ...

def check_iN(
    conn, audit_config, filters_config, eligibility_config, freshness_config, repo_root
) -> Finding: ...
```

All invariant modules accept the uniform signature. I8 continues to read
`score_threshold` from `filters_config`. I2 and I6a evaluate eligibility through the new
pure evaluator. I6a uses POST decisions and reports only FILTER outcomes leaking into
active/scored/application states. I2 evaluates RESOLVE_FAILED metadata at PRE stage; only
rows that are explicit eligibility FILTER outcomes are excluded from resolver-gap evidence,
while DEFER/PASS remain relevant. Neither invariant mutates eligibility state.

- [ ] Write red I2/I6a tests for explicit Canada, unknown location, sponsorship silence,
      and explicit no-sponsorship leakage.
- [ ] Update orchestrator tests to prove score and eligibility configs remain distinct and
      are passed to every check.
- [ ] Update `run_ingest` audit call to pass the already-validated typed eligibility config;
      never reload a second policy mid-run.
- [ ] Remove legacy keys from `config/filters.yaml` and run `rg -n 'title_include|title_exclude|location_allow|jd_flags|years_cap' src config tests`.
      Remaining hits are allowed only in legacy-impact reason lists/tests or historical docs,
      not active config consumers.
- [ ] Run:

```bash
pytest -q tests/test_audit_orchestrator.py tests/test_audit_invariants_sources.py tests/test_audit_invariants_db.py tests/test_run_ingest.py
```

- [ ] Run scoring regression tests to prove threshold loading still works:

```bash
pytest -q tests/test_score_batch.py tests/test_export_batch.py tests/test_import_scores.py
```

- [ ] Commit all and only changed migration files:

```bash
git add config/filters.yaml src/audit src/run_ingest.py tests/test_audit_orchestrator.py tests/test_audit_invariants_sources.py tests/test_audit_invariants_db.py
git commit -m "refactor(m6.11): migrate audit to eligibility policy v2"
```

Add any other actually modified direct invariant test by exact path; do not stage unrelated
files.

---

### Task 8: Build the read-only impact report and guarded apply path

**Files:**
- Modify: `src/db.py`
- Create: `scripts/eligibility_impact.py`
- Create: `tests/test_eligibility_impact.py`

Keep transition calculation pure enough to test. Recommended contracts:

```python
class ImpactAction(str, Enum):
    FILTER_DISCOVERED = "filter_discovered"
    FILTER_ACTIVE = "filter_active"
    RESTORE_LEGACY = "restore_legacy"
    REPORT_TERMINAL = "report_terminal"

@dataclass(frozen=True)
class ImpactTransition:
    job_id: int
    action: ImpactAction
    from_status: str
    to_status: str | None
    reason_code: str | None
    evidence: tuple[str, ...]

def build_impact(conn, config: EligibilityConfig) -> tuple[ImpactTransition, ...]: ...
def apply_eligibility_transitions(
    conn, transitions: tuple[ImpactTransition, ...]
) -> int: ...  # db.py; one transaction, exact compare-and-set
```

The script CLI must default to preview and accept at least:

```text
python -m scripts.eligibility_impact --db data/jobs.db
python -m scripts.eligibility_impact --db data/jobs.db --json PATH
python -m scripts.eligibility_impact --db data/jobs.db --apply --confirm APPLY --backup PATH
```

Preview uses `db.get_readonly_connection()` and must not create/modify the database, output
file, or any other file unless `--json PATH` is explicitly supplied. The JSON report has a
version, policy version, generation timestamp, counts by action/reason, and sorted transition
records. Applying must refuse without both exact `--confirm APPLY` and a non-existing backup
path; create the backup via SQLite's backup API before the transaction; apply exactly the
freshly recomputed preview in one transaction; rollback all changes on any mismatch/error.

Selection and transition policy is exact:

- DISCOVERED: report/apply PRE FILTER outcomes.
- RESOLVED/SCORED/SHORTLISTED: report/apply POST FILTER outcomes.
- Legacy FILTERED_OUT with reason `location`, `title_include`, `title_exclude`, or matching
  `yoe:*`: if POST evaluation now passes, restore to RESOLVED, clear `filter_reason`, and
  clear `fit_score`, `fit_rationale`, `base_variant`, `missing_keywords`, and `borderline`.
- APPLIED/REJECTED/TAILORED/CLOSED: report eligibility observations only; never apply them.
- Active SCORED/SHORTLISTED rows filtered by v2 preserve historical scoring fields.
- Already-v2 FILTERED_OUT rows are not reopened by this migration command.

All SQL and the transaction live in `src/db.py`. The script must not contain SQL. Database
helpers must compare expected old status/reason for every transition so a stale preview
cannot overwrite concurrent state. Report order is action, job ID.

- [ ] Write red tests seeding one row for every category above plus unrelated legacy/new
      filter reasons.
- [ ] Prove preview returns exact transitions/reasons, terminal records have no target
      status, and preview leaves `jobs`, `runs`, filesystem, and DB modification state
      unchanged.
- [ ] Prove apply refuses missing/wrong confirmation, refuses an existing backup path,
      writes a readable backup before mutation, applies exactly the preview, preserves
      active scoring history, clears restored-row scoring fields, and never mutates terminal
      rows.
- [ ] Prove a forced mid-transaction exception rolls everything back.
- [ ] Prove a second preview after apply has zero actionable transitions and a second apply
      changes zero rows.
- [ ] Implement and run:

```bash
pytest -q tests/test_eligibility_impact.py tests/test_db.py
```

- [ ] Commit:

```bash
git add src/db.py scripts/eligibility_impact.py tests/test_eligibility_impact.py
git commit -m "feat(m6.11): add guarded eligibility impact migration"
```

---

### Task 9: Offline integration verification and documentation

**Files:**
- Modify: `tests/test_idempotency.py` if needed for end-to-end gate coverage
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/DECISIONS.md`

- [ ] Add/extend an offline end-to-end idempotency test that seeds a mix of explicit Canada,
      unknown country, eligible full-time 2027, eligible Spring 2027 internship, explicit
      no-sponsorship, and unknown full-time start. Run the same gate flow twice and compare
      complete job rows; the second run may change no fields.
- [ ] Run every focused M6.11 test:

```bash
pytest -q tests/test_eligibility_config.py tests/test_eligibility_country.py tests/test_eligibility_opportunity_dates.py tests/test_eligibility.py tests/test_prefilter.py tests/test_eligibility_impact.py tests/test_run_ingest.py tests/test_run_ingest_lifecycle.py tests/test_audit_orchestrator.py tests/test_audit_invariants_sources.py tests/test_audit_invariants_db.py tests/test_idempotency.py
```

- [ ] Run the entire suite:

```bash
pytest -q
```

Expected: all tests pass; no test makes a network/browser call. Do not claim a fixed total
because this milestone adds tests.

- [ ] Inspect `git diff --check` and `git status --short`. Confirm the user's pre-existing
      dirty/untracked files are untouched.
- [ ] Update `docs/ARCHITECTURE.md` with the implemented two-stage deterministic data-plane
      flow, config ownership boundary, country-first semantics, and impact/apply boundary.
- [ ] Update `docs/ROADMAP.md` to mark M6.11 offline implementation complete but live
      acceptance pending. Do not mark the milestone fully complete yet.
- [ ] Add a dated `docs/DECISIONS.md` entry recording the accepted configurable policy,
      silence/ambiguity sponsorship semantics, unknown country/full-time-start behavior,
      strict internship window, no dependency/schema change, automated test evidence, and
      the pending user-supervised gates.
- [ ] Correct any stale M6.10 status wording encountered in these three docs, but do not
      rewrite unrelated roadmap milestones.
- [ ] Commit docs and any idempotency test:

```bash
git add docs/ARCHITECTURE.md docs/ROADMAP.md docs/DECISIONS.md tests/test_idempotency.py
git commit -m "docs(m6.11): record offline eligibility implementation"
```

If `tests/test_idempotency.py` did not change, omit it. Then **stop and show the user**:

- full-suite result;
- exact commits created;
- `git status --short` with pre-existing user files identified;
- the dry impact command that will be run next.

Do not run against `data/jobs.db`, create a live backup, or apply transitions until the user
explicitly approves Task 10 after reviewing this checkpoint.

---

### Task 10: User-supervised live impact, apply, smoke, and completion (GATED)

This task begins only after explicit user approval in a fresh continuation. It is still part
of M6.11; do not start the next milestone.

- [ ] Confirm no ingest, resolver, scorer, or import process is active. Use read-only process
      inspection and report any match rather than killing it.
- [ ] Record a read-only baseline: database path/size, `PRAGMA integrity_check`, row counts by
      status, and current git HEAD/status.
- [ ] Run the read-only impact preview against `data/jobs.db`, save the explicitly requested
      JSON report under `data/eligibility-impact/`, and present counts plus row IDs grouped by
      action/reason to the user.
- [ ] Stop for a second explicit approval of the exact preview. Preview approval is not apply
      approval.
- [ ] On approval, choose a timestamped non-existing backup path such as
      `data/backups/jobs-pre-m6.11-YYYYMMDDTHHMMSSZ.db` and run the guarded apply command with
      `--apply --confirm APPLY --backup ...`.
- [ ] Verify backup readability, `PRAGMA integrity_check`, exact transition count, preserved
      terminal rows, restored-row scoring clears, and preserved active-row historical scores.
- [ ] Rerun preview and require zero actionable transitions. If not zero, stop and diagnose;
      do not repeatedly apply.
- [ ] With user approval, run a bounded live smoke using the existing CLI and a small
      `--resolve-limit` (default proposal: 5). Observe that an explicitly non-US discovered
      row, if present, is filtered before any resolver attempt and that resolved eligibility
      outcomes match policy. Do not fabricate a production posting solely to force evidence;
      if the bounded live sample lacks an explicit non-US row, report that the offline
      no-network-call test is the country-first evidence and mark only that live observation
      as not encountered.
- [ ] Run `pytest -q` again and `git diff --check`.
- [ ] Update `docs/ROADMAP.md` to complete M6.11 and `docs/DECISIONS.md` with backup path,
      preview/apply counts, post-apply zero-diff result, smoke command/evidence, and final test
      count.
- [ ] Commit only milestone documentation (and any narrowly required smoke-discovered fix,
      after TDD and re-verification) with:

```bash
git add docs/ROADMAP.md docs/DECISIONS.md
git commit -m "feat(m6.11): complete configurable eligibility policy"
```

- [ ] Use `superpowers:verification-before-completion`, show final git status/commits/test
      evidence, and stop. The next action is planning Calibration Contract v2 in a separate
      task; do not implement it here.

## Final acceptance checklist

- [ ] Eligibility configuration is typed, validated, and loaded before production mutation.
- [ ] Country is evaluated first and explicit non-US metadata avoids resolution.
- [ ] Full-time 2027 and Spring/January-May 2027 internship behavior matches the approved
      policy, including distinct unknown-date handling.
- [ ] Explicit no-sponsorship/citizenship-only filters; silence and configured ambiguity are
      retained correctly.
- [ ] Changing countries, types, dates, seasons, role patterns, seniority cap, or sponsorship
      patterns requires configuration only.
- [ ] No active eligibility policy remains in `config/filters.yaml` or old prefilter code.
- [ ] Audit I2/I6a use the same typed policy as ingestion.
- [ ] DB access is confined to `src/db.py`; no schema/dependency/network-test change.
- [ ] Pipeline and impact application are idempotent.
- [ ] Live DB preview was reviewed; any apply had explicit approval and a verified backup.
- [ ] Full tests, docs, live smoke, and milestone commits are complete.
- [ ] Calibration Contract v2, M8, and M9D were not started.
