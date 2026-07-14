# Hybrid Discovery v2 — Design

**Status:** APPROVED design, NOT IMPLEMENTED

**Milestone family:** M9D

**Decision date:** 2026-07-14

## 1. Context

The implemented discovery layer has three automatic sources—Vansh, Simplify, and
Jobright—plus the manual inbox. The three automatic sources aggregate many employers, but
they are still correlated GitHub trackers with shared blind spots, upstream latency, and
failure modes. The resolution layer supports more ATS families than the discovery layer can
find, so URL acquisition—not URL parsing—is the primary architectural coverage gap.

Hybrid Discovery v2 adds independent source classes and an agentic reconnaissance layer
without allowing nondeterministic output to mutate the production job ledger directly.

## 2. Goals

- Discover relevant jobs from several independent source classes rather than three trackers.
- Find new companies, career boards, ATS tokens, feeds, and source configurations
  continuously.
- Preserve deterministic validation, provenance, deduplication, etiquette, replayability,
  and database writes.
- Measure the marginal value, freshness, precision, reliability, and cost of every source.
- Allow Crawl4AI, Crawlee, and Apify to coexist only where their responsibilities do not
  overlap.
- Introduce capability incrementally, with shadow-mode evidence before autonomous promotion.

## 3. Non-goals

- “All possible sources”; coverage is open-ended and must be optimized with measured yield.
- LinkedIn or Indeed scraping, login automation, CAPTCHA bypass, stealth escalation, or
  proxy rotation used to evade blocking.
- Automated job applications.
- Letting an LLM, MCP tool, crawler, or public Apify Actor write directly to `jobs.db`.
- Running two browser engines against every URL.
- Adding Crawlee merely because it exists; it must win a bounded bake-off first.

## 4. Decision

The system adopts an **agentic control plane with a deterministic data plane**:

1. Deterministic adapters poll approved sources.
2. Bounded crawlers explore approved domains under explicit budgets.
3. An agentic scout proposes new sources and candidate URLs through a versioned file
   contract.
4. Deterministic code validates proposals and stages candidates.
5. Initially, only the user can promote a proposed source to approved.
6. Every accepted job passes through the existing normalized `DiscoveredJob` and database
   insertion path.

“50/50 agentic and deterministic” is therefore a product aspiration about discovery breadth,
not a runtime quota. Agents may originate many leads, but 100% of accepted records cross the
deterministic acceptance boundary.

## 5. Architecture

```text
 approved deterministic sources ───────────────┐
                                               │
 approved-domain bounded crawlers ─────────────┼──> candidate staging
                                               │          │
 agentic scout -> SourceProposal/Candidate ────┘          v
                                                   deterministic verifier
                                                            │
                                              reject/quarantine/approve
                                                            │
                                                   canonicalize + dedupe
                                                            │
                                                    job_observations
                                                            │
                                                       jobs ledger
```

### 5.1 Deterministic source lane

Priority order:

1. Direct ATS watchlists for Greenhouse, Lever, and Ashby; add Workday and other ATS
   families only from measured demand.
2. Authorized alert emails from company boards and aggregators. Receiving a user-requested
   alert is permitted; crawling LinkedIn or Indeed is not.
3. Existing GitHub trackers.
4. Public RSS, sitemap, JSON-LD, and careers APIs.
5. Selected public or licensed aggregator APIs when shadow evaluation shows marginal value.

### 5.2 Bounded crawler lane

The strategy router chooses one mechanism per fetch:

| Need | Mechanism |
|---|---|
| Structured ATS/API | `requests` plus a typed adapter |
| Static job page | existing HTTP/generic resolver |
| JS-heavy individual page | existing Crawl4AI tier-2 resolver |
| Small approved careers-site traversal | evaluate Crawl4AI deep crawl first |
| Durable multi-page queues, routing, or crash recovery | Crawlee Python, only if bake-off wins |
| Cloud execution | allowlisted, version-pinned Apify Actor |

Crawlee and Crawl4AI must not fetch the same URL in the same stage. If Crawlee is adopted,
its primary role is discovering leaf job URLs; the existing resolution router then processes
those URLs and may use Crawl4AI as a leaf-page fallback.

Every crawl has explicit `allowed_domains`, allowed path patterns, maximum depth, pages,
elapsed time, response bytes, and cost. The existing per-host delay and no-evasion rules
apply to every transport.

### 5.3 Agentic scout lane

The scout runs separately from `src.run_ingest`, initially on demand or daily/weekly. It may:

- identify target companies and careers pages;
- infer ATS families and board identifiers;
- generate search queries from candidate preferences and coverage gaps;
- propose RSS, sitemap, API, or crawler seeds;
- investigate source drift and propose configuration changes;
- use web search or allowlisted Apify tools within a run budget.

It may not approve its own source, edit production configuration, call `src.db`, or bypass
the deterministic importer.

The versioned `SourceProposal` contract contains at least:

```json
{
  "schema_version": 1,
  "company": "Example Corp",
  "source_kind": "greenhouse_board",
  "seed_url": "https://boards.greenhouse.io/example",
  "allowed_domains": ["boards.greenhouse.io"],
  "observed_ats": "greenhouse",
  "evidence_urls": ["https://example.com/careers"],
  "confidence": 0.96,
  "proposed_cadence_minutes": 60,
  "discovered_by": "agentic-scout",
  "tool_version": "recorded-at-runtime",
  "requires_review": true
}
```

Web content is untrusted data, never instructions. The scout receives no database or shell
write authority beyond its proposal-output directory.

### 5.4 Apify boundary

Apify is an optional scout or execution boundary, not an authority:

- MCP is suitable for interactive research and evaluating Actors.
- Recurring production use requires an allowlisted Actor ID and pinned build/version.
- Record Actor ID, build, input hash, run ID, dataset ID, elapsed time, and cost.
- Actor output lands in staging and passes the same local validation as every other source.
- Public Actors receive no database credentials or unrestricted secrets.
- Dynamic selection of arbitrary Actors is forbidden in an unattended production run.

## 6. Target data model

The exact migration is designed during M9D-1, but these logical records are required:

- `source_registry`: source ID, kind, configuration, status (`proposed`, `approved`,
  `quarantined`, `disabled`), cadence, domains, extractor/Actor version, and health.
- `source_runs`: source/run identity, timing, pages, candidates, accepted rows, duplicates,
  errors, bytes, and external cost. This may extend or supersede `run_sources` through an
  idempotent migration; no parallel ambiguous counters.
- `discovery_candidates`: raw proposal/candidate, normalized fields, provenance, validation
  status, rejection reason, and evidence.
- `job_observations`: many-to-one record of every source observation of a canonical job.
  `jobs` remains the lifecycle record; one source no longer overwrites all provenance.
- `scout_runs`: model/tool versions, query/input hashes, budgets, proposal artifact, and
  completion state.

M9D-1 must migrate without changing the meaning of existing `jobs.source` rows. Existing
rows are backfilled as one historical observation each.

## 7. Deterministic acceptance gateway

For every proposal and candidate, deterministic code must:

1. Validate the versioned schema and required provenance.
2. Normalize and validate URLs; reject unsupported schemes and out-of-policy domains.
3. Apply the approved source/domain/path policy and crawl budget.
4. Fetch only through the selected polite transport.
5. Validate required job fields and content quality.
6. Canonicalize and deduplicate.
7. Write the observation and canonical job atomically.
8. Advance snapshots/checkpoints only after durable acceptance, or retain a replayable
   checkpoint that cannot outrun the database.

Any partial failure leaves accepted state replayable and does not silently lose candidates.

## 8. Reliability and safety

- Fix snapshot/database consistency before increasing source volume.
- Persist failures and zero-yield runs per source.
- Apply backpressure when resolution backlog exceeds configured limits.
- Quarantine sources that repeatedly violate their expected schema or policy.
- Never treat robots/terms warnings as permission to evade; stop and surface the source.
- Sanitize external text before model context and retain prompt-injection indicators.
- Use least-privilege tokens and keep secrets out of proposal files and traces.
- All automated tests use fixtures; live smoke tests are explicit and manual.

## 9. Evaluation

Every source and scout strategy is evaluated on:

- marginal unique jobs and companies;
- time from posting to discovery;
- accepted candidates / total candidates;
- ATS-quality resolution rate;
- duplicate and stale-listing rates;
- source failure rate;
- cost per unique ATS-quality job;
- shortlist, application, and later interview yield.

Agentic and Apify lanes begin in shadow mode for at least two representative weeks or until
the user approves an evidence-equivalent sample. Shadow candidates cannot write canonical
jobs. Promotion requires acceptable precision/cost and material novelty over the existing
sources.

## 10. Rollout boundaries

Each item is a separate milestone/session:

1. **M9D-0 — Correctness baseline:** snapshot/checkpoint safety, backlog metrics, and source
   yield baseline.
2. **M9D-1 — Provenance foundation:** source registry, candidate staging, observations, and
   idempotent migration.
3. **M9D-2 — Direct-source breadth:** ATS watchlists and authorized alert-email ingestion.
4. **M9D-3 — Crawler bake-off:** bounded Crawl4AI deep crawl versus Crawlee Python on saved
   fixtures and a small approved live sample; adopt at most one multi-page orchestrator.
5. **M9D-4 — Agentic scout shadow:** proposal contract, budgets, injection isolation,
   deterministic verifier, and no production promotion.
6. **M9D-5 — Controlled external execution:** optional allowlisted Apify integration and
   user-approved source promotion, only if shadow metrics justify it.

No M9D implementation starts from this design alone. A dedicated implementation-plan task
must translate one sub-milestone at a time into tests, migrations, rollback, and acceptance
commands.

## 11. Alternatives considered

### Deterministic adapters only

Lowest operational risk, but source discovery remains manual and coverage grows too slowly.

### Agent directly discovers and inserts jobs

Maximum flexibility, but unacceptable reproducibility, policy, idempotency, prompt-injection,
and cost risk. Rejected.

### Crawlee plus Crawl4AI on every source

Feature-rich but duplicates browser, retry, concurrency, and queue ownership. Rejected.

### Selected design: agentic proposals plus deterministic acceptance

Adds adaptive reconnaissance while preserving the pipeline's strongest existing properties.
This is the approved approach.

## 12. Testing strategy

- Contract tests for proposal schema versions and reject-on-any-error behavior.
- Idempotency tests for proposal import, observation writes, and source promotion.
- Migration tests against a copy of the current schema and representative data.
- Policy tests for domain/path/budget restrictions and unsupported URL schemes.
- Fixture tests for each deterministic adapter and crawler route.
- Failure-injection tests proving checkpoints cannot advance past durable writes.
- Prompt-injection fixtures proving page text cannot change scout policy or tool authority.
- Shadow-mode tests proving canonical `jobs` rows remain unchanged.
- Live smoke tests only with user-approved domains, budgets, and Actors.
