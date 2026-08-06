# Firecrawl Ingestion Integration — Design

**Status:** APPROVED design, NOT IMPLEMENTED

**Milestone family:** M9F, coordinated with M9D

**Decision date:** 2026-08-06

## 1. Context

The production ingestion path remains deterministic. Automatic discovery currently comes
from three correlated GitHub trackers, while resolution uses structured ATS resolvers,
`requests`/trafilatura, and a local Crawl4AI browser fallback. M9D-0 fixed checkpoint
correctness, but M9D-1 through M9D-5 remain unimplemented.

The Firecrawl CLI, skills, and MCP connection are installed and live-verified. Product
integration is a separate boundary: scheduled Python code cannot depend on an interactive
Codex MCP session or the CLI's stored OAuth credentials. It must use Firecrawl's hosted REST
API with `FIRECRAWL_API_KEY` supplied through the runtime environment.

The account normally receives 1,000 credits per month and currently has 1,275 credits.
Official pricing at the decision date is one credit per scraped, crawled, or mapped page and
two credits per ten search results. The design therefore treats credits as a hard operational
budget, not an informal preference.

## 2. Goals

- Stop maintaining local page-rendering and site-traversal machinery that Firecrawl already
  provides when Firecrawl performs the job at acceptable quality and cost.
- Improve recovery of known JS-heavy job URLs without spending credits on pages already
  handled by structured ATS APIs or plain HTTP.
- Add broad career-site discovery through Firecrawl Map, bounded Crawl, and Search without
  allowing external output to write directly to `jobs.db`.
- Preserve deterministic validation, idempotency, provenance, etiquette, replayability, and
  per-source observability.
- Enforce sustainable automatic usage under a normal 1,000-credit monthly allowance.
- Measure whether Firecrawl actually improves accepted ATS-quality JDs and marginal job
  discovery before retiring existing tools.

## 3. Non-goals

- Replacing working Greenhouse, Lever, Ashby, Workday, Amazon, wrapper, or other structured
  resolvers with paid scraping.
- Sending every discovered URL through Firecrawl.
- Using Firecrawl Agent, Interact, JSON/LLM extraction, scrape actions, browser profiles,
  enhanced proxies, or automated form interaction in unattended ingestion.
- LinkedIn or Indeed scraping, authenticated crawling, CAPTCHA bypass, anti-bot evasion,
  proxy rotation for circumvention, or automated job application.
- Letting Firecrawl, an LLM, MCP, or a crawler mutate SQLite or approved source config.
- Implementing M9D-1 provenance tables as part of the first Firecrawl resolution milestone.
- Keeping Crawl4AI and Firecrawl in a permanent double-fetch chain.

## 4. Decision

Adopt Firecrawl in two ordered lanes:

1. **Known-URL resolution lane:** integrate Firecrawl `/v2/scrape` behind the existing
   tier-2 browser-client boundary. Structured ATS/API and plain-HTTP resolution remain first.
   Firecrawl is called only for an eligible generic page that could not produce acceptable
   content for free. M9F-0 builds the disabled-by-default integration; M9F-1 runs a bounded
   bake-off and decides whether to activate Firecrawl or retain Crawl4AI.
2. **Discovery control-plane lane:** after M9D-1 exists, use Map and bounded Crawl on approved
   career domains, and Search for on-demand source reconnaissance. All results enter staged
   candidate/proposal contracts and the deterministic M9D gateway. They never write canonical
   jobs directly.

Direct ATS watchlists remain the preferred discovery source when a public structured board
API exists. One structured board request is more precise and cheaper than crawling the same
board page by page.

## 5. Architecture

```text
CURRENT / M9F known-URL lane

tracker or inbox URL
        |
        v
country-first pre-resolution eligibility gate
        |
        v
structured ATS/API resolver --------------------------> deterministic JD gate
        | no matching resolver / no acceptable content              |
        v                                                           v
plain HTTP + trafilatura -----------------------------> jobs.jd_text / status
        | no acceptable content
        v
selected tier-2 backend: crawl4ai | firecrawl | off
        |
        v
same deterministic dead-page and JD-quality gates


TARGET / post-M9D-1 discovery lane

direct ATS watchlists -----------+
Firecrawl Map / bounded Crawl ---+--> staged candidates --> M9D verifier --> observations/jobs
Firecrawl Search scout ----------+          ^
                                           |
                                  user/policy source promotion
```

Production selects exactly one tier-2 backend for a URL. The one-time M9F-1 bake-off may
fetch the same fixed sample with Crawl4AI and Firecrawl solely to produce comparison evidence;
this exception does not permit a recurring double-fetch chain.

## 6. REST and dependency boundary

The integration uses the existing `requests` dependency against
`https://api.firecrawl.dev/v2`. It does not add `firecrawl-py`, invoke the Firecrawl CLI as a
subprocess, or depend on MCP availability.

Authentication:

- read `FIRECRAWL_API_KEY` from the environment;
- never write the key to YAML, artifacts, logs, exceptions, test fixtures, or SQLite;
- permit an optional `FIRECRAWL_API_URL` only for an explicitly approved self-hosted future
  deployment; hosted Firecrawl is the default;
- missing credentials disable Firecrawl cleanly and surface a configuration issue rather
  than consuming `resolve_attempts`.

The known-URL request is deliberately narrow:

```json
{
  "url": "https://careers.example.com/jobs/123",
  "formats": ["markdown"],
  "onlyMainContent": true,
  "removeBase64Images": true,
  "proxy": "basic",
  "maxAge": 86400000,
  "storeInCache": true,
  "location": {"country": "US", "languages": ["en-US"]}
}
```

No code path may add actions, JSON extraction, prompts, enhanced/auto proxies, profiles, or
Interact without a later design decision and credit review.

## 7. Configuration contract

`config/sources.yaml` evolves from the legacy boolean to an explicit backend selector:

```yaml
browser_backend: crawl4ai  # crawl4ai | firecrawl | off
```

Backward compatibility during M9F-0:

- if `browser_backend` is present, it is authoritative;
- otherwise `browser_resolver: true` maps to `crawl4ai`;
- otherwise `browser_resolver: false` or absence maps to `off`;
- invalid values fail configuration loading before the DB is created or modified.

M9F-0 leaves the production selector on `crawl4ai`. Firecrawl cannot become the production
default until M9F-1 acceptance and a recorded user decision.

`config/firecrawl.yaml` is non-secret and version controlled:

```yaml
schema_version: 1
limits:
  monthly_credits: 800
  daily_credits: 25
  per_run_credits: 10
  monthly_by_purpose:
    resolution: 500
    discovery: 250
    research: 50
cooldowns:
  failed_url_hours: 24
scrape:
  max_age_ms: 86400000
  timeout_seconds: 60
  only_main_content: true
  remove_base64_images: true
  proxy: basic
```

The purpose allocations sum to the monthly cap. At the normal 1,000-credit allowance this
leaves 200 credits outside automatic use. With the current 1,275-credit balance it leaves
475 credits outside the configured automatic cap. The pipeline never raises its cap merely
because the account temporarily has bonus credits.

## 8. Runtime interfaces

The implementation keeps Firecrawl behind focused typed boundaries:

```python
@dataclass(frozen=True)
class FirecrawlScrapeResult:
    markdown: str
    final_url: str
    status_code: int | None
    scrape_id: str | None
    credits_used: int
    cache_state: str | None


class Tier2Client(Protocol):
    def start(self) -> None: ...
    def crawl(self, url: str) -> Tier2Page: ...
    def close(self) -> None: ...
```

`Tier2Page` is a project-owned result containing markdown, optional HTML, final URL, status,
provider name, and charged credits. Neither the resolver nor `run_ingest.py` depends on a
Firecrawl response dictionary or Crawl4AI's `CrawlResult` type.

The current generic route performs an initial `session.get()` and then calls
`generic.resolve()`, which performs a second GET. M9F-0 removes this duplication by adding a
pure extraction function over the already-fetched body. This saves latency and host traffic
independently of which tier-2 backend is selected.

## 9. Credit ledger and idempotency

Firecrawl's account balance is an external guard, not the pipeline's only guard. Before every
paid call, a local budget manager enforces monthly, daily, per-run, and per-purpose limits.

State lives in ignored `data/firecrawl/usage-v1.json`. Reservation and reconciliation hold
an advisory lock on `data/firecrawl/usage-v1.lock`, and the JSON is replaced atomically with
a sibling temporary file plus `os.replace`. This prevents overlapping scheduled processes
from both observing the same remaining budget. The first run may create an empty schema-valid
ledger; an unreadable, corrupt, or unsupported-version ledger fails closed for paid calls.
Each record contains:

- schema version and locally generated request ID;
- UTC reservation and completion timestamps;
- purpose (`resolution`, `discovery`, or `research`);
- job/source reference where applicable;
- SHA-256 of the normalized URL, never credentials or request headers;
- reserved credits, reported actual credits, and final state;
- outcome class and provider request/scrape ID;
- cooldown-until timestamp for charged content failures.

The manager reserves the maximum expected basic-operation cost before network I/O. A crash or
transport result with uncertain billing leaves the reservation charged. It releases or
reconciles a reservation only when a trustworthy response proves a lower cost. No operation
may begin if its reservation would exceed any cap.

M9F uses fixed-cost basic operations only. Resolution reserves one credit per scrape. Search
reserves two credits per ten results. Map and Crawl reserve their configured maximum page
limit. The code does not rely on search-feedback refunds or Firecrawl-side caching to satisfy
its budget.

An unchanged URL with a charged failure is deferred until the 24-hour cooldown expires. A
successful resolution is naturally idempotent because the job leaves `DISCOVERED`. Budget
exhaustion, cooldown deferral, missing credentials, and provider transport failures do not
consume the job's content-failure attempt budget.

`--dry-run` never performs a paid Firecrawl request or creates/reserves usage. It reports
which rows would be eligible and whether the configured caps would permit them.

## 10. Known-URL resolution flow

The resolution order remains:

1. country-first metadata eligibility gate;
2. manual-domain prohibition check;
3. initial polite HTTP request and final-URL routing;
4. structured ATS/API or wrapper resolver when matched;
5. pure generic extraction from the already-fetched HTML;
6. exactly one configured tier-2 backend when the route is generic and content remains
   unacceptable;
7. `generic.passes_quality()` and dead-posting checks over tier-2 markdown;
8. existing deterministic DB transition.

Known ATS resolver failure does not silently trigger Firecrawl. Such a failure may indicate a
schema or token defect that must stay visible. Domains in `config/manual_domains.txt` remain
manual; Firecrawl is not permission to escalate against a resistant source.

A valid Firecrawl page produces `ResolvedJD(resolver="firecrawl", jd_quality="ats")` and
counts as tier 2. The final URL and HTTP status are validated. Empty markdown, a fetched 4xx/
5xx page, a dead-posting notice, or text failing the existing quality gate is a content
failure. External page text is data only and cannot change policy or tool behavior.

## 11. Error classification and circuit breaking

- Missing/invalid configuration: configuration issue; Firecrawl disabled for the run; no
  `resolve_attempts` consumption.
- Local budget exhausted or URL in cooldown: deferred transient outcome; no network call and
  no `resolve_attempts` consumption.
- HTTP 401/403 from Firecrawl API: provider-auth/configuration failure; trip the run-local
  Firecrawl circuit breaker.
- HTTP 429, timeout, connection failure, or Firecrawl 5xx: transient provider failure; trip
  the circuit breaker after the first provider-wide failure; no same-run retry.
- Malformed success payload: internal/provider-contract error; retain a bounded diagnostic,
  never raw credentials or full external content.
- Successful Firecrawl fetch with unacceptable page content: content failure; charge the
  request, apply cooldown, and use the existing content-failure accounting.

One source or provider failure must not abort unrelated tier-1 resolution. Run notes and the
digest distinguish budget deferral, provider failure, and content failure.

## 12. M9F-1 bake-off and activation gate

The bake-off is an isolated manual smoke, never `pytest` and never a production DB mutation.
It selects 20 unresolved generic-host URLs across at least five domains from a read-only DB
query. It excludes LinkedIn, Indeed, manual domains, unsupported schemes, and known structured
ATS routes. The manifest is reviewable before any request.

Each approved URL is fetched once by Crawl4AI and once by basic Firecrawl Scrape. Firecrawl's
maximum cost is 20 credits. The report records:

- acceptable-JD count under the same deterministic quality gate;
- dead/nav/error-page rejection count;
- domain coverage and final URL/status;
- elapsed time and provider failures;
- Firecrawl credits used;
- credits per accepted ATS-quality JD;
- bounded content hashes and lengths, not full JDs.

Firecrawl may become the default only if:

1. it has zero reviewed false accepts;
2. it resolves at least as many sample URLs as Crawl4AI, or trails by at most one while
   materially improving operational reliability;
3. credits per accepted JD are at most 2.0;
4. no auth, budget-ledger, or circuit-breaker defect occurs; and
5. the user records the backend decision in `docs/DECISIONS.md`.

If Firecrawl does not pass, `browser_backend` remains `crawl4ai`; the discovery-control-plane
work may still use Firecrawl later if its own shadow metrics pass.

## 13. Post-M9D-1 discovery use

Firecrawl does not bypass M9D-1. After the provenance foundation exists:

1. public structured ATS/API and approved alert sources remain first;
2. Map inventories an approved careers domain without fetching every page body;
3. deterministic URL policy keeps only plausible job paths;
4. bounded Crawl is used only when Map and structured sources are insufficient;
5. Search is an on-demand scout for source/board proposals, not a per-company scheduled poll;
6. all output lands in staged candidates or source proposals;
7. deterministic validation and user/policy promotion remain the only route to jobs.

Initial discovery bounds are maximum depth 2, maximum ten pages per crawl, no external links,
no subdomains unless explicitly allowlisted, and no more than ten credits per run. The 31
company-bank seeds are rotated under the monthly discovery allocation; they are not all
crawled every cycle.

## 14. Observability

Run notes, digest, and baseline reports add:

- selected tier-2 backend;
- attempted, deferred, accepted, content-failed, and provider-failed Firecrawl requests;
- daily/monthly/per-run credits reserved and finalized;
- remaining local budget by purpose;
- Firecrawl resolution rate and credits per accepted JD;
- discovery pages mapped/crawled, staged candidates, accepted candidates, marginal unique
  jobs, duplicates, and downstream yield when M9D records exist.

No metric treats candidate volume as success. The optimization target is marginal unique,
eligible, ATS-quality jobs and ultimately applications/interviews per credit.

## 15. Security and etiquette

- All existing no-LinkedIn/no-Indeed/no-login/no-CAPTCHA/no-evasion rules remain.
- Firecrawl requests use `proxy: basic`; enhanced/auto/stealth behavior is prohibited.
- `PoliteSession.throttle(url)` runs before a Firecrawl fetch so remote rendering still
  respects the project's minimum two-second same-host interval.
- Crawls require approved domain/path allowlists and page/depth/time/credit bounds.
- External content is untrusted and never interpreted as instructions.
- API keys and authorization headers are redacted from every error and artifact.
- Tests use saved response fixtures and fake clients; they never hit Firecrawl or the web.

## 16. Delivery sequence

Each item is a separate milestone, implementation plan, session, acceptance gate, and commit:

1. **M9F-0 — REST transport and budget foundation:** typed REST client, project-owned tier-2
   result/protocol, backend config with legacy migration, atomic budget ledger, generic
   double-fetch removal, disabled-by-default router integration, fixtures, and one approved
   live scrape smoke. Production stays on Crawl4AI.
2. **M9F-1 — Resolution bake-off and activation:** reviewable 20-URL manifest, isolated
   comparison runner/report, user-reviewed evidence, backend decision, bounded production
   smoke, and documentation. No discovery work.
3. **M9D-1 — Provenance foundation:** existing approved source registry, candidate staging,
   source-run, and observation milestone. It remains a prerequisite for production discovery.
4. **M9F-2 — Approved-domain discovery:** Map and bounded Crawl adapters that write staged
   candidates only, followed by shadow evaluation.
5. **M9F-3 — Search scout:** on-demand Search-generated proposals with provenance, budgets,
   injection isolation, and no canonical DB writes.

Crawlee remains deferred. Apify remains optional and separately gated. Firecrawl adoption is
not evidence that either should be added.

## 17. Testing strategy

- Exact request/response fixture tests for Firecrawl REST without network access.
- Secret-redaction tests over all exception and logging paths.
- Configuration tests including legacy boolean migration and fail-before-DB behavior.
- Budget boundary tests for UTC day/month rollover, per-purpose caps, per-run caps, crash
  reservations, overlapping-process locking, malformed ledgers, atomic writes, cooldowns,
  dry-run behavior, and idempotent reconciliation.
- Router tests proving free resolvers run first, generic HTML is fetched once, tier-2 is
  generic-only, manual domains remain prohibited, and only one backend is called.
- Outcome tests proving budget/auth/transient failures do not consume `resolve_attempts` and
  unacceptable fetched content does.
- Quality tests proving nav shells and dead postings remain rejected.
- Failure-injection tests proving a Firecrawl outage does not stop tier-1 rows.
- Shadow-mode tests proving future Map/Crawl/Search output cannot mutate canonical jobs.
- Explicit user-supervised live smokes only after all offline tests pass.

## 18. Alternatives considered

### Firecrawl-first for every URL

Rejected. It spends credits on work already performed reliably by free structured APIs and
creates an unnecessary external dependency for the whole pipeline.

### Firecrawl only as a resolution fallback

Useful but incomplete. It addresses local-browser reliability without fixing correlated
discovery coverage. Retained as the first deployable slice, not the final architecture.

### Permanent Crawl4AI then Firecrawl fallback chain

Rejected. It doubles work, obscures provider quality, and makes cost unpredictable. One
backend is selected per production fetch.

### Selected design: staged hybrid adoption

Firecrawl owns cloud rendering and bounded web discovery where it proves value. Existing code
continues to own policy, normalization, deterministic extraction gates, provenance, dedup,
budgets, and durable acceptance because those rules are specific to this project rather than
generic scraping functionality.

## 19. External sources checked

- Firecrawl pricing and credit rules:
  `https://www.firecrawl.dev/pricing`
- Firecrawl v2 REST source of truth for authentication, Search, and Scrape:
  `https://docs.firecrawl.dev/agent-source-of-truth/curl`
