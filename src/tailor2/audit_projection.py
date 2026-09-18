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
from src.tailor2.title_policy import resolve_displayed_title


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


@dataclasses.dataclass(frozen=True)
class SkillTermProjection:
    term: str
    supported: bool
    evidence_ids: list[str]


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


def _evidence_summary(ev: Any) -> dict[str, Any]:
    return {
        "id": ev.id,
        "canonical_phrasing_medium": getattr(getattr(ev, "phrasings", None), "medium", ""),
        "evidence": ev.evidence,
        "defense": getattr(ev, "defense", "") or "",
        "interview_risk": getattr(ev, "interview_risk", "") or "",
    }


def _resolve_skills(profile: MasterProfile, evidence_by_id: dict[str, Any], selected_evidence_ids: set[str]) -> dict[str, list[SkillTermProjection]]:
    """Every skill term the profile lists, marked as supported only if it is
    a substring (case-insensitive) of some cited evidence's canonical
    phrasing/evidence/keywords for a bullet actually selected this run.
    Deterministic and conservative: a term is "supported" only when the
    run's own selected evidence backs it, not merely because it appears
    somewhere in the whole profile."""
    banned = {t.casefold() for t in profile.do_not_claim}
    banned.add("kubernetes")

    haystacks: list[str] = []
    for eid in selected_evidence_ids:
        ev = evidence_by_id.get(eid)
        if ev is None:
            continue
        haystacks.append(str(getattr(getattr(ev, "phrasings", None), "medium", "")))
        haystacks.append(str(getattr(getattr(ev, "phrasings", None), "long", "")))
        ev_text = ev.evidence
        if isinstance(ev_text, (list, tuple)):
            haystacks.extend(str(x) for x in ev_text)
        else:
            haystacks.append(str(ev_text))
        haystacks.extend(str(k) for k in getattr(ev, "keywords_hit", ()) or ())
    combined = " \n ".join(haystacks).casefold()

    result: dict[str, list[SkillTermProjection]] = {}
    for category, terms in profile.skills.items():
        projected = []
        for term in terms:
            if term.casefold() in banned:
                continue
            supported = term.casefold() in combined
            # Which selected evidence ids actually mention it (best-effort,
            # for auditor traceability -- not used to gate anything itself).
            supporting = [
                eid
                for eid in selected_evidence_ids
                if evidence_by_id.get(eid) is not None
                and term.casefold() in " ".join(
                    [
                        str(getattr(getattr(evidence_by_id[eid], "phrasings", None), "medium", "")),
                        str(getattr(getattr(evidence_by_id[eid], "phrasings", None), "long", "")),
                        str(evidence_by_id[eid].evidence),
                    ]
                ).casefold()
            ]
            projected.append(SkillTermProjection(term=term, supported=supported, evidence_ids=supporting))
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
    for entry_id in entry_order:
        if entry_id in exp_by_id:
            exp = exp_by_id[entry_id]
            resolution = resolve_displayed_title(
                entry_id, draft.entry_title_overrides.get(entry_id), exp.title
            )
            if resolution.was_auto_corrected:
                title_auto_corrections.append(
                    f"entry {entry_id!r}: proposed title {resolution.proposed_title!r} is not canonical or an "
                    f"approved variant; corrected to canonical title {resolution.canonical_title!r}"
                )
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
    )


def projection_to_dict(projection: ResumeProjection) -> dict[str, Any]:
    return dataclasses.asdict(projection)


def unsupported_skill_terms(projection: ResumeProjection) -> list[tuple[str, str]]:
    """(category, term) pairs whose `supported` flag is False."""
    return [
        (category, s.term)
        for category, terms in projection.skills.items()
        for s in terms
        if not s.supported
    ]
