# M8Q-0B Resume Evidence Research and Corpus Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acquire, validate, annotate, review, and atomically promote at least 50 distinct early-career Huntr outcome records plus public doctrine and additional success evidence.

**Architecture:** The M8Q-0A offline foundation remains the only promotion authority. Firecrawl CLI performs bounded, sequential, public-page acquisition into ignored research directories; a source-specific pure Huntr parser and a tested research-only operator turn raw captures into staged bundles; deterministic validation and duplicate analysis produce a review report whose SHA-256 must be explicitly approved by the user before canonical promotion.

**Tech Stack:** Python 3.11+, existing M8Q-0A package, standard library subprocess wrapper, Firecrawl CLI for user-supervised public research, Crawl4AI only as a single-page fallback, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-early-career-resume-evidence-bank-design.md`

**Prerequisite plan:** `docs/superpowers/plans/2026-08-29-m8q-0a-resume-evidence-foundation.md` must be implemented, committed, fully green, and documented as offline complete.

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, the spec, and the completed M8Q-0A closeout before any live call.
- One milestone only: complete M8Q-0B and stop before any tailoring, prompt, SkillOpt, or quality-gate integration.
- Do not start if M8Q-0A is incomplete, the focused foundation tests fail, or the canonical loader cannot validate a synthetic corpus.
- Preserve all unrelated dirty files. Never stage `data/`, `inbox/urls.txt`, `docs/sampleJD.md`, profile files, prompts, applications, or traces.
- Firecrawl calls are sequential on `huntr.co`; maintain at least 2 seconds between same-host requests.
- Never pass `--profile`, `--actions`, credentials, cookies, or an API key on the command line. The research operator passes only `--proxy basic`; authentication comes only from stored CLI credentials or the environment.
- Use `--redact-pii`, `--only-main-content`, and normal public scraping. No auth, CAPTCHA, paywall, stealth, enhanced proxy, or anti-bot escalation.
- Never scrape LinkedIn. Do not follow LinkedIn links discovered on resume pages.
- A Firecrawl 403, CAPTCHA, login wall, paywall, robots refusal, missing account information, or exhausted budget stops the affected batch.
- Raw captures, screenshots, manifests, checkpoints, candidate bundles, and review drafts remain under ignored `data/resume_research/`.
- Complete resumes and copyrighted page text are never committed. Canonical tracked files contain only the bounded fields authorized by the spec.
- No external model invocation. The executing agent may analyze staged public text, but all judgments remain explicit bundle fields and pass deterministic validation.
- No live tailoring, scoring, ingestion, Company Bank import, database mutation, or `git push`.
- Record `data/jobs.db` SHA-256 before the first live call and after final promotion; they must match.
- Run network activity only in explicit bounded tasks below. Tests remain offline and mock the Firecrawl subprocess boundary.

## Files Created or Modified

**Create and track:**

- `src/resume_evidence/huntr.py` — pure parser/classifier for captured Huntr markdown.
- `scripts/research_resume_evidence.py` — research-only allowlisted Firecrawl CLI orchestrator; no production imports.
- `tests/resume_evidence/test_huntr.py`
- `tests/test_research_resume_evidence_cli.py`
- `tests/fixtures/resume_evidence/huntr_mixed_minimal.md` — synthetic minimal page shape, not copied resume content.
- `config/resume_evidence_bank/current/` — only after exact report-hash approval and atomic import.

**Create but keep ignored:**

- `data/resume_research/preflight/`
- `data/resume_research/smoke/`
- `data/resume_research/raw/`
- `data/resume_research/inbox/`
- `data/resume_research/checkpoints/`
- `data/resume_research/reports/`
- `data/resume_research/source_manifest.yaml`
- `data/resume_research/manifest.yaml`

**Modify at closeout only:**

- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DECISIONS.md`

---

### Task 1: Preflight, Baseline, and Firecrawl Readiness

**Files:**

- No tracked changes.
- Create ignored evidence under `data/resume_research/preflight/`.

**Interfaces:**

- Consumes: completed M8Q-0A CLI/package.
- Produces: baseline Git/DB/test/credit evidence and a go/no-go decision.

- [ ] **Step 1: Confirm repository and foundation state**

Run:

```bash
git status --short
git log --oneline -12
.venv/bin/python -m pytest tests/resume_evidence tests/test_resume_evidence_cli.py tests/test_resume_evidence_integration.py -q
git check-ignore -v data/resume_research/preflight/example.txt
```

Expected: foundation tests pass; the research path is ignored; unrelated dirty files are listed and
recorded but not changed.

- [ ] **Step 2: Record immutable production baselines**

Record, without modifying, the outputs of:

```bash
shasum -a 256 data/jobs.db
sqlite3 data/jobs.db "PRAGMA integrity_check;"
git rev-parse HEAD
```

Write a 0600 `data/resume_research/preflight/baseline.json` using a small Python invocation or the
repository's normal atomic-write helper, not shell redirection. Include HEAD, DB SHA-256, integrity
result, existing dirty paths, UTC timestamp, and M8Q-0A focused test count.

- [ ] **Step 3: Verify Firecrawl without spending a scrape credit**

Run:

```bash
firecrawl --status
firecrawl credit-usage --json --pretty -o data/resume_research/preflight/credits-before.json
```

Expected: authenticated account information and a positive remaining-credit count. If status says
authenticated but cannot fetch account information, request network permission and retry once. If it
still cannot report usage, stop before scraping.

- [ ] **Step 4: Confirm hard exclusions**

Search the proposed source list for `linkedin.com`, URLs with query secrets, non-HTTPS schemes, or
hosts other than approved public sources. The initial smoke list must contain exactly the three URLs
in Task 2 and no redirect targets supplied manually.

- [ ] **Step 5: Report preflight and continue only on a clean gate**

Report the account status, remaining credits, DB hash, focused tests, and preserved dirty state. No
commit is created because only ignored evidence changed.

---

### Task 2: Three-Page Huntr Live Smoke

**Files:**

- Create ignored Firecrawl output in `data/resume_research/smoke/`.
- No tracked code changes in this task.

**Interfaces:**

- Produces three real page-shape observations that Task 3's pure parser must support.

Approved smoke URLs:

1. `https://huntr.co/resume-examples/real-resume-examples`
2. `https://huntr.co/resume-examples/software-engineer-resume-examples`
3. `https://huntr.co/resume-examples/machine-learning-engineer`

The first is the outcome-linked hub. The second deliberately mixes verified composites and
illustrative examples. The third is a negative-control legacy guide: it must not promote merely
because its example looks polished.

**Firecrawl CLI 1.19.29 correction (verified 2026-08-30):** `screenshot` in `--format` and
`--full-page-screenshot` are mutually exclusive screenshot requests. The first live attempt
correctly stopped before spending a credit when the CLI rejected that duplication. For the first
two pages, use `--format markdown,links` together with `--full-page-screenshot`; the flag adds the
single full-page screenshot output. Do not add `screenshot` back to the format list.

- [ ] **Step 1: Scrape the outcome hub as the install/live check**

Run exactly one normal scrape:

```bash
firecrawl scrape "https://huntr.co/resume-examples/real-resume-examples" --format markdown,links --only-main-content --redact-pii --full-page-screenshot --timing -o data/resume_research/smoke/real-resume-examples.json
```

Expected: exit 0, nonempty markdown, same-domain links, and screenshot metadata. Do not rerun if
content is complete.

- [ ] **Step 2: Inspect incrementally and check for leakage**

Use `wc`, `head`, `rg`, and `jq` to inspect headings, methodology labels, example labels, links, and
output shape without dumping the entire page into the terminal. Verify the output does not contain a
CLI key, cookies, or source query secrets. Private resume names/contact data may have been redacted;
do not copy any such material to tracked files.

- [ ] **Step 3: Respect the host delay, then scrape the mixed page**

After at least 2 seconds since the prior Huntr request:

```bash
firecrawl scrape "https://huntr.co/resume-examples/software-engineer-resume-examples" --format markdown,links --only-main-content --redact-pii --full-page-screenshot --timing -o data/resume_research/smoke/software-engineer-resume-examples.json
```

Expected: the capture preserves enough labeling to distinguish verified composites from
`Illustrative example` sections. If it does not, stop; do not guess from prose style.

- [ ] **Step 4: Respect the host delay, then scrape the negative control**

```bash
firecrawl scrape "https://huntr.co/resume-examples/machine-learning-engineer" --format markdown,links --only-main-content --redact-pii --timing -o data/resume_research/smoke/machine-learning-engineer.json
```

Expected: content is extractable, but no record can pass unless the page itself supplies qualifying
outcome evidence. A generic `Why this resume is great` heading is not outcome evidence.

- [ ] **Step 5: Record post-smoke usage and stop on anomalies**

Run:

```bash
firecrawl credit-usage --json --pretty -o data/resume_research/smoke/credits-after.json
```

Create `data/resume_research/smoke/smoke-report.json` with page statuses, byte counts, labels found,
same-domain link count, screenshot availability, pre/post usage, and candidate/negative-control
observations. If any invariant fails, stop M8Q-0B and repair the design/plan or offline parser in a
separate approved change before bulk acquisition.

---

### Task 3: Pure Huntr Page Parser and False-Positive Defense

**Files:**

- Create: `src/resume_evidence/huntr.py`
- Create: `tests/resume_evidence/test_huntr.py`
- Create: `tests/fixtures/resume_evidence/huntr_mixed_minimal.md`

**Interfaces:**

- Produces:
  - `HuntrExampleKind`: `VERIFIED_INDIVIDUAL | VERIFIED_COMPOSITE | ILLUSTRATIVE | UNKNOWN`
  - `HuntrExample(anchor, heading, target_level, kind, resume_markdown, outcome_quote, limitations)`
  - `parse_huntr_examples(markdown: str) -> tuple[HuntrExample, ...]`
  - `promotable_huntr_examples(examples) -> tuple[HuntrExample, ...]`

- [ ] **Step 1: Author a synthetic minimal fixture from observed structure**

The fixture must contain invented text only, but preserve the real heading/label relationships
observed in Task 2:

```markdown
## New Grad Software Engineer Resume Example
Verified composite
Built from resumes attached to jobs that reached the interview stage.
### Experience
Software Engineer | Example Company | 2025-06 - 2026-06
- Built a synthetic test service.

## Entry-Level Data Engineer Resume Example
Illustrative example
Built from job postings in this set.
### Experience
Data Engineering Intern | Example Lab | 2025-06 - 2025-08
- Built a synthetic test pipeline.
```

- [ ] **Step 2: Write parser RED tests**

```python
def test_verified_and_illustrative_examples_remain_distinct(mixed_markdown):
    examples = parse_huntr_examples(mixed_markdown)
    assert [item.kind for item in examples] == [
        HuntrExampleKind.VERIFIED_COMPOSITE,
        HuntrExampleKind.ILLUSTRATIVE,
    ]
    assert [item.heading for item in promotable_huntr_examples(examples)] == [
        "New Grad Software Engineer Resume Example"
    ]

def test_unknown_label_never_promotes(): ...
def test_why_this_resume_is_great_is_not_outcome_evidence(): ...
def test_duplicate_anchor_or_empty_resume_fails_closed(): ...
def test_outcome_quote_is_copied_from_the_source_not_synthesized(): ...
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/resume_evidence/test_huntr.py -q`

Expected: import failure for `src.resume_evidence.huntr`.

- [ ] **Step 4: Implement a single-pass heading parser**

Split only on explicit level-2 resume-example headings observed in the smoke. Determine kind only
from explicit labels/methodology statements in the same section. Never infer verification from
quantified bullets, polished writing, the words `great`, `success`, or a page title. Normalize
whitespace for comparisons but retain exact source substrings for evidence quotes.

If the real smoke structure cannot be represented by these rules, stop and update the design/plan;
do not add a broad heuristic during implementation.

- [ ] **Step 5: Replay the parser read-only over smoke captures**

Extract markdown from the Firecrawl JSON and run the parser without writing bundles. Confirm:

- outcome hub yields explicit outcome-linked candidates;
- mixed page keeps illustrative examples out;
- negative control yields zero promotable candidates unless explicit evidence is actually present.

- [ ] **Step 6: Run focused and foundation regressions**

Run:

```bash
.venv/bin/python -m pytest tests/resume_evidence/test_huntr.py -q
.venv/bin/python -m pytest tests/resume_evidence tests/test_resume_evidence_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/resume_evidence/huntr.py tests/resume_evidence/test_huntr.py tests/fixtures/resume_evidence/huntr_mixed_minimal.md
git commit -m "feat(m8q): classify Huntr outcome examples safely"
```

---

### Task 4: Bounded Research-Only Firecrawl Operator

**Files:**

- Create: `scripts/research_resume_evidence.py`
- Create: `tests/test_research_resume_evidence_cli.py`

**Interfaces:**

- Produces:
  - `load_source_manifest(path) -> tuple[ResearchTarget, ...]`
  - `validate_research_target(target) -> None`
  - `run_scrape_batch(targets, output_root, runner, sleeper, max_pages) -> BatchResult`
  - CLI `scrape-batch --manifest PATH --output DIR --max-pages N`
  - CLI `extract-huntr --raw DIR --inbox DIR --manifest PATH`
- The script may invoke the installed `firecrawl` executable through `subprocess.run`; it may not
  import application DB, tailoring, or production Firecrawl REST modules.

- [ ] **Step 1: Write operator RED tests with a fake runner**

Assert:

```python
def test_only_https_huntr_resume_example_targets_are_allowed(): ...
def test_linkedin_and_off_domain_targets_are_rejected_before_runner(): ...
def test_runner_uses_redact_pii_main_content_and_no_proxy_profile_or_actions(): ...
def test_same_host_calls_sleep_at_least_two_seconds(): ...
def test_nonzero_firecrawl_exit_stops_without_retry(): ...
def test_checkpoint_is_published_atomically_after_each_success(): ...
def test_rerun_skips_hash_matching_completed_targets(): ...
def test_max_pages_is_a_hard_bound(): ...
```

The fake runner returns small JSON strings; tests never invoke Firecrawl.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_research_resume_evidence_cli.py -q`

Expected: import failure for `scripts.research_resume_evidence`.

- [ ] **Step 3: Implement the allowlisted sequential runner**

Manifest format:

```yaml
schema_version: m8q.resume_research.v1
targets:
  - target_id: huntr_real_resume_examples
    url: https://huntr.co/resume-examples/real-resume-examples
    source_kind: huntr
    captured_sha256: null
```

Reject duplicate IDs/URLs, query strings, fragments, userinfo, non-HTTPS, and hosts other than
`huntr.co`/`www.huntr.co`. Construct an argv tuple, never a shell string:

```python
(
    "firecrawl", "scrape", target.url,
    "--format", "markdown,links",
    "--only-main-content", "--redact-pii", "--timing",
    "-o", str(output_path),
)
```

Use an injectable monotonic clock/sleeper and a 2.0-second minimum. One failed subprocess stops the
batch. Write checkpoint JSON through a sibling temporary file plus `os.replace`. A target is skipped
only when its expected output file exists and its exact byte SHA-256 equals non-null
`captured_sha256`; otherwise an existing file is a conflict, not permission to overwrite.

- [ ] **Step 4: Implement deterministic skeleton extraction**

`extract-huntr` reads captured JSON, calls `parse_huntr_examples`, and writes private
`skeleton.yaml` files only for explicit verified examples. Skeletons use the separate research-only
schema version `m8q.huntr_skeleton.v1` and contain source records, source hashes, exact outcome
quote, representation label, and target heading. They are never passed to the strict corpus parser.
Task 6 creates a separate complete `bundle.yaml` beside each skeleton after annotation.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_research_resume_evidence_cli.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/research_resume_evidence.py tests/test_research_resume_evidence_cli.py
git commit -m "feat(m8q): add bounded public resume research operator"
```

---

### Task 5: Discover and Acquire the Huntr Candidate Pool

**Files:**

- Create ignored: `data/resume_research/source_manifest.yaml`
- Create ignored: `data/resume_research/raw/huntr/`
- Create ignored: `data/resume_research/checkpoints/huntr.json`

**Interfaces:**

- Produces a bounded raw pool large enough to attempt 50 valid promoted Huntr records.

- [ ] **Step 1: Extract same-domain role links from the outcome hub**

Use the already captured hub `links` field. Accept only canonical HTTPS URLs with paths below
`/resume-examples/`. Prefer pages whose public title or hub callout explicitly says `real`,
`verified`, `interview data`, or equivalent. Exclude senior-only, management, non-technical,
generic template, and company-only SEO guides before fetching.

- [ ] **Step 2: Use Firecrawl Map only if the hub cannot supply enough candidate pages**

One bounded fallback is allowed:

```bash
firecrawl map "https://huntr.co/resume-examples/" --search "software engineering data machine learning entry level interview resume examples" --limit 100 --ignore-query-parameters --wait --json --pretty -o data/resume_research/raw/huntr/map.json
```

Filter the result locally through the same allowlist. Do not map again with broader terms merely to
inflate volume.

- [ ] **Step 3: Build and validate the private source manifest**

Use stable IDs derived from canonical slugs. Copy the already captured smoke JSON files into their
deterministic raw target paths, then include their exact byte hashes as `captured_sha256` so the
batch operator skips them. Review every URL before execution.

- [ ] **Step 4: Acquire in batches of at most five pages**

For each batch:

```bash
.venv/bin/python -m scripts.research_resume_evidence scrape-batch --manifest data/resume_research/source_manifest.yaml --output data/resume_research/raw/huntr --max-pages 5
firecrawl credit-usage --json --pretty -o data/resume_research/checkpoints/credits-after-batch.json
```

Generate a uniquely numbered credit file per batch in actual execution. Pause between batches,
report progress, inspect failures, and resume from the checkpoint. Do not run a single long command
that leaves the user without an update for more than 60 seconds.

- [ ] **Step 5: Extract verified candidate skeletons**

Run:

```bash
.venv/bin/python -m scripts.research_resume_evidence extract-huntr --raw data/resume_research/raw/huntr --inbox data/resume_research/inbox/outcomes --manifest data/resume_research/source_manifest.yaml
```

Count verified individual/composite skeletons, illustrative/unknown exclusions, unique source URLs,
and obvious duplicates. Continue bounded discovery only while eligible supply remains and credits
stay within the recorded user budget.

- [ ] **Step 6: Stop at adequate supply or honest exhaustion**

Target enough verified skeletons to yield 50 valid 0–3 YOE records after annotation. If the eligible
public Huntr supply is exhausted below 50, stop and report the exact shortfall; do not admit senior,
illustrative, non-technical, or outcome-ambiguous examples.

No commit occurs because this task changes ignored research data only.

---

### Task 6: Annotate and Validate at Least 50 Huntr Records

**Files:**

- Modify ignored candidate bundles under `data/resume_research/inbox/outcomes/`.
- Create ignored annotation reports/checkpoints.

**Interfaces:**

- Produces at least 50 strict `OutcomeCandidate` bundles that return `AdmissionStatus.ACCEPTED`.

- [ ] **Step 1: Annotate in batches of five records**

For each candidate, inspect the private capture and complete:

- role family and target role/level;
- graduation month;
- post-graduation professional intervals;
- internships/co-ops separately;
- stored professional month count from the deterministic calculator;
- experience confidence;
- recruiter-screen-or-later outcome tier and exact source quote;
- evidence confidence;
- representation and version-attribution labels;
- section order and feature tags;
- all eight editorial ratings with concise evidence-backed explanations;
- limitations.

Do not infer missing dates or outcomes. Ambiguous records remain staged and do not count.

- [ ] **Step 2: Validate each batch before continuing**

Run `validate-bundle` for every completed `bundle.yaml`. Fix only annotation errors supported by the
snapshot. Structural uncertainty becomes `NEEDS_REVIEW`/rejection rather than a guess. Whole-corpus
validation waits until Task 9 freezes the complete manifest.

- [ ] **Step 3: Review weak editorial records without deleting them**

A qualifying outcome record with editorial scores of 1 remains eligible if the outcome and
experience evidence pass. Record the weaknesses explicitly; outcome is not editorial endorsement.

- [ ] **Step 4: Resolve duplicate reports**

Inspect every exact or >=0.90 near-duplicate pair. Keep both only when substantive resume content and
published role examples are distinct. Record the resolution; superficial name/employer swaps count
once.

- [ ] **Step 5: Reach the binding Huntr gate**

Generate a provisional report and verify:

- accepted Huntr records >= 50;
- every accepted record is 0–36 months;
- no illustrative or unknown examples promoted;
- every record has recruiter screen or stronger evidence;
- all composites/reconstructions are labeled;
- no unresolved duplicate blocks remain.

If any count is below the gate, return to bounded discovery, not policy relaxation.

No commit occurs because candidate bundles remain ignored.

---

### Task 7: Acquire and Annotate Public Doctrine

**Files:**

- Create ignored: `data/resume_research/raw/doctrine/`
- Create ignored doctrine bundles under `data/resume_research/inbox/doctrine/`.

**Interfaces:**

- Produces 6–10 valid doctrine records, prioritizing author-first-party material.

Approved initial URLs:

- `https://thetechresume.com/A_Good_Tech_Resume.pdf`
- `https://thetechresume.com/assets/downloads/Sample%20Chapters%20The%20Tech%20Resume%20Inside%20Out%201.0.pdf`
- `https://thetechresume.com/samples/resume-structure.html`
- `https://thetechresume.com/samples/resume-templates`
- `https://thetechresume.com/samples/common-mistakes`
- `https://thetechresume.com/samples/the-hiring-pipeline`
- `https://techleadjournal.dev/episodes/15/`
- `https://www.techinterviewhandbook.org/resume/`

- [ ] **Step 1: Validate the allowlist and fetch sequentially by host**

Use the research operator with separate host-aware batches. PDFs may be scraped directly if
Firecrawl returns complete extracted text. If not, download the public official PDF once into the
ignored directory and parse it locally using the existing PDF runtime; do not seek another copy.

- [ ] **Step 2: Create source-anchored doctrine records**

Paraphrase principles rather than copying passages. Each record has one 4–25-word exact supporting
quote, early-career applicability, affected dimensions, qualifications/conflicts, authority kind,
confidence, and permitted use.

- [ ] **Step 3: Cross-check secondary material**

An interview or third-party note can corroborate first-party doctrine. It cannot introduce a paid
book claim as authoritative unless the public source itself contains and supports that claim.
Unauthorized PDF mirrors and book-substitute summaries are rejected without fetching.

- [ ] **Step 4: Validate the doctrine sub-corpus**

Run every doctrine record through the strict parser, source hash, quote anchor, URL policy, and
corpus-ID checks. Produce the authority-kind and affected-dimension distribution.

No commit occurs because raw and staged doctrine remain ignored.

---

### Task 8: Discover Additional Individually Shared Outcome Resumes

**Files:**

- Create ignored raw and candidate bundles for approved public stories.

**Interfaces:**

- Produces up to 10–15 additional accepted outcome records or an honest shortfall report.

- [ ] **Step 1: Run bounded public searches**

Use exact query families:

```text
site:reddit.com/r/EngineeringResumes 0 YOE offer sharing resume
site:reddit.com/r/EngineeringResumes new grad interview resume success
site:reddit.com/r/cscareerquestions exemplary resume new grad offer
early career software engineer resume landed interview public PDF
```

Do not search or scrape LinkedIn. Prefer posts where the author explicitly shares the resume version,
experience level, and interview/offer result.

- [ ] **Step 2: Apply the same admission policy without exceptions**

Self-reported evidence is labeled `self_reported`. The shared resume version must be attributable to
the result. Comments praising a resume are not outcome evidence. Deleted images, unavailable files,
or vague funnels remain rejected.

- [ ] **Step 3: Stop at 15 accepted records or exhausted credible supply**

Report searched, fetched, accepted, rejected, ambiguous, and unavailable counts. This task cannot
delay the binding 50-Huntr gate once Huntr and doctrine requirements pass.

No commit occurs because these are ignored research artifacts.

---

### Task 9: Pattern Cards, Final Review Report, and User Approval Gate

**Files:**

- Create ignored pattern bundles under `data/resume_research/inbox/patterns/`.
- Create ignored final manifest and report under `data/resume_research/reports/`.

**Interfaces:**

- Produces the exact report hash that may authorize promotion.

- [ ] **Step 1: Derive traceable pattern cards**

Each pattern/anti-pattern cites at least two distinct outcome IDs or one direct doctrine ID, states
role/early-career scope, limitations, confidence, prohibited uses, and candidate rubric dimensions.
Do not state that a pattern caused an interview.

- [ ] **Step 2: Freeze the exact disposition manifest**

List accepted outcomes under `promote_outcome_ids`. List every rejected, ambiguous, superseded, or
duplicate outcome under `excluded_outcomes` with a specific nonempty reason. List every doctrine and
pattern ID. Include corpus version `0.1.0`. Every staged outcome must appear exactly once in one of
the two outcome dispositions. After this point, any record or disposition change changes the report
hash and invalidates approval.

- [ ] **Step 3: Generate the deterministic final report**

Run:

```bash
.venv/bin/python -m scripts.resume_evidence report --inbox data/resume_research/inbox --manifest data/resume_research/manifest.yaml --output data/resume_research/reports/final
```

Verify report counts include accepted/rejected/ambiguous/duplicates, source, role family, outcome
tier, confidence, and representation. Confirm accepted Huntr count is at least 50.

- [ ] **Step 4: Verify no raw content leaked into the report**

Search for synthetic/public names, emails, phone patterns, full bullets, and long source passages.
Only bounded evidence excerpts and concise annotations are permitted.

- [ ] **Step 5: Present the report and stop for explicit approval**

Give the user the report path, exact `report.json` SHA-256, counts, limitations, credits spent, and
all unresolved exclusions. Ask the user to approve that exact hash. Do not import, stage tracked
canonical YAML, or continue on an approval that does not repeat or unambiguously reference the hash.

---

### Task 10: Atomic Promotion and Milestone Closeout

**Files:**

- Create through importer: `config/resume_evidence_bank/current/`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/IMPLEMENTATION_PLAN.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**

- Consumes: exact user-approved final report SHA-256.
- Produces: canonical advisory corpus only; no tailoring integration.

- [ ] **Step 1: Recompute and verify the approval hash immediately before import**

Regenerate the report from the unchanged inbox/manifest. Its hash must equal the approved hash.
Abort on any drift.

- [ ] **Step 2: Import atomically**

Copy the exact 64-character hash from the user's approval message into the
`--approved-report-sha256` argument. Set `--approved-at` to the current whole-second UTC timestamp
only after that approval. Before execution, show the fully resolved command—with the literal hash
and timestamp—to the user; do not execute a command containing symbolic operands or a hash read
automatically from the report. The remaining fixed arguments are:

```text
.venv/bin/python -m scripts.resume_evidence import-corpus
--inbox data/resume_research/inbox
--manifest data/resume_research/manifest.yaml
--bank-root config/resume_evidence_bank
--approved-report-sha256 <the literal user-approved 64-character hash>
--approved-at <the post-approval whole-second UTC timestamp>
```

The importer must report `created`. Rerun the fully resolved identical command and require
`unchanged` with byte-identical canonical files.

- [ ] **Step 3: Validate and inspect canonical statistics**

Run:

```bash
.venv/bin/python -m scripts.resume_evidence stats --bank-root config/resume_evidence_bank
.venv/bin/python -m scripts.resume_evidence lookup --bank-root config/resume_evidence_bank --role-family backend_platform --max-months 36
```

Verify at least 50 Huntr outcomes, 6–10 doctrine sources, no ambiguous outcomes, no complete resume
text, and the approved report hash in `corpus.yaml`.

- [ ] **Step 4: Update authoritative documentation**

Record actual counts, credits, source limitations, approval hash, commits, and smoke evidence.
State explicitly that M8Q-0B is a canonical advisory bank only and that integration with tailoring,
M8V, SkillOpt, prompts, quality gates, and application outcomes remains unstarted.

- [ ] **Step 5: Verify production and privacy invariants**

Run:

```bash
shasum -a 256 data/jobs.db
sqlite3 data/jobs.db "PRAGMA integrity_check;"
git status --short
git diff --check
```

Compare DB hash to Task 1. Confirm no raw `data/` artifact is staged and all unrelated user changes
remain untouched.

- [ ] **Step 6: Run focused and full suites**

Run:

```bash
.venv/bin/python -m pytest tests/resume_evidence tests/test_resume_evidence_cli.py tests/test_resume_evidence_integration.py tests/test_research_resume_evidence_cli.py -q
.venv/bin/python -m pytest -q
```

Expected: all selected tests pass; the full suite retains only the repository's intentional
deselection.

- [ ] **Step 7: Commit scoped tracked files**

```bash
git add src/resume_evidence/huntr.py scripts/research_resume_evidence.py tests/resume_evidence/test_huntr.py tests/test_research_resume_evidence_cli.py tests/fixtures/resume_evidence/huntr_mixed_minimal.md config/resume_evidence_bank/current docs/ARCHITECTURE.md docs/ROADMAP.md docs/IMPLEMENTATION_PLAN.md docs/DECISIONS.md
git commit -m "feat(m8q): adopt early-career resume evidence corpus"
```

Before committing, inspect `git diff --cached --name-only` and abort if any `data/`, inbox, profile,
prompt, application, trace, or unrelated path is present.

- [ ] **Step 8: Report completion and stop**

Report exact accepted/rejected/ambiguous/duplicate counts, 50+ Huntr proof, role/outcome/representation
distribution, doctrine count, additional public-story count, Firecrawl credits consumed, tests, DB
hash, commits, and final dirty state. Confirm no push, model call, LinkedIn scrape, paid-book access,
DB mutation, tailoring run, prompt/profile change, Company Bank change, or SkillOpt integration.

Stop. The next work, if requested, is a separate evidence-bank integration design—not an automatic
continuation of M8Q-0B.

### M8Q-0B transport decision (2026-08-30)

The first approved Firecrawl CLI attempt used version 1.19.29 and failed normally after
approximately 58 seconds with `All scraping engines failed to retrieve content from this URL.`
The target remains publicly accessible through an ordinary independent reader, and the
Firecrawl balance remained 1,249 before and after, so no credit was consumed. Firecrawl remains
the primary acquisition transport, with at most one attempt per target. The approved Crawl4AI
path may receive at most one explicitly selected fallback attempt after a recorded Firecrawl
retrieval failure or incomplete extraction; this is not an automatic retry loop and does not
authorize proxies, stealth, authentication, CAPTCHA handling, or broader crawling.

Same-host spacing remains at least two seconds across transports. Both failed and successful
attempts are recorded in ignored checkpoints/reports, and a Crawl4AI failure ends the affected
batch. A fallback capture may omit screenshots when complete markdown and HTML are available;
it records `layout_capture_available: false`, actual transport provenance, and the limitation.
The Huntr parser consumes only the transport-neutral normalized capture envelope, never a
provider-specific response object.

### M8Q-0BR repair milestone (2026-08-30)

M8Q-0BR repairs the offline contracts exposed by the first three-page smoke without performing
another live smoke. The Huntr parser now separates page-level methodology from bounded resume
sections, requires publisher outcome provenance plus reconstruction/anonymization for composite
promotion, preserves exact section and methodology quotes, and retains composite limitations.
Read-only replay of the three existing ignored captures found 91 sections/91 promotable composites
on the real-resume hub, 26 sections/2 promotable composites/24 illustrative sections on the
software page, and 20 sections/1 promotable composite/19 illustrative sections on the ML page.
Exact per-example outcome evidence appeared in 91, 7, and 9 sections respectively.

The operator now classifies real subprocess results through a typed bounded outcome contract,
passes a finite 180-second timeout, and uses `--proxy basic` only. `auto`, `enhanced`, and
`stealth` are prohibited. `--allow-crawl4ai-fallback` is disabled by default and enables exactly
one existing ordinary `Crawl4AIBrowserClient` attempt only after `retrieval_failure` or
deterministic `incomplete_extraction`; terminal access, authentication, policy, budget,
rate-limit, and timeout outcomes never activate it. Both attempts are recorded in a strict atomic
checkpoint, and the client closes in `finally`. Provider normalization drops LinkedIn and
unrelated external navigation links without visiting them; strict caller-supplied captures remain
fail-closed for unsafe links.

No new live smoke occurred during repair: the three ignored captures and smoke report were not
overwritten. Playwright was not added as a transport; Crawl4AI remains the approved ordinary
browser fallback, with no stealth or anti-bot circumvention. Verification passed with 164
`tests/resume_evidence/` tests, 50 M8Q CLI/integration tests, and 1852 full-suite tests with one
intentional deselection. M8Q-0B Task 5, bulk acquisition, annotation/import, and later tailoring
integration remain pending.
