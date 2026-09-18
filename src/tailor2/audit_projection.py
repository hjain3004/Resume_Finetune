"""Builds the complete résumé projection the auditor evaluates.

Design decision: the pre-existing auditor only ever saw isolated bullet
text plus that bullet's own cited evidence (see prompts.build_audit_prompt
before this change). It could not see the employer's displayed title, the
Skills section, whether a requirement was silently dropped, or whether the
word "agentic" appeared in three other bullets it never saw -- so it could
not catch title mismatches, unsupported Skills entries, or cross-bullet
repetition even in principle. This module assembles everything the task
requires the auditor to see (still never the drafter's chain-of-thought or
persuasive rationale -- only the final structured facts) into one
JSON-serializable projection, used for both the audit and re-audit prompts.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from src.profile import MasterProfile
from src.tailor2.models import DraftResponse
from src.tailor2.title_policy import TitleResolution, resolve_displayed_title


@dataclasses.dataclass(frozen=True)
class ProjectionBullet:
    bullet_id: str
    text: str
    evidence_ids: list[str]
    cited_evidence: list[dict[str, Any]]  # id, canonical_phrasing_medium, evidence, defense, interview_risk


@dataclasses.dataclass(frozen=True)
class ProjectionEntry:
    entry_id: str
    kind: str  # "Experience" | "Projects"
    heading: str  # employer name or project display_title
    displayed_title_or_tech: str  # experience title (post title_policy resolution) or project tech_line
    title_was_auto_corrected: bool
    bullets: list[ProjectionBullet]


SEMANTIC_SKILL_ALIASES: dict[str, frozenset[str]] = {
    "postgres": frozenset({"postgres", "postgresql", "postgres db", "postgresql db"}),
    "postgresql": frozenset({"postgres", "postgresql", "postgres db", "postgresql db"}),
    "react": frozenset({"react", "react.js", "reactjs"}),
    "react.js": frozenset({"react", "react.js", "reactjs"}),
    "reactjs": frozenset({"react", "react.js", "reactjs"}),
    "asyncio": frozenset({"asyncio", "async", "aio"}),
    "async": frozenset({"asyncio", "async", "aio"}),
    "kafka": frozenset({"kafka", "apache kafka"}),
    "apache kafka": frozenset({"kafka", "apache kafka"}),
    "fastapi": frozenset({"fastapi", "fastapi microservices"}),
    "fastapi microservices": frozenset({"fastapi", "fastapi microservices"}),
}


def get_skill_aliases(term: str) -> set[str]:
    low = term.strip().casefold()
    return set(SEMANTIC_SKILL_ALIASES.get(low, frozenset({low}))) | {low}


@dataclasses.dataclass(frozen=True)
class SkillTermProjection:
    term: str
    canonical_support: bool = True
    selected_demonstration: bool = False
    target_relevance: bool = True
    display_decision: bool = True
    evidence_ids: list[str] = dataclasses.field(default_factory=list)
    canonical_evidence_ids: list[str] = dataclasses.field(default_factory=list)
    supported: bool = True

    def __post_init__(self) -> None:
        if not self.canonical_support and self.supported:
            object.__setattr__(self, "supported", False)
        elif not self.supported and self.canonical_support:
            object.__setattr__(self, "canonical_support", False)
        if not self.canonical_support:
            object.__setattr__(self, "display_decision", False)


@dataclasses.dataclass(frozen=True)
class RequirementCoverage:
    id: str
    term: str
    importance: str
    covered: bool
    supporting_bullet_ids: list[str]


@dataclasses.dataclass(frozen=True)
class ResumeProjection:
    company: str
    title: str
    variant: str
    section_order: list[str]
    entries: list[ProjectionEntry]
    skills: dict[str, list[SkillTermProjection]]
    requirement_coverage: list[RequirementCoverage]
    omission_ledger: list[dict[str, Any]]
    model_identities: dict[str, dict[str, str]]
    title_auto_corrections: list[str]
    title_resolutions: list[TitleResolution] = dataclasses.field(default_factory=list)


def _evidence_summary(ev: Any) -> dict[str, Any]:
    return {
        "id": ev.id,
        "canonical_phrasing_medium": getattr(getattr(ev, "phrasings", None), "medium", ""),
        "evidence": ev.evidence,
        "defense": getattr(ev, "defense", "") or "",
        "interview_risk": getattr(ev, "interview_risk", "") or "",
    }


def _text_matches_skill(text: str, term: str) -> bool:
    import re
    aliases = get_skill_aliases(term)
    text_lower = text.casefold()
    for a in aliases:
        pattern = r"(?<!\w)" + re.escape(a) + r"(?!\w)"
        if re.search(pattern, text_lower):
            return True
    return False


def _evidence_matches_term(ev: Any, term: str) -> bool:
    if ev is None:
        return False
    ph = getattr(ev, "phrasings", None)
    if ph:
        for attr in ("short", "medium", "long"):
            val = getattr(ph, attr, "")
            if val and _text_matches_skill(str(val), term):
                return True
    if hasattr(ev, "text") and ev.text and _text_matches_skill(str(ev.text), term):
        return True
    ev_text = getattr(ev, "evidence", "")
    if ev_text:
        if isinstance(ev_text, (list, tuple)):
            for item in ev_text:
                if _text_matches_skill(str(item), term):
                    return True
        elif _text_matches_skill(str(ev_text), term):
            return True
    kws = getattr(ev, "keywords_hit", ()) or ()
    for kw in kws:
        if _text_matches_skill(str(kw), term):
            return True
    return False


def _resolve_skills(
    profile: MasterProfile,
    evidence_by_id: dict[str, Any],
    selected_evidence_ids: set[str],
    skills_by_category: dict[str, list[str]] | None = None,
) -> dict[str, list[SkillTermProjection]]:
    """Resolve skills using the 4-tier model:
    1. canonical_support: supported anywhere in verified master profile or profile.skills.
    2. selected_demonstration: visibly demonstrated by selected evidence for this run.
    3. target_relevance: relevant to the target role / JD context.
    4. display_decision: selected for display on the tailored resume.

    Semantic aliases (e.g. Postgres <-> PostgreSQL) resolve to the same concept.
    Banned terms (Kubernetes, do_not_claim) have canonical_support = False and are auto-corrected.
    Canonically supported terms lacking selected demonstration remain on the resume,
    generating an advisory notice rather than automatic removal.
    """
    banned = {t.casefold() for t in profile.do_not_claim}
    banned.add("kubernetes")

    profile_skill_terms = {
        t.casefold()
        for cat_terms in profile.skills.values()
        for t in cat_terms
    }

    target_skills = skills_by_category if skills_by_category is not None else profile.skills
    result: dict[str, list[SkillTermProjection]] = {}

    for category, terms in target_skills.items():
        projected: list[SkillTermProjection] = []
        for term in terms:
            term_clean = term.strip()
            aliases = get_skill_aliases(term_clean)
            is_banned = any(a in banned for a in aliases)

            all_supporting_eids = [
                eid for eid, ev in evidence_by_id.items()
                if _evidence_matches_term(ev, term_clean)
            ]

            if is_banned:
                canonical_support = False
            elif any(a in profile_skill_terms for a in aliases) or len(all_supporting_eids) > 0:
                canonical_support = True
            else:
                canonical_support = False

            if canonical_support:
                supporting_selected = [
                    eid for eid in all_supporting_eids
                    if eid in selected_evidence_ids
                ]
                selected_demonstration = len(supporting_selected) > 0
                display_decision = True
            else:
                supporting_selected = []
                selected_demonstration = False
                display_decision = False

            projected.append(
                SkillTermProjection(
                    term=term_clean,
                    canonical_support=canonical_support,
                    selected_demonstration=selected_demonstration,
                    target_relevance=True,
                    display_decision=display_decision,
                    evidence_ids=supporting_selected,
                    canonical_evidence_ids=all_supporting_eids,
                    supported=canonical_support,
                )
            )
        result[category] = projected

    return result


def _resolve_requirement_coverage(draft: DraftResponse) -> list[RequirementCoverage]:
    supported_req_ids: set[str] = set()
    supporting_bullets_by_req: dict[str, list[str]] = {}
    for b in draft.bullets:
        for rid in b.supported_requirement_ids:
            supported_req_ids.add(rid)
            supporting_bullets_by_req.setdefault(rid, []).append(b.bullet_id)

    coverage = []
    for req in draft.atomic_requirements:
        covered = req.id in supported_req_ids
        coverage.append(
            RequirementCoverage(
                id=req.id,
                term=req.term,
                importance=req.importance,
                covered=covered,
                supporting_bullet_ids=supporting_bullets_by_req.get(req.id, []),
            )
        )
    return coverage


def build_resume_projection(
    draft: DraftResponse,
    profile: MasterProfile,
    company: str,
    title: str,
    variant: str,
    model_identities: dict[str, dict[str, str]],
) -> ResumeProjection:
    """Pure: DraftResponse + profile + run context -> ResumeProjection.

    Applies title_policy resolution to every Experience entry's displayed
    title, so the projection the auditor sees already reflects what would
    actually render -- the auditor is checking the resolved state, not
    re-deriving it."""
    exp_by_id = {exp.id: exp for exp in profile.experience}
    proj_by_id = {proj.id: proj for proj in profile.projects}
    evidence_by_id: dict[str, Any] = {}
    for exp in profile.experience:
        for b in exp.bullets:
            evidence_by_id[b.id] = b
    for proj in profile.projects:
        for b in proj.bullets:
            evidence_by_id[b.id] = b

    bullets_by_entry: dict[str, list[ProjectionBullet]] = {}
    entry_order: list[str] = []
    for b in draft.bullets:
        if b.entry_id not in bullets_by_entry:
            bullets_by_entry[b.entry_id] = []
            entry_order.append(b.entry_id)
        cited = [_evidence_summary(evidence_by_id[eid]) for eid in b.evidence_ids if eid in evidence_by_id]
        bullets_by_entry[b.entry_id].append(
            ProjectionBullet(bullet_id=b.bullet_id, text=b.text, evidence_ids=list(b.evidence_ids), cited_evidence=cited)
        )

    entries: list[ProjectionEntry] = []
    title_auto_corrections: list[str] = []
    title_resolutions: list[TitleResolution] = []
    for entry_id in entry_order:
        if entry_id in exp_by_id:
            exp = exp_by_id[entry_id]
            resolution = resolve_displayed_title(
                entry_id, draft.entry_title_overrides.get(entry_id), exp.title
            )
            title_resolutions.append(resolution)
            if resolution.was_auto_corrected:
                title_auto_corrections.append(resolution.authority_note)
            entries.append(
                ProjectionEntry(
                    entry_id=entry_id,
                    kind="Experience",
                    heading=exp.employer,
                    displayed_title_or_tech=resolution.final_title,
                    title_was_auto_corrected=resolution.was_auto_corrected,
                    bullets=bullets_by_entry[entry_id],
                )
            )
        elif entry_id in proj_by_id:
            proj = proj_by_id[entry_id]
            entries.append(
                ProjectionEntry(
                    entry_id=entry_id,
                    kind="Projects",
                    heading=proj.display_title,
                    displayed_title_or_tech=proj.tech_line,
                    title_was_auto_corrected=False,
                    bullets=bullets_by_entry[entry_id],
                )
            )

    skills = _resolve_skills(profile, evidence_by_id, set(draft.selected_evidence_ids))
    requirement_coverage = _resolve_requirement_coverage(draft)

    return ResumeProjection(
        company=company,
        title=title,
        variant=variant,
        section_order=list(draft.section_order),
        entries=entries,
        skills=skills,
        requirement_coverage=requirement_coverage,
        omission_ledger=[dataclasses.asdict(om) for om in draft.amdocs_omission_ledger],
        model_identities=model_identities,
        title_auto_corrections=title_auto_corrections,
        title_resolutions=title_resolutions,
    )


def projection_to_dict(projection: ResumeProjection) -> dict[str, Any]:
    return dataclasses.asdict(projection)


def unsupported_skill_terms(projection: ResumeProjection) -> list[tuple[str, str]]:
    """(category, term) pairs where canonical_support is False."""
    return [
        (category, s.term)
        for category, terms in projection.skills.items()
        for s in terms
        if not s.canonical_support
    ]


def weakly_demonstrated_skill_terms(projection: ResumeProjection) -> list[tuple[str, str]]:
    """(category, term) pairs where canonical_support is True but selected_demonstration is False."""
    return [
        (category, s.term)
        for category, terms in projection.skills.items()
        for s in terms
        if s.canonical_support and not s.selected_demonstration
    ]


def check_skills_advisories(projection: ResumeProjection) -> list[str]:
    """Advisory notices for canonically supported skills not demonstrated in selected bullets."""
    return [
        f"Skills advisory: {category!r} term {term!r} is canonically supported in profile but not demonstrated in selected bullets for this run"
        for category, term in weakly_demonstrated_skill_terms(projection)
    ]
