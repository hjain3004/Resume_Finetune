# CLAUDE.md — job-pipeline

Personal job-discovery pipeline. The implemented ingestion path is deterministic. The
approved M9D target adds an agentic discovery control plane whose outputs remain staged
until deterministic validation and user/policy approval. Claude is also used for scoring
and tailoring through explicit file contracts. You (the coding agent) are the implementer;
the current/target boundary is fixed in `docs/ARCHITECTURE.md`, the phase status is in
`docs/ROADMAP.md`, and milestone work is indexed in `docs/IMPLEMENTATION_PLAN.md`.

## Prime directives

1. **The docs are authoritative.** Read `docs/ARCHITECTURE.md` before writing code. If code
   and docs disagree, the docs win. If the real world and the docs disagree (a site changed,
   an endpoint differs), stop and ask the user; record approved deviations in
   `docs/DECISIONS.md`.
2. **One milestone at a time.** Never start milestone N+1 in the same session as N.
3. **Idempotency is sacred.** Any change that could make a second identical run mutate the DB
   is a bug, full stop.
4. **No unapproved dependencies.** The currently approved list is: requests, trafilatura, PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver), pdfminer.six (M10 L7 gate). RenderCV/Typst are bake-off-only and become runtime deps only if adopted by the M10 decision; Node/OpenResume is an opt-in test oracle and must never be required by pytest -q.
   Ask before adding anything else.
5. **Tests never touch the network.** Fixtures live in `tests/fixtures/`, recorded via
   `scripts/record_fixture.py`. Live checks are manual "smoke" steps run with the user.
6. **Etiquette is non-negotiable:** no LinkedIn scraping, no auth/CAPTCHA bypass, ≥2 s
   between requests to the same host, honest User-Agent. If a source resists, mark it failed
   and surface it in the digest — do not escalate scraping tactics.
7. **Keep production acceptance deterministic.** `src/` is the deterministic data plane.
   Agentic discovery belongs in a separate control-plane script/tool and may only write
   versioned proposal artifacts; it may not edit approved source config or write SQLite.
   Every proposal passes deterministic validation, provenance, policy, dedup, and promotion
   gates. Scoring/tailoring continue through their file contracts. Never dynamically select
   an arbitrary public Actor in an unattended production run.

## Commands

- Run pipeline: `python -m src.run_ingest` (flags: `--dry-run --source X --limit N
  --discover-only --resolve-only --db PATH`)
- Tests: `pytest -q`
- Record a fixture: `python scripts/record_fixture.py <url> <name>`

## Code style

- Python 3.11+, type hints everywhere, dataclasses over dicts at module boundaries.
- Small pure functions; parsing separated from I/O so parsers are testable on fixtures.
- Raw sqlite3 via `src/db.py` helpers only — no SQL strings outside `db.py`.
- Logging via `logging` (INFO to stderr); never `print` inside `src/` (CLI summary output is
  the exception, in `run_ingest.py` only).
- UTC ISO-8601 timestamps in storage.

## Definition of done (every milestone)

pytest green → acceptance criteria in `docs/IMPLEMENTATION_PLAN.md` checked → live smoke run
with the user where the plan calls for one → `git commit` with `feat(mN): ...` message →
one-paragraph summary to the user of what was built and any decisions recorded.
