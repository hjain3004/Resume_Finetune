# LLM-First Tailoring Lane (Tailor2) — Design Specification

**Date:** 2026-09-17  
**Status:** DRAFT / PENDING REVIEW  
**Package:** `src/tailor2/`  
**CLI:** `scripts/tailor2.py`  
**Related Docs:** `docs/ARCHITECTURE.md`, `docs/TAILORING_METHODOLOGY.md`, `docs/DECISIONS.md`, `config/taste.md`, `config/master_profile.yaml`

---

## 1. Problem Statement & Motivation

The existing Apply-Now lane (`scripts/tailor_now.py`, composing S1 → S0 → S2 → S3 → G1 → G2 → Render/L7 → G3) is structurally incapable of producing the required résumé quality:
1. **Keyword-Placement Constraint:** S3 requires the "smallest possible terminology substitution," bans broader rephrasing, and treats tailoring primarily as an atomic keyword insertion exercise.
2. **Artificial Phrasing Shackles:** Adding STAR/Google XYZ guidelines to `config/taste.md` does not overcome S3's low edit-distance budget (<= 15%) and strict unedited canonical token preservation.
3. **Mechanical vs. Strategic Alignment:** Rather than generating coherent, impactful, accomplishment-driven sentences from real evidence, the legacy pipeline patches existing text fragments.

This design introduces **Tailor2**: a separate, LLM-first tailoring lane that creates complete, high-impact, single-sentence STAR/XYZ bullets from verified candidate evidence while preserving strict factual grounding through an adversarial, independent multi-stage audit.

The legacy lane (`src/tailor/`, `scripts/tailor_now.py`) remains completely untouched as an available legacy path.

---

## 2. Core Architecture & Workflow

Tailor2 is organized around an explicit, bounded 4-stage model workflow with strict information isolation:

```
                  ┌─────────────────────────────────┐
                  │      Input Job Description      │
                  │   + Company, Title, Variant     │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │        1. DRAFT STAGE         │
                   │   (LLM Call 1: Generator)     │
                   └───────────────┬───────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │  Deterministic Draft Gate     │
                   │  - exact quote verification   │
                   │  - profile ID resolution      │
                   │  - numeric token subset check │
                   │  - 7 Amdocs accounting check  │
                   │  - no "Kubernetes" / forbidden│
                   │  - section & layout bounds    │
                   └───────────────┬───────────────┘
                                   │ (Fails closed on violation)
                                   ▼
                   ┌───────────────────────────────┐
                   │    2. INDEPENDENT AUDIT       │
                   │     (LLM Call 2: Auditor)     │
                   │  * Sees ONLY JD, bullets, and │
                   │    cited evidence.            │
                   │  * NO drafter CoT or reasoning│
                   └───────────────┬───────────────┘
                                   │
                     Is overall verdict == PASS?
                    /                           \
                  YES                            NO (≥1 rejected bullet)
                  /                                \
                 │                        ┌─────────┴─────────┐
                 │                        │ 3. REPAIR STAGE   │
                 │                        │ (LLM Call 3)      │
                 │                        │ * Sees ONLY the   │
                 │                        │   rejected bullets│
                 │                        │   + cited evidence│
                 │                        │   + audit findings│
                 │                        └─────────┬─────────┘
                 │                                  │
                 │                        ┌─────────┴─────────┐
                 │                        │ Deterministic     │
                 │                        │ Repair Gate       │
                 │                        └─────────┬─────────┘
                 │                                  │
                 │                        ┌─────────┴─────────┐
                 │                        │ 4. RE-AUDIT STAGE │
                 │                        │ (LLM Call 4)      │
                 │                        │ * Evaluates ONLY  │
                 │                        │   repaired bullets│
                 │                        └─────────┬─────────┘
                 │                                  │
                 │                       All repaired ACCEPT?
                 │                      /                    \
                 │                    YES                     NO
                 │                    /                        \
                 ▼                   ▼                          ▼
        ┌────────────────────────────────┐            ┌──────────────────┐
        │       5. RENDER & L7 GATE      │            │   FAIL CLOSED    │
        │ - RenderDoc mapping            │            │ - No retry loop  │
        │ - LaTeX compilation (pdflatex) │            │ - Unaudited text │
        │ - L7 validation                │            │   never rendered │
        │ - 1-page budget check          │            └──────────────────┘
        └────────────────┬───────────────┘
                         │
                         ▼
        ┌────────────────────────────────┐
        │  6. ATOMIC ARTIFACT PUBLISH    │
        │ - resume.tex & resume.pdf      │
        │ - draft.json & audit.json      │
        │ - repair.json & re_audit.json  │
        │ - run_manifest.json            │
        │ - I11 audit traces             │
        └────────────────────────────────┘
```

### Call Budget Invariants:
- **Normal execution:** Exactly 2 calls (Draft, Audit).
- **Repair execution:** Exactly 4 calls (Draft, Audit, Repair, Re-Audit).
- **Hard upper bound:** 4 model calls maximum per run.
- **Zero automated retries:** No retry loop upon re-audit failure.
- **Zero unaudited text:** A repaired bullet is never rendered without re-audit acceptance.

---

## 3. Information Boundaries & Role Separation

1. **Draft Stage (Generator):**
   - Receives: Raw JD, full evidence catalog from `master_profile.yaml` (bullet IDs, canonical texts, interview evidence, tags, approved metrics), variant blueprint layout, writing style rules (`taste.md`).
   - Produces: Atomic JD requirements with verbatim quotes, selected evidence IDs, Amdocs omission ledger, ordered sections and bullets.
2. **Audit Stage (Independent Critic):**
   - Receives: Raw JD, drafted bullets (final text, bullet_id, entry_id, section), and the cited evidence item(s) behind each bullet.
   - **MUST NOT RECEIVE:** Drafter chain-of-thought, internal strategy, or persuasive rationale. Evaluates text objectively against evidence.
3. **Repair Stage (Targeted Fixer):**
   - Receives: ONLY the bullets rejected by the auditor, their cited evidence, and the specific audit findings/critiques.
   - Produces: Corrected bullet text for rejected bullets only.
4. **Re-Audit Stage (Verification Critic):**
   - Receives: ONLY the repaired bullets, their cited evidence, and the JD.
   - Applies the same 9-dimension audit rubric.

---

## 4. Writing Quality & Editorial Rules

Every generated bullet must strictly comply with the following standards:

1. **Sentence Structure:**
   - Exactly one continuous, coherent sentence.
   - Zero colon-led fragments (e.g. `Feature X: built Y`).
   - Zero semicolon chains (`Built X; used Y; improved Z`).
   - Zero architecture dumps or technology laundry lists.
2. **Framing & Cadence:**
   - Compressed STAR or Google XYZ format ("Accomplished [X], measured by [Y], by doing [Z]").
   - Result-first construction whenever a measurable or qualitative outcome exists.
   - Explain what was built, how it operated, and why it mattered.
   - Avoid generic AI phrasing ("spearheaded", "cutting-edge", "pivotal", "revolutionized", "meticulous").
   - Avoid unsupported superlatives.
3. **Technical Rigor & Guarantees:**
   - Preserve exact technical guarantees (e.g. idempotent processing vs. exactly-once, append-only ledger vs. immutable).
   - Preserve numeric tokens exactly as recorded in cited evidence, unless authorized by `~` approximation.
   - **`Kubernetes` is strictly forbidden:** never render `Kubernetes` in bullets, skills, or headings.
4. **Amdocs Accounting:**
   - Amdocs (~2 years) is the professional backbone of backend, e-commerce, and distributed systems profiles.
   - All 7 canonical Amdocs bullets:
     - `am_b00_order_management_domain`
     - `am_b01_dlq_consolidation`
     - `am_b02_row_level_entitlement`
     - `am_b03_audit_trail`
     - `am_b04_data_retention`
     - `am_b05_test_automation`
     - `am_b07_code_quality_gates`
   - Must either be present in the drafted bullets or explicitly listed in the structured omission ledger with category (`relevance` or `space`) and justification.
5. **Team Ownership:**
   - Team-produced systems are valid evidence. Bullets must not be blocked merely because granular commit-level ownership is unavailable.

---

## 5. Model Contracts (Exact JSON Schemas)

### 5.1 Draft Response Contract
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [
    "atomic_requirements",
    "selected_evidence_ids",
    "amdocs_omission_ledger",
    "section_order",
    "bullets"
  ],
  "properties": {
    "atomic_requirements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "term", "quote", "importance"],
        "properties": {
          "id": { "type": "string" },
          "term": { "type": "string" },
          "quote": { "type": "string" },
          "importance": { "type": "string", "enum": ["must_have", "nice_to_have"] }
        }
      }
    },
    "selected_evidence_ids": {
      "type": "array",
      "items": { "type": "string" }
    },
    "amdocs_omission_ledger": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["evidence_id", "category", "reason"],
        "properties": {
          "evidence_id": { "type": "string" },
          "category": { "type": "string", "enum": ["relevance", "space"] },
          "reason": { "type": "string" }
        }
      }
    },
    "section_order": {
      "type": "array",
      "items": { "type": "string" }
    },
    "bullets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "bullet_id",
          "evidence_ids",
          "supported_requirement_ids",
          "section",
          "entry_id",
          "text"
        ],
        "properties": {
          "bullet_id": { "type": "string" },
          "evidence_ids": { "type": "array", "items": { "type": "string" } },
          "supported_requirement_ids": { "type": "array", "items": { "type": "string" } },
          "section": { "type": "string", "enum": ["Experience", "Projects"] },
          "entry_id": { "type": "string" },
          "text": { "type": "string" }
        }
      }
    }
  }
}
```

### 5.2 Independent Audit Request Contract
```json
{
  "jd_text": "<raw job description text>",
  "bullets": [
    {
      "bullet_id": "b01",
      "section": "Experience",
      "entry_id": "bank_integration_internship",
      "text": "Architected an anti-corruption layer integrating legacy core banking systems with modern payment rails, handling 15,000 daily transactions with 99.9% uptime.",
      "cited_evidence": [
        {
          "id": "int_b1",
          "canonical_text": "...",
          "evidence": "...",
          "approved_metrics": ["15,000", "99.9%"],
          "technical_guarantees": ["..."]
        }
      ]
    }
  ]
}
```

### 5.3 Independent Audit Response Contract
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["evaluations", "overall_verdict"],
  "properties": {
    "evaluations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["bullet_id", "dimensions", "verdict", "rejection_reasons"],
        "properties": {
          "bullet_id": { "type": "string" },
          "dimensions": {
            "type": "object",
            "required": [
              "factual_fidelity",
              "metric_fidelity",
              "technology_fidelity",
              "technical_guarantee_fidelity",
              "relevance",
              "star_xyz_coherence",
              "readability",
              "recruiter_scan_quality",
              "ai_slop_risk"
            ],
            "properties": {
              "factual_fidelity": { "$ref": "#/definitions/dimension" },
              "metric_fidelity": { "$ref": "#/definitions/dimension" },
              "technology_fidelity": { "$ref": "#/definitions/dimension" },
              "technical_guarantee_fidelity": { "$ref": "#/definitions/dimension" },
              "relevance": { "$ref": "#/definitions/dimension" },
              "star_xyz_coherence": { "$ref": "#/definitions/dimension" },
              "readability": { "$ref": "#/definitions/dimension" },
              "recruiter_scan_quality": { "$ref": "#/definitions/dimension" },
              "ai_slop_risk": { "$ref": "#/definitions/dimension" }
            }
          },
          "verdict": { "type": "string", "enum": ["ACCEPT", "REJECT"] },
          "rejection_reasons": {
            "type": "array",
            "items": { "type": "string" }
          }
        }
      }
    },
    "overall_verdict": { "type": "string", "enum": ["PASS", "REPAIR_REQUIRED"] }
  },
  "definitions": {
    "dimension": {
      "type": "object",
      "required": ["score", "findings"],
      "properties": {
        "score": { "type": "integer", "enum": [1, 2, 3] },
        "findings": { "type": "string" }
      }
    }
  }
}
```

### 5.4 Repair Request Contract
```json
{
  "rejected_bullets": [
    {
      "bullet_id": "b05",
      "section": "Experience",
      "entry_id": "amdocs_software_developer",
      "text": "Revolutionized database operations through cutting-edge mechanisms.",
      "cited_evidence": [
        {
          "id": "am_b04_data_retention",
          "canonical_text": "...",
          "evidence": "...",
          "approved_metrics": ["40%"],
          "technical_guarantees": ["..."]
        }
      ],
      "audit_findings": [
        {
          "dimension": "ai_slop_risk",
          "score": 1,
          "findings": "Contains buzzwords without concrete mechanism."
        }
      ]
    }
  ]
}
```

### 5.5 Repair Response Contract
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["repaired_bullets"],
  "properties": {
    "repaired_bullets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["bullet_id", "text"],
        "properties": {
          "bullet_id": { "type": "string" },
          "text": { "type": "string" }
        }
      }
    }
  }
}
```

### 5.6 Re-Audit Request & Response Contracts
- Re-audit request takes `{ "jd_text": "...", "repaired_bullets": [...] }` formatted identically to 5.2 for the subset of repaired bullets.
- Re-audit response format is identical to 5.3.

---

## 6. Deterministic Validation Invariants

Deterministic code enforces **only** objectively falsifiable properties:
1. **Schema & Field Types:** Validated strictly against dataclasses and JSON types.
2. **Requirement IDs:** Unique across `atomic_requirements`.
3. **Exact Substring Quotes:** Every `quote` in `atomic_requirements` is verified to be an exact substring of the provided JD (`quote in jd_text`).
4. **Evidence ID Resolution:** Every evidence ID in `selected_evidence_ids` and `bullets[].evidence_ids` must resolve to an existing bullet in `config/master_profile.yaml`.
5. **Numeric Token Fidelity:** Every numeric token (extracted via `r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)"`) in a drafted bullet must exist in its cited evidence, allowing `~` approximations (e.g. `~40%` matches `40%`). Invented metrics fail immediately.
6. **Prohibited Terms & Do Not Claim:** Zero occurrences of `Kubernetes` or any term from `master_profile.yaml` `do_not_claim` (case-insensitive word boundary).
7. **No Duplicates:** Zero duplicate bullet IDs and zero duplicate bullet texts.
8. **Section & Layout Bounds:**
   - Section proportion invariants from `config/taste.md`:
     - Amdocs carries the most bullets of any entry.
     - `bank_integration_internship` (MalyTech) is capped at 3 bullets.
     - Total bullet count adheres to the one-page budget (15 bullets for backend, 16 for ml).
9. **Amdocs Accounting:** Every one of the 7 canonical Amdocs bullet IDs must appear either in `bullets` or in `amdocs_omission_ledger` with category (`relevance` | `space`) and reason.
10. **LaTeX Compilation & One-Page L7:** Must compile via `pdflatex` to 1 page, pass `run_l7_tailored`, and generate zero bleed.

*Heuristic properties (STAR quality, AI-slop risk, relevance, scan quality) are NOT judged by regexes; they belong exclusively to the independent audit model.*

---

## 7. Infrastructure Reuse vs. Isolation Boundary

| Component | Status | Source / Rule |
|---|---|---|
| Master Profile Loader | Reused | `src.profile.load_profile` |
| Renderer & L7 Gate | Reused | `src.render.model.RenderDoc`, `src.render.latex`, `src.render.tailored` |
| Atomic Artifact Writing | Reused | `src.tailor.artifacts.write_json_atomic` |
| LLM Tracing (I11) | Reused | `src.llm_trace.write_trace` |
| Provider Boundary | Reused / Hardened | `src.tailor.invoke.invoke_model`, `src.tailor.providers.build_model_command` |
| S0/S1/S2/S3/G1/G2 Orchestration | **REJECTED** | Zero reuse. Tailor2 has its own isolated pipeline. |
| Keyword-Placement Rules | **REJECTED** | Edit distance and mechanical keyword bounds are eliminated. |
| Ingestion & Scoring Pipeline | **UNTOUCHED** | Zero changes to `src/run_ingest.py`, `src/db.py`, etc. |

---

## 8. Provider Behavior & Safety Rules

1. **Explicit Provider & Model Required:**
   - Live runs must specify both `--provider {claude,openai,gemini}` and `--model <name>`.
   - Defaulting silently to `gpt-4o-mini` or `gemini-2.5-flash` is strictly forbidden.
2. **Tool-Free Pure Text-In / Text-Out:**
   - Claude runs with `--strict-mcp-config` and `--tools ""`.
   - OpenAI & Gemini invoke direct HTTP REST endpoints via `requests`.
   - Zero tool definitions, zero filesystem authority, zero database access.
3. **Credential Protection:**
   - API keys are passed strictly via HTTP request headers.
   - Keys are never logged, persisted, or stored in traces.
