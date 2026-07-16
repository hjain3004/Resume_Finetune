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

## M6.4 — Scoring prompt corrections (2026-07-08)

`base_variant` is now a closed enum (`backend` or `ml`) enforced in
`_validate_entry` via `ALLOWED_BASE_VARIANTS`, matching the two variants
actually defined in `config/profile_summary.md` (the spec's `frontend`
example never had a matching resume variant). This is the only code change;
everything else in the spec — the anchored 0–10 scale, the location/flags
weighting, ignoring residual aggregator noise, and the `sponsorship_risk`
score cap — is guidance given to the headless Claude call in
`docs/scoring_prompt.md`, not something `import_scores.py` re-derives or
enforces from the DB. Rationale: the prompt already has full context
(locations, flags, jd_quality, jd_text) to apply these judgment calls; adding
a second, code-side enforcement layer (e.g. re-checking `sponsorship_risk`
against the DB and clamping the score) would duplicate logic the deterministic
layer has no principled way to apply consistently with the prompt's stated
rationale requirement ("with the rationale noting it") without the DB write
also rewriting `rationale` text — which is out of scope for what
`import_scores.py` is meant to validate (structural/schema correctness), not
rewrite. The `base_variant` enum is different: it's a closed, fully
enumerable set with no judgment involved, so it belongs in the deterministic
validator, same as the existing `fit_score` range and `rationale` length
checks.

`docs/scoring_prompt.md` also now tells Claude not to run
`scripts/import_scores.py` itself — the wrapper runs it after the headless
call returns, per the spec ("The wrapper (not Claude) runs `import_scores.py`
after the headless call").

## M6.5 — Tier-2 browser resolver placement and reuse (2026-07-08)

The kickoff doc specifies the `browser_resolver` toggle lives "in
`config/sources.yaml`" without saying exactly where. It's a top-level key
(`browser_resolver: true`), a sibling of `sources:`, not a per-source flag —
the tier-2 fallback is a pipeline-wide behavior (any URL that falls through
to `generic.py` can hit it), not something that varies by discovery adapter.
`run_ingest.load_browser_resolver_flag()` reads it independently of
`load_sources_config()` (which still returns only the `sources:` sub-dict,
unchanged, so existing tests patching its return value are unaffected).

Tier-2 only fires when the router falls through to `generic.py` and
`generic.resolve()` fails its quality heuristic — never for a URL that
matched a specific tier-1 resolver (greenhouse/lever/ashby/workday/
amazon_jobs) that then failed. A specific resolver failing usually means a
real schema break (bad board token, API shape changed) that a browser render
won't fix, and silently masking that with a browser fallback would hide the
break instead of surfacing it. This matches the kickoff doc's wording
("used ONLY when no tier-1 resolver applies AND `generic.py` fails").

Per-tier counts (`tier1_resolved`/`tier2_resolved`/`manual_failed`) are new
columns on `runs`, populated by `run_ingest.run_resolution()` tallying by
`ResolvedJD.resolver` (`"browser"` → tier2, anything else on success → tier1)
and by `db.record_resolve_failure()`'s returned status (`RESOLVE_FAILED` this
run → manual). This is a run-scoped snapshot, not a lifetime count of rows
in `RESOLVE_FAILED` (the digest's "Needs your help" table already shows the
full lifetime list) — it answers "how did *this run's* resolutions break
down," which is what the acceptance criterion ("whether tier 2 is earning
its 400MB") is asking about.

`resolve/browser.py` exposes `fetch_markdown()` and `fetch_html()` as two
thin wrappers over one internal `_crawl()`/`_crawl_async()` seam (the only
thing tests mock — no real browser in pytest). `jobright.py`'s rendered-DOM
reuse (`find_ats_link()` retried against `fetch_html()`'s output) only
replaces the *input* to the existing `find_ats_link()` regex scan; the
`__NEXT_DATA__` aggregator fallback is untouched and still runs against the
original static `html_text` if no link is found even after rendering.

Live smoke run (2026-07-08) surfaced a gap the test suite didn't catch: the
router's very first check, `if response.status_code != 200: return None`, ran
*before* any tier-2 attempt — so a host that plain `requests` can't reach at
all (qualtrics.com returns `410` to `requests` but renders fine for crawl4ai's
headless browser — real bot detection keyed on the HTTP client, not the URL)
never got a chance at tier 2, exactly the case tier 2 exists for. Fixed by
retrying via `browser.resolve(url, session)` on a non-200 initial fetch, but
only when `route(url) is generic` (a blocked tier-1 host — confirmed live:
tesla.com's Akamai block defeats crawl4ai too — stays tier-3 rather than
masking what could be a real tier-1 schema break). Confirmed live: qualtrics
now resolves via tier 2; tesla rows still fail (crawl4ai reports "Blocked by
anti-bot protection: Akamai block") and correctly stay in "needs your help."

## M6.6 — Batch quality patch punch list (2026-07-08)

Closed all four items from `PHASE2_KICKOFF.md`'s M6.6 punch list.

**1 & 3 (shingle grouping, export schema v2)** were already implemented by
M6.1/M6.3 (see those sections above); the punch list's own evidence predated
those commits. No further code needed — just re-verified live post items 2/4
below.

**2 (aggregator cleaning / re-resolution one-off).** Per the M6.2 decision
above, the ~107 `tracker_jobright` rows resolved via the old `generic`
resolver (before `src/resolve/jobright.py` existed) were left untouched by
M6.2 and still carried raw scraped chrome (`"H1B Sponsor Likely"`, funding/
news sections, `"· N hours ago"` lines). Added
`scripts/reresolve_aggregator_chrome.py`: a pure `matches_aggregator_chrome()`
detector (six regexes covering the chrome patterns above) selects every row
whose `jd_text` matches, regardless of `status`/`resolve_attempts`; `db.py`
gained `all_rows()` and `reset_for_reresolution()` (reset to `DISCOVERED`,
clearing `jd_text`/`resolver`/`flags`/`ats_url`/`jd_quality`/`notes`/
`filter_reason`/`resolve_attempts`) so the reset rows flow back through the
normal `run_ingest.run_resolution()` path — no bespoke re-fetch logic. Live
run: `python -m scripts.reresolve_aggregator_chrome --db data/jobs.db`
matched and re-resolved all 107 rows (0 failed); all now carry
`resolver='jobright'`, `jd_quality='aggregator'`, and clean `__NEXT_DATA__`-
derived `jd_text` with zero chrome-pattern matches (confirmed with
`--dry-run` afterward: 0 rows match).

**4 (prefilter title_include fix).** Removed the second `title_include` regex
line (`new.?grad|early.?career|university|entry.?level|graduate|2026|2027`)
from `config/filters.yaml` and `ARCHITECTURE.md` §7 — it let non-role titles
like "Graduate Research Scientist" or "Student Researcher" pass on the bare
word "graduate"/"university" alone; level/new-grad is already enforced by
`title_exclude` + `years_cap`. Live re-run of `prefilter.run_prefilter()`
over existing `RESOLVED` rows flipped 81 rows to `FILTERED_OUT` (50
`title_include`, 47 `location`, 1 `title_exclude` — some rows would have hit
multiple gates and are counted at whichever fires first); both punch-list
examples ("Graduate Research Scientist - 3D/4D Reconstruction/..." id 111 and
"Student Researcher(Multimedia Streaming)... " id 138) are among them, both
with `filter_reason='title_include'`. Regression tests added in
`tests/test_prefilter.py`.

**Unplanned finding during live re-export.** After item 2's re-resolution,
Neuralink exported as 5 objects instead of the required ≤ 2: jobright
generates a differently-worded AI paraphrase of the same posting per
location, so same-company+same-title rows now legitimately score below the
0.85 Jaccard threshold (observed 0.66–0.85 across the 4 "Software Engineer,
BCI Applications" rows) even though the exact-content-hash and near-dup-by-
title rules were both designed to catch exactly this case. Per CLAUDE.md
prime directive #1, stopped and asked the user rather than silently tuning
the threshold. Approved fix: `_cluster_rows()` in `scripts/export_batch.py`
now merges on exact `(company_norm, title_norm)` match unconditionally,
dropping the Jaccard-similarity gate on that path entirely — an exact title
match within a company is itself sufficient evidence of the same posting;
the shingle/Jaccard helpers (`_shingles`, `jaccard_similarity`) remain as
tested utilities but are no longer used by the clustering path itself. Live
re-export post-fix: Neuralink → 2 objects, Serco → 1, 0 objects match
aggregator-chrome patterns, every object still carries `locations`/`flags`/
`jd_quality`. Regression test:
`test_export_batch_collapses_same_title_even_below_similarity_threshold`.

Also corrected mid-session: the first live prefilter re-run used a
`title_include` regex missing the punch list's own `|developer` suffix,
incorrectly filtering 4 rows containing "Developer" but none of the other
role-family words (e.g. "Jr. Web Developer"). Caught by re-reading the punch
list text, fixed `config/filters.yaml`/`ARCHITECTURE.md`/test `CONFIG` to add
`|developer`, reset those 4 rows back to `RESOLVED`/`filter_reason=NULL`, and
re-ran `prefilter.run_prefilter()` — 2 of the 4 correctly stayed filtered
(on `location`), 2 correctly returned to `RESOLVED`.

M6.6 acceptance criteria (per `PHASE2_KICKOFF.md`) all verified live against
`data/jobs.db`: Neuralink ≤ 2 ✓ (2), Serco ≤ 2 ✓ (1), zero chrome-pattern
objects ✓, every object carries `locations`/`flags`/`jd_quality` ✓,
research-role leak closed with regression tests ✓. DB backed up beforehand to
`data/jobs.db.pre-m6.6-bak`.

## M6.8 — Freshness & recycling defense (2026-07-08)

Per CLAUDE.md prime directive #2, M6.8 was done before M6.7 in this session at the user's
explicit request (M6.8 is schema-touching; doing it first meant the idempotent migration
could be validated by itself, per §5's "run the I7 idempotency check ... before anything
else"). `docs/SELF_HEALING.md` §1 (I7) supplied the actual mechanism: the existing
`tests/test_idempotency.py` (full pipeline run twice on fixtures, byte-diff the jobs table)
already *is* the I7 check — `scripts/audit.py` (M7) doesn't exist yet to run it standalone.

**Migration-only step, verified in isolation.** Added `last_seen_at TEXT`,
`repost_count INTEGER NOT NULL DEFAULT 0` to `_JOBS_MIGRATIONS`, and `Status.CLOSED` to
`models.py`, with zero behavior change. Ran `pytest tests/test_idempotency.py` — passed —
before writing any M6.8 logic. Also confirmed the idempotent `ALTER TABLE` applies cleanly
to the live `data/jobs.db` (columns present after first connect; second connect is a no-op).

**I7 test itself required updating** once M6.8's actual behavior landed. Per
`docs/PHASE2_KICKOFF.md` M6.8 item 2, `last_seen_at`/`repost_count` are *designed* to change
on every dedup-key conflict — a daily run rediscovering the same still-open posting is
supposed to bump `repost_count` and refresh `last_seen_at`. That's new legitimate drift, the
same category as the pre-existing `resolve_attempts` retry carve-out. Updated
`test_full_pipeline_run_twice_is_idempotent` to strip those two columns before the
byte-equality check, and added an explicit assertion that the drift is *exactly*
`repost_count += 1` / `last_seen_at` strictly increasing — nothing else — so the test still
catches any unrelated second-run mutation.

**Design decisions not fully pinned down by the spec:**
- Shared shingle/Jaccard code moved out of `scripts/export_batch.py` into new
  `src/textsim.py` (`normalize_jd`, `shingles`, `jaccard_similarity`, `content_hash`), since
  M6.8's content-based repost detection needs the exact same similarity notion export
  clustering uses (M6.6 already established 0.85 as a safe within-company threshold).
  `export_batch.py` re-imports the same names so its existing tests needed no changes.
- **Stale-at-discovery default when `date_posted` is missing:** flag only when `date_posted`
  is present AND older than `stale_days` — missing data is not evidence of staleness. (An
  earlier pass reused the reopen-rule's "missing timestamp = eligible" default here too,
  which incorrectly flagged every job with no posted date; caught by the idempotency test
  regressing before this shipped, fixed before commit.)
- **"Prior outcome" wording:** the doc's target digest text is `"recycled: you
  [skipped/applied] on <date>"`. Rendered at detection time (not re-derived by the digest)
  as `"recycled: you {skipped|applied} job #{prior_id} ({prior_status}) on {date}"` —
  `APPLIED` → "applied", everything else terminal (`FILTERED_OUT`/`REJECTED`/`CLOSED`) →
  "skipped". `{date}` is the prior row's `jd_resolved_at` (fallback `discovered_at`) since
  there's no dedicated "terminal transition" timestamp column (adding one would be a further
  PROTECTED schema change beyond what's pre-approved here).
- **Liveness recheck scope.** The doc's "404/410/absence from the board's live listing"
  is implemented as 404/410 only; "absence from the board's live listing" would require
  per-ATS scraping heuristics this pipeline deliberately avoids (CLAUDE.md prime directive
  #6). Any other response (200, 5xx, timeout, connection error) just touches `last_seen_at`
  and stays open — false negatives (missed closures) are cheaper than false positives (a row
  wrongly marked CLOSED, blocking Phase 3 tailoring).
- I13 (SELF_HEALING audit hook) intentionally not built — M7 hasn't started.

**New files:** `src/freshness.py`, `src/textsim.py`, `config/freshness.yaml`,
`tests/test_freshness.py`, `tests/test_run_ingest_freshness.py`. **Modified:** `src/db.py`
(migrations, `insert_discovered` reopen/repost bookkeeping, `mark_resolved` flag-merge fix,
`add_flag_and_note`/`mark_closed`/`touch_last_seen`/`rows_needing_liveness_check`),
`src/models.py` (`Status.CLOSED`, `TERMINAL_STATUSES`), `src/run_ingest.py` (freshness config
loading, content-repost call in `run_resolution`, liveness recheck before digest),
`src/digest.py` (Recycled & reopened / Closed sections), `scripts/export_batch.py` (imports
from `textsim` instead of defining its own copies), `docs/ARCHITECTURE.md` §4.1–4.3, §7.5
(new), §8. Full suite: 259 passed.

## M6.7 — Sub-batched scoring + synthetic stress suite (2026-07-08)

**Synthetic JD bands not fully specified by the doc.** `PHASE2_KICKOFF.md` M6.7 item 2 names
6 categories with explicit bands (perfect backend [8.5–10], hard-requirement miss [2.5–4.5],
wrong specialty [3–4], sponsorship_risk [≤6 cap]) plus two more by name only
("keyword-stuffed JD", "stale/vague JD") with no band. Per instruction, drafted all 10
synthetic JDs against `docs/scoring_prompt.md`'s anchored scale and the candidate's actual
profile (`config/profile_summary.md`: Java/Spring backend + Python/LLM-agent evidence,
new-grad, San Jose), including two extra categories beyond the doc's 6 (an LLM-agent-match
variant of "perfect," and an `ml`-track-stretch variant of "partial overlap") to reach 10 and
give both `base_variant` values a positive case. Presented the full expected-band table to
the user before writing any code (per instruction) — approved as-is, including the
improvised bands for keyword-stuffed [3–5] and stale/vague [2–4]: low-confidence but not 0,
since the anchored scale's 0–2 band is reserved for "hard disqualifier," not "insufficient
information," and a scorer that zeroes vague JDs would incentivize the wrong caution.

**Sub-batched scoring wrapper design.** `docs/scoring_prompt.md`'s prompt body assumes a
single fixed workflow ("read the most recent file in `data/batch/`..."), which doesn't work
per-chunk. Rather than fork the prompt file, `scripts/score_batch.py`'s
`build_chunk_prompt()` reuses the prompt body verbatim (split at the `## Prompt` heading) and
prepends a short override paragraph naming the chunk-local input/output file paths — "same
prompt" per the spec, with only the file-path instructions swapped. `import_scores.py`
needed no changes: `score_batch()` concatenates all chunk results into one array before
writing the final `*.scored.json`, so row-coverage validation still runs over the whole
batch as the M6.1 spec requires.

**Exemplar injection (item 3) not built** — explicitly gated by the doc on ≥20 calibration
labels existing, which isn't true yet (calibration hasn't started).

**New files:** `scripts/score_batch.py`, `scripts/scoring_stress.py`,
`tests/fixtures/scoring_stress/cases.json`, `tests/test_score_batch.py`,
`tests/test_scoring_stress.py`. No `src/` changes (this is Phase-2 tooling, lives in
`scripts/` per the existing `export_batch.py`/`import_scores.py` pattern — no LLM calls
inside `src/`, per CLAUDE.md prime directive #7). `subprocess` is stdlib, and shelling out to
the already-present `claude` CLI is not a new Python dependency. Full suite: 272 passed.

## Test isolation bug found during M6.8/M6.7 live verification (2026-07-08)

`tests/test_idempotency.py`, `tests/test_run_ingest_browser_resolver.py`, and
`tests/test_run_ingest_sources.py` all called `run_ingest.main()` with a `--db` pointed at
`tmp_path`, but no equivalent override for the digest — `digest.write_digest()` defaulted to
the real `data/digests/` directory. Every pytest run of the full suite silently overwrote
today's real digest file with fixture content (e.g. company "Acme"/"SWE"), which clobbered
the evidence from this session's live M6.8 verification run before it could be inspected.
Pre-existing bug (present since `test_idempotency.py`'s original M4 version), not introduced
this session, but actively blocking a deliverable — fixed now rather than deferred. Added
`--digest-dir` to `run_ingest.build_parser()` (default `data/digests`, unchanged), threaded
into the `digest.write_digest()` call, and updated all three test files to pass a
`tmp_path`-scoped digest dir. No test assertions changed; this only isolates side effects.

## M6.7/M6.8 live verification (2026-07-08)

Ran `python -m src.run_ingest --db data/jobs.db` live (backed up first to
`data/jobs.db.pre-m6.7-m6.8-bak`). Discovery inserted 641 new rows (674 discovered total
across tracker_jobright/tracker_simplify) and resolution reached 236 `RESOLVED` before the
background process was interrupted (likely a harness wall-clock limit — resolving ~640 rows
at the mandatory 2s-per-host throttle across hundreds of distinct ATS hosts is a long-running
job; `runs.id=8` never reached `db.finish_run()`). Rather than discard the already-fetched
work, completed the run administratively: ran `prefilter.run_prefilter()` (191 newly
`FILTERED_OUT`) and `freshness.run_liveness_recheck()` (0 closed — no `SHORTLISTED`/`TAILORED`
rows exist yet, scoring hasn't run) directly against the live DB, then called
`db.finish_run()`/`digest.write_digest()` with the real resulting counts. `runs.notes` records
that this run was completed administratively rather than end-to-end in one process.

**M6.8 live evidence:** `data/digests/2026-07-08.md` shows a real `stale_listing` flag in the
"New & resolved" table (Cisco — "Software Engineer Data/AI/Intelligent Systems 1", real
`date_posted` older than 21 days) — 38 rows total carry it. `repost_count` bumped to 1 on 26
rows via real dedup-key conflicts against already-known postings from earlier sessions,
confirming the M6.8 item 2 bookkeeping fires live. No `repost`/`reopened` flag fired this run
(would need a dedup-key conflict against a `RESOLVE_FAILED`/`CLOSED` row, or a genuine
content-match against a `FILTERED_OUT`/`REJECTED`/`APPLIED`/`CLOSED` row at the same company —
neither condition arose in this run's data), so the digest's "Recycled & reopened" section is
correctly absent rather than fabricated. Also re-confirmed the M6.6 prefilter fix is still
live-correct: "ByteDance — Graduate Research Scientist..." and "...Student Researcher..." both
still filtered on `title_include`.

**M6.7 live verification not completed:** the `claude` CLI (required by
`scripts/score_batch.py` to actually invoke the headless scorer) is not present in this
sandboxed execution environment — only inside Claude Code itself, which cannot shell out to a
second copy of itself here. `scripts.score_batch`/`scripts.scoring_stress` are built and
covered by mocked-subprocess tests, but running them for real against the live 31-object
export (`data/batch/2026-07-08.json`) is left as the user's manual dry-run activity, per the
existing M5 pattern ("Writing the template is M5; running it is the user's dry-run
activity"). Command: `python -m scripts.score_batch data/batch/2026-07-08.json` (then
`python -m scripts.import_scores data/batch/2026-07-08.scored.json` to apply).

## 2026-07-08 — Mid-milestone doc update (PHASE2_KICKOFF/SELF_HEALING/TAILORING_METHODOLOGY)

`docs/PHASE2_KICKOFF.md`, `docs/SELF_HEALING.md`, and `docs/TAILORING_METHODOLOGY.md` were
updated by the user between sessions while M6.7/M6.8 implementation was in progress. Per the
user's instruction, confirmed via `git diff` that the changes are strictly additive: the
M6.7/M6.8 section bodies are byte-identical to what was being implemented; only the
"— CLOSED 2026-07-08" status annotations were removed from their headers (correctly, since
M6.9 — added in the same edit, scoped "do alongside M6.7/M6.8" — was not yet done), plus the
wholly new M6.9 section and two new (deferred) `SELF_HEALING.md`/`TAILORING_METHODOLOGY.md`
files. No rework was required; M6.7/M6.8 scope, acceptance criteria, and already-committed
code (SHA 0ca6e36, 457aaed) were unaffected. Per the user's explicit scoping: SELF_HEALING's
I3b belongs to M7 and Calibration protocol amendments are Phase-2 process / an M8
`ats_vendor` schema note — both deferred, not built this session.

## 2026-07-08 — M6.9 items 1 & 2 (residual engineering notes)

**Item 1 — jd_quality starvation / `__NEXT_DATA__` apply-URL probe.** Inspected the full
`__NEXT_DATA__.props.pageProps.dataSource.jobResult` object (54 keys) in
`tests/fixtures/jobright_amazon_page.body`. No apply/original-posting URL field exists
anywhere in the payload: `isCompanySiteLink` is a bare boolean (true, no accompanying URL),
`jobRecruiterProfileUrl`/`jobtargetJobId`/`jobtargetQuestionnaire` are present but empty, and
every populated URL field is for logos, LinkedIn/Crunchbase/press links, or the jobright page
itself. Conclusion: the underlying ATS URL is not present in jobright's server-rendered
`__NEXT_DATA__` blob (likely fetched client-side via a separate API call not captured by a
static fixture). Per the doc's own fallback clause, no router/resolver change made — the
"needs your help" paste path remains the only path to `jd_quality='ats'` for jobright rows.
Findings shown to the user before any wiring, per instruction.

**Item 2 — title backfill hygiene.** Added `clean_title()` to `src/models.py`: strips
trailing requisition-id and page-furniture suffixes ("Job Details", "| Careers", a
company-name + Careers/Jobs combo) from a resolver's `raw_title` before it backfills a
placeholder title, while preserving human-readable casing/punctuation (unlike `norm()`,
which is dedup-key-only). Wired into `db.mark_resolved()`'s existing title-backfill branch
(`src/db.py`). Checked the actual id-52 row in the live DB (the doc's citation was a
truncated snippet): the real `raw_title` is
"Front End Developer (Hybrid) - 28751 Job Details / HII's Mission Technologies division" —
furniture continues *after* "Job Details" rather than the string ending there, which a
purely trailing-suffix regex would miss. Added a boundary rule: a "`<reqid> Job Details`"
marker is treated as a hard cut regardless of what follows it. Regression tests cover both
the doc's simplified example and the real live string, plus piped/site-name Careers
suffixes, bare requisition numbers, and a negative case (a legitimately dashed title,
"Backend Engineer - Distributed Systems", is left untouched). Full suite: 281 passed. No
backfill migration run against already-resolved rows — item 2 as scoped only prevents future
placeholder-title backfills; id 52's already-stored title is untouched (a one-off
re-backfill was not requested and title isn't part of the dedup key, so it's cosmetic only).

## 2026-07-08 — M6.7/M6.8 closure

M6.7 (sub-batched scoring + synthetic score-band stress suite) and M6.8 (freshness &
recycling defense) are complete per their acceptance criteria: code committed (SHA 0ca6e36,
457aaed), live-verified against the real DB (see the "M6.7/M6.8 live verification" entry
above), and full suite green. M6.7 item 3 (exemplar injection) and M6.8's I13 audit hook
remain correctly deferred per the doc's own gating. Marking both CLOSED in
`docs/PHASE2_KICKOFF.md` alongside M6.9 items 1–2, completed in this session.

## 2026-07-09 — M7: jobs.resolved_logic_version schema addition (I9)

New nullable `jobs.resolved_logic_version INTEGER` column, added via the standard idempotent
`ALTER TABLE` migration. This is a DB schema change (SELF_HEALING §4 item 1, normally
PROTECTED); approval for this specific addition is the user's M7 task instructions, which
explicitly commissioned "LOGIC_VERSION plumbing for I9" — recorded here per §4's requirement
that PROTECTED changes need an in-session approval entry. `resolve.LOGIC_VERSION` (currently
`1`) is written by every `db.mark_resolved()` call; `mark_resolved()` also strips any
`stale_logic_version` flag the audit previously set, since re-resolving is what clears
staleness.

## 2026-07-09 — M7: I3 definition extended with exact-(company,title)-match trigger

Verified against the real archived `data/batch/2026-07-06.json` (copied to
`tests/fixtures/audit_2026_07_06_batch.json`) that `check_i3`'s Jaccard-only definition
missed a real, already-documented leakage pattern: jobright generates a genuinely
independent AI paraphrase of the same posting per location (different wording throughout,
not a location-suffix difference), so two batch objects for the same underlying posting can
score well below the 0.85 threshold — e.g. ids 66/67/69 (Neuralink — Software Engineer, BCI
Applications) scored 0.6865–0.785 Jaccard, and ids 101/102 (Serco — Software Engineer)
scored 0.8397, all below threshold, so I3 PASSed on a batch that plainly leaked duplicates.
Two rounds of investigation first ruled out the location-boilerplate explanation that I3's
own playbook (`docs/SELF_HEALING.md` §"I3 fires →") originally suggested as the fix path —
these pairs differ throughout the body text, not just in a trailing location clause.

Fix: `check_i3` (`src/audit/invariants_export.py`) now FAILs a pair when EITHER the existing
`same-company AND jaccard >= threshold` condition holds, OR a new `same-company AND
norm(title_a) == norm(title_b)` condition holds (using `src.models.norm` on both sides).
This exact-title-match signal mirrors the already-proven M6.6 fix in
`scripts/export_batch.py`'s `_cluster_rows()` (see above), which added the identical
company+title exact-match trigger to the *export-time* clustering logic for the same
underlying reason. Evidence entries now include a `matched_on` key (`"content"` or
`"title"`) alongside `similarity`, which is still reported (even below threshold) on
title-match-only triggers so the evidence stays informative.

This is a PROTECTED invariant-definition change (`docs/SELF_HEALING.md` §4 item 3).
Approved in-session by the user, explicitly scoped as an extension of Task 8's I3 check,
after the real-batch investigation above ruled out a non-PROTECTED fix. Regression coverage:
`tests/test_audit_2026_07_06_regression.py::test_archived_2026_07_06_batch_fails_i3` (real
batch), plus new unit tests in `tests/test_audit_invariants_export.py` covering the
low-Jaccard/exact-title FAIL case and a same-title/different-company PASS case (the
company-match gate still applies to the new signal). Full suite green aside from two
pre-existing, unrelated `tests/test_audit_cli.py` failures (I4/I5 already failing against
the real repo's live `data/batch/2026-07-06.json` before this change, confirmed via
`git stash`).

## 2026-07-09 — Test-isolation fix: `tests/test_audit_cli.py` was reading real `data/batch/`

The two `tests/test_audit_cli.py` failures noted above (M7's I3 extension) traced to a
pre-existing bug in Task 12's own test design, not the I3 change itself:
`test_main_writes_audit_json_and_returns_zero_on_pass` and
`test_audit_runs_under_10s_on_10k_rows` both passed `--repo-root` pointed at the real
project root, so `check_i3`/`check_i4`/`check_i5` read the repo's actual `data/batch/`
directory instead of an isolated fixture. Once the archived `2026-07-06.json` (a known-bad
batch, deliberately present for the M7 acceptance regression test) sat in that directory
and I3 started catching it correctly, these two unrelated CLI-wiring tests went red for a
reason that had nothing to do with what they were meant to verify (exit codes, JSON output
shape, runtime budget). Fixed by pointing both tests at an isolated `tmp_path` root
containing a copy of `config/` and `docs/scoring_prompt.md` but no `data/batch/` directory,
so I3/I4/I5 correctly PASS vacuously (no batch file to check) — matching the tests' actual
intent. No production code changed.

## 2026-07-09 — M7 self-healing audit suite complete

Implemented `scripts/audit.py` + `src/audit/` (I1-I13 per `docs/SELF_HEALING.md` §1) +
`src/audit_schema.py` (hand-rolled JSON-schema-subset validator, no new dependency) +
`src/llm_trace.py` (I11 shared trace helper, wired into `scripts/score_batch.py`) +
`config/audit.yaml`/`chrome_patterns.txt`/`manual_domains.txt`/`batch_schema.json`/
`scored_schema.json` + `resolve.LOGIC_VERSION` plumbing (I9, `jobs.resolved_logic_version`
column — schema-change approval logged separately above, 2026-07-09) + manual_domains
routing (I2, skips the resolve_attempts budget) + digest AUDIT section and FAIL banner +
audit wired into `run_ingest.main()` right after the liveness recheck.

Scoping decisions carried from the implementation plan: I7 (idempotency) is SKIP in the
automatic per-run audit — a full double-pipeline run doesn't fit the <10s/10k-row budget
and duplicates `tests/test_idempotency.py`; `invariants_db.diff_permitted_drift()` is
exposed via `scripts.audit --db-before/--db-after` for the weekly cadence instead. I11 is
a coarse "any trace file exists at all" check, not per-row trace linkage, since adding a
`trace_id` FK would be a second PROTECTED schema change beyond what this session's
instructions commissioned.

**I3 acceptance-gate finding and fix (mid-build, this session):** the milestone's own
acceptance test — the archived `2026-07-06.json` batch must fail I3, I4, and I5 — initially
only held for I4/I5. Investigation found I3's Jaccard-similarity-only definition (≥0.85 on
5-word shingles) did not catch the real historical Neuralink (ids 66/67/69, similarity
0.6865–0.785) and Serco (ids 101/102, similarity 0.8397) near-dup pairs — all below
threshold. `SELF_HEALING.md` §2's own I3 playbook suggested a "location-boilerplate,
strip location lines before shingling" fix for the 0.70–0.85 band; inspecting the real
`jd_text` content ruled this out — these are fully independent per-location AI paraphrases
(no location-suffix text at all), the same root cause already documented and fixed for
`scripts/export_batch.py`'s clustering in M6.6 via exact-(company,title)-match. With the
user's explicit approval (I3's definition is PROTECTED per §4 item 3), extended `check_i3`
to FAIL on EITHER the existing Jaccard≥threshold signal OR an exact `norm(company)` +
`norm(title)` match, mirroring the M6.6 precedent. Regression-tested: existing
Jaccard-based FAIL/PASS cases unchanged, new title-match FAIL case (low-Jaccard,
exact-title, same-company) added, new cross-company-same-title PASS case added (the
company-match gate still applies to the new signal).

**Acceptance verified:** seeded-violation + clean fixture per invariant I1-I10
(`pytest tests/test_audit_invariants_*.py`), the archived 2026-07-06 batch fixture now
fails I3, I4, AND I5 (`tests/test_audit_2026_07_06_regression.py`, all 3 green), FAIL
produces a nonzero exit and the digest banner (`tests/test_audit_cli.py`,
`tests/test_digest.py`), full audit runs in <1s on a synthetic 10k-row DB (well under the
10s budget; `tests/test_audit_cli.py::test_audit_runs_under_10s_on_10k_rows`). Full suite:
`pytest -q` — 357 passed.

**Live audit run against `data/jobs.db` (report only, not fixed this session per the
user's instruction):** overall **FAIL**.
- ✗ **I3 FAIL** — one near-duplicate pair not yet collapsed: ids 119/164, content
  similarity 0.884 (above the 0.85 threshold — the existing Jaccard signal, not the new
  title-match signal).
- ✗ **I6a FAIL** — one row (id 257, "Software Integration Engineer") in a post-prefilter
  status whose title/location would now be filtered by the `location` rule — a prefilter
  leak.
- ⚠ **I1 WARN** — `tracker_vansh` has reported 0 discoveries for 4 consecutive runs
  (WARN threshold is 3; FAIL is 7).
- ⚠ **I6b WARN** — the most recent run (id 9) filtered 0% of resolved rows, below the 20%
  low-end sanity threshold.
- ✓ I2, I3b, I4, I5, I8, I9, I10, I11, I12, I13 all PASS. I7 SKIP (by design — see above).

Per CLAUDE.md's one-milestone-per-session rule and the user's explicit instruction, these
live findings are next session's weekly-maintenance work (`SELF_HEALING.md` §6), triaged
and fixed one invariant at a time per the §2 playbook, highest severity and lowest
invariant number first (I3 FAIL before I6a FAIL before the two WARNs).

## 2026-07-12 — M7 weekly maintenance: I6a FAIL + I6b WARN, one root cause

**User-approved deviation from the §2 "one invariant per session" playbook default:**
findings I6a (FAIL, id 257 leaked past the `location` prefilter rule) and I6b (WARN, run 9
filtered 0% of resolved rows) were treated as a single fix in one session because
investigation showed they share one root cause. Approved explicitly by the user in-session.

**Root cause:** `src/run_ingest.py::main()` gated the call to `prefilter.run_prefilter()`
behind `if not args.resolve_only:` (previously ~line 198). `prefilter.run_prefilter()`
itself is already correctly stateful — it queries `WHERE status = RESOLVED AND
filter_reason IS NULL`, so it will catch *any* eligible row regardless of which run
resolved it — but the CLI wiring skipped calling it at all during a `--resolve-only`
invocation. Run id 9 (2026-07-08) was exactly such a run ("resolve-only smoke run for
M6.9 title-hygiene verification... interrupted administratively," per its `runs.notes`):
it resolved id 257 (Cubic, "Software Integration Engineer", San Diego, CA — outside
`config/filters.yaml`'s `location_allow` list) but never swept it, and no full
(non-`--resolve-only`) run has executed since to catch up. That single gap explains both
I6a (the row still sits RESOLVED with `filter_reason IS NULL` days later) and I6b (run 9's
0%-filtered stat, which reflects prefilter never running that run, not the rules
behaving oddly).

**Fix (`src/run_ingest.py`):** moved the `prefilter.run_prefilter()` call out from behind
the `if not args.resolve_only:` guard so it runs on every invocation that can produce
RESOLVED rows (i.e., whenever `not args.discover_only`), matching prefilter's own
already-stateful design instead of gating it on run mode. The liveness recheck
(`freshness.run_liveness_recheck`) stays behind `--resolve-only` unchanged — this fix is
scoped to the prefilter-skip bug only.

**Regression tests:**
- `tests/test_prefilter.py::test_evaluate_title_location_years_cases` — added id 257's
  exact title/location ("Software Integration Engineer", "San Diego, CA") as a new
  parametrized case, asserting `location` filter reason.
- `tests/test_run_ingest_prefilter.py::test_resolve_only_run_still_filters_newly_resolved_rows`
  (new file) — seeds id 257's exact company/title/location/URL as DISCOVERED, mocks
  resolution, runs `run_ingest.main([..., "--resolve-only", ...])`, and asserts the row
  ends FILTERED_OUT with `filter_reason == "location"` — proving a resolve-only run alone
  no longer leaves a row unfiltered.

**Verified:** full suite green (`pytest -q` — 360 passed). Retroactive fix confirmed
directly against a copy of `data/jobs.db`: running `prefilter.run_prefilter()` (the code
path the CLI now always reaches) flips id 257 from `RESOLVED`/`filter_reason=NULL` to
`FILTERED_OUT`/`filter_reason='location'`. Did not run the live pipeline end-to-end against
`data/jobs.db` (443 DISCOVERED rows would trigger live network resolution, unnecessary to
verify this fix and outside this session's scope) — the next scheduled/manual run will
apply it in production.

**Not changed (still open, separate sessions per user's instruction):** I3 FAIL (Cisco
duplicate ids 119/164 — DB-wide check vs. export-batch clustering scope question, plus
whether URL req-ID extraction is a cheaper fix) and I1 WARN (`tracker_vansh` 4 consecutive
zero-discovery runs, per the four-step I1 playbook).

## 2026-07-12 — M7 weekly maintenance: I3 FAIL (Cisco duplicate ids 119/164)

**Investigation (per the user's instruction to propose before implementing):** I3 does not
run a separate "DB-wide" duplicate check — `check_i3` (`src/audit/invariants_export.py`)
reads the *exported batch* (`_load_batch()` → `data/batch/*.json`), so it audits whether
`scripts/export_batch.py`'s `_cluster_rows()` clustered correctly. The real gap: M6.6
removed Jaccard-similarity clustering from `_cluster_rows()` entirely (kept only exact
`content_hash` match and exact normalized-title match), because jobright generates a
differently-worded AI summary per location for the *same title* — but `check_i3` never
stopped checking for Jaccard similarity >= 0.85 as an independent FAIL signal. Ids 119/164
(Cisco, "...Systems I (Full Time)" vs "...Systems 1", content similarity 0.884) have neither
matching content_hash nor matching normalized title, so `_cluster_rows()` had no path to
merge them — not a code defect, but a structural mismatch between what the audit checks for
and what the clusterer implements.

**Options considered:** (A) restore Jaccard similarity as an *additional* merge signal in
`_cluster_rows()` (same 0.85 threshold `check_i3` already uses), closing the check_i3/
clusterer definition gap generally; (B) extract a req/job ID from the URL (both Cisco URLs
contain `2000073`) as a third exact-match signal, cheaper and zero fuzzy-matching risk but
Cisco-specific unless generalized into a URL-pattern registry (rejected per CLAUDE.md's
no-arms-race stance on per-domain special-casing — wrapper_map/manual_domains entries are
earned only after >=3 failures, and this is a single observed case).

**User approved Option A.** Implemented: `_cluster_rows()` now also merges same-company
rows when `jaccard_similarity(shingles(a), shingles(b)) >= SIMILARITY_THRESHOLD` (module
constant `SIMILARITY_THRESHOLD = 0.85` in `scripts/export_batch.py`, kept in sync with
`config/audit.yaml`'s `i3.similarity_threshold` — PROTECTED per `SELF_HEALING.md` §4 item 3;
no threshold VALUE changed, only a second consumer added for the same already-approved
number). This only *adds* merge opportunities on top of the exact-hash/exact-title paths
(never removes one), so it cannot reintroduce the M6.6 aggregator-per-location false
negative.

**Regression tests (`tests/test_export_batch.py`):**
- `test_export_batch_collapses_high_similarity_pair_with_different_titles` — reproduces the
  live Cisco shape (same company, similarity >= 0.85, differently-worded titles) and asserts
  the two rows collapse into one batch object.
- `test_export_batch_does_not_merge_different_roles_at_same_company` — negative fixture:
  two distinct roles (backend vs. frontend) at the same company sharing a boilerplate
  company-description paragraph; asserts similarity stays below 0.85 and the rows do NOT
  merge, guarding against over-merging on shared boilerplate.

**Verified:** full suite green (`pytest -q` — 362 passed). Re-exported the live
`data/jobs.db` (via a scratch copy) and re-ran the full audit: ids 119/164 now merge into
one batch object (`id 119, row_ids [119, 164]`), and I3 flips from FAIL to PASS. I6a/I6b/I1
in that same scratch run reflect the scratch copy's own state (I6a still shows the id-257
FAIL there because the prefilter fix from the earlier finding-group wasn't re-run against
that particular scratch copy) — unrelated to this fix and not re-verified here.

## 2026-07-12 — M7 weekly maintenance: I1 WARN (`tracker_vansh` silent for 4 runs)

**Playbook investigation (per §2 I1, in order):** (1) `config/sources.yaml` has
`tracker_vansh: {enabled: true}` — not disabled. (2) Ran the adapter standalone with DEBUG
logging: the raw fetch (`fetch_json_listings` against
`vanshb03/New-Grad-2027`/`dev`/`.github/scripts/listings.json`) succeeded (200, 1122
entries, 639 after `active`/`is_visible` filtering) — the upstream source is not gone and
not renamed/moved (rules out step 3). (4) Cross-referenced the 639 currently-live postings
against the DB's actual `tracker_vansh` dedup_keys (the real ledger): **608 of them had
never been inserted into the DB at all**, even though the on-disk snapshot
(`snapshots/tracker_vansh.json`) already had nearly all of them marked "seen." That is
exactly the §2 I1 failure mode: *"snapshot file corrupt/marking everything seen."* The
adapter code itself is correct — proven by a real discovery run below inserting the missing
rows cleanly on the first pass and finding zero on an immediate re-run (idempotent).

Root cause of how the snapshot got that far ahead of the DB isn't fully forensically
pinned down (no `runs` row shows a matching bulk-discovery event), but the mechanism is
clear and reproducible: `tracker_common.diff_new_jobs()` overwrites its snapshot file as a
side effect on every call, and it does this unconditionally — `discover(config)`'s
`dry_run=True` path reads the snapshot without writing it, but any direct/interactive call
to `diff_new_jobs()` (or `discover()` with `dry_run` falsy) against the real
`snapshots/` directory permanently marks whatever it saw as "seen," whether or not those
jobs ever reach the DB. This is consistent with earlier sessions' documented pattern of
"reproduce interactively" debugging (e.g., M6.0's ashby-bug reproduction) very plausibly
having done exactly this against production snapshots at some point.

**This session compounded it, transparently disclosed:** while executing playbook step (2),
I called `tracker_vansh.diff_new_jobs()` directly against the real
`snapshots/tracker_vansh.json` (not an isolated copy) to check the fetch/parse path. That
call's side effect marked ~6 more postings "seen" without inserting them, on top of the
pre-existing ~602-posting drift. I hadn't copied the file first. Since the correct fix was a
full snapshot reset regardless, this didn't change the remediation, but it was a process
mistake — backed up the (already-mutated) file to the scratchpad before proceeding, for the
record.

**Fix (permitted per §2 I1: "snapshot reset"):** deleted `snapshots/tracker_vansh.json`.
With the user's explicit go-ahead, ran the real backfill:
`python -m src.run_ingest --source tracker_vansh --discover-only` — discovered 639,
inserted 583 new rows (the ~25-row gap from 608 vs. 583 is intra-batch duplicate
dedup_keys within the same 639-entry fetch, correctly collapsed by `insert_discovered`'s
existing uniqueness handling). An immediate second run of the same command found 0 new,
confirming idempotency. Also added a warning docstring to
`tracker_common.diff_new_jobs()` (`src/discover/tracker_common.py`) flagging its
snapshot-overwrite side effect and pointing future debugging sessions at `dry_run=True` or
a `tmp_path` copy instead, to reduce recurrence risk. No test added beyond this — there is
no code defect to regression-test; the adapter behaved correctly once given a
non-corrupted snapshot, which the live backfill run itself demonstrates.

**Also applied this session's earlier-committed I3/I6a fixes to production state** (both
were only verified against scratch copies until now): ran `prefilter.run_prefilter()`
directly against `data/jobs.db` (filtered id 257 — `location`), and re-ran
`scripts.export_batch` to regenerate `data/batch/2026-07-12.json` with the restored
Jaccard clustering signal (collapses ids 119/164).

**Verified:** `python -m scripts.audit` against the live `data/jobs.db` now reports
**Overall: PASS** across all 14 invariants (I1 PASS, I3 PASS, I6a PASS, I6b PASS; I7 SKIP by
design). Full test suite: `pytest -q` — 362 passed. This closes every finding from the
2026-07-11 live audit run.

## 2026-07-14 — Phase 2 calibration actually starts; false "complete" belief corrected;
## `docs/ROADMAP.md` recreated; M8 status verified as un-built

**Corrected false belief: Phase 2 calibration was NOT complete.** A prior session's memory
summary asserted Phase 2 calibration was done and that "M8 item 1 (profile loader)" was
already built. Both were wrong, verified against actual repo state this session:
- No `*.scored.json` file had ever been produced and imported into `data/jobs.db` before
  today — `git log` shows no such artifact, and every prior scoring attempt this week
  (2026-07-12 through 2026-07-13 sessions) either used `--skip-import` deliberately, hit the
  `acceptEdits` trust-boundary bug, or failed outright (`chunk_0.json` written but no
  `.scored.json`, per the 2026-07-13 session's own investigation).
- `grep -rn "master.profile|profile_loader|MasterProfile" src/ scripts/ tests/` returns
  **nothing**. No master-profile loader exists anywhere in the repo. M8 item 1 was never
  built; the belief that it was is unexplained (possibly a hallucinated summary, possibly
  referring to work that was done in an uncommitted, now-lost state) and is not to be
  trusted going forward.

**`docs/ROADMAP.md` was missing from the repo entirely**, despite being cited by name in
`docs/PHASE2_KICKOFF.md` ("Exit to Phase 3 (per ROADMAP.md)") — a dangling reference that
predates this session. Recreated it as the single source of truth for phase status (Phase 1
COMPLETE, Phase 2 IN PROGRESS as of today, Phase 3/M8 LOCKED with nothing built, M9–M12 per
`UPGRADE_PLAN.md`). Every status line was set from verified repo/DB state (grep, git log,
live query), not from memory or chat claims. Future sessions should check `ROADMAP.md`
before starting work, per its own instruction.

**Self-consistency scoring (k=3) implemented, mitigating measured run-to-run variance.**
Pre-mitigation baseline (2026-07-14, single-pass, recorded here since the run producing it
was never committed): re-scoring the same 2026-07-12 30-job batch twice with the (then)
single-invocation-per-chunk scorer gave mean |Δfit_score| = 0.67, max |Δ| = 2.0, and 2/30
jobs (id 42 Amazon PXT, id 105 TikTok) crossing the 7.0 shortlist threshold between
identical consecutive runs; id 105 additionally flipped `base_variant` (backend ↔ ml)
between runs — a second axis of instability on the same job.

Mitigation (`scripts/score_batch.py`): each chunk is now scored `SELF_CONSISTENCY_K = 3`
times independently. Per job: `fit_score` is the median of the 3 runs; `base_variant` is a
majority vote (2-of-3 always resolves at k=3 with a 2-value enum, so a true tie can't occur
in practice; the tie-break path falls back to the `'backend'` profile default rather than a
coverage-table lookup, because no such lookup is implemented at scoring time —
`majority_vote_variant()`); `missing_keywords`/`rationale` are taken from whichever of the 3
runs produced the median score. A `borderline` flag is set when the median lands within 0.5
of `shortlist_threshold`; it flows through `import_scores.py` into a new `jobs.borderline`
column and renders in a new digest "Borderline calls" section. All 3 raw invocations per
chunk get their own I11 trace (`data/traces/`), not just the aggregate.

**Post-mitigation verification:** re-scored the same 2026-07-12 batch twice more with k=3
(`--skip-import` both times, scratch copies, no DB writes):
- mean |Δfit_score| = 0.200 (down from 0.67), max |Δ| = 1.0 (down from 2.0)
- 1/30 threshold-crossing flip remained: **id 50 (Paylocity)**, 6.5 → 7.5 — not one of the
  two original baseline flips, so this is a different marginal case, not a persistence of
  the same ones. Not investigated further this session (single job, both scores near the
  boundary; expected to be exactly the kind of case Phase 2 Step 3/4 exists to work through
  once real disagreement data accumulates).
- **id 42 (Amazon PXT)**: fully stable — 7.5 both runs, `base_variant` "backend" both runs.
- **id 105 (TikTok)**: `fit_score` 5.5 → 6.0 (same side of the 7.0 threshold both times, no
  flip), `base_variant` "ml" both runs (no flip — this was the case with the base_variant
  flip pre-mitigation). Frozen as a permanent regression fixture:
  `tests/fixtures/variance_regression/tiktok_105.json` (real `jd_text`, unedited) — a live
  smoke re-check against it (not an automated pytest; running it needs the real `claude`
  CLI, which CLAUDE.md's "tests never touch the network" rule forbids in `pytest`) should
  confirm this case stays stable after any future `scoring_prompt.md`/`profile_summary.md`
  change.
- 0 `base_variant` flips across all 30 jobs (down from 1).

**Stress-suite bands marked PROVISIONAL.** The M8 gate's band-adherence condition (10/10 on
`scripts/scoring_stress.py`) is waived: all 10 `expected_band` values in
`tests/fixtures/scoring_stress/cases.json` are unvalidated pre-calibration guesses by the
implementer, not values derived from real user judgment, so failing 4/10 of them was never
meaningful evidence against the scoring rework. Each case now carries
`"band_status": "PROVISIONAL"`; bands will be re-anchored once real calibration
disagreement data (Step 3/4 below) exists to derive them from.

**First real Step 2 completion.** Imported run 1's k=3 output for real:
`python -m scripts.import_scores <run1>.scored.json --db data/jobs.db` — 45 rows updated
(30 batch entries fan out to 45 `row_ids` via export-time clustering), 18 shortlisted. This
is the first time Step 2 ("Run scoring") has ever actually completed against the live DB.

**First real Step 3 (calibration_report.py) run**, against the one existing blind-rating
worksheet, `data/calibration/2026-07-12.user.md` (30/30 jobs rated, 0 unscored): **15/30
disagreements** — a high rate, expected for the very first pass per PHASE2_KICKOFF.md Step
5 ("repeat daily until two consecutive batches have zero..."). Per Step 4, these are not to
be hand-fixed in the DB; they're the input for the user's next profile_summary.md/prompt/
prefilter amendment pass. Full disagreement list is in the run output (not reproduced here);
notable pattern: every disagreement this pass is APPLY-said/score-below-threshold (the
system currently runs colder than the user on this batch), zero SKIP-said/score-above-
threshold disagreements.

**M8 status confirmed LOCKED, nothing built, no M8/M9 work performed this session** per
`docs/ROADMAP.md` and this session's explicit scope (Phase 2 calibration only).

**Verified:** `pytest -q` — 385 passed. Live: two real k=3 re-score runs against
`data/batch/2026-07-12.json` (scratch copies, `--skip-import`), one real import against
`data/jobs.db`, one real `calibration_report.py` run against the live DB.

## 2026-07-14 — Phase 2 Step 4, first pass: sponsorship_risk cap removed;
## transferable-skill weighting added for well-known employers

Working through the 15 disagreements from the same-day calibration_report.py run (above),
split into two buckets before asking the user anything:

- **9 of the 15** (ids 32, 66, 94, 101, 135, 145, 146, 148, 390) are cases where the model
  read a real, hard disqualifier straight out of `jd_text` (DoD/security clearance, US
  citizenship, native-mobile/low-level-OS stack, legacy frontend stack, required C++
  distributed-systems experience, 3+ yrs experience, QA/UI-test focus, frontend/React
  focus) that the user could not have seen at blind-baseline time (Step 1 is
  company/title/flags only, explicitly forbidding the JD text). **Judged: not
  disagreements to fix.** The blind baseline did its job — it surfaced that "this
  company/title sounds appealing" and "the actual posting is a fit" are different
  questions — and the model's score is correct in all 9. `profile_summary.md` changes
  wouldn't move any of these; the gaps are real. No action taken on this bucket.
- **6 of the 15** (ids 50, 76, 105, 113, 131, 152) are genuine judgment calls: two
  (113 mthree, 131 Affirm) were hard-capped at 6 by the `sponsorship_risk` rule; the other
  four (50 Paylocity, 76 CLEAR, 105 TikTok, 152 Amazon) scored 5.5–6.5 on adjacent-but-not-
  exact stack overlap. Brought both patterns to the user for a decision (this is Step 4's
  "user decides which cause" — not something to resolve unilaterally).

**User's rulings, both applied to PROTECTED files with explicit approval in this session:**

1. **Remove the `sponsorship_risk` hard cap.** The user confirmed they want to apply to
   `sponsorship_risk`-flagged roles regardless of visa-sponsorship uncertainty.
   `docs/scoring_prompt.md` §3 changed from "CAP the score at 6" to "do NOT cap the
   score... score on fit alone, but always note the flag in the rationale." This directly
   un-caps ids 113 and 131 on the next scoring pass (both were capped, not naturally low).

2. **Weigh genuine transferable skills more heavily for well-known/large employers.**
   Scoped narrowly after an explicit clarifying question, because the user's initial
   phrasing ("add the closest skills in my resume which will match the JD") was ambiguous
   between three very different things: (a) score-only credit for real transferable
   skills, (b) resume-tailoring emphasis (Phase 3/M8, LOCKED, out of scope this session),
   or (c) fabricating skills the user doesn't have. The user confirmed (a) — score only,
   real skills, no resume-content change. Added a `profile_summary.md` Notes bullet: for
   employers like Amazon/TikTok "and similarly prominent tech companies," weigh genuinely-
   held transferable/adjacent skills (distributed systems, backend services, Kafka/
   event-driven, PyTorch/ML pipeline work) above literal keyword overlap, without requiring
   an exact stack match for the 7–8 band. The bullet explicitly disclaims that this is not
   permission to claim skills the candidate doesn't have, and points at
   `TAILORING_METHODOLOGY.md`'s anti-fabrication rules for the separate, later tailoring
   phase. Option (b) is noted here so it isn't lost: once Phase 3/M8 unlocks, tailoring
   should foreground the candidate's closest *real* matching bullets per JD — this is
   already what S1→S2→S3 is designed to do, no new instruction needed there.

**Not yet re-scored against these changes** — that's the next Step 2/3/4 cycle, on a future
batch (or a re-run of this one), not done in this session.

**Verified:** `pytest -q` — 385 passed (no test asserted the old cap behavior by name, so
none needed updating). No DB writes; both edits are to `docs/scoring_prompt.md` and
`config/profile_summary.md` only.

## 2026-07-14 — Hybrid Discovery v2 approved as an agentic control plane with a
## deterministic acceptance boundary

The user rejected the current three-tracker discovery architecture as the final design and
asked for broad, hybrid deterministic/agentic discovery, specifically raising Crawl4AI,
Crawlee, and Apify. Repository review confirmed that the existing resolver breadth does not
equal discovery breadth: Crawl4AI currently resolves an already-known URL, while automatic
URL acquisition is limited to the Vansh, Simplify, and Jobright GitHub trackers.

**Approved direction:** agents may research companies, find career boards/ATS tokens, and
propose sources or candidate URLs, but their output is staged through a versioned file
contract. Deterministic code remains the sole authority for schema validation, crawl policy,
provenance, canonicalization, deduplication, source promotion, and SQLite writes. Initial
source promotion is user-approved; no agent may approve its own proposal. This replaces the
old blanket “no agentic discovery” architecture while retaining deterministic production
acceptance.

**Tool boundary:** Crawl4AI remains the leaf-page browser fallback and is evaluated first for
bounded small-site crawling. Crawlee Python—not the linked JavaScript package—is considered
only if a fixture/live bake-off proves that persistent queues, route handlers, or crash
recovery add material value. If adopted, Crawlee discovers leaf URLs and does not duplicate
Crawl4AI's fetch in the same stage. Apify MCP is permitted for interactive research; an
unattended Actor must be allowlisted and version-pinned, with its output staged and locally
validated. Dynamic unattended selection of arbitrary public Actors is rejected.

**Still prohibited:** LinkedIn/Indeed scraping, login/CAPTCHA bypass, anti-bot evasion,
proxy rotation for circumvention, automated applications, direct agent DB writes, and
unbounded crawling. Authorized alert emails from those platforms are allowed as input.

This is not a purely additive clarification: it changes the target architecture and future
work queue. The documentation distinguishes CURRENT code from TARGET M9D so no file claims
the feature is live. No production code, database schema, dependency, source configuration,
or runtime behavior changed in this documentation session. Detailed design:
`docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`.

## 2026-07-14 — M9D-0 discovery correctness baseline implemented

M9D-0 fixed the tracker snapshot failure mode documented earlier in this file. The previous
implementation let `tracker_common.diff_new_jobs()` overwrite `snapshots/{source}.json`
before `db.insert_discovered()` completed, and `discover_all()` applied `--limit` after the
adapter had already written the full upstream key set. That meant a DB failure or a limited
run could mark rows seen without durable job rows.

**Implemented boundary:** tracker adapters now return `AdapterDiscovery(jobs,
PendingCheckpoint)` without writing snapshots. `run_ingest.persist_discovery()` inserts jobs
first, then commits checkpoints with sibling temp file plus `os.replace`. A failed DB insert
makes zero checkpoint calls. A checkpoint failure leaves inserted rows durable, leaves the
old snapshot intact, records a structured `checkpoint` issue, and returns nonzero. Legacy
snapshots without `pending_keys` load with empty pending sets.

**Limit semantics:** `--limit N` is per source. Unselected candidates are stored as
`pending_keys` and stay eligible on the next run. Isolated live smoke used
`/tmp/job-pipeline-m9d0.SuBvhS`:

- First run: `tracker_vansh --discover-only --limit 2` inserted Qualcomm and Qualtrics.
- Second run against the same temp DB/snapshot dir inserted Amazon and Roblox.
- Final temp DB count: 4.

Production `data/jobs.db` and production `snapshots/` were not used for the smoke.

**Source failure visibility:** adapter exceptions are preserved as structured
`DiscoveryIssue` rows in `runs.notes` and render in the digest as `Run warnings`. A valid zero
yield is now distinguishable from a fetch/checkpoint failure. Partial source failure remains
nonfatal; all selected sources failing returns nonzero with a finished run record.

**Read-only baseline captured:** `scripts.source_baseline` opens SQLite with `mode=ro`, adds
no schema, and writes ignored report `data/metrics/m9d-0-source-baseline.json`.

- Generated at: `2026-07-14T19:20:27.376129+00:00`, trailing finished runs window: 30.
- Totals: discovered 1373, credited unique insertions 1284, resolved 57, failed 89,
  source-run observations 14.
- inbox: runs 2, discovered 0, credited unique insertions 0, resolved 0, failed 0.
- tracker_jobright: runs 2, discovered 456, credited unique insertions 432,
  credited unique rate 0.9473684210526315, resolved 30, failed 0, resolution rate 1.0.
- tracker_simplify: runs 4, discovered 278, credited unique insertions 269,
  credited unique rate 0.9676258992805755, resolved 24, failed 21,
  resolution rate 0.5333333333333333.
- tracker_vansh: runs 6, discovered 639, credited unique insertions 583,
  credited unique rate 0.9123630672926447, resolved 3, failed 68,
  resolution rate 0.04225352112676056.
- Status backlog: DISCOVERED 1047 (oldest `2026-07-04T15:43:16.283331+00:00`);
  FILTERED_OUT 288 (oldest `2026-07-04T15:43:16.283331+00:00`); RESOLVE_FAILED 6
  (oldest `2026-07-05T12:33:31.339457+00:00`); SCORED 27 (oldest
  `2026-07-04T20:57:38.154506+00:00`); SHORTLISTED 18 (oldest
  `2026-07-04T20:57:38.154506+00:00`).

The baseline's `credited_unique_insertions` metric is source-order attribution after
deduplication. It is not causal or Shapley marginal contribution, so it is a starting point
for M9D source evaluation, not proof that a source independently caused those unique jobs.

**Verification:** `.venv/bin/pytest -q` passed with 411 tests; `git diff --check` passed.
`rg -n "crawlee|apify|mcp" src scripts pyproject.toml` returned no matches. No schema,
dependency, crawler, agent, Apify, or new-source work entered M9D-0. M9D-1 through M9D-5
remain unimplemented.

## 2026-07-15 — M6.10 offline implementation through Task 7

M6.10 was continued from the approved resolution-runtime-hardening plan after Tasks 1-5 had
already been committed. Task 6 added reliable finalization for partial and aborted runs.

**Implemented boundary:** `run_ingest.main()` now creates a run-scoped `ResolutionSummary`
before vulnerable work, creates one `CircuitBreakingBrowserClient(Crawl4AIBrowserClient())`
when browser resolution is enabled, and passes both into `run_resolution()`. The production
browser client is therefore shared for the run instead of being omitted from orchestration.

**Finalization:** `run_ingest.finalize_run()` is the single run-finalization boundary for
normal and aborted runs. It closes the browser client before DB finalization, logs browser
close failures without blocking finalization, writes partial per-source resolved/failed
counts from `ResolutionSummary.per_source`, calls `db.finish_run()` once, and always writes
valid JSON notes. Notes include `run_outcome`, `resolution_summary`, reason-code counts, and
optional `discovery_issues`/bounded `fatal_error` diagnostics. `KeyboardInterrupt` and other
`BaseException` subclasses are finalized as `aborted` and then re-raised; the original
interrupt is not swallowed or converted.

**Preserved behavior:** discovery source selection, checkpoint commits, inbox ingestion,
all-selected-source/checkpoint exit semantics, resolve-only prefilter sweeping, liveness
checks, audit JSON writing, digest generation, dry-run digest output, and existing source
accounting were preserved. Digest generation still queries the run row only after
finalization, and the existing `audit_result` object is still passed into digest rendering.

**Documentation status:** `docs/ARCHITECTURE.md` now describes the M6.10 runtime behavior as
current. `docs/ROADMAP.md` was intentionally not marked complete; Task 8's live DB smoke is
still user-gated.

**Verification:** `.venv/bin/python -m pytest -q` passed with 464 tests. `git diff --check`
passed. The user-owned `tests/test_scoring_stress.py` change, `docs/2605.27371v1.pdf`,
`docs/_Aditya___Sood_.pdf`, and `docs/superpowers/reports/` remained unstaged and untouched
by the M6.10 commits. No live DB mutation, dependency, schema migration, M9D-1 work, M8
work, or scoring investigation was performed.

## 2026-07-15 — M6.10 live smoke completed

Task 8 of the approved M6.10 plan was run only after user approval. Before mutating
`data/jobs.db`, a timestamped backup was created at
`data/jobs.db.pre-m6.10-smoke-20260715T081900Z.bak`. Baseline status counts were:
DISCOVERED 366, FILTERED_OUT 697, RESOLVED 214, RESOLVE_FAILED 64, SCORED 27, and
SHORTLISTED 18. Two older unfinished run rows already existed (`runs.id` 12 and 13) with
zero counters.

Narrow process checks found no active `src.run_ingest` or `score_batch.py` process before
the smoke. A first sandboxed run of
`.venv/bin/python -m src.run_ingest --resolve-only --resolve-limit 5 --db data/jobs.db`
completed without status changes but recorded five transient `http_transport` outcomes,
which was treated as sandbox-network evidence rather than acceptance evidence.

The approved live-network rerun of the same bounded command completed as `runs.id` 16:
`run_outcome=completed`, `resolved=0`, `failed=5`, `manual_failed=5`, `tier1_resolved=0`,
`tier2_resolved=0`, and `filtered_out=0`. Its `resolution_summary` recorded
`content_failed=5`, `manual=5`, `transient=0`, `internal=0`, and
`reason_codes={"no_acceptable_content": 5}`. `run_sources` recorded the five failures under
`tracker_jobright`. Final status counts were DISCOVERED 361, FILTERED_OUT 697, RESOLVED
214, RESOLVE_FAILED 69, SCORED 27, and SHORTLISTED 18, so exactly five eligible rows were
processed and converted to deterministic content/manual failures.

Post-smoke verification passed with `.venv/bin/python -m pytest -q` reporting 464 tests.
M6.10 is therefore complete. Calibration-contract correction, M9D-1, M8, dependency work,
and scoring changes remain separate future milestones.

## 2026-07-15 — M6.11 offline configurable eligibility implementation

M6.11 offline implementation completed through Task 9. Eligibility policy now lives in
`config/eligibility.yaml`; `config/location_taxonomy.yaml` supplies deterministic country and
US-state vocabulary; `config/filters.yaml` is scoring-only (`score_threshold`). No dependency
or schema migration was added.

Accepted policy semantics implemented offline: country is evaluated first; explicit non-US
roles filter before resolution; unknown country evidence is preserved; full-time 2027 roles
pass; full-time roles with no stated start pass post-resolution with `start_date_unknown`;
internships require Spring 2027 or January-May 2027 evidence; explicit no-sponsorship and
US-citizens-only requirements filter; sponsorship silence passes; generic authorization
language passes with `authorization_ambiguous`.

`src/prefilter.py` is now an orchestration adapter around the pure evaluator and DB helpers.
Audit I2/I6a use the same typed policy as ingestion. `scripts/eligibility_impact.py` provides
a read-only preview and guarded apply path with explicit `--confirm APPLY` plus backup
requirements; live preview/apply/smoke remain Task 10 and were not run.

Offline verification: focused M6.11 suite passed with 130 tests; full suite passed with
538 tests. User-owned `tests/test_scoring_stress.py`, the untracked PDFs, and
`docs/superpowers/reports/` were left untouched. Calibration Contract v2, M8, M9D, Crawlee,
and Apify were not started.

## 2026-07-16 — M6.11 live acceptance completed

M6.11 Task 10 was completed through the two required user-supervised gates. Before preview,
no active `src.run_ingest`, scoring, import, impact, or audit process was found. Baseline
live DB evidence for `data/jobs.db`: size 9,478,144 bytes, `PRAGMA integrity_check=ok`, git
HEAD `cbb9d4c`, and status counts DISCOVERED 361, FILTERED_OUT 697, RESOLVED 214,
RESOLVE_FAILED 69, SCORED 27, SHORTLISTED 18. The only dirty worktree files were the known
user-owned `tests/test_scoring_stress.py`, two untracked PDFs, and `docs/superpowers/reports/`.

The read-only preview was saved at `data/eligibility-impact/20260716T063102Z-preview.json`.
The DB SHA-256 before and after preview was identical
(`9afd1d455feae95de17f36910214d11f2803ba894a500f73b5bdfcd83e3ef087`), confirming no DB
mutation. Previewed actionable transitions: 488 total — 80 `filter_active`, 94
`filter_discovered`, and 314 `restore_legacy`. Reason counts were `eligibility:country` 34,
`eligibility:opportunity_type` 8, `eligibility:start_window` 118,
`eligibility:work_authorization` 14, legacy `location` 179, and legacy `title_include` 135.
There were zero terminal/report-only observations.

After explicit preview approval, the current preview was recomputed and matched the approved
transition set exactly. The guarded apply command used backup
`data/backups/jobs-pre-m6.11-20260716T072916Z.db` and applied 488 of 488 previewed
transitions. Backup and live DB integrity checks both returned `ok`. Verification found zero
transition-effect errors, zero terminal-row changes, zero unrelated-row changes, zero
restored-row scoring-clear errors across 314 restored legacy rows, and zero scoring
preservation errors across 13 newly filtered SCORED/SHORTLISTED rows. Post-apply preview
returned zero actionable transitions. Post-apply status counts were DISCOVERED 267,
FILTERED_OUT 557, RESOLVED 461, RESOLVE_FAILED 69, SCORED 17, SHORTLISTED 15.

After explicit smoke approval, the bounded command
`.venv/bin/python -m src.run_ingest --resolve-only --resolve-limit 5 --db data/jobs.db` was
run. A sandboxed first attempt produced five transient `http_transport` outcomes and no job
status changes, so it was treated as sandbox-network evidence. The approved live-network
rerun completed as `runs.id` 18 with `run_outcome=completed`, `resolved=0`, `failed=5`,
`manual_failed=5`, `transient=0`, `internal=0`, and
`reason_codes={"no_acceptable_content": 5}`. It processed exactly five eligible rows from
`tracker_jobright`; status counts became DISCOVERED 262, FILTERED_OUT 557, RESOLVED 461,
RESOLVE_FAILED 74, SCORED 17, SHORTLISTED 15. The live sample did not contain an explicit
non-US discovered row because the approved apply had already filtered such rows; the offline
no-resolver-call tests remain the deterministic country-first evidence.

Post-smoke preview again returned zero actionable transitions. Final verification passed:
`.venv/bin/python -m pytest -q` reported 538 tests, and `git diff --check` passed. M6.11 is
complete. Calibration Contract v2, M8, M9D, Crawlee, Apify, and any unrelated milestone work
were not started.

## 2026-07-16 — Calibration Contract v2 implemented

The original Phase 2 worksheet (`data/calibration/2026-07-12.user.md`) was confirmed to be a
metadata-interest artifact, not JD-informed model ground truth. The defect was semantic:
the user made calls from digest metadata, while the scorer sees JD text. Treating those as
the same judgment created false calibration disagreements when the full JD introduced
citizenship restrictions, specialty mismatch, level mismatch, or other information not
present in the digest.

Approved contract now separates `interest_call` and `fit_call`. `interest_call` is recorded
before the user sees JD text and is diagnostic only. `fit_call` is recorded after the user
reads the complete JD and before any model score is shown; only `fit_call` is calibration
ground truth. `APPLY` means the user would submit an application. `MAYBE` means the posting
is worth human review. For the 7+ shortlist boundary, `APPLY` and `MAYBE` are positive;
`SKIP` is negative. `interest_call -> fit_call` changes are reported separately from model
disagreements.

Implementation added `src/calibration.py` for typed artifact parsing/rendering, provenance
validation, strict scored-file coverage validation, legacy parsing, and comparison
semantics. `scripts/calibration_packet.py` now creates immutable v2 round batches and
metadata-only interest worksheets, then reveals full-JD fit worksheets through a read-only
SQLite connection. Complete JDs are retrieved via `src.db.calibration_jobs_by_ids`;
DB-backed report compatibility reads scores via `src.db.calibration_scores_by_ids`.
`scripts/calibration_report.py` now requires v2 fit ground truth and prefers
`--scored-file`.

The historical worksheet stayed byte-identical with SHA-256
`c094aeabcadd1e6eead34e498083baf8aa208d26d1c3767ee4950242bcee7e6c`. It remains valid
legacy interest-only evidence, but the v2 report refuses to use it as fit ground truth and
instructs the user to start a v2 round.

Scope intentionally did not include changing `docs/scoring_prompt.md`,
`config/profile_summary.md`, `scripts/score_batch.py`, scoring aggregation/model invocation,
`config/filters.yaml`, the threshold value, DB schema, live job statuses/scores, production
DB contents, stress-band anchors, M8, M9D, discovery, tailoring, dependencies, or a first
real v2 calibration round.

Verification: focused Task 7 suite passed with 180 tests:
`.venv/bin/python -m pytest -q tests/test_calibration_contract.py tests/test_calibration_packet.py tests/test_calibration_report.py tests/test_db.py tests/test_export_batch.py tests/test_score_batch.py tests/test_import_scores.py`.
Full suite passed with 608 tests before documentation edits. The documentation-only follow-up
used `git diff --check`. Next human action is to export a fresh eligibility-passed batch,
start a v2 round with `scripts/calibration_packet.py start`, complete the interest and fit
worksheets blind to scores, then run `scripts/calibration_report.py` against the resulting
fit worksheet and scored JSON.
