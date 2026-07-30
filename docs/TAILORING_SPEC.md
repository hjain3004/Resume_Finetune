# TAILORING_SPEC.md — Phase 3: Resume Tailoring

Scope: how shortlisted jobs become tailored resumes. Do not implement until the user has
completed scoring dry-runs (see IMPLEMENTATION_PLAN, Phase 3 gate). This spec is the
distillation of design research; treat its rules as requirements.

## 1. Source of truth: `config/master_profile.yaml`

### Nomenclature
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

### Schema
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

do_not_claim:                    # required by TAILORING_METHODOLOGY.md §2; user-supplied
  - "Kubernetes"                 # example shape only
```

### 4.1 `do_not_claim` and the `priority` / `strength` mapping

Two requirements from `docs/TAILORING_METHODOLOGY.md` §2 were dropped by v0.2.0 and are
restored here. Neither is a new decision — that document is authoritative under `CLAUDE.md`
prime directive 1.

**`do_not_claim`** (§2, line 89) is a required top-level list of technologies the user has
touched but cannot defend in an interview. Quality gate L6 (§4, line 185) checks for "zero
occurrences of listed terms outside the gap report." The authored v0.2.0 file contains zero
occurrences of the key, and the M8 item 1 loader's guard against it was lost in the rewrite.
It returns as a top-level list, defaulting to `[]` when absent.

**`strength`** (§2, line 87) is `flagship | solid | filler` and drives selection ordering:
"selection prefers flagship; a tailored resume may not demote a flagship bullet below a
filler one to chase a keyword." v0.2.0 replaced it with `priority` (integers 1–4 in the
authored file) without ever defining the correspondence, leaving gate L6's flagship-ordering
rule undefined. The mapping is fixed here:

| `priority` | methodology `strength` | authored count |
|---|---|---|
| 1 | flagship | 14 |
| 2 | solid | 13 |
| 3–4 | filler | 11 |

`priority` is the only ordering field; `strength` is never stored, only referenced when
reading the methodology. Lower `priority` means higher precedence. The ordering rule becomes
mechanical: within a `base_variants.*.bullet_order`, no bullet may precede one of strictly
lower `priority` from the same project or experience entry.

`identity`, `education`, and `skills` keep flexible key sets (per `TAILORING_SPEC.md`'s
"mirror the sections used in the current resumes") but their runtime shape is validated:
identity values are strings, education entries are string-key/string-value mappings, skills
values are nonempty string lists.

Date formats: `start` and `end` are `"YYYY-MM"`; `last_updated` is `"YYYY-MM-DD"`;
`display_date` is a free human string and is the only date the renderer prints.

### Metric Ledger
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


## 2. ATS rules (encode in the tailoring prompt/skill verbatim)

1. Keyword matching in real ATSs is largely **literal**. Mirror the JD's exact terminology
   ("RESTful services" vs "REST APIs", "Kubernetes" vs "K8s"). Do not rely on semantic
   matching. Where an abbreviation is common, use the dual form once: "Kubernetes (K8s)".
2. **Dual placement**: every must-have JD keyword appears (a) in the Skills section for the
   exact-match filter, and (b) in ≥1 experience/project bullet as evidence, ideally with a
   number.
3. The 3–5 highest-priority JD terms appear 2–3× across the document total. Any term
   appearing >4× is stuffing — reduce.
4. Single-column layout, standard section headers (Education / Experience / Projects /
   Technical Skills), no tables, no text boxes, no graphics, contact info in body not header.
   (The user's current template already complies — do not restructure it.)
5. Most-recent-role bullets carry the most keyword weight; prioritize alignment edits there
   and in the projects chosen.
6. Never hidden text, white text, or keyword lists jammed into unrelated sections — modern
   screeners detect this and flag it.

## 3. Anti-slop rules

1. **Edit budget: ≤15% of the base variant may change.** Legal edits: swap one project for
   another from the master profile; reorder bullets; align terminology in ≤8 places; adjust
   the skills line. A rewrite exceeding budget means the wrong base variant was chosen —
   re-select instead.
2. **Style fingerprint** (derived from the user's writing; the tailor must match it):
   impact-first, mechanism-second bullets — "Reduced X by 40% and improved Y by 25% by
   architecting Z"; dense concrete nouns; specific tech names; a number in most bullets;
   no adjectives doing the work a metric should do.
3. **Banned vocabulary** (non-exhaustive; maintain in `config/banned_words.txt`):
   spearheaded, passionate, results-driven, dynamic, synergy/synergies, utilize(d),
   leveraging (as filler), cutting-edge, seamless(ly), robust (as filler), delve,
   "proven track record", "fast-paced environment". Also banned: em-dash chains,
   three-adjective pileups, bullets that state responsibility without outcome.
4. **Output is a diff, not a document.** The tailor produces: (a) chosen base variant + why,
   (b) a change list — each entry: location, before, after, and the JD phrase motivating it,
   (c) the patched resume source. The user reviews the change list, not the whole resume.
5. Resumes live as source (LaTeX or the user's chosen format) in git, one branch or directory
   per application: `applications/{company}-{role-slug}/`. Compile to PDF after approval.

## 4. Critic pass

A second, fresh Claude invocation (no access to the tailor's reasoning) receives only:
the JD, the patched resume, the banned list, and this rubric. It outputs PASS or a numbered
issue list:

- R1: any bullet not traceable to a master-profile id (fabrication check)
- R2: banned vocabulary or style-fingerprint violations
- R3: keyword stuffing (>4 occurrences) or missing dual placement for a must-have term
- R4: edit budget exceeded
- R5: parse risks introduced (layout/table/header changes)
- R6: "generic AI resume" smell — would a recruiter reading 200 resumes flag this bullet as
  template output? Quote the offending line.

The tailor fixes issues; max 2 critic rounds, then escalate remaining issues to the user in
the review packet.

## 5. Taste feedback loop

`config/taste.md` — an append-only file of the user's review feedback, one dated line per
lesson ("2026-07-10: never open a bullet with 'Worked on'"). Both tailor and critic prompts
include this file. During dry runs, every piece of user feedback MUST be written here before
the next tailoring run; this file is the system's memory of the user's standards.

## 6. Gap → project recommendations

When scoring flags a high-fit job (≥8) with missing must-have keywords that no master-profile
entry covers, the scoring output includes a `gap` note. Weekly, gaps are aggregated into
`data/digests/gaps.md` with at most 3 scoped project suggestions (1–2 weekend effort each,
phrased as: what to build, which JD keywords it would legitimately earn, which existing
variant it slots into). The user decides; nothing is auto-added to the profile.
