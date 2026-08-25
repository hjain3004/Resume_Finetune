"""Map an accepted TailoredDraft onto the render IR by re-hydrating identity,
education, and ATS policy from the local master profile and binding the two
together by alignment fingerprint. Pure: no filesystem, no subprocess."""
from __future__ import annotations

import hashlib
import json
import re

from src.profile import MasterProfile
from src.render.emphasis import EmphasisError, parse_emphasis
from src.render.model import RenderBullet, RenderDoc, RenderEntry
from src.tailor.alignment_view import AlignmentError, default_alignment_bullet
from src.tailor.s3 import DraftBullet, TailoredDraft

SECTION_ORDER = ("Education", "Experience", "Projects", "Technical Skills")


class TailoredRenderError(ValueError):
    """Raised when a TailoredDraft cannot be rendered without losing or
    fabricating content."""


def _slugify(value: str) -> str:
    """Re-implementation of src/render/mapping.py's private _slugify: a
    private name is not imported across the M8P-5/M8P-3 boundary."""
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _canonical_projection(profile: MasterProfile, draft: TailoredDraft) -> dict:
    """Re-implementation of src/tailor/alignment_view.py's private
    _canonical_dict, applied to the draft's own structural projection
    (its base_variant, project_ids, experience_ids, and bullet order) with
    CANONICAL (unedited) bullet text pulled fresh from the profile -- never
    the draft's own (possibly edited) text. This is what alignment_fingerprint
    binds to."""
    bullet_ids = tuple(bullet.bullet_id for bullet in draft.bullets)
    try:
        canonical_bullets = tuple(default_alignment_bullet(profile, bullet_id) for bullet_id in bullet_ids)
    except AlignmentError as exc:
        raise TailoredRenderError(f"bullet {exc}") from exc
    return {
        "base_variant": draft.base_variant,
        "project_ids": list(draft.project_ids),
        "experience_ids": list(draft.experience_ids),
        "bullets": [
            {
                "bullet_id": bullet.bullet_id,
                "owner_id": bullet.owner_id,
                "owner_kind": bullet.owner_kind,
                "source_text": bullet.source_text,
                "plain_text": bullet.plain_text,
                "emphasis": [[start, end] for start, end in bullet.emphasis],
                "keywords_hit": list(bullet.keywords_hit),
                "claim_type": bullet.claim_type,
            }
            for bullet in canonical_bullets
        ],
        "skills": [[category, list(items)] for category, items in profile.skills.items()],
        "do_not_claim": list(profile.do_not_claim),
    }


def _fingerprint(projection: dict) -> str:
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _to_render_bullet(bullet: DraftBullet) -> RenderBullet:
    try:
        plain, spans = parse_emphasis(bullet.text)
    except EmphasisError as exc:
        raise TailoredRenderError(f"bullet {bullet.bullet_id}: invalid emphasis: {exc}") from exc
    if plain != bullet.plain_text or spans != bullet.emphasis:
        raise TailoredRenderError(
            f"bullet {bullet.bullet_id}: stored plain_text/emphasis does not match "
            f"its own marked text"
        )
    return RenderBullet(bullet_id=bullet.bullet_id, text=plain, emphasis=spans)


def render_doc_from_draft(profile: MasterProfile, draft: TailoredDraft) -> RenderDoc:
    """Rehydrate identity/education/ATS from the profile and bind them to
    `draft` by recomputing its alignment fingerprint. Fails closed on any
    unknown id, orphan bullet, text/emphasis disagreement, illegal section
    name, or fingerprint mismatch -- never silently drops or substitutes."""
    project_by_id = {project.id: project for project in profile.projects}
    experience_by_id = {exp.id: exp for exp in profile.experience}

    unknown_projects = [pid for pid in draft.project_ids if pid not in project_by_id]
    if unknown_projects:
        raise TailoredRenderError(f"unknown project id(s): {sorted(unknown_projects)}")
    unknown_experiences = [eid for eid in draft.experience_ids if eid not in experience_by_id]
    if unknown_experiences:
        raise TailoredRenderError(f"unknown experience id(s): {sorted(unknown_experiences)}")

    selected_projects = set(draft.project_ids)
    selected_experiences = set(draft.experience_ids)
    for bullet in draft.bullets:
        if bullet.owner_kind == "project" and bullet.owner_id not in selected_projects:
            raise TailoredRenderError(
                f"bullet {bullet.bullet_id}: owner {bullet.owner_id!r} is not among the selected projects"
            )
        if bullet.owner_kind == "experience" and bullet.owner_id not in selected_experiences:
            raise TailoredRenderError(
                f"bullet {bullet.bullet_id}: owner {bullet.owner_id!r} is not among the selected experience"
            )

    render_bullets_by_id = {bullet.bullet_id: _to_render_bullet(bullet) for bullet in draft.bullets}

    expected_fingerprint = _fingerprint(_canonical_projection(profile, draft))
    if draft.alignment_fingerprint != expected_fingerprint:
        raise TailoredRenderError(
            "alignment_fingerprint does not match the local profile's canonical projection"
        )

    whitelist = set(profile.ats.get("headings_whitelist", ()))
    illegal = [name for name in SECTION_ORDER if name not in whitelist]
    if illegal:
        raise TailoredRenderError(
            f"section name(s) {illegal} absent from ats.headings_whitelist {sorted(whitelist)}"
        )

    def _entry_bullets(owner_id: str) -> tuple[RenderBullet, ...]:
        return tuple(
            render_bullets_by_id[bullet.bullet_id]
            for bullet in draft.bullets
            if bullet.owner_id == owner_id
        )

    projects = tuple(
        RenderEntry(
            entry_id=project.id,
            heading=project.display_title,
            subheading=project.tech_line,
            date_range=project.display_date,
            bullets=_entry_bullets(project.id),
        )
        for project in profile.projects
        if project.id in selected_projects
    )

    experience = tuple(
        RenderEntry(
            entry_id=exp.id,
            heading=exp.employer,
            subheading=exp.title,
            date_range=exp.display_date,
            bullets=_entry_bullets(exp.id),
        )
        for exp in profile.experience
        if exp.id in selected_experiences
    )

    education = tuple(
        RenderEntry(
            entry_id=_slugify(item["institution"]),
            heading=item["institution"],
            subheading=item["degree"],
            date_range=item.get("display_date", ""),
            location=item.get("location", ""),
        )
        for item in profile.education
    )

    return RenderDoc(
        identity=dict(profile.identity),
        education=education,
        experience=experience,
        projects=projects,
        skills={category: tuple(terms) for category, terms in draft.skills},
        section_order=SECTION_ORDER,
        ats=dict(profile.ats),
    )


def modified_bullet_ids(draft: TailoredDraft, canonical_text_by_id: dict[str, str]) -> frozenset[str]:
    """Bullet ids whose draft plain_text differs from the given canonical
    plain text. A bullet id absent from `canonical_text_by_id` counts as
    unmodified (nothing to compare against)."""
    return frozenset(
        bullet.bullet_id
        for bullet in draft.bullets
        if bullet.bullet_id in canonical_text_by_id
        and bullet.plain_text != canonical_text_by_id[bullet.bullet_id]
    )
