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
What genuinely remains in M8: live tailoring (the S1 → S0 → S2 → S3 → G1 → G2 → G3 workflow in `docs/TAILORING_METHODOLOGY.md`), the CLI, and DB integration.
The Company Knowledge Bank design was approved on 2026-08-04 as a supporting M8 subsystem.
Its foundation, separate 30-company web-research run, and corpus adoption are fully planned
but not yet implemented; completing the bank will still not complete or integrate the live
tailoring workflow.


## Upgrades (M9–M12)
**Status: see docs/UPGRADE_PLAN.md.** M9 items 1–2 (cadence, watchlist adapter) are
unblocked now that M7 is complete; M9 item 3 (hot lane) is gated on Phase 2 exit.
M10 is complete: both arms built, L7 implemented including `check_page_count`, `check_no_overlap`, and `check_within_page`; LaTeX selected as the production renderer. M10's completion satisfies the renderer dependency for M8. M11–M12 by appetite/trigger.

## Hybrid Discovery v2 (M9D)
**Status: M9D-0 COMPLETE; M9D-1..M9D-5 NOT IMPLEMENTED.**
The current three-tracker discovery layer is not considered the final coverage architecture.
M9D-0 added checkpoint/source-failure correctness and baseline reporting. Remaining M9D work
adds multi-source provenance, direct ATS and authorized alert sources, a bounded crawler
bake-off, and an agentic source scout operating in shadow mode behind a deterministic
acceptance gateway. Detailed design:
`docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`.

M9D is a family of one-session sub-milestones, not one giant implementation session. Before
starting M9D-1, create and approve a dedicated plan for M9D-1 only. M8 remains governed by
its Phase 2 gate; discovery work does not silently unlock or implement M8.

## Not yet specified (future, not gated — just not designed)
Notion sync; Claude-in-Chrome JD capture; automated gap→project pipeline. Alert-email
ingestion and controlled Apify evaluation now belong to M9D. LinkedIn scraping remains
rejected; LinkedIn alert emails remain permitted.

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

Company Bank foundation complete; research corpus, adoption, and S0/S2 integration pending.
