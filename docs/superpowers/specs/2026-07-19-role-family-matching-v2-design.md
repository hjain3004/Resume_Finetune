# Role-Family Matching v2 Design

**Status:** Draft for user review on 2026-07-19.

## 1. Purpose

Calibration round `2026-07-17-r2` surfaced three eligibility-passed jobs with no
software-engineering relationship at all: id=96 (RG&T Solutions, "Casino Game Tester"),
id=123 (Heron Power, "Power Electronics PCBA Technician"), id=111 (ByteDance, "Graduate
Research Scientist"). Investigation traced this to `role_family` matching in
`src/eligibility.py`: `config/eligibility.yaml`'s `software_engineering` family is a single
regex (`software|swe|backend|back.end|full.?stack|platform|infrastructure|distributed|
developer`) checked against the title first; if the title doesn't match, `evaluate()` falls
back to searching the full post-resolution JD text and passes on **one incidental word match
anywhere in the JD**. All three jobs above passed the fallback on a single word ("platform",
"infrastructure", "developer") that had nothing to do with the role itself.

`docs/PHASE2_KICKOFF.md` (M6.9 note 3) documents a JD-text fallback as *intentional*: it
exists so non-standard-title engineering roles (front-end, embedded) still reach the scorer,
which prices wrong-specialty postings at 3-4 with JD context a regex can't use. The
documented revisit trigger — wrong-specialty rows exceeding ~20% of *scored* volume — is not
met (0/45 scored rows are wrong-specialty as of this session). This design is therefore an
explicit, user-approved deviation from that documented threshold, not a response to it: the
user has judged the current mechanism too weak regardless of scored-volume impact, because it
already let three clearly-wrong-category jobs reach human calibration review. Recording this
deviation in `docs/DECISIONS.md` is part of this milestone's completion, per `CLAUDE.md`
prime directive 1.

This design keeps the *intent* of M6.9 note 3 (non-standard-title genuine SWE roles should
still reach the scorer) while closing the specific gap: a single incidental keyword should
never be sufficient signal, and titles that are unambiguously a different discipline should
never reach the scorer at all.

## 2. Milestone boundary

This design is one implementation milestone named **M6.12 — Role-Family Matching v2**.

M6.12 includes:

- restructuring `role_families.include[].patterns` from one alternation string into a list of
  individual term patterns (same YAML schema, different content shape) so distinct hits are
  countable;
- a new `role_families.include[].exclude_patterns` field: title-only hard-exclusion regexes,
  checked before any positive match;
- a new global `role_families.jd_fallback_min_hits` config value (default 2): the JD-only
  fallback now requires at least this many *distinct* include patterns to match, not one;
- `src/eligibility.py` logic changes to `evaluate()`'s role-family step implementing the
  above, with a new `eligibility:role_family_excluded` reason code distinct from the existing
  `eligibility:role_family`;
- unit tests in `tests/test_eligibility.py` covering exclude-first precedence, the raised
  fallback bar, and unchanged title-match-passes-outright behavior;
- a read-only impact preview (reusing `scripts/eligibility_impact.py` unchanged — it already
  re-evaluates every row against whatever policy is loaded), user review of the transition
  list, a timestamped backup of `data/jobs.db`, then an approved apply;
- a `docs/DECISIONS.md` entry recording this as an approved deviation from the M6.9 fallback
  design and the current impact numbers;
- regeneration of calibration round `2026-07-17-r2` if the apply step removes any of its 12
  jobs (expected: ids 96, 111, 123 are removed; the round is discarded and redrawn the same
  way the contaminated `2026-07-17-r1` was, per the existing `--exclude-round` mechanism).

M6.12 does **not** include:

- changes to the scoring prompt, profile summary, or fit-score thresholds;
- changes to country, opportunity-type, start-window, seniority, or work-authorization
  eligibility logic (only the role-family step changes);
- a general-purpose taxonomy engine, ML/embedding-based matching, or per-family confidence
  scoring beyond the hit-count threshold;
- new dependencies;
- automatic re-scoring of any already-scored row.

## 3. Config schema changes (`config/eligibility.yaml`)

Before:

```yaml
role_families:
  include:
    - name: software_engineering
      patterns:
        - "software|swe|backend|back.end|full.?stack|platform|infrastructure|distributed|developer"
```

After:

```yaml
role_families:
  jd_fallback_min_hits: 2
  include:
    - name: software_engineering
      patterns:
        - "software"
        - "\\bswe\\b"
        - "backend"
        - "back.end"
        - "full.?stack"
        - "platform"
        - "infrastructure"
        - "distributed"
        - "developer"
      exclude_patterns:
        - "technician"
        - "\\bresearch scientist\\b"
        - "\\banalyst\\b"
        - "\\bauditor\\b"
        - "\\b(game\\s+)?tester\\b"
        - "casino"
```

`exclude_patterns` seed list is drawn from evidence gathered this session (ids 96, 111, 123)
plus two previously-known non-engineering passers named in `docs/DECISIONS.md`'s 2026-07-17
entry (id=44 QA Auditor, id=53 SAP SD Analyst). The user reviews and may edit this list before
implementation.

`RoleFamily` (dataclass in `src/eligibility.py`) gains an `exclude_patterns:
tuple[Pattern[str], ...]` field, parsed the same way as `patterns` via `_compile_patterns`.
`RoleFamilyPolicy` gains `jd_fallback_min_hits: int`, parsed and validated as a positive int
the same way `seniority.years_cap` is validated today.

## 4. Logic changes (`src/eligibility.py`, `evaluate()`)

Current role-family step (lines ~721-723):

```python
if not any(pattern.search(title) or (stage is EligibilityStage.POST_RESOLUTION and jd_text and pattern.search(jd_text))
           for family in config.role_families.include for pattern in family.patterns):
    return _decision(EligibilityDisposition.FILTER, "eligibility:role_family", flags, ())
```

New step, same call site, same inputs (`title`, `jd_text`, `stage`, `config`):

1. **Exclude check (title only, all families):** if any family's `exclude_patterns` matches
   `title`, return `FILTER` with reason `eligibility:role_family_excluded` immediately —
   this runs before any positive-match check, so it cannot be overridden by an incidental JD
   keyword hit.
2. **Title include check (unchanged):** if any family's `patterns` matches `title`, pass this
   step (same single-match-suffices behavior as today — title is a reliable signal).
3. **JD fallback (post-resolution only, title didn't match):** count the number of *distinct*
   patterns (not total occurrences) across all families' `patterns` that match `jd_text`. If
   the count is `>= config.role_families.jd_fallback_min_hits`, pass. Otherwise `FILTER` with
   the existing `eligibility:role_family` reason code (unchanged, so this remains
   distinguishable from the new exclude reason and from unrelated legacy `FILTERED_OUT` rows
   already using that code).

Pre-resolution stage behavior is unchanged in substance: no `jd_text` is available at that
stage, so only the exclude and title-include checks apply — same as today's title-only
matching, just with the added exclude check.

## 5. Retroactive DB apply

Reuses `scripts/eligibility_impact.py` exactly as it exists today — it loads whatever
`config/eligibility.yaml` is current and re-evaluates every row via `evaluate()`, so no code
change is needed there. Workflow, matching the clearance-level fix precedent:

1. Run the impact tool in its existing dry-run/report mode against the updated config.
2. Review the transition list with the user (expected: ids 96, 111, 123 move
   `RESOLVED -> FILTERED_OUT` with reason `eligibility:role_family_excluded`; ids 44 and 53
   likely also move if still `RESOLVED`/active).
3. Back up `data/jobs.db` to `data/backups/jobs-pre-role-family-v2-<timestamp>.db`.
4. Apply.
5. Verify DB integrity and status-count deltas before/after, same as prior fixes.
6. Record the apply in `docs/DECISIONS.md`.

## 6. Calibration round r2 impact

If step 4 above removes any of the 12 jobs in `data/calibration/2026-07-17-r2.batch.json`
(expected: 96, 111, 123), the round is no longer a valid clean calibration round. It is
discarded (its labels are not lost — they remain in `2026-07-17-r2.interest.md` and
`2026-07-17-r2.fit.md` as a record, but the round does not count toward the Phase 2 "at least
two complete v2 rounds" exit criterion) and redrawn with `--exclude-round` against both prior
rounds plus the discarded r2, following the same recovery already used for the contaminated
`2026-07-17-r1`.

## 7. Testing

Offline only, per repo rules (tests never touch the network). New/changed tests in
`tests/test_eligibility.py`:

- a job whose title matches an `exclude_patterns` entry is filtered with
  `eligibility:role_family_excluded`, even when the JD text is saturated with positive
  include-pattern words;
- a job whose title matches a positive include pattern still passes outright (regression
  guard on existing behavior);
- a JD-only job (title doesn't match any pattern) with exactly one incidental include-pattern
  hit in the JD is filtered with `eligibility:role_family` (the bug this design fixes);
- a JD-only job with `jd_fallback_min_hits` or more distinct include-pattern hits in the JD
  passes;
- pre-resolution stage: exclude check applies to title even though no `jd_text` is available.

No fixture recordings needed — this is pure regex/config logic exercised with synthetic
title/JD strings, consistent with the existing `tests/test_eligibility.py` style.
