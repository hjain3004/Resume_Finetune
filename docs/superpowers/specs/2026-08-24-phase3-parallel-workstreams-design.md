# Phase 3 Parallel Workstreams — Umbrella Design

**Date:** 2026-08-24

**Status:** Planning authority document. Approved for planning only. No production
code, test, live run, model call, render, database change, Company Bank import, or
dependency addition is authorized by this document.

**Phase:** 3 (M8 Tailoring)

**Scope:** Establish the verified current state, the dependency graph from that state
to the three-resume human pilot, the 30-resume dry run, and an eventual Microsoft
SkillOpt evaluation; classify every candidate task by whether it is genuinely
parallelisable; and index the per-workstream design and plan documents.

**Companion documents (created with this one):**

| Workstream | Design | Plan |
|---|---|---|
| M8P-4 G2 anchored critic | `docs/superpowers/specs/2026-08-24-m8p-4-g2-anchored-critic-design.md` | `docs/superpowers/plans/2026-08-24-m8p-4-g2-anchored-critic.md` |
| M8P-5 render + L7 | `docs/superpowers/specs/2026-08-24-m8p-5-render-l7-design.md` | `docs/superpowers/plans/2026-08-24-m8p-5-render-l7.md` |
| M8P-6 G3 packet + feedback | `docs/superpowers/specs/2026-08-24-m8p-6-g3-packet-feedback-design.md` | `docs/superpowers/plans/2026-08-24-m8p-6-g3-packet-feedback.md` |
| M8P-7/M8P-8 pilot operator and scale-up | `docs/superpowers/specs/2026-08-24-m8p-7-pilot-operator-design.md` | `docs/superpowers/plans/2026-08-24-m8p-7-pilot-operator.md` |
| M8X-1 SkillOpt evaluation | `docs/superpowers/specs/2026-08-24-m8x-1-skillopt-evaluation-design.md` | `docs/superpowers/plans/2026-08-24-m8x-1-skillopt-evaluation.md` |

---

## 1. Authoritative current state (verified against the repository, not from chat)

Verified on 2026-08-24 at `HEAD = 20f2d2b` ("docs(m8): close offline S3 and static G1
milestone").

### 1.1 What exists

| Stage / gate | State | Evidence |
|---|---|---|
| S1 requirement extraction | Complete offline | `src/tailor/s1.py`, `src/tailor/s1_pipeline.py`, `scripts/tailor_s1.py`, `docs/prompts/tailoring_s1.md`, commit `f6cb99e` |
| S0 positioning (JD-only) | Complete offline | `src/tailor/s0.py`, `src/tailor/s0_pipeline.py`, `docs/prompts/tailoring_s0.md`, commits `865675a`, `8a26298` |
| S2 structural selection | Complete offline, repaired | `src/tailor/s2.py`, `src/tailor/s2_pipeline.py`, commits `ea0d893`, `ad19314`, `9c34823`, `cd7c927`, `bd5f8ab` |
| S3 constrained alignment | Implemented, **under repair as M8P-3R** | `src/tailor/s3.py`, `src/tailor/s3_pipeline.py`, `scripts/tailor_s3.py`, commits `07dce7f`…`9a1fd9c` |
| G1 static gate | Implemented, **under repair as M8P-3R** | `src/tailor/g1.py`, commit `6fbf2ef` |
| G2 anchored critic | **Does not exist** | no `src/tailor/g2*.py`, no `docs/prompts/tailoring_g2.md` |
| G3 human packet / feedback | **Does not exist** | no `src/tailor/g3*.py`, no feedback schema, `config/taste.md` is a 67-byte header stub |
| Final render of a tailored draft | **Does not exist** | `src/render/latex.py` renders a `RenderDoc` built from the *base variant*, never from a `TailoredDraft` |
| L7 parseability gate | Complete for base-variant PDFs | `src/render/l7.py` — 11 checks including `check_page_count`, `check_no_overlap`, `check_within_page` |
| Rendered line count (`L4` second half) | **Not implemented** | `G1Report.render_line_check` is the literal string `"pending"` |
| `applications/` archival layout | **Does not exist** | no `applications/` directory in the repository |
| Company Bank Track C canonical import | Incomplete | `docs/IMPLEMENTATION_PLAN.md`, Track C status |
| DB mutation for tailoring | None, by design | `src.db.prepare_tailoring_request()` is read-only; no `TAILORED` status exists |

### 1.2 Verified numbers

- Full suite after M8P-3: `1330 passed, 1 deselected` (the deselected test is the
  `oracle` marker in `pyproject.toml`, requiring Node).
- Production database SHA-256:
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1` (re-verified
  2026-08-24 against `data/jobs.db`).
- Runtime dependencies: `requests`, `trafilatura`, `PyYAML`, `crawl4ai`,
  `pdfminer.six>=20231228`. Dev: `pytest`. `pdfminer.six` is already a runtime
  dependency, so L7 work adds none.
- LaTeX template geometry is already `left/right/top/bottom = 0.20in`
  (`profile/template.tex:22-24`). The user's "margins as small as safely practical"
  preference is already satisfied; **no margin redesign is planned or needed.**
- `config/master_profile.yaml` `ats.max_pages = 1`, `ats.max_file_size_mb = 2.5`,
  `ats.layout.columns = 1`, `do_not_claim = ["Kubernetes"]`.
- Both base variants (`backend`, `ml`) carry exactly 13 ordered bullets.

### 1.3 Verified corpus reality — this changes the 30-resume plan

Read-only query against `data/jobs.db` on 2026-08-24:

```
status counts:  FILTERED_OUT 669 | RESOLVED 273 | DISCOVERED 260 |
                RESOLVE_FAILED 76 | SCORED 37 | SHORTLISTED 36 | CLOSED 35
```

Of the 36 `SHORTLISTED` rows, **16 carry `jd_quality='ats'`** — the only rows
`prepare_tailoring_request()` accepts. Job 279 (Quantcast) is prohibited by the
Phase 2 closure, leaving 15. Those 15 rows collapse to **eight distinct job
descriptions**:

| Distinct JD | Row ids | `base_variant` | `jd_text` length |
|---|---|---|---|
| Cisco — SWE Data/AI/Intelligent Systems | 119, 164 | ml | ~13.4k |
| Palantir — New Grad SWE | 205, 875, 876, 877, 878 | backend | ~4.27k |
| Citadel — SWE University Graduate | 211 | backend | 19,215 |
| Citadel Securities — Graduate SWE | 213, 883 | backend | 2,352 |
| Notion — SWE Early Career (AI / general) | 225, 248 | backend | ~7.4k |
| Atos — Analyst Programmer | 233 | backend | 2,822 |
| NewsBreak — Venture New Grad AI Growth | 266 | backend | 6,058 |
| ByteDance — Graduate SWE Dev Infra | 283 | backend | 6,210 |

Two consequences that no prior document records:

1. **A 30-resume dry run cannot be sourced from the current shortlist.** Eight
   distinct eligible JDs exist. Reaching thirty requires promoting new rows, which
   requires running the existing Phase 2 scoring chain (`scripts/export_batch.py` →
   `scripts/score_batch.py` → `scripts/import_scores.py`) over some of the 273
   `RESOLVED` rows. `import_scores.py` **writes to SQLite**. That is a database
   mutation and therefore its own approval decision (see §9, D1).
2. **`ml` diversity is nearly absent.** The only non-prohibited `ml` rows are the two
   Cisco duplicates. Any pilot that wants to exercise both base variants must use
   Cisco for `ml`.

Additionally, the highest-scoring `SCORED`-but-not-shortlisted ATS row is 5.5
(job 195), below the locked `shortlist_threshold = 6.0`. There is no reservoir of
already-scored rows to promote without re-scoring.

### 1.4 M8P-3R — merged during this planning session

M8P-3R was being implemented in a separate active session while this document was
written, and **it merged before this document was committed.** Verified state:

- Commits `e587c94`, `a0d90f1`, `a1864fa`, `c01f9ab`, `e67aca1`, `560ad8d`.
- Full suite re-verified after the merge: **1381 passed, 1 deselected** (was 1330).
- Production DB SHA-256 still
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.

Verified public API now available to every downstream workstream:

```python
# src/tailor/s3.py
tailored_draft_to_dict(draft) -> dict
parse_tailored_draft(raw, path="$.draft") -> TailoredDraft
parse_change_log(raw, path="$.change_log") -> tuple[ChangeEntry, ...]
parse_edit_budget(raw, path="$.edit_budget") -> EditBudget

# src/tailor/s3_pipeline.py
s3_bundle_to_dict(bundle) -> dict
parse_s3_bundle(raw, request: S3Request, banned_terms: tuple[str, ...]) -> S3Bundle
```

`parse_s3_bundle` takes **three** arguments, not one. It re-derives the response
validation, hydrated draft, change log, unified diff, edit budget, and static G1 report
from the authoritative request and requires every persisted derived field to match
exactly. That is stronger than this document originally assumed, and it has one
concrete consequence: **any consumer of a persisted bundle must first rebuild the
authoritative `S3Request` from the upstream chain.** There is no "just load the
bundle" path, by design. Interface assumption A3 below records the real signature.

The consequence for scheduling is that the classification in §4 stands, but its
*timing* is now more favourable: M8P-4 and the second half of M8P-5 are unblocked
immediately rather than after a wait.

The repair scope M8P-3R delivered:

- recursive JSON-safe S3 bundle serialization;
- strict authoritative bundle parsing and revalidation;
- complete G0/L1 canonical ownership and identity binding;
- detection of undeclared bullet and skill mutations;
- `text` / `plain_text` / emphasis consistency;
- complete static L4 integrity;
- narrow exception handling;
- missing CLI and adversarial integration coverage.

**No document created today may modify `src/tailor/s3.py`, `src/tailor/g1.py`,
`src/tailor/s3_pipeline.py`, `scripts/tailor_s3.py`, or any existing M8P-3 test.**
Where a downstream workstream needs a change in those files, it is written as a
post-merge integration task, explicitly labelled as such.

---

## 2. Milestone identifiers

The M8P-3 design already names the next milestone: "M8P-4 (G2 anchored critic and
bounded revision loop)". That naming is authoritative and is kept. The remaining
identifiers extend the same family; the SkillOpt track gets a distinct family letter
because it is deliberately off the critical path.

| Id | Name | Family rationale |
|---|---|---|
| M8P-3R | S3/G1 repair | in flight, other session |
| M8P-4 | G2 anchored critic and bounded revision loop | named by the M8P-3 design |
| M8P-5 | Deterministic tailored render, rendered line check, L7 execution, atomic publication | next pipeline stage |
| M8P-6 | G3 human review packet and feedback contract | next pipeline stage |
| M8P-7 | Three-resume pilot operator (live join point) | the pilot itself |
| M8P-8 | 30-resume dry run (conditional) | scale-up, gated on M8P-7 |
| M8X-1 | Microsoft SkillOpt feasibility and offline evaluation | `X` = experimental / off critical path, mirrors the `M9F` family-letter precedent |

M8P-7 and M8P-8 share one design and one plan document because M8P-8 is the same
operator run at scale behind an explicit acceptance gate; splitting them would
duplicate the entire artifact layout and failure taxonomy for no reviewer benefit.

---

## 3. Dependency DAG

```
                       [M8P-3R repair]  (in flight, other session)
                              │
              ┌───────────────┼────────────────────────────────┐
              │               │                                │
              │               ▼                                │
              │        [M8P-4  G2 critic +                     │
              │         bounded revision loop]                 │
              │               │                                │
              ▼               │                                ▼
   [M8P-5a  draft→RenderDoc,  │                    [M8P-6a  feedback record
    rendered line count,      │                     schema + storage +
    L7 extension]             │                     idempotency]
    (PARALLEL-SAFE NOW)       │                     (PARALLEL-SAFE NOW)
              │               │                                │
              ▼               │                                │
   [M8P-5b  bundle loader,    │                                │
    atomic publication CLI]   │                                │
    (needs M8P-3R merged)     │                                │
              │               │                                │
              └───────┬───────┴────────────────┬───────────────┘
                      ▼                        ▼
              [M8P-6b  G3 packet builder — needs M8P-4 verdict type
                        and M8P-5 render result type]
                                   │
                                   ▼
                    [M8P-7  three-resume pilot operator]
                       (LIVE: model calls, user review)
                                   │
                        ┌──────────┴──────────┐
                        │  user acceptance    │
                        │  criteria met?      │
                        └──────────┬──────────┘
                                   ▼
                 [D1 decision: scoring batch to create eligible corpus]
                                   │
                                   ▼
                       [M8P-8  30-resume dry run]
                                   │
                                   ▼
                       [M8X-1  SkillOpt evaluation]
                     (needs a labelled feedback corpus
                      and a measured deterministic baseline)


Independent, off-path (no edge to any node above):
   [M9F-1 Firecrawl bake-off]  [Company Bank Track C]  [M9D-1 discovery]
   [company-aware tailoring — depends on Track C, not on the pilot]
```

### 3.1 Critical path

```
M8P-3R → M8P-4 → M8P-6b → M8P-7 → (D1) → M8P-8 → M8X-1
```

M8P-5 is **not** on the critical path provided its parallel-safe half (M8P-5a) starts
now, because M8P-4 is the longer of the two branches and M8P-5b is a short
integration task. If M8P-5 is started only after M8P-3R merges, it joins the critical
path and adds roughly one session.

### 3.2 Join points

| Join | What must be true | Owner |
|---|---|---|
| J1 — M8P-3R merged to `main` | **DONE** at `560ad8d`; API verified above; `pytest -q` green at 1381 passed / 1 deselected | M8P-3R session |
| J2 — M8P-5 rebased onto J1 | `parse_s3_bundle()` exists; render CLI wired to it; DB checksum unchanged | M8P-5 implementer |
| J3 — M8P-4 merged after J2 | G2 verdict type frozen; revised-bundle producer emits the same `TailoredDraft` type the renderer already consumes | M8P-4 implementer |
| J4 — M8P-6 merged after J3 | Packet builder consumes S1/S0/S2 responses, the accepted bundle, the G2 verdict, and the render result | M8P-6 implementer |
| J5 — Central docs updated | `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md` updated once per merged branch, on `main`, by the integrator only | Integrator (see §7) |

---

## 4. Task classification

The user asked for four categories. A task is only category 1 if it has **no
dependency on the repaired bundle representation, no overlapping production file, and
can be verified with synthetic fixtures**. Being editable by a different person is
not sufficient.

### Category 1 — Safe to implement in parallel with M8P-3R

| Task | Milestone | Why genuinely parallel |
|---|---|---|
| `TailoredDraft` + `MasterProfile` → `RenderDoc` mapper | M8P-5a | Consumes the `TailoredDraft` **dataclass fields**, which M8P-3R does not rename or remove (it adds serialization helpers). Verified with in-test synthetic drafts; touches only the new `src/render/tailored.py`. |
| Rendered bullet line counting from PDF geometry | M8P-5a | Pure function over `ParsedPdf.boxes`; no tailoring type involved at all. Testable against the two committed PDF fixtures in `tests/fixtures/render/`. |
| L7 extension: `check_bullet_line_counts`, modified-bullet-aware runner | M8P-5a | `src/render/l7.py` is untouched by M8P-3R. |
| Deterministic artifact naming and directory layout helpers | M8P-5a | Pure string/path functions, new file. |
| `FeedbackRecord` schema, versioning, append-only storage, idempotency | M8P-6a | Keyed on `(job_id, bundle_fingerprint, schema_version)`; needs no upstream type. New file `src/tailor/feedback.py`. |
| SkillOpt feasibility/compatibility study (documentation only) | M8X-1 Task 1 | Reading published material and writing a decision memo. No code, no install. |

### Category 2 — Safe to plan now, implement only after M8P-3R merges

| Task | Milestone | Blocking reason |
|---|---|---|
| G2 request/response contracts and prompt | M8P-4 | The critic's input is derived from the *repaired* bundle (draft, change log, diff, G1 report). Building against the pre-repair shape would be rework. |
| Bounded revision loop driver | M8P-4 | Must call the repaired `run_s3_invocation` and repaired `run_static_g1`; requires adding a typed revision context to `src/tailor/s3.py` and `src/tailor/s3_pipeline.py`, both M8P-3R-owned. |
| S3 bundle loader + atomic application publication CLI | M8P-5b | Needs `parse_s3_bundle()` from M8P-3R. |
| G3 packet builder | M8P-6b | Needs the M8P-4 verdict type and the M8P-5 render-result type. |

### Category 3 — Strictly sequential

| Task | Milestone | Reason |
|---|---|---|
| Three-resume pilot execution | M8P-7 | Requires live model calls and the user's own judgement. Cannot be simulated. |
| Feedback incorporation into `config/taste.md` and prompts | post-M8P-7 | Requires real user feedback as input. |
| Corpus expansion decision and scoring batch | D1, pre-M8P-8 | Requires a user decision about a DB mutation. |
| 30-resume dry run | M8P-8 | Requires M8P-7 acceptance criteria met, in the user's judgement, not merely three runs completed. |
| SkillOpt offline experiment and baseline comparison | M8X-1 Tasks 3–5 | Requires a measured deterministic baseline and a labelled feedback corpus that only M8P-7/M8P-8 can produce. |

### Category 4 — Independent but non-critical

| Task | Can proceed independently? | Effect on the resume pilot |
|---|---|---|
| M9F-1 Firecrawl vs Crawl4AI bake-off | Yes — ingestion plane only, disabled by default, no shared file with `src/tailor/` or `src/render/` | **Delays** the pilot if it consumes the user's supervision budget: it needs live credit-bounded smoke runs, which is exactly the scarce resource M8P-7 needs. Recommend deferring until after M8P-7. |
| Company Bank Track C canonical import | Yes | **Delays.** And it is provably *not* a prerequisite: `S3Request.context_mode` is the constant `"jd_only"`, S0 is JD-only, and `prepare_tailoring_request()` never consults the bank. The JD-only pilot is complete without it. |
| Company-aware tailoring (S0/S2 domain affinity from the bank) | No — depends on Track C | Delays. Genuinely valuable, but it is an *improvement* to a pipeline that does not yet produce a resume. Sequence it after the first pilot so the improvement can be measured against a baseline. |
| M9D agentic discovery | Yes | Delays. Unrelated plane. |
| Provenance work (multi-source discovery provenance) | Yes | Delays. Unrelated plane. |

**Recommendation:** run nothing from Category 4 until the three-resume pilot is
accepted. The binding constraint on this project is the user's review attention, not
implementer throughput, and every Category 4 item competes for it.

---

## 5. Interface assumptions

These are the contracts the parallel branches are written against. If M8P-3R lands
something different, the affected plan's stated stop condition fires and the branch
rebases before continuing.

**A1 — `TailoredDraft` field shape is stable.** After M8P-3R it still exposes
`job_id`, `company`, `title`, `base_variant`, `project_ids`, `experience_ids`,
`bullets` (each with `bullet_id`, `owner_id`, `owner_kind`, `text`, `plain_text`,
`emphasis`), `skills`, `alignment_fingerprint`. Added fields are tolerated; renamed or
removed fields are a stop condition for M8P-5.

**A2 — `TailoredDraft` is privacy-minimised and therefore insufficient to render.**
It carries no identity, no education, no ATS block, no display titles, no tech lines,
no date ranges. The renderer must re-hydrate those from the local
`config/master_profile.yaml`, binding them by `alignment_fingerprint` so a draft can
never be rendered against a profile it was not derived from. This is an interface
fact, not a preference.

**A3 — `parse_s3_bundle(raw, request: S3Request, banned_terms) -> S3Bundle`**
(verified signature, `src/tailor/s3_pipeline.py:155`). It revalidates and recomputes
rather than trusting persisted JSON, so every consumer must first rebuild the
authoritative `S3Request` from the upstream chain — exactly the revalidation
`scripts/tailor_s3.py prepare` already performs. M8P-4 and M8P-5b both consume it.

**A4 — `run_static_g1(request, response, draft, banned_terms) -> G1Report` keeps its
signature.** M8P-4 re-runs it after every revision.

**A5 — `G1Report.render_line_check` is a string field.** M8P-5 sets it to a real
verdict only in the *render* report it produces; it does not mutate the S3 bundle's
own G1 report, which stays `"pending"` because it is honest about what a pre-render
gate can prove.

**A6 — `invoke_text_model`, `write_trace`, `write_json_atomic` are stable shared
plumbing.** Every new stage reuses them; none forks them.

**A7 — No stage after S3 may introduce content vocabulary.** G2 emits findings and
the *S3 stage* revises under the same bounded edit contract. G2 never emits resume
text.

---

## 6. File-ownership and conflict matrix

Exclusive ownership. A file appears under exactly one owner while that branch is open.

| File / directory | M8P-3R (in flight) | M8P-4 | M8P-5 | M8P-6 | M8P-7/8 | M8X-1 |
|---|---|---|---|---|---|---|
| `src/tailor/s3.py` | **OWNS** | post-merge integration only | — | — | — | — |
| `src/tailor/g1.py` | **OWNS** | read-only import | read-only import | — | — | — |
| `src/tailor/s3_pipeline.py` | **OWNS** | post-merge integration only | read-only import | — | — | — |
| `scripts/tailor_s3.py` | **OWNS** | — | — | — | read-only invocation | — |
| `tests/tailor/test_s3*.py`, `tests/tailor/test_g1.py`, `tests/test_tailor_s3_cli.py`, `tests/test_m8p3_integration.py` | **OWNS** | — | — | — | — | — |
| `src/tailor/alignment_view.py`, `src/tailor/lint.py` | **OWNS** | read-only import | read-only import | — | — | — |
| `src/tailor/g2.py`, `src/tailor/g2_pipeline.py` | — | **OWNS** | — | read-only import | — | — |
| `docs/prompts/tailoring_g2.md` | — | **OWNS** | — | — | — | read-only |
| `scripts/tailor_g2.py` | — | **OWNS** | — | — | read-only invocation | — |
| `src/render/tailored.py`, `src/render/lines.py` | — | — | **OWNS** | — | — | — |
| `src/render/l7.py` | — | — | **OWNS** | — | — | — |
| `src/render/mapping.py`, `src/render/latex.py`, `src/render/model.py`, `src/render/parse.py` | — | — | read-only import | — | — | — |
| `src/tailor/publish.py`, `scripts/tailor_render.py` | — | — | **OWNS** | read-only import | read-only invocation | — |
| `src/tailor/feedback.py`, `scripts/tailor_feedback.py` | — | — | — | **OWNS** | read-only invocation | read-only |
| `src/tailor/g3.py`, `scripts/tailor_g3.py` | — | — | — | **OWNS** | read-only invocation | — |
| `scripts/tailor_pilot.py`, `src/tailor/pilot.py` | — | — | — | — | **OWNS** | — |
| `config/banned_words.txt`, `config/taste.md` | — | — | — | — | **OWNS** (post-pilot only) | — |
| `docs/superpowers/specs/2026-08-24-m8x-1-*` and `docs/superpowers/reports/skillopt-*` | — | — | — | — | — | **OWNS** |
| `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DECISIONS.md` | *deferred* | *deferred* | *deferred* | *deferred* | *deferred* | *deferred* |

### 6.1 Shared-fixture rule

Integration fixtures are the second-most-likely conflict source after the central
docs. Rule: **each branch creates its own fixture module under its own filename**
(`tests/fixtures/tailor/m8p5_*.py`, `tests/fixtures/tailor/m8p6_*.json`, …). No branch
edits another branch's fixture. A shared synthetic-draft builder is only extracted
after two branches have merged and the duplication is real, never speculatively.

### 6.2 Central documentation rule

No parallel branch edits `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or
`docs/DECISIONS.md`. Each branch instead leaves a `## Documentation deltas` section at
the end of its plan describing exactly what the integrator must write. The integrator
applies those deltas on `main`, one commit per merged branch, in merge order. This
trades a small amount of integrator work for the complete elimination of the
three-way conflicts that these append-heavy files would otherwise guarantee.

---

## 7. Branch and worktree strategy

Use `git worktree` so each implementer has a physically separate checkout and no
branch switching disturbs another session's in-progress edits.

```bash
git worktree add ../job-pipeline-m8p5 -b m8p-5-render-l7 main
git worktree add ../job-pipeline-m8p6 -b m8p-6-feedback  main
```

`m8p-4-g2` is created from the merged `main`, which as of `560ad8d` already contains
M8P-3R — so all three branches can be created immediately:

```bash
git worktree add ../job-pipeline-m8p4 -b m8p-4-g2 main
```

Rules:

- Every worktree has its own `.venv` or reuses the primary one read-only; no branch
  installs a dependency.
- No branch runs the production pipeline, mutates `data/jobs.db`, or invokes a model.
  Each branch's verification ends with `shasum -a 256 data/jobs.db` matching the
  baseline.
- Rebase, do not merge `main` into a feature branch, so the merge order below stays a
  linear, reviewable history.
- A worktree whose branch is abandoned is removed with `git worktree remove`, never
  left to rot.

### 7.1 Merge order

```
1. m8p-3r          (other session)      → main
2. m8p-5-render-l7 (rebase onto main, finish M8P-5b) → main
3. m8p-4-g2        (branch after 1, implement, rebase onto main) → main
4. m8p-6-feedback  (rebase onto main, finish M8P-6b) → main
5. M8P-7 pilot     (on main, live, with the user)
6. M8P-8 scale-up  (on main, after the D1 decision and the M8P-7 gate)
```

M8P-5 merges before M8P-4 because it is finishable earlier and because the renderer's
input contract (`TailoredDraft` + profile) is deliberately agnostic to whether G2 ran.
M8P-4 then adds a second producer of an accepted draft without touching the renderer.

---

## 8. Risks and stop conditions

| Id | Risk | Stop condition / mitigation |
|---|---|---|
| R1 | M8P-3R renames or removes a `TailoredDraft` field | M8P-5 halts at its next task boundary, rebases, and re-runs its full focused suite before continuing. Assumption A1 is written into the M8P-5 plan as an explicit stop condition. |
| R2 | Two branches invent competing artifact schemas (e.g. two different "render result" shapes) | Every artifact schema is declared in exactly one milestone's design and is versioned with an explicit `schema_version` string. M8P-5 owns `render_result.v1`; M8P-6 owns `review_packet.v1` and `feedback_record.v1`; M8P-4 owns `g2_verdict.v1`. Cross-milestone reuse is by import, never by redefinition. |
| R3 | Treating static G1 as a resume-quality gate | Written into every design: G1 proves *structural and lexical* constraints only. It cannot see rendered geometry, cannot judge voice, and cannot detect a claim that is technically traceable but misleading. G2 and G3 exist precisely because G1 is insufficient, and no document may report "G1 pass" as "resume is good". |
| R4 | Using character count as a proxy for rendered line count | M8P-5's line check measures actual `LTTextContainer` geometry from the compiled PDF. Any character-count heuristic is a review rejection. `render_line_check` stays `"pending"` in the S3 bundle. |
| R5 | G2 inventing claims | G2's response schema contains **no free text destined for the resume** — only `{dimension, rule_id, quoted_line, requested_change_kind}`. Revision goes back through the S3 bounded edit contract, which already enforces verb preservation, numeric-multiset preservation, no-growth, cited-vocabulary-only, and the 15% budget. A G2 finding cannot bypass that. |
| R6 | Scaling to 30 because three runs *completed* rather than because they were *good* | M8P-8's plan opens with a numeric acceptance gate derived from M8P-7 feedback records; the plan cannot start until the gate query returns a pass. |
| R7 | Rendered PDFs containing phone/email committed to a public repository | The user's standing constraint is that `origin` is public and `config/master_profile.yaml` PII must stay local. `applications/` and every rendered PDF **must be gitignored**. This contradicts `TAILORING_METHODOLOGY.md` §3 ("resumes live as source in git") and requires the user's decision — see §9, D4. Until decided, M8P-5 writes only under a gitignored path. |
| R8 | The 30-resume corpus does not exist | §1.3. Surfaced as decision D1 before M8P-8 is planned into execution. |
| R9 | SkillOpt tuned against three or thirty examples overfits | M8X-1 forbids promotion without a held-out split and a minimum corpus size, and forbids running before a deterministic baseline is measured. |
| R10 | The user's review budget is consumed by Category 4 work | §4 recommendation: freeze Category 4 until the pilot is accepted. |

---

## 9. Decisions required from the user

| Id | Decision | Recommendation |
|---|---|---|
| D1 | The 30-resume dry run needs ~22 more distinct eligible ATS jobs than exist. Either (a) run the existing Phase 2 scoring chain over a slice of the 273 `RESOLVED` rows — which **writes to SQLite** — or (b) redefine the scale-up as "30 tailoring runs across the 8 available JDs plus prompt/profile variations", or (c) run fresh ingestion first. | (a), scoped and backed up, as its own approved maintenance step before M8P-8. (b) measures the pipeline against a corpus too small to generalise. |
| D2 | Does the bounded revision loop re-invoke **S3** with critic findings, or does **G2** emit edits directly? | **RESOLVED 2026-08-24: re-invoke S3.** `TAILORING_METHODOLOGY.md` §4 says "the tailor revises", and it keeps every edit inside the one contract that is already fabrication-proof. The M8P-4 design and plan are written against this; Task 4's blocker is cleared. |
| D3 | Does any pilot milestone write to SQLite (e.g. a `TAILORED` status)? | No. Keep the read-only boundary through M8P-8. A DB integration milestone can follow once the artifact layout has proven itself. |
| D4 | Are `applications/` directories and rendered PDFs git-tracked (methodology §3) or gitignored (public-repo PII constraint)? | **RESOLVED 2026-08-24: gitignored.** The PII constraint is a hard user rule; methodology §3 predates it. M8P-5 Task 6's blocker is cleared; the integrator records the deviation in `DECISIONS.md` at the M8P-5 integration commit. |
| D5 | Which three jobs for the pilot? | Chosen at execution time by the criteria in the M8P-7 design (§4 of that document), re-checking eligibility at run time. Do not pre-commit to 119/225/211. |
| D6 | Company Bank Track C before or after the pilot? | After. Evidence in §4: the JD-only pilot needs nothing from it. |
| D7 | Is `docs/prompts/tailoring_g2.md` PROTECTED from creation, or only after the first accepted pilot run? | Only after the first accepted pilot run, matching how `tailoring_s1.md` was handled (`DECISIONS.md`, 2026-08-21). |

---

## 10. Elapsed-time estimate

"Session" means one focused implementation session ending in a green suite and a
commit, matching the observed M8P-1 / M8P-2 / M8P-3 cadence (each of those was one
session producing 4–7 commits).

### One implementer

| Step | Sessions |
|---|---|
| M8P-3R | **complete** (0 remaining) |
| M8P-5 render + L7 | 1 |
| M8P-4 G2 + revision loop | 1–1.5 |
| M8P-6 G3 packet + feedback | 1 |
| M8P-7 three-resume pilot (incl. the user's review and one feedback incorporation pass) | 1 + ~1–2 h of the user's time |
| **To the three-resume pilot** | **5–5.5 sessions** |
| D1 scoring batch (if approved) | 0.5 |
| M8P-8 30-resume dry run | 1 + ~2–3 h of the user's time |
| **To the 30-resume pilot** | **6.5–7 sessions** |

### Two parallel implementers

| Wall-clock step | Sessions |
|---|---|
| M8P-5a ∥ M8P-6a (M8P-3R already merged) | 1 |
| M8P-5b integration ∥ M8P-4 | 1–1.5 |
| M8P-6b | 0.5 |
| M8P-7 pilot | 1 + the user's time |
| **To the three-resume pilot** | **3.5–4 sessions** |
| D1 + M8P-8 | 1.5 |
| **To the 30-resume pilot** | **5–5.5 sessions** |

Saving: roughly **1.5 sessions (≈30%)** to the first pilot. The saving is capped
because M8P-4 is both the longest single item and strictly downstream of M8P-3R;
no amount of parallelism shortens that edge.

Honest caveat: the user's review time is not parallelisable and does not shrink. If
the three pilot resumes need two feedback rounds, the elapsed time to acceptance is
dominated by the user, not by implementers.

---

## 11. Recommended assignment

**Claude (this planning authority, and integration):**
- Own M8P-4 (G2 critic + bounded revision loop). It is the subtlest contract in the
  remaining work — it must add adversarial value without gaining any authoring
  power — and it touches the S3 contract at integration time.
- Own the integrator role: merges in the §7.1 order, applies the deferred
  `ROADMAP`/`IMPLEMENTATION_PLAN`/`DECISIONS` deltas, and re-verifies the DB checksum
  after every merge.
- Own M8P-7's operator code and drive the live pilot session with the user.

**Gemini (second implementer, isolated worktree):**
- Own M8P-5 (render + L7 + rendered line count + publication). It is the most
  self-contained remaining track, it has zero overlap with M8P-3R's files, and it is
  verifiable entirely against committed PDF fixtures and synthetic drafts. Start now.
- Then own M8P-6 (G3 packet + feedback contract), starting with the parallel-safe
  feedback schema.
- Consistent with the recorded preference that Gemini receives a written design plus
  plan rather than an open-ended implementation brief: both documents exist before
  work starts.

**The user:**
- Resolve D1–D4 and D7 before M8P-4 and M8P-5 integration (D2 blocks M8P-4's first
  task; D4 blocks M8P-5's publication task).
- Supply the pilot judgement in M8P-7 — this is the irreplaceable input, and it is
  the actual product of Phase 3.
- Decide at the M8P-8 gate whether three accepted resumes justify thirty.
- Hold Category 4 work (Firecrawl bake-off, Company Bank Track C, M9D) until after the
  pilot is accepted.

---

## 12. Explicit non-goals of this document

This umbrella design does not:

- authorise any implementation, test, live run, model call, render, or commit beyond
  the planning documents themselves;
- modify `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md`, or `docs/DECISIONS.md`, or
  mark any milestone complete;
- change any M8P-3R file;
- add, install, clone, or evaluate a dependency, including SkillOpt;
- select the three pilot jobs;
- redesign the already-selected LaTeX renderer, whose 0.20in margins already satisfy
  the user's stated preference;
- import Company Bank data or introduce company-aware tailoring;
- promise that static G1 is a sufficient resume-quality gate.
