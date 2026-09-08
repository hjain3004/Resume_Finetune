# Job Ingestion Run Report — 2026-09-08

Isolated real ingestion of full-time US new-grad / early-career software roles.
Confirmed posting window: **2026-09-01 … 2026-09-08 inclusive**. Candidate willing to
work anywhere in the US; onsite/hybrid/relocation not penalized; no undocumented work
authorization inferred.

Paths below are written as `<repo>` = the job-pipeline checkout and `<parent>` = its
parent directory.

## 1. Git commit used for execution
- **Commit:** `af9418fd1e8aed5bcca4b1325ef637d6aa815645` (`feat(m8n0c): implement atomic keyword placement contract repair`)
- Local `main` HEAD == `origin/main` == this commit at checkpoint (fetched; 0 divergence).
- Ingestion ran from a **detached worktree** at that commit (`<parent>/ingest-worktree-20260908T064433Z`),
  cwd = worktree so `src/` + `config/` were the pristine committed versions; `--db` / `--snapshot-dir`
  / `--digest-dir` / `--audit-dir` pointed at the real repo by absolute path. Worktree removed after the run.
- **Pre-run M8N working tree** (recorded, untouched throughout): `M src/tailor/placement.py`,
  `M src/tailor/s1.py`, `M src/tailor/s3.py`, `M tests/render/test_l7_tailored.py`,
  `M tests/tailor/test_s1_atomic.py`, `M tests/tailor/test_trace_replay.py`, + 11 untracked files.

## 2. Database backup
- **Path:** `<parent>/jobs.db.backup-20260908T064433Z` (outside the repo; no existing file overwritten)
- **SHA-256:** `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`
  (identical to `data/jobs.db` before the run; still intact post-run)

## 3. Ingestion exit code
**0** — `run_outcome: "completed"`. Run id **22**, 2026-09-08T06:45:29Z → 08:28:09Z (1h43m).
Command (no `--dry-run`, no `--limit`, no `--resolve-limit`):
```
python -m src.run_ingest \
  --db <repo>/data/jobs.db \
  --snapshot-dir <repo>/snapshots \
  --digest-dir <repo>/data/digests \
  --audit-dir <repo>/data/audit
```

## 4. Counts per source (`run_sources`, run 22)

| Source | Discovered | Newly inserted | Resolved | Failed | Filtered |
|---|---|---|---|---|---|
| tracker_vansh | 17 | 17 | 8 | 253 | — |
| tracker_simplify | 2633 | 2628 | 1874 | 219 | — |
| tracker_jobright | 562 | 531 | 137 | 295 | — |
| inbox | 0 | 0 | 0 | 0 | 0 |
| **totals** | **3212 (3176 new)** | **3176** | **2019** | **767** | **1766** |

Notes:
- `Resolved`/`Failed` per source count *this-run resolution outcomes for all `DISCOVERED` rows of that
  source, including July backlog* — hence `tracker_vansh` failed 253 against 17 new inserts (old
  vansh-sourced rows retried and failed). Discovered/Inserted are this-run only.
- Schema has **no per-source `filtered` counter**. Global filtered = **1766**. Eligibility breakdown
  (`runs.notes.eligibility_summary`):
  - Pre-resolution gate: evaluated 3436, passed 41, deferred 2757, filtered 638 —
    country 437, role_family_excluded 163, opportunity_type 17, role_family 13, start_window 7, seniority 1.
  - Post-resolution gate: evaluated 2292, passed 1164, filtered 1128 —
    work_authorization 381, role_family 272, start_window 230, opportunity_type 195, seniority 48, role_family_excluded 2.
- Resolution tiers: t1 (structured/HTTP) 2019, t2 (crawl4ai browser) **0**, manual→RESOLVE_FAILED 2.
  crawl4ai ran on generic-fallback pages but 0 renders passed the content-quality gate.
- `content_failed` 767, `transient` 12 (`http_transport`), `internal` 0. Liveness recheck closed 2 rows.

## 5. Audit result and exact paths
- **Audit: FAIL** (15 invariants). See `audit.json` in this folder.
  - **I2 FAIL** — resolver-coverage gap: `www.amazon.jobs`, `www.tesla.com`, `www.equipmentshare.com`,
    `job-boards.eu.greenhouse.io`, `jobright.ai` all had 0 resolved this run (anti-bot / JS-shell; expected).
  - **I11 FAIL** — pre-existing: 37 SCORED + 34 SHORTLISTED July rows exist but `data/traces/` has no
    trace files. Not caused by this run.
  - **I1 WARN** — inbox idle 3 runs. **I7 SKIP** — idempotency (separate cadence). All others PASS.
  - Because of the FAIL the digest's "New & resolved" section is auto-suppressed (SELF_HEALING §3);
    role lists here come straight from the DB.
- **Digest:** `<repo>/data/digests/2026-09-08.md` (copy: `digest.md` in this folder)
- **Audit JSON:** `<repo>/data/audit/2026-09-08.json` (copy: `audit.json` in this folder)

## 6. Fresh-role group sizes

| Group | Definition | Total in window | RESOLVED (qualifying) | FILTERED_OUT | Still DISCOVERED (unresolved) |
|---|---|---|---|---|---|
| **A — Confirmed fresh** | `date_posted` 2026-09-01 … 2026-09-08 | 355 | **86** | 227 | 42 |
| **B — Posting date unknown** | `date_posted` NULL AND `discovered_at` in window (all 2026-09-08T06:45:31Z) | 531 | **78** | 159 | 294 |

- **Qualifying total: 164** (86 A + 78 B), status `RESOLVED`, all passing every deterministic gate
  (country / work-authorization / opportunity-type / start-window / role-family / seniority) **and**
  re-confirmed `src.eligibility.classify_opportunity_type` → `full_time` for all 164.
- 0 qualifying rows are `SCORED`/`SHORTLISTED`/`RESOLVE_FAILED`/`CLOSED`.
- **Group B rows are NOT confirmed posted within 7 days** — only discovered within the window.

## 7. Qualifying roles

All 164 rows: see **`qualifying_roles.csv`** in this folder (columns: group, id, company, title,
location, date_posted, discovered_at, source, status, fit_score, base_variant, flags, jd_quality,
url, fit_rationale). Ordering: SHORTLISTED > SCORED > RESOLVED, then fit_score desc, then group A
before B, then newest date first. Every row is `RESOLVED` and **unscored** (see §9), so fit_score /
base_variant / fit_rationale are empty for all 164; `url` is the direct ATS URL where known, else the
source URL.

**Role-family caveat:** all 164 passed the deterministic `eligibility:role_family` gate (JD-text
keyword match), so per the "not rejected by the role-family gate" criterion they are included. A
strict SWE-only reading would still hand-drop these non-dev titles that passed on JD keywords:
`4021` AMAT Data Scientist, `3999` MGB Data Analyst 1, `3978` Houlihan Lokey AI Business Development
Analyst, `3966` Geosyntec Water Resources Engineer, `3847` AMAT Data Scientist 2, `3825`/`3820`
Micron Failure Analysis Engineer, `3416` Horizon Media Data Science, `3389` KLA Systems Engineer,
`3370` Deluxe Marketing Analyst, `3322` KLA Product Development Engineer, `3313` Unlimited Hardware
Engineer, `3309` Gunvor Quant Analysis, `3289`/`3829`/`3284`/`3249` Data Scientist/Analyst, `3286`
Red Sox International Scouting, `3242` Hunter Douglas Product Specialist, `3241`/`3239`/`3238` JHUAPL
Postdoc/PhD research, `3235` Barclays Electronic Trading, `4228`/`4097`/`4106`/`4054` QA roles,
`4039` Brave BDR/SDR, `4170` Wordpress+Graphic Design, `4050` Computational Designer.

## 8. Fresh roles excluded, with deterministic reason

All 386 FILTERED_OUT rows in the window: see **`excluded_roles.csv`**. Breakdown by exact `filter_reason`:

| Reason | Group A | Group B | Meaning |
|---|---|---|---|
| `eligibility:country` | 63 | 71 | explicit non-US location evidence |
| `eligibility:work_authorization` | 53 | 36 | JD requires citizenship / clearance / "no sponsorship" |
| `eligibility:role_family` | 48 | 10 | JD text didn't match software include-terms |
| `eligibility:start_window` | 32 | 17 | stated start date outside policy window |
| `eligibility:opportunity_type` | 14 | 16 | classified internship / co-op / contract / part-time |
| `eligibility:role_family_excluded` | 9 | 8 | title hard-excluded (wrong specialty) |
| `eligibility:seniority` | 8 | 1 | senior / staff / principal / lead / manager / director |
| **total** | **227** | **159** | |

**Potentially-relevant subset** — software-titled roles excluded for a reason other than
country / work-authorization (most worth eyeballing):

| ID | Grp | Company | Title | Location | Posted | Exclusion reason |
|---|---|---|---|---|---|---|
| 4459 | B | Mach Industries | December 2026 New Graduate Engineer, Software / GNC | Huntington Beach, CA | — | eligibility:start_window |
| 4252 | B | Amazon | Software Development Engineer, Early Careers | Cambridge, MA | — | eligibility:start_window |
| 4242 | B | Vestwell | Associate, Software Engineer | Austin, TX | — | eligibility:start_window |
| 4217 | B | Audible | Software Development Engineer, Early Careers | Cambridge, MA | — | eligibility:start_window |
| 4196 | B | Applied Intuition | Embedded Test Engineer - New Grad (December 2026) | Sunnyvale, CA | — | eligibility:start_window |
| 4163 | B | Freeform | Software Engineer (New Grad December 2026) | Los Angeles, CA | — | eligibility:start_window |
| 4156 | B | WHOOP | Software Engineer I (Backend) | Boston, MA | — | eligibility:start_window |
| 4150 | B | AXQ Capital | Quantitative Developer | New York, NY | — | eligibility:start_window |
| 4141 | B | SpaceX | Software Engineer (Starlink) | Hawthorne, CA | — | eligibility:start_window |
| 4140 | B | SpaceX | Software Engineer (Starlink) | Redmond, WA | — | eligibility:start_window |
| 4112 | B | IBM | Entry Level Cloud Developer - Chicago | Chicago, IL | — | eligibility:start_window |
| 4052 | B | Parallel | Embedded Software Engineer - Vehicle Software | Los Angeles, CA | — | eligibility:start_window |
| 4037 | B | Notion | Software Engineer, New Grad (Dec 2026) | San Francisco, CA | — | eligibility:start_window |
| 4036 | B | Salesforce | Software Engineering AMTS (College Grad) | San Francisco, CA | — | eligibility:start_window |
| 4032 | B | UST HealthProof | Junior Full Stack Developer (Data CoE) | Bellevue, WA | — | eligibility:start_window |
| 4003 | A | Valmont | IT Associate Programmer Analyst | Carrollton, TX; Omaha, NE | 2026-09-05 | eligibility:start_window |
| 3979 | A | Vestwell | Associate Software Engineer | Austin, TX | 2026-09-04 | eligibility:start_window |
| 3952 | A | Spirit AeroSystems | Entry-Level Software Engineer | Wichita, KS | 2026-09-04 | eligibility:start_window |
| 3846 | A | L3Harris Technologies | Software Engineer Intern - Engineering Leadership | Melbourne, FL | 2026-09-03 | eligibility:start_window |
| 3811 | A | Self Financial | Associate Software Engineer - UI | Austin, TX | 2026-09-03 | eligibility:start_window |
| 3406 | A | Trulioo | Junior Software Engineer | San Diego, CA | 2026-09-03 | eligibility:start_window |
| 3397 | A | Onto Innovation | Software Engineer 2 | Wilmington, MA | 2026-09-02 | eligibility:start_window |
| 3387 | A | ViaSat | Software Engineer - Automation | Carlsbad, CA | 2026-09-03 | eligibility:start_window |
| 3292 | A | Tebra | Software Engineer 1 - Back-End | Remote in USA | 2026-09-01 | eligibility:start_window |
| 3250 | A | Johns Hopkins APL | Software Developer - Modeling, Simulation | Laurel, MD | 2026-09-01 | eligibility:start_window |
| 3232 | A | Qualcomm | Sensors Software Engineer – Engineer or Senior | San Diego, CA | 2026-09-01 | eligibility:start_window |
| 3213 | A | DiDi Global | Software Engineer - Planning Selection Autonomy | San Jose, CA | 2026-09-01 | eligibility:start_window |
| 4549 | B | OnLogic | Firmware Engineering Co-op | Cary, NC | — | eligibility:opportunity_type |
| 4548 | B | OnLogic | Firmware Engineering Co-op | South Burlington, VT | — | eligibility:opportunity_type |
| 4528 | B | Johnson & Johnson MedTech | Software Engineering Co-Op, Summer 2027 | Cincinnati, OH | — | eligibility:opportunity_type |
| 4414 | B | Schneider Electric | Embedded Engineer Spring Co-Op | Andover, MA | — | eligibility:opportunity_type |
| 4400 | B | Collins Aerospace | Software Engineering Co-op (Winter/Spring 2027) | Cedar Rapids, IA | — | eligibility:opportunity_type |
| 4399 | B | Collins Aerospace | Software Engineering Co-op (Summer/Fall 2027) | Cedar Rapids, IA | — | eligibility:opportunity_type |
| 4332 | B | Skillz | Co-op, Software Engineer | Las Vegas, NV | — | eligibility:opportunity_type |
| 4318 | B | GE Vernova | Software Engineering Co-op - Summer 2027 | Rochester, NY | — | eligibility:opportunity_type |
| 4085 | B | Medpace | Junior Software Engineer | Denver, CO | — | eligibility:opportunity_type |
| 4073 | B | GE Aerospace | Engines Engineering Co-op – Computer/Software | Evendale, OH | — | eligibility:opportunity_type |
| 4059 | B | Leaf Health | Software Engineer | Austin, TX | — | eligibility:opportunity_type |
| 4022 | A | Caterpillar | Software Engineer | Peoria/Chicago, IL | 2026-09-07 | eligibility:opportunity_type |
| 3962 | A | Rivian | Software Engineer - Cloud & Software FinOps | Atlanta, GA | 2026-09-04 | eligibility:opportunity_type |
| 3314 | A | Nationwide | Software Engineer - Full Stack - Application | Columbus, OH | 2026-09-02 | eligibility:opportunity_type |
| 3844 | A | L3Harris Technologies | Software Engineer - Engineering Leadership Dev Program | Melbourne, FL | 2026-09-03 | eligibility:seniority |
| 3809 | A | Aptiv | Product Manager ADAS - Advanced Safety Software | Boston, MA | 2026-09-03 | eligibility:seniority |
| 3275 | A | L3Harris Technologies | Senior Associate - Software Engineering | Nashville, TN | 2026-09-01 | eligibility:seniority |
| 4213 | B | L3Harris Technologies | Engineering Leadership Development Program | Melbourne, FL | — | eligibility:seniority |
| 4523 | B | Intelliswift (LTTS) | Telecom - Software Tester 3 | Plano, TX | — | eligibility:role_family_excluded |
| 4447 | B | iFIT | QA Software Tester 1 | Logan, UT | — | eligibility:role_family_excluded |
| 4194 | B | Accenture Federal Services | Software System Tester / Business Analyst | Springfield, VA | — | eligibility:role_family_excluded |

The remaining ~338 window exclusions are `country` (non-US), `work_authorization` (clearance /
citizenship), or `role_family` (JD with no software signal). All are in `excluded_roles.csv`.

## 9. Failures — sources, resolvers, browser, rate-limit, credential

- **Resolution: 767 content failures + 12 transient (`http_transport`).** These rows stay `DISCOVERED`
  (attempt 1–2 of 3) and retry next run; only **2** reached `RESOLVE_FAILED`. From logs:
  - **86** `www.tesla.com` — Akamai anti-bot block (known tier-3; no evasion attempted).
  - **~40** JS-shell "structural" blocks — `careers.duolingo.com`, `app.careerpuck.com` (Lyft),
    multiple `*.oraclecloud.com` HCM pages, `careers-peraton.icims.com`, `equipmentshare.com`,
    `job-boards.eu.greenhouse.io`.
  - **2** Cloudflare JS-challenge.
  - remainder — generic `no_acceptable_content`: JS-heavy ATS leaf pages where neither plain HTTP nor
    the crawl4ai render produced >=400 chars of JD text with a JD keyword.
  - crawl4ai tier-2 backend ran but resolved **0** rows (every render failed the content-quality gate).
  - No HTTP 429/403 rate-limit failures logged; no credential failures in resolution. The >=2s-per-host
    throttle was honored throughout (why the run took 1h43m).
- **Scoring: FAILED (exit 1), nothing written to the DB.** `scripts.score_batch` on the 154-object
  fresh batch aborted at **chunk 8 of 26** (3 retries exhausted); nested `claude -p` returned:
  `You've hit your session limit · resets 4:40am (America/Los_Angeles)`. Because `score_batch`
  concatenates all chunks before importing once, the partial results (chunks 1–7) were discarded — no
  `*.scored.json`, `scripts.import_scores` never ran. **0 fresh rows scored.** All 164 qualifying roles
  are reported unscored (no fabricated scores). The scorer is installed and authenticated (a probe call
  succeeded); this was an account usage-limit cutoff mid-batch. Re-run after reset:
  ```
  <repo>/.venv/bin/python -m scripts.score_batch <fresh-batch>.json --db <repo>/data/jobs.db
  ```

## 10. Final `data/jobs.db` SHA-256
`f599c8c3c29ce914074c3d4574e3404be893357ee0f450f014ba03c60d759775`
(Changed from the backup hash `a9966f4a…` — delta is the ingestion run's writes only; scoring wrote
nothing. DB grew 9.57 MB → ~29 MB.)

Post-run DB status totals: `FILTERED_OUT 2435`, `RESOLVED 1164`, `DISCOVERED 777`,
`RESOLVE_FAILED 78`, `CLOSED 37`, `SCORED 37`, `SHORTLISTED 34`.

## 11. Change-safety confirmation (ingestion phase)
- **No source/config/prompt/test/doc file modified.** `find config src docs tests scripts` for
  `*.py`/`*.yaml`/`*.md` newer than run start → none. `config/eligibility.yaml`, `config/sources.yaml`,
  prompts, tests untouched (ingestion used the worktree's pristine committed copies).
- **No commit, no push during the ingestion/scoring phase.** HEAD stayed `af9418f`; reflog unchanged.
- **M8N working tree preserved byte-for-byte** — `git status --short` identical to the pre-run
  snapshot (6 modified + 11 untracked). Nothing stashed / reset / cleaned / reverted / checked out.
- Scratch ingestion worktree removed after the run. DB backup + digest + audit all in place.
- (Separately, after the report was delivered, this `review/2026-09-08-ingest/` folder was committed
  to `main` and pushed at the user's explicit instruction — that push contains only these review
  artifacts, no `config/`, no M8N changes, no DB/snapshots.)
