# ROADMAP.md — Phase Status

One repo. One docs/ folder. One CLAUDE.md, edited in place as phases unlock — never
forked. This file is the single source of truth for "what's live right now." Any Claude
Code session should check this file before starting work; if a phase says LOCKED, do not
build it — check the exit criteria with the user instead.

## Phase 1 — Ingestion, Filtering & Self-Healing (M0–M7, M6.x)
**Status: COMPLETE (2026-07-14).**
Current deterministic discovery (three trackers, inbox, wrapper unwrapping), resolution (tier-1 ATS
APIs, tier-2 browser, manual), prefilter, dedup + export-time clustering, freshness/
recycling defense, digest, scheduling, and the M7 audit suite (14 invariants, PASS on
live DB). Scoring I/O contract reworked 2026-07-14: model is pure text-in/text-out, the
wrapper owns all file I/O; self-consistency scoring (k=3, median + majority-vote) added
after run-to-run variance was measured. Specs: ARCHITECTURE.md, IMPLEMENTATION_PLAN.md
(M0–M5, historical), PHASE2_KICKOFF.md (M6.x), SELF_HEALING.md (M7).

## Phase 2 — Scoring Calibration
**Status: COMPLETE — user-approved deviation (2026-07-25).**

Phase 2 is closed without a post-tuning held-out round. This is an explicit deviation from
the stricter calibration protocol in `docs/PHASE2_KICKOFF.md`, approved by the user on
2026-07-25 and recorded in `docs/DECISIONS.md`.

Accepted closure facts:

- No post-tuning held-out round will be run before Phase 3.
- `2026-07-25-r1` had 12 complete fit labels: 9 APPLY, 2 MAYBE, 1 SKIP.
- After the protected quant-targeting addition to `config/profile_summary.md`, the report
  produced 9/12 agreement, 3 false negatives, and 0 false positives at threshold 6.0.
- This was tuning-confirmation evidence, not a held-out validation round.
- The user knowingly waived the additional held-out round because further calibration cost
  now exceeds its expected value.
- Three known false negatives remain accepted calibration debt.
- Zero false positives were observed in the usable human-reviewed calibration evidence.
- `shortlist_threshold = 6.0` is accepted and locked for the start of Phase 3.
- Stress-suite bands remain `PROVISIONAL`; they are not treated as calibrated evidence.
- The current `2026-07-25-r1.scored.json` must not be imported merely to close calibration;
  no database mutation is part of this closure.
- The 6,000-character scoring truncation / navigation-boilerplate failure mode is deferred
  technical debt, not a Phase 3 blocker.
- Jobs 229 and 279 are prohibited live-tailoring inputs until deterministic eligibility is
  corrected in a separate maintenance milestone: job 229 contains an ITAR U.S.-person
  requirement, and job 279 contains work authorization without employer sponsorship.
- Phase 3 remains fully human-reviewed and must never auto-submit applications.

NOTE: earlier claims of completion before 2026-07-19 were wrong; no scored output existed
before 2026-07-14, and the 2026-07-19 closure was later retracted during M6.13R after
invalid calibration rows were found. The 2026-07-25 closure supersedes that retraction via
explicit user approval of the narrower evidence standard above.

### Stabilization gate before the next calibration batch

**M6.10 — Resolution runtime hardening: COMPLETE (2026-07-15).** The M9D-0
backlog-clear exposed two production-boundary defects that unit-test success did not catch:
transient resolver infrastructure errors consumed a job's three-attempt content failure
budget, and the tier-2 Crawl4AI path launched a fresh Chromium lifecycle per URL. M6.10
implemented the approved stabilization design and plan:

- `docs/superpowers/specs/2026-07-15-resolution-runtime-hardening-design.md`
- `docs/superpowers/plans/2026-07-15-m6-10-resolution-runtime-hardening.md`

M6.10 is a stabilization milestone, not M9D-1. It added typed resolution outcomes, bounded
resolution work, a run-scoped browser lifecycle with a circuit breaker, static-first
Jobright fallback, reliable aborted-run accounting, and live-smoke evidence recorded in
DECISIONS.md. It did not add dependencies, start M9D-1/M8, or change scoring behavior.

**M6.11 — Configurable Eligibility Policy v2: COMPLETE (2026-07-16).** Offline code, tests,
audit migration, docs, the read-only/guarded impact tool, live preview, backed-up apply, and
bounded live smoke are complete. The policy is country-first, config-driven, separates
eligibility from scoring config, and live acceptance evidence is recorded in DECISIONS.md.

**Calibration Contract v2: COMPLETE (2026-07-16).** The implementation now separates
metadata-only `interest_call` from full-JD `fit_call`, defaults fresh rounds to 12 canonical
groups, validates batch/interest/fit/JD/scored provenance, reads complete JDs through a
read-only SQLite connection, preserves the historical `2026-07-12.user.md` worksheet as
legacy interest-only evidence, and compares 7+ shortlist decisions only against fit labels.

**M6.12 — Role-Family Matching v2: COMPLETE (2026-07-19).** Closed a gap in M6.9's JD-text
fallback where a single incidental keyword match (e.g. "platform" once) let clearly
wrong-specialty postings (casino game tester, PCBA technician, PhD-only research scientist)
reach the scorer. Added title-only exclude patterns and a distinct-hit threshold for the JD
fallback, then widened the include vocabulary after the live-DB impact preview surfaced
false-negative titles the narrower list missed. See `docs/DECISIONS.md` (2026-07-19 entry)
for the approved deviation from the documented 20%-of-scored-volume revisit trigger and full
live impact numbers. Calibration round `2026-07-17-r2` was contaminated by this change (3 of
its 12 jobs were reclassified `FILTERED_OUT`) and was regenerated as `2026-07-19-r2` (12 fresh
jobs, zero overlap with any prior round). CORRECTION (2026-07-25): the same eligibility
tightening also invalidated rows in the *earlier* rounds, which was not checked at the time —
`2026-07-17-r1` lost 3 groups and `2026-07-16-r1` lost 5 to eligibility plus 2 to
dead-posting pages. `2026-07-19-r2` remains the only complete clean round.

**M6.13 — Dead-posting content gate: SUPERSEDED (2026-07-22), replaced by M6.13R
(2026-07-25).** M6.13 correctly identified that dead ATS shells were passing `passes_quality()`
and being scored, but its detector matched unbounded fragments and its remediation overwrote
terminal states. M6.13R narrowed the detector to explicit subject+predicate notices, made the
remediation transactional and state-safe, and repaired the 35 overwritten `FILTERED_OUT` rows.
Evidence in `docs/DECISIONS.md` (2026-07-25 entry).

## Phase 3 — Tailoring (M8)
**Status: UNLOCKED; M8 item 1 and item 2 COMPLETE (2026-07-30). The prior M8 item 3 tailor/critic code is a non-production skeleton, not the live workflow. The M8 phrasing rework is complete.**
Unlock condition met by explicit Phase 2 closure above plus the ATS-quality shortlist gate.
Gate status (2026-07-25): 16 `SHORTLISTED` rows carry `jd_quality='ats'` in `data/jobs.db`.
Quantcast contributes one of those rows (job 279), so removing Quantcast would still leave
15 ATS-quality shortlisted rows, comfortably above the ≥5 gate. A prior note suggesting M8
item 1 already existed was incorrect — verified 2026-07-14: no master-profile loader in repo.
M8 item 1 adds only the pure, schema-validating `config/master_profile.yaml` loader.
M8 item 2 rewrites the loader to schema v0.3.0 and authors the deterministic sections of `config/master_profile.yaml`.
The M8 phrasing rework is complete: both base variants cut to 13 bullets on a measured one-page budget; `src/profile_lint.py` added and wired into `scripts/validate_profile.py`; the emphasis pipeline (`src/render/emphasis.py`, `RenderBullet.emphasis`, `\textbf` in the LaTeX arm, markdown in the RenderCV arm) added.
M8P-1 (2026-08-21) is COMPLETE: the validated S1 requirement-extraction contract, strict/semantic parser, protected S1 prompt (`docs/prompts/tailoring_s1.md`), safe tool-disabled invocation wrapper, I11 tracing, read-only job-preparation DB boundary, and a narrow `prepare`/`invoke` CLI (`scripts/tailor_s1.py`). M8P-2 (2026-08-23) is COMPLETE offline: JD-only S0 positioning, privacy-minimised S0/S2 projections, deterministic S2 selection validation, traced safe invocations, and one-job CLI preparation/invocation are implemented and tested. No live model invocation, Company Bank use, database mutation, resume generation, or PDF generation occurred. Jobs 119/225/211 passed eligibility and profile-projection preflight only. What genuinely remains in M8: S3, G1 completion (L1/L4), G2, G3, PDF rendering, DB integration, and the archival layout. Next: M8P-3.
The Company Knowledge Bank design was approved on 2026-08-04 as a supporting M8 subsystem.
Track A foundation is complete. The approved seed corpus is 20 companies. Track B is local
research-in-progress only: 20/20 ignored inbox bundles exist before Batches 5/6, and no raw
research inbox artifact should be Git-tracked. Source verification and rendered fallback are
approved and implemented; the 2026-08-06 hardening repair closes fail-closed, redirect,
throttling, report-output, and staging-boundary defects in that verifier. Track C canonical
adoption, S0/S2/G3 integration, live tailoring, CLI integration, and DB integration remain
incomplete and require their own scoped milestone.


## Upgrades (M9–M12)
**Status: see docs/UPGRADE_PLAN.md.** M9 items 1–2 (cadence, watchlist adapter) are
unblocked now that M7 is complete; M9 item 3 (hot lane) is gated on Phase 2 exit.
M10 is complete: both arms built, L7 implemented including `check_page_count`, `check_no_overlap`, and `check_within_page`; LaTeX selected as the production renderer. M10's completion satisfies the renderer dependency for M8. M11–M12 by appetite/trigger.

## Hybrid Discovery v2 (M9D)
**Status: M9D-0 COMPLETE; M9D-1..M9D-5 NOT IMPLEMENTED; M9F-0 COMPLETE (live smoke
closed 2026-08-21), shipped disabled by default; M9F-1..M9F-3 NOT IMPLEMENTED.**
The current three-tracker discovery layer is not considered the final coverage architecture.
M9D-0 added checkpoint/source-failure correctness and baseline reporting. Remaining M9D work
adds multi-source provenance, direct ATS and authorized alert sources, a bounded crawler
bake-off, and an agentic source scout operating in shadow mode behind a deterministic
acceptance gateway. Detailed design:
`docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`.

Firecrawl adoption was approved as a target on 2026-08-06. M9F-0/M9F-1 may add and evaluate
a credit-bounded known-URL tier-2 REST backend before M9D-1; Firecrawl Map/Crawl/Search
discovery remains staged and blocked on M9D-1. M9F-0 is **COMPLETE** as of 2026-08-21: the
implementation was repaired, offline-verified, and closed by its single user-supervised live
REST smoke (one `/v2/scrape`, one credit). The integration ships disabled by default:
`browser_backend` remains `crawl4ai`, so no production run reaches Firecrawl. Activating it
requires the M9F-1 bake-off and a recorded user decision. M9F-1 through M9F-3 remain
unimplemented. Detailed design:
`docs/superpowers/specs/2026-08-06-firecrawl-ingestion-integration-design.md`.

M9D is a family of one-session sub-milestones, not one giant implementation session. Before
starting M9D-1, create and approve a dedicated plan for M9D-1 only. M8 remains governed by
its Phase 2 gate; discovery work does not silently unlock or implement M8.

- 2026-08-23: **M8P-2 initial closeout was premature and was repaired as M8P-2R.** The
  pre-repair implementation accepted fabricated catalog bullets and reordered experience
  groups, omitted response shapes from both prompts, and had only four new contract tests.
  Repair commits `ad19314`, `9c34823`, and `cd7c927` add canonical profile binding, observed
  experience-order validation, complete prompt contracts, injection blocking, and focused
  pipeline/CLI/integration coverage. Final verification passes 1290 tests with 1 deselected.
  No live model/network/Company Bank use, DB mutation, resume, or PDF occurred. Jobs
  119/225/211 passed M8P-1 eligibility and projection preflight only. Next is M8P-3; Phase 3,
  M8, and both human pilots remain incomplete.

## Not yet specified (future, not gated — just not designed)
Notion sync; Claude-in-Chrome JD capture; automated gap→project pipeline. Alert-email
ingestion and controlled Apify evaluation now belong to M9D. LinkedIn scraping remains
rejected; LinkedIn alert emails remain permitted.

M8P-3 (2026-08-24) is complete as an offline S3/static-G1 foundation. Commits
`07dce7f`, `9cf487a`, `7f94fa3`, `6fbf2ef`, `64fa048`, `f488dd4`, and `9a1fd9c`
implement canonical alignment, strict bounded edits, deterministic hydration/diffs,
static G1, protected invocation/tracing, fail-closed CLI preparation, and integration
coverage. Focused verification passed 34 tests; the full suite passed 1330 with 1
deselected. No live model, network, Company Bank, database mutation, resume, PDF, or
pilot activity occurred. `render_line_check` remains `pending`; rendered line checking,
G2, G3, final rendering, and human pilots remain incomplete. M8P-4 is not started.

**M8P-3's initial closeout above was premature and was repaired as M8P-3R
(2026-08-24).** An independent review found the 34/1330-passing suite insufficient:
`s3_bundle_to_dict()` used dataclass `.__dict__`, so no otherwise-valid response could
ever publish (`TypeError: DraftBullet is not JSON serializable`); `run_static_g1()`
checked only the bullet-id sequence, so a bullet keeping its id but carrying a
fabricated `owner_id`/`owner_kind`, or an undeclared mutation to an unedited bullet's
text/plain_text/emphasis, both passed `static_pass`; `run_s3_invocation()` caught bare
`Exception` around response parsing and mislabeled any unrelated programmer error as
`parse_failure`; and the plan's required strict authoritative bundle parser did not
exist. Test coverage matched: the CLI test file had one shallow contract test, the
integration file had two tests, and the required G1 adversarial mutation matrix,
prepare failure matrix, and mocked valid-publish-and-reparse test were all absent.
Repair commits `e587c94`, `a0d90f1`, `a1864fa`, `c01f9ab`, and `e67aca1` add explicit
recursive serializers for every persisted contract type; a strict authoritative bundle
parser (`parse_s3_bundle`) that structurally validates a persisted `s3_bundle.json` and
then deterministically recomputes the response, draft, change log, diff, edit budget,
and G1 report from the authoritative request, rejecting any persisted field that
disagrees; G0 canonical-binding checks applied to every draft bullet (not just declared
edits) for owner identity, exact text-vs-canonical-or-accepted-edit equality, and
plain_text/emphasis reparse consistency; narrowed exception handling so only
`S3ParseError`/`S3SemanticError` become modeled outcomes; a 19-case G1 adversarial
mutation matrix; a full CLI prepare failure matrix (prohibited job, ineligible status,
DB/S1 mismatch, injection-blocked S1, S0/S2 request/response drift, stale persisted
catalog, changed DB-recommended variant, current profile drift, request preservation on
failure); mocked valid publication that reparses via the new strict parser; failure
preservation across parse/semantic/invocation/G1 failures; and pipeline-outcome coverage
including `HYDRATION_FAILURE` and exactly-once/no-retry invocation. Focused verification
(`test_alignment_view.py`, `test_s3.py`, `test_g1.py`, `test_s3_pipeline.py`,
`test_tailor_s3_cli.py`, `test_m8p3_integration.py`) passed 85 tests; the full suite
passed 1381 with 1 deselected. No live model, network, Company Bank access, database
mutation, resume, or PDF occurred in the repair session; `data/jobs.db` was never
opened for write and its checksum is unchanged. `render_line_check` remains `pending`.
**Only after M8P-3R does M8P-3 count as complete.**

M8P-4 (2026-08-25) is COMPLETE offline. G2 is an anchored critic operating over the diff and the change log; revisions are routed back through S3's existing bounded contract and re-evaluated under full static G1 and canonical edit budgets. G2 never authors resume text. Prepare revalidates the full upstream chain and accepted S3 bundle; invoke publishes a `g2_bundle.json` only on passing rounds or open flags. Rendering, L7, `render_line_check`, G3, Company Bank integration, and both human pilots remain incomplete. Neither M8, Phase 3, nor any pilot is marked complete.

M8P-5 (2026-08-25) is COMPLETE offline. Tailored drafts now render deterministically through the selected LaTeX arm; rendered line counts and font geometries are measured from real PDF geometry post-render (`locate_text_lines`); `run_l7_tailored` runs all 11 base L7 checks plus 6 tailored checks. The S3 bundle's own G1 report correctly remains `render_line_check="pending"` because a pre-render gate cannot prove a rendered fact; the real verdict belongs only in `render_result.json`. Applications are published atomically to gitignored `applications/` with `render_result.json` written last as the commit marker. G3, the review packet, feedback capture, and both human pilots remain incomplete. Neither M8, Phase 3, nor any pilot is marked complete.

M8P-6 (2026-08-26) is COMPLETE offline. Tasks 1–3 established the validated feedback record contract, immutable append-only revision-numbered storage (`data/feedback/`), and pure taste-candidate derivation (`derive_taste_candidates`, which writes nothing). Tasks 4–6 add `src/tailor/g3.py`: a deterministic Markdown review packet (`review.md`) plus a typed JSON twin (`packet.json`) built entirely from already-validated S1/S0/S2/S3-bundle/G2-bundle/render-result artifacts, bound by `alignment_fingerprint` and `job_id` and failing closed on any disagreement between them, and a pre-populated YAML feedback form (`feedback_form.yaml`); and `scripts/tailor_g3.py`'s `build`/`record`/`summarize` CLI. G3 makes **no model call** — the critic already ran in G2 — and has **no web UI**: the review surface is a Markdown file read next to the rendered PDF and a YAML file the user edits, per the design's explicit rejection of a server or frontend dependency. Publication is idempotent (`ALREADY_BUILT` on an identical packet, `CONFLICT` on a differing one, never an overwrite) and `review.md` is byte-identical across runs on identical inputs. Neither human pilot has run and no resume has yet been produced; M8P-7 (pilot operator), M8P-8, and both human pilots remain incomplete. Neither M8, Phase 3, nor any pilot is marked complete.

## Log
- 2026-07-14: File recreated (was missing from repo since project start — the original
  package copy was never added). Statuses set from verified repo/DB state, not from
  memory or chat claims.
- 2026-07-14: Hybrid Discovery v2 approved as a planned M9D track. No M9D code or dependency
  was added by the documentation change.
- 2026-07-14: M9D-0 completed. Tracker checkpoints now prepare before DB insertion and
  atomically commit only after durable insertion; `--limit` drains `pending_keys`; adapter
  fetch/checkpoint issues are structured in run notes/digest warnings; source-yield/backlog
  baseline captured read-only. M9D-1 through M9D-5 remain unimplemented.
- 2026-08-04: M10 completed (LaTeX selected) and M8 phrasing rework completed. Statuses set from verified repo state. The previously circulated baseline of "785 tests passing" and "11 RenderCV violations" were stale; the verified baseline is now 883 passed / 1 deselected, and 14 RenderCV violations (due to later overlap and page-bleed checks).

- 2026-08-06: Company Bank Track A foundation complete; approved seed corpus is 20 companies; Track B local ignored inbox research is in progress at 20/20 before Batches 5/6. Source verification and rendered fallback are approved and implemented, with hardening repairs closed. Track C/canonical adoption, S0/S2/G3 integration, live tailoring, CLI integration, and DB integration remain incomplete.
- 2026-08-06: Firecrawl integration design approved as target-only M9F work. M9F-0/M9F-1
  cover a credit-bounded known-URL REST backend and bake-off; Map/Crawl/Search discovery
  remains blocked on M9D-1.
- 2026-08-21: M9F-0 acceptance-contract repair landed and offline-verified (per-run credit
  cap, ledger state accounting, credential-before-reserve, shared deterministic tier-2 page
  acceptance, typed dry-run deferral, canonical tier-2 contract, run-note/digest
  observability). Default backend remains `crawl4ai`; M9F-1 through M9F-3 remain
  unimplemented.
- 2026-08-21: M9F-0 live REST smoke executed and **M9F-0 is COMPLETE**. One authorized
  `/v2/scrape` against one dead generic-host posting, one credit charged. Auth, transport,
  ledger reserve/reconcile, cooldown, budget decrement, and deterministic acceptance all
  verified live; the page was correctly rejected `bad_status` (upstream HTTP 404,
  independently corroborated). Production DB byte-identical. Default backend remains
  `crawl4ai`; M9F-1..M9F-3 and M9D-1 remain unimplemented.
- 2026-08-21: **M8P-1 is COMPLETE.** O1 (manual vs. wrapper-invoked S1 model call) resolved
  as wrapper-invoked pure text-in/text-out (see
  `docs/superpowers/specs/2026-08-21-m8-human-pilot-s1-design.md`). Built and offline-verified
  the S1 requirement-extraction contract/trace foundation only: typed dataclasses, a strict
  parser with JD-anchored semantic validation, the protected `docs/prompts/tailoring_s1.md`
  prompt, a safe tool-disabled invocation wrapper, I11 tracing, a read-only job-preparation DB
  boundary (jobs 229/279 prohibited), and a narrow `prepare`/`invoke` CLI. The legacy unsafe
  `src/tailor/wrapper.py` single-shot path is permanently disabled. Company Bank remains
  optional and unavailable to this stage. S0/S2/S3/G1(L1,L4)/G2/G3, PDF generation, taste
  capture, DB mutation, and batch mode remain unimplemented. No resume has been generated and
  no live S1 invocation occurred; the three planned pilot jobs (119 Cisco, 225 Notion, 211
  Citadel) were not touched. Next: M8P-2 (S0 + S2, one-job-at-a-time, JD-only).
- 2026-08-24: **M8P-3R repair complete.** M8P-3's 2026-08-24 closeout (commits `07dce7f`
  through `9a1fd9c`) claimed completion on a suite that was insufficient: an unserializable
  bundle blocked every valid publish, static G1 skipped bullet-owner binding and undeclared
  mutations, `run_s3_invocation()` mislabeled unrelated exceptions as parse failures, and the
  plan's required authoritative bundle parser was never built. Repair commits `e587c94`,
  `a0d90f1`, `a1864fa`, `c01f9ab`, and `e67aca1` fix all four defects, add `parse_s3_bundle`,
  and close the test-coverage gap (G1 adversarial matrix, CLI prepare failure matrix, mocked
  valid-publish-and-reparse, failure preservation, pipeline outcomes). Full suite: 1381 passed,
  1 deselected. `data/jobs.db` checksum unchanged; no live model/network/Company Bank/DB
  mutation/resume/PDF activity occurred. M8P-3 counts as complete only as of this entry.
  M8P-4, G2, G3, rendering, PDF generation, Company Bank integration, and both human pilots
  remain unstarted.
- 2026-08-25: **M8P-4 is COMPLETE offline.** Implemented the anchored G2 critic and bounded
  revision loop (commits `073ba9e`, `f69e7b1`, `85d9f2b`, `1fe4ab6`, `68feec1`, `5e8beb3`,
  and `84c5554`). G2 operates over the diff and change log with strict privacy projection,
  closed rule vocabularies, and exact quoted substrings. Revisions re-invoke S3 under its
  existing bounded edit contract and must pass full static G1 with edit budgets recomputed
  against the canonical alignment. G2 never emits replacement resume text. Prepare revalidates
  the full upstream chain and accepted S3 bundle; invoke produces `g2_bundle.json` only on
  pass or open_flags. Full test suite: 1433 passed, 1 deselected. `data/jobs.db` checksum
  unchanged; no live model, network, Company Bank, DB mutation, resume, or PDF activity
  occurred. Rendering, L7, `render_line_check`, G3, and both human pilots remain incomplete.
- 2026-08-25: **M8P-5 is COMPLETE offline.** Implemented deterministic tailored rendering, PDF
  line/char geometry extraction, tailored L7 gate (`run_l7_tailored`), atomic publication
  (`render_and_publish`), and bundle-driven render CLI (`scripts/tailor_render.py`) across commits
  `3b2ce9b`, `ecc2896`, `7317f42`, `531cafe`, and `5234626`. Rendered line counts are measured
  from real PDF geometry (`locate_text_lines`), proving L4 2-line limits on modified bullets
  post-render. S3 bundle G1 report correctly remains `render_line_check="pending"`; the real
  verdict is stored in `render_result.json`. Applications are published atomically to gitignored
  `applications/` (D4). Full test suite: 1477 passed, 1 deselected (+44 net tests over M8P-4).
  `data/jobs.db` checksum unchanged; no live model, network, `pdflatex`, or DB mutation occurred.
  G3, review packet, feedback capture, and both human pilots remain incomplete.
