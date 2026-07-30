# Job Pipeline: Progress, Error History, Current Bottlenecks, and Tailoring Forecast

**Prepared:** 2026-07-16  
**Repository:** `job-pipeline`  
**Purpose:** Give a durable, evidence-based account of what has been built, why progress has
felt slower than expected, which failures are closed, which risks remain, and how long it is
likely to take before resume tailoring can begin.

## Scope note

This report deliberately excludes detailed analysis of the two small Calibration Contract v2
defects found in the 2026-07-16 acceptance review, per the user's request. They should still
be repaired before the first real v2 calibration round. Their estimated combined repair and
verification time is **30–90 minutes**. They are not responsible for the larger historical
delay described below.

## Executive summary

The project has made substantial progress. It is no longer a simple scraper: it is a tested,
stateful job-discovery and evaluation pipeline with deterministic ingestion, multi-tier JD
resolution, configurable eligibility, provenance-aware scoring files, audits, lifecycle
tracking, and a corrected human-calibration contract. The full automated suite currently has
**608 passing tests**.

The project is now in **Phase 2: scoring calibration**. Resume tailoring is **Phase 3/M8**
and remains intentionally locked. The remaining distance is not mainly another large coding
milestone. It is an evidence gate:

- complete at least two fresh v2 calibration rounds;
- label at least 20 eligibility-passed jobs after reading full JDs;
- obtain two consecutive complete rounds with zero threshold-crossing disagreements;
- re-anchor the provisional stress bands and then lock the threshold from evidence;
- increase ATS-quality shortlisted jobs from **3 to at least 5**.

The shortest credible path to starting M8 is **2–4 calendar days** if both 12-job rounds are
clean, the scorer runs reliably, and two additional ATS-quality jobs become shortlisted. A
more realistic planning range is **1–2 weeks**. The first trustworthy tailored resume is
likely **4–7 days away in the best case** and **2–3 weeks away realistically**, because M8
still begins with a profile loader and an interactive master-profile construction session.

The largest historical delays came from five recurring causes:

1. contracts were discovered or corrected after implementation had already begun;
2. unit tests passed while production-scale behavior still failed;
3. external model/browser/website behavior was less reliable than deterministic code;
4. stateful operations wrote or interpreted state before their true commit boundary;
5. long sessions and model limits fragmented context and caused unreliable handoffs.

## Current factual state

### Repository and phases

- Phase 1 ingestion/filtering/self-healing: complete.
- M9D-0 discovery correctness baseline: complete.
- M6.10 resolution-runtime hardening: complete.
- M6.11 configurable eligibility policy: complete, including live migration and smoke.
- Calibration Contract v2: implemented; no real v2 calibration round completed yet.
- Phase 2 scoring calibration: in progress.
- Phase 3/M8 tailoring: locked and not implemented.
- M9D-1 and later hybrid-discovery milestones: designed but not implemented.

### Live database snapshot

| Status | Rows |
|---|---:|
| DISCOVERED | 262 |
| FILTERED_OUT | 557 |
| RESOLVED | 461 |
| RESOLVE_FAILED | 74 |
| SCORED | 17 |
| SHORTLISTED | 15 |

Shortlist quality:

| Shortlist category | Rows |
|---|---:|
| ATS-quality | 3 |
| Aggregator-quality | 12 |
| ATS-quality required to unlock M8 | 5 |
| Current ATS-quality gap | 2 |

### Verification state

- Focused Calibration Contract v2 tests: 180 passing.
- Full repository suite: 608 passing.
- M6.11 live eligibility transition: 488 reviewed and applied transactionally after backup.
- M6.11 post-apply preview: zero remaining actionable transitions.
- Historical calibration worksheet preserved as interest-only evidence.

## Progress made so far

### 1. Repository, data model, and deterministic discovery

M0–M3 established the Python project, SQLite state machine, normalized/deduplicated job
records, three GitHub tracker adapters, and the manual inbox. Discovery has source isolation,
snapshots, checkpointing, and per-source visibility rather than being an unobservable fetch
script.

The current production discovery set is still narrower than the desired end state—Vansh,
Simplify, Jobright, and manual inbox—but the target hybrid deterministic/agentic architecture
is now designed under M9D. M9D-0 fixed the correctness boundary before source breadth is
expanded.

### 2. Resolution and job-description quality

M2 and M6.x built structured Greenhouse, Lever, Ashby, Workday, Amazon, wrapper, Jobright,
generic, and Crawl4AI-backed resolution paths. The pipeline distinguishes ATS-quality text
from aggregator summaries, stores the underlying ATS URL when found, cleans aggregator
chrome, and surfaces unresolved/manual cases.

M6.10 later hardened this layer for real backlog processing by adding typed outcomes,
bounded resolution, run-scoped browser reuse, a browser circuit breaker, static-first
Jobright handling, correct transient/content failure accounting, and reliable aborted-run
finalization.

### 3. Deduplication, freshness, and lifecycle correctness

The pipeline now combines exact content hashes, exact company/title evidence, and fuzzy
Jaccard similarity at export time. It tracks last-seen timestamps, reposts, stale listings,
closures, and logic versions. Repeated identical processing is expected to be idempotent,
and audits check the state machine and duplicate leakage.

### 4. Audit and self-healing coverage

M7 added 14 audit invariants covering source liveness, resolution health, content purity,
schema contracts, prefilter leakage, idempotency support, state legality, resolver-version
staleness, referential sanity, LLM traces, prompt isolation, and score integrity. Audit
results flow into the digest and produce structured evidence rather than silent degradation.

### 5. Scoring contract and stability controls

The scoring wrapper owns file I/O and treats the model as a text-in/text-out function with
no filesystem authority. It splits batches into chunks of six, performs k=3 independent
scores, aggregates by median and majority vote, validates the returned schema, records LLM
traces, and imports scores transactionally.

Measured run-to-run variance fell from mean absolute score movement 0.67 to 0.20 after
self-consistency was introduced. Threshold-crossing flips fell from 2/30 to 1/30 in the
measured reruns, and base-variant flips fell from one to zero.

### 6. Configurable eligibility

M6.11 replaced the earlier small regex filter with a country-first, two-stage, fully
configurable policy. It now handles country, role type, start windows, role family,
seniority, and work authorization. The active requirements are United States roles, 2027
full-time starts, Spring/January–May 2027 internships, explicit no-sponsorship/citizenship
rejection, and sponsorship-silence acceptance.

The live migration previewed and applied 488 transitions with a verified backup, preserved
terminal/scoring history where required, restored eligible legacy rows for fresh scoring,
and ended with a zero-action preview.

### 7. Corrected calibration evidence contract

The original worksheet captured metadata interest while the scorer saw full JD text. The new
contract separates:

- `interest_call`: metadata-only interest;
- `fit_call`: final JD-informed decision, recorded before seeing model scores.

APPLY means “would submit,” MAYBE means “worth human review,” and both are positive for the
7+ shortlist. New rounds default to 12 canonical jobs, preserve provenance hashes, reveal
complete JDs only after interest labels are locked, and compare the model only against
`fit_call`.

This correction prevents the system from “learning” from disagreements that were actually
caused by the human and model seeing different information.

## Detailed error history

### A. Silent or unsafe LLM scoring execution

#### What happened

The initial nested `claude -p` scorer produced archived chunk input but sometimes no scored
file. The first response was to grant `acceptEdits` authority so the nested model could read
and write files. That removed the immediate permission block but created a more serious
trust-boundary defect: the model now had filesystem authority.

#### Root cause

The architecture had assigned file I/O to the model instead of to deterministic wrapper
code. A headless model call and an interactive coding agent were treated as though they had
the same operating environment.

#### Resolution

The wrapper now embeds input text, reads stdout, validates it, writes files itself, and gives
the nested scorer no tools or permission flags. This is resolved.

#### Time impact

The initial “fix” had to be undone and the whole boundary redesigned. This cost more than a
small bug because prompt, wrapper, trace, schema, and test assumptions all changed together.

### B. Model non-determinism and unresolved nested-CLI flakiness

#### What happened

Identical scoring inputs produced materially different results. Before mitigation, two of
30 jobs crossed the shortlist boundary between consecutive runs, and one job changed resume
variant. After k=3 self-consistency, variance improved substantially but did not disappear.

Separate from model variance, repeated nested CLI calls failed in several ways:

- malformed JSON with trailing commas;
- exit code 1 with empty stderr;
- failures moving between different chunks;
- all three retry attempts failing silently on the same invocation.

#### Root cause

Score variation is inherent model sampling variance. The silent exit-1 behavior was never
root-caused. Evidence suggests recursive/high-volume `claude -p` calls, throttling, session
state, or CLI infrastructure rather than a specific JD.

#### Resolution status

- Variance: mitigated with k=3 median/majority aggregation.
- Trailing comma: narrowly repaired after strict JSON parsing fails.
- Transient invocation failure: retried with exponential backoff and jitter.
- Silent repeated exit 1: **still unresolved** and previously deprioritized because repeated
  live rescoring consumed time and tokens.

#### Current impact

This is the most important unresolved engineering risk to the Phase 2 schedule. Each
12-job round requires six model invocations at k=3. A failure late in a run can delay the
round and may require careful retry outside the coding-agent session.

#### Correct response if it recurs

Run the exact generated prompt through `claude -p` manually outside an already-running
Claude Code agent, capture real stdout/stderr and exit status, and preserve the failing
prompt/trace. Do not immediately add broader JSON repair or unlimited retries.

### C. Provisional synthetic scoring bands were mistaken for a regression

#### What happened

The synthetic scoring stress suite reported only 6/10 cases inside expected bands. This
looked like a scoring regression.

#### Root cause

The expected bands had never been calibrated against real user judgments, and the suite had
never successfully produced a historical baseline. The project was comparing output against
implementer guesses and treating them as truth.

#### Resolution

Bands were marked PROVISIONAL and removed as a tailoring unlock signal until real v2 fit
labels exist.

#### Lesson

An automated test can be mechanically correct and still measure an invalid target. Expected
values need provenance just as much as production data.

### D. Metadata interest was compared against full-JD scoring

#### What happened

The first real calibration report showed 15 disagreements out of 30. Nine apparent model
errors were actually jobs where the metadata looked attractive but the JD contained a real
blocker: citizenship/clearance, wrong specialty, excessive experience, QA/frontend focus,
or another requirement hidden from the digest.

#### Root cause

The human label and model score answered different questions. The worksheet deliberately hid
the JD, while the scorer read it. The original protocol did not represent this difference.

#### Resolution

Calibration Contract v2 now separates interest and fit calls and preserves the old sheet as
interest-only history.

#### Time impact

The original 30 labels cannot satisfy the new fit-label evidence gate. They were useful for
discovering the semantic problem, but the project must now collect at least 20 fresh labels.
This is a deliberate rework cost required for trustworthy calibration.

### E. False project-state beliefs and documentation drift

#### What happened

A prior handoff claimed Phase 2 was complete and that an M8 master-profile loader existed.
Repository inspection showed neither was true. No real scored output had existed before
2026-07-14, no profile loader existed, and `docs/ROADMAP.md` itself was missing despite being
referenced by other documents.

#### Root cause

Session summaries and model memory were treated as evidence without checking commits,
artifacts, tests, and live database state.

#### Resolution

`docs/ROADMAP.md` was recreated as the phase source of truth. Later milestones use explicit
specs, detailed implementation plans, scoped commits, live gates, and repository
verification before completion claims.

#### Current impact

This is mostly resolved procedurally, but every cross-model handoff still carries a context-
loss risk. The project now spends more time writing plans and evidence because earlier
unverified summaries caused expensive detours. That overhead is justified, but it is real.

### F. Tracker snapshots advanced before database durability

#### What happened

Tracker snapshots marked hundreds of jobs as seen before database insertion was guaranteed.
One source appeared silent for multiple runs, and roughly 608 real postings were absent from
the database even though the snapshot said they had already been processed.

#### Root cause

Discovery mixed pure comparison with side-effecting checkpoint writes. Debugging calls,
limited runs, or crashes could advance external state before the database commit boundary.

#### Resolution

M9D-0 introduced prepared checkpoints. Adapters return jobs plus a pending checkpoint;
database insertion happens first; an atomic checkpoint commit happens only afterward.
Limited runs preserve deferred keys.

#### Lesson

Idempotency is not just duplicate protection. Every external progress marker must advance
after, never before, the durable state it represents.

### G. Reopen logic interpreted unknown timestamps as old enough

#### What happened

Previously failed rows with `last_seen_at = NULL` were reopened days after failure despite a
45-day cooldown. Their failure history was cleared and they re-entered the discovery queue.

#### Root cause

A generic time helper interpreted missing timestamps as “old.” That behavior was valid for
one stale-listing decision but invalid for reopening terminal/failed rows after a schema
migration left historical timestamps NULL.

#### Resolution

Reopen now requires a known `last_seen_at`. New sightings backfill the timestamp for future
decisions.

#### Lesson

NULL is not one universal semantic value. “Unknown,” “never,” and “old” require explicit
policy at each call site, especially after additive migrations.

### H. Resolution backlog runs crashed on production-only exception classes

#### What happened

A 1,047-row backlog-clear run first crashed on a `requests.ConnectionError`, then crashed
again on a Playwright browser-launch timeout. The first patch caught only request exceptions,
so it did not protect the browser path. Interrupted run rows were left unfinished.

#### Root cause

The resolution boundary did not have a typed outcome contract or universal per-row isolation.
Code had been tested resolver-by-resolver, but not under long mixed HTTP/browser workloads.
Different infrastructure layers raised unrelated exception classes.

#### Resolution

Immediate isolation was broadened, then M6.10 replaced the ad hoc behavior with typed content,
transient, and internal outcomes; bounded work; browser reuse/circuit breaking; correct retry
budgets; and `finally`-based run finalization with partial counters.

#### Time impact

This caused multiple long live runs, crashes after partial progress, investigation of
orphaned runs, two rounds of exception fixes, and eventually a dedicated stabilization
milestone before calibration could safely continue.

### I. Browser lifecycle was too expensive and fragile

#### What happened

The tier-2 path launched a fresh Crawl4AI/Chromium lifecycle per URL. Browser launch itself
could hang for three minutes, and repeated launches made large backlog resolution slow and
failure-prone.

#### Root cause

The implementation was locally correct for one URL but operationally wrong for a batch. The
resource lifecycle was scoped to a call rather than a run.

#### Resolution

M6.10 introduced a run-scoped browser client, circuit breaking, and static-first Jobright
resolution to avoid unnecessary browser launches.

#### Lesson

Acceptance tests for resource-heavy components need batch-scale lifecycle assertions, not
only mocked single-call behavior.

### J. Test isolation leaked into real data directories

#### What happened

Some tests wrote to or read from real `data/digests/` and `data/batch/` paths. Audit failures
could therefore depend on local production artifacts, and tests risked overwriting user data.

#### Root cause

Default-path behavior was exercised without injecting `tmp_path`. Tests appeared hermetic in
a clean environment but were stateful in the real workspace.

#### Resolution

Affected tests were changed to use temporary directories and explicit paths.

#### Lesson

“No network” is not sufficient isolation. Tests must also avoid production filesystem and
database defaults.

### K. Eligibility was originally too small, late, and partly hard-coded

#### What happened

The old prefilter was a handful of regexes in `filters.yaml`. It could let `Remote - Canada`
pass because of the word “remote,” did not model opportunity types/start windows, and treated
explicit no-sponsorship text as a flag rather than an eligibility rejection. It also ran
after JD resolution, spending network/browser work on obvious non-US roles.

#### Root cause

Initial implementation optimized for a small deterministic MVP, while the actual search
requirements—country, 2027 timing, Spring internships, sponsorship semantics, seniority, and
role family—were not captured as a typed policy contract early enough.

#### Resolution

M6.11 implemented a validated, country-first, two-stage configurable policy and migrated the
live DB under explicit preview/backup/apply gates.

#### Time impact

The late correction required a full design, plan, code migration, audit migration, 488-row
live reclassification, and new calibration baseline. It was necessary, but it delayed the
next scoring round.

### L. Discovery breadth was mistaken for a finished architecture

#### What happened

The deterministic discovery layer had only a few GitHub trackers plus inbox, despite the
project's broader goal of finding roles across many sources. The implemented MVP was at risk
of being treated as the final architecture.

#### Root cause

The boundary between “current implemented source set” and “target broad hybrid discovery”
was not made explicit early enough. Tool candidates such as Crawl4AI, Crawlee, and Apify were
discussed without a controlled promotion/data-plane boundary.

#### Resolution status

The hybrid design is approved: deterministic sources, bounded crawlers, and an agentic scout
feed staged candidates through deterministic validation and promotion. Only M9D-0 is built;
M9D-1 onward remains deferred so discovery expansion does not derail calibration again.

#### Current impact

Source breadth is still a product limitation, but it is not the immediate M8 gate. Starting
M9D-1 now would likely delay tailoring further. The disciplined choice is to finish Phase 2
first unless current sources cannot produce the two missing ATS-quality shortlists.

### M. Agent limits and cross-session handoffs repeatedly broke momentum

#### What happened

Several implementation sessions ended mid-task because the model hit session/token limits.
Work then had to be reconstructed from terminal output, partial commits, background process
logs, and new prompts. At least one background run completed while another milestone was in
progress; other runs crashed without a final handoff.

#### Root cause

Milestones were sometimes too large for one model session, and important context lived in
chat rather than committed specs/reports. Different agents also made different assumptions
about “done.”

#### Resolution

Recent work uses one milestone at a time, approved design specs, detailed executable plans,
small scoped commits, explicit live gates, and durable error reports.

#### Current impact

The process is safer but planning/handoff overhead is now visible. The fastest remaining path
is to avoid switching agents during a calibration round and keep the human labels, scorer
output, and report in one continuous workflow.

## Current bottlenecks slowing progress

### 1. Human calibration evidence does not exist yet under the corrected contract

The code for v2 exists, but zero fresh v2 rounds are complete. At least 20 fit labels and two
rounds are mandatory. This cannot be replaced by more unit tests or by reusing the old 30
metadata-only labels.

This is now the largest unavoidable bottleneck. Reading 12 complete JDs carefully is human
work, and rushing it would damage the ground truth the system is intended to learn.

### 2. The exit gate requires consecutive clean rounds, not merely two rounds

If either round contains a threshold-crossing disagreement, the cause must be classified:
eligibility leak, profile-summary gap, prompt-anchor gap, model variance, or legitimate
borderline ambiguity. After an approved correction, another fresh round is needed. Therefore
two rounds are the minimum, not a guarantee.

### 3. Scoring execution is still an external reliability risk

The unresolved silent nested-CLI failure can interrupt real rounds even though all repository
tests pass. Retries reduce the probability but do not prove reliability. This adds scheduling
uncertainty and can waste model tokens.

### 4. ATS-quality shortlist count is below the tailoring gate

There are 15 shortlisted jobs but only 3 ATS-quality descriptions. M8 requires 5. The 12
aggregator-quality shortlists may be useful leads but cannot safely drive literal-keyword
resume tailoring.

The next two rounds may naturally supply two ATS-quality shortlists. If not, the fastest
fallback is to obtain the original employer ATS URLs/JDs for strong existing aggregator
shortlists through the permitted manual inbox/resolution path—not to weaken the quality gate.

### 5. Stress bands and threshold are intentionally not yet authoritative

The threshold remains 7, but it cannot be declared calibrated until real fit-call evidence
supports it. The stress suite remains provisional. Re-anchoring before collecting v2 labels
would repeat the earlier mistake of treating implementer expectations as ground truth.

### 6. M8 itself has not started

Even after the gate opens, there is no master-profile loader. The first M8 work is profile
loading/validation, followed by an interactive master-profile construction session. Actual
per-JD tailoring comes after those foundations.

### 7. Aggregator-heavy historical data limits immediate tailoring value

The current shortlist is 80% aggregator-quality (12 of 15). This reflects the historical
source/resolution mix. Scoring can tolerate cleaned aggregator summaries; tailoring cannot,
because it needs the employer's literal requirements and phrasing. This quality asymmetry is
why a numerically large shortlist does not yet mean the tailoring gate is satisfied.

## Time estimate

These estimates assume focused work, no new milestone, and no M9D expansion before Phase 2
closes.

### Work immediately before the first round

| Work | Active time |
|---|---:|
| Repair and verify the two excluded small defects | 0.5–1.5 hours |
| Export/select fresh eligible batch and generate round 1 interest packet | 10–20 minutes |

### Per 12-job calibration round

| Work | Active time |
|---|---:|
| Metadata-only interest labels | 10–25 minutes |
| Read 12 complete JDs and record careful fit calls | 1.5–3 hours |
| k=3 scoring: six model calls, if healthy | 15–45 minutes |
| Validate/report/classify disagreements | 20–60 minutes |
| **Total per clean round** | **2.25–4.25 hours** |

### Minimum Phase 2 closeout

| Work | Best case | Realistic |
|---|---:|---:|
| Two complete rounds | 4.5–6 hours | 6–9 hours |
| Re-anchor stress bands and confirm threshold | 1–2 hours | 2–4 hours |
| Close ATS-quality gap | included if rounds produce two | 0.5–2 working days |
| Phase 2 evidence/docs verification | 0.5–1 hour | 1–2 hours |

### Calendar forecast

| Outcome | Best case | Realistic | Adverse case |
|---|---:|---:|---:|
| Start M8 implementation | 2–4 days | 1–2 weeks | 2–4 weeks |
| Complete profile loader + master-profile session | 3–5 days | 1.5–2.5 weeks | 3–5 weeks |
| Produce first trustworthy tailored resume | 4–7 days | 2–3 weeks | 4–6 weeks |

The adverse case assumes recurring scorer failures, one or more disagreement rounds, and no
natural improvement in ATS-quality shortlist count.

### What can shorten the schedule

- Complete both 12-job human reviews in focused sessions rather than spreading individual
  labels across many days.
- Run the scorer standalone rather than recursively inside another long agent session.
- Preserve every round artifact and trace; do not restart successful chunks unnecessarily.
- Choose no parallel milestone until the Phase 2 gate is evaluated.
- For strong aggregator shortlists, locate original ATS postings through the existing manual
  inbox rather than lowering the ATS-quality requirement.

### What will lengthen the schedule

- Starting M9D-1, Crawlee, Apify, or broad source work before calibration closes.
- Editing threshold/prompt/profile after looking at only one or two anecdotes.
- Reusing metadata-only labels as fit ground truth.
- Re-running full 30-job or larger scoring batches when 12-job v2 rounds are sufficient.
- Continuing a flaky nested scorer without capturing the exact standalone failure.
- Accepting aggregator text for tailoring merely to satisfy the five-job count.

## Recommended next sequence

1. Repair and verify the two small excluded defects; keep the fix narrowly scoped.
2. Freeze Calibration Contract v2 code for the duration of round 1.
3. Export current eligibility-passed jobs and start a 12-job v2 round.
4. Complete all interest calls before revealing any JD.
5. Reveal complete JDs and complete all fit calls before scoring.
6. Score the immutable round batch standalone and preserve traces/output.
7. Run the report and classify every disagreement without hand-editing DB scores.
8. Repeat with round 2.
9. If both consecutive rounds are clean, re-anchor bands and lock the threshold from the
   combined evidence; otherwise make only the approved input correction and continue rounds.
10. Confirm or close the ATS-quality shortlist gap.
11. Mark Phase 2 complete and plan M8 item 1 only.
12. Build the profile loader, then conduct the master-profile construction session before
    generating the first tailored resume.

## Bottom line

The project is not stuck in the sense of lacking an architecture or working code. Most of
the difficult infrastructure is already built, and the automated suite is strong. It has
felt stuck because each live milestone exposed a deeper contract or operational boundary
that unit tests alone could not reveal.

The remaining pre-tailoring work is narrower but partly irreducible: the user must supply
fresh JD-informed decisions, the scorer must survive real execution, and two more ATS-quality
shortlists must exist. If focus stays on those gates, M8 can plausibly begin within one to
two weeks. If discovery expansion or another architectural correction is started first,
tailoring will move further out even if that new work is valuable.
