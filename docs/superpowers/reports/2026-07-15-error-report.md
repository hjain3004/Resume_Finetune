# job-pipeline — Error/Incident Report, 2026-07-13 → 2026-07-15

Compiled for cross-chat context handoff (Fable). Covers every distinct error,
crash, or defect encountered across the last two days of work: Phase 2
scoring-calibration rework and M9D-0 (discovery correctness baseline) plus
follow-on backlog-clearing work. Ordered chronologically within each category.
Repo: `job-pipeline`. All commit SHAs below are on `main`.

---

## RESOLVED vs UNRESOLVED — at a glance

**RESOLVED (8):**
- **1.1** — score_batch subprocess silent failure (missing permission flags) — fixed, then superseded entirely by 1.2's rework
- **1.2** — Trust-boundary violation (model had filesystem I/O authority) — fixed via full I/O-inversion rework
- **1.3** — Stress-suite band failures (6/10) — turned out to be a measurement artifact, not a defect; resolved by marking bands PROVISIONAL
- **1.4** — Run-to-run scoring non-determinism (2/30 threshold flips) — mitigated via k=3 self-consistency (residual 1/30 flip judged acceptable, see status note)
- **2.1** — Tracker snapshot-ahead-of-DB corruption — structurally fixed via prepare/commit checkpoint protocol (M9D-0)
- **2.2** — Premature RESOLVE_FAILED reopen (NULL last_seen_at) — fixed, regression-tested
- **2.3** — Backlog-resolution crash #1 (unhandled `ConnectionError`) — fixed, regression-tested
- **2.4** — Backlog-resolution crash #2 (unhandled Playwright `TimeoutError`) — fixed (commit `ac06f22`), regression-tested; the per-row catch around `resolve.resolve()` was broadened from `requests.exceptions.RequestException` to a bare `except Exception`, matching `discover_all()`'s existing per-adapter isolation

**UNRESOLVED (1):**
- **1.5** — score_batch nested-`claude -p` CLI flakiness (3 distinct crash modes across 4 live re-score attempts, even after a retry/backoff fix) — root cause never identified; user explicitly deprioritized further investigation (token cost) after the 4th failure. **No code fix exists for this.**

**Not a code issue:** 3.1 (transient Claude Code harness/Bash-tool unavailability) — infra-side, resolved itself on retry, no repo action needed.

---

## Category 1 — LLM scoring pipeline (Phase 2 calibration), 2026-07-13/14

### 1.1 `score_batch` silent failure: chunk scorer subprocess didn't write output
**When:** 2026-07-13, early session.
**Symptom:** `scripts/score_batch.py` produced `chunk_0.json` (the archived input)
but no `*.scored.json` output. No visible error initially.
**Root cause:** the nested `claude` CLI invocation (`claude -p`) was missing
`--permission-mode`/`--allowedTools` flags appropriate for a headless, non-interactive
context; the nested call was silently blocked on a permission prompt it could
never answer.
**Status:** Diagnosed same session. Initially "fixed" by adding
`--permission-mode acceptEdits` to `DEFAULT_CLAUDE_CMD` — this was later found to
be the wrong fix (see 1.2) and was reverted.

### 1.2 Trust-boundary defect: nested scorer had filesystem authority
**When:** 2026-07-13, ~11:49p–11:56p.
**Symptom:** Not a crash — an architecture review found that the `acceptEdits`
permission-mode fix from 1.1 gave the nested `claude -p` scorer real filesystem
read/write authority (it was being told to read the batch file and profile
summary and write its own output file). This violated the intended trust
boundary (`docs/ARCHITECTURE.md` §11: "Claude never touches the DB directly —
files in, files out, validation in between") and meant a compromised or
malfunctioning scorer prompt could write arbitrary files.
**Root cause:** `score_batch.py`'s original design let the model own file I/O
instead of the wrapper.
**Fix:** full I/O-inversion rework — the wrapper (`score_batch.py`) now embeds
the chunk JSON and profile summary directly into the prompt text, invokes
`claude -p` with **zero permission flags and zero tool access** (pure
text-in/text-out), reads only stdout, and owns every filesystem write itself.
`docs/scoring_prompt.md` was rewritten to match (template markers instead of
file-read instructions). `src/llm_trace.py` added as a mandatory audit-trail
helper (I11) for every LLM invocation.
**Status:** Fixed and committed (pre-dates the commits in this report's `git log`
window — committed before 2026-07-14 session start, part of `3ce63d5` and
earlier).

### 1.3 Scoring-stress synthetic band-adherence failures (6/10)
**When:** 2026-07-14, ~12:00a.
**Symptom:** `scripts/scoring_stress.py` (10 synthetic JD test cases in
`tests/fixtures/scoring_stress/cases.json`, each with an `expected_band`) showed
only 6/10 in-band after the I/O-inversion rework — cases `partial_overlap_adjacent_stack`,
`partial_overlap_ml_stretch`, `wrong_specialty`, `keyword_stuffed` landed just
outside their bands.
**Root cause:** NOT a scoring regression. Investigation found this was the
*first time this suite had ever produced output* (prior attempts died on a
file-permission bug, so there was no historical baseline to compare against),
and the `expected_band` values themselves were unvalidated pre-calibration
guesses by the implementer, not values derived from real user judgment.
**Fix:** Bands marked `"band_status": "PROVISIONAL"` per case (commit `dfa9855`);
the M8 gate's band-adherence condition was formally waived until real
calibration data exists to re-anchor the bands. Documented in `docs/DECISIONS.md`.
**Status:** Resolved (as a non-issue) — not a defect, a measurement artifact.

### 1.4 Run-to-run scoring non-determinism (real defect)
**When:** 2026-07-14, ~12:00a–8:00a.
**Symptom:** Re-scoring the identical 30-job 2026-07-12 batch twice, back to
back, with the (then) single-invocation-per-chunk scorer produced different
results: mean `|Δfit_score|` = 0.67, max `|Δ|` = 2.0, and **2/30 jobs crossed
the 7.0 shortlist threshold** between identical consecutive runs (id 42 Amazon
PXT, id 105 TikTok). id 105 additionally flipped `base_variant` (`backend` ↔
`ml`) between runs — a second axis of instability on the same job.
**Root cause:** inherent LLM sampling variance on a single scoring pass per job.
**Fix:** self-consistency scoring — each chunk is now scored `SELF_CONSISTENCY_K
= 3` times independently; results are combined via median `fit_score`,
majority-vote `base_variant`, and `missing_keywords`/`rationale` from the median
run (`scripts/score_batch.py`, commit `dfa9855`).
**Verification:** two live re-scores of the same batch with k=3 showed mean
`|Δ|` = 0.20 (down from 0.67), max `|Δ|` = 1.0 (down from 2.0), 1/30 threshold
flips (down from 2/30, though the one remaining flip — id 50 Paylocity — is a
*different* job than either original flip), and 0 `base_variant` flips (down
from 1). id 105 was frozen as a permanent regression fixture at
`tests/fixtures/variance_regression/tiktok_105.json`.
**Status:** Substantially mitigated, not eliminated. Documented in
`docs/DECISIONS.md` (2026-07-14 entry).

### 1.5 `score_batch` live re-scoring crashes (multiple distinct failure modes)
**When:** 2026-07-14, evening, across ~4 live re-score attempts of the
2026-07-12 batch (each doing 5 chunks × k=3 = 15 nested `claude -p` calls).
**Attempt 1:** Failed with `json.decoder.JSONDecodeError: Illegal trailing
comma before end of object` — chunk 1, one of the 3 runs returned JSON with a
stray trailing comma.
**Attempt 2 (retry):** Failed differently — `chunk 0 run 1 scoring failed (exit
1)`, **empty stderr**, no diagnostic information.
**Attempt 3 (retry):** Failed a third consecutive time, again with the
trailing-comma `JSONDecodeError`, on yet another chunk.
**Pattern:** 3 consecutive attempts, 3 different chunks failed, 2 different
failure modes — ruled out a specific-job-content trigger (chunk 3's actual JD
content, later inspected, was unremarkable). Most likely cause: the nested
`claude -p` CLI is intermittently flaky when invoked back-to-back at volume
(by that point in the session, 45+ nested invocations had run), possibly
rate-limiting, possibly an artifact of running `claude -p` recursively from
inside an already-active Claude Code session.
**Fix (implemented by a coworker, reviewed and committed by me, commit
`2c79c76`):** `_invoke_scorer_with_retry()` wraps each nested invocation in a
3-attempt loop with exponential backoff + jitter, catching non-zero exit,
empty stdout, and unparseable JSON. `parse_scoring_response()` tries strict
`json.loads` first and only falls back to a narrow trailing-comma repair
(`repair_trailing_commas()`) if that fails, then validates
`id`/`fit_score`/`base_variant` are present so a garbled-but-parseable response
fails at the invocation boundary (and retries) rather than deep inside
aggregation.
**Attempt 4 (post-fix retry):** Still failed — `chunk 3 run 1 scoring failed
after 3 attempts` — this time the retry loop itself exhausted all 3 attempts on
the *same* chunk, all with the identical silent `exit 1: <empty stderr>`
symptom, logged with backoff delays (2.2s, 4.5s) between attempts.
**Status:** **UNRESOLVED / ABANDONED BY USER DECISION.** After this 4th
failure, the user explicitly told me "no need to do the re-score thing, uses
up too many tokens" and to move on. The underlying flakiness in the nested
`claude -p` invocation (whatever its true cause) was never root-caused; the
retry/backoff mitigation reduces but does not eliminate its impact. **If this
resurfaces, the next diagnostic step would be running the nested `claude -p`
command manually/standalone against the exact failing chunk's prompt outside
the wrapper to capture real stderr/behavior, since the wrapper currently
surfaces empty stderr on this failure mode.**

---

## Category 2 — Discovery/ingestion pipeline, 2026-07-14/15

### 2.1 Tracker snapshot corruption (pre-existing defect, root-caused and fixed by M9D-0)
**When originally found:** 2026-07-12 (M7 weekly maintenance session, documented
in `docs/DECISIONS.md`). **Root-caused and structurally fixed:** 2026-07-14
evening (M9D-0).
**Symptom (original):** `tracker_vansh` silent for 4 runs; ~608 real postings
never inserted into the DB despite the on-disk snapshot marking them "seen."
**Root cause:** `tracker_common.diff_new_jobs()` (as it existed before M9D-0)
overwrote `snapshots/{source}.json` as a side effect **before**
`db.insert_discovered()` ran, and did so unconditionally on every call —
including direct interactive/debugging calls against the real `snapshots/`
directory. A crashed or partial run, or even just interactive inspection,
could mark jobs "seen" without ever inserting them.
**Immediate fix (2026-07-12):** deleted the corrupted snapshot, ran a real
backfill (discovered 639, inserted 583 new rows after intra-batch dedup).
**Structural fix (2026-07-14, M9D-0, commits `4cf2c6b`, `5a567d4`, `cc3cae2`):**
replaced the whole mechanism with a prepare/commit checkpoint protocol.
Adapters now return a pure `AdapterDiscovery(jobs, PendingCheckpoint)` with
**no side-effecting writes**. `run_ingest.persist_discovery()` inserts jobs into
the DB **first**, and only **after** that succeeds calls
`tracker_common.commit_checkpoint()`, which writes atomically (sibling temp
file + `os.replace`). A failed DB insert now makes zero checkpoint calls, so a
crash can never again get the snapshot ahead of the database. `--limit N`
truncation also no longer marks deferred jobs "seen" — they're tracked in a new
`pending_keys` set and stay eligible next run (this was a related bug: the old
`discover_all()` applied `--limit` *after* the adapter had already written the
full upstream key set to the snapshot).
**Status:** Fixed. 411 tests passing after the change (up from 391).

### 2.2 Reopen-cooldown bug: RESOLVE_FAILED rows reopened far ahead of schedule
**When found:** 2026-07-15, ~1:30a–2:00a, while investigating why the M9D-0
source-yield baseline showed `tracker_vansh` with 68 historical resolution
failures but the live DB showed **zero** current `RESOLVE_FAILED` rows for that
source.
**Symptom:** 21 real `tracker_vansh` rows (ids 3–24: Amazon, Roblox, Tesla,
Twitch, etc., originally `discovered_at: 2026-07-04`, failed resolution on
2026-07-08) were found with `flags: ["reopened"]`, `resolve_attempts: 0`,
`status: DISCOVERED` — i.e., their failure history had been silently wiped and
they'd been reset to look brand-new, only 4 days after failing, despite
`config/freshness.yaml`'s `reopen_days: 45` cooldown.
**Root cause:** `src/db.py`'s `_is_older_than(iso_ts, days, now_iso)` helper
returns `True` ("old enough to reopen") whenever `iso_ts` is `None` — i.e.
missing/unconfirmed is treated as "definitely stale enough." `last_seen_at` is
`NULL` for every row inserted before the M6.8 milestone added that column
(added via `ALTER TABLE`, so pre-existing rows got `NULL`, not a real
timestamp). So any pre-M6.8 `RESOLVE_FAILED`/`CLOSED` row got reopened on its
very next sighting after M6.8 shipped, regardless of the 45-day cooldown.
137 rows in the live DB currently have `last_seen_at IS NULL` and remain
vulnerable to this until fixed.
**Fix (commit `e7cb402`):** `insert_discovered()`'s reopen check now requires
`prior_last_seen is not None` before calling `_is_older_than()` — i.e., an
unknown last-seen time no longer implies "definitely overdue." `last_seen_at`
is unconditionally backfilled on every sighting regardless, so the *next*
sighting is judged correctly. The sibling `_is_older_than()` call site
(`stale_days` check on `date_posted` for brand-new rows) was deliberately left
unchanged — its "missing → treat as stale" semantics are a different,
intentional design choice, not a bug.
**Note:** the 21 already-reopened rows were **not** retroactively reverted —
they're simply back in the normal resolution queue now, which is harmless.
**Status:** Fixed and committed with a regression test
(`test_insert_discovered_does_not_reopen_resolve_failed_row_with_null_last_seen_at`).
413 tests passing.

### 2.3 Backlog-clearing resolution run — crash #1 (unhandled `ConnectionError`)
**When:** 2026-07-14, ~22:08–22:28 UTC (run id 12 in the `runs` table).
**Context:** After 2.1/2.2, the DB had a backlog of **1,047 jobs stuck in
`DISCOVERED`** because no resolution pass had run since 2026-07-08 (only
`--discover-only` runs happened on 2026-07-12). Started
`python -m src.run_ingest --resolve-only --db data/jobs.db` to clear it.
**Symptom:** the process died ~20 minutes in, having processed 181/1047 rows
(171 resolved, 10 newly resolve-failed), with an uncaught exception:
```
requests.exceptions.ConnectionError: ('Connection aborted.',
ConnectionResetError(54, 'Connection reset by peer'))
```
raised from `session.get(url)` inside `resolve.resolve()`
(`src/resolve/base.py:53`), propagating all the way up through
`run_resolution()` and killing `main()` entirely.
**Root cause:** `resolve.resolve()` (`src/resolve/__init__.py`) has **zero
exception handling** around its network call — unlike the discovery layer
(`discover_all()`), which already isolates per-adapter exceptions so one
broken source can't kill a run. One single transient network blip took down
progress on the other 866 unprocessed rows (though the 181 already-processed
rows were durably saved — no data corruption, just an unfinished run; `runs`
row id 12 has `started_at` but no `finished_at`, same pattern as prior
administratively-interrupted runs).
**Fix (commit `bf687e4`):** wrapped the `resolve.resolve()` call site inside
`run_resolution()` in a `try/except requests.exceptions.RequestException`,
logging a warning and treating it as a per-row resolve failure (retryable next
run) — the same isolation pattern `discover_all()` already applies per
adapter. Added a regression test
(`test_run_resolution_treats_network_exception_as_a_resolve_failure`).
413 tests passing (this fix's tests were included in the same commit
window as 2.2's).
**Status:** Fixed for this specific exception class — but see 2.4, the fix was
too narrow.

### 2.4 Backlog-clearing resolution run — crash #2 (unhandled Playwright `TimeoutError`) — **FIXED**
**When:** 2026-07-14 22:40 UTC – 2026-07-15 ~00:xx UTC (run id 13, resumed after
2.3's fix, PID 71936).
**Symptom:** the resumed run crashed again, after making only marginal
additional progress (roughly 3 more rows: `DISCOVERED` 866→863,
`RESOLVE_FAILED` 16→19). Uncaught exception this time:
```
playwright._impl._errors.TimeoutError: BrowserType.launch: Timeout 180000ms exceeded.
```
raised while trying to launch a headless Chrome-for-Testing instance via
Playwright — this is the **tier-2 browser resolver** path (Crawl4AI), invoked
as a fallback when a plain HTTP fetch fails for a generic (non-ATS-API) host.
**Root cause:** the 2.3 fix only caught `requests.exceptions.RequestException`
— i.e. only the tier-1 plain-HTTP path inside `resolve.resolve()`. But
`resolve.resolve()` also internally routes to `browser.resolve(url, session)`
(Playwright/Crawl4AI) for certain hosts, and that code path can raise entirely
different exception types (Playwright's own `TimeoutError`, and potentially
other Playwright/Crawl4AI exception classes) that are **not** subclasses of
`requests.exceptions.RequestException`. The narrow catch didn't cover this.
**Fix (commit `ac06f22`):** broadened `run_resolution()`'s catch around
`resolve.resolve()` from `requests.exceptions.RequestException` to a bare
`except Exception`, matching `discover_all()`'s existing per-adapter isolation
exactly — since `resolve.resolve()` can raise from requests, Playwright/
Crawl4AI, or any of the per-ATS resolver modules
(greenhouse/lever/ashby/workday/amazon_jobs/jobright/generic/wrapper), and new
resolver code could introduce yet other exception types in the future, no
narrower catch is safe here. Added a regression test using a plain
`TimeoutError` (standing in for Playwright's own exception type, to prove the
catch isn't requests-specific)
(`test_run_resolution_treats_non_request_exception_as_a_resolve_failure`).
The now-unused `requests` import was removed from `src/run_ingest.py`.
**Verification:** 414 tests passing.
**DB state as of this fix:** `runs` rows 12 and 13 both have `started_at` but
no `finished_at` (orphaned, harmless — same pattern as prior
administratively-interrupted runs). Status counts at the time of the fix:
`DISCOVERED` 863, `FILTERED_OUT` 288, `RESOLVED` 171, `SCORED` 27,
`RESOLVE_FAILED` 19, `SHORTLISTED` 18 — backlog-clear was ~18% complete
(184/1047 processed across both crashed runs) before being resumed a third
time.

---

## Category 3 — Tooling/infrastructure (not a job-pipeline code defect)

### 3.1 Bash tool transiently unavailable
**When:** 2026-07-15, while checking on the crashed run 13 / gathering data for
this report.
**Symptom:** a Bash tool call returned:
```
claude-sonnet-5 is temporarily unavailable, so auto mode cannot determine the
safety of Bash right now.
```
**Root cause:** infrastructure-side (Claude Code harness / auto-mode safety
classifier), unrelated to the job-pipeline codebase.
**Status:** Transient — the very next Bash call succeeded normally. No action
taken or needed on the repo side.

---

## Summary table

| # | Issue | Severity | Status |
|---|---|---|---|
| 1.1 | score_batch subprocess silent failure (permission flags) | High | Fixed (superseded by 1.2's rework) |
| 1.2 | Trust-boundary violation (model had file I/O authority) | High (security/architecture) | Fixed — I/O inversion, `docs/scoring_prompt.md` rewrite |
| 1.3 | Stress-suite band failures (6/10) | Low (measurement artifact) | Resolved — bands marked PROVISIONAL |
| 1.4 | Run-to-run scoring non-determinism, 2/30 threshold flips | Medium (data-quality) | Mitigated — k=3 self-consistency (1/30 flips remain) |
| 1.5 | score_batch nested-CLI flakiness (3 distinct crash modes across 4 attempts) | Medium | **Unresolved**, deprioritized by user (token cost) |
| 2.1 | Tracker snapshot-ahead-of-DB corruption | High (data-loss risk) | Fixed — prepare/commit checkpoint protocol |
| 2.2 | Premature RESOLVE_FAILED reopen (NULL last_seen_at) | Medium (data-quality) | Fixed, regression-tested |
| 2.3 | Backlog resolution crash #1 (ConnectionError) | High (run-killing) | Fixed, regression-tested |
| 2.4 | Backlog resolution crash #2 (Playwright TimeoutError) | High (run-killing) | Fixed — broadened to `except Exception`, regression-tested (commit `ac06f22`) |
| 3.1 | Bash tool transient unavailability | N/A (infra) | Transient, no action needed |

**Net open items carried forward:** only 1.5 (deprioritized by user, not
fixed). 2.4 is fixed as of commit `ac06f22`; the backlog-clearing run was
resumed a third time immediately after.
