# Job Pipeline — Documentation Package

Architecture and implementation docs for an automated job-discovery and resume-tailoring
pipeline. Designed by Claude Fable; intended to be implemented by Claude Sonnet in Claude Code.

## What this system is

A daily, mostly-deterministic pipeline that:

1. **Discovers** new job postings from GitHub trackers, email alerts, and a manual inbox (zero LLM tokens)
2. **Resolves** posting links into clean job-description text via ATS APIs (zero LLM tokens)
3. **Filters** obvious mismatches with deterministic rules (zero LLM tokens)
4. **Scores** survivors against the user's profile in one batched Claude call (Phase 2)
5. **Tailors** resumes for shortlisted jobs via a diff-based, anti-slop workflow (Phase 3)
6. **Reports** everything in a daily digest for human review

The governing principle: **deterministic code does everything that doesn't require judgment;
Claude is invoked only for scoring, tailoring, and critique.** Ingestion (Phases 0–1) is a pure
Python pipeline with no agentic behavior at runtime.

## Files in this package

| File | Purpose | Who reads it |
|---|---|---|
| `ARCHITECTURE.md` | Full system design: data model, module contracts, source adapters, resolver router, error handling | Sonnet, before any milestone |
| `IMPLEMENTATION_PLAN.md` | Milestones M1–M5 with tasks, acceptance criteria, and definition of done | Sonnet, one milestone at a time |
| `CLAUDE.md` | Project memory file — copy to the repo root of the new project | Claude Code, automatically |
| `TAILORING_SPEC.md` | Phase-3 spec: master profile schema, ATS rules, anti-slop rules, critic rubric | Sonnet, in Phase 3 only |
| `PROMPTS.md` | Ready-to-paste kickoff prompts for each milestone | You (the user) |

## How to use this with Sonnet

1. Create an empty project folder (e.g. `~/job-pipeline`), `git init`, and copy `CLAUDE.md`
   into its root. Copy `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, and `TAILORING_SPEC.md`
   into a `docs/` subfolder.
2. Open Claude Code in that folder with Sonnet selected.
3. Work **one milestone at a time**. Paste the corresponding prompt from `PROMPTS.md`.
   Do not ask Sonnet to build multiple milestones in one session — each milestone ends with
   passing tests and a git commit, which keeps context small and quality high.
4. After each milestone, run the acceptance checks listed in `IMPLEMENTATION_PLAN.md` yourself
   before moving on. If a check fails, tell Sonnet which check failed and nothing else — the
   docs contain everything needed to fix it.
5. Review diffs before committing. You are the code reviewer; Sonnet is the implementer.

## Non-negotiable constraints (summary — full versions in ARCHITECTURE.md)

- Python 3.11+, SQLite, no external services in Phase 0–1. No frameworks beyond the listed libraries.
- Every pipeline run must be **idempotent**: running twice in a row changes nothing on the second run.
- Tests never hit the live network. Fixtures only.
- Polite fetching: rate limits, honest User-Agent, no auth-wall circumvention, no LinkedIn scraping.
- No secrets in the repo. `.env` is gitignored from commit one.
