# DECISIONS.md — approved deviations & verified facts

One dated entry per decision/finding. Newest last.

## 2026-07-04 — vanshb03/New-Grad-2027 verification (M1)

- Default branch is `dev`, not `main`. Hardcoded in `discover/tracker_vansh.py`.
- A machine-readable listings file exists at `.github/scripts/listings.json`
  (confirmed via `GET /repos/vanshb03/New-Grad-2027/contents/.github/scripts`).
  Per ARCHITECTURE §5.2 this is preferred over the README table. Schema (list of
  objects): `date_updated` (unix ts), `url`, `company_name`, `title`,
  `locations` (list[str]), `sponsorship`, `active` (bool), `source`, `id`,
  `date_posted` (unix ts), `company_url`, `is_visible` (bool). Rows are treated
  as closed/skip when `active` is `false` or `is_visible` is `false`.
- README table (fallback path, kept in sync for when/if the JSON disappears):
  header `| Company | Role | Location | Application/Link | Date Posted |`,
  matches ARCHITECTURE §5.2 exactly. Closed rows render `🔒` in the
  Application/Link cell instead of an `<a href>` — no URL, so these are
  skipped. No live `↳` (inherited-company) rows were observed in the current
  table, but the parser still implements inheritance defensively since the
  format is documented by the repo's own legend.
- Real README (`dev` branch, as fetched) saved as
  `tests/fixtures/vansh_readme.md`. A trimmed (30-row) real sample of
  `listings.json` saved as `tests/fixtures/vansh_listings.json`, plus a
  `vansh_listings_plus2.json` variant with 2 additional synthetic rows for the
  snapshot-diff test.

## 2026-07-04 — Resolver endpoint verification (M2)

- None of the 25 M1-discovered rows (all `tracker_vansh`) matched the
  greenhouse/lever/workday URL patterns — that tracker happens to route
  postings through vanity company domains, Amazon, Tesla, and ATS platforms
  outside the five resolvers. Only one M1 row matched a resolver pattern:
  Credit Genie's `jobs.ashbyhq.com` posting (used for the ashby fixture, with
  a currently-listed job id since the original M1 id had since closed).
  Greenhouse, lever, and workday fixtures were recorded from real, currently
  open postings found via web search (Thinking Machines Lab / Palantir /
  Cadence) — same public, unauthenticated API endpoints ARCHITECTURE §6.3
  specifies, just not sourced from this DB. Not a deviation from the
  documented endpoints, so no approval gate applies; noting it here only
  because the M2 prompt implied fixtures would come from M1 data specifically.
- Confirmed both `boards.greenhouse.io` and `job-boards.greenhouse.io` map to
  the same `boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}` endpoint.
- Workday: several tenants (`nvidia.wd5`, `stord.wd503`) return HTTP 403
  `{"errorCode":"S22","message":"permission denied"}` from Cloudflare-fronted
  bot protection on the `/wday/cxs/...` JSON endpoint even with a plain
  `requests` GET — not specific to our resolver logic. `cadence.wd1` did not
  trigger this and was used for the fixture. Per CLAUDE.md etiquette rules,
  on 403 the resolver logs and counts a failed attempt; it does not retry or
  attempt to evade the block. Real-world Workday success rate may therefore
  run lower than other resolvers — flagged for the live smoke test rather
  than acted on unprompted.
- Simplify.jobs shortener redirect fixture was not recorded: no
  `tracker_simplify` adapter exists yet (that's M3), so no real shortener
  link was available from our own data. Per the M2 acceptance criteria's
  explicit fallback, the router's redirect-then-route behavior is instead
  covered by a unit test on final URLs only (see `tests/test_resolve_router.py`).
- `ResolvedJD` (ARCHITECTURE §4.4) has `raw_title`/`raw_location` but no
  `raw_company`, while §5.3's inbox note says resolution "backfills
  title/company." Implemented the backfill using only the fields the
  dataclass actually has: `db.mark_resolved` overwrites `title` when it still
  equals the URL's hostname (the inbox placeholder) and overwrites `location`
  when it's still NULL; company is left untouched since no source field
  exists for it. Flagging the doc/dataclass mismatch rather than guessing at
  a `raw_company` field that isn't specified anywhere.
- Live smoke test (`--resolve-only` against the real M1 `data/jobs.db`, 25
  `tracker_vansh` rows): 1/25 resolved (4%), well under the ~70% ballpark.
  Per the acceptance criteria, this is reported rather than acted on by
  adding new resolvers unprompted. Root causes, by domain:
  - `amazon.jobs` (4), `careers.roblox.com` (2), `qualtrics.com` (1),
    `esri.com` (1), `careers.peraton.com` (1),
    `canada-appliedsystems.icims.com` (1): posting now 404/410 — link rot,
    not a resolver bug (these postings were live when discovered but have
    since closed).
  - `tesla.com` (6): consistent HTTP 403, anti-bot blocking on direct
    fetch — no login/CAPTCHA bypass attempted per CLAUDE.md etiquette rule.
  - `amperity.com` (1): HTTP 429 on the single fetch attempt (no retry,
    per architecture — counted as one failed attempt).
  - `jobs.ashbyhq.com/creditgenie` (1): the specific job id from M1 has
    since closed and is no longer in the org's live posting list (ashby
    resolver correctly returns `None`, matching its own unit tests).
  - `join.softheon.com`, `jobs.bentley.com`,
    `recruiting.ultipro.com`, `linksquares.com`,
    `thorsolutionsllc.applytojob.com` (5): JS-rendered or nav-shell pages —
    trafilatura extracts nothing or a nav shell below the keyword/length
    heuristic. Expected given the "no BeautifulSoup/Playwright" constraint.
  - The one success: `careers.qualcomm.com` via the generic resolver.
  A more representative rate should come from resolving jobs closer to
  their discovery time in the normal daily-run flow (once M4 schedules it)
  rather than jobs that already sat for a while.

## 2026-07-05 — Remaining discovery adapters + manual inbox (M3)

- SimplifyJobs/New-Grad-Positions: default branch `dev` (confirmed via the
  GitHub API), `.github/scripts/listings.json` exists with the identical
  schema to vansh's fork of the same tracker infra. `simplify_listings.json`
  fixture is a trimmed sample (20 active + 10 inactive of 17,565 real
  entries — the live file is ~11.8MB) with a hand-built `_plus2` variant for
  the snapshot-diff test, following the same pattern as the vansh fixtures.
- jobright-ai/2026-Software-Engineer-New-Grad: default branch `master`
  (differs from vansh/Simplify's `dev`); `.github/scripts/listings.json`
  returns 404, so this adapter always falls back to the README table. That
  table's header is `Company | Job Title | Location | Work Model | Date
  Posted` — no dedicated `Application/Link` column; the apply URL is a
  markdown link embedded in the `Job Title` cell instead of vansh's HTML
  `<a href>` in a separate column. `tracker_common.parse_readme_table` was
  generalized to accept column-name aliases and to fall back to extracting a
  markdown link from the title cell when no link column is found, rather
  than writing a second bespoke parser.
- Extracted the shared JSON-probe / README-table / snapshot-diff logic from
  `tracker_vansh.py` (M1) into `discover/tracker_common.py` per the M3 task
  list; `tracker_vansh.py`'s public functions (`parse_listings_json`,
  `parse_readme_table`, `diff_new_jobs`, `discover`) keep their exact M1
  signatures so the M1 tests needed no changes.
- Since jobright repos may be added later by the user with an unknown
  default branch (the sources.yaml comment says as much), `tracker_jobright`
  looks up each configured repo's default branch via the GitHub API at
  discovery time (falling back to `master` on any API error) instead of
  hardcoding it, unlike vansh/Simplify where the branch is fixed per-adapter.
- `discover_all()` (moved into `discover/__init__.py` as the ARCHITECTURE
  §5.1-specified registry) only iterates the three tracker adapters. The
  manual inbox (`inbox_manual.py`) is deliberately *not* registered there and
  is called directly from `run_ingest.py` instead: §5.3 requires MD-paste
  rows to be inserted **and** immediately marked `RESOLVED`, and requires
  moving processed files / rewriting `urls.txt` based on which lines
  actually became DB rows — none of that fits the uniform
  `discover(config) -> list[DiscoveredJob]` contract that trackers use,
  since it needs the DB connection and reports back which files to move.
  Flagging this as a deliberate adapter-contract exception rather than
  forcing inbox into the same shape.
- Known gap in the inbox URL-line path: per §5.3 an unresolved URL gets
  placeholder `company="unknown"`, `title=<hostname>` (matching
  `db.mark_resolved`'s existing placeholder-detection check, which compares
  `title` against the URL's hostname to decide whether to backfill). Because
  `dedup_key` is computed from `company`/`title`/`location` only, two
  still-unresolved inbox URLs on the same hostname collide to the same key
  and the second silently reuses the first's row. Unlikely to matter for a
  single-user manual inbox (few pending links at once, typically on
  different domains), but noted here rather than quietly changing the
  placeholder scheme beyond what §5.3 specifies.
