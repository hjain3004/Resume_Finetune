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
