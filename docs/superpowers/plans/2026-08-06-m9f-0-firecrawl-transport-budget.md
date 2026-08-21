# M9F-0 Firecrawl Transport and Budget Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the disabled-by-default integration for Firecrawl REST API, including a typed client, strict budget ledger, config integration, and Tier-2 selector, without altering production behavior (which remains on Crawl4AI). Remove the generic double-fetch bottleneck. This lays the shared substrate for M9F-2/3 regardless of the M9F-1 bake-off results.

**Architecture:** Firecrawl sits behind the generic Tier-2 boundary. A budget manager enforces constraints locally (monthly, daily, per-run, and purpose caps) using an atomic `usage-v1.json` ledger. The integration uses `requests` against `api.firecrawl.dev/v2` without external libraries or SDKs. `browser_backend` config handles legacy migration. 

**Tech Stack:** Python 3.11+, stdlib dataclasses/JSON/pathlib, existing `requests`, `pytest`. No new dependencies.

**Spec Reference:** `docs/superpowers/specs/2026-08-06-firecrawl-ingestion-integration-design.md`

## Prerequisites
- Working knowledge of the existing Tier-2 structure in `src/resolve/`.

## Global Constraints
- NO NEW DEPENDENCIES. Use the existing `requests`. Do not add `firecrawl-py` or CLI dependency.
- `playwright` remains an approved dependency (per Amendment A1) since it is required for `verify-sources --render` to work on JS-heavy company-bank sources. Do NOT attempt to remove it or Crawl4AI.
- `FIRECRAWL_API_KEY` comes from the environment only. Never write it to YAML, logs, artifacts, or SQLite.
- Tests never touch the network. Use saved fixtures and fakes.
- Do not mutate DB or config based on checks.
- Invalid `browser_backend` values must fail configuration loading BEFORE DB is created.
- `--dry-run` must never perform paid requests or reserve usage.
- Missing credentials cleanly disable Firecrawl without consuming `resolve_attempts`.
- `PoliteSession.throttle(url)` runs before any Firecrawl fetch.
- `proxy: basic` only.
- Implement M9F-0 only. M9F-1 (Bake-off), M9F-2/3 (Discovery), and M9D-1 are out of scope.
- Note on Bake-off Sizing (A6): M9F-1 must either raise the sample to 40-50 URLs or drop numeric thresholds in favor of human judgment. Do not implement M9F-1.

---

### Task 1: Measure Tier-2 Demand (Amendment A2)

**Files:** 
- Create: `scripts/measure_tier2_demand.py`

- [x] **Step 1: Write a read-only query script**
Write a script to query `jobs.db` reporting how many distinct job URLs reached the tier-2 generic route in the last 8 weeks, and how many failed to produce acceptable content.
- [x] **Step 2: Run the script and report numbers**
Run the script locally, read the report, and state whether the proposed 500 resolution credits/month cap in `config/firecrawl.yaml` is realistic. Do not change the cap yourself.

---

### Task 2: Configuration Contract and Backward Compatibility

**Files:**
- Modify: `config/sources.yaml` (ensure legacy behaviors)
- Create: `config/firecrawl.yaml`

- [x] **Step 1: Introduce `browser_backend` in sources loader**
Update config loading logic to handle `browser_backend: crawl4ai | firecrawl | off`. Implement backward compatibility (if `browser_backend` missing, map `browser_resolver: true` to `crawl4ai` and `false` or missing to `off`). Fail fast on invalid values.
- [x] **Step 2: Create `config/firecrawl.yaml`**
Create the config file exactly as spec section 7, adding `scrape.location` with `{"country": "US", "languages": ["en-US"]}` as per A3.
- [x] **Step 3: Test configuration**
Ensure tests check fail-fast behavior and backward compatibility.

---

### Task 3: Atomic Budget Ledger & Stale Reservation Cleanup

**Files:**
- Create: `src/firecrawl/budget.py` (or similar)
- Create: `scripts/clear_stale_reservations.py` (Amendment A4)
- Create: `tests/test_firecrawl_budget.py`

- [x] **Step 1: Implement Budget Ledger**
Implement atomic JSON replacement using `os.replace` and a lockfile for `data/firecrawl/usage-v1.json`. Enforce monthly, daily, per-run, and purpose limits based on `config/firecrawl.yaml`.
- [x] **Step 2: Dry-run and Error Handling**
Ensure `--dry-run` does not reserve usage. Treat unsupported/corrupt ledgers as fail-closed.
- [x] **Step 3: Stale Reservation Command (A4)**
Add a script `scripts/clear_stale_reservations.py` that lists non-final reservations older than a threshold (e.g., 2 hours) and prompts to clear them. Never clear them automatically.
- [x] **Step 4: Verify Tests**
Write extensive boundary tests for ledger logic without network access.

---

### Task 4: Typed Firecrawl REST Client

**Files:**
- Create: `src/firecrawl/client.py`
- Create: `tests/test_firecrawl_client.py`

- [x] **Step 1: Implement `Tier2Client` protocol and `FirecrawlScrapeResult` / `Tier2Page`**
Define strictly the request shape (Section 6) with `proxy: basic` and location sourced from config.
- [x] **Step 2: Environment and Safety**
Read `FIRECRAWL_API_KEY` exclusively from env. Redact keys from all logs and exceptions.
- [x] **Step 3: Circuit Breaking and Etiquette**
Implement `PoliteSession.throttle(url)` integration. Handle 401/403 (trip breaker), 429/timeout/5xx (transient trip).
- [x] **Step 4: Verify Tests**
Write offline tests using saved request/response fixtures to verify payload exactness and key redaction.

---

### Task 5: Generic Route Integration & Double-Fetch Removal

**Files:**
- Modify: `src/resolve/generic.py`, `src/run_ingest.py`
- Modify: `src/resolve/browser.py` (or similar entry point)

- [x] **Step 1: Remove generic double-fetch**
Remove the initial `session.get()` duplication by creating a pure extraction function over the already-fetched body in `generic.resolve()`.
- [x] **Step 2: Wire up Tier-2 Router**
Integrate `browser_backend` selection. If `firecrawl` is chosen, invoke the client through the budget ledger. Ensure failures do not silently retry on another backend.
- [x] **Step 3: Error Classification**
Budget exhaustion, cooldown deferral, and provider failures must not consume `resolve_attempts`. Unacceptable fetched content does.
- [x] **Step 4: Verify Tests**
Test router behavior, double-fetch removal, and error classifications with mocks.

---

### Task 6: Testing and Completion

- [x] **Step 1: Full offline suite**
Run `pytest -q` to ensure 100% green and zero network calls.
- [x] **Step 2: Secret Redaction Verification**
Confirm tests explicitly check that API keys never leak into logs or exceptions.
- [ ] **Step 3: Submit for Smoke Test Approval**
Stop and ask for explicit go-ahead for a user-supervised live scrape smoke. Do not proceed until approved.

## Status — 2026-08-21

The acceptance-contract repair (`fix(m9f-0): repair budget and tier-2 acceptance contracts`)
closed eight defects found by audit: per-run credits unenforced; credentials reserved before
validation; cleared reservations still counted; content reconciled before the quality gate;
dry-run fabricating a failed page; missing integrated coverage; duplicate tier-2 contracts;
observability below the approved design.

Offline verification is complete (`pytest -q`: 1151 passed, 1 deselected). **The
user-supervised live REST smoke has NOT run, so M9F-0 is not COMPLETE.** No Firecrawl request
was made and no credit was spent during the repair. `browser_backend` remains `crawl4ai`.

## Definition of Done
- Plan written and approved.
- A1 dependency choice documented.
- A2 demand query executed and reported.
- A4 explicit cleanup script added.
- All code delivered per design sections and amendments.
- `pytest -q` is fully green with no network calls.
- `browser_backend` remains `crawl4ai` in default configuration.
- Single user-supervised smoke run complete. **(OUTSTANDING — blocks M9F-0 completion.)**
- No M9F-1/2/3/M9D-1 tasks started.
