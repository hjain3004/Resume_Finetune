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


def check_page_count(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    max_pages = doc.ats.get("max_pages")
    if max_pages is None:
        return []
    if parsed.page_count > max_pages:
        return [f"L7 size: PDF has {parsed.page_count} pages, exceeds ats.max_pages of {max_pages}"]
    return []


_COLUMN_SEPARATION_RATIO = 0.25
_COLUMN_POPULATION_FLOOR = 0.25
_HEADER_BAND_RATIO = 0.99

#: pdfminer text containers include leading, so adjacent lines routinely share a
#: point or two of vertical extent. Only a larger intersection is real collision.
_OVERLAP_TOLERANCE_PT = 2.0
#: Text reaching past this far outside the page is off the paper, not kerning.
_PAGE_BLEED_TOLERANCE_PT = 1.0


def check_no_overlap(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Text printed through other text. Extraction cannot see this; a reader can.

    A page overflow is loud, but crushed vertical spacing fails silently: every
    string still extracts, so every content check passes while the page is
    visibly broken.
    """
    violations = []
    by_page: dict[int, list] = {}
    for box in parsed.boxes:
        if box.text.strip():
            by_page.setdefault(box.page, []).append(box)

    for page, boxes in sorted(by_page.items()):
        for index, first in enumerate(boxes):
            for second in boxes[index + 1:]:
                overlap_y = min(first.y1, second.y1) - max(first.y0, second.y0)
                overlap_x = min(first.x1, second.x1) - max(first.x0, second.x0)
                if overlap_y > _OVERLAP_TOLERANCE_PT and overlap_x > 0:
                    violations.append(
                        f"L7 layout: page {page} text collision of "
                        f"{overlap_y:.1f}pt between "
                        f"{first.text.strip()[:40]!r} and "
                        f"{second.text.strip()[:40]!r}"
                    )
    return violations


def check_within_page(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Text running off the paper. Extraction still sees it; nobody can read it."""
    violations = []
    for box in parsed.boxes:
        if not box.text.strip():
            continue
        if box.x1 > parsed.page_width + _PAGE_BLEED_TOLERANCE_PT:
            violations.append(
                f"L7 layout: page {box.page} text extends "
                f"{box.x1 - parsed.page_width:.1f}pt past the right page edge: "
                f"{box.text.strip()[:40]!r}"
            )
        elif box.x0 < -_PAGE_BLEED_TOLERANCE_PT:
            violations.append(
                f"L7 layout: page {box.page} text starts {-box.x0:.1f}pt "
                f"left of the page: {box.text.strip()[:40]!r}"
            )
    return violations


def check_single_column(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Flag a bimodal x distribution: the classic ATS reading-order killer."""
    if doc.ats.get("layout", {}).get("columns", 1) != 1:
        return []

    pages: dict[int, list] = {}
    for box in parsed.boxes:
        pages.setdefault(box.page, []).append(box)

    threshold = parsed.page_width * _COLUMN_SEPARATION_RATIO
    violations = []
    for page, boxes in sorted(pages.items()):
        if len(boxes) < 4:
            continue
        starts = sorted(box.x0 for box in boxes)
        split_at = next(
            (i for i in range(1, len(starts))
             if starts[i] - starts[i - 1] > threshold),
            None,
        )
        if split_at is None:
            continue
        left, right = starts[:split_at], starts[split_at:]
        floor = len(boxes) * _COLUMN_POPULATION_FLOOR
        if len(left) >= floor and len(right) >= floor:
            violations.append(
                f"L7 layout: page {page} has two column clusters "
                f"(x~{left[0]:.0f} and x~{right[0]:.0f}); ats.layout.columns is 1"
            )
    return violations


def check_contact_in_body(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Contact details in a true header/footer are dropped by Greenhouse."""
    if not doc.ats.get("layout", {}).get("contact_in_body", True):
        return []
    name = doc.identity.get("name", "")
    if not name:
        return []
    body_ceiling = parsed.page_height * _HEADER_BAND_RATIO
    for box in parsed.boxes:
        if _normalize(name) in _normalize(box.text) and box.y1 <= body_ceiling:
            return []
    return [
        "L7 layout: contact block sits in the header band, not the document body; "
        "ats.layout.contact_in_body is true"
    ]


def check_section_headings(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    violations = []
    whitelist = doc.ats.get("headings_whitelist")
    if whitelist:
        illegal = [n for n in doc.section_order if n not in whitelist]
        if illegal:
            violations.append(
                f"L7 headings: section name(s) {illegal} not in ats.headings_whitelist"
            )

    positions = []
    for name in doc.section_order:
        target = _normalize(name)
        found = next(
            (i for i, box in enumerate(parsed.boxes) if target in _normalize(box.text)),
            None,
        )
        if found is None:
            violations.append(
                f"L7 headings: section {name!r} did not survive PDF extraction"
            )
        else:
            positions.append((name, found))

    for (prev_name, prev_idx), (name, idx) in zip(positions, positions[1:]):
        if idx <= prev_idx:
            violations.append(
                f"L7 headings: {name!r} appears before {prev_name!r} in reading "
                f"order; ATS section attribution will be wrong"
            )
    return violations


def run_l7(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Aggregate every L7 check. Empty list == the PDF is deliverable."""
    violations: list[str] = []
    for check in (
        check_identity_survives,
        check_bullets_survive,
        check_skills_survive,
        check_charset,
        check_file_size,
        check_page_count,
        check_single_column,
        check_contact_in_body,
        check_section_headings,
        check_no_overlap,
        check_within_page,
    ):
        violations.extend(check(doc, parsed))
    logger.info("L7: %d violation(s)", len(violations))
    return violations
