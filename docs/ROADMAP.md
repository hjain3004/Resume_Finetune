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
**Status: IN PROGRESS — exit-integrity repair / one clean round remaining (2026-07-25).**

The 2026-07-19 closure is **retracted**. It claimed 36 fresh fit-labeled jobs across three
non-contaminated rounds; a read-only reconciliation against the live DB (M6.13R) shows that
was not true at the time and is not true now:

| Round | Canonical groups | Still valid | Why the rest are invalid |
|---|---|---|---|
| `2026-07-16-r1` | 12 | **5** | 5 later filtered `eligibility:work_authorization`; 2 hold dead-posting pages (jobs 2, 18) |
| `2026-07-17-r1` | 12 | **9** | 2 filtered `eligibility:role_family_excluded`, 1 `eligibility:work_authorization` |
| `2026-07-19-r2` | 12 | **12** | — |
| **Total** | 36 | **26** | one complete ≥10-job clean round exists, not three |

The approved deviation on 2026-07-19 waived only the "two consecutive zero-disagreement
rounds" condition. It did not waive the eligibility, minimum-round-size, or real-JD
requirements, so 26 usable labels across one clean round does not clear the gate.

`shortlist_threshold` stays at 6.0 and remains **provisionally supported**: no currently
valid `SKIP` label scored above 5.0, which leaves a clean margin under 6.0. That margin must
be confirmed by the next clean round before the threshold is treated as locked.

Stress-suite bands are back to `PROVISIONAL` (all 10 cases). The 2026-07-19 flip to
CALIBRATED re-anchored four bands around a single synthetic scorer run, not human fit
evidence. See `docs/DECISIONS.md` (2026-07-25 entry) for the full retraction and the live
DB repair evidence.

**Remaining Phase 2 gate: one more complete clean round.** The ≥5 ATS-quality shortlist gate
for Phase 3 is already met and stays met — 12 `SHORTLISTED` rows carry `jd_quality='ats'`
after the M6.13R repair — so the evidence gate is the only thing left.

NOTE: earlier claims of completion before 2026-07-19 were also wrong; no scored output
existed before 2026-07-14 (see DECISIONS.md).
Protocol: docs/PHASE2_KICKOFF.md "Phase 2 — Calibration protocol v2" + amendments
(threshold asymmetry, segment tagging, exemplar injection gate). Exit criteria: at least
20 fresh eligibility-passed canonical jobs with complete JD-informed `fit_call` labels;
at least two complete v2 rounds; at least 10 canonical jobs per round; two consecutive
complete rounds with zero threshold-crossing disagreements per `scripts/calibration_report.py`;
shortlist_threshold locked in config only after evidence supports it; scoring stress-suite
bands re-anchored from PROVISIONAL to calibrated values.

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
**Status: LOCKED. Nothing built (a prior note suggesting item 1 existed was incorrect —
verified 2026-07-14: no master-profile loader in repo).**
Unlocks when: Phase 2 exit criteria met AND ≥ 5 SHORTLISTED rows with jd_quality='ats'.
Gate status (2026-07-25): the ATS-quality half is **met** — 12 `SHORTLISTED` rows carry
`jd_quality='ats'`, verified after the M6.13R repair. The Phase 2 evidence half is **not**
met (see above), so Phase 3 stays LOCKED. A note in the M8 profile-loader design spec
claiming Phase 3 unlocked on 2026-07-22 was wrong and has been corrected in place.
Spec: docs/TAILORING_METHODOLOGY.md (workflow S1 → S0 → S2 → S3 → G1 → G2 → G3). First
sessions after unlock: M8 item 1 (profile loader), then the interactive master-profile
construction session with the user (§2 protocol) before any live tailoring.

## Upgrades (M9–M12)
**Status: see docs/UPGRADE_PLAN.md.** M9 items 1–2 (cadence, watchlist adapter) are
unblocked now that M7 is complete; M9 item 3 (hot lane) is gated on Phase 2 exit. M10
(render bake-off + L7 parseability gate) must complete before M8's render step. M11–M12
by appetite/trigger.

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
