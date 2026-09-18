"""Rendering and L7 validation integration for Tailor2."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from string import Template
from src.profile import MasterProfile
from src.render.emphasis import parse_emphasis
from src.render.latex import emit_latex_body, escape_latex, render_latex
from src.render.lines import parse_rendered_lines
from src.render.model import RenderBullet, RenderDoc, RenderEntry
from src.render.parse import parse_pdf
from src.tailor2.models import DraftResponse

_SECTION_ORDER = ("Education", "Experience", "Projects", "Technical Skills")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def render_doc_from_draft_response(
    draft: DraftResponse,
    profile: MasterProfile,
    resolved_titles: dict[str, str] | None = None,
    filtered_skills: dict[str, tuple[str, ...]] | None = None,
) -> RenderDoc:
    """Map accepted DraftResponse into RenderDoc IR.

    `resolved_titles` (entry_id -> displayed title) and `filtered_skills`
    (category -> terms) let the caller supply the AUTO_CORRECTABLE-resolved
    state from audit_projection/validators (title mismatches corrected to
    canonical, Skills entries with no supporting evidence removed) so the
    rendered PDF matches what was actually audited. Both default to None,
    which preserves the exact prior behavior (canonical profile title,
    full profile.skills minus do_not_claim/Kubernetes)."""
    exp_by_id = {exp.id: exp for exp in profile.experience}
    proj_by_id = {proj.id: proj for proj in profile.projects}

    # Group bullets by entry_id in order of appearance
    bullets_by_entry: dict[str, list[RenderBullet]] = {}
    entry_order: list[str] = []

    for b in draft.bullets:
        if b.entry_id not in bullets_by_entry:
            bullets_by_entry[b.entry_id] = []
            entry_order.append(b.entry_id)

        try:
            plain, spans = parse_emphasis(b.text)
        except Exception:
            plain, spans = b.text, ()

        bullets_by_entry[b.entry_id].append(
            RenderBullet(bullet_id=b.bullet_id, text=plain, emphasis=spans)
        )

    # Build experience entries
    experience = []
    # Always include employers in draft order if present, or canonical experience order
    for exp_id in entry_order:
        if exp_id in exp_by_id:
            exp = exp_by_id[exp_id]
            displayed_title = (resolved_titles or {}).get(exp.id, exp.title)
            experience.append(
                RenderEntry(
                    entry_id=exp.id,
                    heading=exp.employer,
                    subheading=displayed_title,
                    date_range=exp.display_date,
                    bullets=tuple(bullets_by_entry[exp.id]),
                    tech_line=exp.tech_line,
                )
            )

    # Build project entries
    projects = []
    for proj_id in entry_order:
        if proj_id in proj_by_id:
            proj = proj_by_id[proj_id]
            projects.append(
                RenderEntry(
                    entry_id=proj.id,
                    heading=proj.display_title,
                    subheading=proj.tech_line,
                    date_range=proj.display_date,
                    bullets=tuple(bullets_by_entry[proj.id]),
                )
            )

    # Build education entries
    education = [
        RenderEntry(
            entry_id=_slugify(item["institution"]),
            heading=item["institution"],
            subheading=item["degree"],
            date_range=item.get("display_date", ""),
            location=item.get("location", ""),
        )
        for item in profile.education
    ]

    if filtered_skills is not None:
        skills = dict(filtered_skills)
    else:
        # Clean skills (filter out do_not_claim & Kubernetes) -- prior
        # behavior, preserved when no auto-corrected skill set is supplied.
        banned = {term.casefold() for term in profile.do_not_claim}
        banned.add("kubernetes")

        skills = {}
        for cat, items in profile.skills.items():
            skills[cat] = tuple(item for item in items if item.casefold() not in banned)

    return RenderDoc(
        identity=dict(profile.identity),
        education=tuple(education),
        experience=tuple(experience),
        projects=tuple(projects),
        skills=skills,
        section_order=_SECTION_ORDER,
        ats=dict(profile.ats),
    )


def render_draft_to_latex(
    draft: DraftResponse,
    profile: MasterProfile,
    template_path: Path = Path("profile/template.tex"),
    resolved_titles: dict[str, str] | None = None,
    filtered_skills: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Render DraftResponse to LaTeX markup source string."""
    doc = render_doc_from_draft_response(draft, profile, resolved_titles, filtered_skills)
    template = Template(Path(template_path).read_text(encoding="utf-8"))
    return template.safe_substitute(
        BODY=emit_latex_body(doc),
        NAME=escape_latex(doc.identity.get("name", "")),
        PHONE=escape_latex(doc.identity.get("phone", "")),
        EMAIL=escape_latex(doc.identity.get("email", "")),
        LINKEDIN=escape_latex(doc.identity.get("linkedin", "")),
        GITHUB=escape_latex(doc.identity.get("github", "")),
        LOCATION=escape_latex(doc.identity.get("location", "")),
    )


def compile_draft_to_pdf(
    draft: DraftResponse,
    profile: MasterProfile,
    out_dir: Path,
    template_path: Path = Path("profile/template.tex"),
    resolved_titles: dict[str, str] | None = None,
    filtered_skills: dict[str, tuple[str, ...]] | None = None,
) -> tuple[Path, Path, RenderDoc]:
    """Render to .tex and compile to .pdf in out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = render_doc_from_draft_response(draft, profile, resolved_titles, filtered_skills)
    out_pdf = out_dir / "resume.pdf"
    render_latex(doc, template_path, out_pdf)
    tex_path = out_pdf.with_suffix(".tex")
    return tex_path, out_pdf, doc
