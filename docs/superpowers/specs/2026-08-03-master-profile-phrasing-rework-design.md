# Design — master_profile phrasing rework + emphasis pipeline

**Date:** 2026-08-03
**Supersedes:** `docs/HANDOFF_PHRASING_REWORK.md` (kept for history; see §7 for its errors)
**Status:** approved; reconciled with the in-place implementation plan on 2026-08-03

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

Six calls the user made during design:

| # | Decision | Consequence |
|---|---|---|
| D1 | **Print all five estimated Amdocs metrics** (~40% data footprint, ~25% query perf, ~50% QA effort, ~40% defects, ~60% resolution time) | All five `metric_ledger` entries become renderable and all five appear together in both base variants. This is an explicit, Amdocs-scoped exception to the profile's prior two-estimate cap. |
| D2 | **Page shape: 4 internship / 6 Amdocs / 2 projects** — later reduced to 3 internship (D4) | Amdocs-weighted: two years of shipped production work leads |
| D3 | **Add the missing Amdocs scene-setter, drop `am_b06`** | New `am_b00`; Spring Boot / Jenkins / OpenShift finally reach the page |
| D4 | **Drop `int_b6`** (test rigor / Postman / Docker / GitLab CI) | Internship goes to 3 bullets; 13 total. Test-automation and CI keywords still reach the page via `am_b00`, `am_b05`, and the Skills line |
| D5 | **Scope includes the emphasis pipeline**, not just content + guards | The umbrella design covers both concerns, but implementation is split at the milestone boundary in §3.1. |
| D6 | **Preserve the existing design and plan in place** | Correct their contracts and exact steps; do not replace them with new documents. |

D1 is legal under the existing schema: `Provenance.ESTIMATED` is **not** in
`NON_RENDERABLE_PROVENANCES` (only `UNSOURCED`, `CONTRADICTED`, `NONE` are). It deliberately
overrides the stale Amdocs comment and known-gap text that cap a resume at two estimated
metrics. Those two policy statements must be rewritten in the same content change; changing
only `renderable` would leave the profile self-contradictory. The exception is narrow: it
authorizes these five named Amdocs estimates together, keeps their provenance and interview
defenses, and does not make any other estimated metric automatically renderable.

### 3.1 Milestone and session boundary

This remains one design and one implementation-plan document, but not one implementation
session:

1. **M10 infrastructure:** emphasis grammar/parser, render-IR transport, both renderer
   emitters, page-count guard, and adoption of the existing bake-off operator script into
   version control.
2. **Mandatory stop:** focused and full tests green, M10 acceptance checked, and an M10
   commit completed. Do not edit profile content in that session.
3. **M8 content hardening in a fresh session:** phrasing lint, evidence-preserving rewrites,
   base-variant reduction, real-profile validation, and the user-supervised render smoke.

This boundary satisfies the repository's one-milestone-per-session directive without
discarding the useful umbrella analysis in this document.

## 4. Content plan — 13 bullets (`backend` 3,399 chars; `ml` 3,537 chars)

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

The merge is structural, not phrasing-only. In the same YAML edit:

- `int_b2.evidence` gains the `int_b4` evidence for the eight request types and the
  three-layer ESB/core-banking/network success condition; its `keywords_hit`, `defense`, and
  `interview_risk` are updated to cover the combined transfer claim.
- `int_b3.evidence` gains the `int_b8` evidence for server-side credential isolation,
  `SecretStr`, recursive credential/PII redaction, and XML hardening; its `keywords_hit`,
  `defense`, and `interview_risk` are updated to cover the combined security claim.
- `int_b4` and `int_b8` remain independent bullets with their original evidence because the
  tailor may still select them separately. The intentional evidence duplication is preferable
  to a surviving bullet whose own evidence does not support its rendered text.

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

Every estimated number remains visibly hedged exactly as recorded in the ledger (`~40%`,
`~25%`, `~50%`, `~40%`, `~60%`). D1 authorizes printing all five; it does not convert a
reconstructed estimate into an exact measurement. Doc-backed figures such as 90% coverage,
~500 smells, 70% topic sprawl, and ~80% partitions retain their existing provenance and
wording.

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
`bullet_order`). The two Sepsis bullets matching `Himanshu_Resume_Gen.tex` have been resolved
against the current profile: **`sepsis_b8`** is the 175-feature leakage-safe pipeline and
**`sepsis_b3`** is the calibrated meta-stacking ensemble. Their ML `bullet_order` positions
are `sepsis_b3` followed by `sepsis_b8`, preserving the current same-entry priority ordering
(priority 1 before priority 3). No implementation-time ID choice remains.

### 4.5 Rewrite rules

- Every rewrite stays inside evidence stored on that bullet after the same atomic edit. A
  surviving merged bullet must copy the relevant source-bullet evidence as specified in
  §4.1; pointing at evidence that remains only on another bullet is insufficient. No bullet
  gains an unsupported claim. **Fabrication is the one unrecoverable failure here.**
- Opening verbs drawn from the user's real vocabulary: Architected, Automated, Built,
  Contributed, Designed, Engineered, Fine-tuned, Implemented, Improved, Integrated, Raised,
  Reduced. Past tense, never a gerund.
- Metric-first when a metric exists; technique follows via "by …"; supporting detail follows
  a semicolon.
- Concrete named technology in nearly every bullet — this is what carries ATS weight.
- Rewritten headline `medium` phrasings generally target 200–395 characters, with 400 as the
  hard maximum. Existing concise project mediums may remain below 200 when expanding them
  would add no information (`ct_b2` is intentionally 139). `short` is a genuine one-line
  variant, normally ~110–150; `long` is optional.
- Preserve every bullet `id`. Rewrite `phrasings`; never renumber.

## 5. Emphasis pipeline

**Enabling fact:** `\textbf{}` does not change the text pdfminer extracts. If
`RenderBullet.text` stays plain, `check_bullets_survive` and the other existing L7 content
checks keep working untouched. Emphasis itself requires no L7 content-survival change;
`src/render/l7.py` changes only for the independent page-count guard in §6.2.

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

- New pure module **`src/render/emphasis.py`**:
  `parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]`, returning plain text
  and span offsets into that plain text. Offsets, not substrings, make repeated text
  unambiguous.
- The delimiter grammar is explicit. A `**` occurrence can open when the following character
  exists and is non-whitespace; it can close when the preceding character exists and is
  non-whitespace. Outside a span, an opening-capable marker opens. Inside a span, a
  closing-capable marker closes; an opening-only marker is a nested opener and raises
  `EmphasisError("nested ...")`. A close-only marker outside a span and an opener left at EOF
  are unbalanced. Adjacent markers that produce a zero-length body raise
  `EmphasisError("empty ...")`.
- This grammar distinguishes the actual nested case
  `Cut **p99 **latency** here** now.` from three valid consecutive spans
  `Cut **p99** **latency** **here** now.`. Merely counting markers and pairing positions is
  explicitly rejected: it cannot detect nesting and made the original nested check dead code.
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

New module **`src/profile_lint.py`** — pure checks over a loaded `MasterProfile` and an
explicit tuple of banned terms, called from `scripts/validate_profile.py`. File I/O is kept
at the CLI boundary: a small loader resolves `config/banned_words.txt` from the repository
root and passes its contents to `lint_profile`. This keeps the lint deterministic from any
working directory and makes the claim that its checks are pure true. It remains deliberately
outside `load_profile`: style opinions must never make the profile schema-invalid for the
tailor or break the synthetic schema fixtures in `tests/test_profile.py`.

| Rule | Threshold | Basis |
|---|---|---|
| 1 | `medium` ≤ 400 chars | real max 395 |
| 2 | `short` ≤ 200 chars | one-line variant |
| 3 | first word must not end in `ing` | no gerund openings |
| 4 | no whole word or phrase from `config/banned_words.txt` | existing config; boundary matching avoids substring false positives |
| 5 | markup balanced, non-empty, non-nested; ≤3 spans; ≥1 span for `medium` of ordered bullets | §5.3 |
| 6 | **sum of resolved default phrasing lengths across a `bullet_order` ≤ 3,800 chars** | §2 measurement; resolution is `medium`, falling back to `short` exactly as the renderer does |

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
have no `medium`. Rules 1 and the medium-specific part of Rule 5 skip a missing `medium`.
Rule 6 must count the `short` fallback rather than silently undercounting what the renderer
will emit. A synthetic ordered short-only bullet is a required regression test.

The 3,800-character lint is a reusable backstop. The two rewritten real base variants have
a stricter acceptance target of **3,600 characters each**. The implementation plan fixes and
asserts their exact resolved plain-text totals: **backend 3,399** and **ML 3,537**. "Roughly
3,700–3,800 and trim if needed" is not an acceptable final contract.

`scripts.validate_profile` prints its success line only after both schema validation and
phrasing lint pass. A lint failure may print `SCHEMA OK` followed by `LINT FAILED`, but it may
not print an unconditional `OK` and then exit 1.

### 6.2 L7 page count

- `ParsedPdf` gains `page_count` property: `max((b.page for b in self.boxes), default=-1) + 1`.
  `parse_pdf` creates contiguous zero-based page indexes, which is the invariant this formula
  relies on; the test name must say "highest zero-based page index plus one," not "distinct
  pages."
- New `check_page_count(doc, parsed)` reading `doc.ats["layout"]["max_pages"]`, registered in
  `run_l7`. No-ops when the key is absent, matching `check_single_column` and
  `check_file_size`; a present value must be a positive integer and malformed policy produces
  a clear L7 configuration violation rather than leaking `ValueError`.
- `ats.layout.max_pages: 1` added to `config/master_profile.yaml`.

### 6.3 Bake-off operator prerequisite

`scripts/render_bakeoff.py` exists in the working tree but is currently untracked. The M10
segment must review it, add focused operator-script coverage where practical, and commit it
before any Done criterion invokes `python -m scripts.render_bakeoff`. The plan may not assume
an unversioned local artifact.

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
- **Omits** that all four reference resumes predate the internship entirely, so the
  budget must now cover two jobs.
- **Omits** that the five estimated Amdocs metrics were deliberately blocked, and that the
  profile's own `am_gap_estimated_metrics` note prescribes keeping them out — a note this
  design overrides per D1 and rewrites accordingly.
- **Omits** the emphasis gap entirely.

## 8. Testing

- **`tests/test_profile_lint.py`** — a synthetic fixture per rule, including an ordered
  short-only bullet for the budget fallback, plus regression tests asserting the real
  `config/master_profile.yaml` passes and both real variants are at or below 3,600 plain
  characters.
- **`tests/render/test_emphasis.py`** — round-trip: plain output is markup-free, offsets
  land on the intended substrings, repeated substrings resolve correctly, three adjacent
  valid spans stay valid, and unbalanced / empty / genuinely nested markers raise with the
  right error class.
- **`tests/render/test_latex.py`** — emphasized bullet emits `\textbf{}`; **a LaTeX special
  character inside an emphasized span escapes correctly** (the real trap in per-segment
  escaping).
- **`tests/render/test_rendercv.py`** — highlights carry `**…**`.
- **`tests/render/test_l7_layout.py`** — a two-page `ParsedPdf` is reported, one page passes,
  and malformed/non-positive `max_pages` is reported deterministically. Built directly from
  `TextBox` tuples per the existing convention in that file — no PDF fixture and no TeX in
  the test path.
- **`tests/render/test_mapping.py`** — its bullet-order assertions are already dynamic and
  require no count rewrite. Its unavailable-tier test must stop deriving coverage from the
  mutable real profile and instead use a synthetic bullet with no `long` phrasing, so the
  test cannot silently turn into a skip after content edits.

Baseline is **827 passed, 1 deselected** (measured 2026-08-03). The deselected test is
the opt-in Tier B parser oracle, excluded by `addopts = "-m 'not oracle'"` in
`pyproject.toml` — that is correct and required by CLAUDE.md.

The handoff document's figure of 785 was stale; it predates the M10 test commits
(`9c50f8e`, `bb37acf`, `30f537e`, `e955633`).

## 9. Constraints and non-goals

- **Never `git push` during this work.** The locally recorded `origin/main` already tracks a
  nearly complete `config/master_profile.yaml`; only eight lines differ from the current
  local version. Therefore "it exists only in unpushed commits" is not a valid privacy
  control. Before any future push, independently audit the current remote file and Git
  history and decide whether sanitization or history repair is required. This milestone does
  not rewrite published history.
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

### 10.1 M10 infrastructure segment

1. Emphasis grammar tests cover valid adjacent spans and the genuine nested case; focused
   render tests and the full suite are green against the measured **827 passed, 1
   deselected** pre-work baseline.
2. Plain text remains the L7 contract while LaTeX and RenderCV receive equivalent emphasis.
3. `ParsedPdf.page_count` and `check_page_count` pass focused tests, including malformed
   policy handling.
4. `scripts/render_bakeoff.py` is reviewed and versioned rather than assumed from the working
   tree.
5. M10 is committed and the session stops before any M8 lint or profile-content edit.

### 10.2 M8 content-hardening segment

1. In a fresh session, `.venv/bin/python -m scripts.validate_profile` reports schema and lint
   success without printing a contradictory success line on failure.
2. Backend and ML each contain exactly 13 ordered bullets. Their resolved plain-text totals
   are asserted as backend **3,399** and ML **3,537**, both below 3,600.
3. Every merged bullet's own evidence, keywords, defense, and interview-risk fields support
   its final phrasing.
4. All five named Amdocs estimates appear in both base variants under the explicit D1
   exception; the stale two-estimate cap and known-gap instructions are removed, while all
   five metrics retain `provenance: estimated` and the three affected bullets retain
   `claim_type: estimated`.
5. The full suite is green. The LaTeX bake-off arm produces a one-page PDF; the RenderCV arm's
   page count and L7 result are reported separately and do not decide the paused renderer
   bake-off.
6. Before/after bullet counts, character totals, page counts, and the rendered PDF are shown
   to the user for judgment.
7. `docs/DECISIONS.md` records D1's scoped policy exception, the `am_b05` claim-type change,
   the `am_b03`/`am_b04`/`am_b05` priority re-rating, and any measured deviation from this
   contract.
