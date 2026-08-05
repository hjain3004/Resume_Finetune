# M8 Company Knowledge Bank Web Research — Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans if available and execute one five-company batch at a time. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Claude Web to create evidence-anchored, importer-ready research bundles and short source snapshots for the approved 31 companies, without editing production code or canonical dossiers.

**Architecture:** Web research is an untrusted proposal stage. Claude Web gathers primary-source facts, saves only the minimum exact source excerpts needed for verification, and emits one strict `bundle.json` per company under the ignored research inbox. The completed artifacts cross into the repository only through Gemini's offline deterministic importer in the separate adoption milestone.

**Tech Stack:** Claude Web/browser access, local plain-text/JSON artifacts, and the Track A offline validation CLI. No new Python package, crawler, database, or production integration.

**Spec:** `docs/superpowers/specs/2026-08-04-m8-company-knowledge-bank-design.md`

**Prerequisite:** `docs/superpowers/plans/2026-08-04-m8-company-bank-foundation.md` is implemented, committed, and green. In particular, `python -m scripts.company_bank validate-bundle` must exist before this plan begins.

## Global Constraints

- This is **Track B only**. Do not modify `src/`, `scripts/`, `config/`, `tests/`, the database, canonical company dossiers, tailoring prompts, scoring, eligibility, or project documentation.
- Write only beneath `data/company_research/inbox/`, which is ignored working evidence. Do not commit or push research-inbox artifacts.
- No LinkedIn scraping. For LinkedIn the company, use public official domains such as its corporate, engineering, or careers properties; do not scrape member profiles, job-search pages, or authenticated pages.
- Never bypass authentication, CAPTCHA, robots controls, access blocks, or paywalls. If an official page resists access, record the gap and select another official source; never substitute a search-result snippet as evidence.
- Prefer official company/about, product, engineering, careers, and hiring-guide pages. Commercial resume hubs, Reddit, employee-review sites, anonymous interview reports, SEO articles, and search snippets are discovery leads only and cannot enter a bundle.
- Do not infer “the company prefers this on resumes” from corporate values or product marketing. Only an official careers/hiring source may support `hiring_guidance`. Values remain soft S0 context.
- Do not collect or encode sponsorship, citizenship, visa, work authorization, location eligibility, employment type, start dates, candidate data, the user's resume, or the master profile.
- Do not turn a company fact into a candidate fact. Signals describe safe positioning or equal-JD-coverage tie-breaks; they never claim the user has a skill or accomplishment.
- Every fact has one source, one concise claim, and one exact quote copied from the saved source snapshot. Quotes are at most 25 whitespace-delimited words. Preserve spelling and punctuation exactly; do not silently normalize quote text.
- Save only the short exact evidence excerpts needed for facts, with enough nearby context to remain intelligible. Do not save whole articles or assemble excerpts that reconstruct a page.
- Use HTTPS. A source URL must be on the dossier's official domain or a true subdomain. Do not accept lookalikes (`fakeamazon.com` is not `amazon.com`).
- Keep aliases conservative: canonical display name plus obvious punctuation/legal-name variants only. Do not add products, subsidiaries, parent companies, or employer brands such as TikTok as aliases; scoped facts can name them, and alias promotion requires later human approval.
- Use UTC retrieval timestamps ending in `Z`. Use lowercase snake-case ids unique inside each company bundle.
- Each five-company batch is a checkpoint. Validate all five, run `lint-snapshots`, (optionally) run `verify-sources`, report sources/facts/signals/gaps, then stop. Do not silently move into the next batch in the same agent turn if validation needs remediation.
- **NORMATIVE RULE:** The per-company figures in the evidence target are **targets, not floors**. A company with no publicly accessible guidance produces a smaller dossier and records the gap. Fabricating a source to satisfy a count is a hard stop, not a trade-off.

## Required bundle shape

For each company, create:

```text
data/company_research/inbox/{company_id}/
  bundle.json
  sources/{source_id}.txt
```

`bundle.json` must follow `config/company_bank/research_bundle.schema.json`. Use this shape, replacing every value with researched evidence:

```json
{
  "schema_version": "0.1.0",
  "company_id": "acme",
  "display_name": "Acme",
  "aliases": ["Acme, Inc."],
  "official_domains": ["acme.example"],
  "researched_at": "2026-08-04T12:00:00Z",
  "sources": [
    {
      "id": "product_platform",
      "url": "https://acme.example/platform",
      "title": "Acme Platform",
      "source_kind": "official_product",
      "scope": {"kind": "company", "name": "Acme"},
      "retrieved_at": "2026-08-04T12:00:00Z",
      "snapshot_file": "sources/product_platform.txt",
      "content_sha256": "ff84059ab1896a486cd0cde3a932c7d699ac2e5625db7d25eb7bef741b415a2d"
    }
  ],
  "facts": [
    {
      "id": "platform_domain",
      "kind": "domain",
      "scope": {"kind": "company", "name": "Acme"},
      "claim": "The structural example describes a synthetic platform.",
      "quote": "Acme provides a synthetic platform example for contract documentation.",
      "source_id": "product_platform"
    }
  ],
  "signals": [
    {
      "id": "position_realtime_systems",
      "text": "Frame JD-relevant evidence around reliable real-time systems when the candidate profile supports it.",
      "basis_fact_ids": ["platform_domain"],
      "permitted_uses": ["s0", "s2_tiebreak"]
    }
  ]
}
```

The example is structural only. Its hash corresponds to a snapshot containing exactly the
shown synthetic quote plus one trailing newline. Do not create an Acme dossier or copy its
claim into any company dossier. Never include `expires_at`; Gemini computes it.

## Per-company evidence target

Aim for this useful but bounded dossier size:

- 3–6 official sources, including at least one official product/about source and one official engineering or careers source when available;
- 6–12 facts total;
- at least one `product`, `domain`, or `engineering_theme` fact from an official source;
- 3–6 tailoring signals;
- no more than 2 company-level `value` facts;
- `hiring_guidance` only when an official careers or official hiring-guide page states the guidance;
- `ats` only from the approved verified dataset and only as G3/preflight advisory context;
- scoped facts only when the source explicitly supports that business-unit or role-family scope.

Quality beats count. If a company lacks public engineering or hiring guidance, produce fewer supported facts and record the gap in the batch report; never pad the dossier with speculation.

## Signal-writing rules

Use the fact-kind policy mechanically:

| Basis fact | Allowed signal uses |
|---|---|
| `product`, `domain`, `engineering_theme` | `s0`, `s2_tiebreak` |
| `value` | `s0` |
| `hiring_guidance` | `s0`, `g3_advisory` |
| `ats` | `g3_advisory` |
| `identity`, `industry` | no signal; context fact only |

If a signal has multiple basis facts, its uses must be valid for every basis fact. Write signals as bounded instructions:

```text
S0 example: Frame supported candidate evidence around reliable data infrastructure.
S2 example: When JD coverage and claim safety are equal, prefer the supported bullet that demonstrates operating reliable data infrastructure.
G3 example: Check the official application guidance for required materials; do not change renderer or L7 rules.
```

These are synthetic wording examples, not facts about any seed company. Replace the subject
with the specific documented fact while retaining the same conditional boundaries.

Forbidden formulations include “the company loves,” “recruiters prefer,” “guarantees an interview,” “add this keyword,” and any unsupported statement about screening behavior.

---

### Task 1: Prepare the research workspace and validation loop

**Files:**
- Create only beneath: `data/company_research/inbox/`

- [ ] **Step 1: Read the controlling contracts**

Read `AGENTS.md`, the design spec, this plan, `config/company_bank/seed_companies.yaml`, and `config/company_bank/research_bundle.schema.json`. Confirm the foundation commit exists and the working tree has no unexpected production edits.

- [ ] **Step 2: Verify the offline validator before browsing**

Run:

```bash
.venv/bin/python -m scripts.company_bank --help
```

Expected: exit 0 with `validate-bundle` and `validate-corpus`. If absent, stop: Track A is incomplete.

- [ ] **Step 3: Use the same repeatable process for every company**

For each company:

1. Identify the official domains from an official corporate property.
2. Find official product/about, engineering, careers, and hiring-guide pages.
3. Open and read each page; never rely on the search snippet.
4. Select short exact evidence excerpts and save them in `sources/{source_id}.txt`.
5. Write facts that paraphrase only what the excerpts support.
6. Write bounded signals supported by fact ids and the permitted-use matrix.
7. Compute the real SHA-256 of each snapshot and put it in the source record.
8. Run the bundle validator and repair only the reported research artifact.

Compute a snapshot hash with:

```bash
shasum -a 256 data/company_research/inbox/{company_id}/sources/{source_id}.txt
```

Then validate with:

```bash
.venv/bin/python -m scripts.company_bank validate-bundle data/company_research/inbox/{company_id}/bundle.json
.venv/bin/python -m scripts.company_bank lint-snapshots data/company_research/inbox/{company_id}/bundle.json
```

Expected: `OK` and the company id, with zero lint findings. Do not edit validator code to make a bundle pass.
Running `verify-sources` per-batch is recommended.

---

### Task 2: Batch 1 — existing shortlist leaders

**Companies:** `palantir`, `cisco`, `notion`, `atos`, `bytedance`, `expedia`

- [ ] Research and validate Palantir.
- [ ] Research and validate Cisco.
- [ ] Research and validate Notion.
- [ ] Research and validate Atos.
- [ ] Research and validate ByteDance.
- [ ] Research and validate Expedia Group.
- [ ] Run `validate-bundle` and `lint-snapshots` for all six companies. (Recommended: run `verify-sources` for the batch).
- [ ] Report a six-row summary: company id, source count, fact count by kind, signal count, scopes, and evidence gaps. Stop for review if any company lacks an official product/domain/engineering fact.

Special caution: do not map TikTok to ByteDance as an alias. TikTok may appear only as an explicitly sourced product/business-unit scope. The same rule applies to Expedia Group: the employer is `Expedia Group`, and consumer brands such as Expedia, Hotels.com, and Vrbo are products, not employer aliases.

---

### Task 3: Batch 2 — remaining known targets and large platforms

**Companies:** `newsbreak`, `quantcast`, `google`, `microsoft`, `amazon`

- [ ] Research and validate NewsBreak.
- [ ] Research and validate Quantcast.
- [ ] Research and validate Google.
- [ ] Research and validate Microsoft.
- [ ] Research and validate Amazon.
- [ ] Re-run `validate-bundle` and `lint-snapshots` for all five (and optionally `verify-sources`), then report the same coverage table.

Special caution: keep Alphabet, Azure, AWS, and Amazon.com distinctions scoped; do not silently turn parent companies, products, or business units into aliases.

---

### Task 4: Batch 3 — consumer/platform companies

**Companies:** `meta`, `apple`, `nvidia`, `netflix`, `linkedin`

- [ ] Research and validate Meta.
- [ ] Research and validate Apple.
- [ ] Research and validate NVIDIA.
- [ ] Research and validate Netflix.
- [ ] Research and validate LinkedIn.
- [ ] Re-run `validate-bundle` and `lint-snapshots` for all five (and optionally `verify-sources`), then report the same coverage table.

Special caution: do not scrape LinkedIn pages requiring login or member/job-search surfaces. Use official public corporate, engineering, careers, and candidate-guidance pages only.

---

### Task 5: Batch 4 — data, infrastructure, and marketplace targets

**Companies:** `uber`, `airbnb`, `stripe`, `databricks`, `snowflake`

- [ ] Research and validate Uber.
- [ ] Research and validate Airbnb.
- [ ] Research and validate Stripe.
- [ ] Research and validate Databricks.
- [ ] Research and validate Snowflake.
- [ ] Re-run `validate-bundle` and `lint-snapshots` for all five (and optionally `verify-sources`), then report the same coverage table.

Special caution: engineering-blog posts about one system support that system/theme, not a universal hiring preference. Scope narrowly when appropriate.

---

### Task 6: Batch 5 — developer infrastructure and consumer platforms

**Companies:** `cloudflare`, `mongodb`, `datadog`, `doordash`, `roblox`

- [ ] Research and validate Cloudflare.
- [ ] Research and validate MongoDB.
- [ ] Research and validate Datadog.
- [ ] Research and validate DoorDash.
- [ ] Research and validate Roblox.
- [ ] Re-run `validate-bundle` and `lint-snapshots` for all five (and optionally `verify-sources`), then report the same coverage table.

Special caution: distinguish MongoDB the company from MongoDB the product through scopes and claims; do not treat the product name as a separate employer alias.

---

### Task 7: Batch 6 — enterprise and fintech targets

**Companies:** `capital_one`, `salesforce`, `rippling`, `plaid`, `ramp`

- [ ] Research and validate Capital One.
- [ ] Research and validate Salesforce.
- [ ] Research and validate Rippling.
- [ ] Research and validate Plaid.
- [ ] Research and validate Ramp.
- [ ] Re-run `validate-bundle` and `lint-snapshots` for all five (and optionally `verify-sources`), then report the same coverage table.

Special caution: fintech product/domain facts do not imply quantitative-finance roles. Keep banking, payments, HR/payroll, and spend-management claims precise.

---

### Task 8: Complete-corpus research handoff

**Files:**
- Read only: all 31 bundle directories
- Create only: `data/company_research/inbox/research_summary.json`

- [ ] **Step 1: Validate the entire seed corpus offline**

Run:

```bash
.venv/bin/python -m scripts.company_bank validate-corpus \
  --inbox data/company_research/inbox \
  --seeds config/company_bank/seed_companies.yaml
```

Expected: `OK`, exactly 31 companies, zero missing ids, zero unexpected ids, zero invalid bundles. If it fails, fix research artifacts only and rerun.

- [ ] **Step 2: Write the ignored research summary**

Create `research_summary.json` with `schema_version` equal to `0.1.0`, `company_count` equal
to integer `31`, and `company_ids` equal to this exact seed-file order:

```text
palantir, cisco, notion, atos, bytedance, newsbreak, quantcast, google,
microsoft, amazon, meta, apple, nvidia, netflix, linkedin, uber, airbnb,
stripe, databricks, snowflake, cloudflare, mongodb, datadog, doordash,
roblox, capital_one, salesforce, rippling, plaid, ramp, expedia
```

Set `validated_at` to the actual UTC time of the successful corpus-validation command,
formatted with a trailing `Z`. Set `validation_command` to the exact command from Step 1.
Set `gaps` to an array of concrete evidence-limit strings; use an empty array only when no
limitations remain. This summary is an operator handoff, not importer input.

- [ ] **Step 3: Stop without importing or committing**

Report:

- exact 31/31 validation result;
- total source, fact, and signal counts;
- per-company coverage table;
- every remaining evidence gap;
- confirmation that production code, canonical YAML, SQLite, and Git history were untouched.

Do not run `import-corpus`. Track C belongs to Gemini in a fresh milestone/session.
