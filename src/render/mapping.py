"""Pure mapping from the validated master profile to the render IR."""

import logging
import re

from src.profile import MasterProfile
from src.render.model import RenderBullet, RenderDoc, RenderEntry

logger = logging.getLogger(__name__)

_TIER_FALLBACK = ("medium", "short")
_SECTION_ORDER = ("Education", "Experience", "Projects", "Technical Skills")


class RenderMappingError(ValueError):
    """Raised when the profile cannot be mapped without losing content."""


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _resolve_text(bullet, requested: str | None) -> str:
    """Pick the phrasing. A requested-but-absent tier is an error, not a downgrade."""
    if requested is not None:
        if requested not in ("short", "medium", "long"):
            raise RenderMappingError(
                f"bullet {bullet.id!r}: unknown phrasing tier {requested!r}"
            )
        text = getattr(bullet.phrasings, requested, None)
        if text is None:
            raise RenderMappingError(
                f"bullet {bullet.id!r}: requested phrasing tier {requested!r} is not "
                f"defined; refusing to silently substitute another tier"
            )
        return text
    for tier in _TIER_FALLBACK:
        text = getattr(bullet.phrasings, tier, None)
        if text is not None:
            return text
    return bullet.phrasings.short


def build_render_doc(
    profile: MasterProfile,
    base_variant: str,
    tier_overrides: dict[str, str] | None = None,
) -> RenderDoc:
    """Resolve a base variant into the renderer-agnostic IR.

    Raises RenderMappingError if a bullet id is unresolvable, an override names
    an unknown bullet, or a section name is not permitted by the ATS whitelist.
    """
    overrides = tier_overrides or {}

    # _ordered_bullets raises ProfileValidationError for an unknown variant.
    ordered = profile._ordered_bullets(base_variant)
    wanted_ids = [bullet.id for _, bullet in ordered]

    unknown_overrides = set(overrides) - set(wanted_ids)
    if unknown_overrides:
        raise RenderMappingError(
            f"tier_overrides reference bullet ids absent from base_variant "
            f"{base_variant!r}: {sorted(unknown_overrides)}"
        )

    selected = {
        bullet.id: RenderBullet(
            bullet_id=bullet.id,
            text=_resolve_text(bullet, overrides.get(bullet.id)),
        )
        for _, bullet in ordered
    }

    def _entry_bullets(source_bullets) -> tuple[RenderBullet, ...]:
        return tuple(selected[b.id] for b in source_bullets if b.id in selected)

    variant_projects = set(profile.base_variants[base_variant].projects)
    projects = tuple(
        RenderEntry(
            entry_id=project.id,
            heading=project.display_title,
            subheading=project.tech_line,
            date_range=project.display_date,
            bullets=_entry_bullets(project.bullets),
        )
        for project in profile.projects
        if project.id in variant_projects
    )

    experience = tuple(
        RenderEntry(
            entry_id=exp.id,
            heading=exp.employer,
            subheading=exp.title,
            date_range=exp.display_date,
            bullets=_entry_bullets(exp.bullets),
        )
        for exp in profile.experience
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

    emitted = [
        bullet.bullet_id
        for group in (education, experience, projects)
        for entry in group
        for bullet in entry.bullets
    ]
    missing = set(wanted_ids) - set(emitted)
    if missing:
        raise RenderMappingError(
            f"base_variant {base_variant!r} orders bullet ids that no project or "
            f"experience in this variant owns: {sorted(missing)}"
        )

    whitelist = set(profile.ats.get("headings_whitelist", ()))
    illegal = [name for name in _SECTION_ORDER if name not in whitelist]
    if illegal:
        raise RenderMappingError(
            f"section name(s) {illegal} absent from ats.headings_whitelist "
            f"{sorted(whitelist)}"
        )

    return RenderDoc(
        identity=dict(profile.identity),
        education=education,
        experience=experience,
        projects=projects,
        skills={k: tuple(v) for k, v in profile.skills.items()},
        section_order=_SECTION_ORDER,
        ats=dict(profile.ats),
    )
