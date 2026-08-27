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

## Phase 3 (M8 and M10)

M8 item 1 (profile loader) and M8 item 2 (schema update and deterministic sections) are implemented. The prior item 3 tailor/critic code is a non-production skeleton and does not implement the live workflow.
The M8 phrasing rework is complete: base variants cut to 13 bullets on a measured one-page budget, phrasing lint wired in, and emphasis pipeline added.
M10 (renderer bake-off + L7 parseability gate) is complete: both arms were built, L7 parseability rules implemented, and LaTeX selected as the production renderer.

M8P-1 (2026-08-21) is complete: the validated S1 requirement-extraction contract, strict/semantic parser, protected S1 prompt, safe tool-disabled invocation wrapper, I11 tracing, read-only job-preparation DB boundary, and a narrow `prepare`/`invoke` CLI (`scripts/tailor_s1.py`). The legacy unsafe `src/tailor/wrapper.py` single-shot path is permanently disabled. See `docs/superpowers/specs/2026-08-21-m8-human-pilot-s1-design.md`.

M8P-2R (2026-08-23) repairs the premature M8P-2 closeout and is complete offline. It adds
canonical profile binding, observed experience-order validation, complete prompt contracts,
injection blocking, and the missing focused pipeline/CLI/integration coverage on top of the
JD-only S0 positioning and privacy-minimised
profile projections, strict S0/S2 contracts, deterministic S2 selection validation, safe
traced invocations, shared atomic artifacts, and the one-job `prepare`, `invoke-s0`,
`prepare-s2`, and `invoke-s2` CLI. The full suite is 1290 passed / 1 deselected. No live
model call, network, Company Bank data, database mutation, resume, or PDF was used or
produced. Jobs 119/225/211 passed eligibility and projection preflight only; they have no
accepted S1 artifacts and were not invoked. Next scoped increment: M8P-3 (S3 plus G1 L1/L4).
Phase 3, M8, and both human pilots remain incomplete.

M8P-3 (2026-08-24) is complete only through offline S3 and static G1. The seven
implementation/test commits are `07dce7f`, `9cf487a`, `7f94fa3`, `6fbf2ef`, `64fa048`,
`f488dd4`, and `9a1fd9c`; Task 8 documentation is closed separately. Focused verification
passed 34 tests and full verification passed 1330 tests with 1 deselected. The accepted
bundle preserves S2 structure and ownership, constrained bullet edits, numeric tokens,
skills, deterministic change log/diff, and `render_line_check="pending"`. G2, G3, final
rendering, rendered line checking, human pilots, and M8P-4 remain out of scope.

**M8P-3's closeout above was premature and was repaired as M8P-3R (2026-08-24); M8P-3
counts as complete only as of the repair.** The 34/1330-passing suite did not catch: an
unserializable bundle (`s3_bundle_to_dict()` used dataclass `.__dict__`, so no valid
response could ever publish); `run_static_g1()` checking only the bullet-id sequence, so a
fabricated bullet owner or an undeclared mutation to an unedited bullet's text/plain_text/
emphasis both passed `static_pass`; `run_s3_invocation()` catching bare `Exception` around
response parsing and mislabeling unrelated errors as `parse_failure`; and the plan's
required strict authoritative bundle parser never being built. Test coverage matched the
gaps: a one-test CLI file, a two-test integration file, and no G1 adversarial matrix.
Repair commits `e587c94` (bundle serialization, G1 owner/mutation binding, narrowed
exception handling, `parse_s3_bundle`), `a0d90f1` (CLI prepare failure matrix and
invoke/publish coverage), `a1864fa` (19-case G1 adversarial matrix), `c01f9ab` (expanded
integration coverage), and `e67aca1` (`HYDRATION_FAILURE` and no-retry pipeline coverage)
close every gap. Focused verification (`test_alignment_view.py`, `test_s3.py`, `test_g1.py`,
`test_s3_pipeline.py`, `test_tailor_s3_cli.py`, `test_m8p3_integration.py`) passed 85 tests;
full verification passed 1381 tests with 1 deselected. `data/jobs.db` checksum unchanged; no
live model call, network access, Company Bank use, database mutation, resume, or PDF
occurred in the repair session. `render_line_check` remains `"pending"`. G2, G3, final
rendering, PDF generation, Company Bank integration, human pilots, and M8P-4 remain
unstarted.

M8P-4 (2026-08-25) is complete offline: G2 anchored critic and bounded revision loop.
The seven implementation and test commits are `073ba9e` (G2 request/response contract and
structural parser), `f69e7b1` (verdict rule and finding resolution), `85d9f2b` (anchored G2
critic prompt), `1fe4ab6` (additive S3 revision context and scope validation), `68feec1`
(bounded G2 revision loop and bundle serialization), `5e8beb3` (fail-closed one-job G2 CLI),
and `84c5554` (adversarial integration coverage). Focused verification passed 52 tests
(`test_g2.py`, `test_g2_pipeline.py`, `test_s3_revision.py`, `test_tailor_g2_cli.py`,
`test_m8p4_integration.py`); full verification passed 1433 tests with 1 deselected (+52 net
tests over M8P-3R). The critic receives a diff-centred, privacy-minimised projection of the
accepted S3 bundle and closed rule vocabularies, anchoring every finding to an exact quoted
substring. Revisions re-invoke S3 under its existing bounded edit contract and re-run full
static G1 with edit budgets recomputed against the canonical alignment; G2 never emits
replacement resume text. `data/jobs.db` checksum unchanged. Deterministic tailored rendering,
L7, `render_line_check`, G3, Company Bank integration, and both human pilots remain incomplete.
Phase 3, M8, and human pilots remain uncompleted.

M8P-5 (2026-08-25) is complete offline: deterministic tailored render, rendered line check, tailored L7 execution, and atomic publication. The five implementation and test commits on the feature branch (prior to rebase) were `66fc58c` (draft-to-RenderDoc mapping and fingerprint binding), `1da364b` (PDF line and font geometry extraction), `c0d3a92` (rendered line counts and tailored L7 risks), `f59976b` (atomic per-application publication), and `1515be3` (bundle-driven render CLI). Branch verification passed 1425 tests (44 new tests); post-rebase and post-merge verification on `main` passed 1477 tests with 1 deselected (1433 + 44). S3 bundle G1 report keeps `render_line_check="pending"`; real verdict is recorded in `render_result.json`. Published applications and `.tex` source live in gitignored `applications/` (D4). `data/jobs.db` checksum unchanged. G3 review packet, feedback capture, and both human pilots remain unstarted. Phase 3, M8, and human pilots remain incomplete.

M8P-6 (2026-08-26) is complete offline: the validated human-feedback contract and the deterministic G3 review packet. Tasks 1–3 (commits `bde360c` — validated feedback contract, `5f4d35f` — immutable append-only revision-numbered storage under `data/feedback/`, `7d5415e` — pure `derive_taste_candidates`) landed on `main` first; Tasks 4–6 (through `006346f` — G3 packet builder, Markdown renderer, and `scripts/tailor_g3.py`'s `build`/`record`/`summarize` CLI) followed as a separate branch (`m8p-6-packet`), rebased onto `main` and fast-forward merged as `450bf61` with no conflicts. `src/tailor/g3.py` derives `review.md` and `packet.json` entirely from already-validated S1/S0/S2/S3-bundle/G2-bundle/render-result artifacts, binding them by `alignment_fingerprint` and `job_id` and failing closed on any disagreement; it makes no model call, imports neither `src.tailor.invoke` nor `src.llm_trace`, and never writes `config/taste.md`, `config/banned_words.txt`, or `docs/prompts/`. Publication is idempotent (`ALREADY_BUILT` / `CONFLICT`, never an overwrite) and `review.md` is byte-identical across runs on identical inputs. Test counts: 31 feedback tests (`tests/tailor/test_feedback.py`); 21 packet/CLI tests (`tests/tailor/test_g3.py`, `tests/test_tailor_g3_cli.py`, `tests/test_m8p6_integration.py`); full suite 1529 passed, 1 deselected (up from the 1508/1 baseline). `data/jobs.db` checksum unchanged. G3 has no web UI — the review surface is a Markdown file plus a YAML form, not a server. Both human pilots, M8P-7 (pilot operator), and M8P-8 remain incomplete; no resume has yet been produced. Neither M8, Phase 3, nor any pilot is marked complete.

M8P-7 Tasks 1–5 of 9 (2026-08-27) are **partial**, on a separate branch (`m8p-7-operator`), rebased onto the post-M8P-6 `main` (cleanly dropping the two already-merged M8P-6 commits it had carried as its base) and fast-forward merged as `a3180a3` with no conflicts. The five commits are `1b8a593` (stage table and run manifest, rebuilt from artifacts every run and never trusted as the source of truth), `95414d2` (resumable, idempotent chain driver — S1→S0→S2→S3→static G1→G2→render+L7→G3 — composing existing stage functions only, with cost accounting and no automatic retry), `48e8edc` (read-only, deterministic pilot-job selection against the live SHORTLISTED corpus, `db.rows_by_status` only, no new SQL), `081ed20` (cost accounting and the seven-condition acceptance gate from design §6, `unsupported_claims` required to be exactly 0), and `a3180a3` (`scripts/tailor_pilot.py`'s `select`/`run`/`cost`/`gate`/`index` CLI). Focused verification (`tests/tailor/test_pilot.py`, `tests/test_tailor_pilot_cli.py`, `tests/test_m8p7_integration.py`) passed 52 tests; full suite passed 1581 with 1 deselected (up from the 1529/1 post-M8P-6 baseline; net +52). `data/jobs.db` checksum unchanged — the operator is read-only against SQLite (`get_readonly_connection` plus `db.prepare_tailoring_request`/`tailoring_base_variant`/`rows_by_status` only, no `.execute(` anywhere in operator code) and makes no model call, no network call, and no `pdflatex` call outside a mocked stage pipeline. **Tasks 6–9 still require:** Task 6, the live three-resume pilot session (user-only, not attempted); Tasks 7–9, the M8P-8 thirty-resume dry run (corpus preparation, a resumable batch queue with a circuit breaker, and the live batch run itself), all gated on the user's acceptance-gate decision after Task 6. No resume has yet been produced. Neither M8, Phase 3, nor any pilot is marked complete.

The approved Company Knowledge Bank supporting subsystem is split into three ordered tracks:

1. **Track A — Gemini foundation:**
   `docs/superpowers/plans/2026-08-04-m8-company-bank-foundation.md`
   Status: complete. Acceptance criteria:
   - Complete implementation of Track A offline foundation, including model, policy, and validation.
   - 100% test coverage.
   - No integration with live DB or web research.
2. **Track B — Claude Web research:**
   `docs/superpowers/plans/2026-08-04-m8-company-bank-web-research.md`
   Status: local research in progress. The approved seed corpus is 20 companies; 20/20
   ignored inbox bundles exist before Batches 5/6. These are staged research proposals,
   not canonical imports.
3. **Track C — Gemini seed-corpus adoption:**
   `docs/superpowers/plans/2026-08-04-m8-company-bank-adoption.md`
   Status: incomplete.

Source verification and rendered fallback are approved and implemented; the 2026-08-06
hardening repair closes fail-closed, redirect, throttling, report-output, and staging
boundary defects in that verifier. Track C canonical adoption, S0/S2/G3 integration, live
tailoring, CLI integration, and DB integration remain incomplete and require their own
scoped milestones/sessions. Track B writes ignored research proposals only.

---

## M6.14 — Collision-Safe Posting Identity & Targeted Priority Resolution

Status: COMPLETE (2026-08-27). Implements collision-safe identity contracts and targeted priority resolution.
Design: `docs/superpowers/specs/2026-08-27-m6-14-posting-identity-priority-resolution-design.md`
Plan: `docs/superpowers/plans/2026-08-27-m6-14-posting-identity-priority-resolution.md`

Tasks & Commits:
1. `feat(m6.14): add deterministic posting identity contracts` (`src/models.py`, `tests/test_models.py`) — `canonical_job_url`, `manual_url_dedup_key`, `stable_posting_identity`, `collision_dedup_key`, `DiscoveredJob.identity_key`.
2. `fix(m6.14): prevent cross-requisition dedup collisions` (`src/db.py`, `tests/test_db.py`) — `get_by_dedup_key`, collision key resolution in `insert_discovered`.
3. `fix(m6.14): give manual URLs collision-safe identities` (`src/discover/inbox_manual.py`, `tests/test_inbox_manual.py`) — fail-closed URL parsing, credential rejection, `InboxInputError`, `url_job_ids`.
4. `feat(m6.14): add exact targeted resolution selection` (`src/db.py`, `src/prefilter.py`, `src/run_ingest.py`) — `require_rows_by_ids_status`, `rows_by_ids_status`, scoped pre/post resolution gates.
5. `feat(m6.14): expose fail-closed priority resolution CLI` (`src/run_ingest.py`, `tests/test_run_ingest_lifecycle.py`) — `--resolve-job-id` flag, mutual exclusivity validation, pre-run status validation.

Acceptance criteria:
- Distinct manual URLs on the same hostname create separate DB rows under deterministic `manual_url_dedup_key`.
- Cross-requisition conflicts on identical semantic metadata create separate DB rows under `collision_dedup_key` without mutating the existing row.
- Whole-line `#` comments in `inbox/urls.txt` are ignored; fragments on URL lines are preserved.
- Sensitive query/fragment credentials raise `InboxInputError`, preserve `inbox/urls.txt`, and insert zero rows.
- `--resolve-job-id` requires `--resolve-only`, rejects invalid/duplicate/non-DISCOVERED IDs with exit code 1 before `db.start_run()`, and resolves only targeted jobs with scoped pre/post eligibility gates.
- Full pytest suite 1622 passed, 1 deselected, 0 failures. No live network or model calls.

