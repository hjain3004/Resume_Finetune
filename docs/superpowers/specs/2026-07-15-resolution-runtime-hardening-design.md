# M6.10 Resolution Runtime Hardening Design

**Status:** Approved for implementation on 2026-07-15. This design addresses the runtime
failures exposed while clearing the post-M9D-0 resolution backlog. It does not change
discovery coverage, scoring, calibration semantics, or tailoring.

## Problem

The live backlog-clear revealed four coupled runtime defects:

1. `run_resolution()` catches any resolver exception and converts it to `None`; the normal
   failure path then increments `resolve_attempts`. A transient connection reset, Playwright
   launch timeout, or programming defect can therefore permanently produce
   `RESOLVE_FAILED` after three runs.
2. `resolve/browser.py` opens a new `AsyncWebCrawler` and event loop per URL. Hundreds of
   browser candidates cause repeated Chromium startup, resource churn, and long launch
   timeouts.
3. Resolution has no separate work limit. A `--resolve-only` invocation attempts every
   `DISCOVERED` row, turning a smoke run into a multi-hour production operation.
4. `finish_run()` and `run_sources` accounting happen only after the full resolution loop
   returns. A crash leaves durable per-job mutations but an unfinished run with zero
   counters.

Jobright magnifies the browser problem: it renders the page to look for an original ATS
link before accepting the static `__NEXT_DATA__` payload that is already sufficient for an
aggregator-quality resolution.

## Scope

M6.10 implements only:

- typed orchestration outcomes;
- correct retry-budget semantics;
- bounded deterministic resolution;
- a persistent run-scoped browser client and circuit breaker;
- static-first Jobright fallback;
- partial/aborted run finalization and diagnostics;
- offline tests, documentation, and a user-supervised bounded smoke run.

M6.10 explicitly excludes:

- calibration-report or scoring-prompt changes;
- nested `claude -p` diagnostics;
- new ATS resolvers, Crawlee, Apify, or any new dependency;
- M9D-1 through M9D-5;
- M8 tailoring;
- automated modification or reset of existing live DB rows.

## Outcome contract

Add `src/resolve/outcomes.py` with:

- `ResolutionOutcomeKind`: `RESOLVED`, `CONTENT_FAILURE`, `TRANSIENT_FAILURE`,
  `INTERNAL_ERROR`;
- immutable `ResolutionOutcome` containing `kind`, optional `ResolvedJD`, `reason_code`,
  and a bounded diagnostic message;
- constructors that reject invalid combinations, such as `RESOLVED` without a result.

The existing individual resolver modules may continue to return `ResolvedJD | None`.
`None` means the page was fetched/processed but did not yield acceptable content and becomes
`CONTENT_FAILURE`. Known transport/browser-boundary exceptions become
`TRANSIENT_FAILURE`. The final orchestration catch turns an unexpected exception into
`INTERNAL_ERROR`, logs a full traceback, and continues to the next row.

Only `CONTENT_FAILURE` calls `db.record_resolve_failure()`. Transient and internal outcomes
leave `status` and `resolve_attempts` unchanged. Manual-domain behavior remains unchanged:
it is policy-routed directly to the existing manual failure path.

## Browser lifecycle

Replace per-call crawler construction in the production path with a `BrowserClient`
protocol and a `Crawl4AIBrowserClient` implementation:

- one dedicated event loop and `AsyncWebCrawler` per resolution run;
- explicit `start()`, `crawl(url)`, and `close()` lifecycle;
- the same `CacheMode.BYPASS`, quality heuristic, and host throttle as today;
- no concurrency in M6.10, preserving the existing ≥2-second per-host etiquette;
- no LLM extraction, stealth, login, CAPTCHA, or bot-evasion behavior.

The first browser lifecycle failure opens a run-local circuit breaker. Later rows that need
the browser receive `TRANSIENT_FAILURE(reason_code="browser_unavailable")` without another
launch attempt. Tier-1 resolution continues normally. Browser page results that explicitly
report unsuccessful/blocked content remain `CONTENT_FAILURE`; infrastructure inability to
start or operate the browser is transient.

Unit tests inject a fake `BrowserClient`; pytest never starts Playwright or accesses the
network. Compatibility one-shot helpers may remain only for isolated/manual callers, but
`run_ingest` must always pass the run-scoped client when browser resolution is enabled.

## Jobright ordering

Jobright resolution order becomes:

1. inspect static HTML for an ATS/apply link and use it if found;
2. parse static `__NEXT_DATA__` and return aggregator-quality content if valid;
3. only when both static paths fail, use the browser client to inspect the rendered DOM for
   an ATS/apply link;
4. otherwise return content failure.

This deliberately stops spending a browser launch on every valid Jobright aggregator row.
The existing digest continues to request an original posting for shortlisted
aggregator-quality rows.

## Bounded orchestration and run accounting

Add `--resolve-limit N` with positive-integer validation. It limits only the ordered
`DISCOVERED` rows selected for resolution and is independent of discovery `--limit`.

Introduce a mutable, typed `ResolutionSummary` owned by `main()` and updated after each row.
It contains resolved/content-failed/transient/internal counts, tier counts, per-source
counts, and a bounded list of structured issues. This lets `main()` finalize the run in a
`finally` block even when interrupted before `run_resolution()` returns.

Run notes remain JSON and merge discovery issues with:

- `run_outcome`: `completed` or `aborted`;
- `resolution_summary`: transient/internal counts and reason-code counts;
- `fatal_error`: type plus bounded message when aborted.

No schema migration is required. `run_sources` partial resolved/failed counters and
`runs` counters are written from the summary before `finish_run()`. An interrupted run is
re-raised after finalization so the CLI still exits nonzero.

Historical runs 12/13 and rows modified by prior backlog attempts are not rewritten by the
implementation. After tests pass, the implementer reports the live state and asks the user
before any administrative cleanup or smoke run.

## Acceptance criteria

- A `requests` connection exception is transient, does not increment attempts, and does not
  prevent the next row resolving.
- A browser startup/operation exception is transient and opens the circuit breaker; later
  browser-required rows do not attempt another startup.
- An unexpected resolver exception is logged with traceback, recorded as internal, does not
  consume attempts, and does not stop later rows.
- A resolver returning `None` still consumes exactly one content-failure attempt and becomes
  `RESOLVE_FAILED` on the third content failure.
- `--resolve-limit 2` processes exactly the two lowest-id eligible rows.
- Multiple browser-required rows use one browser client start/close lifecycle.
- Valid static Jobright `__NEXT_DATA__` produces an aggregator resolution without calling
  the browser client.
- An interrupted run receives `finished_at`, partial counters, per-source counters, and
  structured aborted notes; the interrupt still propagates.
- All tests remain offline and `pytest -q` passes.
- The user approves and observes a bounded live smoke before M6.10 is committed as complete.
