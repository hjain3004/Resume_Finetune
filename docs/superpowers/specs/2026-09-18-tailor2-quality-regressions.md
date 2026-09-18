# Tailor2 Quality Regression Corpus & Acceptance Specification

**Date:** 2026-09-18  
**Status:** Approved Specification  
**Branch:** `feat/tailor2-regression-corpus`  
**Target Subsystems:** `tests/fixtures/tailor2/quality_regressions/`, `tests/tailor2/test_quality_regression_fixtures.py`, `shortlist/tailoring_targets/`

---

## 1. Executive Summary & Context

The Tailor2 pipeline provides an LLM-first résumé-tailoring lane combining multi-stage LLM generation (drafting, auditing, repairing) with strict deterministic boundaries. During the manual tailoring exercise for the **OpenAI Software Engineer (Applied Emerging Talent)** requisition (Job ID 4949, commit `a4dd50b`), real failure modes were encountered across four revision cycles:
1. **Revision 1–2:** Transition from feature inventory to engineering outcomes; balancing whitespace and technical depth; handling estimated vs verified metrics.
2. **Revision 3:** Density maximization leading to visual crowding, bullet wrapping mid-line, rejected candidate bullets (`rft_b12_audit_framework`) causing heading collision, and employer title alteration risks (`Software Developer` vs `Software Engineer`).
3. **Revision 4:** Reader-reported legibility failure ("format become a little messed up. spacing and all is really less between lines"), requiring spacing restoration, bullet reduction from 18 to 16, and explicit trade-off governance.

In parallel with Claude's production-code hardening (`quality-core`), this specification defines a **deterministic, offline regression corpus of 26 core failure scenarios (52 paired negative and positive fixtures)**, an **OpenAI acceptance manifest**, and **fixture-integrity acceptance test scaffolding**.

This corpus bridges the gap between raw LLM drafting and production-grade résumé quality without relying on live LLM calls, nondeterministic APIs, or sensitive contact PII.

---

## 2. Scope & Boundaries

### 2.1 File Ownership
- **Corpus Scaffolding (This Workstream):**
  - `docs/superpowers/specs/2026-09-18-tailor2-quality-regressions.md` (this document)
  - `tests/fixtures/tailor2/quality_regressions/cases.json` (26 negative + 26 positive paired fixtures)
  - `tests/fixtures/tailor2/quality_regressions/openai_acceptance_manifest.json` (OpenAI acceptance criteria)
  - `tests/fixtures/tailor2/quality_regressions/canonical_evidence_catalog.json` (sanitized 70-bullet evidence baseline)
  - `tests/tailor2/test_quality_regression_fixtures.py` (integrity test suite + strict xfail acceptance scaffolding)
  - `shortlist/tailoring_targets/**` (Top-10 targets and selection audit)
- **Production Code (Claude's Parallel Workstream):**
  - `src/tailor2/**`
  - `scripts/tailor2.py`
  - Production prompts and production validators.
  - `main` branch.

### 2.2 Invariants
1. **Zero Live LLM Calls:** All fixtures are static JSON and all tests execute in sub-second offline suites.
2. **Zero Contact PII:** Phone numbers, personal email addresses, physical addresses, and candidate links are strictly excluded from regression fixtures.
3. **Strict Fact Preservation:** Negative and positive pairs must preserve identical underlying canonical facts; positive repairs cannot invent metrics, technologies, or achievements.
4. **Deterministic Resolution:** Every evidence ID in the corpus must resolve against the inspected canonical profile (`origin/resume/openai-4949-manual:config/master_profile.yaml`).

---

## 3. Fixture Schema Specification

Every quality regression case in `tests/fixtures/tailor2/quality_regressions/cases.json` conforms to the following schema:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Tailor2QualityRegressionCase",
  "type": "object",
  "required": [
    "case_id",
    "pair_id",
    "variant",
    "category",
    "target_role",
    "description",
    "is_synthetic",
    "resume_fragment",
    "canonical_evidence_ids",
    "canonical_facts",
    "expected_result",
    "expected_blocking_dimensions",
    "forbidden_inferences",
    "required_reviewer_observations",
    "acceptable_repair_properties",
    "unacceptable_repair_properties"
  ],
  "properties": {
    "case_id": {
      "type": "string",
      "description": "Unique stable identifier for the test case, suffixed with _neg or _pos."
    },
    "pair_id": {
      "type": "string",
      "description": "Shared identifier linking negative and positive fixture pairs."
    },
    "variant": {
      "type": "string",
      "enum": ["negative", "positive"],
      "description": "Whether this case represents a failing draft (negative) or valid repair (positive)."
    },
    "category": {
      "type": "string",
      "description": "Taxonomic category of the failure mode."
    },
    "target_role": {
      "type": "string",
      "description": "Target job requisition and company context."
    },
    "description": {
      "type": "string",
      "description": "Human-readable summary of the test scenario."
    },
    "is_synthetic": {
      "type": "boolean",
      "description": "False if evidence IDs resolve to master_profile.yaml; True only for standalone unit tests."
    },
    "resume_fragment": {
      "type": "string",
      "description": "The exact bullet, header, section, or audit excerpt under test."
    },
    "canonical_evidence_ids": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of bullet IDs from master_profile.yaml that ground this claim."
    },
    "canonical_facts": {
      "type": "array",
      "items": { "type": "string" },
      "description": "The immutable factual ground truth that must be preserved."
    },
    "expected_result": {
      "type": "string",
      "enum": ["ACCEPT", "REJECT"],
      "description": "The expected verdict: REJECT for negative, ACCEPT for positive."
    },
    "expected_blocking_dimensions": {
      "type": "array",
      "items": { "type": "string" },
      "description": "The quality or audit dimensions expected to block the negative case (empty for positive)."
    },
    "forbidden_inferences": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Inferences that an auditor, parser, or human reader must not make."
    },
    "required_reviewer_observations": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Observations that must be noted during auditing or review."
    },
    "acceptable_repair_properties": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Properties that a compliant repair must exhibit."
    },
    "unacceptable_repair_properties": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Modifications that constitute unacceptable repairs (e.g. hallucinating metrics)."
    }
  }
}
```

---

## 4. The 26 Quality Regression Taxonomy

The 26 scenarios are categorized across 20 distinct dimensions reflecting the end-to-end recruitment lifecycle:

| Case ID | Category | Core Defect / Invariant Tested |
|---|---|---|
| `reg_01` | `engineering_substance` | Feature catalogue vs. engineering result in ResumeFinetune. |
| `reg_02` | `tech_stack_positioning` | Auxiliary tools (SQLite, Pytest) dominating project tech header. |
| `reg_03` | `skills_taxonomy` | Demonstrated Agentic AI evidence omitted from Skills despite JD emphasis. |
| `reg_04` | `semantic_equivalence` | `Postgres` and `PostgreSQL` treated as distinct, un-matching technologies. |
| `reg_05` | `claim_credibility` | AI/ML interest evidence overstated as foundational AI research. |
| `reg_06` | `eligibility_parsing` | "Bachelor's degree or equivalent practical experience" split into conflicting mandatory requirements. |
| `reg_07` | `project_selection` | Spurious positioning rationale (e.g. Sepsis ICU model linked to consumer chat). |
| `reg_08` | `page_budget` | Seven long Amdocs experience bullets causing excessive vertical density. |
| `reg_09` | `layout_integrity` | Project technology header string width colliding with date column in LaTeX. |
| `reg_10` | `visual_hygiene` | Excessive bold spans (>3 per bullet) creating visual noise. |
| `reg_11` | `audit_integrity` | Same model drafting and rubber-stamping output without disclosing self-review stance. |
| `reg_12` | `visual_scannability` | Technically 1-page résumé rendered with cramped, unreadable spacing. |
| `reg_13` | `information_hierarchy` | Strong role evidence buried below older undergraduate course projects. |
| `reg_14` | `prose_quality` | Repaired bullet fixing numbers but retaining AI slop buzzwords. |
| `reg_15` | `title_fidelity` | Altering Amdocs historical title from `Software Developer` to `Software Engineer`. |
| `reg_16` | `metric_interpretability` | "Mean LLM scoring movement" used without scale, baseline, or direction. |
| `reg_17` | `claim_credibility` | Multi-pass LLM score stability presented as model accuracy. |
| `reg_18` | `provenance_transparency` | Fake-review metrics presented without dataset or reviewer-disjoint split provenance. |
| `reg_19` | `engineering_substance` | Project bullet listing mechanisms without demonstrated behavioral outcome. |
| `reg_20` | `vocabulary_discipline` | Repeated "agentic," "orchestration," and "validation" buzzword loops. |
| `reg_21` | `skills_taxonomy` | Unsupported terms (Kubernetes, GraphQL) added to Skills solely for ATS padding. |
| `reg_22` | `metric_interpretability` | Suspiciously clean rounded percentages (+50%, +80%) without measurement context. |
| `reg_23` | `positioning_integrity` | Positioning backend candidate as frontend product engineer without product evidence. |
| `reg_24` | `page_budget` | Usable blank space (4+ inches) remaining while strong verified evidence is omitted. |
| `reg_25` | `repair_fidelity` | Repair deleting a verified metric/mechanism to satisfy line length constraints. |
| `reg_26` | `audit_integrity` | Reviewer claiming "independent model review" when single model executed both stages. |

---

## 5. Paired Negative-Positive Design Methodology

Every negative fixture (`_neg`) represents a concrete drafting or evaluation defect. For each negative fixture, a paired positive fixture (`_pos`) is constructed adhering to the following rules:
1. **Fact Symmetry:** `canonical_facts` and `canonical_evidence_ids` are strictly identical between pairs.
2. **Metric Integrity:** Positive repairs do not change numeric figures unless explicitly resolving an unanchored metric with profile-grounded baseline context.
3. **No Hallucination:** Positive repairs use only technologies and accomplishments established in `config/master_profile.yaml`.
4. **Defensible Verification:** Positive fixtures demonstrate that the underlying engineering achievement can be expressed cleanly and persuasively while passing all audit dimensions.

---

## 6. OpenAI Applied Emerging Talent Acceptance Manifest

The manifest `tests/fixtures/tailor2/quality_regressions/openai_acceptance_manifest.json` provides a machine-readable specification of all acceptance criteria established during the manual OpenAI application effort:
- **Canonical Target:** Requisition 4949 (`Software Engineer - Applied Emerging Talent`, SF, Ashby ATS).
- **Employer Title Fidelity:**
  - Amdocs: Canonical `Software Developer`. Alteration to `Software Engineer` is classified as résumé fraud and strictly prohibited.
  - MalyTech: Canonical `Software Engineering Intern`.
- **Semantic Equivalences:**
  - `PostgreSQL` $\equiv$ `Postgres` $\equiv$ `Postgres DB` $\equiv$ `PostgreSQL DB`
  - `React` $\equiv$ `React.js` $\equiv$ `ReactJS`
  - `AsyncIO` $\equiv$ `asyncio`
  - `Apache Kafka` $\equiv$ `Kafka`
  - `FastAPI` $\equiv$ `FastAPI microservices`
- **Protected Metrics:** Exact verification of tokens: `862` topics, `~70%` sprawl, `~40%` storage, `~500` tests, `4` adapters, `5` services, `8` concurrent into 1, `608K` reviews, `260K/5K` profiles, `423K` reviews, `0.93` ROC-AUC, `0.84` macro-F1, `2.4 to 0.6` scoring variance.
- **Project Configuration:**
  - Included: `resume_finetune_pipeline` (lead, 4 bullets), `fake_review_detection` (2 bullets), `peerchat_peer_discovery` (2 bullets).
  - Excluded: `campus_marketplace` (superseded), `sepsis_early_warning` (domain mismatch), `clinical_trial_platform` (domain mismatch).
- **Page Budget & Typography:** 1 page, 16–17 bullets target (hard max 18), 11pt font (10pt floor), 0.30in margins, $\ge 1.5$cm horizontal clearance for date headers.
- **Evidence Gaps:** Explicit acknowledgment of customer-facing UX gap; candidate positioned as product-adjacent backend systems engineer.

---

## 7. Scaffolding & Integration with Claude's Parallel Work

Claude's parallel workstream (`quality-core`) is actively implementing the production validators and prompt engineering to enforce these criteria.

To support this parallel workflow without breaking CI or asserting premature capabilities:
- **Fixture Integrity Tests:** Verify schema, evidence ID resolution, pair symmetry, non-hallucination, absence of PII, manifest references, and Top-10 exporter determinism. **These must pass 100% normally.**
- **Integration Acceptance Scaffolding:** Acceptance tests that assert production validation behavior not yet implemented in `src/tailor2/` are decorated with:
  ```python
  @pytest.mark.xfail(strict=True, reason="pending quality-core merge")
  ```
  This guarantees that:
  1. Tests fail as expected today without breaking CI.
  2. If an un-implemented feature is accidentally passed or merged, `strict=True` triggers an `XPASS` error, enforcing rigorous validation.
  3. When Claude completes `quality-core`, the xfail markers can be cleanly transitioned to standard passing assertions.
