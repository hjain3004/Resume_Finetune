# IMPLEMENTATION_PLAN.md — Milestones & Acceptance Criteria

Status note (2026-07-14): M0–M7 are implemented history. Phase status is authoritative in
`docs/ROADMAP.md`. Hybrid Discovery v2 is an approved target, not implemented code; its
design is `docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`. Before starting it,
write and approve a detailed plan for **M9D-0 only**. Do not treat the design document's
rollout list as executable coding instructions.

Status amendment (2026-07-15): M9D-0 is complete, but the live backlog-clear exposed a
resolution-runtime stabilization gate before further calibration or M9D work. Implement
**M6.10 only** from
`docs/superpowers/plans/2026-07-15-m6-10-resolution-runtime-hardening.md`; then perform its
user-supervised live smoke. The separate calibration-contract correction described in
`docs/ROADMAP.md` is not part of M6.10.

Rules of engagement for the implementer:

- Build **one milestone per session**, in order. Read `docs/ARCHITECTURE.md` first, every time.
- A milestone is done only when every acceptance criterion passes and `pytest` is green.
- End every milestone with a git commit (conventional message: `feat(m1): ...`).
- If the architecture doc is ambiguous or a live site's behavior contradicts it, STOP and ask
  the user. Do not invent workarounds silently. Record any user-approved deviation in
  `docs/DECISIONS.md` (create it on first use, one dated line per decision).
- Tests never hit the live network. Use `scripts/record_fixture.py` (built in M1) to capture
  real responses once, commit them under `tests/fixtures/`, and test against those.
- Keep functions small and typed. No cleverness. Another model designed this; a human reviews it.

For M9D, “one milestone” means exactly one of M9D-0 through M9D-5. Later M9D work may not
start in the same session. Crawlee, Apify runtime integration, and schema changes require
the explicit gates recorded in the M9D design and `SELF_HEALING.md`.

---

## M0 — Repo bootstrap (15 min)

Tasks: `git init`; `pyproject.toml` with deps from ARCHITECTURE §3; `.gitignore`
(data/, snapshots/, inbox/processed/, .env, __pycache__, *.pyc); empty package skeleton
matching ARCHITECTURE §2; `config/sources.yaml` and `config/filters.yaml` with the defaults
from the architecture doc; `pytest` runs (collecting zero tests is fine).

Accept: `python -m src.run_ingest --help` exits 0 with usage text (stub CLI is fine).

## M1 — Data layer + first adapter (vansh tracker)

Tasks:
1. `models.py`: `DiscoveredJob`, `ResolvedJD`, `Status` enum, `norm()`, `norm_loc()`,
   `dedup_key()` exactly per ARCHITECTURE §4.3–4.4.
2. `db.py`: schema creation (idempotent), `insert_discovered(list[DiscoveredJob]) -> int`
   (returns count of genuinely new rows, implements the source-priority upgrade rule),
   `start_run()/finish_run()`, query helpers (`rows_by_status`, `get_by_url`).
3. `scripts/record_fixture.py`: given a URL and output name, fetch and save raw response
   body + headers to `tests/fixtures/`.
4. `discover/tracker_vansh.py` per ARCHITECTURE §5.2, including: JSON-listings probe,
   README-table fallback parser, `↳`/inherited-company handling, closed-row skipping,
   snapshot diffing. Verify the repo's real default branch and table columns against the
   live repo ONCE during development; record findings in `docs/DECISIONS.md`; save the real
   README as a fixture.
5. Wire into `run_ingest.py`: `--source tracker_vansh --discover-only --limit N` works
   end-to-end (discover → insert → print summary).

Acceptance criteria:
- Unit tests: `norm`/`dedup_key` (≥ 8 cases incl. req-ID stripping, `↳` inheritance, suffix
  stripping, remote-location collapsing); README parser against the fixture (row count > 0,
  spot-check 3 known rows); snapshot diff (fixture A then fixture A+2 rows → exactly 2 new).
- Integration: `insert_discovered` called twice with the same list → second call returns 0.
- Live smoke (run manually, not in pytest): first real run with `--limit 25` inserts ≤ 25
  rows; immediate second run inserts 0.

## M2 — Resolution layer

Tasks:
1. `resolve/base.py`: polite session per ARCHITECTURE §6.2; shared HTML→text helper.
2. Resolvers in this order: greenhouse, lever, ashby, workday, generic — each with a recorded
   fixture (use `record_fixture.py` on real postings found in the M1 data; pick postings
   likely to stay up a while, and note in the fixture filename the source URL).
3. Router incl. redirect-then-route behavior (fixture: a simplify.jobs shortener redirect —
   if recording one is impractical, unit-test the routing function on final URLs and note it).
4. `run_ingest.py --resolve-only`: processes `DISCOVERED` rows, updates status /
   `resolve_attempts` / `RESOLVE_FAILED` at 3, backfills placeholder company/title for inbox
   rows from `ResolvedJD.raw_*`.

Acceptance criteria:
- Each resolver: fixture test asserting non-empty `jd_text` with expected substring, and a
  malformed-response test returning `None` (not raising).
- Generic resolver: passes the ≥400-chars + keyword heuristic on a real careers-page fixture;
  returns `None` on a nav-shell fixture.
- Rate limiter test: two calls to same host sleep ≥ 2 s apart (mock time).
- Live smoke: resolve the M1 rows; report success rate. Expected ballpark ≥ 70%. If lower,
  list the failing domains for the user rather than adding new resolvers unprompted.

## M3 — Remaining discovery adapters + manual inbox

Tasks:
1. Extract the shared tracker logic from M1 into a helper; add `tracker_simplify.py`
   (probe `.github/scripts/listings.json` first — it exists for this repo; parse its schema
   after inspecting a fixture) and `tracker_jobright.py` (repos list from config; README
   parsing; verify live shape once, record decisions + fixtures).
2. `inbox_manual.py` per ARCHITECTURE §5.3 including `processed/` moves and `urls.txt`
   rewriting.
3. `discover_all()` registry with per-adapter exception isolation.

Acceptance criteria:
- Simplify adapter: fixture test on `listings.json` (parse ≥ 1 known entry).
- Jobright adapter: fixture test on one repo README.
- Inbox: tmp-dir test — one URL line + one MD paste file in, two rows out (MD row already
  `RESOLVED`, `resolver='manual'`), files moved to `processed/`, second run ingests nothing.
- Cross-source dedup test: same job from two trackers → one row, source upgraded per priority.
- Adapter isolation test: an adapter that raises doesn't prevent others from returning rows.

## M4 — Pre-filter, digest, full pipeline, scheduling

Tasks:
1. `prefilter.py` per ARCHITECTURE §7 (include-OR semantics, exclude, location, years_cap
   conservatism, flags-not-filters for sponsorship).
2. `digest.py` per ARCHITECTURE §8.
3. `run_ingest.py` default full chain + `--dry-run`; `runs` accounting correct.
4. Ask the user their OS and daily run time; implement the matching scheduler install script
   per ARCHITECTURE §10; document uninstall in the script's header comment.

Acceptance criteria:
- Prefilter unit tests: ≥ 10 titles covering include/exclude/edge ("Senior New Grad Program"
  → excluded; "Software Engineer I" → included); years_cap: "minimum 5 years" filtered,
  "5 years is a plus" NOT filtered; sponsorship phrase → flag set, status still RESOLVED.
- Digest golden-file test: seeded DB → digest matches expected markdown (allow timestamp
  placeholders).
- Idempotency test (the big one): temp DB, run full pipeline twice on fixtures; assert second
  run `new_jobs=0` and jobs-table contents byte-identical except permitted resolve retries.
- Live smoke: full run end-to-end; user reads the digest and confirms it's legible and correct.

## M5 — Phase-2 scaffolding (scoring I/O contract only)

Tasks:
1. `scripts/export_batch.py` and `scripts/import_scores.py` per ARCHITECTURE §11, with JSON
   schema validation (stdlib `json` + manual checks; no new deps) and score-threshold →
   `SHORTLISTED` transition (threshold in `config/filters.yaml`, default 7.0).
2. `config/profile_summary.md`: assemble a ~1-page profile summary. Source material: the
   user's resume variants (ask the user to place them in `profile/` first). Summarize
   factually; invent nothing.
3. A documented prompt template `docs/scoring_prompt.md` that the user will run via
   `claude -p` — instructing the model to read the batch file and profile summary and write
   the scored file in the exact schema. (Writing the template is M5; running it is the
   user's dry-run activity.)

Acceptance criteria:
- Round-trip test: export a seeded batch → hand-write a valid scored file → import → statuses
  and scores correct; invalid file (bad id, score out of range, missing field) rejected with
  a clear message and zero DB changes.
- `jd_text` truncation to ~6k chars verified in export.

## Phase 3 (separate track, after dry runs)

Tailoring per `docs/TAILORING_SPEC.md`: master profile construction, tailor + critic prompts,
diff-based output, taste feedback loop. Do not start until the user has reviewed at least one
week of real digests and several manual scoring dry-runs — the spec depends on their feedback.
