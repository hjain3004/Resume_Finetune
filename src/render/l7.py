"""L7 parseability gate: does the PDF an ATS reads still say what we meant?

Every check returns a list of violation strings (empty == pass), matching the
convention in src/tailor/lint.py.
"""

import logging
import re
from collections import Counter

from src.render.lines import RenderedPage, locate_text_lines, normalize
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


def _known_date_ranges(doc: RenderDoc) -> tuple[str, ...]:
    return tuple(
        entry.date_range
        for group in (doc.education, doc.experience, doc.projects)
        for entry in group
        if entry.date_range
    )


def _haystack_without_date_ranges(doc: RenderDoc, parsed: ParsedPdf) -> str:
    """M8V-1 3b: a right-aligned project/experience date range can land, in
    PDF extraction order, between a bullet's two wrapped physical lines
    (confirmed live: sepsis_b5's continuation was split by its project's
    own date range). Stripping every KNOWN date range this document
    actually declares -- never an arbitrary token -- and re-collapsing
    whitespace rejoins the bullet's own wrapped halves without touching
    anything else. A bullet that is genuinely missing stays missing: this
    can only ever remove text that was never part of the bullet."""
    stripped = parsed.normalized_text
    for date_range in _known_date_ranges(doc):
        stripped = stripped.replace(_normalize(date_range), " ")
    return _normalize(stripped)


def check_bullets_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    stripped_haystack = None
    violations = []
    for bullet in doc.all_bullets():
        normalized = _normalize(bullet.text)
        if normalized in haystack:
            continue
        if stripped_haystack is None:
            stripped_haystack = _haystack_without_date_ranges(doc, parsed)
        if normalized in stripped_haystack:
            continue
        violations.append(f"L7 bullet: {bullet.bullet_id} did not survive PDF extraction")
    return violations


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


# ---------------------------------------------------------------------------
# M8P-5 tailored-render extension. Append-only: nothing above this line is
# modified, and run_l7 above is never called from here except by
# run_l7_tailored, which reuses it wholesale rather than re-listing checks.
# ---------------------------------------------------------------------------

MAX_MODIFIED_BULLET_LINES = 2
_MIN_VISIBLE_FONT_PT = 0.5

#: Same numeric-token regex the S3 contract uses (src/tailor/s3.py), defined
#: once here rather than imported so the render layer keeps no dependency on
#: the tailor layer.
_NUMERIC_TOKEN_RE = re.compile(r"(?<!\w)[~+-]?(?:\d[\d,]*(?:\.\d+)?)(?:%|x|\+)?(?!\w)")


def check_bullet_line_counts(
    doc: RenderDoc,
    pages: tuple[RenderedPage, ...],
    modified_bullet_ids: frozenset[str],
    max_lines: int = MAX_MODIFIED_BULLET_LINES,
) -> list[str]:
    """Only MODIFIED bullets are subject to the rendered-line limit -- an
    unmodified canonical bullet is the user's own authored text and is out
    of scope (TAILORING_METHODOLOGY.md L4)."""
    violations = []
    for bullet in doc.all_bullets():
        if bullet.bullet_id not in modified_bullet_ids:
            continue
        run = locate_text_lines(pages, bullet.text)
        if not run:
            violations.append(
                f"L7 lines: bullet {bullet.bullet_id} did not survive rendered-PDF extraction"
            )
            continue
        if len(run) > max_lines:
            violations.append(
                f"L7 lines: bullet {bullet.bullet_id} occupies {len(run)} rendered lines, "
                f"exceeds the {max_lines}-line limit for modified bullets"
            )
    return violations


def check_metrics_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Every numeric token in every draft bullet's plain text must appear in
    the extracted PDF text with the same multiset per bullet -- catches a
    LaTeX escape or ligature silently mangling "40%" or "~3x"."""
    document_counts = Counter(_NUMERIC_TOKEN_RE.findall(parsed.text))
    violations = []
    for bullet in doc.all_bullets():
        bullet_counts = Counter(_NUMERIC_TOKEN_RE.findall(bullet.text))
        for token, needed in bullet_counts.items():
            have = document_counts.get(token, 0)
            if have < needed:
                violations.append(
                    f"L7 metric: bullet {bullet.bullet_id} claims {token!r} {needed} "
                    f"time(s) but the rendered PDF has it {have} time(s)"
                )
    return violations


def _stitched_bold_candidates(pages: tuple[RenderedPage, ...]) -> tuple[str, ...]:
    """M8V-1 3a: a bold phrase that wraps across a line becomes two separate
    `bold_run_texts` entries on two `RenderedLine`s, so the plain per-line
    substring test never sees them as one string (confirmed live:
    am_b01_dlq_consolidation, cm_b1 x2). Every individual bold run is still
    a candidate on its own (the original, unmodified check); in addition,
    each bold run on one line is paired with each bold run on the
    immediately following line within the same page -- exactly "the end of
    one line's bold run plus the start of the next line's bold run", which
    is what a genuine wrap continuation looks like. This never joins runs
    across a page boundary and never joins non-adjacent lines, so it cannot
    manufacture a match for text that was never actually printed in bold."""
    candidates: list[str] = []
    for page in pages:
        per_line_runs = [tuple(normalize(text) for text in line.bold_run_texts) for line in page.lines]
        for runs in per_line_runs:
            candidates.extend(runs)
        for runs_a, runs_b in zip(per_line_runs, per_line_runs[1:]):
            for run_a in runs_a:
                for run_b in runs_b:
                    candidates.append(f"{run_a} {run_b}")
    return tuple(candidates)


def check_emphasis_rendered(doc: RenderDoc, pages: tuple[RenderedPage, ...]) -> list[str]:
    """For every bullet with non-empty emphasis, each emphasised substring
    must appear inside a bold run on the page -- proves \\textbf{} actually
    reached the PDF rather than being escaped away. A bold span that wraps
    across a line is stitched from its two adjacent-line halves before
    matching; a span that was genuinely never rendered bold anywhere still
    fails, since it can never appear in any real bold run or any pair of
    truly adjacent ones."""
    bold_texts = _stitched_bold_candidates(pages)
    violations = []
    for bullet in doc.all_bullets():
        for start, end in bullet.emphasis:
            fragment = normalize(bullet.text[start:end])
            if not any(fragment in bold for bold in bold_texts):
                violations.append(
                    f"L7 emphasis: bullet {bullet.bullet_id} emphasised text "
                    f"{bullet.text[start:end]!r} did not render bold"
                )
    return violations


def check_no_do_not_claim_in_pdf(do_not_claim: tuple[str, ...], parsed: ParsedPdf) -> list[str]:
    """Belt-and-braces against failure #3 at the far end: no do_not_claim
    term may appear anywhere in the extracted PDF text, regardless of
    which surface (bullet, skills, tech_line, display_title, project_name)
    put it there. Deliberately decoupled from RenderDoc -- do_not_claim is
    a profile-level fact, not a rendered-document one -- so the caller
    supplies it directly (e.g. from the same profile that produced the
    draft being rendered)."""
    haystack = parsed.normalized_text
    return [
        f"L7 do_not_claim: term {term!r} found in rendered PDF text"
        for term in do_not_claim
        if _normalize(term) in haystack
    ]


def check_within_page_vertical(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """The vertical counterpart of check_within_page: text off the top or
    bottom of the paper. With 0.20in margins this is the realistic failure
    mode when a tailored bullet grows the document."""
    violations = []
    for box in parsed.boxes:
        if not box.text.strip():
            continue
        if box.y1 > parsed.page_height + _PAGE_BLEED_TOLERANCE_PT:
            violations.append(
                f"L7 layout: page {box.page} text extends "
                f"{box.y1 - parsed.page_height:.1f}pt past the top page edge: "
                f"{box.text.strip()[:40]!r}"
            )
        elif box.y0 < -_PAGE_BLEED_TOLERANCE_PT:
            violations.append(
                f"L7 layout: page {box.page} text extends {-box.y0:.1f}pt "
                f"past the bottom page edge: {box.text.strip()[:40]!r}"
            )
    return violations


def check_no_invisible_text(doc: RenderDoc, pages: tuple[RenderedPage, ...]) -> list[str]:
    """Flag any rendered line whose min_font_size is effectively zero -- the
    "hidden keyword" pattern TAILORING_SPEC.md forbids. Defensive: the
    deterministic renderer cannot produce this today; the check exists so
    it stays impossible."""
    return [
        f"L7 invisible: page {line.page} line {line.text[:40]!r} has "
        f"font size {line.min_font_size:.2f}pt (<= {_MIN_VISIBLE_FONT_PT}pt)"
        for page in pages
        for line in page.lines
        if line.text.strip() and line.min_font_size <= _MIN_VISIBLE_FONT_PT
    ]


def check_printable_margin(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Advisory, default off (TAILORING_METHODOLOGY §6.7 / M8P-5 design
    §6.7): reads ats.layout.min_margin_in. Absent -> silent (the current
    state; 0.20in is the user's accepted template geometry)."""
    min_margin_in = doc.ats.get("layout", {}).get("min_margin_in")
    if min_margin_in is None:
        return []
    floor_pt = float(min_margin_in) * 72.0
    violations = []
    for box in parsed.boxes:
        if not box.text.strip():
            continue
        distances = {
            "left": box.x0,
            "right": parsed.page_width - box.x1,
            "bottom": box.y0,
            "top": parsed.page_height - box.y1,
        }
        for edge, distance in distances.items():
            if distance < floor_pt:
                violations.append(
                    f"L7 margin: page {box.page} text is {distance:.1f}pt from the "
                    f"{edge} edge, inside the {min_margin_in}in floor: {box.text.strip()[:40]!r}"
                )
    return violations


def run_l7_tailored(
    doc: RenderDoc,
    parsed: ParsedPdf,
    pages: tuple[RenderedPage, ...],
    modified_bullet_ids: frozenset[str],
    do_not_claim: tuple[str, ...] = (),
) -> list[str]:
    """Every existing run_l7 check plus the six tailored-render checks
    above, plus check_no_do_not_claim_in_pdf (M8V-1 Task 3). run_l7 itself
    is unchanged so the M10 tests and scripts/render_bakeoff.py keep
    working. `do_not_claim` defaults to empty so every existing caller of
    this four-argument signature is unaffected; a caller that has the
    profile's do_not_claim list on hand should pass it."""
    violations = list(run_l7(doc, parsed))
    violations.extend(check_bullet_line_counts(doc, pages, modified_bullet_ids))
    violations.extend(check_metrics_survive(doc, parsed))
    violations.extend(check_emphasis_rendered(doc, pages))
    violations.extend(check_within_page_vertical(doc, parsed))
    violations.extend(check_no_invisible_text(doc, pages))
    violations.extend(check_printable_margin(doc, parsed))
    violations.extend(check_no_do_not_claim_in_pdf(do_not_claim, parsed))
    logger.info("L7 (tailored): %d violation(s)", len(violations))
    return violations
