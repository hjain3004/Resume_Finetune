"""Arm (a): emit the user's interview-tested LaTeX template from a RenderDoc."""

import logging
import shutil
import subprocess
from pathlib import Path
from string import Template

from src.render.model import RenderDoc

logger = logging.getLogger(__name__)

# Backslash must be replaced first, so iterate the source once per character.
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(value: str) -> str:
    return "".join(_LATEX_ESCAPES.get(char, char) for char in value)


def _bullets(entry) -> list[str]:
    if not entry.bullets:
        return []
    return [
        r"\resumeItemListStart",
        *(rf"\resumeItem{{{escape_latex(b.text)}}}" for b in entry.bullets),
        r"\resumeItemListEnd",
    ]


def _education_block(entries) -> str:
    """\\resumeSubheading{institution}{location}{degree}{dates}"""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        lines.append(
            rf"\resumeSubheading{{{escape_latex(entry.heading)}}}"
            rf"{{{escape_latex(entry.location)}}}"
            rf"{{{escape_latex(entry.subheading)}}}"
            rf"{{{escape_latex(entry.date_range)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _experience_block(entries) -> str:
    """\\resumeSubheading{employer}{dates}{title}{location} -- slots 2 and 4 are
    swapped relative to Education. This asymmetry is the template's, not a bug."""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        lines.append(
            rf"\resumeSubheading{{{escape_latex(entry.heading)}}}"
            rf"{{{escape_latex(entry.date_range)}}}"
            rf"{{{escape_latex(entry.subheading)}}}"
            rf"{{{escape_latex(entry.location)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _projects_block(entries) -> str:
    r"""\resumeProjectHeading{\textbf{Name} $|$ \emph{tech} $|$ org}{dates}"""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        title = rf"\textbf{{{escape_latex(entry.heading)}}}"
        if entry.subheading:
            title += rf" $|$ \emph{{{escape_latex(entry.subheading)}}}"
        lines.append(
            rf"\resumeProjectHeading{{{title}}}{{{escape_latex(entry.date_range)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _skills_block(skills) -> str:
    r"""Free-form inline text, NOT a list:
    \textbf{Category}: term, term \textbar\ \textbf{Category}: ..."""
    chunks = [
        rf"\textbf{{{escape_latex(category)}}}: {escape_latex(', '.join(terms))}"
        for category, terms in skills.items()
    ]
    return "\\small\n" + " \\textbar\\ ".join(chunks)


def emit_latex_body(doc: RenderDoc) -> str:
    """Pure: RenderDoc -> LaTeX body. Bullet ids are stripped here (G0 boundary)."""
    groups = {
        "Education": lambda: _education_block(doc.education),
        "Experience": lambda: _experience_block(doc.experience),
        "Projects": lambda: _projects_block(doc.projects),
        "Skills": lambda: _skills_block(doc.skills),
        "Technical Skills": lambda: _skills_block(doc.skills),
    }
    parts = []
    for name in doc.section_order:
        builder = groups.get(name)
        if builder is None:
            continue
        parts.append(rf"\section{{{name}}}")
        parts.append(builder())
    return "\n".join(parts)


def render_latex(doc: RenderDoc, template_path: Path, out_pdf: Path) -> Path:
    """Substitute the body into the user's template and compile with pdflatex."""
    if shutil.which("pdflatex") is None:
        raise RuntimeError("pdflatex not found; arm (a) is un-runnable on this machine")

    template = Template(Path(template_path).read_text(encoding="utf-8"))
    source = template.safe_substitute(
        BODY=emit_latex_body(doc),
        NAME=escape_latex(doc.identity.get("name", "")),
        PHONE=escape_latex(doc.identity.get("phone", "")),
        EMAIL=escape_latex(doc.identity.get("email", "")),
        LINKEDIN=escape_latex(doc.identity.get("linkedin", "")),
        GITHUB=escape_latex(doc.identity.get("github", "")),
        LOCATION=escape_latex(doc.identity.get("location", "")),
    )

    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    tex_path = out_pdf.with_suffix(".tex")
    tex_path.write_text(source, encoding="utf-8")

    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory",
         str(out_pdf.parent), str(tex_path)],
        check=True,
        capture_output=True,
    )
    logger.info("rendered %s", out_pdf)
    return out_pdf
