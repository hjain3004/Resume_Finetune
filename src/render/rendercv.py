"""Arm (b): emit RenderCV YAML from a RenderDoc and invoke RenderCV."""

import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

from src.render.model import RenderDoc

logger = logging.getLogger(__name__)


def _entry_dicts(entries) -> list[dict[str, Any]]:
    out = []
    for entry in entries:
        item: dict[str, Any] = {
            "company": entry.heading,
            "position": entry.subheading,
        }
        if entry.date_range:
            item["date"] = entry.date_range
        if entry.location:
            item["location"] = entry.location
        if entry.bullets:
            item["highlights"] = [bullet.text for bullet in entry.bullets]
        out.append(item)
    return out


def emit_rendercv_yaml(doc: RenderDoc) -> dict[str, Any]:
    """Pure: RenderDoc -> RenderCV input dict. Bullet ids stripped (G0 boundary)."""
    sections: dict[str, Any] = {}
    for name in doc.section_order:
        if name == "Education":
            sections["education"] = _entry_dicts(doc.education)
        elif name == "Experience":
            sections["experience"] = _entry_dicts(doc.experience)
        elif name == "Projects":
            sections["projects"] = _entry_dicts(doc.projects)
        elif name == "Skills":
            sections["skills"] = [
                {"label": category, "details": ", ".join(terms)}
                for category, terms in doc.skills.items()
            ]
        elif name == "Technical Skills":
            sections["skills"] = [
                {"label": category, "details": ", ".join(terms)}
                for category, terms in doc.skills.items()
            ]

    return {
        "cv": {
            "name": doc.identity.get("name", ""),
            "email": doc.identity.get("email", ""),
            "phone": "+1-" + doc.identity.get("phone", "") if doc.identity.get("phone") and not doc.identity.get("phone", "").startswith("+") else doc.identity.get("phone", ""),
            "location": doc.identity.get("location", ""),
            "social_networks": [
                {"network": "LinkedIn", "username": doc.identity.get("linkedin", "")},
                {"network": "GitHub", "username": doc.identity.get("github", "")},
            ],
            "sections": sections,
        },
        "design": {"theme": "engineeringresumes"},
    }


def render_rendercv(doc: RenderDoc, out_pdf: Path) -> Path:
    """Write RenderCV YAML and invoke the renderer."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    yaml_path = out_pdf.with_suffix(".yaml")
    yaml_path.write_text(
        yaml.safe_dump(emit_rendercv_yaml(doc), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    subprocess.run(
        [".venv/bin/rendercv", "render", str(yaml_path),
         "--output-folder", str(out_pdf.parent)],
        check=True,
        capture_output=True,
    )
    logger.info("rendered %s via RenderCV", out_pdf)
    return out_pdf
