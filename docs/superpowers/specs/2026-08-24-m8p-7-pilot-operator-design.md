# M8P-7 / M8P-8 — Pilot Operator and Three-to-Thirty Scale-Up Design

**Date:** 2026-08-24

**Status:** Approved for planning. M8P-7 implementation requires M8P-3R, M8P-4,
M8P-5, and M8P-6 merged. M8P-8 additionally requires the M8P-7 acceptance gate to
pass and decision D1 to be resolved.

**Phase:** 3 (M8 Tailoring)

**Umbrella:** `docs/superpowers/specs/2026-08-24-phase3-parallel-workstreams-design.md`

## 1. Goal

M8P-7 adds the join point that runs one job through the complete validated chain and
produces a reviewable resume, then executes the three-resume human pilot. M8P-8 runs
the same operator at scale — and only if the pilot's acceptance gate passes.

```
S1 → S0 → S2 → S3 → static G1 → G2 (≤2 rounds) → render + L7 → G3 packet → human feedback
```

M8P-7 is the first milestone in this project that makes live model calls for tailoring
and the first that produces a real resume PDF.

## 2. Fixed boundaries

- **One job at a time.** M8P-7 has no batch mode. M8P-8 adds a queue, but the queue
  executes one job to completion before starting the next.
- **No database mutation, ever, in either milestone.** No `TAILORED` status, no note,
  no flag, no score. The read-only `prepare_tailoring_request()` boundary is the only
  DB contact. (Umbrella decision D3.)
- **No automatic application submission.** The operator produces artifacts; a human
  applies. Nothing in this milestone may open a browser, fill a form, send an email,
  or contact an employer. This is a hard rule, not a default.
- Jobs 229 and 279 remain prohibited. Eligibility is re-checked from the live DB at
  the start of every run, never assumed from a previous session.
- No new dependency. No network beyond the model invocations the stage pipelines
  already own.
- Tests never call a model, the network, or `pdflatex`.
- `src/tailor/s3.py`, `g1.py`, `s3_pipeline.py`, `g2*.py`, `publish.py`, `g3.py`,
  `feedback.py`, `src/render/*`, and their tests are read-only. The operator composes
  the existing stage functions; it does not reimplement any stage.
- Every artifact is written under the gitignored `applications/` tree.

## 3. Operator design

`src/tailor/pilot.py` plus `scripts/tailor_pilot.py`.

### 3.1 Stage table

| Stage | Function composed | Model calls | Accepted artifact |
|---|---|---|---|
| `prepare` | `db.prepare_tailoring_request` (read-only) | 0 | `s1_request.json` |
| `s1` | `run_s1_invocation` | 1 | `s1_response.json` |
| `s0` | `run_s0_invocation` | 1 | `s0_response.json` |
| `s2` | `run_s2_invocation` | 1 | `s2_response.json` |
| `s3` | `run_s3_invocation` | 1 | `s3_bundle.json` |
| `g2` | `run_g2_loop` | 1–3 | `g2_bundle.json` |
| `render` | `render_and_publish` | 0 | `render_result.json` |
| `g3` | `publish_packet` | 0 | `packet.json` |

Total per application: **5–7 model calls**, matching the budget recorded in
`docs/superpowers/specs/2026-08-04-m8-live-tailoring-decisions.md`. The operator
reports the actual count; it does not assume it.

### 3.2 Artifact layout

```
applications/{company-slug}-{role-slug}/
├── run_manifest.json            # schema_version "m8p7.run_manifest.v1"
├── s1_request.json   s1_response.json
├── s0_request.json   s0_response.json
├── s2_request.json   s2_response.json
├── s3_request.json   s3_bundle.json
├── g2_request.json   g2_bundle.json
├── resume.tex        Himanshu_Jain_Resume.pdf
├── render_result.json  l7_report.json
└── review.md  packet.json  feedback_form.yaml
```

`run_manifest.json` records, per stage: `state ∈ {pending, complete, failed}`, the
outcome kind, the artifact path, the model-call count, the I11 trace paths, the
wall-clock duration, and the UTC ISO-8601 start/end timestamps. It also records the
`alignment_fingerprint` once S2 completes and a `prohibited_actions` block asserting
`db_mutations: 0` and `submissions: 0`.

The manifest is **not** the source of truth for whether a stage succeeded. Each stage's
own accepted artifact is. The manifest is rebuilt from the artifacts on every run, so a
corrupted or stale manifest cannot cause a stage to be skipped.

### 3.3 Resumability and idempotency

Before each stage the operator:

1. re-derives the stage's request from upstream artifacts;
2. if the accepted artifact exists, strictly parses it and compares its bound
   identity (`job_id` and, from S2 onward, `alignment_fingerprint`) with the
   re-derived request;
3. on match ⇒ `SKIPPED_COMPLETE`, no model call;
4. on mismatch ⇒ `CONFLICT`, stop the run, change nothing.

Consequences, all deliberate:

- Re-running a completed application costs zero model calls and produces byte-identical
  artifacts.
- Re-running after a mid-chain failure resumes at the failed stage.
- An upstream change (edited profile, edited prompt, changed JD) invalidates the
  fingerprint and the operator **refuses** rather than silently producing a hybrid
  resume from two different profiles.
- Feedback records are never touched by the operator. Re-running an application that
  already has feedback is allowed only with `--allow-rerun-after-feedback`, and even
  then it writes new artifacts under `applications/{slug}/rerun-{n}/` rather than
  overwriting the reviewed ones.

### 3.4 Failure diagnostics and rerun boundaries

Every failure prints: the stage, the typed outcome kind, the bounded (≤ 200 char)
diagnostic, the I11 trace path when raw output exists, and the exact command to retry
just that stage. The operator never retries automatically — every stage pipeline is
one-attempt by design, and a silent retry would double cost and hide a systematic
prompt defect.

`--stop-after STAGE` and `--only STAGE` exist so a failing stage can be iterated in
isolation without re-spending upstream calls.

### 3.5 Cost accounting

`run_manifest.json` and the CLI summary both report per-stage and total model calls
and wall-clock duration. `scripts/tailor_pilot.py cost --root applications` aggregates
across applications: total calls, calls by stage, mean calls per application, and the
G2 round distribution. This is the evidence base for later claims about whether the
loop is worth its cost, and it is the baseline M8X-1 must beat.

## 4. Selecting the three pilot jobs

The three jobs must exercise **meaningfully different resume behaviour**, not merely be
three rows. Criteria, applied in order, at execution time:

1. **Eligibility, re-checked live.** `status='SHORTLISTED'`, `jd_quality='ats'`,
   non-empty `jd_text`, `base_variant ∈ {backend, ml}`, id not in
   `PROHIBITED_TAILORING_JOB_IDS`. Never assume a previously eligible id still is.
2. **One row per distinct JD content group.** The current shortlist contains
   near-duplicate rows (five Palantir rows share a ~4.27 KB JD; two Citadel Securities
   rows share a 2.35 KB JD; two Cisco and two Notion rows are near-identical). Picking
   two rows from one group would produce two nearly identical resumes and prove
   nothing.
3. **Both base variants represented.** At least one `ml` and at least one `backend`,
   so variant selection and project swapping are both exercised.
4. **JD length spread.** One short (< 3 KB), one medium (5–8 KB), one long (> 12 KB).
   S1 extraction, coverage density, and the L3 keyword bounds all behave differently at
   different JD lengths, and the long JDs are where `must_have` term counts stress the
   "top five terms appear 2–3 times" rule.
5. **Domain distance spread.** At least one job whose domain is close to a profile
   project and at least one that is distant, so the S0 positioning brief and S2 domain
   affinity are visibly tested.
6. **At least one job expected to produce a `GAP`.** The gap path must be exercised
   before scaling, since gap handling is the system's only sanctioned response to a
   missing skill.

Applying these to the corpus verified on 2026-08-24 gives an *illustrative* set —
Cisco 119 (`ml`, ~13.4 KB, close domain), Notion 225 or ByteDance 283 (`backend`,
~6–7.5 KB), and Citadel Securities 213 or Atos 233 (`backend`, < 3 KB, distant
domain). **These are illustrations, not a commitment.** The operator's
`select --count 3` subcommand re-runs the criteria against the live DB read-only and
prints its choices with the reason for each, and the user confirms before any run.

The prior planning documents named jobs 119 / 225 / 211. Job 211's JD is 19 KB, which
would give two long JDs and no short one, so it is a weaker third pick than the short
distant-domain option — and its eligibility must be re-checked regardless.

## 5. M8P-7 execution protocol

1. `select --count 3` → the user confirms the three ids.
2. For each job, one at a time: `run --job-id ID --dry-run` first (proves the chain
   composes and reports the planned call count without spending anything), then
   `run --job-id ID`.
3. After each run the user reads `review.md`, opens the PDF, and fills
   `feedback_form.yaml`; `python -m scripts.tailor_g3 record` stores it.
4. If a run produces `open_flags` from G2, the packet says so in its warnings section
   and the user decides — the system does not retry.
5. After all three, `python -m scripts.tailor_g3 summarize` produces the gate
   statistics and `cost` produces the call accounting.
6. Taste incorporation: the user reviews `derive_taste_candidates` output and decides
   which lessons to append to `config/taste.md` and which literal terms to add to
   `config/banned_words.txt`. **This is the only point at which M8P-7 writes those
   files, and only under explicit user instruction.** Because both are PROTECTED
   prompt inputs, any change triggers a re-run of the three pilot jobs' G1 and G2 on
   the archived artifacts before further tailoring — the methodology's D2 drift
   discipline, applied at pilot scale.

## 6. The M8P-8 acceptance gate

M8P-8 does not begin because three runs *completed*. It begins when the user, looking
at the three feedback records, decides to scale — and the following minimum conditions
are met, computed from `data/feedback/index.jsonl` and the stored records:

| Condition | Threshold | Why |
|---|---|---|
| Runs reaching a built packet | 3 of 3 | A fail-closed chain cannot be scaled. |
| `unsupported_claims` entries, total | **exactly 0** | Fidelity is not a spectrum. This mirrors G2's `C1 == 3` rule: one fabricated or misleading claim at n=3 predicts many at n=30. |
| `would_submit == "yes"` | ≥ 2 of 3 | The system's actual purpose. `accept` alone is too weak a bar. |
| `needs_another_revision == "yes"` | ≤ 1 of 3 | More than one means the loop is not converging. |
| mean `visual_quality` | ≥ 2.0 | The PDF must be presentable, not merely valid. |
| mean `company_alignment` | ≥ 2.0 | Otherwise the tailoring is not tailoring. |
| L7 failures | 0 | A resume that fails L7 was never deliverable. |

Failing any condition means **fix, then re-run the three**, not proceed with a caveat.
The gate is recomputed by `scripts/tailor_pilot.py gate`, which prints each condition
with its computed value and a pass/fail, and exits non-zero if any fails. The user's
decision, and the gate output, are recorded in `docs/DECISIONS.md` at the M8P-7
closing commit.

## 7. M8P-8 — the thirty-resume dry run

### 7.1 The corpus does not exist yet

Verified 2026-08-24: the shortlist contains 16 `jd_quality='ats'` rows, one prohibited,
collapsing to **eight distinct JDs**. Thirty distinct eligible jobs cannot be sourced
from the current database, and the highest-scoring non-shortlisted ATS row is 5.5,
below the locked 6.0 threshold, so there is nothing to promote without re-scoring.

This is umbrella decision **D1** and it must be resolved before M8P-8 is scheduled.
The recommended resolution is to run the existing Phase 2 scoring chain
(`scripts/export_batch.py` → `scripts/score_batch.py` → `scripts/import_scores.py`)
over a slice of the 273 `RESOLVED` rows as a **separately approved maintenance step**
with a database backup taken first — because `import_scores.py` writes to SQLite and
this design otherwise permits no DB mutation.

M8P-8 cannot start until D1 is resolved and the eligible distinct-JD count is ≥ 30.

### 7.2 Queue execution

`run-batch --job-ids-file PATH --root applications [--limit N]`:

- executes one job to completion before starting the next;
- skips already-complete applications at zero cost via §3.3;
- writes a queue state file so an interrupted batch resumes exactly where it stopped;
- **circuit breaker:** aborts the batch when any of these fires — three consecutive
  runs end in a fail-closed outcome; any run produces an L7 failure; or the cumulative
  model-call count exceeds `--max-calls` (default `7 × remaining_jobs`). An abort
  leaves every completed application intact.

### 7.3 Human review at scale

Thirty two-minute reviews is roughly an hour of concentrated attention, and attention
degrades. The protocol is therefore three review batches of ten, each followed by
`summarize`, so a systematic defect is caught after ten resumes rather than thirty. If
batch 1's statistics fall below the §6 thresholds, the remaining twenty are not run
until the cause is fixed.

### 7.4 What M8P-8 produces

A labelled corpus of thirty feedback records bound to thirty fingerprinted drafts, plus
complete cost accounting. That corpus — not the resumes — is the input that makes
M8X-1 (SkillOpt) meaningful, and it is the deterministic baseline any future
optimization must beat.

## 8. Explicit non-goals

Neither milestone implements or starts: automatic application submission of any kind;
database mutation; the golden set or D2 drift harness beyond the pilot-scale re-run in
§5.6; gap aggregation into `data/digests/gaps.md`; `applications/by-date/` beyond the
simple `INDEX.md` regeneration M8P-7 adds; Company Bank integration or company-aware
tailoring; SkillOpt; M9D/M9F work; a web UI; or any dependency addition.

## 9. Acceptance criteria

**M8P-7:**

- The operator composes existing stage functions only; a test asserts it defines no
  parsing, validation, or hydration logic of its own.
- Every stage's skip/conflict/failure path is tested with mocked invocations.
- A completed application re-runs at zero model calls with byte-identical artifacts.
- A tampered upstream artifact produces `CONFLICT` and changes nothing.
- An application with stored feedback cannot be silently re-run.
- `select` is read-only, applies all six criteria, prints a reason per pick, and
  refuses to return two rows from one JD content group.
- `run --dry-run` makes no model call and writes no accepted artifact.
- `cost` and `gate` are read-only and produce exact numbers.
- No code path can submit an application; a test greps the operator for `requests`,
  `urllib`, `smtplib`, `webbrowser`, and browser automation imports and asserts none
  are present.
- Three live pilot runs complete with the user, feedback is recorded for all three,
  and the gate output is recorded in `docs/DECISIONS.md`.
- The production DB SHA-256 is unchanged after the pilot:
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.

**M8P-8:**

- D1 resolved and ≥ 30 distinct eligible JDs available, verified by a read-only query
  recorded in the milestone's decision entry.
- The §6 gate passes before the batch starts.
- The queue is resumable, idempotent, and circuit-broken.
- Review proceeds in three batches of ten with `summarize` between batches.
- Thirty feedback records exist, bound to thirty distinct fingerprints.
- Complete cost accounting is recorded as the deterministic baseline.
- No automatic submission occurred; no DB mutation occurred beyond the separately
  approved D1 scoring step.
