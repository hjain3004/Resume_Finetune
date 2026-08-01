"""L7 parseability gate: does the PDF an ATS reads still say what we meant?

Every check returns a list of violation strings (empty == pass), matching the
convention in src/tailor/lint.py.
"""

import logging

from src.render.model import RenderDoc
from src.render.parse import ParsedPdf

logger = logging.getLogger(__name__)

_IDENTITY_FIELDS = ("name", "phone", "email", "location")


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def check_identity_survives(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    violations = []
    for field in _IDENTITY_FIELDS:
        value = doc.identity.get(field, "")
        if not value:
            continue
        if _normalize(value) not in haystack:
            violations.append(
                f"L7 identity: {field} {value!r} did not survive PDF extraction"
            )
    return violations


def check_bullets_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    return [
        f"L7 bullet: {bullet.bullet_id} did not survive PDF extraction"
        for bullet in doc.all_bullets()
        if _normalize(bullet.text) not in haystack
    ]


def check_skills_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    return [
        f"L7 skills: term {term!r} did not survive PDF extraction"
        for term in doc.all_skill_terms()
        if _normalize(term) not in haystack
    ]


def check_charset(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    forbidden = doc.ats.get("forbidden_chars", ())
    text = parsed.text
    return [
        f"L7 charset: forbidden character {char!r} present in rendered text"
        for char in forbidden
        if char in text
    ]


def check_file_size(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    limit_mb = doc.ats.get("max_file_size_mb")
    if limit_mb is None:
        return []
    actual_mb = parsed.size_bytes / (1024 * 1024)
    if actual_mb > float(limit_mb):
        return [
            f"L7 size: PDF is {actual_mb:.2f} MB, exceeds ats.max_file_size_mb "
            f"of {limit_mb}"
        ]
    return []
