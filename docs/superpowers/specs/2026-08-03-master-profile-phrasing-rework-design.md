# Design — master_profile phrasing rework + emphasis pipeline

**Date:** 2026-08-03
**Supersedes:** `docs/HANDOFF_PHRASING_REWORK.md` (kept for history; see §7 for its errors)
**Status:** approved by user, ready for implementation planning

## 1. Problem

M10's render bake-off produced the first real PDF from `config/master_profile.yaml`.
It rendered **2 pages / 8,853 characters** (LaTeX arm) and **3 pages** (RenderCV arm)
against a measured one-page budget of ~4,450 characters. The user's verdict was that the
bullets read as "AI slop."

Three distinct defects, measured rather than assumed:

1. **Volume.** `base_variants.backend.bullet_order` holds 29 bullets / 7,350 chars of
   `medium` phrasing. The user's own one-page resumes hold 11–13 bullets / ~3,400–3,800
   chars. Bullet *length* is already correct (profile median ~253 vs real median ~275,
   profile max 336 vs real max 395) — the excess is entirely count.
2. **Fragmentation.** `int_b1`/`int_b2`/`int_b3` are three priority-1 bullets describing
   one accomplishment: `int_b1` is the adapter layer, `int_b2` (idempotency) and `int_b3`
   (the AML gateway) are components of it promoted to headline status.
3. **No emphasis.** `RenderBullet` carries plain text and `escape_latex()` escapes all of
   it, so every bullet renders as undifferentiated gray prose. The user's real resume bolds
   a metric clause or a key noun phrase in nearly every bullet. This is a renderer
   capability gap, not a content problem, and it is a large part of the "slop" impression.

Nothing in the pipeline currently constrains any of this. L4/C4 lint the *tailored draft*
downstream; no gate reads `master_profile.yaml` for count, length, or style, and L7 never
asserts a page count.

## 2. Measurements

All four reference PDFs in `profile/` are one page and remarkably consistent:

| PDF | Pages | Rendered lines | Total chars |
|---|---|---|---|
| `Himanshu_Jain.pdf` | 1 | 61 | 4,447 |
| `Himanshu_Jain_cv.pdf` | 1 | 62 | 4,611 |
| `Himanshu_Jain_Gen.pdf` | 1 | 61 | 4,481 |
| `Himanshu_Resume_New.pdf` | 1 | 61 | 4,430 |

Bullet text only, extracted from the `.tex` sources (excluding two brace-bug artifacts and
a commented template example): **11–14 bullets, 3,389–3,766 chars total, median ~275,
max 395.**

Structure of every reference resume: Education (2 entries) → Experience (**Amdocs only**,
7–8 bullets) → Projects (**exactly 2**, 2–3 bullets each) → Technical Skills.

**The new resume must fit two jobs**, so it carries four entry headers where the references
carry three. Budget target is therefore the lower half of the measured range: **~3,300–3,600
chars of bullet text.**

## 3. Decisions

Five calls the user made during design:

| # | Decision | Consequence |
|---|---|---|
| D1 | **Reinstate all five estimated Amdocs metrics** (~40% data footprint, ~25% query perf, ~50% QA effort, ~40% defects, ~60% resolution time) | `metric_ledger` entries flip to `renderable: true`; `am_gap_estimated_metrics` is rewritten to record this as the user's decision |
| D2 | **Page shape: 4 internship / 6 Amdocs / 2 projects** — later reduced to 3 internship (D4) | Amdocs-weighted: two years of shipped production work leads |
| D3 | **Add the missing Amdocs scene-setter, drop `am_b06`** | New `am_b00`; Spring Boot / Jenkins / OpenShift finally reach the page |
| D4 | **Drop `int_b6`** (test rigor / Postman / Docker / GitLab CI) | Internship goes to 3 bullets; 13 total. Test-automation and CI keywords still reach the page via `am_b00`, `am_b05`, and the Skills line |
| D5 | **Scope includes the emphasis pipeline**, not just content + guards | Pulls renderer work (`model.py`, `mapping.py`, `latex.py`, `rendercv.py`) into a content session; accepted deliberately |

D1 is legal under the existing schema: `Provenance.ESTIMATED` is **not** in
`NON_RENDERABLE_PROVENANCES` (only `UNSOURCED`, `CONTRADICTED`, `NONE` are). The prior
`renderable: false` was a judgment call, not a constraint.

## 4. Content plan — 13 bullets, ~3,300 chars

### 4.1 Internship: 8 → 3

| Slot | Merges | Claim |
|---|---|---|
| 1 | `int_b1` | The anti-corruption layer — four asynchronous Python microservices (FastAPI, SQLAlchemy 2.0, PostgreSQL) on one standardized adapter architecture |
| 2 | `int_b2` + `int_b4` | Exactly-once money movement: INSERT-first idempotency reservation proven under an 8-way parallel duplicate harness, on the real-time interbank transfer adapter (8 transaction types, three-layer settlement validation) |
| 3 | `int_b3` + `int_b8` | Fail-closed AML sanctions screening over both REST/JSON and legacy SOAP/XML, with credential isolation, recursive PII redaction, and XML-injection/XML-bomb resistance |

Demoted out of `bullet_order` (retained in the profile, available to the M8 tailor):
`int_b5`, `int_b6`, `int_b7`.

Merges 2 and 3 are the direct fix for defect #2: sub-details fold in after a semicolon
rather than becoming their own bullet, matching the user's real style.

### 4.2 Amdocs: 6 → 6 (one swap)

Rendered order, matching the narrative order of the real resume:

| Slot | Bullet | Metrics printed |
|---|---|---|
| 1 | **`am_b00_order_management_domain`** (new) | none — scene-setting |
| 2 | `am_b04_data_retention` | ~40% footprint, ~25% query perf |
| 3 | `am_b05_test_automation` | ~50% QA effort, ~40% defects, 90% coverage, ~500 smells |
| 4 | `am_b03_audit_trail` | ~60% resolution time |
| 5 | `am_b01_dlq_consolidation` | 70% sprawl, 80% partitions (already doc-backed) |
| 6 | `am_b02_row_level_entitlement` | none |

Demoted: `am_b06_aws_ci_and_resilience`.

**`am_b00` is not fabrication.** Its claim (Order Management domain — Catalog, Shopping
Cart, Proposal and Agreement — Java/Spring Boot microservices, Jenkins pipelines,
OpenShift) is fully supported by the existing `amdocs_software_developer.scope_line`, which
already names every one of those elements. Its `evidence` field cites that scope line and
the prior resume; `claim_type: verified`; no metric.

**Priority re-rating.** `bullet_order` is validated so no bullet may precede a strictly
lower-priority bullet **from the same entry**. The order above is illegal today
(`am_b01`/`am_b02` are priority 1; `am_b03`/`am_b04`/`am_b05` are priority 2). Reinstating
their metrics genuinely re-rates those three bullets, so they move to **priority 1** rather
than contorting the order. `am_b00` is authored at priority 1. `priority` feeds the tailor's
L6 flagship-ordering gate — this is a deliberate, recorded change, not a workaround.

**`am_b05` claim_type changes `verified` → `estimated`,** because two of the four numbers it
will now print (~50%, ~40%) are estimated. A bullet that prints an estimated figure is not
fully verified. `am_b03` and `am_b04` are already `estimated` and stay so.

### 4.3 Projects: 4 bullets

Clinical Trial Platform (`ct_b1`, `ct_b2`) and Campus Marketplace (`cm_b1`, `cm_b2`) — the
pair on the user's own resume. `peerchat_peer_discovery` is removed from
`base_variants.backend.projects` and its bullets leave `bullet_order`; the entry stays in
the profile for JD-specific tailoring.

### 4.4 ml variant: 28 → 13

Same 3 internship + 6 Amdocs bullets, then Sepsis ×2 and Fake Review ×2 (`frd_b1`,
`frd_b3` — the other four `frd_*` bullets are `ownership_unresolved` and blocked from any
`bullet_order`). The two Sepsis bullets are the ones matching `Himanshu_Resume_Gen.tex`:
the 175-feature leakage-safe pipeline and the calibrated meta-stacking ensemble. **The
implementer must confirm which bullet ids carry those two claims before selecting them** —
do not assume `sepsis_b1`/`sepsis_b2` without reading the phrasings.

### 4.5 Rewrite rules

- Every rewrite stays inside its existing `evidence`. No bullet gains a claim its evidence
  does not already support. **Fabrication is the one unrecoverable failure here.**
- Opening verbs drawn from the user's real vocabulary: Architected, Automated, Built,
  Contributed, Designed, Engineered, Fine-tuned, Implemented, Improved, Integrated, Raised,
  Reduced. Past tense, never a gerund.
- Metric-first when a metric exists; technique follows via "by …"; supporting detail follows
  a semicolon.
- Concrete named technology in nearly every bullet — this is what carries ATS weight.
- `medium` 200–395 chars. `short` is a genuine one-line variant, ~110–150. `long` optional.
- Preserve every bullet `id`. Rewrite `phrasings`; never renumber.

## 5. Emphasis pipeline

**Enabling fact:** `\textbf{}` does not change the text pdfminer extracts. If
`RenderBullet.text` stays plain, `check_bullets_survive` and every other L7 check keep
working untouched. Bold is purely additive — **`src/render/l7.py` requires no change.**

### 5.1 Approaches considered

- **A. Inline `**markup**` in the phrasing** *(chosen)* — one source of truth, natural to
  author, and RenderCV consumes `**` natively. Costs a new character convention requiring
  its own lint rule.
- **B. Separate `emphasis:` list of literal substrings** — keeps phrasing text clean, but
  duplicates content, rots silently when a phrasing is rewritten, and is ambiguous when a
  substring occurs twice.
- **C. Auto-bold metrics by regex** — zero authoring burden, but cannot find the noun
  phrases the user actually bolds (**modular Data-Fencing extension library**, **AI Medical
  Monitor agent**). Too rigid.

### 5.2 Design (A)

- New pure module **`src/render/emphasis.py`**: `parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]`
  returning plain text and span offsets into that plain text. Offsets, not substrings, so
  repeated text is unambiguous. Raises on unbalanced, empty, or nested markers.
- **`RenderBullet`** gains `emphasis: tuple[tuple[int, int], ...] = ()`. The default keeps
  the one construction site in `src/render/mapping.py:68` and all six test construction
  sites valid — no churn.
- **`src/render/mapping.py`** calls `parse_emphasis` when building each `RenderBullet`.
- **`src/render/latex.py`** segments the plain text at span boundaries, runs `escape_latex`
  **per segment**, then wraps emphasized segments in `\textbf{}`. Per-segment escaping is
  what keeps the `\textbf` braces from being escaped themselves — this is the subtle part.
- **`src/render/rendercv.py`** re-emits `**…**` in `highlights` (currently
  `[bullet.text for bullet in entry.bullets]` at line 27).

### 5.3 Style rule

**1–3 emphasized spans per `medium` phrasing** for any bullet in a `bullet_order`; 0–3
elsewhere. Taken from the reference resumes, not invented — the Purge & Archive bullet in
`Himanshu_Resume_New.tex` carries exactly three. Spans mark either the metric clause or the
key noun phrase.

## 6. Guards

### 6.1 Phrasing lint

New module **`src/profile_lint.py`** — pure functions over a loaded `MasterProfile`, called
from `scripts/validate_profile.py`. Deliberately **not** inside `load_profile`: style
opinions must never render the profile schema-invalid for the tailor, and doing so would
break existing `tests/test_profile.py` fixtures.

| Rule | Threshold | Basis |
|---|---|---|
| 1 | `medium` ≤ 400 chars | real max 395 |
| 2 | `short` ≤ 200 chars | one-line variant |
| 3 | first word must not end in `ing` | no gerund openings |
| 4 | no term from `config/banned_words.txt` | existing config |
| 5 | markup balanced, non-empty, non-nested; ≤3 spans; ≥1 span for `medium` of ordered bullets | §5.3 |
| 6 | **sum of `medium` lengths across a `bullet_order` ≤ 3,800 chars** | §2 measurement |

Rule 6 is the guard that actually prevents recurrence: it catches a 29-bullet regression at
the source, before anything renders. Its ceiling (3,800) sits deliberately above the
authoring target from §2 (~3,300–3,600) — the lint is a backstop against regression, not the
budget itself. Hitting 3,800 means the page is already at risk; L7's page-count check in
§6.2 is the hard stop.

Thresholds are calibrated to the measurements in §2, **not** to L4's ≤2-line rule — the
user's interview-tested resume is the authority.

**Known failures on current content** that must be fixed as part of this work rather than
allowlisted: `int_b7` `medium` 431, `int_b8` `medium` 481, and `short` over 200 on `int_b1`
(214), `sepsis_b9` (213), `sepsis_b11` (217), `frd_b7` (279). These are demoted bullets, but
the lint ships clean.

**Short-only bullets must be tolerated** — `pc_b06`, `sepsis_b9`, `sepsis_b11`, `frd_b7`
have no `medium`. Rules 1, 5, and 6 must skip a missing `medium` rather than crash.

### 6.2 L7 page count

- `ParsedPdf` gains `page_count` property: `max((b.page for b in self.boxes), default=-1) + 1`.
- New `check_page_count(doc, parsed)` reading `doc.ats["layout"]["max_pages"]`, registered in
  `run_l7`. No-ops when the key is absent, matching `check_single_column` and
  `check_file_size`.
- `ats.layout.max_pages: 1` added to `config/master_profile.yaml`.

## 7. Corrections to the handoff document

`docs/HANDOFF_PHRASING_REWORK.md` is superseded. Its errors, for the record:

- **"Preserve every `bullet_id`"** — the YAML field is `id`. `bullet_id` exists only on
  `RenderBullet` in the render IR.
- **"`ParsedPdf` already knows page count"** — it does not. There is no such field; it is
  derivable from `TextBox.page`.
- **"Bold the metric, not the noun"** — wrong about the user's style. The reference resumes
  bold metric clauses *and* key noun phrases, up to three spans per bullet.
- **"Target ~12–14 bullets"** — correct by accident. The binding constraint is total
  characters (~3,300–3,600), because bullet count alone does not bound page length.
- **"~6 to their main job and 2–3 per project"** — the references give Amdocs 7–8 and each
  project exactly 2.
- **Omits** that all three reference resumes predate the internship entirely, so the
  budget must now cover two jobs.
- **Omits** that the five estimated Amdocs metrics were deliberately blocked, and that the
  profile's own `am_gap_estimated_metrics` note prescribes keeping them out — a note this
  design overrides per D1 and rewrites accordingly.
- **Omits** the emphasis gap entirely.

## 8. Testing

- **`tests/test_profile_lint.py`** — a synthetic fixture per rule, plus one test asserting
  the real `config/master_profile.yaml` passes clean.
- **`tests/render/test_emphasis.py`** — round-trip: plain output is markup-free, offsets
  land on the intended substrings, repeated substrings resolve correctly, unbalanced /
  empty / nested markers raise.
- **`tests/render/test_latex.py`** — emphasized bullet emits `\textbf{}`; **a LaTeX special
  character inside an emphasized span escapes correctly** (the real trap in per-segment
  escaping).
- **`tests/render/test_rendercv.py`** — highlights carry `**…**`.
- **`tests/render/test_l7_layout.py`** — a two-page `ParsedPdf` is reported, one page
  passes. Built directly from `TextBox` tuples per the existing convention in that file —
  no PDF fixture and no TeX in the test path.
- **`tests/render/test_mapping.py`** — requires updating; it asserts over `bullet_order`,
  which changes from 29 entries to 13.

Baseline is **785 tests passing**.

## 9. Constraints and non-goals

- **Never `git push`.** `origin` is a public GitHub repo; `config/master_profile.yaml`
  contains real contact details and private notes that exist only in unpushed commits.
  Commit locally only.
- **No new dependencies.** Everything here uses the existing approved set.
- **Tests never touch the network**, and must not require a TeX installation.
- **Blocked bullets** (`claim_type` in `ownership_unresolved` / `needs_input`) may not enter
  any `bullet_order`.
- **Non-goal: deciding the M10 renderer bake-off.** Task 10 Step 4 stays paused. Re-rendering
  the PDF here is for content review only; choosing LaTeX vs RenderCV is the user's call on
  visual acceptability and is out of scope.
- **Non-goal:** the sixth project ("Performance Modeling for Cloud Message Queue Systems",
  Sep–Dec 2025) present in `Himanshu_Resume_cv.tex` but absent from `master_profile.yaml`.
  Recorded in `docs/DECISIONS.md`; out of scope unless the user asks.
- **Non-goal:** `config/profile_summary.md` duplicating facts `master_profile.yaml` owns.

## 10. Done

1. `pytest -q` green (785 baseline + new tests).
2. `.venv/bin/python -m scripts.validate_profile` prints OK **and** the new phrasing lint
   passes clean.
3. Bake-off re-rendered: `.venv/bin/python -m scripts.render_bakeoff --variant backend --template profile/template.tex`
   produces a **one-page** PDF.
4. Before/after bullet counts and the rendered PDF shown to the user for judgement.
5. Deviations recorded in `docs/DECISIONS.md` — specifically D1 (metric reinstatement),
   the `am_b05` claim_type downgrade, and the `am_b03`/`am_b04`/`am_b05` priority re-rating.
