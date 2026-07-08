# PHASE2_KICKOFF.md — M6 Patch + Scoring Calibration Protocol

Context: Stage 1 (M0–M5) is built and mechanically sound. Review of the first real batch
export (2026-07-05, 19 jobs) found three data-quality issues that must be fixed before
scoring calibration begins. This doc specifies the fix milestone (M6) and then the Phase 2
calibration protocol. ARCHITECTURE.md remains authoritative for everything not amended here;
this file amends §11 (batch export schema) and adds resolver post-processing rules.

---

## Findings being fixed (evidence from the 2026-07-05 batch)

1. **Near-duplicate rows reach the batch.** Same company+title with near-identical jd_text
   exported multiple times (Relativity ×6 — five byte-identical except a "· N hours ago"
   timestamp; Neuralink ×4; Serco ×2). Root cause: location-scoped dedup keys are working as
   designed, but export doesn't collapse content duplicates.
2. **Jobright-sourced rows resolve to jobright.com listing pages, not employer ATS pages.**
   jd_text contains aggregator chrome (tag strings, "H1B Sponsor Likely", sponsorship trend
   tables, Crunchbase funding data, news links) and the JD prose is Jobright's AI summary,
   not the employer's original wording. Acceptable for scoring after cleaning; NOT acceptable
   as tailoring input (Phase 3 requires the employer's literal phrasing).
3. **Batch export lacks `location` and structured flags**, so the scorer can't weigh
   geography or sponsorship signal.

## M6 — Batch quality patch

### M6.0 Repair the dark sources (do this FIRST)

Live-DB evidence (2026-07-05): 24 of 25 `tracker_vansh` rows stuck at `resolve_attempts=2`
(systematic resolution failure, not flakiness); zero `tracker_simplify` rows exist and
`runs.notes` is empty (adapter returned zero rows silently — no exception).

1. **Vansh resolution failures — diagnosis CONFIRMED (2026-07-05).** The 24 stuck URLs are
   company career-site wrappers and long-tail ATSs, not big-4 ATS domains. The generic
   resolver correctly rejects their JS-rendered shells. Fixes, in this order:
   a. **Ashby bug**: `jobs.ashbyhq.com/creditgenie/...` failed despite the M2 ashby resolver.
      Reproduce interactively, find root cause (org-slug parsing? API shape? posting-id
      match?), fix, add regression fixture. This is a defect, not a gap.
   b. **Greenhouse unwrap via `gh_jid`**: any URL containing a `gh_jid` query param
      (seen: amperity.com, esri.com, linksquares.com) → extract the job id; derive the board
      token by trying, in order: (i) the site's second-level domain name, (ii) fetching the
      wrapper page once and regexing for `boards.greenhouse.io/{token}` or
      `greenhouse.io/embed/job_board?for={token}`. On success resolve via the existing
      greenhouse resolver; store the derived URL in `ats_url`.
   c. **Known-wrapper map**: `config/wrapper_map.yaml`, e.g.
      `careers.roblox.com: {ats: greenhouse, board: roblox, id_from: path}` — checked by the
      router before the generic fallback. Seed it with roblox; it grows over time.
   d. **Amazon.jobs resolver**: dedicated resolver (high posting volume for this candidate).
      Amazon job pages are backed by JSON (inspect the page's network calls once during dev;
      there is a search/detail JSON endpoint pattern). Defensive parsing like workday.
   e. **Everything else** (tesla.com [bot-protected], icims, ultipro, successfactors,
      peraton, softheon, applytojob, one-offs): leave as RESOLVE_FAILED → digest "needs your
      help". POLICY (add to CLAUDE.md): a domain earns a dedicated resolver only after
      failing ≥3 times on postings the user marked as wanted. No resolver arms races.
   Before the first repaired run, reset stuck rows' resolve_attempts to 0 (documented
   one-off command). Do NOT raise attempt limits or add retries — failures are deterministic.
2. **Simplify silent zero.** Check, in order: (a) `config/sources.yaml` — is the adapter
   enabled? (b) run the adapter standalone with DEBUG logging — does listings.json fetch and
   parse? (c) inspect the snapshot file — did the first run incorrectly mark everything seen?
   Fix root cause, add a regression test with the real listings.json fixture.
3. **Observability fix (prevents recurrence).** Add per-source counters to each run:
   new table `run_sources(run_id, source, discovered, inserted, resolved, failed)`, populated
   every run, and a "Per-source" line in the digest's run summary. Acceptance: a source
   returning zero discoveries is visibly zero in the digest, not invisible.

### M6.1 Content-hash duplicate collapse (export-time, not dedup-key change)

Do NOT change the dedup key or delete rows. In `scripts/export_batch.py`:

- Compute `content_hash = sha256(normalize_jd(jd_text))` where `normalize_jd`:
  lowercases; removes any line matching `^.{0,60}·\s*\d+\s*(minutes?|hours?|days?)\s+ago`;
  collapses all whitespace runs to single spaces.
- Group RESOLVED rows by `(norm(company), content_hash)`. For each group, export ONE
  representative object with a new field `"row_ids": [all ids in group]` (keep `"id"` as the
  representative's id for backward compat).
- Additionally group by `(norm(company), norm(title))` where jd_texts are *similar but not
  identical* (e.g. Neuralink's 4 location variants): similarity = Jaccard over 5-word
  shingles ≥ 0.85. Same treatment: one representative, all row_ids. Keep this helper pure
  and unit-tested; if the shingling approach proves fiddly, ask the user before substituting
  a library.
- `scripts/import_scores.py`: apply the scored result to every id in `row_ids`. Validation:
  every exported row_id must be covered exactly once across the scored file; reject otherwise.

### M6.2 Unwrap aggregator/wrapper pages to the original ATS posting

General principle (user requirement): whenever a discovered URL is an aggregator or wrapper
page (jobright, company career shells, anything with an embedded ATS reference), the pipeline
must resolve the ORIGINAL employer posting, not the wrapper's rendition. M6.0(b–c) covers
career-site wrappers; this section covers jobright. Two-part fix in this order:

1. **ATS link extraction (preferred path).** When the resolved final URL's host is
   `jobright.com`/`jobright.ai`: fetch the page, extract the outbound apply/original-posting
   URL (look for anchors whose href leaves the jobright domain toward a known ATS host from
   the router table, or an "Apply" / "Original" link). If found: re-route resolution to that
   URL through the normal router, set `resolver` to the underlying resolver's name, and store
   the ATS URL in a new column `ats_url TEXT` (nullable; ALTER TABLE, idempotent migration in
   `db.py`). Record the jobright URL in `notes`.
2. **Fallback cleaning.** If no outbound ATS link is found, keep the jobright text but clean
   it deterministically:
   - Drop everything from the first line matching any of:
     `^Trends of Total Sponsorships`, `^Funding$`, `^Recent News`, `^Company data provided by`
     — whichever appears first — to the end.
   - Drop leading "Company · N hours ago" line (same regex as M6.1).
   - Drop tag-soup lines: a line with ≥ 4 CamelCase-concatenated tokens and no sentence
     punctuation (heuristic; unit-test against the saved fixture).
   - Detect `H1B Sponsor Likely` / `H1B Sponsorship` markers BEFORE dropping them → add
     `"sponsor_likely"` to the row's `flags` JSON.
   - Set a new column `jd_quality TEXT` to `'ats'` (path 1 or non-jobright resolvers) or
     `'aggregator'` (path 2). Phase 3 will require `jd_quality='ats'` before tailoring;
     aggregator-quality rows that get SHORTLISTED go to the digest's "Needs your help" section
     asking the user to drop the real posting URL into inbox/urls.txt.

### M6.3 Export schema v2

Batch objects become:

```json
{"id": 77, "row_ids": [77, 79, 81, 85, 92, 93], "company": "Relativity",
 "title": "Software Engineer", "locations": ["Chicago, IL", "Remote"],
 "flags": ["sponsor_likely"], "jd_quality": "aggregator",
 "jd_text": "..." }
```

`locations` = distinct locations across the group, in id order. Update
`docs/scoring_prompt.md` (see M6.4) and `import_scores.py` validation to match.

### M6.4 Scoring prompt corrections

- `base_variant` allowed values are EXACTLY `backend` or `ml` (closed enum; remove the
  `frontend` example). `import_scores.py` rejects anything else.
- Scorer must consider `locations` (candidate is San Jose, CA; remote-US and Bay Area
  strongest, other US metros acceptable for a new grad — encode this preference in
  `profile_summary.md`'s Notes, not hardcoded in the prompt) and `flags`.
- Add: "Ignore any residual company-funding, news, or sponsorship-trend content in jd_text;
  score only against role requirements."
- Replace the unanchored 0–10 scale with anchors:
  - 9–10: role's core stack overlaps the candidate's primary evidence (Java/Spring or
    Python backend, Kafka/microservices, or explicit LLM-integration work); level explicitly
    new-grad/early-career; no disqualifiers.
  - 7–8: strong overlap with minor gaps (one unfamiliar core technology, or level ambiguous).
  - 5–6: partial overlap; would require the `ml` variant to stretch, or stack is adjacent
    (e.g., C#/.NET, Go) but role is otherwise entry-level appropriate.
  - 3–4: wrong specialty (frontend-only, embedded, EE-heavy) or demands >2 yrs professional.
  - 0–2: no meaningful overlap or hard disqualifier (clearance-required, licensure, etc.).
  Note: `flags:["sponsorship_risk"]` from the prefilter should CAP the score at 6 with the
  rationale noting it, never silently zero it — the user decides on those.
- The wrapper (not Claude) runs `import_scores.py` after the headless call; remove the
  instruction telling Claude to run it.

### M6.5 Tier-2 browser resolver (crawl4ai)

Approved new dependency: `crawl4ai` (brings Playwright + Chromium; run its post-install
setup). Update CLAUDE.md's dependency list accordingly. This formalizes a three-tier
resolution ladder:

- Tier 1: structured resolvers + unwrap rules (M6.0/M6.2). Always attempted first; nothing
  about them changes.
- Tier 2: `resolve/browser.py` — used ONLY when no tier-1 resolver applies AND `generic.py`
  fails its quality heuristic. Renders the page with crawl4ai, takes the markdown output,
  applies the SAME ≥400-chars + JD-keyword quality heuristic before accepting. Config toggle
  `browser_resolver: true` in sources.yaml; when disabled, behavior is exactly pre-M6.5.
- Tier 3: RESOLVE_FAILED → digest "needs your help" (unchanged).

Constraints (hard):
- Use crawl4ai's deterministic rendering/markdown only. Its LLM-extraction strategies are
  FORBIDDEN in this repo (no model calls inside src/, no API keys in the pipeline).
- No stealth/anti-bot-evasion features. Default browser fingerprint, honest behavior. If a
  site blocks a plain headless browser (expected: tesla.com), it stays tier-3. Document this
  in the module docstring.
- Respect the same per-host rate limit as the polite session; browser fetches count.
- Async is contained: crawl4ai is async — wrap in `asyncio.run()` inside browser.py; the
  rest of the pipeline stays sync.
- Also use the rendered DOM for M6.2's jobright apply-link extraction when static HTML
  yields no outbound ATS link (reuse browser.py's fetch, not a second implementation).

M6.5 acceptance:
- With the toggle off: full test suite passes identically to pre-M6.5 (proves isolation).
- Fixture tests: browser resolver accepts a rendered careers-page fixture, rejects a
  blocked/empty fixture (crawl4ai calls mocked at the module boundary; no browser in pytest).
- Live smoke: at least the qualtrics row from the 2026-07-05 stuck set resolves via tier 2;
  tesla rows appear in "needs your help" with a note that a browser attempt was made.
- Digest run summary gains a per-tier resolution count (t1/t2/manual) so the user can see
  whether tier 2 is earning its 400MB.

### M6 acceptance criteria (M6.0–M6.4)

- M6.0: the ashby defect is fixed with a regression test; gh_jid unwrapping resolves the
  amperity/esri/linksquares rows; the roblox wrapper-map entry resolves both roblox rows;
  amazon.jobs resolver resolves the 5 amazon rows; remaining long-tail rows are visibly
  listed in the digest's "needs your help" (NOT silently stuck); simplify contributes > 0
  discovered rows (or the digest's per-source line proves the adapter ran on an empty day);
  every run row has per-source counts.
- Unit: normalize_jd strips the "· N hours ago" line and whitespace-collapses (fixture-based:
  two Relativity texts → equal hashes). Shingle similarity: two Neuralink variants ≥ 0.85;
  a Relativity vs an Amazon text < 0.85.
- Unit: jobright cleaner on the saved Amazon fixture removes the funding/news tail and tag
  line, preserves Responsibilities/Qualifications, and emits the sponsor flag.
- Integration: re-export the 2026-07-05 data → batch contains ~10 objects (one per real
  posting), each with correct row_ids, locations, jd_quality.
- Round-trip: scored file applies to all row_ids; a scored file missing a group is rejected.
- Migration: running the pipeline on the existing DB adds ats_url/jd_quality columns without
  data loss; second run makes no schema changes.

### M6.6 Completion punch list (from the 2026-07-06 batch audit)

Audit of the first post-M6 export found these incomplete. Each is REQUIRED before Phase 2
calibration begins:

1. **Shingle-similarity grouping (M6.1) not collapsing near-duplicates.** Evidence:
   Neuralink "Software Engineer, BCI Applications" still exports as 3 objects; Serco as 2.
   Implement or fix the Jaccard-over-5-word-shingles ≥ 0.85 grouping. Fixture: the two live
   Neuralink variants MUST group; a cross-company pair MUST NOT.
2. **Aggregator cleaning (M6.2 fallback) not applied.** Evidence: 23/28 exported objects
   still contain "H1B Sponsor Likely" / funding sections / "· N hours ago" lines. Implement
   the cleaner AND run a one-off re-resolution pass: every row whose jd_text matches
   aggregator-chrome patterns is re-resolved through the current pipeline (ATS unwrap first,
   cleaning fallback), regardless of status or resolve_attempts. Document the one-off
   command in DECISIONS.md.
3. **Export schema v2 (M6.3) missing entirely.** Add locations, flags, jd_quality to every
   exported object per M6.3 and enforce presence in import_scores.py validation.
4. **Prefilter semantics fix (amends ARCHITECTURE §7).** Evidence: "Graduate Research
   Scientist" and "Student Researcher" postings passed via the new-grad regex.
   Change title_include to the role-family regex ONLY
   ("software|swe|backend|back.end|full.?stack|platform|infrastructure|distributed|developer");
   delete the level/new-grad regex from includes (level is already enforced by
   title_exclude + years_cap). Re-run the prefilter over existing RESOLVED rows and report
   how many flip to FILTERED_OUT; the two research postings must be among them.

M6.6 acceptance: re-export the current DB → Neuralink ≤ 2 objects, Serco ≤ 2; zero objects
match chrome patterns; every object carries locations/flags/jd_quality; research-role leak
closed with a regression test.

### M6.7 Scoring architecture amendment (evidence: RecruitBench, Sood 2026) — CLOSED 2026-07-08

Items 1 and 2 built (`scripts/score_batch.py`, `scripts/scoring_stress.py` +
`tests/fixtures/scoring_stress/cases.json`); item 3 (exemplar injection) correctly deferred —
see the "M6.7" entry in DECISIONS.md.

Benchmark evidence (RecruitBench: outcome-grounded evaluation of LLM job-fit scoring
against real interview progression) shows monolithic scoring of large pools under-scores
true positives (lost-in-the-middle / context bloat): parallel batches of ~6 doubled recall
at unchanged precision and improved rubric-band calibration vs. one large prompt.
Amendments:

1. **Sub-batched scoring.** The scoring wrapper splits the exported batch into chunks of
   at most 6 objects, invokes the headless scorer once per chunk (same prompt, chunk-local
   input file), and concatenates results before import validation. import_scores.py
   validation is unchanged (row coverage is checked across the concatenated whole).
2. **Synthetic score-band suite.** `tests/fixtures/scoring_stress/`: 8–10 synthetic JDs
   paired with expected score bands from the anchored scale (perfect backend match
   [8.5–10]; hard-requirement miss [2.5–4.5]; wrong specialty [3–4]; sponsorship_risk case
   [≤6 cap]; keyword-stuffed JD; stale/vague JD). `scripts/scoring_stress.py` runs them
   and reports band adherence. Run at calibration start and after ANY change to
   scoring_prompt.md or profile_summary.md (ties into SELF_HEALING D2 discipline; prompt
   files remain PROTECTED post-calibration).
3. **Exemplar injection (deferred until ≥20 calibration labels exist).** Include the 3–5
   most similar past user decisions (APPLY/SKIP + one-line reason) in the scoring prompt
   as few-shot exemplars, selected by shingle similarity of JD texts. Gate: only after
   calibration Step 5 completes once; log exemplar ids in the trace (I11).

### M6.8 Freshness & recycling defense (stale/reposted jobs) — CLOSED 2026-07-08

See the "M6.8" entry in DECISIONS.md for what was built, the I7 idempotency-test update it
required, and the scope decisions (liveness recheck limited to 404/410; I13 deferred to M7).

Observed problems: aggregators recycle old postings as new; postings die within days
(link-rot finding, M6.0); exact reposts are silently suppressed forever (correct for
noise, wrong for legitimately re-opened roles); no staleness visibility at discovery.
User-approved schema/state-machine changes (PROTECTED items; approval recorded here):
columns `last_seen_at TEXT`, `repost_count INTEGER DEFAULT 0`; new terminal status
`CLOSED` (posting verified dead).

1. **Stale-at-discovery flag.** If date_posted is present and older than `stale_days`
   (config, default 21) at discovery → flag `stale_listing`. The scoring prompt treats it
   as a soft negative (must mention in rationale); the digest shows it.
2. **Repost detection.** On dedup-key conflict: update the existing row's `last_seen_at`,
   increment `repost_count` (cheap, no behavior change). Additionally, for genuinely new
   rows after resolution: compare content (same norm(company), shingle ≥ 0.85) against
   TERMINAL rows (FILTERED_OUT / REJECTED / APPLIED / CLOSED); on match → flag `repost`,
   record prior row id + prior outcome in notes; digest renders "recycled: you
   [skipped/applied] on <date>". Never silently re-shortlist recycled content the user
   already rejected.
3. **Resurfacing rule (narrow).** A dedup conflict whose existing row is RESOLVE_FAILED
   or CLOSED, with last_seen_at older than `reopen_days` (default 45): reset that row to
   DISCOVERED with flag `reopened` — it was never actually evaluated, or it died and is
   genuinely back. All other terminal statuses stay suppressed.
4. **Liveness recheck.** At digest time, SHORTLISTED/TAILORED rows unchecked for
   `liveness_days` (default 5) get one polite GET of ats_url (or url): 404/410/absence
   from the board's live listing → status CLOSED, digest note. Never tailor against a
   CLOSED row.
5. **Audit hook (I13 — add to the SELF_HEALING suite when building M7).** WARN on: any
   SHORTLISTED row with no liveness check within `liveness_days`; any exported object
   carrying `stale_listing` with fit_score ≥ 9 whose rationale doesn't mention staleness
   (prompt-adherence spot check).

### M6.9 Residual engineering notes (small, do alongside M6.7/M6.8) — items 1–2 CLOSED 2026-07-08

Item 1: no apply/original-posting URL field exists in jobright's `__NEXT_DATA__` payload —
probed, no code change (see DECISIONS.md). Item 2: `clean_title()` added to
`src/models.py`, wired into `db.mark_resolved()`'s title backfill — see DECISIONS.md. Item 3
is a policy note, not a task; nothing to build.

1. **jd_quality starvation — `__NEXT_DATA__` apply-URL probe.** Only 4/25 objects in the
   2026-07-08 batch are jd_quality='ats'; Phase 3's gate needs a steady ats supply. The
   jobright `__NEXT_DATA__` blob already parsed for JD fields very likely also carries an
   apply/original-posting URL field (the M6.2 session extracted jobSummary/qualifications/
   isH1bSponsor but did not probe for a URL). Inspect the saved fixture's full JSON for
   any field resembling applyLink/originalUrl/jobUrl; if present, feed it to the router as
   the ATS unwrap path (path 1), which should convert most jobright rows to 'ats'. If
   absent, no change — the "needs your help" paste path remains the valve.
2. **Title backfill hygiene.** Resolver raw_title backfill imports page furniture (live
   example, id 52: "Front End Developer (Hybrid) - 28751 Job Details"). On backfill,
   strip trailing requisition IDs and boilerplate suffixes ("Job Details", "| Careers",
   site-name suffixes) using the same normalization family dedup already applies. Display
   titles must be human-clean; dedup keys are unaffected (already normalized).
3. **Do NOT prefilter front-end/embedded titles.** They pass via the role-family regex by
   design; the anchored scale prices wrong-specialty at 3–4 and the scorer sees context
   the regex can't. Revisit only if wrong-specialty rows exceed ~20% of scored volume.

### Calibration protocol amendments (evidence-derived)

- **Threshold asymmetry (apply during Step 5).** The costs are asymmetric: a mediocre
  shortlist entry costs ~90 seconds of review; a missed strong job costs an opportunity —
  and correlated algorithmic screening across employers (Bommasani et al., FAccT 2026)
  makes breadth structurally more valuable than naive independence assumptions suggest
  (~25 applications for the systemic-rejection risk that ~10 would give under independent
  decisions). Therefore: when the calibration data leaves the threshold ambiguous between
  two values, choose the LOWER one (favor recall); tune upward only if review burden
  becomes real.
- **Track disagreements by segment.** When logging calibration disagreements (Step 3),
  tag each with role family (backend/ml/adjacent) and company type. Per-segment variance
  is the expected failure shape (RecruitBench found large per-job variance in LLM
  scoring); a segment-clustered disagreement pattern means the fix is a targeted
  profile_summary note for that segment, not a global anchor change.
- **Outcomes journal gains an `ats_vendor` column** (populate from the row's resolver /
  ats_url host at APPLIED time; carried into Phase 3's D5 outcomes.csv). Rationale:
  screening outcomes correlate within a vendor's stack (monoculture finding); after
  sufficient volume, rejections clustering by vendor is actionable signal (diversify
  where you apply) that per-company tracking cannot reveal.

---

## Phase 2 — Calibration protocol (human process, not code)

Goal: make `fit_score` mean the same thing to Claude as it does to the user, then set the
SHORTLISTED threshold. This is deliberately manual for 1–2 weeks.

**Step 1 — Blind baseline (first batch after M6).** Before looking at Claude's scores, the
user reads the digest and privately marks each unique job: APPLY / MAYBE / SKIP. Keep it in
`data/calibration/YYYY-MM-DD.user.md`.

**Step 2 — Run scoring.** Export → `claude -p` with the corrected prompt → import.

**Step 3 — Compare.** A tiny script (`scripts/calibration_report.py`, M6-adjacent, trivial)
prints jobs where the user said APPLY but score < 7, or SKIP but score ≥ 7. These
disagreements are the only interesting rows.

**Step 4 — Fix the *inputs*, not the scores.** For each disagreement, decide which of these
is the cause and amend it:
- profile_summary.md Notes (most common fix — e.g., "I don't want ServiceNow/low-code roles"
  belongs there)
- the anchor definitions in the prompt
- a prefilter rule (if the job should never have reached scoring)
Never hand-edit scores in the DB; the DB reflects what the system believes.

**Step 5 — Repeat daily until** two consecutive batches have zero threshold-crossing
disagreements. Then set `shortlist_threshold` in config to the boundary the exercise
revealed (likely 7.0–7.5) and scoring goes on autopilot with spot-checks.

**Exit to Phase 3** (per ROADMAP.md): ≥15–20 real jobs reviewed, disagreement rate
acceptable to the user, AND the jd_quality pipeline reliably produces `ats`-grade text for
shortlisted jobs — because tailoring cannot start from aggregator paraphrases.
