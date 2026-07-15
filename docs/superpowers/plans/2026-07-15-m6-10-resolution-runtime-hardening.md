# M6.10 Resolution Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make resolution bounded and crash-tolerant without allowing transient infrastructure failures to consume a job's content-failure budget.

**Architecture:** Preserve existing individual resolver contracts while adding a typed outcome boundary in orchestration. Production resolution owns one run-scoped Crawl4AI browser client with a circuit breaker, processes a deterministic limited row set, and finalizes partial run accounting in `finally`.

**Tech Stack:** Python 3.11+, stdlib, requests, crawl4ai, Playwright as already transitively installed, PyYAML, pytest.

## Global Constraints

- Implement M6.10 only; do not start calibration-contract fixes, nested-scorer fixes, M9D-1, or M8.
- Add no dependency and no schema migration.
- Tests never touch the network or launch a browser.
- Preserve ≥2 seconds between requests to the same host and all existing scraping-etiquette rules.
- Raw SQL stays in `src/db.py`.
- Preserve the user's pre-existing `tests/test_scoring_stress.py` modification and the untracked incident report.
- Do not mutate `data/jobs.db`, stop/start background processes, or run a live smoke without asking the user.
- Use TDD: failing targeted test, minimal implementation, targeted pass, then full suite.

---

## File Structure

**Create**

- `src/resolve/outcomes.py` — typed resolution outcome and summary contracts.
- `tests/test_resolve_outcomes.py` — outcome invariant tests.

**Modify**

- `src/db.py` — deterministic limited status query helper only; no migration.
- `src/resolve/browser.py` — injectable persistent browser client and circuit breaker errors.
- `src/resolve/__init__.py` — produce typed outcomes at the router boundary and accept a browser client.
- `src/resolve/jobright.py` — static NEXT_DATA before rendered-browser fallback.
- `src/run_ingest.py` — `--resolve-limit`, summary accounting, per-row isolation, and finalization.
- `tests/test_db.py` — limited ordered query coverage.
- `tests/test_resolve_browser.py` — persistent lifecycle/circuit-breaker coverage with fakes.
- `tests/test_resolve_jobright.py` — static-first no-browser regression.
- `tests/test_run_ingest_resolve.py` — retry semantics, limits, summaries, continuation.
- `tests/test_run_ingest_lifecycle.py` — new interrupted-run finalization and CLI validation coverage.
- `docs/ARCHITECTURE.md` — convert M6.10 target text to implemented behavior after acceptance.
- `docs/ROADMAP.md` — mark M6.10 complete only after the user-supervised smoke.
- `docs/DECISIONS.md` — record final implementation details and approved deviations.

## Task 1: Typed outcome and summary contracts

**Interfaces**

- Produces `ResolutionOutcomeKind`, `ResolutionOutcome`, `ResolutionIssue`, and
  `ResolutionSummary` in `src.resolve.outcomes`.
- `ResolutionSummary` exposes `record(row, outcome)` and retains mutable counters needed by
  `main()` during interruption.

- [ ] Write `tests/test_resolve_outcomes.py` covering valid constructors, rejection of a
  resolved outcome without `ResolvedJD`, bounded issue messages, and summary counts.
- [ ] Run `pytest tests/test_resolve_outcomes.py -q`; expect failure because the module does
  not exist.
- [ ] Implement the smallest typed dataclasses/enums satisfying those tests. Use this public
  shape (helper constructors may be classmethods):

  ```python
  class ResolutionOutcomeKind(str, Enum):
      RESOLVED = "resolved"
      CONTENT_FAILURE = "content_failure"
      TRANSIENT_FAILURE = "transient_failure"
      INTERNAL_ERROR = "internal_error"


  @dataclass(frozen=True)
  class ResolutionOutcome:
      kind: ResolutionOutcomeKind
      result: ResolvedJD | None = None
      reason_code: str | None = None
      message: str | None = None


  @dataclass(frozen=True)
  class ResolutionIssue:
      job_id: int
      url: str
      kind: ResolutionOutcomeKind
      reason_code: str
      message: str


  @dataclass
  class ResolutionSummary:
      resolved: int = 0
      content_failed: int = 0
      transient: int = 0
      internal: int = 0
      tier1: int = 0
      tier2: int = 0
      manual: int = 0
      per_source: dict[str, dict[str, int]] = field(default_factory=dict)
      issues: list[ResolutionIssue] = field(default_factory=list)
  ```

  Enforce `RESOLVED` iff `result is not None`; truncate stored messages to 500 characters.
  Do not include DB or browser behavior in this module.
- [ ] Re-run the targeted test; expect pass.
- [ ] Commit only this task as `feat(m6.10): add typed resolution outcomes`.

## Task 2: Deterministic bounded DB selection and CLI flag

**Interfaces**

- Add `db.rows_by_status(conn, status, *, limit: int | None = None)` with `ORDER BY id` and a
  parameterized `LIMIT` path when provided.
- Add `--resolve-limit N`; reject values below 1 through `argparse` validation.

- [ ] Add tests proving unordered insertion is returned by id and a limit of two returns
  exactly two rows. Add CLI parser tests for `1` accepted and `0` rejected.
- [ ] Run the targeted DB/parser tests; expect failure.
- [ ] Implement the query with these two SQL paths inside `src/db.py` and a small argparse
  validator in `src/run_ingest.py`:

  ```python
  def rows_by_status(
      conn: sqlite3.Connection, status: str, *, limit: int | None = None
  ) -> list[sqlite3.Row]:
      if limit is None:
          return conn.execute(
              "SELECT * FROM jobs WHERE status = ? ORDER BY id", (status,)
          ).fetchall()
      return conn.execute(
          "SELECT * FROM jobs WHERE status = ? ORDER BY id LIMIT ?", (status, limit)
      ).fetchall()


  def _positive_int(value: str) -> int:
      parsed = int(value)
      if parsed < 1:
          raise argparse.ArgumentTypeError("must be >= 1")
      return parsed
  ```

  Register `--resolve-limit` with `type=_positive_int`, and do not change discovery
  `--limit`.
- [ ] Thread the parsed value only as far as the `run_resolution()` call; behavioral use is
  completed in Task 5.
- [ ] Run targeted tests and commit as `feat(m6.10): bound deterministic resolution work`.

## Task 3: Persistent browser client and circuit breaker

**Interfaces**

- Add a `BrowserClient` protocol with synchronous `start()`, `crawl(url)`, and `close()`.
- Add `Crawl4AIBrowserClient`, owning one event loop and one `AsyncWebCrawler`.
- Add `BrowserUnavailableError` for lifecycle/start/operation failures.
- `fetch_markdown`, `fetch_html`, and `resolve` accept an injected `BrowserClient`.

- [ ] Rewrite/add browser tests using a fake client. Prove two fetches share one start and
  close, unsuccessful crawl results remain content failures, and a lifecycle exception is
  surfaced as `BrowserUnavailableError`. No real browser may start.
- [ ] Run `pytest tests/test_resolve_browser.py -q`; expect failures.
- [ ] Implement explicit lifecycle using this interface and ownership model. Preserve
  throttle, `CacheMode.BYPASS`, and the existing quality heuristic:

  ```python
  class BrowserClient(Protocol):
      def start(self) -> None:
          raise NotImplementedError

      def crawl(self, url: str) -> CrawlResult:
          raise NotImplementedError

      def close(self) -> None:
          raise NotImplementedError


  class BrowserUnavailableError(RuntimeError):
      pass


  class Crawl4AIBrowserClient:
      def __init__(self) -> None:
          self._loop = asyncio.new_event_loop()
          self._crawler: AsyncWebCrawler | None = None
          self._started = False
          self._unavailable_reason: str | None = None

      def start(self) -> None:
          if self._started:
              return
          if self._unavailable_reason is not None:
              raise BrowserUnavailableError(self._unavailable_reason)
          try:
              self._crawler = AsyncWebCrawler()
              self._loop.run_until_complete(self._crawler.start())
              self._started = True
          except Exception as exc:
              self._unavailable_reason = f"{type(exc).__name__}: {exc}"
              raise BrowserUnavailableError(self._unavailable_reason) from exc

      def crawl(self, url: str) -> CrawlResult:
          self.start()
          assert self._crawler is not None
          try:
              return self._loop.run_until_complete(
                  self._crawler.arun(
                      url=url,
                      config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS),
                  )
              )
          except Exception as exc:
              self._unavailable_reason = f"{type(exc).__name__}: {exc}"
              raise BrowserUnavailableError(self._unavailable_reason) from exc

      def close(self) -> None:
          try:
              if self._crawler is not None and self._started:
                  self._loop.run_until_complete(self._crawler.close())
          finally:
              self._loop.close()
              self._started = False
  ```

  Keep cleanup idempotent. If Crawl4AI's installed public API differs from this skeleton,
  stop and show the user the exact local signature before deviating, per `AGENTS.md`.
- [ ] Add a small run-local circuit-breaker wrapper/state: after the first
  `BrowserUnavailableError`, later browser calls fail immediately with reason
  `browser_unavailable` and never call `start()`/`crawl()` again.
- [ ] Run browser tests and commit as `feat(m6.10): reuse browser lifecycle per run`.

## Task 4: Static-first Jobright resolution

**Interfaces**

- `jobright.resolve(url, html_text, session, *, browser_resolver=False,
  browser_client=None)` checks static ATS, then static NEXT_DATA, then rendered ATS.

- [ ] Add a regression test with valid `__NEXT_DATA__`, no static ATS link, and a browser
  fake that raises if called. Expect an aggregator-quality `ResolvedJD` and zero browser
  calls.
- [ ] Add a test proving rendered fallback still runs when neither static path succeeds.
- [ ] Run `pytest tests/test_resolve_jobright.py -q`; expect the no-browser test to fail.
- [ ] Reorder the implementation minimally and thread the injected browser client through
  the router. The control flow must be equivalent to:

  ```python
  ats_link = find_ats_link(html_text)
  if ats_link:
      return _resolve_ats_link(url, ats_link, session)

  job = _extract_job_result(html_text)
  if job is not None:
      return _resolved_from_jobright_payload(url, job)

  if browser_resolver and browser_client is not None:
      rendered_html = browser.fetch_html(url, session, browser_client)
      ats_link = find_ats_link(rendered_html or "")
      if ats_link:
          return _resolve_ats_link(url, ats_link, session)
  return None
  ```

  Extract private helpers only where needed to avoid duplicating the existing result
  construction.
- [ ] Run Jobright and router tests; commit as
  `fix(m6.10): resolve static Jobright payload before browser`.

## Task 5: Correct retry-budget semantics and per-row continuation

**Interfaces**

- Add a router/orchestration function returning `ResolutionOutcome` while retaining
  individual resolver `ResolvedJD | None` contracts.
- `run_resolution(conn, session, *, browser_resolver=False, resolve_limit=None,
  browser_client=None, summary=None)` records outcomes.
- Only `CONTENT_FAILURE` calls `db.record_resolve_failure()`.

- [ ] Change the existing network and Playwright-timeout regression tests: their rows must
  remain `DISCOVERED` with `resolve_attempts == 0`, while the next row resolves.
- [ ] Add an unexpected-exception test using `caplog`: full traceback is logged, attempts
  remain zero, an internal issue is recorded, and the next row resolves.
- [ ] Retain/prove the existing `None` behavior: attempts increase and the third content
  failure becomes `RESOLVE_FAILED`.
- [ ] Add `resolve_limit=2` behavior coverage over three rows.
- [ ] Run targeted tests; expect failures against the current broad-catch behavior.
- [ ] Implement a typed router wrapper with this boundary:

  ```python
  def attempt(
      url: str,
      session,
      *,
      browser_resolver: bool = False,
      browser_client: BrowserClient | None = None,
  ) -> ResolutionOutcome:
      try:
          result = resolve(
              url,
              session,
              browser_resolver=browser_resolver,
              browser_client=browser_client,
          )
      except requests.exceptions.RequestException as exc:
          return ResolutionOutcome.transient("http_transport", exc)
      except BrowserUnavailableError as exc:
          return ResolutionOutcome.transient("browser_unavailable", exc)
      return (
          ResolutionOutcome.resolved(result)
          if result is not None
          else ResolutionOutcome.content_failure("no_acceptable_content")
      )
  ```

  `run_resolution()` calls `attempt()`. Its final `except Exception` calls
  `logger.exception("unexpected resolve error for row %s (%s)", row["id"], row["url"])`,
  constructs `ResolutionOutcome.internal("unexpected_exception", exc)`, and continues.
  Only the `CONTENT_FAILURE` branch calls `db.record_resolve_failure()`; manual-domain logic
  remains its existing explicit branch.
- [ ] Run all resolution tests; commit as
  `fix(m6.10): separate transient and content resolution failures`.

## Task 6: Reliable partial and aborted run finalization

**Interfaces**

- `main()` creates `ResolutionSummary` before resolution and finalizes from it in `finally`.
- Run notes remain valid JSON and include `run_outcome`, `resolution_summary`, and optional
  `fatal_error`, merged with existing discovery issues.
- The original exception/interrupt propagates after finalization.

- [ ] Add a test that patches resolution to record one success and then raise
  `KeyboardInterrupt`. Use a temporary DB and assert `finished_at`, partial counters,
  per-source counters, and `run_outcome="aborted"`; also assert the interrupt propagates.
- [ ] Add a completed-run test proving notes and counters remain correct without discovery
  issues.
- [ ] Run targeted main tests; expect failure because current finalization is after the
  vulnerable block.
- [ ] Refactor initialization/finalization into a single guarded lifecycle. Initialize all
  counters and the summary before the guarded work. Use this exception pattern without
  suppressing `KeyboardInterrupt`:

  ```python
  run_outcome = "completed"
  fatal_error: BaseException | None = None
  try:
      exit_code = _execute_run(
          args=args,
          conn=conn,
          run_id=run_id,
          resolution_summary=resolution_summary,
          browser_client=browser_client,
      )
  except BaseException as exc:
      run_outcome = "aborted"
      fatal_error = exc
      raise
  finally:
      # close the browser client first, then record partial run_sources and finish_run
      # from ResolutionSummary; merge structured notes without losing discovery issues
      finalize_run(
          conn,
          run_id,
          summary=resolution_summary,
          run_outcome=run_outcome,
          fatal_error=fatal_error,
          discovery_issues=discovery_issues,
      )
  ```

  Extract the current discovery/resolution/prefilter/audit body into `_execute_run()` with
  the shown keyword parameters; it returns the existing CLI exit code. Keep
  `finalize_run()` small and test it directly where that makes the interrupt test simpler.
- [ ] Run targeted tests and commit as
  `fix(m6.10): finalize interrupted resolution runs`.

## Task 7: Integration verification and documentation

- [ ] Run `pytest -q`; expected baseline is at least 414 passing plus the new tests.
- [ ] Run `git diff --check`; expect no whitespace errors.
- [ ] Inspect `git status --short` and confirm the user's pre-existing stress-test edit and
  incident report were neither staged nor modified by M6.10.
- [ ] Update `docs/ARCHITECTURE.md` M6.10 from TARGET to CURRENT with the exact implemented
  interfaces. Add a dated `docs/DECISIONS.md` entry describing any approved deviation from
  this plan.
- [ ] Do not mark the roadmap complete yet. Present test evidence and ask the user for
  approval to run a live smoke against `data/jobs.db` with a small explicit
  `--resolve-limit`.

## Task 8: User-supervised live smoke and completion

This task starts only after explicit user approval.

- [ ] Before mutation, record current status counts, unfinished runs, and copy the live DB
  to a timestamped backup without overwriting an existing backup.
- [ ] Confirm no other ingest/resolution process is active. If one is active, stop and ask
  the user; do not kill it unilaterally.
- [ ] Run a bounded smoke such as
  `python -m src.run_ingest --resolve-only --resolve-limit 5 --db data/jobs.db` while the
  user observes it.
- [ ] Verify the run finishes, counters are populated, no transient/internal outcome spent
  a retry attempt, and at most five eligible rows were processed.
- [ ] Run `pytest -q` again.
- [ ] Mark M6.10 COMPLETE in `docs/ROADMAP.md`, record smoke evidence in
  `docs/DECISIONS.md`, and commit remaining milestone files with
  `feat(m6.10): harden resolution runtime`.
- [ ] Stop. Do not begin the calibration-contract correction, M9D-1, or M8 in this session.
