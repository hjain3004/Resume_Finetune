"""Prompt generation for the LLM-first tailoring lane (Tailor2).

Strict role separation & information isolation:
- Generator receives JD, MasterProfile evidence catalog, and taste/blueprint rules.
- Independent Auditor receives ONLY JD, final drafted bullets, and cited evidence. Zero drafter CoT.
- Repair receives ONLY rejected bullets, their cited evidence, and the audit findings.
- Re-Audit receives ONLY repaired bullets, their cited evidence, and the JD.
"""

from __future__ import annotations

import json
from typing import Any

from src.profile import MasterProfile
from src.tailor2.models import (
    DraftBullet,
    RepairedBullet,
)
from src.tailor2.validators import CANONICAL_AMDOCS_BULLETS


def _format_evidence_catalog(profile: MasterProfile) -> str:
    lines = []
    lines.append("### Professional Experience")
    for exp in profile.experience:
        lines.append(f"\n#### Employer: {exp.employer} (id: `{exp.id}`, title: `{exp.title}`)")
        for b in exp.bullets:
            phrasings_str = f"Short: {b.phrasings.short}\nMedium: {b.phrasings.medium}\nLong: {b.phrasings.long}"
            ev_str = "; ".join(b.evidence) if isinstance(b.evidence, (list, tuple)) else str(b.evidence)
            lines.append(
                f"- Bullet ID: `{b.id}` (claim_type: {b.claim_type.value})\n"
                f"  Phrasings:\n{phrasings_str}\n"
                f"  Evidence: {ev_str}\n"
                f"  Defense: {b.defense or 'N/A'}"
            )

    lines.append("\n### Technical Projects")
    for proj in profile.projects:
        lines.append(f"\n#### Project: {proj.name} (id: `{proj.id}`)")
        lines.append(f"Tech stack line: {proj.tech_line}")
        for b in proj.bullets:
            phrasings_str = f"Short: {b.phrasings.short}\nMedium: {b.phrasings.medium}\nLong: {b.phrasings.long}"
            ev_str = "; ".join(b.evidence) if isinstance(b.evidence, (list, tuple)) else str(b.evidence)
            lines.append(
                f"- Bullet ID: `{b.id}` (claim_type: {b.claim_type.value})\n"
                f"  Phrasings:\n{phrasings_str}\n"
                f"  Evidence: {ev_str}\n"
                f"  Defense: {b.defense or 'N/A'}"
            )
    return "\n".join(lines)


def build_draft_prompt(
    jd_text: str,
    profile: MasterProfile,
    base_variant: str,
    company: str,
    title: str,
) -> str:
    """Construct prompt for the draft generation stage."""
    canonical_amdocs_str = ", ".join(f"`{bid}`" for bid in CANONICAL_AMDOCS_BULLETS)
    catalog_str = _format_evidence_catalog(profile)

    return f"""You are an expert technical résumé drafter. Your task is to draft a world-class, tailored, one-page software engineering résumé for the following target role using ONLY the candidate's real, verified evidence from their master profile.

## Target Position
- Company: {company}
- Title: {title}
- Base Profile Variant: {base_variant}

## Job Description
```text
{jd_text}
```

## Candidate Master Profile Evidence Catalog
{catalog_str}

## Mandatory Writing-Quality Requirements
1. **Sentence Structure:**
   - Every bullet MUST be exactly ONE coherent, continuous sentence.
   - Follow compressed STAR or Google XYZ structure ("Accomplished [X], measured by [Y], by doing [Z]").
   - Prefer result-first construction whenever a measurable or qualitative result exists.
   - Explain what was built, how it worked, and why it mattered.
   - NO colon-led fragments (e.g. `Feature X: built Y`).
   - NO semicolon chains (`Built X; used Y; improved Z`).
   - NO architecture dumps, keyword inventories, or technology laundry lists disguised as bullets.
   - NO generic AI résumé phrasing ("spearheaded", "cutting-edge", "pivotal", "revolutionized", "meticulous").
   - NO unsupported superlatives.
2. **Factual Rigor & Guarantees:**
   - Preserve exact technical guarantees (e.g. idempotent processing rather than exactly-once; append-only rather than immutable).
   - Preserve all numeric claims exactly as stated in the evidence, unless an approximation with `~` is used (e.g. `~40%`, `~500`). NEVER invent a metric or number.
   - **Never render `Kubernetes`**: It is strictly forbidden from candidate skills, keyword lists, and rendered bullets.
   - Team-produced systems are valid evidence. Describe accomplishments accurately.
3. **Amdocs Accounting:**
   - Amdocs (~2 years) is the professional backbone of backend, e-commerce, and distributed systems profiles.
   - All seven canonical Amdocs bullets: {canonical_amdocs_str} MUST be either:
     a) included in the draft, OR
     b) listed in `amdocs_omission_ledger` with a specific relevance or space reason.
4. **Layout Blueprint Proportions:**
   - Amdocs MUST carry the most bullets of any entry in the résumé.
   - `bank_integration_internship` (MalyTech) is capped at 3 bullets (typically default int_b1, int_b2, int_b3 unless the JD clearly favors another).
   - Projects: For backend, include 3 projects (PeerChat ~2, Fake Review Detection ~2, Campus Marketplace ~1). For ML, include 2 projects (Sepsis ~4, Fake Review Detection ~3).
   - Maximum total bullets: 15 for backend, 16 for ML.

## Output Format
You MUST respond with a single valid JSON object with NO preamble or surrounding markdown text outside ```json ... ``` code fences.

JSON Schema:
{{
  "atomic_requirements": [
    {{
      "id": "req_01",
      "term": "<atomic requirement name>",
      "quote": "<EXACT substring from the supplied JD>",
      "importance": "must_have" | "nice_to_have"
    }}
  ],
  "selected_evidence_ids": ["<list of evidence bullet IDs selected>"],
  "amdocs_omission_ledger": [
    {{
      "evidence_id": "<canonical amdocs bullet id omitted>",
      "category": "relevance" | "space",
      "reason": "<specific justification>"
    }}
  ],
  "section_order": ["Experience", "Projects", "Technical Skills"],
  "bullets": [
    {{
      "bullet_id": "b01",
      "evidence_ids": ["<master profile bullet id>"],
      "supported_requirement_ids": ["req_01"],
      "section": "Experience" | "Projects",
      "entry_id": "<employer or project id>",
      "text": "<Complete rewritten single-sentence bullet text>"
    }}
  ]
}}
"""


def build_audit_prompt(
    jd_text: str,
    bullets: list[DraftBullet],
    evidence_by_id: dict[str, Any],
) -> str:
    """Construct prompt for the independent auditor.

    CRITICAL: Receives ONLY the JD, drafted bullets, and cited evidence.
    Zero drafter chain of thought or persuasive rationale.
    """
    bullets_payload = []
    for b in bullets:
        ev_items = []
        for eid in b.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev:
                ev_items.append({
                    "id": ev.id,
                    "canonical_phrasing_medium": getattr(ev.phrasings, "medium", ""),
                    "evidence": ev.evidence,
                    "defense": getattr(ev, "defense", ""),
                })
        bullets_payload.append({
            "bullet_id": b.bullet_id,
            "section": b.section,
            "entry_id": b.entry_id,
            "text": b.text,
            "cited_evidence": ev_items,
        })

    bullets_json = json.dumps(bullets_payload, indent=2)

    return f"""You are an adversarial, independent résumé auditor. Your sole duty is to rigorously evaluate whether the candidate's drafted bullets adhere strictly to factual evidence and world-class writing standards.

You MUST evaluate the bullets strictly against the provided Job Description and cited profile evidence. Do NOT give the candidate the benefit of the doubt.

## Target Job Description
```text
{jd_text}
```

## Drafted Bullets and Cited Evidence
```json
{bullets_json}
```

## Evaluation Rubric (9 Dimensions)
Score each dimension on a 1–3 scale (3 = Excellent, 2 = Acceptable, 1 = Unacceptable / Defect):
1. **factual_fidelity:** Is every fact substantiated by the cited evidence? (Score 1 if any claim is unevidenced or exaggerated).
2. **metric_fidelity:** Are all metrics exact matches to the evidence or approved `~` approximations? (Score 1 if any number is invented or altered).
3. **technology_fidelity:** Are all technologies accurate to the evidence? (Score 1 if unmentioned tools or forbidden `Kubernetes` appear).
4. **technical_guarantee_fidelity:** Are guarantees exact (e.g. idempotent, append-only) without false claims like exactly-once? (Score 1 if false guarantees appear).
5. **relevance:** Does the bullet highlight technical capabilities relevant to the JD? (Score 1 if irrelevant filler).
6. **star_xyz_coherence:** Is the bullet a single continuous sentence in compressed STAR or Google XYZ format? (Score 1 if colon fragment, semicolon chain, or run-on).
7. **readability:** Is the sentence crisp, active, and immediate? (Score 1 if awkward, passive, or confusing).
8. **recruiter_scan_quality:** Does it stand out in a 7-second recruiter F-pattern scan? (Score 1 if a dense laundry list or architecture dump).
9. **ai_slop_risk:** Is the language natural and authentic? (Score 1 if it contains AI clichés like "spearheaded", "cutting-edge", "pivotal", "revolutionized", "meticulous").

## MANDATORY REJECTION RULES:
- A verdict of `"REJECT"` is MANDATORY for any bullet with score = 1 on ANY dimension.
- A verdict of `"REJECT"` is MANDATORY for any factual error, metric invention, or prohibited term.
- If ANY bullet is rejected, `overall_verdict` MUST be `"REPAIR_REQUIRED"`. If all bullets pass, `overall_verdict` is `"PASS"`.

## Output JSON Schema
{{
  "evaluations": [
    {{
      "bullet_id": "<id>",
      "dimensions": {{
        "factual_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "metric_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "technology_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "technical_guarantee_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "relevance": {{ "score": 1|2|3, "findings": "<critique>" }},
        "star_xyz_coherence": {{ "score": 1|2|3, "findings": "<critique>" }},
        "readability": {{ "score": 1|2|3, "findings": "<critique>" }},
        "recruiter_scan_quality": {{ "score": 1|2|3, "findings": "<critique>" }},
        "ai_slop_risk": {{ "score": 1|2|3, "findings": "<critique>" }}
      }},
      "verdict": "ACCEPT" | "REJECT",
      "rejection_reasons": ["<concise reason for rejection>"]
    }}
  ],
  "overall_verdict": "PASS" | "REPAIR_REQUIRED"
}}
"""


def build_repair_prompt(
    rejected_bullets: list[DraftBullet],
    evidence_by_id: dict[str, Any],
    audit_findings_by_bullet: dict[str, list[dict[str, Any]]],
) -> str:
    """Construct prompt for repairing rejected bullets.

    Receives ONLY the rejected bullets, their cited evidence, and the audit critiques.
    """
    items = []
    for b in rejected_bullets:
        ev_items = []
        for eid in b.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev:
                ev_items.append({
                    "id": ev.id,
                    "canonical_phrasing": getattr(ev.phrasings, "medium", ""),
                    "evidence": ev.evidence,
                    "defense": getattr(ev, "defense", ""),
                })
        items.append({
            "bullet_id": b.bullet_id,
            "entry_id": b.entry_id,
            "section": b.section,
            "rejected_text": b.text,
            "cited_evidence": ev_items,
            "audit_findings": audit_findings_by_bullet.get(b.bullet_id, []),
        })

    payload_json = json.dumps(items, indent=2)

    return f"""You are a precise résumé repair engineer. The independent auditor rejected the following bullets due to specific defects (such as factual inaccuracies, AI buzzwords, sentence structure issues, or metric deviations).

Your job is to rewrite ONLY these rejected bullets to completely resolve the auditor's critique while remaining 100% faithful to the cited evidence.

## Rejected Bullets & Audit Critiques
```json
{payload_json}
```

## Mandatory Repair Rules
1. Each repaired bullet must be ONE coherent, continuous sentence in compressed STAR or Google XYZ format.
2. Address and resolve every issue noted in `audit_findings`.
3. Eliminate all AI buzzwords, colon fragments, and semicolon chains.
4. Keep all metrics exactly faithful to the evidence (or approved `~` approximations). Never invent numbers.
5. Never render `Kubernetes`.

## Output JSON Schema
{{
  "repaired_bullets": [
    {{
      "bullet_id": "<id>",
      "text": "<Repaired complete single-sentence bullet text>"
    }}
  ]
}}
"""


def build_re_audit_prompt(
    jd_text: str,
    repaired_bullets: list[RepairedBullet],
    evidence_by_id: dict[str, Any],
    bullet_entries: dict[str, tuple[str, str, list[str]]],
) -> str:
    """Construct prompt for re-auditing repaired bullets.

    Receives ONLY the repaired bullets, their cited evidence, and the JD.
    """
    bullets_payload = []
    for b in repaired_bullets:
        section, entry_id, evidence_ids = bullet_entries.get(b.bullet_id, ("Experience", "unknown", []))
        ev_items = []
        for eid in evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev:
                ev_items.append({
                    "id": ev.id,
                    "canonical_phrasing_medium": getattr(ev.phrasings, "medium", ""),
                    "evidence": ev.evidence,
                    "defense": getattr(ev, "defense", ""),
                })
        bullets_payload.append({
            "bullet_id": b.bullet_id,
            "section": section,
            "entry_id": entry_id,
            "text": b.text,
            "cited_evidence": ev_items,
        })

    bullets_json = json.dumps(bullets_payload, indent=2)

    return f"""You are an adversarial, independent résumé auditor. The following repaired bullets were rewritten to fix previous audit defects.

Evaluate these repaired bullets under the exact same 9 dimensions against the JD and cited evidence. Do NOT lower your standards.

## Target Job Description
```text
{jd_text}
```

## Repaired Bullets and Cited Evidence
```json
{bullets_json}
```

## Evaluation Rubric (9 Dimensions)
Score each on a 1–3 scale:
1. factual_fidelity
2. metric_fidelity
3. technology_fidelity
4. technical_guarantee_fidelity
5. relevance
6. star_xyz_coherence
7. readability
8. recruiter_scan_quality
9. ai_slop_risk

## MANDATORY REJECTION RULES:
- Score 1 on ANY dimension MUST result in `"REJECT"`.
- If ANY repaired bullet is rejected, `overall_verdict` MUST be `"REPAIR_REQUIRED"`. If all pass, `overall_verdict` is `"PASS"`.

## Output JSON Schema
{{
  "evaluations": [
    {{
      "bullet_id": "<id>",
      "dimensions": {{
        "factual_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "metric_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "technology_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "technical_guarantee_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
        "relevance": {{ "score": 1|2|3, "findings": "<critique>" }},
        "star_xyz_coherence": {{ "score": 1|2|3, "findings": "<critique>" }},
        "readability": {{ "score": 1|2|3, "findings": "<critique>" }},
        "recruiter_scan_quality": {{ "score": 1|2|3, "findings": "<critique>" }},
        "ai_slop_risk": {{ "score": 1|2|3, "findings": "<critique>" }}
      }},
      "verdict": "ACCEPT" | "REJECT",
      "rejection_reasons": ["<concise reason if rejected>"]
    }}
  ],
  "overall_verdict": "PASS" | "REPAIR_REQUIRED"
}}
"""
