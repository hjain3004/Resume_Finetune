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
) -> RenderDoc:
    """Map accepted DraftResponse into RenderDoc IR."""
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
            experience.append(
                RenderEntry(
                    entry_id=exp.id,
                    heading=exp.employer,
                    subheading=exp.title,
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

    # Clean skills (filter out do_not_claim & Kubernetes)
    banned = {term.casefold() for term in profile.do_not_claim}
    banned.add("kubernetes")

    skills: dict[str, tuple[str, ...]] = {}
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
) -> str:
    """Render DraftResponse to LaTeX markup source string."""
    doc = render_doc_from_draft_response(draft, profile)
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
) -> tuple[Path, Path, RenderDoc]:
    """Render to .tex and compile to .pdf in out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = render_doc_from_draft_response(draft, profile)
    out_pdf = out_dir / "resume.pdf"
    render_latex(doc, template_path, out_pdf)
    tex_path = out_pdf.with_suffix(".tex")
    return tex_path, out_pdf, doc
