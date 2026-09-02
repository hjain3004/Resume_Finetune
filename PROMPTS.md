# PROMPTS.md — Kickoff prompts for Sonnet (one per session)

Usage: open Claude Code in the repo, one milestone per session, paste the prompt. After the
milestone, run the acceptance checks from `docs/IMPLEMENTATION_PLAN.md` yourself. If something
fails, reply with only the failing check and the error output.

---

## M0
Read CLAUDE.md and docs/ARCHITECTURE.md fully. Then implement milestone M0 from
docs/IMPLEMENTATION_PLAN.md exactly: repo bootstrap only. Do not start M1. Show me the
tree and the pyproject before committing.

## M1
Read CLAUDE.md, docs/ARCHITECTURE.md (especially §4 and §5.2), and milestone M1 in
docs/IMPLEMENTATION_PLAN.md. Implement M1: models, db layer, fixture recorder, and the
vanshb03 tracker adapter with snapshot diffing. Before writing the parser, fetch the live
repo's README once to verify branch name and table shape, record findings in
docs/DECISIONS.md, and save the README as a test fixture. Write the unit tests listed in
the acceptance criteria. When pytest is green, walk me through the live smoke test
(--limit 25, then a second run proving 0 new inserts) — I'll run it with you. Then commit.

## M2
Read CLAUDE.md, docs/ARCHITECTURE.md §6, and milestone M2. Implement the resolution layer:
polite session, HTML→text helper, then resolvers in order (greenhouse, lever, ashby,
workday, generic) each with recorded fixtures from real postings already in my DB, then the
router with redirect handling, then --resolve-only wiring. Do NOT add BeautifulSoup or
Playwright. Ask me before deviating from the documented endpoints if any of them behave
differently than specified. Finish with the live smoke resolution run and report the
success rate by domain.

## M3
Read CLAUDE.md, docs/ARCHITECTURE.md §5, and milestone M3. Refactor shared tracker logic
into a helper, then add the Simplify adapter (probe .github/scripts/listings.json first),
the jobright-ai adapter, and the manual inbox adapter with processed/ moves. Add the
cross-source dedup and adapter-isolation tests from the acceptance criteria. Commit when
green.

## M4
Read CLAUDE.md, docs/ARCHITECTURE.md §7–10, and milestone M4. Implement prefilter, digest,
the full default pipeline chain with --dry-run, and the idempotency test (this test is the
most important artifact of the milestone — write it first, TDD style). Then ask me my OS
and preferred daily run time and set up the scheduler with an install script. Finish with
a full live run; I'll review the digest with you.

## M5
Read CLAUDE.md, docs/ARCHITECTURE.md §11, and milestone M5. Build the scoring I/O contract:
export_batch.py, import_scores.py with strict validation, and the scoring prompt template
in docs/scoring_prompt.md. I've placed my resume PDFs in profile/ — draft
config/profile_summary.md from them, factually, and show it to me for approval before
committing. Do not build any tailoring functionality; that's Phase 3 and gated on my
dry-run feedback.

## M8N-0
Read CLAUDE.md, docs/ARCHITECTURE.md, docs/TAILORING_METHODOLOGY.md §3–§4, the design
docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md (all of it), and the plan
docs/superpowers/plans/2026-09-01-m8n-0-apply-now-lane.md. Implement M8N-0 only, task by
task, in a git worktree, using superpowers:subagent-driven-development or
superpowers:executing-plans. Do not start M8N-1. Do not open data/jobs.db except through the
read-only export-jd helper. Never stage data/, inbox/, applications_manual/, profile/, or
docs/sampleJD.md. The only prompt edits permitted are the two documented-shape fixes in
tailoring_s1.md and tailoring_s0.md described in plan Task 2, which I approve now under spec
N12; make no other prompt change. When pytest is green and the
three benchmark jobs (225, 119, 211) reach G3 through the lane, stop and walk me through the
review packets; I approve before you commit the closeout docs.

## Debugging template (any milestone)
Acceptance check failed: [paste the check text from IMPLEMENTATION_PLAN.md].
Output: [paste error/output]. Fix within the constraints of CLAUDE.md — if the fix
requires deviating from ARCHITECTURE.md, propose the deviation and wait for my approval.
