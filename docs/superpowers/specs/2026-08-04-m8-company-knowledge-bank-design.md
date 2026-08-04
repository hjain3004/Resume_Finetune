# M8 Company Knowledge Bank — Design

**Date:** 2026-08-04
**Status:** Proposed for user review; no implementation is authorized by this document
**Phase:** 3 (M8 Tailoring), supporting subsystem for S0 positioning and S2 tie-breaking

## 1. Goal

Build a versioned, evidence-anchored knowledge bank for 30 approved target companies so
company and product context can be reused across applications without repeating web research
or an LLM research call for every role.

The bank influences positioning, project affinity, and bullet ordering. It never creates a
resume claim, turns a company value into a job requirement, overrides the JD, changes
eligibility or sponsorship policy, or writes to SQLite.

## 2. Why this is a separate subsystem

The authoritative tailoring flow remains:

```text
JD -> S1 -> validate S1 -> S0 -> S2 -> validate S2 -> S3 -> G1 -> G2 -> G3
```

Company research has a different reuse key and trust boundary from the JD:

- a JD is per application and is authoritative for requirements and exact terminology;
- company research is reusable across applications but can become stale;
- product and engineering facts may influence strategy but cannot become candidate facts;
- explicit hiring guidance is advisory and may be scoped to one role family or location.

Therefore research is collected and validated before live tailoring, then projected into a
small typed view for S0. No live-tailoring model receives raw web pages.

## 3. Fixed seed corpus

Version 0.1.0 covers exactly these 30 canonical company ids and display names:

| `company_id` | Display name |
|---|---|
| `palantir` | Palantir |
| `cisco` | Cisco |
| `notion` | Notion |
| `atos` | Atos |
| `bytedance` | ByteDance |
| `newsbreak` | NewsBreak |
| `quantcast` | Quantcast |
| `google` | Google |
| `microsoft` | Microsoft |
| `amazon` | Amazon |
| `meta` | Meta |
| `apple` | Apple |
| `nvidia` | NVIDIA |
| `netflix` | Netflix |
| `linkedin` | LinkedIn |
| `uber` | Uber |
| `airbnb` | Airbnb |
| `stripe` | Stripe |
| `databricks` | Databricks |
| `snowflake` | Snowflake |
| `cloudflare` | Cloudflare |
| `mongodb` | MongoDB |
| `datadog` | Datadog |
| `doordash` | DoorDash |
| `roblox` | Roblox |
| `capital_one` | Capital One |
| `salesforce` | Salesforce |
| `rippling` | Rippling |
| `plaid` | Plaid |
| `ramp` | Ramp |

Citadel, Citadel Securities, and Bloomberg were deliberately excluded at the user's request.
Quantcast remains because it is an advertising/ML infrastructure company, not a quantitative
finance employer.

After version 0.1.0, unseen companies are added lazily through the same research/import
contract. Expanding beyond these 30 is not part of the first implementation or research run.

## 4. Source-of-truth and storage boundaries

### 4.1 Versioned canonical bank

```text
config/company_bank/
  seed_companies.yaml
  companies/
    amazon.yaml
    ... one YAML file per canonical company id
```

The individual YAML dossiers are the only canonical company-knowledge source. There is no
hand-maintained duplicate index. The loader scans `companies/*.yaml` in sorted filename order
and builds its alias index in memory.

`seed_companies.yaml` fixes the 30-company acceptance set and the expected display name for
each id. It contains no research facts.

### 4.2 Untrusted research inbox and source snapshots

```text
data/company_research/inbox/{company_id}/
  bundle.json
  sources/{source_id}.txt
```

Claude Web writes research proposals and saved plain-text source snapshots here. These files
are untrusted inputs, local working evidence, and remain outside the canonical bank. They do
not become production data until Gemini's deterministic importer validates the complete
corpus.

The existing `data/` ignore policy applies. Canonical dossiers retain source URLs, short
quotes, retrieval timestamps, and snapshot hashes so their provenance remains inspectable
without committing full web pages.

### 4.3 No SQLite schema

The bank is configuration/reference data, not job lifecycle state. Version 0.1.0 adds no DB
table, column, migration, or status transition. This avoids a PROTECTED schema change and
keeps the bank reviewable in Git.

## 5. Canonical dossier contract

Each `companies/{company_id}.yaml` has this logical shape:

```yaml
schema_version: "0.1.0"
company_id: amazon
display_name: Amazon
aliases: [Amazon.com]
official_domains: [amazon.com, amazon.jobs]
researched_at: "2026-08-04T00:00:00Z"
expires_at: "2026-11-02T00:00:00Z"
sources:
  - id: careers_how_we_hire
    url: "https://www.amazon.jobs/content/en/how-we-hire"
    title: "How We Hire"
    source_kind: official_careers
    scope: {kind: company, name: Amazon}
    retrieved_at: "2026-08-04T00:00:00Z"
    content_sha256: "<64 lowercase hex characters>"
facts:
  - id: role_specific_process
    kind: hiring_guidance
    scope: {kind: company, name: Amazon}
    claim: "Application and interview processes vary by role."
    quote: "<short exact quote from the saved source snapshot>"
    source_id: careers_how_we_hire
signals:
  - id: prefer_role_specific_evidence
    text: "Prioritize evidence tied to the role and business unit over generic company values."
    basis_fact_ids: [role_specific_process]
    permitted_uses: [s0, g3_advisory]
```

The example illustrates shape only. The research plan supplies the real facts and exact
quotes; implementation must not copy example prose into a production dossier.

### 5.1 Typed model

`src/company_bank/model.py` defines frozen dataclasses and enums:

- `ScopeKind = company | business_unit | role_family`
- `SourceKind = official_company | official_product | official_engineering |
  official_careers | official_hiring_guide | verified_dataset`
- `FactKind = identity | industry | product | domain | engineering_theme | value |
  hiring_guidance | ats`
- `PermittedUse = s0 | s2_tiebreak | g3_advisory`
- `CompanyScope(kind: ScopeKind, name: str)`
- `CompanySource(...)`
- `CompanyFact(...)`
- `TailoringSignal(...)`
- `CompanyDossier(...)`
- `CompanyPositioningView(...)`
- `LookupStatus = fresh | expired | missing`
- `CompanyLookupResult(status, company_id, view, message)`

Raw dictionaries exist only at the JSON/YAML serialization boundary.

## 6. Source authority and evidence rules

### 6.1 Permitted canonical sources

Primary sources are required for product, engineering, values, and hiring guidance:

- official company/about pages;
- official product or business-unit pages;
- official engineering blogs or technical publications;
- official careers/how-we-hire pages;
- official candidate or resume guidance.

Verified open datasets may seed only identity, industry, and ATS facts. Version 0.1.0 may use
Wikidata for identity/industry leads and the MIT-licensed State of ATS dataset for ATS leads,
but the research run must still record provenance and verification status.

Commercial resume hubs, search snippets, employee-review sites, Reddit, anonymous interview
reports, and recruiter SEO articles are lead sources only. Their prose and conclusions do
not enter canonical dossiers.

No LinkedIn scraping is permitted.

### 6.2 Quote anchoring

Every canonical fact has exactly one `source_id` and one nonempty `quote`. During import:

- the source snapshot must exist and decode as UTF-8;
- its SHA-256 must equal `content_sha256`;
- `quote` must be an exact substring of that snapshot;
- the source URL must be HTTPS;
- the URL host must equal an official domain declared by the dossier or be its true
  subdomain (`host == domain` or `host.endswith("." + domain)`), or be an explicitly
  allowlisted verified-dataset host for an eligible fact kind;
- source, fact, and signal ids must be unique within the dossier;
- every reference must resolve.

The importer refuses invalid bundles. It never repairs quotes, coerces types, fills missing
fields, or partially imports a corpus.

### 6.3 Copyright minimization

Canonical dossiers store only the shortest excerpt needed to support a fact. Full page text
stays in the ignored research inbox. Research must not copy articles, large page sections,
or collections of excerpts that reconstruct a source.

## 7. Deterministic use policy

The JD remains authoritative for requirements, disqualifiers, exact keywords, and S3
terminology. The company bank has no path into scoring or eligibility.

Permitted influence is mechanically bounded by fact kind:

| Fact kind | Allowed downstream influence |
|---|---|
| `product`, `domain`, `engineering_theme` | S0 positioning; S2 tie-break at equal JD coverage |
| `hiring_guidance` | S0 positioning; G3 advisory note |
| `value` | S0 soft positioning only |
| `identity`, `industry` | Context labels only |
| `ats` | G3/preflight advisory only |

Rules:

1. Raw sources and raw research bundles are never prompt inputs.
2. S0 receives only `CompanyPositioningView`, containing fresh signals plus their short
   citations.
3. S2 may receive only signals marked `s2_tiebreak`; they may break a tie after JD coverage,
   claim safety, and priority constraints, never overrule them.
4. S3 receives no company-bank facts or signals. It uses validated S1 requirements, the S0
   strategy, and validated S2 selection. New terminology must come from the JD.
5. G1 and G2 rules are unchanged.
6. A company fact never becomes a candidate fact.
7. Values never become technical requirements or stuffing targets.
8. Company-specific formatting advice is advisory unless an official application source
   explicitly states it; it never bypasses the selected LaTeX renderer or L7.
9. Sponsorship, citizenship, work authorization, location, role type, and start window are
   excluded from the bank. The JD and `config/eligibility.yaml` remain authoritative.

## 8. Lookup, aliases, and scope

Company matching uses deterministic exact normalization:

1. Unicode NFKC;
2. casefold;
3. collapse non-alphanumeric runs to one space;
4. collapse whitespace and trim.

No fuzzy matching is allowed. Each normalized canonical display name and alias must map to
exactly one company id; collisions fail the entire bank load before lookup is available. A
missing lookup falls back to JD-only tailoring and produces a visible warning.

Aliases are human-reviewed. Parent companies and product brands are not silently merged.
For example, a TikTok alias may only map to ByteDance if the research packet explicitly
records that scope and the user accepts it.

Version 0.1.0 stores company, business-unit, and role-family facts in one dossier using the
typed `scope`. Lookup returns all fresh company-wide signals plus the exact matching scoped
signals requested by the caller. There is no substring or semantic scope matching.

## 9. Freshness and cache behavior

Every imported dossier has a 90-day TTL:

- `expires_at` is computed by the importer as `researched_at + 90 days`;
- the untrusted research bundle omits `expires_at`; research output cannot choose or extend
  the TTL;
- expired dossiers remain readable for audit but are not projected into S0;
- expired or missing data triggers JD-only tailoring, not a pipeline failure;
- refresh writes a new research bundle and updates the canonical dossier through the same
  validation path;
- no runtime model call is made for a fresh dossier.

A later refresh tool may extend the expiry without another synthesis only when every source
was re-fetched, every content hash is unchanged, and the refresh is traced. That optimization
is outside version 0.1.0.

## 10. Research/import boundary

The work is deliberately split into three execution tracks:

### Track A — Gemini foundation milestone

Build typed models, pure parsing and semantic validation, deterministic loader/lookup,
research-bundle schema, atomic corpus importer, validation CLI, synthetic fixtures, and
tests. It uses no real company research and no network.

### Track B — Claude Web research run

Research the fixed 30 companies in six batches of five. Produce one `bundle.json` and the
referenced plain-text source snapshots per company. Use primary sources, exact quotes, and
the fixed contract. Do not edit production code or canonical dossiers.

### Track C — Gemini adoption milestone

Treat all 30 bundles as untrusted. Validate the complete set, import only if all 30 pass,
generate the human-readable coverage report, run bank tests and the full suite, and commit
the canonical 30-company corpus. No web research occurs in this track.

Tracks A and C are separate implementation sessions and commits. Track C cannot begin until
Track B has produced all required artifacts. Live S0/S2 integration is a later M8 milestone
after the live-tailoring design is approved; the bank exposes the typed projection it will
consume but does not implement S0 or S2.

## 11. Failure handling and idempotency

- Import uses a staging directory. It validates all expected company ids and every bundle
  before replacing or creating any canonical dossier.
- A failed corpus import writes no canonical files.
- Re-importing byte-identical bundles produces byte-identical canonical YAML and no Git diff.
- Missing seed companies, unexpected company ids, duplicate aliases, expired-on-arrival
  timestamps, unresolved references, disallowed source hosts, snapshot hash mismatches, and
  quote mismatches are hard failures.
- Missing/expired runtime lookup is a warning plus JD-only fallback.
- The importer and loader never access the network.
- Logs use `logging`; library code never prints. CLI summary output is permitted in scripts.

## 12. Security and privacy

- Research packets contain public company information only.
- Candidate identity, contact details, profile evidence, defenses, interview risks, job DB
  rows, and tailored resumes never enter the company bank.
- Claude Web receives the fixed company research contract, not `master_profile.yaml`.
- The future S0 projection contains only validated company signals and citations.
- No unattended actor, crawler, or arbitrary public integration is introduced.

## 13. Testing strategy

All automated tests are offline and fixture-based.

Foundation coverage includes:

- schema and typed parsing success;
- missing/unknown fields and wrong types;
- exact quote success and mismatch;
- snapshot hash mismatch;
- official-host and verified-dataset restrictions;
- fact-kind/source-kind compatibility;
- unresolved source/fact references;
- duplicate ids and normalized alias collisions;
- permitted-use matrix enforcement;
- 90-day TTL computation and expired lookup;
- missing lookup fallback and load-time alias-collision rejection;
- scope filtering;
- all-or-nothing 30-company corpus import;
- byte-identical re-import;
- privacy projection excludes raw pages and unrelated fields.

Adoption acceptance includes:

- exactly 30 canonical dossiers;
- exact agreement with `seed_companies.yaml`;
- at least one official source and one product/domain/engineering fact per company;
- any `hiring_guidance` fact is backed by an official careers or hiring-guide source;
- every signal has at least one valid basis fact;
- zero sponsorship or candidate-data fields;
- all dossiers fresh on import;
- complete bank validation and full `pytest -q` green.

## 14. Documentation and status

Track A documents the contract and offline commands. Track C adds a coverage report listing
per company: source count, fact count by kind, signal count, scopes, researched time, and
expiry. It does not reproduce source quotes in the report.

M8 remains incomplete after the bank lands. ROADMAP may report the company bank as complete
only after Track C acceptance, while continuing to list S1/S0/S2/S3/G1/G2/G3, CLI, and DB
integration as remaining work.

The prior `2026-07-30-m8-tailor-critic-design.md` remains superseded by the forthcoming live
tailoring design. This company-bank spec does not authorize implementation of that broader
workflow.

## 15. Accepted trade-offs

- Thirty dossiers provide useful coverage without attempting an unmaintainable universal
  database.
- Primary-source requirements reduce coverage but keep decisions defensible.
- A 90-day TTL creates periodic maintenance but prevents silent use of stale guidance.
- On-disk YAML avoids a protected DB migration and makes review easy.
- Separate S1 and S0 calls cost one additional small invocation but prevent external company
  research from contaminating JD requirement extraction.
- Company research is amortized once per company/scope; fresh dossiers require zero research
  calls per application.
