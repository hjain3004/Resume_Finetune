# UPGRADE_PLAN.md — M9–M12: Discovery, Latency & Research-Driven Upgrades

Scope: post-M7 upgrades. M9 (moved here from PHASE2_KICKOFF.md, which now contains only
M6.x + the calibration protocol) plus milestones derived from the July 2026
state-of-the-art benchmark research. Every external recommendation was filtered against
this project's constraints (Pro-subscription cost model, etiquette rules, dependency
discipline, solo-maintainer budget); §5 records what was evaluated and REJECTED so
decisions aren't re-litigated.

Sequencing: M7 → M9 items 1–2 and/or one approved M9D sub-milestone per session → Phase 2
calibration → M9 item 3 (hot lane needs a calibrated threshold) → M10 (MUST precede M8's
render build) → M8 → M11 → M12 by appetite. Discovery work does not bypass M8's gate.

---

## M9 — Latency package (be early without being impolite)

Goal: cut posting→application latency from ~24–48h to same-day. Evidence: recruiter
review-in-waves behavior and widely repeated (directionally robust, softly sourced)
early-application statistics; the dominant latency term is our own daily cadence, not
source choice.

1. **Cadence.** Reschedule to hourly during business hours (config: 07:00–19:00 local,
   Mon–Fri; one nightly full run on weekends). Safe because of the I7 idempotency
   guarantee — run the idempotency check immediately after the schedule change. Scoring
   runs each cycle only if new RESOLVED rows exist. The daily digest remains once per
   day; intermediate cycles log to runs as usual.
2. **Watchlist ATS adapter (`discover/watchlist_ats.py`).** New config
   `config/watchlist.yaml`: list of {company, ats: greenhouse|lever|ashby, board_token}.
   Each cycle, fetch each company's full live board via the existing tier-1 API clients
   (one GET per company per cycle; polite per-host limits apply), normalize to
   DiscoveredJob; dedup/snapshotting absorbs repeats. Rows are jd_quality='ats' by
   construction — this adapter also feeds the Phase-3 gate. Seeding:
   `scripts/seed_watchlist.py` proposes entries (companies with any historical
   fit_score ≥ 7 whose resolver was greenhouse/lever/ashby) for user approval; manual
   additions welcome. Workday boards deferred unless Workday-only companies exceed ~20%
   of approved entries.
3. **Hot lane.** After scoring in any cycle: rows (discovered < 24h) AND (fit_score ≥
   shortlist_threshold) AND not yet notified → one push notification (ntfy.sh topic or
   SMTP via stdlib; no new dependencies) with company, title, score, link. Mark notified
   in flags (at-most-once). Digest gains a "Hot today" section. GATED on calibration
   completion — an uncalibrated hot lane pushes noise.

Acceptance: idempotency check passes under hourly cadence (second consecutive cycle
inserts 0); watchlist fixture test (one board JSON → normalized rows) + live smoke on 5
approved companies; hot-lane at-most-once verified over two cycles on the same fixture
row (exactly one notification); per-source digest line shows watchlist counts (I1 covers
liveness automatically).

## M9D — Hybrid Discovery v2 (M9D-0 complete; M9D-1..5 not implemented)

Goal: replace the three-correlated-tracker ceiling with multiple independent source classes
and agent-assisted source reconnaissance while preserving deterministic production writes.
The authoritative design is
`docs/superpowers/specs/2026-07-14-hybrid-discovery-design.md`.

Sub-milestones, each requiring its own implementation plan and session:

1. **M9D-0 correctness baseline — COMPLETE 2026-07-14:** tracker checkpoints cannot advance
   past durable DB acceptance; `--limit` preserves deferred rows through `pending_keys`;
   fetch/checkpoint failures are structured in run notes/digest warnings; backlog and
   per-source yield baselines are recorded read-only.
2. **M9D-1 provenance foundation:** source registry, staged candidates, source runs, and
   many-to-one job observations through an idempotent migration.
3. **M9D-2 direct-source breadth:** approved ATS watchlists and authorized alert emails.
4. **M9D-3 crawler bake-off:** test bounded Crawl4AI deep crawl against Crawlee Python on
   fixtures and an approved live sample. Crawlee is added only if it materially wins on
   queues/routing/recovery; the JavaScript Crawlee package is not the default.
5. **M9D-4 agentic scout shadow:** versioned proposal contract, budgets, provenance,
   prompt-injection isolation, deterministic verifier, and zero canonical job writes.
6. **M9D-5 controlled external execution:** optional allowlisted/version-pinned Apify Actor
   runs and explicit user source promotion, only when shadow metrics justify them.

Cross-cutting acceptance: tests never touch the network; all candidate imports are
reject-on-any-error; replay is idempotent; crawl policy is enforced for every transport;
source value is reported as marginal unique jobs, freshness, precision, ATS-quality rate,
duplicates, failures, cost, and downstream application yield.

## M10 — Rendering decision gate + parseability CI  (BLOCKS M8's render step)

Research finding: resume-as-code toolchains (RenderCV: YAML→Typst→PDF, schema-validated,
diffable) formalize what our master-profile design already implies; and free parseability
checkers (OpenResume parser; open-source ATS-screener simulators) can regression-test
rendered PDFs against the parsing failures that actually kill applications.

1. **Render bake-off (one session, user in the loop).** Render the user's current resume
   content two ways: (a) existing LaTeX template; (b) RenderCV from a hand-mapped YAML.
   Compare: visual acceptability to the user (hard gate — the user's template is
   interview-tested), parse fidelity (item 2's checker), and pipeline fit (bullet IDs as
   YAML keys, diffability). Decision recorded in DECISIONS.md. If LaTeX wins on visuals,
   we keep LaTeX and take only item 2 — that is a fully acceptable outcome; RenderCV is
   a convenience, not a quality gate.
2. **Parseability gate (adopt regardless of bake-off outcome).** Add to the Phase-3
   pipeline as lint rule **L7**: every rendered PDF is run through an open-source resume
   parser (OpenResume's parser or an offline ATS-screener equivalent — evaluate and pin
   ONE, vendored or version-locked); assert that name/contact, section boundaries, every
   bullet, and every skills term survive parsing. A term that passes L3 keyword bounds
   but fails L7 extraction is a delivery failure invisible to all other gates.
3. **Master-profile → render mapping.** Whichever renderer wins, the render step consumes
   master_profile-selected content mechanically (ids → rendered bullets) so G0
   traceability survives through to the PDF.

Acceptance: bake-off artifacts + decision logged; L7 gate with a deliberately corrupted
fixture PDF (two-column or table-based) failing and the real template passing; render
mapping round-trips one golden application with zero manual edits.

## M11 — Guardrail hooks + funnel instrumentation

1. **PROTECTED-file enforcement via Claude Code hooks.** A PreToolUse hook in the repo's
   Claude Code settings blocks Edit/Write operations on PROTECTED paths (SELF_HEALING §4
   list: schema/state-machine module, prompt files post-calibration, CLAUDE.md,
   SELF_HEALING.md, audit.yaml, dedup normalization module) unless an explicit
   override marker file exists (`.protected_override`, created manually by the user for
   one session and deleted by the hook after use). This converts change-control from a
   documented rule into an in-band mechanical barrier — the same judgment→check
   conversion the audit layer applies to data. Document in CLAUDE.md.
2. **Funnel metrics.** Weekly digest section: counts and week-over-week deltas per stage
   (discovered → resolved → passed prefilter → scored → shortlisted → tailored → applied
   → response → interview), computed from the jobs table + outcomes journal. Research
   context: nobody in the public field instruments the funnel; we already store every
   stage transition, so this is a query and a template, and it is the measurement that
   eventually says which upgrades move interviews rather than metrics.

Acceptance: hook demonstrably blocks a protected edit and permits it with the override
marker (recorded demo in DECISIONS.md); funnel section renders from a seeded DB with
known counts.

## M12 — Deferred bucket (adopt only on trigger)

- **Aggregator APIs (Adzuna / Arbeitnow / JSearch).** Deferred from the first deterministic
  build, but eligible for M9D shadow evaluation. Honest fit assessment:
  USAJobs is federal (citizenship-gated — near-zero value for this candidate); Arbeitnow
  is EU-weighted; Adzuna's free tier (~250 calls/month) adds little over tracker + ATS +
  watchlist coverage for US new-grad SWE. Trigger: calibration reveals whole segments of
  wanted jobs the current sources never surface. Adoption still requires measured marginal
  novelty and acceptable cost rather than source count alone.
- **Cross-model golden-set judge.** Monoculture research argues for a second judge model;
  a genuinely independent second provider means new accounts/costs. Cheap partial hedge
  when D2 runs: execute the critic pass with a different Claude model tier on the golden
  set only, and diff verdicts (weaker hedge — same family — but free and catches
  tier-specific drift). Trigger: any D2 drift FAIL, or calibration disagreements that
  cluster on rubric dimensions rather than segments.
- **Eval-harness migration (promptfoo / DeepEval / Langfuse).** Our bespoke harness
  (stress suite, D2, traces, I12 scan) already covers the report's checklist for keeping
  a custom harness. Triggers to revisit: the golden set exceeds ~50 applications and D2
  runtime/maintenance hurts; or we need systematic injection red-teaming beyond the I12
  scan. Note: promptfoo's ownership changed (acquired 2026) — re-verify governance
  before adopting.
- **Claude Code Routines / cloud scheduling.** Monitor. Current preview run caps
  (~15/day) are below M9's hourly cadence. Trigger: caps lift above ~15 runs/day AND the
  user wants off local cron.

## §5 — Evaluated and REJECTED (do not re-litigate without new evidence)

- **JobSpy / any LinkedIn or Indeed scraping.** Rejected on etiquette rules (CLAUDE.md
  §6) and ToS asymmetry; the benchmark's own findings (AIHawk archived after platform
  detection and quality collapse; ban risk real even if thinly documented) reinforce the
  standing decision. LinkedIn remains manual inbox + alert emails.
- **Dynamic unattended Apify Actor selection.** Rejected. Interactive MCP research is
  permitted, and a recurring Actor may be approved under M9D only when its ID/build is pinned,
  its permissions and budget are bounded, and its output enters deterministic staging.
- **Instructor / SDK structured outputs.** Rejected for now: they wrap API clients, and
  our LLM boundary is the headless `claude -p` CLI under the Pro subscription. Switching
  to the API changes the cost model from flat-rate to per-token for zero quality gain —
  our deterministic whole-file validation with reject-on-any-error already provides the
  guarantee. Revisit only if the pipeline ever moves to the API for other reasons.
- **Wholesale auto-apply (browser agents submitting applications).** Rejected,
  permanently on current evidence: ATS submit APIs are recruiter-gated (documented HTTP
  401s), employer fraud-detection stacks (identity verification, application-source
  signals) are escalating, and the system's entire moat is authenticity. The pipeline
  ends at "tailored, verified, one click from submission by a human" — by design.
