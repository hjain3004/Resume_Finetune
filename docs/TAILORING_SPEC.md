# TAILORING_SPEC.md — Phase 3: Resume Tailoring

Scope: how shortlisted jobs become tailored resumes. Do not implement until the user has
completed scoring dry-runs (see IMPLEMENTATION_PLAN, Phase 3 gate). This spec is the
distillation of design research; treat its rules as requirements.

## 1. Source of truth: `profile/master_profile.yaml`

The user's 5–6 resume variants are decomposed ONCE (with the user, interactively) into a
single superset file. Structure:

```yaml
identity: {name, phone, email, linkedin, github, location}
education: [...]
experience:
  - org: Amdocs
    title: Software Developer
    dates: "Jul 2023 – Jun 2025"
    bullets:
      - id: amdocs-purge-archive
        text: "Reduced production data footprint by 40% ... on OpenShift (OCP)."
        tags: [backend, kafka, data-lifecycle, microservices]
        metrics: ["40%", "25%"]
      - id: amdocs-dlq
        ...
projects:
  - id: sepsis-prediction
    name: Early Sepsis Prediction in ICU
    stack: "Python, PyTorch, Scikit-learn"
    dates: "Feb 2026 – Apr 2026"
    bullets: [...]
    tags: [ml, healthcare, time-series]
skills:
  languages: [...]
  frameworks: [...]
  # mirror the sections used in the current resumes
variants:                     # named base resumes = ordered selections of bullet/project ids
  systems: {projects: [mq-simulation, clinical-trial], bullet_order: [...]}
  aiml:    {projects: [sepsis-prediction, yelp-fraud], bullet_order: [...]}
  ...
```

**Invariant: every bullet in any generated resume must carry the `id` of a master-profile
entry** (tracked in the working data, stripped at render). New wording is allowed only as a
*rewrite* of an existing entry's facts; new facts require the user to add an entry first.
This is the structural guarantee against fabrication.

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
