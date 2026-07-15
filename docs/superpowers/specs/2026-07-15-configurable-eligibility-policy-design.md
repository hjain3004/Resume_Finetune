# Configurable Eligibility Policy v2 Design

**Status:** Draft for user review on 2026-07-15.

## 1. Purpose

The pipeline currently expresses eligibility through a few regular expressions in
`config/filters.yaml`. That mechanism is insufficient for the user's current search:

- United States roles only;
- full-time roles whose stated start falls in calendar year 2027;
- Spring 2027 internships whose stated start falls from January through May 2027;
- explicit no-sponsorship or US-citizens-only postings rejected;
- silence about sponsorship accepted;
- role family, opportunity type, dates, country, seniority, and authorization policy all
  configurable rather than embedded in Python.

The existing location rule is not a country policy. It allows the bare word `remote`, so
`Remote - Canada` can pass, while US locations not named in the regex can fail. It also runs
only after JD resolution, after the pipeline may already have spent network and browser work
on an explicitly out-of-country posting. Employment type is inferred only from a narrow
internship title exclusion; co-op, contract, part-time, and temporary roles are not modeled.

Eligibility Policy v2 creates a deterministic, configuration-driven eligibility boundary
before scoring. It is a prerequisite to Calibration Contract v2: calibration must not learn
preferences from jobs that policy should have removed.

## 2. Milestone boundary

This design is one implementation milestone named **M6.11 — Configurable
Eligibility Policy v2**.

M6.11 includes:

- validated structured eligibility configuration;
- deterministic country, opportunity-type, start-window, role-family, seniority, and work-
  authorization classification;
- a conservative pre-resolution metadata gate;
- an authoritative post-resolution eligibility gate;
- stable reasons and review flags;
- a read-only-by-default impact report for existing rows;
- a user-approved, backed-up one-off application path;
- offline tests and a bounded live smoke.

M6.11 does **not** include:

- the `interest_call` / JD-informed `fit_call` calibration contract;
- scoring-prompt, profile-summary, score-threshold, or stress-band changes;
- automatic application submission;
- new discovery sources, M9D-1, M8, Crawlee, Apify, or a new dependency;
- probabilistic or LLM-based eligibility classification;
- an automatic rewrite of the live database during tests or deployment.

Calibration Contract v2 becomes the next separately planned milestone after M6.11 is
accepted.

## 3. Policy configuration

Create `config/eligibility.yaml` as the only business-policy source for eligibility. Python
implements generic parsing and evaluation; it must not contain the allowed country, enabled
opportunity types, target dates, role-family choices, or authorization decisions.

The initial configuration has this semantic shape:

```yaml
version: 2

countries:
  allowed: [US]
  explicit_non_match: reject
  unknown_pre_resolution: defer
  unknown_post_resolution: allow_with_flag
  remote_without_country: unknown

opportunity_types:
  classification_order: [internship, co_op, contract, part_time, temporary, full_time]
  default_when_unmarked: full_time
  patterns:
    internship: ["\\bintern(ship)?\\b"]
    co_op: ["\\bco[- ]?op\\b", "\\bcooperative education\\b"]
    contract: ["\\bcontract(or)?\\b", "\\b1099\\b"]
    part_time: ["\\bpart[- ]time\\b"]
    temporary: ["\\btemporary\\b", "\\btemp\\b"]
    full_time: ["\\bfull[- ]time\\b", "\\bnew grad(uate)?\\b", "\\bgraduate\\b"]
  types:
    full_time:
      enabled: true
      start_windows:
        - {earliest: "2027-01-01", latest: "2027-12-31"}
      year_only_evidence: sufficient
      unknown_start_pre_resolution: defer
      unknown_start_post_resolution: allow_with_flag
    internship:
      enabled: true
      allowed_seasons: [spring]
      start_windows:
        - {earliest: "2027-01-01", latest: "2027-05-31"}
      year_only_evidence: insufficient
      unknown_start_pre_resolution: defer
      unknown_start_post_resolution: reject
    co_op: {enabled: false}
    contract: {enabled: false}
    part_time: {enabled: false}
    temporary: {enabled: false}

seasons:
  spring: {months: [1, 2, 3, 4, 5]}
  summer: {months: [6, 7, 8]}
  fall: {months: [9, 10, 11, 12]}

role_families:
  include:
    - name: software_engineering
      patterns:
        - "software|swe|backend|back.end|full.?stack|platform|infrastructure|distributed|developer"

seniority:
  title_exclude_patterns:
    - "senior|staff|principal|lead|manager|director"
    - "\\b(7|8|9|10)\\+?\\s*years"
  years_cap: 3

work_authorization:
  silence: allow
  ambiguous: allow_with_flag
  explicit_no_sponsorship: reject
  citizenship_required: reject
  patterns:
    explicit_no_sponsorship:
      - "unable to sponsor"
      - "no (?:visa )?sponsorship"
      - "will not sponsor"
      - "not.{0,30}sponsor"
      - "without sponsorship now or in the future"
    citizenship_required:
      - "US citizens? only"
      - "must be (?:a )?US citizen"
      - "US citizenship (?:is )?required"
    positive_sponsorship:
      - "visa sponsorship (?:is )?available"
      - "we (?:can|will) sponsor"
    ambiguous:
      - "authorized to work in the (?:US|United States)"

flags:
  country_unknown: country_unknown
  start_date_unknown: start_date_unknown
  authorization_ambiguous: authorization_ambiguous
  opportunity_type_inferred: opportunity_type_inferred
```

The exact spelling of the YAML keys is part of the contract. Configuration validation
must reject unsupported policy values, invalid ISO country codes, invalid or inverted date
windows, unknown enabled types, invalid season references, invalid regular expressions,
negative experience caps, and an empty role-family include list.

Configuration is loaded and validated before `db.start_run()` or any other production
mutation. Invalid configuration is an infrastructure error: the command exits nonzero and
does not create a run row.

Eligibility keys currently living in `config/filters.yaml` (`title_include`,
`title_exclude`, `location_allow`, `jd_flags`, and `years_cap`) move to the new contract
once every production, audit, and test consumer has been updated. `score_threshold` remains
in `config/filters.yaml`; scoring configuration and eligibility configuration must not be
silently merged into one dictionary. There is no dual-source compatibility period in which
two files can disagree about the active eligibility policy.

## 4. Country recognition

Country evaluation returns exactly one of:

- `EXPLICIT_ALLOWED`;
- `EXPLICIT_DISALLOWED`;
- `UNKNOWN`.

The configured `countries.allowed` list is business policy. A separate deterministic
`config/location_taxonomy.yaml` supplies parsing vocabulary: ISO-3166 country names/codes,
common aliases, and US state names/abbreviations. The taxonomy is local version-controlled
data and adds no runtime dependency. Users change target countries in `eligibility.yaml`,
not Python.

Country evaluation is deliberately asymmetric:

- an explicit non-allowed country is safe to reject early;
- a recognized US state or explicit United States marker is allowed;
- bare `Remote`, an empty location, or an unrecognized city is `UNKNOWN`;
- `Remote - Canada` is explicitly Canada and cannot pass merely because it contains
  `remote`;
- unknown evidence is never converted into an explicit non-US judgment.

Country is the first evaluated dimension. An explicit country mismatch short-circuits all
later eligibility work.

## 5. Opportunity type and start-window recognition

Opportunity type is selected using the configured classification order and configured
patterns over title first, then title plus full JD after resolution. Specific non-full-time
signals take precedence over the configured default. A posting with no type marker uses
`default_when_unmarked` and receives `opportunity_type_inferred`.

Date recognition is deterministic. Generic code may recognize month names, numeric dates,
four-digit years, and configured season names; target windows remain configuration. The
policy uses the following rules:

- a full-time posting with explicit 2027 year evidence is eligible;
- a full-time posting with an exact or month-level start inside 2027 is eligible;
- an explicitly 2026-only or 2028-only full-time start is rejected;
- a full-time posting with no start evidence after resolution is retained with
  `start_date_unknown`;
- `Spring 2027` is sufficient internship evidence;
- an internship with an explicit start from January through May 2027 is eligible;
- `Summer 2027`, `Fall 2027`, a 2026 internship, and a 2028 internship are rejected;
- `2027 internship` without a season/month is insufficient and remains deferred before
  resolution, then is rejected if the full JD supplies nothing more specific;
- when a posting explicitly offers multiple start dates, it is eligible if at least one
  configured start window matches.

Changing the configured dates, seasons, or enabled types must change decisions without a
code edit.

## 6. Work-authorization policy

Work authorization is evaluated from structured source evidence when available and from
the literal full JD after resolution. Evidence precedence is:

1. explicit no-sponsorship or citizenship-required text;
2. explicit positive sponsorship evidence;
3. ambiguous authorization language;
4. silence.

An explicit negative always wins over an aggregator-derived `sponsor_likely` flag. The
initial policy is:

- explicit no-sponsorship: reject;
- US citizenship required / US citizens only: reject;
- generic work-authorization language without a sponsorship prohibition: retain with
  `authorization_ambiguous`;
- no sponsorship language: allow;
- positive sponsorship language: allow.

The matcher must use bounded, reviewable patterns so equal-opportunity boilerplate mentioning
`citizenship status` does not become a citizenship requirement.

This replaces the current policy that merely flags explicit no-sponsorship language and
allows the row to reach scoring. `docs/scoring_prompt.md` is not changed in M6.11 because
explicitly ineligible rows will no longer reach it; removal of stale prompt wording belongs
to the later calibration/prompt milestone after eligibility is live-verified.

## 7. Two-stage eligibility flow

### 7.1 Pre-resolution metadata gate

For full and resolve-only runs, evaluate `DISCOVERED` rows before network resolution using
the available title, location, and flags. `date_posted` is the publication date and must
never be treated as a role start date. The dimension order is:

1. country;
2. opportunity type;
3. start-window evidence;
4. role family;
5. title-level seniority.

Only explicit failures are marked `FILTERED_OUT`. Missing evidence produces `DEFER`, leaves
the row `DISCOVERED`, and permits resolution. This gate is where an explicit Canadian role,
disabled co-op, Summer 2027 internship, or clearly senior title avoids expensive resolution.

`--discover-only` remains discovery-only and does not run the gate. A normal run and a
`--resolve-only` run both run it immediately before `run_resolution()`.

### 7.2 Post-resolution authoritative gate

After a row becomes `RESOLVED`, evaluate title, normalized location, flags, and full JD in
this order:

1. country;
2. work authorization;
3. opportunity type;
4. start window;
5. role family;
6. seniority / required years;
7. non-rejection review flags.

Post-resolution unknown handling follows configuration. For the initial policy, unknown
country and unknown full-time start are retained with flags, while an internship still
lacking Spring 2027/January-May 2027 evidence is rejected. Rows that pass remain `RESOLVED`
and may be exported for scoring.

## 8. Pure interfaces and persistence boundary

Eligibility reasoning lives in `src/eligibility.py`, separate from SQLite orchestration.
The public contract is:

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

Stable rejection reasons are:

- `eligibility:country`;
- `eligibility:work_authorization`;
- `eligibility:opportunity_type`;
- `eligibility:start_window`;
- `eligibility:role_family`;
- `eligibility:seniority`.

SQLite writes remain in `src/db.py`. The orchestration layer may request an idempotent
status/flag transition through DB helpers but contains no SQL. A second identical run must
make no additional job-row changes.

No schema migration is required in M6.11. Stable reason codes use `filter_reason`; retained
uncertainty uses the existing JSON `flags` column. Human-readable evidence appears in the
impact report and logs, not in a new database column.

## 9. Existing-row impact and controlled application

Deployment does not automatically reclassify the live database. Add a dedicated impact
command that is read-only unless an explicit apply flag is supplied.

The dry report covers:

- `DISCOVERED` rows that would be filtered before resolution;
- `RESOLVED`, `SCORED`, and `SHORTLISTED` rows that would now be filtered;
- legacy `FILTERED_OUT` rows with `location`, `title_include`, `title_exclude`, or `yoe:*`
  reasons that would become eligible under the new policy;
- terminal `APPLIED`, `REJECTED`, `TAILORED`, and `CLOSED` rows as report-only observations.

It reports counts and row identifiers by transition and reason, including explicit
work-authorization rejections and newly eligible Spring 2027 internships. Dry-run execution
must produce no database or file mutation.

Applying the report is a user-supervised acceptance step. Before application:

1. confirm no ingest/resolution/scoring process is active;
2. create a timestamped non-overwriting database backup;
3. show the exact transition counts to the user;
4. require explicit approval;
5. apply only the reported eligible transition set in one transaction;
6. rerun the report and require zero remaining proposed transitions.

Rows already in a terminal application/tailoring outcome are never changed automatically.
When an active `SCORED` or `SHORTLISTED` row becomes ineligible, the apply transaction sets
its status to `FILTERED_OUT` and records the new stable reason while preserving its scoring
fields as historical evidence. If a legacy `FILTERED_OUT` row becomes eligible, the apply
transaction sets it to `RESOLVED`, clears `filter_reason`, and clears `fit_score`,
`fit_rationale`, `base_variant`, `missing_keywords`, and `borderline` so it must pass through
fresh scoring. Existing `RESOLVED` rows that remain eligible keep their state and fields.

## 10. Error handling and observability

- Invalid configuration aborts before a run row or job mutation.
- Regex compilation errors identify the exact configuration path.
- An unrecognized location/date/type is unknown evidence, not an internal exception and not
  an invented classification.
- Filter reasons are stable machine-readable values; flags remain visible in export and
  digest output.
- A normal run records early- and post-resolution filtered counts in existing run accounting;
  detailed policy counts are included in structured run notes without a schema migration.
- The impact command exits nonzero on malformed configuration, a missing database, or a
  transaction failure.

## 11. Testing strategy

All automated tests are offline and use pure fixtures or temporary SQLite databases.

Required behavioral coverage includes:

- `Toronto, Canada` and `Remote - Canada` filter before any HTTP call;
- a recognized US state/location is not rejected as non-US;
- bare `Remote`, empty, and unrecognized locations defer early rather than becoming non-US;
- full-time 2027 and `New Grad 2027` pass;
- explicit full-time 2026/2028 fails;
- full-time with no start evidence is retained post-resolution with `start_date_unknown`;
- Spring 2027 and January-May 2027 internships pass;
- Summer/Fall 2027 and non-2027 internships fail;
- internship with insufficient date/season evidence defers early and fails after resolution;
- disabled co-op, contract, part-time, and temporary postings fail;
- explicit no-sponsorship and citizenship-required language fail;
- authorization-only ambiguity is retained with a flag;
- sponsorship silence passes;
- equal-opportunity citizenship-status boilerplate does not trigger rejection;
- explicit negative JD evidence overrides a pre-existing `sponsor_likely` flag;
- changing allowed countries, start windows, enabled types, role patterns, and experience cap
  changes outcomes without code edits;
- country mismatch short-circuits later evaluation;
- a repeated identical run is idempotent;
- dry impact reporting performs no writes;
- the user-approved apply transaction produces exactly the previewed transitions;
- existing discovery, resolution, scoring export, audit, and digest tests remain green.

## 12. Acceptance criteria

M6.11 is complete only when:

1. the structured configuration and taxonomy validate deterministically;
2. explicit non-US roles are filtered before resolution while unknown locations are preserved;
3. the configured 2027 full-time and Spring 2027 internship windows behave as specified;
4. explicit no-sponsorship/citizenship-only roles are rejected and sponsorship silence passes;
5. policy changes require configuration edits only;
6. automated tests pass with no network/browser use;
7. a dry live-DB impact report is reviewed by the user;
8. any live application is backed up, explicitly approved, transactional, and idempotent;
9. a bounded live ingest/resolve smoke demonstrates country-first behavior and correct
   post-resolution decisions;
10. `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/DECISIONS.md` record the implemented
    behavior and evidence;
11. the milestone is committed and stops without beginning Calibration Contract v2, M9D-1,
    or M8.

## 13. Subsequent milestone

After M6.11 acceptance, plan and implement Calibration Contract v2 using the already agreed
human contract:

- `interest_call` is the metadata-only impression;
- `fit_call` is the final APPLY/MAYBE/SKIP decision after reading the full JD;
- APPLY and MAYBE are positive for the 7+ human-review shortlist;
- SKIP is negative;
- the review packet is versioned, references the exact source batch, contains one canonical
  job group per row, and embeds the full JDs.

That later milestone must consume only jobs that have passed Eligibility Policy v2.
