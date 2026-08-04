# ARCHITECTURE.md — Job Pipeline System Design

Status: authoritative. If code and this document disagree, this document wins unless the user
says otherwise. Implementation questions not answered here should be raised to the user, not
guessed.

Implementation notation: sections labeled **CURRENT** describe deployed code. Sections
labeled **TARGET — M9D** are approved architecture not yet implemented beyond the explicitly
marked M9D-0 checkpoint-correctness baseline. A target section does not authorize skipping
its implementation milestone, migration, tests, or user smoke gate. The detailed target design is
`docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`.

---

## 1. System overview

```
       CURRENT DISCOVERY (implemented through M7; deterministic)
  ┌──────────────┬──────────────┬───────────────┬─────────────┐
  │ GitHub       │ GitHub       │ GitHub        │ Manual      │
  │ tracker:     │ tracker:     │ trackers:     │ inbox:      │
  │ vanshb03     │ SimplifyJobs │ jobright-ai   │ URLs + MD   │
  └──────┬───────┴──────┬───────┴──────┬────────┴──────┬──────┘
         └──────────────┴───── normalize ──────────────┘
                               │
                        dedupe + insert
                               │
                        ┌──────▼──────┐
                        │  SQLite DB  │  status: DISCOVERED
                        └──────┬──────┘
                               │
                 RESOLUTION (deterministic router)
        greenhouse │ lever │ ashby │ workday │ generic
                               │
                        status: RESOLVED / RESOLVE_FAILED
                               │
                 PRE-FILTER (deterministic rules)
                               │
                        status: FILTERED_OUT or stays RESOLVED
                               │
                 DIGEST (markdown report for the user)
                               │
        ═══════════ Phase 2+: Claude enters here ═══════════
                               │
                 SCORING (one batched Claude call)   → SCORED / SHORTLISTED
                 TAILORING (per-job, diff-based)     → TAILORED
                 HUMAN REVIEW                        → APPLIED / REJECTED
```

Phase 0–1 (this build) implements everything above the double line. The original DB schema
and status machine cover the planned lifecycle through M8. The separately approved M9D
provenance model requires its own idempotent migration; target fields are not present today.

**TARGET — M9D:** discovery becomes hybrid without weakening the commit boundary. Approved
deterministic adapters, bounded crawlers, and an agentic scout may all produce staged
candidates. The scout produces versioned proposals only. Deterministic validation, policy,
provenance, canonicalization, and deduplication remain the only path into SQLite.

```text
deterministic sources ─┐
bounded crawlers ──────┼──> candidate staging -> deterministic verifier -> observations/jobs
agentic scout ─────────┘             ^
                              user/policy promotion
```

## 2. Repository layout

*Note on M8 Company Bank*: The M8 Track A implementation provides the offline foundation only (`config/company_bank`, `src/company_bank`, and `data/company_research/inbox`). It does not integrate with SQLite, eligibility, scoring, or live tailoring.*

```
job-pipeline/
├── CLAUDE.md
├── docs/                      # this documentation package
├── config/
│   ├── company_bank/          # M8: Offline company knowledge base
│   ├── sources.yaml           # tracker repos, watchlist, toggles
│   ├── eligibility.yaml       # M6.11: sole eligibility business policy
│   ├── location_taxonomy.yaml # M6.11: local country/state vocabulary
│   ├── filters.yaml           # scoring config only (score_threshold)
│   └── wrapper_map.yaml       # M6.0: known wrapper hostname -> fixed ATS board
├── data/
│   ├── company_research/inbox/ # M8: Staged company research bundles
│   ├── jobs.db                # SQLite (gitignored)
│   └── digests/               # daily digest output (gitignored)
├── snapshots/                 # per-source snapshots for diffing (gitignored)
├── inbox/
│   ├── urls.txt               # manual URL drop, one per line
│   └── *.md                   # manual JD paste files
├── src/
│   ├── company_bank/          # M8: Offline knowledge foundation (Track A)
│   ├── __init__.py
│   ├── models.py              # dataclasses, enums, normalization helpers
│   ├── db.py                  # schema, connection, upsert/query helpers
│   ├── discover/
│   │   ├── __init__.py        # discover_all() registry
│   │   ├── base.py            # adapter protocol
│   │   ├── tracker_vansh.py
│   │   ├── tracker_simplify.py
│   │   ├── tracker_jobright.py
│   │   └── inbox_manual.py
│   ├── resolve/
│   │   ├── __init__.py        # route(url) -> resolver
│   │   ├── base.py            # resolver protocol, polite HTTP session
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── workday.py
│   │   ├── amazon_jobs.py     # M6.0(d)
│   │   ├── wrapper.py         # M6.0(b)-(c): gh_jid unwrap + wrapper_map
│   │   └── generic.py         # trafilatura fallback
│   ├── prefilter.py
│   ├── digest.py
│   └── run_ingest.py          # CLI entry point
├── tests/
│   ├── fixtures/              # saved HTML/JSON responses
│   └── test_*.py
├── scripts/
│   └── record_fixture.py      # one-off: fetch a URL and save it as a test fixture
├── pyproject.toml
└── .gitignore
```

## 3. Dependencies (CURRENT; exhaustive — do not add others without asking)

- `requests` — HTTP
- `trafilatura` — main-content extraction for generic resolver
- `PyYAML` — config files
- `pytest` — testing
- `crawl4ai` (M6.5) — deterministic headless-browser rendering/markdown for the tier-2
  resolver (`resolve/browser.py`). M9D may also evaluate its bounded deep-crawl mode on
  approved careers domains. Its LLM-extraction strategies remain forbidden in the
  deterministic data plane (see §6.4).
- Standard library for everything else (`sqlite3`, `hashlib`, `re`, `dataclasses`,
  `argparse`, `logging`, `datetime`, `json`, `pathlib`, `asyncio`).

No ORM (raw `sqlite3` with helper functions). No async in the pipeline proper (daily batch
job; simplicity wins) — `resolve/browser.py` is the one exception, and it contains its
async usage entirely behind a synchronous `asyncio.run()` wrapper.

**TARGET — M9D dependency gate:** Crawlee Python and Apify are candidates, not approved
dependencies. First evaluate Crawl4AI deep crawling against saved fixtures. Add Crawlee only
if persistent queues, route handlers, or crash recovery show a material advantage. Apify MCP
is an interactive scout integration; unattended runs require allowlisted, version-pinned
Actors and deterministic local validation. No JavaScript sidecar is the default design.

## 4. Data model

### 4.1 SQLite schema

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key       TEXT UNIQUE NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT,
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,      -- 'tracker_vansh' | 'tracker_simplify' | 'tracker_jobright' | 'inbox'
    date_posted     TEXT,               -- ISO date if known, else NULL
    discovered_at   TEXT NOT NULL,      -- ISO datetime UTC
    status          TEXT NOT NULL DEFAULT 'DISCOVERED',
    jd_text         TEXT,
    jd_resolved_at  TEXT,
    resolver        TEXT,               -- which resolver succeeded
    resolve_attempts INTEGER NOT NULL DEFAULT 0,
    filter_reason   TEXT,               -- why FILTERED_OUT, human-readable
    flags           TEXT,               -- JSON array, e.g. ["sponsorship_risk"]
    fit_score       REAL,               -- Phase 2
    fit_rationale   TEXT,               -- Phase 2
    base_variant    TEXT,               -- Phase 3
    missing_keywords TEXT,              -- Phase 2, JSON array
    notes           TEXT,
    ats_url         TEXT,               -- M6.0/M6.2: underlying ATS URL when resolved via an
                                         -- aggregator/wrapper unwrap (gh_jid, wrapper_map, jobright)
    jd_quality      TEXT,               -- M6.2: 'ats' (employer's literal posting) or
                                         -- 'aggregator' (jobright's own summary); Phase 3
                                         -- tailoring requires jd_quality='ats'
    last_seen_at    TEXT,               -- M6.8: last time this dedup_key was seen anywhere —
                                         -- set at insert, touched on every dedup-key conflict
                                         -- and on every liveness-recheck GET (alive or dead)
    repost_count    INTEGER NOT NULL DEFAULT 0  -- M6.8: dedup-key conflicts seen, i.e. how many
                                         -- times a tracker has re-listed this same posting
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    new_jobs       INTEGER DEFAULT 0,
    resolved       INTEGER DEFAULT 0,
    failed         INTEGER DEFAULT 0,
    filtered_out   INTEGER DEFAULT 0,
    tier1_resolved INTEGER NOT NULL DEFAULT 0,  -- M6.5: resolved by a tier-1 resolver this run
    tier2_resolved INTEGER NOT NULL DEFAULT 0,  -- M6.5: resolved by resolve/browser.py this run
    manual_failed  INTEGER NOT NULL DEFAULT 0,  -- M6.5: reached RESOLVE_FAILED this run
    notes          TEXT
);

-- M6.0: per-source counters, one row per (run, source), so a source
-- contributing zero rows is a visible zero rather than a silent gap.
CREATE TABLE IF NOT EXISTS run_sources (
    run_id      INTEGER NOT NULL,
    source      TEXT NOT NULL,
    discovered  INTEGER NOT NULL DEFAULT 0,
    inserted    INTEGER NOT NULL DEFAULT 0,
    resolved    INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, source)
);
```

`ats_url`, `jd_quality`, and `run_sources` were added after the initial (M1) schema;
`tier1_resolved`/`tier2_resolved`/`manual_failed` were added in M6.5;
`last_seen_at`/`repost_count` were added in M6.8. `db.init_db()` applies new `jobs`/`runs`
columns via idempotent `ALTER TABLE` so existing databases migrate without data loss (new
tables need no migration — `CREATE TABLE IF NOT EXISTS` already covers them).

### 4.2 Status state machine

```
DISCOVERED ──resolve ok──▶ RESOLVED ──prefilter fail──▶ FILTERED_OUT   (terminal, keep row)
     │                        │
     │ resolve fail ×3        │  Phase 2: scoring
     ▼                        ▼
RESOLVE_FAILED (terminal)   SCORED ──▶ SHORTLISTED ──▶ TAILORED ──▶ APPLIED
     │                                     │  │
     │ M6.8 resurfacing                    │  │ M6.8 liveness recheck (dead link)
     │ (reopen_days elapsed)               │  ▼
     └──────────────▶ DISCOVERED           │ CLOSED (terminal — never tailor against it)
                          ▲                ▼
                          │             REJECTED (by user or by score threshold)
                          └── M6.8 resurfacing from CLOSED (reopen_days elapsed)
```

Rules:
- Status only moves forward, with one narrow exception: M6.8's resurfacing rule (§7.5) resets
  `RESOLVE_FAILED`/`CLOSED` rows back to `DISCOVERED` when the same dedup_key reappears after
  `reopen_days` of not being seen — the posting either was never actually evaluated
  (RESOLVE_FAILED) or died and is genuinely back (CLOSED). No other status is ever reset.
- `RESOLVE_FAILED` is set after 3 failed attempts across runs (`resolve_attempts >= 3`).
  Fewer than 3: stay `DISCOVERED`, retry next run.
- A job the user manually pastes into `inbox/` for a row in `RESOLVE_FAILED` moves it to
  `RESOLVED` (match by URL).
- `CLOSED` is set by exactly two paths, both terminal:
  1. **Liveness recheck (M6.8).** The digest-time recheck (§7.5) finds a 404/410 on a
     `SHORTLISTED`/`TAILORED` row's `ats_url`/`url` (`db.mark_closed()`).
  2. **Content-based closure (M6.13R).** The stored `jd_text` is a dead-page notice rather
     than JD content — the resolver fetched the ATS's "this job is no longer available"
     shell, which is long enough and job-adjacent enough to pass the length/keyword gate.
     Detected by `resolve.generic.dead_posting_evidence()`, which requires an explicit
     subject naming *this* posting bound to a dead predicate in the same sentence; bare
     fragments such as "has been filled" are not evidence, so careers-page FAQ wording
     ("when an opportunity has been filled, we will remove the job posting") does not
     qualify. The same function backs `passes_quality()`, so freshly fetched text and
     already-stored `jd_text` are judged identically on both the generic and browser tiers.

  Content-based closure is applied only by `scripts/remediate_dead_postings.py` through
  `db.apply_dead_posting_closures()`, and **only from these source states**
  (`db.CONTENT_CLOSURE_SOURCE_STATUSES`): `RESOLVED`, `SCORED`, `SHORTLISTED`, `TAILORED`.
  `FILTERED_OUT`, `REJECTED`, `APPLIED`, `CLOSED`, and `RESOLVE_FAILED` are never
  overwritten — the M6.13 version of this path did overwrite 35 `FILTERED_OUT` rows, which
  destroyed their eligibility decisions and had to be repaired (see DECISIONS.md
  2026-07-25). `DISCOVERED` is excluded too: a `DISCOVERED` row's leftover `jd_text` is
  stale by definition and is not evidence that the posting is dead. The apply runs in one
  transaction with compare-and-set predicates on each previewed row's expected status, so a
  stale preview rolls the whole batch back rather than writing against drifted state, and
  re-applying an already-applied preview is a no-op. Scoring fields are cleared only for
  rows that actually transition.

### 4.3 Dedup key

`dedup_key = sha256(f"{norm(company)}|{norm(title)}|{norm_loc(location)}")` where:

- `norm(s)`: lowercase → strip accents → remove punctuation → collapse whitespace →
  strip corporate suffixes as trailing words (`inc`, `llc`, `ltd`, `corp`, `co`) →
  strip requisition IDs from titles (regex: trailing `#?\d{4,}` or `\(req[^\)]*\)` or
  bracketed IDs like `[R-12345]`).
- `norm_loc(s)`: apply `norm`, then map any of {`remote`, `remote us`, `remote usa`,
  `united states remote`, `us remote`} → `remote-us`. Empty/NULL location → `unknown`.
- Insertion uses `INSERT ... ON CONFLICT(dedup_key) DO NOTHING`. If the conflicting existing
  row has a "worse" source (see priority below) and no `jd_text` yet, update its `url` and
  `source` to the better one:
  priority: `inbox` > `tracker_simplify` > `tracker_vansh` > `tracker_jobright`.
- M6.8: every conflict (regardless of source priority) touches the existing row's
  `last_seen_at`/`repost_count` (§7.5) — a dedup-key conflict means the posting is still being
  seen somewhere, independent of which source wins.

### 4.4 Normalized interchange types (`models.py`)

```python
@dataclass(frozen=True)
class DiscoveredJob:
    company: str
    title: str
    location: str | None
    url: str
    source: str
    date_posted: str | None   # ISO date or None

@dataclass(frozen=True)
class ResolvedJD:
    jd_text: str               # clean plain text / markdown, no nav or boilerplate
    resolver: str
    raw_title: str | None      # title as the ATS reports it, if available
    raw_location: str | None
```

### 4.5 Hybrid discovery records (TARGET — M9D)

M9D introduces four logical records through an idempotent, separately approved migration:

- `source_registry`: proposed/approved/quarantined/disabled source configuration, domains,
  cadence, extractor or Actor version, and health.
- `discovery_candidates`: raw staged candidate/proposal, normalization, provenance,
  validation state, evidence, and rejection reason.
- `job_observations`: every source observation of a canonical job. `jobs` remains the
  lifecycle record; one source must no longer erase multi-source provenance.
- `scout_runs`: agent/model/tool versions, input hash, budgets, proposal artifact, and status.

Existing `run_sources` either evolves into the source-run ledger or is migrated to one
unambiguous successor; the implementation must not maintain competing counters. Existing
`jobs.source` values remain valid and are backfilled as one historical observation per row.

## 5. Discovery adapters

### 5.1 Adapter contract (`discover/base.py`)

Each adapter module exposes:

```python
SOURCE_NAME: str
def discover(config: dict) -> AdapterDiscovery: ...
```

`AdapterDiscovery` contains immutable `jobs` plus a `PendingCheckpoint`. `discover_all()` in
`discover/__init__.py` iterates enabled adapters from `config/sources.yaml`, returns a
`DiscoveryResult` containing jobs, checkpoints, succeeded sources, and structured issues, and
never lets one adapter's exception kill the run: catch, log, record in `runs.notes`, continue.

### 5.2 GitHub tracker adapters (vansh, simplify, jobright)

Shared strategy, implemented once in a helper and parameterized per repo:

1. **Prefer machine-readable data.** On first run against a repo, probe for a JSON listings
   file: try `/.github/scripts/listings.json` (Simplify's known location) and any `*.json`
   under `/.github/` via the GitHub contents API (`api.github.com/repos/{owner}/{repo}/contents/.github`).
   If found, record its path in the snapshot metadata and use it from then on.
2. **Fallback: parse the README markdown table.** Fetch
   `raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md`. Parse rows of the main
   table. Columns to expect (tolerate reordering by reading the header row): Company, Role,
   Location, Application/Link, Date Posted. Extract the apply URL from the markdown link or
   `<a href>` in the cell. Rows using `↳` or empty company cells inherit the company from the
   previous row. Skip rows marked closed (🔒 or struck-through).
3. **Prepare checkpoint diff.** After parsing, compute the set of `dedup_key`s; compare with
   `snapshots/{source}.json` (`keys` plus M9D-0 `pending_keys`). Only rows with new keys or
   deferred pending keys are returned. The adapter does **not** write the snapshot. It returns
   a pending checkpoint to `run_ingest.py`.
4. **Commit only after durable insert.** `run_ingest.py` inserts accepted jobs into SQLite
   first. Only after `db.insert_discovered()` succeeds does it atomically replace the snapshot
   via sibling temp file plus `os.replace`. A crash may leave the checkpoint behind SQLite;
   it must never advance ahead of SQLite. Legacy snapshots containing only `{keys,
   source_path}` load with empty `pending_keys`.
5. **Limit handling.** `--limit N` is per source. Unselected candidates are kept in
   `pending_keys`, so repeated limited runs drain the same fetched snapshot instead of marking
   uninserted rows permanently seen.
6. Send header `User-Agent: job-pipeline (personal use)` and, if `GITHUB_TOKEN` is present in
   env, an auth header (raises rate limits; optional).

Configured repos (in `config/sources.yaml`, user-editable):

```yaml
sources:
  tracker_vansh:
    enabled: true
    repo: vanshb03/New-Grad-2027
  tracker_simplify:
    enabled: true
    repo: SimplifyJobs/New-Grad-Positions
  tracker_jobright:
    enabled: true
    repos:                      # jobright-ai publishes several category repos
      - jobright-ai/2026-Software-Engineer-New-Grad
      # user may add e.g. backend / ML category repos later
```

Note for implementation: exact default branch names and README table shapes must be verified
against the live repos during development (they are `dev`/`main` depending on repo). Verify
once, hardcode per-repo config, and save a real README as a test fixture.

### 5.3 Manual inbox adapter (`inbox_manual.py`)

- `inbox/urls.txt`: one URL per line, `#` comments allowed. Each URL becomes a
  `DiscoveredJob` with `source='inbox'`, company/title parsed later at resolution
  (placeholder company `unknown` + the URL's domain; the resolver's `raw_title` backfills
  title/company when available — update the row after resolution if fields were placeholders).
- `inbox/*.md`: manual JD paste. File format:
  - Line 1: the job URL
  - Line 2: `Company — Title — Location` (em-dash or `|` separated; be lenient)
  - Rest: the JD text
  These become `DiscoveredJob`s AND are immediately marked `RESOLVED` with the pasted text
  (`resolver='manual'`).
- After successful ingestion, move processed files to `inbox/processed/` (create it), and
  rewrite `urls.txt` keeping only unprocessed lines (a line is processed once its job row
  exists). Never delete user files; move them.

### 5.4 Hybrid Discovery v2 (TARGET — M9D)

M9D broadens discovery through independent source classes while keeping acceptance
deterministic:

1. direct ATS watchlists (Greenhouse, Lever, Ashby first; expand from measured demand);
2. authorized company/aggregator alert emails;
3. existing GitHub trackers;
4. public RSS, sitemaps, JSON-LD, and careers APIs;
5. selected public/licensed aggregators that prove marginal value in shadow evaluation;
6. approved-domain bounded crawling; and
7. an agentic scout that proposes companies, board tokens, source configurations, and
   candidate URLs through a versioned file contract.

The agentic scout is a control-plane tool outside `src.run_ingest`. It cannot call `src.db`,
edit approved config, promote its own source, or write canonical jobs. Initially every source
promotion requires user approval. Its proposal must include provenance, evidence URLs,
confidence, domains, source kind, suggested cadence, and recorded tool/model versions.

Transport selection is exclusive per fetch:

| Fetch purpose | Owner |
|---|---|
| structured ATS/API | `requests` + typed adapter |
| static leaf job page | existing HTTP/generic resolver |
| JS-heavy leaf page | Crawl4AI tier-2 resolver |
| bounded small-site traversal | evaluate Crawl4AI deep crawl first |
| durable multi-page queue/routing | Crawlee Python only if the M9D bake-off wins |
| cloud execution | allowlisted, pinned Apify Actor -> staging only |

Crawlee and Crawl4AI do not fetch the same URL in the same stage. All crawls have explicit
domain/path allowlists and page/depth/time/byte/cost budgets. The ≥2-second same-host delay,
honest User-Agent, no-login, and no-evasion rules apply regardless of library or platform.

The deterministic acceptance gateway validates schemas and URLs, applies policy, checks
content quality, canonicalizes, deduplicates, and atomically writes observations/jobs.
Snapshots/checkpoints advance only after durable acceptance or through a replayable protocol
that cannot outrun SQLite.

## 6. Resolution layer

### 6.1 Router (`resolve/__init__.py`)

`route(url) -> module` by hostname:

| Hostname contains | Resolver |
|---|---|
| `greenhouse.io` | greenhouse |
| `lever.co` | lever |
| `ashbyhq.com` | ashby |
| `myworkdayjobs.com` | workday |
| `amazon.jobs` | amazon_jobs |
| `jobright.com`, `jobright.ai` | jobright |
| anything else | generic (after the M6.0 wrapper checks below) |

Redirect handling: tracker links are often shorteners (e.g. `simplify.jobs/p/...`). The polite
session follows redirects; route on the **final** URL after redirects, not the original.

M6.0 wrapper unwrap (checked before falling through to generic, on the final URL): first
`wrapper.resolve_wrapper_map()` (known hostname → fixed ATS board, `config/wrapper_map.yaml`),
then `wrapper.resolve_gh_jid()` (URL carries a `gh_jid` query param → derive a Greenhouse board
token and resolve through the greenhouse resolver). Either path sets `resolver` to the
underlying resolver's name (e.g. `greenhouse`) and records the unwrapped URL in
`ResolvedJD.ats_url`/`jobs.ats_url`. See §6.3.

M6.2 jobright dispatch: hostname-routed like a normal resolver, but (like the M6.0 wrapper
checks) needs the already-fetched page HTML, so the router special-cases it to call
`jobright.resolve(final_url, response.text, session, browser_resolver=browser_resolver)`
directly rather than the uniform `module.resolve(url, session)` signature. See §6.3, §6.4.

M6.5 tier-2 fallback: `resolve(url, session, *, browser_resolver=False)` threads the toggle
(loaded from `config/sources.yaml`'s top-level `browser_resolver` key by
`run_ingest.load_browser_resolver_flag()`) through to both the generic-path fallback and the
jobright dispatch. When routing falls through to `generic` (no tier-1 resolver, wrapper-map,
or gh_jid unwrap matched) and `generic.resolve()` returns `None`, the router calls
`browser.resolve()` only if the toggle is on — a specific tier-1 resolver's failure (e.g.
greenhouse 404) never triggers it (see §6.4).

### 6.2 Polite HTTP session (`resolve/base.py`)

Single shared `requests.Session` with:
- `User-Agent: Mozilla/5.0 (compatible; job-pipeline personal use)`
- Timeout 15 s, `allow_redirects=True`
- Per-hostname rate limit: minimum 2 s between requests to the same host (simple in-memory
  timestamp map — the run is single-threaded). `PoliteSession.throttle(url)` applies this
  same wait without making a `requests` call, for the M6.5 browser resolver's non-`requests`
  fetches.
- On HTTP 429/403: log, count as a failed attempt, do NOT retry within the same run
- Never attempt login, cookies from a browser, or paywall/auth circumvention

### 6.3 Individual resolvers

Each exposes `resolve(url: str, session) -> ResolvedJD | None` (None = failure; router
increments `resolve_attempts`).

- **greenhouse.py**: extract board token + job id from URL (patterns:
  `boards.greenhouse.io/{board}/jobs/{id}`, `job-boards.greenhouse.io/{board}/jobs/{id}`).
  GET `https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}`. Response JSON has
  `title`, `location.name`, `content` (HTML-escaped HTML). Unescape, strip HTML to text.
- **lever.py**: pattern `jobs.lever.co/{company}/{id}`. GET
  `https://api.lever.co/v0/postings/{company}/{id}`. Fields: `text` (title),
  `categories.location`, `description` + `lists[]` (HTML). Strip to text.
- **ashby.py**: pattern `jobs.ashbyhq.com/{org}/{jobPostingId}`. Use Ashby's public posting
  API (`https://api.ashbyhq.com/posting-api/job-board/{org}` returns all postings with
  `descriptionHtml`; match by id). Strip to text.
- **workday.py**: URL pattern `https://{tenant}.wd{N}.myworkdayjobs.com/{lang?}/{site}/job/{slug}/{req}`.
  Corresponding JSON endpoint:
  `https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{slug}/{req}`
  (drop any language segment like `/en-US`). GET with `Accept: application/json`. Response
  `jobPostingInfo` contains `title`, `location`, `jobDescription` (HTML). This endpoint is
  unofficial: wrap in defensive parsing and treat any schema surprise as a soft failure.
- **generic.py**: GET the page; run `trafilatura.extract()` on the HTML. Success criteria:
  extracted text ≥ 400 characters AND contains at least one of the words
  {`responsibilit`, `qualif`, `requirement`, `experience`, `skills`} (case-insensitive) —
  otherwise treat as failure (likely got a nav shell or a JS-rendered page).
- **amazon_jobs.py** (M6.0(d)): pattern `amazon.jobs/{lang}/jobs/{id}`. The obvious per-job
  `{job_path}.json` endpoint is bot-gated (406 without a browser session); instead GET
  `https://www.amazon.jobs/en/search.json?base_query={id}` (public, not bot-gated) and match
  the result whose `job_path` contains `/jobs/{id}/` — defensive against the search endpoint
  returning unrelated hits. Fields: `title`, `description`, `basic_qualifications`,
  `preferred_qualifications` (HTML), `normalized_location`.
- **wrapper.py** (M6.0(b)-(c)): not hostname-routed — checked by the router before falling
  through to generic (§6.1). Two independent unwrap paths, both resolving through
  `greenhouse.py`'s API and setting `ResolvedJD.ats_url`:
  - `resolve_gh_jid(url, html_text, session)`: if `url` has a `gh_jid` query param, try the
    URL's second-level domain as the Greenhouse board token first, then (if that 404s) regex
    `html_text` (the wrapper page, already fetched by the router — no extra request) for
    `boards.greenhouse.io/{token}/jobs/` or `greenhouse.io/embed/job_board(?:/js)?\?for={token}`.
  - `resolve_wrapper_map(url, session, wrapper_map=None)`: looks up the URL's hostname in
    `config/wrapper_map.yaml` (schema: `{hostname: {ats, board, id_from}}`; only
    `ats: greenhouse` + `id_from: path` are implemented, matching the seeded `roblox` entry —
    extend when a new shape is actually needed, not speculatively).
- **jobright.py** (M6.2): jobright.com/jobright.ai postings never host the employer's literal
  JD, so this resolver signature is `resolve(url, html_text, session)` — the router passes it
  the page HTML it already fetched (§6.1). Two-part fix, in order:
  1. `find_ats_link(html_text)`: scan outbound anchors (host not jobright) for either a known
     ATS host (per §6.1's router table) or "Apply"/"Original" anchor text. On a match, re-route
     through the normal router and resolve via the underlying resolver; sets
     `jd_quality='ats'` and `ats_url` to the discovered link, `resolver` to the underlying
     resolver's name. Live-verified (2026-07-06): jobright's actual apply flow is
     client-rendered, so this path does not find a link in practice today — kept as the
     preferred path per spec, in case a page ever includes one statically.
  2. Fallback: parse the page's `__NEXT_DATA__` Next.js JSON blob (present on every jobright
     posting) for `props.pageProps.dataSource.jobResult`, and build `jd_text` from
     `jobSummary` + `coreResponsibilities` + `qualifications` (mustHave/preferredHave).
     `isH1bSponsor: true` → `"sponsor_likely"` in `flags`. Sets `resolver='jobright'`,
     `jd_quality='aggregator'` (still Jobright's own summary, not the employer's literal
     wording — Phase 3 tailoring requires `jd_quality='ats'`, so aggregator-quality
     SHORTLISTED rows surface in the digest's "needs your help" section asking the user to
     drop the real posting URL into `inbox/urls.txt`). Deviates from the kickoff doc's literal
     regex-based text-cleaning spec — see `DECISIONS.md` 2026-07-07.

HTML→text stripping: use a small shared helper (regex-free where possible; `html.unescape`
+ a minimal tag stripper, preserving list items as `- ` lines and paragraph breaks). Do not
add BeautifulSoup as a dependency unless the helper proves insufficient — if it does, ask.

### 6.4 Tier-2 browser resolver (`resolve/browser.py`, M6.5)

Three-tier resolution ladder:

1. **Tier 1** — structured resolvers + unwrap rules (§6.1/§6.3, unchanged). Always tried first.
2. **Tier 2** — `resolve/browser.py`, used only when routing fell through to `generic` and
   either the initial plain-`requests` fetch failed (non-200 — a bot-blocked host, e.g.
   qualtrics.com returns 410 to `requests` but renders fine in a headless browser) or it
   succeeded but `generic.resolve()` failed its quality heuristic — and only if
   `browser_resolver` is enabled. A blocked *tier-1* host (routed to a specific resolver, e.g.
   a Tesla-style Akamai block) does NOT get a tier-2 retry: only hosts with no tier-1 resolver
   qualify, so a real tier-1 schema break stays visible instead of being masked. Renders the
   page with `crawl4ai` and applies the *same* `generic.passes_quality()` heuristic (≥400
   chars + a JD keyword) to the rendered markdown before accepting.
3. **Tier 3** — `RESOLVE_FAILED` → digest "Needs your help" (unchanged).

Implementation:
- `BrowserClient` protocol: synchronous `start()`, `crawl(url)`, and `close()`.
- `Crawl4AIBrowserClient`: owns one event loop and one `crawl4ai.AsyncWebCrawler` for a
  resolution run. It uses `CacheMode.BYPASS`, keeps Crawl4AI behind a synchronous boundary,
  and raises `BrowserUnavailableError` for lifecycle/start/operation failures.
- `CircuitBreakingBrowserClient`: run-local wrapper around a `BrowserClient`. The first
  `BrowserUnavailableError` trips the breaker; subsequent browser-required rows fail fast
  with the same transient browser-unavailable outcome instead of retrying browser startup.
- `fetch_markdown(url, session, browser_client)` / `fetch_html(url, session, browser_client)`:
  both call `session.throttle(url)` first (§6.2) so browser fetches count against the same
  per-host rate limit, then `browser_client.crawl(url)`, returning `None` on
  `result.success is False`.
- `resolve(url, session, browser_client) -> ResolvedJD | None`: `fetch_markdown()` +
  `generic.passes_quality()`; on success, `resolver="browser"`, `jd_quality="ats"` (a
  rendered DOM is still the employer's own text, unlike jobright's aggregator summary).
- Deterministic rendering/markdown only — crawl4ai's LLM-extraction strategies are forbidden
  (no model calls inside `src/`, no API keys in the pipeline). No stealth/anti-bot-evasion:
  default browser fingerprint, honest behavior. A site that blocks a plain headless browser
  (e.g. tesla.com) is expected to stay tier-3 — this is not a bug to work around.
- M6.2/M6.10 Jobright ordering: `jobright.resolve()` checks static ATS links first, then
  accepts a valid static `__NEXT_DATA__` aggregator payload, and only then uses
  `browser.fetch_html()` to inspect rendered DOM for an ATS link. Browser work is not spent
  on every valid Jobright aggregator row merely to look for a possible upgrade link.
- Config: `browser_resolver: true` is a top-level key in `config/sources.yaml` (sibling to
  `sources:`, not per-source — the fallback applies pipeline-wide). Read by
  `run_ingest.load_browser_resolver_flag()` (default `False` if absent) and threaded through
  `run_ingest.run_resolution()` → `resolve.resolve(..., browser_resolver=...,
  browser_client=...)`. With the toggle off, behavior is byte-for-byte identical to
  pre-M6.5.
- Observability: `run_ingest.run_resolution()` tallies `tier1`/`tier2`/`manual` counts per run
  (tier2 = `ResolvedJD.resolver == "browser"`; manual = `db.record_resolve_failure()` returned
  `RESOLVE_FAILED` this run) and writes them to the new `runs.tier1_resolved`/`tier2_resolved`/
  `manual_failed` columns (§4.1) via `db.finish_run()`. See §8 for the digest line.

### 6.5 Resolution runtime hardening (CURRENT — M6.10 complete, 2026-07-15)

M6.10 changes runtime orchestration without weakening the three-tier content policy:

- A resolver attempt produces a typed orchestration outcome: resolved, content failure,
  transient infrastructure failure, or internal error. Only a content failure consumes
  `resolve_attempts`; connection resets, browser launch failures, and unexpected internal
  exceptions leave the job eligible without spending its content-failure budget.
- `run_resolution()` retains a final per-row `except Exception` isolation boundary, but an
  unexpected exception is logged with its traceback and recorded as an internal issue, not
  converted to `None` and counted as a content failure.
- Resolution accepts a separate deterministic `--resolve-limit N`; discovery's `--limit`
  semantics are unchanged. Selection is ordered by job id so bounded runs are repeatable.
- Production browser fallback uses one run-scoped `CircuitBreakingBrowserClient(
  Crawl4AIBrowserClient())`, not one Chromium launch per URL. If browser startup/lifecycle
  fails, a circuit breaker defers subsequent browser-required rows for the remainder of that
  run while tier-1 work continues. Tests mock the browser boundary and never launch a browser.
- Jobright uses a static ATS link when present, otherwise accepts its static
  `__NEXT_DATA__` aggregator payload before considering browser rendering. Browser work is
  not spent on every Jobright row merely to look for a possible upgrade link; shortlisted
  aggregator rows continue to use the existing digest/manual-original-posting path.
- A run interrupted by an exception or `KeyboardInterrupt` still receives `finished_at`,
  partial counters, and structured notes identifying it as aborted. Historical live-DB
  cleanup is a separate user-approved administrative action, never an automated migration.
- `main()` owns a mutable `ResolutionSummary` for the entire run. `finalize_run()` is the
  single run-finalization boundary: it closes the browser client first, logs close failures
  without blocking DB finalization, records partial `run_sources` resolved/failed counters,
  calls `db.finish_run()` once, and always writes valid JSON notes with `run_outcome`,
  `resolution_summary`, optional `discovery_issues`, and optional bounded `fatal_error`.

No schema migration or new dependency was added by M6.10. Task 8's live DB smoke completed
2026-07-15. Full details and acceptance criteria are in
`docs/superpowers/specs/2026-07-15-resolution-runtime-hardening-design.md`.

## 7. Eligibility policy v2 (`eligibility.py` + `prefilter.py`)

M6.11 replaces the legacy regex-only prefilter with a typed, validated, configuration-driven
eligibility policy. `config/eligibility.yaml` is the sole business-policy source for
country, opportunity type, start windows, role family, seniority, work authorization, and
review flag names. `config/location_taxonomy.yaml` is data vocabulary only. `config/filters.yaml`
is scoring-owned and currently retains only `score_threshold`.

The pure evaluator in `src/eligibility.py` performs no SQLite, network, browser, or LLM work.
`src/prefilter.py` is now only a gate adapter: it calls the pure evaluator and DB helpers in
`src/db.py`. Stable filter reasons are `eligibility:country`,
`eligibility:work_authorization`, `eligibility:opportunity_type`,
`eligibility:start_window`, `eligibility:role_family`,
`eligibility:role_family_excluded`, and `eligibility:seniority`.
`eligibility:role_family_excluded` (M6.12) is the title-only hard-exclude arm of the
role-family gate — a wrong-specialty title is rejected outright rather than falling through
to the JD-text include match that `eligibility:role_family` records.

There are two deterministic gates:

1. Pre-resolution gate over `DISCOVERED` rows, run in normal and `--resolve-only` modes before
   any HTTP session/browser work. Country is evaluated first; explicit non-US evidence filters
   immediately, while bare `Remote`, empty, or unrecognized locations defer rather than being
   guessed. Explicit disabled type or out-of-window internship evidence can also filter before
   resolution.
2. Post-resolution gate over `RESOLVED` rows, run immediately after resolution. It evaluates
   country, work authorization, opportunity type/start window, role family, seniority, and
   non-rejection flags using the full JD.

Initial policy: United States roles only; full-time roles with 2027 start evidence pass;
full-time roles with no stated start remain eligible with `start_date_unknown`; internships
require Spring 2027 or January-May 2027 evidence; explicit no-sponsorship and US-citizens-only
requirements filter; sponsorship silence passes; generic authorization language passes with
`authorization_ambiguous`.

`runs.notes` includes an `eligibility_summary` with `pre_resolution` and `post_resolution`
gate counts. `scripts/eligibility_impact.py` previews existing-row effects read-only by
default. Its guarded apply path requires explicit confirmation and a non-existing backup path,
then applies the freshly recomputed transition set transactionally. Task 10 live preview,
apply, and smoke remain user-supervised and are not run during offline implementation.

Every `FILTERED_OUT` row keeps its `jd_text` and records a one-line `filter_reason`.

### 7.5 Freshness & recycling defense (`freshness.py`, M6.8)

Config in `config/freshness.yaml`: `stale_days: 21`, `reopen_days: 45`, `liveness_days: 5`.
Four independent behaviors:

1. **Stale-at-discovery flag.** `db.insert_discovered()`: a genuinely new row whose
   `date_posted` is present and older than `stale_days` gets `flags=["stale_listing"]` at
   insert time. Missing `date_posted` is never flagged (no evidence either way). This flag
   must survive resolution — `db.mark_resolved()` merges (unions) `ResolvedJD.flags` into the
   row's existing flags rather than overwriting, the same class of fix as M6.2's prefilter
   flag-clobbering bug.
2. **Repost bookkeeping + content-based repost detection.** Two mechanisms:
   - Dedup-key conflict (same posting rediscovered): `db.insert_discovered()` always touches
     `last_seen_at`/`repost_count` on the existing row (§4.3), regardless of source priority.
   - Content-based (a *new* dedup_key that's really the same posting under different title
     wording/location): after each successful resolve, `run_ingest.run_resolution()` calls
     `freshness.find_content_repost(conn, company, jd_text, exclude_row_id=...)`, which scans
     TERMINAL rows (`FILTERED_OUT`/`REJECTED`/`APPLIED`/`CLOSED`) at the same `norm(company)`
     for a 5-word-shingle Jaccard ≥ 0.85 match (`src/textsim.py`, shared with
     `export_batch.py`'s clustering). On a match, `freshness.record_content_repost()` flags
     the new row `repost` and writes a rendered note directly (`db.add_flag_and_note()`), e.g.
     `"recycled: you skipped job #57 (FILTERED_OUT) on 2026-06-01"` — the digest shows this
     verbatim rather than re-deriving it from structured fields.
3. **Resurfacing rule.** Inside the same dedup-key-conflict branch: if the existing row is
   `RESOLVE_FAILED` or `CLOSED` and its `last_seen_at` is missing or older than `reopen_days`,
   it's reset to `DISCOVERED` (flag `reopened`, `resolve_attempts`/`filter_reason` cleared,
   `url`/`source` updated to the fresh discovery) — see §4.2. Any other terminal status is
   left untouched by this path (content-repost detection, not resurfacing, is what flags
   those).
4. **Liveness recheck.** `run_ingest.main()` calls `freshness.run_liveness_recheck(conn,
   session, liveness_days)` once per run, right after the pre-filter and before the digest is
   built. For every `SHORTLISTED`/`TAILORED` row whose `last_seen_at` is missing or older than
   `liveness_days`, one polite GET of `ats_url` (falling back to `url`): a 404/410 response
   marks the row `CLOSED` (`db.mark_closed()`, note records the status code); any other
   response (200, 5xx, timeout) just touches `last_seen_at` — deliberately scoped down from
   the original "or absence from the board's live listing" spec, which would require
   per-ATS scraping logic; see DECISIONS.md. A `RequestException` is swallowed (row stays
   unchecked, retried next run) rather than failing the whole run over one dead link.

I13 (audit hook for SHORTLISTED rows overdue a liveness check, and high-score `stale_listing`
rows whose rationale doesn't mention staleness) is deferred to M7 (`SELF_HEALING.md` §5), not
built in M6.8.

## 8. Digest (`digest.py`)

Written to `data/digests/YYYY-MM-DD.md` at the end of every run (overwrite if re-run same
day). Sections, in order:

1. **Run summary** — counts from the `runs` row (discovered / resolved / failed / filtered),
   plus a **Resolution tiers** line (M6.5): `t1: N, t2: N, manual: N` from
   `tier1_resolved`/`tier2_resolved`/`manual_failed`, so the user can see at a glance whether
   tier 2 (the browser resolver) is earning its cost. If `runs.notes` contains structured
   M9D-0 discovery issues, a **Run warnings** block follows with `source [stage/type]:
   message`; legacy non-JSON notes render as a raw warning line. Followed by a **Per-source** table
   (M6.0(3)) from `run_sources`: Source | Discovered | Inserted | Resolved | Failed, one row
   per enabled adapter for this run — a source contributing zero rows is a visible `0` row,
   not an absent one.
2. **New & resolved** — table: Company | Title | Location | Flags | Source | Link. Sorted by
   company. These are the rows awaiting scoring (Phase 2) — for now, the user's reading list.
3. **Needs your help** — `RESOLVE_FAILED` rows (and rows at 1–2 failed attempts, marked
   "retrying"): Company | Title | URL | last error. Instruction line reminding the user they
   can paste the JD into `inbox/` using the file format from §5.3. Followed by "Needs the
   original posting" (M6.2, aggregator-quality SHORTLISTED rows) and, when non-empty (M6.8):
   **Recycled & reopened** — `RESOLVED` rows carrying `repost`/`reopened` flags, Company |
   Title | Note (the rendered note from §7.5 item 2/3, shown verbatim); and **Closed (dead
   links)** — `CLOSED` rows, Company | Title | Note (liveness-recheck status code, §7.5 item
   4). Both are omitted entirely when there's nothing to show.
4. **Filtered out** — collapsed one-liner per row: `Company — Title (reason)`. This section
   exists so bad filter rules are caught by eyeball.

## 9. CLI (`run_ingest.py`)

```
python -m src.run_ingest [--dry-run] [--source NAME] [--resolve-only] [--discover-only]
                         [--limit N] [--resolve-limit N] [--db PATH] [--snapshot-dir DIR]
```

- Default: discover → dedupe/insert → resolve (all `DISCOVERED` with attempts < 3) →
  prefilter → digest. Log to stderr (INFO), plus a `runs` row.
- `--dry-run`: full pipeline, no DB writes, no snapshot writes; print would-be digest to stdout.
- `--limit N`: cap new insertions per source; deferred rows remain eligible through
  `pending_keys`.
- `--resolve-limit N`: cap the number of `DISCOVERED` rows attempted by resolution, ordered
  by row id. This is independent of discovery `--limit` and is the required flag for bounded
  live smokes.
- `--snapshot-dir DIR`: override tracker checkpoint location, primarily for isolated smoke
  runs and tests.
- Exit code 0 on success even if some resolutions failed (failures are data, not errors);
  nonzero on infrastructure errors, all selected discovery sources failing, or checkpoint
  commit failure after durable insert. Partial source failure is nonfatal and visible in
  `runs.notes`/digest warnings.
- `runs.notes` is valid JSON for new runs. It always includes `run_outcome` and
  `resolution_summary`; aborted runs include bounded `fatal_error` diagnostics, and runs with
  discovery issues include `discovery_issues`.

Idempotency requirement (testable): running the command twice back-to-back must produce a
second `runs` row with `new_jobs=0` and no row modifications other than that `runs` row,
legitimate resolve retries, and (M6.8) `last_seen_at`/`repost_count` bumping by exactly the
designed amount on rows whose posting is rediscovered (§7.5) — everything else must be
byte-identical.

## 10. Scheduling (M4)

Detect the user's OS at milestone time and set up ONE of:
- macOS: `launchd` plist in `~/Library/LaunchAgents` (survives sleep better than cron)
- Linux: user crontab
- Windows: Task Scheduler via `schtasks`

Run daily at a fixed local time chosen by the user. The job runs
`python -m src.run_ingest` and, on completion, opens/prints the digest path.
Include a `scripts/install_schedule.*` helper and document uninstall.

## 11. Phase 2+ interfaces (design now, build later)

- **Scoring**: a script `scripts/export_batch.py` dumps all `RESOLVED` rows (id, company,
  title, jd_text truncated to ~6k chars each) to `data/batch/YYYY-MM-DD.json`. A headless
  Claude Code invocation reads that file plus `config/profile_summary.md` and writes
  `data/batch/YYYY-MM-DD.scored.json` (`[{id, row_ids, fit_score 0-10, base_variant (`backend`
  or `ml`, closed enum), missing_keywords[], rationale ≤160 chars}]`). A deterministic script
  validates the JSON against a schema and writes scores back to SQLite (`SCORED`; ≥ threshold →
  `SHORTLISTED`). Claude never touches the DB directly — files in, files out, validation in
  between.
- **Calibration Contract v2 (2026-07-16)**: `scripts/calibration_packet.py start` takes an
  exported batch and writes an immutable `data/calibration/YYYY-MM-DD.batch.json` plus a
  metadata-only `YYYY-MM-DD.interest.md` worksheet. `reveal` validates completed interest
  calls, opens SQLite read-only, retrieves complete untruncated representative JDs through
  `src.db.calibration_jobs_by_ids()`, and writes `YYYY-MM-DD.fit.md`. `scripts/calibration_report.py`
  compares scored output only against JD-informed `fit_call` labels. `interest_call` remains
  diagnostic, not model ground truth. APPLY and MAYBE are positive at the 7+ human-review
  shortlist boundary; SKIP is negative. Legacy `data/calibration/2026-07-12.user.md` is
  preserved as historical interest-only evidence and cannot be used as fit ground truth.
- **Sub-batched scoring (M6.7 item 1, `scripts/score_batch.py`)**: rather than one Claude
  invocation over the whole exported batch, `score_batch()` splits it into chunks of at most
  6 objects (`CHUNK_SIZE`), writes each chunk to `data/batch/chunk_N.json`, and invokes
  `claude -p` once per chunk with the same prompt body as `docs/scoring_prompt.md` (only the
  file-path instructions are overridden — see `build_chunk_prompt()`). Chunk results are
  concatenated into the same `*.scored.json` shape `import_scores.py` already validates
  (row-coverage is checked across the concatenated whole, not per chunk). Rationale
  (RecruitBench, Sood 2026): monolithic scoring of large pools under-scores true positives;
  parallel ~6-object batches doubled recall at unchanged precision in that benchmark.
- **Synthetic score-band stress suite (M6.7 item 2, `scripts/scoring_stress.py`)**: 10
  synthetic JDs in `tests/fixtures/scoring_stress/cases.json`, each paired with an
  `expected_band` derived from `docs/scoring_prompt.md`'s anchored scale (perfect backend/
  LLM-agent match, strong-overlap-minor-gap, two partial-overlap variants, wrong specialty,
  hard-requirement-miss-years, sponsorship-risk cap, keyword-stuffed, stale/vague — the last
  two don't have doc-specified bands, so their bands were chosen by the implementer and
  approved by the user; see DECISIONS.md). `scoring_stress.py` builds a batch from the
  fixture, scores it via `score_batch.score_batch()`, and reports per-case band adherence.
  Run at calibration start and after ANY change to `scoring_prompt.md`/`profile_summary.md`
  (both are PROTECTED per `SELF_HEALING.md` §4 once calibration locks them).
- **Exemplar injection (M6.7 item 3)**: deferred until ≥20 calibration labels exist (not
  built in M6.7) — see `PHASE2_KICKOFF.md`.
- **Tailoring**: see `docs/TAILORING_SPEC.md`.
- **Authorized alert-email adapter** (company, LinkedIn, Indeed, Jobright, and similar alerts):
  an M9D deterministic adapter using the same staged-candidate/`DiscoveredJob` boundary.
  Receiving user-authorized alerts is permitted; scraping those platforms is not.
- **Agentic source scout** (M9D): separate control-plane invocation writes versioned source
  proposals and candidate artifacts. A deterministic importer rejects malformed, untrusted,
  unapproved, or out-of-budget output before any database write.

## 12. Security & etiquette (hard rules)

- Never scrape LinkedIn. LinkedIn jobs enter only via the manual inbox or (later) alert emails.
- Never bypass auth, CAPTCHAs, or bot detection anywhere.
- Do not use proxy/session/fingerprint features to evade resistance, even if a selected
  crawler or Actor supports them.
- Respect the rate limits in §6.2 even when it makes runs slower.
- Treat all page text and Actor output as untrusted data, never tool instructions. The scout
  receives least privilege, explicit budgets, and no direct DB credentials.
- Public Apify Actors are never selected dynamically in unattended production. Recurring use
  requires an allowlisted Actor and recorded build/version/input/run/dataset metadata.
- `data/`, `snapshots/`, `inbox/processed/`, `.env` are gitignored. No tokens in code.
- All timestamps stored in UTC ISO-8601; the digest may render local time.
