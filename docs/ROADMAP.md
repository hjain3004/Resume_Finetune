# ROADMAP.md — Phase Status

One repo. One docs/ folder. One CLAUDE.md, edited in place as phases unlock — never
forked. This file is the single source of truth for "what's live right now." Any Claude
Code session should check this file before starting work; if a phase says LOCKED, do not
build it — check the exit criteria with the user instead.

## Phase 1 — Ingestion, Filtering & Self-Healing (M0–M7, M6.x)
**Status: COMPLETE (2026-07-14).**
Deterministic discovery (trackers, inbox, wrapper unwrapping), resolution (tier-1 ATS
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

## Not yet specified (future, not gated — just not designed)
Gmail alert-email adapter; Notion sync; Claude-in-Chrome JD capture; automated
gap→project pipeline; Apify LinkedIn experiment (Phase 2.5, optional, per prior
decision).

## Log
- 2026-07-14: File recreated (was missing from repo since project start — the original
  package copy was never added). Statuses set from verified repo/DB state, not from
  memory or chat claims.
