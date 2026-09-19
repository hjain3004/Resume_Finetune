"""Severity model for Tailor2 quality gates.

Design decision (see docs/tailor2_quality_core.md): the pipeline must be
fail-closed for factual integrity but repair-first for writing quality. A
single "any dimension scores 1 -> REJECT the whole run" rule (the pre-existing
behavior) does not distinguish a fabricated number from a repetitive
adjective, so every quality nit escalated to a full rejection. This module
introduces a four-tier severity classification and a five-state run outcome,
and keeps the classification decision (this module) fully separate from the
schema-consistency rule enforced by validators.validate_audit_response
(a dimension scoring 1 must still carry verdict=REJECT on that evaluation --
that invariant is unchanged and untouched). What changes is what the LANE
does once it sees a REJECT: escalate to fatal only for fatal-tier dimensions.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class Severity(str, Enum):
    """How a quality defect should be handled once detected.

    FATAL_INTEGRITY:  audit-tier factual/metric integrity concern. The lane
        sanitizes the cited element first; it becomes REJECTED_FATAL only
        when canonical replacement/removal and safe fallback are impossible.
    AUTO_CORRECTABLE: deterministically fixable without model judgment
        (canonical title/employer mismatch, an unsupported Skills entry
        that can simply be dropped, terminology normalization, spacing).
        Corrected automatically; the run continues.
    REPAIRABLE_QUALITY: a writing-quality or positioning defect. Triggers a
        bounded, targeted repair pass, not a rejection.
    ADVISORY_GAP: the profile has no evidence for some JD capability.
        Disclosed, never invented, never blocks completion.
    """

    FATAL_INTEGRITY = "FATAL_INTEGRITY"
    AUTO_CORRECTABLE = "AUTO_CORRECTABLE"
    REPAIRABLE_QUALITY = "REPAIRABLE_QUALITY"
    ADVISORY_GAP = "ADVISORY_GAP"


class RunStatus(str, Enum):
    """Terminal (or, for REPAIR_REQUIRED, transient-but-reportable) outcome
    of a Tailor2 run. Exactly one of these is recorded as the final
    Tailor2Manifest.status for a completed run."""

    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_WARNINGS = "ACCEPTED_WITH_WARNINGS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    REJECTED_FATAL = "REJECTED_FATAL"


# --------------------------------------------------------------------------
# Dimension -> severity classification.
#
# Bullet-level dimensions (REQUIRED_AUDIT_DIMENSIONS in models.py) and the
# new whole-résumé dimensions (WHOLE_RESUME_AUDIT_DIMENSIONS in models.py)
# share one table so lane.py has a single lookup regardless of which
# evaluation block a score came from.
#
# Rationale for each placement is documented once here rather than scattered:
#
# FATAL_INTEGRITY -- factual_fidelity and metric_fidelity identify claims
#   that require element-level sanitization. They remain fatal-tier for audit
#   classification, but lane.py quarantines/restores the cited element before
#   deciding whether a whole run is fatal. Whole-run fatality is reserved for
#   missing grounded content, impossible provenance, and failed artifact or
#   source fallback.
#
# REPAIRABLE_QUALITY -- everything about HOW a true claim is expressed:
#   technology_fidelity and technical_guarantee_fidelity failures are
#   almost always an imprecise word choice (e.g. "exactly-once" instead of
#   "idempotent") that a repair pass can correct without inventing
#   anything; relevance, star_xyz_coherence, readability,
#   recruiter_scan_quality, and ai_slop_risk are classic rewrite targets;
#   the eight new whole-résumé dimensions (metric_interpretability,
#   interview_defensibility, whole_resume_positioning,
#   mechanism_outcome_balance, cross_bullet_repetition,
#   misleading_implication) are judgment calls about clarity and
#   positioning, not fact disputes -- a résumé that misleadingly implies a
#   role it wasn't in should force a repair (or, if repair can't resolve
#   it, NEEDS_HUMAN_REVIEW), not a fatal rejection, because the literal
#   words may all be true.
#
# skills_evidence_integrity and title_identity_fidelity are primarily
#   deterministic/AUTO_CORRECTABLE concerns (see validators.py
#   check_skills_evidence_integrity and title_policy.py); they are also
#   scored by the LLM whole-résumé auditor as a second line of defense for
#   subtler cases the deterministic check doesn't catch (e.g. a skill
#   term that resolves to evidence but is presented in a misleading
#   context). When the LLM flags one, treat it the same as any other
#   REPAIRABLE_QUALITY finding -- the deterministic layer already handles
#   the clean-cut cases before the audit is invoked.
# --------------------------------------------------------------------------

DIMENSION_SEVERITY: dict[str, Severity] = {
    # Bullet-level (existing 9)
    "factual_fidelity": Severity.FATAL_INTEGRITY,
    "metric_fidelity": Severity.FATAL_INTEGRITY,
    "technology_fidelity": Severity.REPAIRABLE_QUALITY,
    "technical_guarantee_fidelity": Severity.REPAIRABLE_QUALITY,
    "relevance": Severity.REPAIRABLE_QUALITY,
    "star_xyz_coherence": Severity.REPAIRABLE_QUALITY,
    "readability": Severity.REPAIRABLE_QUALITY,
    "recruiter_scan_quality": Severity.REPAIRABLE_QUALITY,
    "ai_slop_risk": Severity.REPAIRABLE_QUALITY,
    # Whole-résumé (new 8)
    "metric_interpretability": Severity.REPAIRABLE_QUALITY,
    "interview_defensibility": Severity.REPAIRABLE_QUALITY,
    "whole_resume_positioning": Severity.REPAIRABLE_QUALITY,
    "skills_evidence_integrity": Severity.REPAIRABLE_QUALITY,
    "title_identity_fidelity": Severity.REPAIRABLE_QUALITY,
    "mechanism_outcome_balance": Severity.REPAIRABLE_QUALITY,
    "cross_bullet_repetition": Severity.REPAIRABLE_QUALITY,
    "misleading_implication": Severity.REPAIRABLE_QUALITY,
}


def dimension_severity(dimension_name: str) -> Severity:
    """Look up a dimension's severity tier. Unknown dimensions are treated
    as REPAIRABLE_QUALITY (fail toward repair, never toward silent fatal
    rejection, if the rubric ever grows a dimension this table hasn't
    been updated for yet)."""
    return DIMENSION_SEVERITY.get(dimension_name, Severity.REPAIRABLE_QUALITY)


def has_fatal_dimension(score_one_dimensions: Iterable[str]) -> bool:
    """True if any of the given (score==1) dimension names is fatal-tier."""
    return any(dimension_severity(name) == Severity.FATAL_INTEGRITY for name in score_one_dimensions)
