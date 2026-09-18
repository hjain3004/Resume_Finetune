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
from src.tailor2.audit_projection import ResumeProjection, projection_to_dict
from src.tailor2.models import (
    REQUIRED_WHOLE_RESUME_DIMENSIONS,
    DraftBullet,
    RepairedBullet,
)
from src.tailor2.validators import CANONICAL_AMDOCS_BULLETS

_WHOLE_RESUME_RUBRIC = """
## Whole-Résumé Evaluation (in addition to per-bullet scoring above)
You have also been given the COMPLETE résumé projection below (every
selected bullet in final order, employer/project headings and displayed
titles, the full Skills section, requirement-to-evidence coverage, the
omission ledger, and model identities). Evaluate the résumé AS A WHOLE --
not bullet by bullet -- on these 8 additional dimensions. A résumé must NOT
pass merely because each individual bullet's literal claims are supported;
score these honestly even when every per-bullet score above is a 3.

1. **metric_interpretability:** Does every metric have an interpretable
   denominator, scale, baseline, or evaluation context, or does the résumé
   present an undefined figure (e.g. "mean LLM scoring movement" with no
   explanation of what movement means or why smaller is better)? (Score 1
   if any metric is uninterpretable as written.)
2. **interview_defensibility:** Could the candidate defend every claim if
   an interviewer pushed on it, given the cited evidence and any
   interview_risk notes? (Score 1 if a claim reads as impressive but is
   not defensible from the evidence provided.)
3. **whole_resume_positioning:** Does the complete résumé, read start to
   finish, present a coherent, compelling case for this specific role --
   not just a set of individually-true bullets? (Score 1 if the résumé
   reads as a pile of accomplishments with no coherent narrative.)
4. **skills_evidence_integrity:** Does every Skills entry resolve to
   evidence actually selected for this run? (Score 1 if any Skills term
   in the projection is marked unsupported.)
5. **title_identity_fidelity:** Does every displayed employer/title match
   canonical data or a documented approved variant? (Score 1 if any entry
   in `title_auto_corrections` reflects a mismatch that required
   correction -- note that a mismatch which WAS auto-corrected before you
   saw this projection should still be scored 1 here, since the underlying
   drafter behavior that produced it is a real defect worth flagging even
   though the deterministic layer already fixed the output.)
6. **mechanism_outcome_balance:** Do bullets demonstrate outcomes and
   behavior, not just an inventory of mechanisms/technologies used? (Score
   1 if a bullet or project is primarily a feature/mechanism catalogue
   with no demonstrated result.)
7. **cross_bullet_repetition:** Is abstract terminology (e.g. "agentic",
   "orchestration", "evidence-grounded", "validation", "human review")
   repeated across multiple bullets, project headers, and Skills in a way
   that reads as generated rather than precise and sparing? Precise,
   sparing use of a technical term is NOT a defect by itself -- only
   repetition without added specificity is. (Score 1 if the same abstract
   term appears 3+ times across different bullets/sections without adding
   new information each time.)
8. **misleading_implication:** Even if every individual literal phrase is
   factually supported, does the complete résumé create a materially
   misleading overall impression (e.g. implying a different role, scope,
   or level of ownership than the evidence supports)? (Score 1 if the
   whole-résumé impression is misleading regardless of per-phrase
   factuality.)

## Whole-Résumé Projection
```json
{projection_json}
```

## Output JSON Schema Addition
Add this top-level key to your JSON response, alongside "evaluations" and
"overall_verdict":
{{
  "whole_resume": {{
    "dimensions": {{
      "metric_interpretability": {{ "score": 1|2|3, "findings": "<critique>" }},
      "interview_defensibility": {{ "score": 1|2|3, "findings": "<critique>" }},
      "whole_resume_positioning": {{ "score": 1|2|3, "findings": "<critique>" }},
      "skills_evidence_integrity": {{ "score": 1|2|3, "findings": "<critique>" }},
      "title_identity_fidelity": {{ "score": 1|2|3, "findings": "<critique>" }},
      "mechanism_outcome_balance": {{ "score": 1|2|3, "findings": "<critique>" }},
      "cross_bullet_repetition": {{ "score": 1|2|3, "findings": "<critique>" }},
      "misleading_implication": {{ "score": 1|2|3, "findings": "<critique>" }}
    }},
    "verdict": "ACCEPT" | "REJECT",
    "rejection_reasons": ["<concise reason if rejected>"]
  }}
}}
A "REJECT" verdict here (or on any bullet) means overall_verdict must be
"REPAIR_REQUIRED". This is a writing-quality and positioning judgment, not
a factual-integrity one -- it should trigger a repair pass, not imply the
underlying facts are wrong.
"""


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


def build_selection_prompt(
    jd_text: str,
    profile: MasterProfile,
    base_variant: str,
    company: str,
    title: str,
    *,
    max_candidates_per_bullet: int = 3,
) -> str:
    """Construct the single bounded model call for selection and ranking."""
    return f"""You are the constrained selection and ranking stage for a résumé tailoring lane.
Return one JSON object only. Do not write résumé structure, section order, project order,
or employer order: the downstream draft contract remains the authority for those decisions.
Use only the canonical evidence catalog below.

Target: {company} — {title}
Base variant: {base_variant}

JOB DESCRIPTION
{jd_text}

CANONICAL EVIDENCE
{_format_evidence_catalog(profile)}

Your response must contain:
1. `requirements`: stable IDs, exact JD quotes, `kind` in `must_have`, `preferred`, or
   `responsibility`, optional `alternative_group_id`, domain context, ambiguity, and evidence gaps.
2. `matches`: requirement IDs mapped to evidence IDs with `classification` in `direct`,
   `adjacent`, `transferable`, or `gap`, confidence, strength, explanation, and limitation.
   Do not turn general AI interest into LLM production experience.
3. `evidence_selection`: role-aware selections with score, requirement IDs, line cost, and reason.
   Balance employer/project ownership and avoid keyword-heavy or redundant bullets.
4. `skills`: only terms from existing canonical skill categories; never invent a category or term.
5. `candidates`: at most {max_candidates_per_bullet} candidates per canonical selected bullet.
   Preserve evidence IDs, identities, achievements, metrics, units, baselines, approximation markers,
   title and prohibited-claim constraints. Candidates must be one line and no longer than canonical text.
6. `rankings`: explicit candidate IDs, component scores for clarity, relevance, achievement,
   metric interpretability, defensibility, mechanism/outcome balance, redundancy, AI abstraction,
   recruiter scan, and line cost, plus concise rationale.
7. `unused_evidence`: include omitted evidence IDs, requirement coverage, strength, likely section,
   line cost, omission/redundancy reason, and later page-fill suitability.

The deterministic validator will discard unsafe candidates individually and use a safe fallback when
ranking data is incomplete. Never fabricate evidence, numbers, metrics, categories, or experience.
Never render Kubernetes or any other do_not_claim term.
"""


def build_draft_prompt(
    jd_text: str,
    profile: MasterProfile,
    base_variant: str,
    company: str,
    title: str,
    selection_context: str | None = None,
) -> str:
    """Construct prompt for the draft generation stage."""
    canonical_amdocs_str = ", ".join(f"`{bid}`" for bid in CANONICAL_AMDOCS_BULLETS)
    catalog_str = _format_evidence_catalog(profile)

    selection_block = selection_context or "No separate selection artifact was supplied; make a conservative evidence selection from the canonical catalog."

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
4. **Flexible Selection and Layout:**
   - Select evidence by role coverage, strength, specificity, recency, defensibility, diversity, and line cost; do not use fixed project or employer counts.
   - Preserve the supplied base variant's canonical project/experience availability and let the selected bullets determine the final allocation.
   - Keep the strongest evidence visible without allowing one employer, project, or keyword cluster to consume the whole résumé.
   - Do not add a bullet merely to fill a quota; omission reasons must remain explicit.

## Bounded Selection Artifact
{selection_block}

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
    projection: ResumeProjection | None = None,
) -> str:
    """Construct prompt for the independent auditor.

    CRITICAL: Receives ONLY the JD, drafted bullets, and cited evidence
    (plus, when `projection` is supplied, the complete résumé projection --
    still never the drafter's chain of thought or persuasive rationale).
    When `projection` is omitted the output is identical to the pre-existing
    9-dimension-only prompt, for backward compatibility with direct callers
    that construct their own bullet list.
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

    base_prompt = f"""You are an adversarial, independent résumé auditor. Your sole duty is to rigorously evaluate whether the candidate's drafted bullets adhere strictly to factual evidence and world-class writing standards.

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
- Note: not every rejection is equally severe downstream. factual_fidelity and metric_fidelity failures indicate a claim or number that cannot be trusted; the other 7 dimensions indicate a writing-quality or positioning defect that a repair pass can fix without inventing anything. Score each dimension on its own merits regardless of downstream handling -- that policy decision is made by the pipeline, not by you.

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

    if projection is None:
        return base_prompt

    projection_json = json.dumps(projection_to_dict(projection), indent=2, default=str)
    return base_prompt + _WHOLE_RESUME_RUBRIC.format(projection_json=projection_json)


def build_repair_prompt(
    rejected_bullets: list[DraftBullet],
    evidence_by_id: dict[str, Any],
    audit_findings_by_bullet: dict[str, list[dict[str, Any]]],
    projection: ResumeProjection | None = None,
    protected_facts: list[str] | None = None,
) -> str:
    """Construct prompt for repairing rejected bullets.

    Receives the rejected bullets, their cited evidence, and the audit
    critiques -- and, when supplied, the complete résumé projection (for
    context: what else is already on the page, so the repair doesn't
    duplicate another bullet or contradict the résumé's overall
    positioning) plus a `protected_facts` list the model must not alter.
    Only the rejected bullets are editable targets; everything else in the
    projection is context, not something this call is asked to rewrite.
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

    base_prompt = f"""You are a precise résumé repair engineer. The independent auditor rejected the following bullets due to specific defects (such as factual inaccuracies, AI buzzwords, sentence structure issues, or metric deviations).

Your job is to rewrite ONLY these rejected bullets to completely resolve the auditor's critique while remaining 100% faithful to the cited evidence. Preserve every supported achievement in each bullet while you improve clarity and impact -- do not resolve a critique by deleting the achievement instead of rewriting it.

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
6. Preserve every supported achievement in the bullet. If a critique is about tone, repetition, or clarity, rewrite the sentence -- do not shorten it into a vaguer claim or drop the accomplishment to make the critique go away.
7. Edit ONLY the bullets listed above. Every other bullet on the résumé (visible in the projection below, if provided) is out of scope for this call.

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

    if projection is None and not protected_facts:
        return base_prompt

    extra = "\n## Protected Facts (must not change, must not be contradicted)\n"
    if protected_facts:
        for fact in protected_facts:
            extra += f"- {fact}\n"
    else:
        extra += "(none supplied)\n"

    if projection is not None:
        projection_json = json.dumps(projection_to_dict(projection), indent=2, default=str)
        extra += (
            "\n## Full Résumé Projection (context only -- NOT editable; the rejected bullets above are "
            "the only editable targets)\n```json\n" + projection_json + "\n```\n"
        )

    return base_prompt + extra


def build_re_audit_prompt(
    jd_text: str,
    repaired_bullets: list[RepairedBullet],
    evidence_by_id: dict[str, Any],
    bullet_entries: dict[str, tuple[str, str, list[str]]],
    projection: ResumeProjection | None = None,
) -> str:
    """Construct prompt for re-auditing repaired bullets.

    Receives the repaired bullets, their cited evidence, and the JD -- and,
    when `projection` is supplied, the COMPLETE spliced résumé (every
    bullet, not just the repaired fragments), so the re-audit genuinely
    evaluates the whole repaired résumé rather than only the changed
    pieces. `projection` is optional for backward compatibility with
    direct callers that only want the fragment-level re-check.
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

    base_prompt = f"""You are an adversarial, independent résumé auditor. The following repaired bullets were rewritten to fix previous audit defects.

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

    if projection is None:
        return base_prompt

    projection_json = json.dumps(projection_to_dict(projection), indent=2, default=str)
    return base_prompt + _WHOLE_RESUME_RUBRIC.format(projection_json=projection_json)
