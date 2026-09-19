"""Deterministic validators for the LLM-first tailoring lane (Tailor2).

Enforces strictly objectively falsifiable rules:
- Schema and types
- Requirement ID uniqueness
- Exact JD quote substrings
- Evidence ID resolution in master_profile.yaml
- Numeric token multiset / approximation fidelity
- Zero occurrences of do_not_claim or prohibited terms ("Kubernetes")
- Zero duplicate bullets
- Blueprint layout and section bounds (Amdocs largest, MalyTech <= 3)
- Canonical Amdocs 7-bullet accounting
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from src.profile import MasterProfile
from src.tailor2.audit_projection import ResumeProjection, unsupported_skill_terms
from src.tailor2.models import (
    REQUIRED_AUDIT_DIMENSIONS,
    AuditResponse,
    BulletAuditEvaluation,
    DraftResponse,
    RepairResponse,
    WholeResumeEvaluation,
)
from src.tailor2.severity import Severity, has_fatal_dimension

CANONICAL_AMDOCS_BULLETS: tuple[str, ...] = (
    "am_b00_order_management_domain",
    "am_b01_dlq_consolidation",
    "am_b02_row_level_entitlement",
    "am_b03_audit_trail",
    "am_b04_data_retention",
    "am_b05_test_automation",
    "am_b07_code_quality_gates",
)

_NUMBER_RE = re.compile(r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)")


class DraftValidationError(ValueError):
    """Raised when a drafted resume fails deterministic validation."""


class AuditValidationError(ValueError):
    """Raised when an audit response fails deterministic validation."""


class RepairValidationError(ValueError):
    """Raised when a repair response fails deterministic validation."""


def extract_numeric_tokens(text: str) -> list[str]:
    """Extract raw numeric tokens matching the canonical regex."""
    return [match.group(0) for match in _NUMBER_RE.finditer(text)]


def _normalize_num_token(token: str) -> str:
    """Normalize a numeric token for approximation comparison (~40% -> 40%)."""
    return token.lstrip("~+").strip()


def validate_draft_response(
    draft: DraftResponse,
    jd_text: str,
    profile: MasterProfile,
    base_variant: str,
    *,
    allow_missing_canonical: bool = False,
    enforce_layout: bool = True,
) -> None:
    """Deterministically validate DraftResponse against JD and MasterProfile."""
    # 1. Unique requirement IDs and exact quote verification
    seen_req_ids: set[str] = set()
    for req in draft.atomic_requirements:
        if req.id in seen_req_ids:
            raise DraftValidationError(f"Duplicate requirement id: {req.id!r}")
        seen_req_ids.add(req.id)

        if req.quote not in jd_text:
            raise DraftValidationError(
                f"Requirement quote {req.quote!r} (id: {req.id}) is not an exact substring of the JD"
            )

    # 2. Build profile evidence catalog
    evidence_by_id: dict[str, Any] = {}
    for exp in profile.experience:
        for b in exp.bullets:
            evidence_by_id[b.id] = b
    for proj in profile.projects:
        for b in proj.bullets:
            evidence_by_id[b.id] = b

    # 3. Check selected evidence IDs
    for eid in draft.selected_evidence_ids:
        if eid not in evidence_by_id:
            raise DraftValidationError(f"unknown evidence_id in selected_evidence_ids: {eid!r}")

    # 4. Check bullets: IDs, text uniqueness, evidence resolution, and numeric tokens
    seen_bullet_ids: set[str] = set()
    seen_bullet_texts: set[str] = set()
    cited_amdocs_evidence: set[str] = set()
    entry_bullet_counts: dict[str, int] = {}

    do_not_claim_terms = list(profile.do_not_claim)
    if "Kubernetes" not in do_not_claim_terms:
        do_not_claim_terms.append("Kubernetes")

    for bullet in draft.bullets:
        if bullet.bullet_id in seen_bullet_ids:
            raise DraftValidationError(f"Duplicate bullet_id: {bullet.bullet_id!r}")
        seen_bullet_ids.add(bullet.bullet_id)

        if bullet.text in seen_bullet_texts:
            raise DraftValidationError(f"Duplicate bullet text in bullet {bullet.bullet_id!r}")
        seen_bullet_texts.add(bullet.text)

        # Check prohibited terms / do_not_claim
        for term in do_not_claim_terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, bullet.text, re.IGNORECASE):
                raise DraftValidationError(
                    f"Bullet {bullet.bullet_id!r} contains prohibited do_not_claim term {term!r}"
                )

        # Resolve evidence IDs
        cited_evidence_objects = []
        for eid in bullet.evidence_ids:
            if eid not in evidence_by_id:
                raise DraftValidationError(
                    f"Bullet {bullet.bullet_id!r} cites unknown evidence_id: {eid!r}"
                )
            ev_obj = evidence_by_id[eid]
            cited_evidence_objects.append(ev_obj)
            if eid in CANONICAL_AMDOCS_BULLETS:
                cited_amdocs_evidence.add(eid)

        # Check numeric tokens
        bullet_num_tokens = extract_numeric_tokens(bullet.text)
        if bullet_num_tokens:
            def _add_texts(val: Any) -> None:
                if isinstance(val, str):
                    evidence_texts.append(val)
                elif isinstance(val, (tuple, list)):
                    for item in val:
                        if isinstance(item, str):
                            evidence_texts.append(item)

            # Collect all numeric tokens from cited evidence phrasings, evidence notes, and defense
            evidence_texts: list[str] = []
            for ev in cited_evidence_objects:
                if hasattr(ev, "phrasings") and ev.phrasings:
                    for ph_attr in ("short", "medium", "long"):
                        _add_texts(getattr(ev.phrasings, ph_attr, None))
                elif hasattr(ev, "text"):
                    _add_texts(getattr(ev, "text", None))
                if hasattr(ev, "evidence"):
                    _add_texts(getattr(ev, "evidence", None))
                if hasattr(ev, "defense"):
                    _add_texts(getattr(ev, "defense", None))
            
            allowed_tokens = set()
            for t in evidence_texts:
                for tok in extract_numeric_tokens(t):
                    allowed_tokens.add(tok)
                    allowed_tokens.add(_normalize_num_token(tok))

            for tok in bullet_num_tokens:
                norm_tok = _normalize_num_token(tok)
                if tok not in allowed_tokens and norm_tok not in allowed_tokens:
                    raise DraftValidationError(
                        f"Bullet {bullet.bullet_id!r}: numeric token {tok!r} not found in cited evidence {bullet.evidence_ids}"
                    )

        # Count per entry
        entry_bullet_counts[bullet.entry_id] = entry_bullet_counts.get(bullet.entry_id, 0) + 1

    # 5. Canonical Amdocs 7-bullet accounting
    omitted_amdocs_evidence = {
        om.evidence_id for om in draft.amdocs_omission_ledger
    }
    if not allow_missing_canonical:
        for req_amdocs in CANONICAL_AMDOCS_BULLETS:
            if req_amdocs not in cited_amdocs_evidence and req_amdocs not in omitted_amdocs_evidence:
                raise DraftValidationError(
                    f"Canonical Amdocs bullet {req_amdocs!r} missing: must be included in draft bullets or listed in amdocs_omission_ledger"
                )

    # 6. Layout and blueprint bounds
    if not enforce_layout:
        return
    # Amdocs must be the largest entry
    amdocs_count = entry_bullet_counts.get("amdocs_software_developer", 0)
    for entry_id, count in entry_bullet_counts.items():
        if entry_id != "amdocs_software_developer" and count >= amdocs_count and amdocs_count > 0:
            raise DraftValidationError(
                f"Amdocs must carry the most bullets: amdocs has {amdocs_count}, but {entry_id} has {count}"
            )

    # MalyTech (bank_integration_internship) is capped at 3 bullets
    maly_count = entry_bullet_counts.get("bank_integration_internship", 0)
    if maly_count > 3:
        raise DraftValidationError(
            f"bank_integration_internship (MalyTech) is capped at 3 bullets; found {maly_count}"
        )

    # Total bullet budget
    max_bullets = 16 if base_variant == "ml" else 15
    if len(draft.bullets) > max_bullets:
        raise DraftValidationError(
            f"Draft has {len(draft.bullets)} bullets, exceeding layout budget of {max_bullets} for {base_variant}"
        )


def validate_missing_evidence_response(
    response: Any,
    expected_evidence_ids: set[str],
    existing_bullet_ids: set[str],
    evidence_by_id: dict[str, Any],
    profile: MasterProfile,
) -> None:
    """Validate a targeted recovery response before it enters the draft."""
    returned_ids = [item.evidence_id for item in response.recovered_bullets]
    if set(returned_ids) != expected_evidence_ids or len(returned_ids) != len(set(returned_ids)):
        raise DraftValidationError(
            f"Missing-evidence response IDs mismatch: expected {sorted(expected_evidence_ids)}, got {returned_ids}"
        )
    do_not_claim_terms = list(profile.do_not_claim)
    if "Kubernetes" not in do_not_claim_terms:
        do_not_claim_terms.append("Kubernetes")
    for item in response.recovered_bullets:
        if item.evidence_id not in evidence_by_id:
            raise DraftValidationError(f"Recovery cites unknown evidence_id: {item.evidence_id!r}")
        if item.bullet_id in existing_bullet_ids:
            raise DraftValidationError(f"Recovery duplicates existing bullet_id: {item.bullet_id!r}")
        if not item.text.strip() or "\n" in item.text or "\r" in item.text:
            raise DraftValidationError(f"Recovery bullet {item.bullet_id!r} must be one non-empty line")
        for term in do_not_claim_terms:
            if re.search(r"\b" + re.escape(term) + r"\b", item.text, re.IGNORECASE):
                raise DraftValidationError(f"Recovery bullet {item.bullet_id!r} contains prohibited term {term!r}")
        evidence = evidence_by_id[item.evidence_id]
        evidence_texts: list[str] = []
        if hasattr(evidence, "phrasings") and evidence.phrasings:
            evidence_texts.extend(
                value for value in (
                    getattr(evidence.phrasings, "short", ""),
                    getattr(evidence.phrasings, "medium", ""),
                    getattr(evidence.phrasings, "long", ""),
                ) if isinstance(value, str)
            )
        for attribute in ("evidence", "defense"):
            value = getattr(evidence, attribute, "")
            if isinstance(value, str):
                evidence_texts.append(value)
        allowed_tokens = {
            normalized
            for text in evidence_texts
            for token in extract_numeric_tokens(text)
            for normalized in (token, _normalize_num_token(token))
        }
        for token in extract_numeric_tokens(item.text):
            if token not in allowed_tokens and _normalize_num_token(token) not in allowed_tokens:
                raise DraftValidationError(
                    f"Recovery bullet {item.bullet_id!r}: numeric token {token!r} not found in canonical evidence"
                )


def validate_audit_response(
    audit: AuditResponse,
    expected_bullet_ids: list[str],
) -> None:
    """Deterministically validate AuditResponse."""
    evaluated_ids = {ev.bullet_id for ev in audit.evaluations}
    expected_set = set(expected_bullet_ids)
    if evaluated_ids != expected_set:
        missing = expected_set - evaluated_ids
        extra = evaluated_ids - expected_set
        raise AuditValidationError(
            f"Audit evaluation bullet ID mismatch. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    has_rejection = False
    for ev in audit.evaluations:
        for dim_name in REQUIRED_AUDIT_DIMENSIONS:
            if dim_name not in ev.dimensions:
                raise AuditValidationError(
                    f"Bullet {ev.bullet_id!r} evaluation missing dimension {dim_name!r}"
                )
            dim_score = ev.dimensions[dim_name]
            if dim_score.score not in (1, 2, 3):
                raise AuditValidationError(
                    f"Bullet {ev.bullet_id!r} dimension {dim_name!r} invalid score: {dim_score.score}"
                )
            # Mandatory repair rule: score == 1 MUST result in REJECT
            if dim_score.score == 1 and ev.verdict != "REJECT":
                raise AuditValidationError(
                    f"Bullet {ev.bullet_id!r} dimension {dim_name!r} has score 1 must have verdict REJECT, got {ev.verdict}"
                )

        if ev.rejection_reasons and ev.verdict != "REJECT":
            raise AuditValidationError(
                f"Bullet {ev.bullet_id!r} has rejection reasons but verdict is {ev.verdict}"
            )

        if ev.verdict == "REJECT":
            has_rejection = True

    if has_rejection and audit.overall_verdict != "REPAIR_REQUIRED":
        raise AuditValidationError(
            f"Audit has rejected bullets but overall_verdict is {audit.overall_verdict!r} (expected 'REPAIR_REQUIRED')"
        )
    if not has_rejection and audit.overall_verdict != "PASS":
        raise AuditValidationError(
            f"Audit has 0 rejected bullets but overall_verdict is {audit.overall_verdict!r} (expected 'PASS')"
        )


def validate_repair_response(
    repair: RepairResponse,
    expected_bullet_ids: list[str],
    evidence_ids_by_bullet: dict[str, list[str]],
    evidence_by_id: dict[str, Any],
    profile: MasterProfile,
) -> None:
    """Deterministically validate RepairResponse."""
    repaired_ids = {b.bullet_id for b in repair.repaired_bullets}
    expected_set = set(expected_bullet_ids)
    if repaired_ids != expected_set:
        missing = expected_set - repaired_ids
        extra = repaired_ids - expected_set
        raise RepairValidationError(
            f"Repair response bullet ID mismatch. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    do_not_claim_terms = list(profile.do_not_claim)
    if "Kubernetes" not in do_not_claim_terms:
        do_not_claim_terms.append("Kubernetes")

    for rep in repair.repaired_bullets:
        for term in do_not_claim_terms:
            pattern = r"\b" + re.escape(term) + r"\b"
            if re.search(pattern, rep.text, re.IGNORECASE):
                raise RepairValidationError(
                    f"Repaired bullet {rep.bullet_id!r} contains prohibited term {term!r}"
                )

        num_tokens = extract_numeric_tokens(rep.text)
        if num_tokens:
            cited_eids = evidence_ids_by_bullet.get(rep.bullet_id, [])
            def _add_texts(val: Any) -> None:
                if isinstance(val, str):
                    evidence_texts.append(val)
                elif isinstance(val, (tuple, list)):
                    for item in val:
                        if isinstance(item, str):
                            evidence_texts.append(item)

            evidence_texts: list[str] = []
            for eid in cited_eids:
                ev = evidence_by_id.get(eid)
                if ev:
                    if hasattr(ev, "phrasings") and ev.phrasings:
                        for ph_attr in ("short", "medium", "long"):
                            _add_texts(getattr(ev.phrasings, ph_attr, None))
                    elif hasattr(ev, "text"):
                        _add_texts(getattr(ev, "text", None))
                    if hasattr(ev, "evidence"):
                        _add_texts(getattr(ev, "evidence", None))
                    if hasattr(ev, "defense"):
                        _add_texts(getattr(ev, "defense", None))

            allowed_tokens = set()
            for t in evidence_texts:
                for tok in extract_numeric_tokens(t):
                    allowed_tokens.add(tok)
                    allowed_tokens.add(_normalize_num_token(tok))

            for tok in num_tokens:
                norm_tok = _normalize_num_token(tok)
                if tok not in allowed_tokens and norm_tok not in allowed_tokens:
                    raise RepairValidationError(
                        f"Repaired bullet {rep.bullet_id!r}: numeric token {tok!r} not found in cited evidence {cited_eids}"
                    )


# Re-audit response uses identical validation rules as audit response
validate_re_audit_response = validate_audit_response


# ---------------------------------------------------------------------------
# Severity classification and deterministic auto-correction.
#
# validate_audit_response above is unchanged: it only enforces that the
# AuditResponse object is internally consistent (score==1 on a dimension
# implies verdict==REJECT on that evaluation, overall_verdict reflects
# whether anything was rejected). It says nothing about what the LANE should
# DO once it sees a REJECT -- that policy decision lives here, using the
# dimension -> Severity table in severity.py, so it can be reasoned about
# and tested independently of the schema-consistency rule.
# ---------------------------------------------------------------------------


def classify_evaluation_severity(evaluation: BulletAuditEvaluation) -> Severity | None:
    """Severity of a bullet's rejection, or None if the bullet was accepted.

    A bullet can fail multiple dimensions at once; if ANY failing dimension
    is FATAL_INTEGRITY, the whole bullet is treated as fatal (a single
    fabricated number is not offset by three well-written sentences)."""
    if evaluation.verdict != "REJECT":
        return None
    failing = [name for name, d in evaluation.dimensions.items() if d.score == 1]
    if has_fatal_dimension(failing):
        return Severity.FATAL_INTEGRITY
    return Severity.REPAIRABLE_QUALITY


def classify_whole_resume_severity(evaluation: WholeResumeEvaluation | None) -> Severity | None:
    """Same logic as classify_evaluation_severity, for the whole-résumé
    evaluation block. None input (legacy fixture with no whole_resume audit)
    and an ACCEPT verdict both return None."""
    if evaluation is None or evaluation.verdict != "REJECT":
        return None
    failing = [name for name, d in evaluation.dimensions.items() if d.score == 1]
    if has_fatal_dimension(failing):
        return Severity.FATAL_INTEGRITY
    return Severity.REPAIRABLE_QUALITY


def check_skills_evidence_integrity(projection: ResumeProjection) -> list[str]:
    """Deterministic AUTO_CORRECTABLE check: every rendered Skills term must
    be supported by canonical profile evidence. Terms unsupported anywhere in
    canonical evidence are removed."""
    return [
        f"Skills: {category!r} term {term!r} is not canonically supported in profile; removed"
        for category, term in unsupported_skill_terms(projection)
    ]


def check_skills_advisories(projection: ResumeProjection) -> list[str]:
    """Advisory check: canonically supported terms that lack visible demonstration
    in this run's selected evidence generate informational warnings without removal."""
    from src.tailor2.audit_projection import check_skills_advisories as _advisories
    return _advisories(projection)


def apply_deterministic_auto_corrections(
    projection: ResumeProjection,
) -> tuple[ResumeProjection, list[str]]:
    """Apply every AUTO_CORRECTABLE fix this module knows how to make
    deterministically (title mismatches were already resolved when the
    projection was built -- see audit_projection.build_resume_projection --
    so this only needs to strip unsupported Skills entries) and return the
    corrected projection plus a flat list of human-readable correction
    messages for the manifest."""
    import dataclasses as _dc

    corrections = list(projection.title_auto_corrections)
    corrections.extend(check_skills_evidence_integrity(projection))

    corrected_skills = {
        category: [s for s in terms if s.canonical_support]
        for category, terms in projection.skills.items()
    }
    corrected = _dc.replace(projection, skills=corrected_skills)
    return corrected, corrections
