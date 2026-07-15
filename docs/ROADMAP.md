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
**Status: IN PROGRESS — started 2026-07-14. NOTE: earlier claims of completion were
wrong; no scored output existed before this date (see DECISIONS.md).**
Protocol: docs/PHASE2_KICKOFF.md "Phase 2 — Calibration protocol" + amendments (threshold
asymmetry, segment tagging, exemplar injection gate). Exit criteria: user has blind-rated
≥ 15–20 real jobs; two consecutive batches with zero threshold-crossing disagreements
per calibration_report.py; shortlist_threshold locked in config; scoring stress-suite
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

**M6.11 — Configurable Eligibility Policy v2: OFFLINE IMPLEMENTATION COMPLETE
(2026-07-15); live acceptance pending.** Offline code, tests, audit migration, docs, and the
read-only/guarded impact tool are implemented. The policy is country-first, config-driven,
and separates eligibility from scoring config. Task 10 remains a hard user-supervised gate:
do not run the live `data/jobs.db` impact preview, create live backups, apply transitions,
or run live smoke until explicitly approved.

**Calibration-contract correction follows in a separate milestone.** The current worksheet
is a metadata-interest baseline, while the scorer sees the full JD; those labels cannot be
used as equivalent evidence. The next calibration design must separate metadata
`interest_call` from JD-informed `fit_call`, and treat both APPLY and MAYBE as positive for
the 7+ human-review shortlist. Do not combine that correction with M6.10 or M6.11.

## Phase 3 — Tailoring (M8)
**Status: LOCKED. Nothing built (a prior note suggesting item 1 existed was incorrect —
verified 2026-07-14: no master-profile loader in repo).**
Unlocks when: Phase 2 exit criteria met AND ≥ 5 SHORTLISTED rows with jd_quality='ats'.
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
