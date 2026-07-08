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

## 2026-07-05 — M6.0 diagnosis: dark sources, per PHASE2_KICKOFF.md

PHASE2_KICKOFF.md frames the 24 stuck `tracker_vansh` rows as a systematic resolver
defect ("not flakiness") and specifically calls the Ashby case "a defect, not a gap."
Live testing before writing any fix contradicts that framing — this reaffirms and
extends the M2 finding above (link rot, not a resolver bug), which the kickoff doc
apparently didn't account for:

- **Ashby** (`creditgenie`): resolver verified end-to-end against a currently-live
  posting on the same board (title + full JD returned correctly). The specific stuck
  job id is absent from the board's current listing entirely — the posting closed
  between discovery (07-04) and resolution (07-05). No code defect.
- **gh_jid trio** (amperity, esri, linksquares): derived board tokens correctly
  (`amperity`, `esri`, `linksquaresinc` — confirmed `gh_jid` *is* literally the
  Greenhouse job id via a live job's `absolute_url` field). All three specific job
  ids 404 on their correctly-derived boards. Postings gone, not a derivation bug.
- **Roblox wrapper**: mapping confirmed correct — a live Roblox posting
  (`careers.roblox.com/jobs/7142298`) resolves 1:1 to Greenhouse board `roblox`,
  same numeric id. The two stuck ids (6.7M range) are far below the current active
  range (7.1–7.4M) and 404 directly. Old/removed postings.
- **Amazon.jobs** (5 rows), **Qualtrics**, **iCIMS**: all 404/410 live right now.
  Removed.
- **Tesla** (6 rows): still 403, bot-protected as already documented in M2.

Conclusion: the router/resolver *mechanisms* for gh_jid-unwrap, a wrapper map, and a
dedicated Amazon resolver are genuine, real gaps (M6.0 builds them anyway — they'll
catch current/future postings of these shapes), but building them will not flip
these 24 specific rows to RESOLVED; the underlying postings churned out before
resolution ran. Per CLAUDE.md directive #1 (docs vs. reality), flagging this rather
than silently building toward a false acceptance claim. User approved: build the
resolvers regardless, expect most of today's 24 rows to land in `RESOLVE_FAILED` /
digest "needs your help" even after the fix, since that's the correct terminal state
for an expired posting.

One-off repairs performed before the first repaired run (documented per M6.0):
- `UPDATE jobs SET resolve_attempts = 0 WHERE source = 'tracker_vansh' AND
  resolve_attempts >= 2` — un-sticks the 24 rows so the new resolver mechanisms get
  a fair first attempt against them (most will still fail as expired, correctly).
- Deleted `snapshots/tracker_simplify.json`.

## 2026-07-05 — M6.0 diagnosis: `tracker_simplify` silent zero

Root cause confirmed (not the parsing/diff logic, which is correct and already
covered by `test_tracker_simplify.py`): `snapshots/tracker_simplify.json` existed on
disk with 1901 dedup keys *before* any `tracker_simplify` row ever reached
`jobs.db` (0 rows for that source, despite `tracker_jobright` and `tracker_vansh`
both having real rows from the same live run). `diff_new_jobs()` writes the snapshot
unconditionally on every non-dry call, independent of whether the caller goes on to
insert the returned jobs into the DB. Some earlier non-dry, out-of-band call to
`tracker_simplify.discover()` — almost certainly a manual verification during M3
development that pointed at the real `snapshots/` dir instead of a `tmp_path` — had
already advanced the "seen" set to include essentially all currently-listed
postings, with no corresponding DB insert. Every real pipeline run since has
therefore correctly seen "0 new" against that poisoned baseline; this was not a
silently swallowed exception. Fixed by deleting the stale snapshot (see above) so
the next run treats current listings as new. No code change needed — the diff
contract (pure snapshot diff, unaware of DB state) is working as designed; the
recurrence-prevention measure is the M6.0(3) per-source `run_sources` observability,
which would have made this zero-row source visible on day one instead of silent.

## 2026-07-05 — M6.1 content-hash duplicate collapse (export-time)

Implemented per `PHASE2_KICKOFF.md`'s M6.1 spec: `scripts/export_batch.py` now
clusters RESOLVED rows before writing the batch, instead of exporting one object
per row.

- Clustering runs in a single pass over rows ordered by `id`: a row joins an
  existing cluster if `norm(company)` matches AND either (a) its
  `content_hash` (sha256 of `normalize_jd(jd_text)`) exactly matches the
  cluster's, or (b) `norm(title)` matches AND the 5-word-shingle Jaccard
  similarity of its `jd_text` to the cluster representative's is ≥ 0.85.
  Otherwise it starts a new cluster as its own representative. This folds the
  kickoff doc's two separately-described grouping rules (exact content-hash,
  near-dup by title) into one clustering pass rather than two independent
  group-bys, since a row can only sensibly belong to one output object.
- `normalize_jd`: lowercases, strips lines matching the "· N minutes/hours/days
  ago" pattern, collapses whitespace. Used for both the hash and the shingle
  input.
- Batch objects gained `"row_ids": [...]` (all ids folded into that
  representative, sorted); `"id"` stays the lowest/first-seen id in the group
  for backward compat, per spec.
- `scripts/import_scores.py` now requires `row_ids` on every scored entry
  (previously just `id`), applies the score/status update to every id in that
  list, and validates that every `row_ids` entry: exists in the DB, is
  disjoint across entries in the same scored file (a row_id claimed by two
  entries is rejected — "must be covered exactly once"), and includes the
  entry's own `id`. `docs/scoring_prompt.md` updated to tell the scorer to
  copy `row_ids` verbatim per object.
- Live re-export of the current `data/jobs.db` (28 RESOLVED objects after
  clustering) confirms real collapsing: e.g. 9 Relativity rows (up from the
  kickoff doc's 6, since more were discovered/resolved since) collapsed to one
  object, two Neuralink location-variant pairs collapsed correctly, unrelated
  companies untouched.

## 2026-07-07 — M6.2 jobright unwrap: JSON extraction instead of regex text-cleaning

PHASE2_KICKOFF.md's M6.2 fallback path assumes scraping the rendered page's visible
text and regex-stripping aggregator chrome (funding/trend tables, CamelCase tag-soup
lines, "H1B Sponsor Likely" text markers). Recording a real fixture
(`tests/fixtures/jobright_amazon_page.body`) found the page instead embeds a
structured `__NEXT_DATA__` Next.js JSON blob containing `jobSummary`,
`coreResponsibilities`, `qualifications` (mustHave/preferredHave), and explicit
booleans (`isH1bSponsor`, `isWorkAuthRequired`, `isCitizenOnly`,
`isClearanceRequired`) alongside `jobTitle`/`jobLocation`. This is strictly more
robust than regex text-cleaning (no tag-soup heuristics, no risk of a changed page
layout silently breaking extraction) and gives an exact sponsor signal instead of a
text-pattern guess.

Approved deviation (per CLAUDE.md prime directive #1): `src/resolve/jobright.py`
parses `__NEXT_DATA__` directly for the fallback path rather than implementing the
doc's regex-based cleaner. `jd_quality='aggregator'` still applies — this is still
Jobright's own summary, not the employer's literal wording (doc finding #2's
caveat holds). `isH1bSponsor=True` maps to the `sponsor_likely` flag.

Path 1 (outbound ATS link extraction) is implemented as specced: scan anchors for a
known ATS host or "Apply"/"Original" text, re-routing through the normal router on a
match. Live-verified (`jobright.ai/jobs/info/6a1882dfc2a87d6cd3df1c67`, BAE Systems):
no outbound ATS link is present in the static HTML — the real apply flow is
client-rendered — so path 1 does not fire in practice today; this matches the saved
fixture's own live verification and the M6.6 punch-list finding that fallback
cleaning is the dominant path for jobright rows.

Also fixed a flag-clobbering bug found while wiring `sponsor_likely` through:
`prefilter.run_prefilter` overwrote the `flags` column wholesale whenever its own
`jd_flags` config matched, silently discarding any resolver-set flags (e.g. this
new `sponsor_likely`). Changed to merge resolver-set and prefilter-set flags
(union, deduped) rather than overwrite.

Not done this session (left for M6.6, which already covers re-auditing/re-export):
the ~40 jobright rows already `RESOLVED` via the old generic resolver were left
as-is — idempotency means they won't be reprocessed by the new resolver
automatically. Reprocessing them (reset to `DISCOVERED`, documented one-off) is
M6.6's job per its punch-list acceptance criteria, not M6.2's.

## M6.3 — Export schema v2 (2026-07-08)

PHASE2_KICKOFF.md specifies `locations` as an aggregate across a cluster's
`row_ids` ("distinct locations across the group, in id order") but doesn't say
whether `flags`/`jd_quality` should aggregate the same way or come from the
representative row alone. Decision: `flags` and `jd_quality`, like `company`/
`title`/`jd_text`, are taken from the representative row only, not unioned
across the group. Rationale: the exported `jd_text` is always the
representative's own text, so `jd_quality` describing "how clean is this
jd_text" only makes sense tied to that same row — unioning in an aggregator
flag from a sibling row whose text isn't shown would mislabel a genuinely
`ats`-quality representative. `locations` is the one field the spec explicitly
calls out as cluster-wide, because the whole point of clustering near-dup rows
is that they differ mainly by location.

`scripts/import_scores.py` was left unchanged. The scored-file schema (what
Claude writes back) is a fixed, narrow contract — `id, row_ids, fit_score,
base_variant, missing_keywords, rationale` — and `locations`/`flags`/
`jd_quality` are batch-input context for scoring, not fields the scorer
returns. `docs/scoring_prompt.md` step 2 now documents the v2 input shape;
no validation changes were needed for `import_scores.py` to "match" it since
its contract never included those fields.
