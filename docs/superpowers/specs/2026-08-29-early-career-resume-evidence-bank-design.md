# Early-Career Resume Evidence Bank — Design

**Date:** 2026-08-29

**Status:** approved design; implementation and live acquisition have not started

**Working milestone label:** M8Q-0

**Owner:** user-supervised research supporting Phase 3 tailoring quality

## 1. Purpose

The current tailoring system is strong at provenance, fabrication prevention, deterministic
validation, bounded editing, rendering, and review traceability. Those controls can prove that a
resume is internally valid, but they cannot by themselves prove that its editorial choices resemble
effective early-career resumes. This design adds a separate evidence bank to support that missing
quality judgment.

The bank has two distinct evidence surfaces:

1. **Outcome resumes:** public or publisher-anonymized resumes from candidates with 0–3 years of
   professional experience whose resume reached at least a recruiter/HR screen.
2. **Editorial doctrine:** public guidance from experienced technical hiring practitioners,
   prioritizing first-party material such as Gergely Orosz's official free guide, sample chapters,
   public summaries, posts, and interviews.

The first version must promote at least **50 distinct validated Huntr outcome records**. Additional
individually shared success resumes and doctrine sources provide diversity and a cross-check against
Huntr's editorial style.

This is an advisory research subsystem. It does not alter tailoring behavior. A later, separately
approved milestone may decide whether and how derived pattern cards enter S0, S2, G2, G3, a new
quality gate, or SkillOpt experiments.

## 2. Decisions

| ID | Decision |
|---|---|
| D1 | Scope is limited to candidates with 0–3 years of post-graduation full-time professional experience. |
| D2 | Internships and co-ops are recorded separately and do not consume the 36-month professional-experience cap. |
| D3 | A recruiter/HR screen is the minimum accepted outcome. Automated OAs, resume views, vague responses, and application acknowledgements do not qualify. |
| D4 | Outcome strength and editorial quality are independent. An outcome-linked resume may be retained while receiving a weak editorial assessment. |
| D5 | V1 requires at least 50 distinct validated Huntr records. Fetch count is not promotion count. |
| D6 | Huntr composites and reconstructed examples are eligible only when explicitly labeled; they are never represented as literal individual resumes. |
| D7 | Raw resume captures remain local, private, and Git-ignored. Tracked canonical records contain metadata, hashes, short anchored evidence, annotations, and derived patterns only. |
| D8 | Firecrawl CLI is an interactive acquisition tool, not a production dependency. Crawl4AI is a bounded public-page fallback. Crawlee is not added. |
| D9 | Promotion is corpus-wide and atomic. An invalid record cannot be silently skipped during promotion. |
| D10 | The evidence bank cannot edit prompts, profiles, taste rules, applications, or SQLite. Integration requires a new milestone. |
| D11 | No LinkedIn scraping, authentication, CAPTCHA handling, paywall bypass, stealth, proxies, or anti-bot evasion is permitted. |
| D12 | The paid text of *The Tech Resume Inside Out* is not acquired. Only public authorized material and public commentary are used unless the user later supplies a legally obtained private copy. |

## 3. Approaches considered

### 3.1 Curated hybrid bank — selected

Build an outcome corpus and a doctrine corpus, validate both, then derive traceable pattern cards.
This preserves the distinction between observed outcomes and expert recommendations. It is slower
than copying a commercial example site, but its provenance and limitations remain reviewable.

### 3.2 Huntr-only bank — rejected as the complete design

Huntr provides a large, consistent outcome-linked collection and remains the primary V1 source.
However, its methodology allows anonymized reconstruction, composites, and adjusted details. A
Huntr-only bank risks learning one publisher's editing conventions rather than durable hiring
patterns.

### 3.3 Broad web crawl — rejected

A large crawl would maximize volume while admitting synthetic templates, duplicated resumes,
unclear consent, unverifiable outcomes, senior candidates, and SEO content. Human cleanup would
cost more than careful acquisition and would weaken the evidence standard.

## 4. Scope and targets

### 4.1 Outcome corpus

V1 acquisition targets:

- Discover approximately 60–70 Huntr candidates in order to promote at least 50 valid records.
- Add 10–15 individually shared public resumes with interview or offer outcomes when they pass the
  same experience and evidence gates.
- Report the observed role distribution rather than padding quotas with irrelevant examples.

Role-family labels are:

- `general_swe`
- `backend_platform`
- `ml_data`
- `java_enterprise`
- `other_relevant`

The desired corpus covers all four primary families where the public evidence allows it. A source
shortfall remains visible; it is not repaired by reclassifying a resume.

### 4.2 Doctrine corpus

V1 targets 6–10 authoritative public sources. Source precedence is:

1. official free book material and author-controlled excerpts;
2. the author's public summaries, posts, talks, and interviews;
3. official technical-hiring guidance from other credible practitioners or institutions;
4. detailed reader notes used only as corroboration;
5. ordinary reviews used only to discover possible topics, never as sole authority.

Initial approved discovery set:

- `https://thetechresume.com/A_Good_Tech_Resume.pdf`
- `https://thetechresume.com/assets/downloads/Sample%20Chapters%20The%20Tech%20Resume%20Inside%20Out%201.0.pdf`
- `https://thetechresume.com/samples/resume-structure.html`
- `https://thetechresume.com/samples/resume-templates`
- `https://thetechresume.com/samples/common-mistakes`
- Gergely Orosz's public resume-summary posts and public interviews
- Tech Interview Handbook's public software-engineering resume guidance
- a small number of engineering-focused university or hiring-manager guides

Public third-party summaries may be evaluated, but the bank must not rely on a source that appears
to reconstruct the paid book or function as an unauthorized substitute for it.

### 4.3 Non-goals

- Building a resume search engine.
- Training or fine-tuning a model.
- SkillOpt integration.
- Modifying the current M8 pilot or M8V verification work.
- Declaring scraped wording safe to copy.
- Proving causal effectiveness from a resume and its outcome.
- Redistributing full resumes or paid book text.
- Creating a continuously running crawler or monitor.

## 5. Repository boundary

Proposed layout:

```text
data/
└── resume_research/                  # ignored; private local research state
    ├── inbox/
    │   └── <reference_id>/
    │       ├── candidate.yaml
    │       ├── source.md
    │       ├── layout.png|pdf        # optional; private visual reference
    │       └── acquisition.json
    ├── reports/
    └── checkpoints/

config/
└── resume_evidence_bank/             # tracked canonical advisory data
    ├── corpus.yaml
    ├── outcomes/
    │   └── <reference_id>.yaml
    ├── doctrine/
    │   └── <doctrine_id>.yaml
    └── patterns/
        └── <pattern_id>.yaml

src/
└── resume_evidence/                  # deterministic contracts and validation

scripts/
└── resume_evidence.py                # thin offline operator CLI

tests/
├── resume_evidence/
└── fixtures/resume_evidence/
```

`data/` is already ignored. Complete resumes, screenshots, PDFs, and Firecrawl output never leave
the private `data/resume_research/` boundary. Canonical tracked YAML must be sufficient to audit
the classification without reproducing the source.

## 6. Typed contracts

### 6.1 Outcome candidate

Each staged candidate contains:

- `schema_version`
- `reference_id`
- one or more source records, each with `source_id`, URL, host, kind, retrieval time, title, and
  content SHA-256
- `resume_source_id`
- `outcome_source_id`
- `layout_sha256` when a visual capture exists
- `role_family`
- `target_role`
- `target_level`
- `graduation_month` when available
- normalized professional-employment intervals
- normalized internship/co-op intervals
- `professional_experience_months`
- `experience_confidence`
- `outcome_tier`
- `outcome_evidence_quote`
- `outcome_evidence_confidence`
- `resume_representation`
- `resume_version_attribution`
- structured section and layout observations
- editorial dimension annotations with evidence
- exclusion or review flags

Closed enums:

```text
source_kind:
  huntr | individual_public_story | other_approved

outcome_tier:
  recruiter_screen | technical_interview | final_interview | offer

outcome_evidence_confidence:
  platform_logged | publisher_asserted | self_reported

resume_representation:
  individual | anonymized | reconstructed | composite

resume_version_attribution:
  exact | publisher_linked | ambiguous

experience_confidence:
  exact | derived | ambiguous
```

`ambiguous` experience or resume-version attribution cannot promote automatically. A later human
decision may resolve it by adding explicit evidence; the validator never guesses.

The resume and outcome may be supported by different public pages. This is necessary when a role
page contains the resume while a publisher methodology or outcome page establishes how the example
was selected. Both pages must be captured, hashed, and linked explicitly; a corpus-wide publisher
claim may not be silently treated as a per-resume fact without recording that attribution limit.

### 6.2 Canonical outcome record

The canonical record excludes the complete resume and retains:

- identity, all supporting source records, hashes, and retrieval metadata;
- experience and outcome classifications;
- an outcome excerpt of no more than 25 words that must occur in the staged snapshot;
- section/layout observations;
- editorial ratings and concise evidence-backed explanations;
- limitations and representation labels;
- derived feature tags;
- promotion timestamp and corpus version.

### 6.3 Doctrine record

Each doctrine record contains:

- `doctrine_id`
- source metadata and hash
- `authority_kind`: `author_first_party | practitioner_first_party | institutional | secondary`
- principle paraphrase
- applicability to early-career candidates
- affected resume section or review dimension
- supporting excerpt of no more than 25 words
- conflicts or qualifications
- confidence
- permitted use: `rubric_candidate | pattern_context | advisory_only`

### 6.4 Pattern card

A pattern card is a derived observation, not source text. It contains:

- a concise pattern or anti-pattern;
- the early-career and role-family scope;
- supporting outcome-record IDs and doctrine-record IDs;
- limitations and counterexamples;
- confidence;
- prohibited uses;
- candidate rubric dimensions it may inform.

A pattern card may not claim an outcome relationship from a single resume. Promotion requires either
two independent outcome records or one direct doctrine record. Even then, the wording remains
observational rather than causal.

## 7. Experience calculation

The 0–3 YOE rule is deterministic:

1. Parse month-granular start and end dates for full-time professional roles.
2. Exclude roles explicitly labeled internship, intern, co-op, apprenticeship, campus employment,
   or part-time student work from the cap; record them separately.
3. Count professional intervals only after the recorded graduation month.
4. Merge overlapping intervals before summing so concurrent roles are not double-counted.
5. Treat `Present` as the resume's stated as-of month when available. An explicit publication month
   may be used only when the publisher binds that date to the displayed resume version. Retrieval
   time is never substituted for employment time; without a bound as-of month, classification is
   ambiguous.
6. Accept 0–36 months inclusive. Reject 37 months or more.
7. If a necessary date, role type, or graduation boundary cannot be established, classify the
   experience as ambiguous and withhold promotion.

The stored month count must equal the deterministic recomputation from the stored intervals.

## 8. Admission policy

An outcome candidate promotes only when all conditions pass:

- public HTTPS source accessible without authentication or circumvention;
- actual resume content or a publisher-declared anonymized reconstruction is available;
- 0–36 months under §7;
- relevant technical role family;
- recruiter screen or stronger outcome;
- short outcome evidence is literally anchored in the declared outcome-source snapshot;
- the resume content is present in the declared resume-source snapshot;
- source limitations and representation kind are recorded;
- extraction is complete enough to assess section order, experience, projects, skills, and bullets;
- no unnecessary personal data is retained;
- source and content identities are not duplicates;
- editorial annotations are complete;
- staged hashes match the files being validated.

Automatic OA only, resume view, application acknowledgment, recruiter message without a screen,
generic "got responses," and an outcome attributed to a different unknown resume version fail the
outcome gate.

## 9. Editorial assessment

Outcome strength and editorial quality are separate. Each dimension uses a three-level behavioral
anchor:

| Dimension | 1 — weak | 2 — mixed | 3 — strong |
|---|---|---|---|
| Early-career prioritization | Space is dominated by low-signal or irrelevant material | Relevant material exists but competes with weaker content | Strongest internships, experience, and projects are immediately visible |
| Technical specificity | Generic responsibilities or tool lists | Some concrete systems and techniques | Concrete system, technique, ownership, and constraints are clear |
| Ownership clarity | Team outcome presented without individual contribution | Contribution is partly identifiable | Candidate action and boundary of ownership are explicit |
| Claim credibility | Inflated, unexplained, or internally inconsistent claims | Plausible but weakly contextualized claims | Metrics and claims have credible scope and mechanism |
| Project selection | Tutorial-like or role-irrelevant projects dominate | Mixed relevance or differentiation | Projects demonstrate role-relevant engineering depth |
| Role alignment | Target role is unclear | Some relevant keywords and evidence | Selection and ordering make the target role obvious without stuffing |
| Scanability | Dense, inconsistent, or visually confusing | Readable with localized friction | Clear single-pass hierarchy and restrained emphasis |
| Professional voice | Generic, repetitive, or obviously templated | Mostly natural with some weak lines | Concise, specific, defensible, and consistent voice |

Every rating requires a concise explanation tied to the captured resume. Ratings are evidence for
comparison, not universal truth.

## 10. Acquisition workflow

### 10.1 Discovery

- Use Firecrawl Search or Map only to enumerate likely public pages.
- Do not re-scrape pages already returned with complete content by Search.
- Use an allowlisted source manifest rather than a broad site crawl.
- Record Firecrawl credit status before and after each bounded batch.

### 10.2 Three-page smoke

Before bulk work:

1. select three Huntr pages covering different role families;
2. scrape sequentially;
3. preserve text and a layout representation where available;
4. build candidate bundles;
5. validate outcome evidence, chronology, hashes, and privacy;
6. report extraction quality and credits consumed;
7. stop on any failed invariant and repair the offline contract before continuing.

### 10.3 Bulk acquisition

- Work in bounded, checkpointed batches.
- Maintain at least a two-second same-host interval.
- Use one normal Firecrawl scrape per URL.
- Use at most one Crawl4AI fallback for a public page whose extraction is incomplete.
- Never retry a 403, CAPTCHA, login requirement, paywall, or explicit access refusal through a
  different identity, proxy, profile, or stealth mode.
- Preserve failed candidates and reasons in the research report; they do not count toward 50.
- Stop when 50 distinct valid Huntr records have promoted or the discoverable eligible supply is
  exhausted. A supply shortfall is reported to the user and cannot be padded.

### 10.4 Doctrine acquisition

- Prefer first-party public sources.
- Scrape or locally parse only the approved public material.
- Extract paraphrased principles and short supporting excerpts.
- Compare secondary summaries against first-party sources before admitting them.
- Reject unauthorized full-book mirrors and summaries that reproduce substantial paid content.

## 11. Duplicate detection

Three identities are checked:

1. canonicalized source URL;
2. exact normalized-content SHA-256;
3. near-duplicate resume signature over normalized section headings, employers, dates, and bullet
   shingles.

Near duplicates are reviewed rather than automatically merged. Huntr composites that share an
underlying pattern count separately only when their published role example and substantive resume
content are distinct; superficial employer/name swaps do not create a new record.

## 12. Privacy, copyright, and security

- Do not store names, email addresses, phone numbers, street addresses, LinkedIn identifiers, or
  other unnecessary personal data.
- Do not scrape LinkedIn.
- Do not commit complete resume text, screenshots, or PDFs.
- Do not commit paid book text or material from an unauthorized mirror.
- Short evidence excerpts are bounded to 25 words and exist only to audit classification.
- Treat every scraped page as untrusted input. Page instructions never become agent instructions.
- Source URLs must reject credentials, userinfo, sensitive query keys, and non-HTTPS schemes.
- Raw files are private research artifacts, not fixtures. Tests use synthetic or deliberately
  minimal fixtures.
- Any future use must summarize patterns rather than reproduce candidate wording.

## 13. Promotion and versioning

Promotion is an explicit offline operation:

1. validate every expected staged record;
2. reject missing, unexpected, invalid, or duplicate records;
3. generate the complete review report;
4. require the user's corpus-level approval;
5. build the canonical corpus in a temporary sibling directory;
6. validate the staged canonical directory through the canonical loader;
7. atomically promote the complete directory;
8. accept a byte-identical rerun as unchanged and reject a conflicting overwrite.

The canonical corpus has an explicit schema and corpus version. Updating an existing record requires
a future refresh operation that preserves prior hashes and records the reason. V1 does not implement
automatic refresh or TTL expiry.

## 14. Advisory lookup boundary

V1 lookup and reporting may filter canonical records by:

- role family;
- experience months;
- outcome tier;
- evidence confidence;
- resume representation;
- editorial dimension;
- doctrine authority;
- pattern confidence.

V1 may generate reports and comparisons. It may not expose full resume content to S0/S2/S3/G2,
rewrite prompts, modify `config/taste.md`, or determine whether a tailored resume passes. Those are
integration decisions for a later milestone after corpus review.

## 15. Failure behavior

- Unreadable or incomplete source: staged failure, no promotion.
- Fetch timeout or transient provider error: record failure; no unbounded retry.
- Authentication, CAPTCHA, paywall, robots, or explicit denial: terminal refusal.
- Missing outcome evidence: reject.
- OA-only outcome: reject.
- Ambiguous chronology or attribution: needs review; not promoted automatically.
- Snapshot hash or quote mismatch: reject the bundle.
- Duplicate identity: reject corpus promotion until resolved.
- Invalid canonical staging directory: delete staging directory and leave the current canonical bank
  byte-identical.
- Firecrawl budget or account information unavailable: stop before paid work.
- Any unexpected exception: surface a bounded diagnostic; never reinterpret it as a content failure.

## 16. Tests

All automated tests are offline. Required fixture coverage includes:

- valid early-career offer;
- valid recruiter-screen minimum;
- valid internship-heavy candidate;
- exactly 36 months;
- 37 months rejected;
- overlapping professional intervals;
- internship exclusion from cap;
- `Present` handling;
- ambiguous graduation or chronology;
- automated-OA-only rejection;
- vague outcome rejection;
- ambiguous resume-version attribution;
- Huntr reconstructed/composite labels;
- missing or overlong outcome quote;
- quote not in snapshot;
- snapshot and layout hash mismatch;
- unsafe URL and sensitive query parameters;
- PII redaction and prohibited canonical fields;
- partial extraction;
- exact and near duplicates;
- editorial rating completeness;
- doctrine authority and permitted-use validation;
- pattern card with insufficient basis;
- unexpected/missing corpus record;
- invalid staged canonical corpus;
- byte-identical re-import;
- conflicting re-import;
- deterministic report ordering and statistics;
- CLI exit codes for success, validation failure, and unreadable input.

Network tests are forbidden. The three-page and bulk acquisition runs are user-supervised live
research steps, not pytest cases.

## 17. Acceptance criteria

The foundation and research milestone is complete only when:

- typed contracts and strict parsers exist for outcome, doctrine, and pattern records;
- every validation and failure rule above has focused offline coverage;
- raw research state is demonstrably ignored;
- the three-page Huntr smoke passes and records credits and extraction evidence;
- at least 50 distinct Huntr outcome records pass every promotion gate;
- additional public success records and 6–10 doctrine sources are reported honestly;
- the corpus review report shows accepted, rejected, ambiguous, duplicate, role-family, outcome,
  confidence, and representation counts;
- the user approves the complete corpus;
- canonical promotion is atomic and idempotent;
- the full test suite and `git diff --check` pass;
- `data/jobs.db` is byte-identical to its pre-milestone checksum;
- no tailoring prompt, profile, application artifact, Company Bank record, or existing feedback
  record changes;
- no live tailoring invocation occurs;
- implementation and research are committed in scoped commits, with no push unless the user asks.

## 18. Deferred integration

After the bank is complete and reviewed, a separate design must decide among:

1. a human-only comparison/reference report;
2. retrieval of compact pattern cards into G3;
3. an anchored editorial quality evaluator run beside, not inside, current safety gates;
4. pairwise preference data for a later SkillOpt experiment;
5. a golden-set expansion based on the user's approved tailored resumes and real application
   outcomes.

No integration option is implied by completing this design.
