# M8 item 2 — Master Profile Schema Reconciliation (design)

Status: approved, not implemented
Date: 2026-07-30
Phase: 3 (M8 Tailoring), item 2
Supersedes the schema defined in: `docs/TAILORING_SPEC.md` §1, `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md`
Depends on: `docs/TAILORING_METHODOLOGY.md` §2 (evidence / anti-fabrication protocol)

## 1. Context

M8 item 1 (commit `ed8645f`) shipped `src/profile.py`, a pure loader validating the schema
written in `TAILORING_SPEC.md` §1. On 2026-07-30 the user authored the real profile at
`config/master_profile.yaml` (1,933 lines, `schema_version: 0.2.0`) using a substantially
richer and different schema. The two do not agree. Running the committed loader against the
real file fails immediately:

```
ProfileValidationError: master_profile.yaml.identity: missing required key
```

Divergences:

| Concern | `TAILORING_SPEC.md` §1 / `src/profile.py` | authored `config/master_profile.yaml` v0.2.0 |
|---|---|---|
| Path | `profile/master_profile.yaml` | `config/master_profile.yaml` |
| Top-level keys | `identity, education, experience, projects, skills, variants` | `schema_version, last_updated, ats, projects, experience` |
| Bullet text | `text` (single string) | `variants: {long, medium, short}` |
| Provenance | `strength: flagship\|solid\|filler` | `claim_type` (6-value enum) |
| `evidence` | single string | list of artifact paths / commands |
| Additional fields | — | `defense`, `interview_risk`, `priority`, `theme`, `keywords_hit`, `ownership_boundary`, `known_gaps`, `metric_ledger`, `scope_line`, `ats` policy block |
| Meaning of `variants` | named base resumes | bullet length tiers |

Per `CLAUDE.md` prime directive 1, this real-world/docs disagreement was escalated to the
user rather than resolved unilaterally.

## 2. Decisions (user-approved, 2026-07-30)

1. **v0.2.0 is canonical.** `src/profile.py` and `TAILORING_SPEC.md` §1 are rewritten to
   match the authored file, not the reverse. Rationale: `claim_type` + mandatory `defense` +
   evidence-as-artifact-paths is a strictly stronger anti-fabrication guard than
   `strength` + a prose evidence string, and `interview_risk` / `ownership_boundary` /
   `known_gaps` capture material the spec schema has nowhere to store.
2. **Canonical path is `config/master_profile.yaml`**, consistent with every other YAML
   config in the repo. `profile/` remains a directory of rendered resume PDF artifacts.
3. **Scope of M8 item 2 is loader plus authoring**, in one milestone: rewrite the loader and
   spec, *and* author the missing `identity`, `education`, `skills`, `base_variants`
   sections plus the two absent backend projects.
4. **Author `campus_marketplace` and `clinical_trial_platform` to full v0.2.0 depth** —
   bullets with `claim_type`, `evidence`, `defense`, `interview_risk`, `known_gaps`. The
   2022–23 multi-drone project is dropped as superseded.
5. **Front-load rigor.** The user's stated working principle: invest in the schema and
   nomenclature now so the token-intensive later phases (tailoring, critic, render) are
   cheap and unambiguous. Sections 4–7 below apply this directly.

## 3. Nomenclature

One name per concept. No aliases anywhere in code, docs, or prompts.

| Term | Means | Never called |
|---|---|---|
| `base_variants` | named base resumes (`backend`, `ml`) | variants, tracks, profiles |
| `phrasings` | length tiers of one bullet (`long` / `medium` / `short`) | variants, versions |
| `bullet_id` | the fabrication anchor, globally unique | id, bid |
| `claim_type` | provenance of a claim | strength, confidence |
| `evidence` | artifact paths or reproducible commands | source, proof |
| `defense` | what the candidate says when the claim is challenged | rebuttal, note |
| `provenance` | where a number in `metric_ledger` came from | status |
| `renderable` | whether a number may be printed | — |

Two renames follow from this and are part of the migration:

- bullet-level `variants:` → `phrasings:` (38 occurrences, all at bullet level, verified by
  grep — no other usage). Resolves the collision with the base-resume concept permanently.
- `base_variants` is keyed `backend` / `ml`, matching the `base_variant` vocabulary already
  emitted by the Phase 2 scoring pipeline (`config/profile_summary.md` §"Project variants").
  `TAILORING_SPEC.md`'s `systems` / `aiml` naming is stale and is removed.

## 4. Schema v0.3.0

```yaml
schema_version: "0.3.0"
last_updated: "2026-07-30"

ats: {...}                       # unchanged from v0.2.0

identity:
  name: "Himanshu Jain"
  phone: "..."
  email: "..."
  linkedin: "..."
  github: "..."
  location: "San Jose, CA"

education:
  - institution: "San Jose State University"
    degree: "Master of Science in Software Engineering"
    location: "San Jose, CA"
    start: "2025-08"
    end: "2027-05"
    display_date: "Aug. 2025 - May 2027"

skills:                          # free-form categories, nonempty string lists
  languages: [...]
  frameworks: [...]
  # ...

projects:   [...]                # v0.2.0 shape + campus_marketplace, clinical_trial_platform
experience: [...]                # v0.2.0 shape, unchanged

base_variants:
  backend:
    projects: [campus_marketplace, clinical_trial_platform, peerchat_peer_discovery]
    bullet_order: [...]          # ordered bullet_ids
  ml:
    projects: [sepsis_early_warning, fake_review_detection]
    bullet_order: [...]
```

`identity`, `education`, and `skills` keep flexible key sets (per `TAILORING_SPEC.md`'s
"mirror the sections used in the current resumes") but their runtime shape is validated:
identity values are strings, education entries are string-key/string-value mappings, skills
values are nonempty string lists.

Date formats: `start` and `end` are `"YYYY-MM"`; `last_updated` is `"YYYY-MM-DD"`;
`display_date` is a free human string and is the only date the renderer prints.

## 5. Loader rules — `src/profile.py`, rewritten

Conventions retained from M8 item 1: a single `ProfileValidationError`, raised fail-fast on
the first violation with a path-labeled message, mirroring
`src/eligibility.py::load_eligibility_config`. Pure — PyYAML only, no SQLite, no network, no
logging, no I/O beyond reading the one YAML file. YAML sequences become tuples in the
returned dataclasses.

Each rule traces to a contract already written in the authored file's own header (C1–C5) or
to `TAILORING_SPEC.md` §1.

| # | Rule | Enforces |
|---|---|---|
| 1 | Reject duplicate mapping keys anywhere in the document | data integrity — see §8 defect 1 |
| 2 | `bullet_id` globally unique across `projects` + `experience` | C1 |
| 3 | `phrasings` must contain `short`; `long` and `medium` optional | matches authored reality: 22 bullets long+medium+short, 12 medium+short, 4 short-only |
| 4 | `claim_type ∈ {verified, scoped, estimated, observed, ownership_unresolved, needs_input}` | authored header |
| 5 | `defense` nonempty whenever `claim_type != verified` | C3 |
| 6 | `evidence` is a nonempty list of nonempty strings | C5 |
| 7 | Every string in the document is ASCII-only, with exactly one exemption: the `ats.forbidden_chars` list and the keys of `ats.substitutions`. Non-ASCII elsewhere is an error, not a warning | C4 |
| 8 | Every `base_variants.*.projects` and `.bullet_order` entry resolves to a real id; no duplicates within a variant | `TAILORING_SPEC.md` §1 |
| 9 | No `base_variants` entry references a **blocked** bullet — `claim_type ∈ {ownership_unresolved, needs_input}` | authored header: "Must not render" |
| 10 | `metric_ledger` entries are mappings carrying required `value` (may be `null`), `provenance`, `renderable`; optional `render_as` and `note` are permitted, any other key is an error | §6 |
| 11 | `provenance ∈ {unsourced, contradicted, none}` may not pair with `renderable: true` | §6 |
| 12 | `priority` is a positive integer | — |
| 13 | Required textual fields nonempty after trimming; containers are containers | M8 item 1 rules 3–4, retained |

Rule 9 is the load-bearing one: it converts "blocked claims must never render" from a
render-time hope into a load-time failure. The four `ownership_unresolved` bullets currently
in the file cannot be selected into `backend` or `ml`.

## 6. `metric_ledger` normalization

v0.2.0 uses ten ad-hoc `status` values that conflate two orthogonal facts — where a number
came from, and whether it may be printed: `counted`, `doc_backed`, `configured`,
`estimated`, `unsourced_do_not_use`, `contradicted_do_not_use`, `unverified_do_not_use`,
`confirmed_none`, `none_exist_by_design`.

Replaced by two fields that cannot contradict each other:

```yaml
automated_tests:   { value: 233, provenance: counted, renderable: true, render_as: "230+" }
caller_rate_limit: { value: "600/min", provenance: configured, renderable: false,
                     note: "CONFIGURED LIMIT, not observed throughput" }
```

- `provenance ∈ {counted, doc_backed, configured, estimated, unsourced, contradicted, none}`
- `renderable: bool`

A prohibited number becomes structurally unprintable (rule 11) rather than depending on a
reader noticing a `_do_not_use` suffix.

Two entries are currently bare strings among `{value, status}` mappings —
`sepsis_early_warning.metric_ledger.split_scope` and
`fake_review_detection.metric_ledger.ablation_scope`. They are scope descriptors, not
metrics; they move to a sibling `metric_scope:` mapping.

`known_gaps.severity` currently mixes severities (`high`, `medium`, `low`) with a state
(`resolved`, 5 uses). Split into `severity ∈ {high, medium, low}` and
`status ∈ {open, resolved}`.

`theme` is deleted: 26 distinct values across 38 bullets, 20 used exactly once. It carries no
selection signal, `keywords_hit` does the real matching work, and a free-form field is
exactly the ambiguity this design removes.

## 7. Projection API

The file is ~1,900 lines today and roughly doubles with §2 decisions 3–4. Passing all of it
into every tailoring call is the expensive mistake this design exists to prevent. The loader
therefore exposes three views over one source of truth:

| View | Contains | Consumer |
|---|---|---|
| `for_tailoring(base_variant)` | `bullet_id`, selected phrasing, `keywords_hit`, `claim_type` | tailor prompt — the hot path |
| `for_critic(base_variant)` | the above plus `evidence`, `defense`, `ownership_boundary` | R1 fabrication check, `TAILORING_SPEC.md` §4 |
| `MasterProfile` (full) | everything, including `interview_risk`, `known_gaps`, `metric_ledger` | offline human use |

`interview_risk` and `known_gaps` are written for a human preparing for an interview and
never enter a tailoring prompt. Blocked bullets (rule 9) are filtered at the projection
boundary, so the tailor never sees a claim it is not permitted to make.

## 8. Defects found in the authored file

1. **Silent data loss.** `bank_integration_internship` declares `date_note` twice
   (`config/master_profile.yaml:1150` and `:1157`). PyYAML keeps the last, so the
   `CONFIRMED 2026-07-30: 06/2026 - 08/2026` note is discarded and the stale
   "Not recoverable from the repo … Use personal records" note is what loads. Loader rule 1
   makes this an error; the migration keeps the CONFIRMED note and deletes the stale one.
2. **Placeholder URL.** `config/master_profile.yaml:98` is
   `https://github.com/CHANGEME/peerchat`. Must be replaced before any render. Not a loader
   rule — a `CHANGEME` sentinel check belongs in the render gate, not the schema.
3. **Incomplete project inventory.** `config/profile_summary.md` defines `backend` over
   *Campus Marketplace* and *Synthetic Clinical Trial Data Platform*; neither exists in the
   master profile. `backend` is the default scoring variant, so it currently has zero
   projects. Addressed by §2 decision 4.

Audit facts that came back clean and should stay that way: all 38 bullets satisfy C3 (zero
non-`verified` bullets with an empty `defense`), and all 38 carry a nonempty `evidence` list.

C4 holds under rule 7 as scoped: the raw file contains zero literal non-ASCII bytes, and the
only non-ASCII values that exist after YAML parsing are the eight characters inside
`ats.forbidden_chars` and the five `ats.substitutions` keys — written as `\uXXXX` escapes and
present precisely to declare what is banned. This is why rule 7 carries an exemption rather
than a blanket prohibition; without it the loader would reject the file for containing its
own policy.

## 9. Migration

Mechanical, in this order:

1. Rename bullet-level `variants:` → `phrasings:` (38 occurrences).
2. Delete `theme` from all bullets.
3. Normalize `metric_ledger` to `provenance` + `renderable`; extract `metric_scope`.
4. Split `known_gaps.severity` into `severity` + `status`.
5. Delete the stale duplicate `date_note`.
6. Bump `schema_version` to `0.3.0`.
7. Author `identity`, `education`, `skills` (sourced from `profile/Himanshu_Resume_New.pdf`
   and `config/profile_summary.md`, confirmed with the user — not invented).
8. Author `campus_marketplace` and `clinical_trial_platform` projects at full depth.
9. Author `base_variants` for `backend` and `ml`.

## 10. Documentation updates

- `docs/TAILORING_SPEC.md` §1 — replaced wholesale with §3, §4, §6 of this document.
- `docs/ROADMAP.md` — Phase 3 status: M8 item 2 complete; canonical path corrected to
  `config/`.
- `docs/DECISIONS.md` — record the approved deviation: the authored v0.2.0 schema supersedes
  the `TAILORING_SPEC.md` §1 schema, and the canonical path moves from `profile/` to
  `config/`.
- `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md` — marked superseded by this
  document.

## 11. Testing

`tests/test_profile.py` rewritten. Inline YAML fixture strings, per the existing convention
(small enough that fixture and assertion read together). Coverage:

- Happy path across all top-level sections.
- One failing test per numbered rule in §5 — duplicate keys, missing `short` phrasing,
  invalid `claim_type`, missing `defense` on a non-`verified` bullet, empty `evidence`,
  non-ASCII, unresolved `base_variants` reference, blocked-bullet reference, malformed
  `metric_ledger`, `renderable: true` on a prohibited `provenance`.
- Projection tests: `for_tailoring` omits `evidence` / `defense` / `interview_risk` /
  `known_gaps` and excludes blocked bullets; `for_critic` includes `evidence` and `defense`.
- Malformed YAML and file-not-found behavior.
- An integration test that loads the real `config/master_profile.yaml` green, so file and
  loader cannot drift again.

`scripts/validate_profile.py` — a CLI wrapper over `load_profile` for checking the file
while authoring. Now justified, since something finally consumes the loader.

## 12. Out of scope

- Tailor prompt, critic prompt, renderer, and the S1→S3/G1→G3 workflow steps
  (`TAILORING_METHODOLOGY.md`) — later M8 items.
- Any change to `src/db.py`, `run_ingest.py`, scoring, or eligibility. This remains a pure
  parsing module plus a config file.
- `config/banned_words.txt` and `config/taste.md` (`TAILORING_SPEC.md` §3, §5).
- Replacing the `CHANGEME` PeerChat URL — user action, tracked as defect 2.
- M10 render bake-off, which `ROADMAP.md` requires before M8's render step.
