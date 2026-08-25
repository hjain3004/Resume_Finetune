"""L7 extension: rendered line counts, metric survival, emphasis rendering,
vertical bleed, invisible text, and the printable-margin advisory (M8P-5
Task 3). No pdflatex here -- every test runs against committed fixtures."""
from pathlib import Path

import pytest

from src.render.l7 import (
    check_bullet_line_counts,
    check_emphasis_rendered,
    check_metrics_survive,
    check_no_invisible_text,
    check_printable_margin,
    check_within_page_vertical,
    run_l7_tailored,
)
from src.render.lines import parse_rendered_lines
from src.render.model import RenderBullet, RenderDoc, RenderEntry
from src.render.parse import parse_pdf
from tests.render.test_lines import EMPHASISED_FRAGMENT, THREE_LINE_BULLET_PLAIN, TWO_LINE_BULLET_PLAIN

FIXTURES = Path("tests/fixtures/render")

_ATS = {
    "forbidden_chars": [], "max_file_size_mb": 2.5, "max_pages": 1,
    "layout": {"columns": 1, "contact_in_body": True},
    "headings_whitelist": ["Education", "Experience", "Projects", "Technical Skills"],
}


def _bullet(bullet_id: str, text: str, *, emphasise: str | None = None) -> RenderBullet:
    spans = ()
    if emphasise is not None:
        start = text.index(emphasise)
        spans = ((start, start + len(emphasise)),)
    return RenderBullet(bullet_id=bullet_id, text=text, emphasis=spans)


def _doc(*, bullets, ats=None) -> RenderDoc:
    entry = RenderEntry(entry_id="p1", heading="Fixture Project", subheading="Python, FastAPI", bullets=tuple(bullets))
    return RenderDoc(
        identity={"name": "Test User"}, education=(), experience=(), projects=(entry,),
        skills={}, section_order=("Education", "Experience", "Projects", "Technical Skills"),
        ats=dict(ats) if ats is not None else dict(_ATS),
    )


@pytest.fixture
def two_line_doc():
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def three_line_doc():
    return _doc(bullets=[_bullet("b_modified", THREE_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def two_line_doc_with_absent_bullet():
    return _doc(bullets=[_bullet("b_absent", "text that was never rendered anywhere on this page")])


@pytest.fixture
def doc_claiming_extra_metric():
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN + " Also saved 99%.", emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def doc_claiming_unrendered_emphasis():
    # "between commercial bank" is real, rendered text -- but never bold.
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise="between commercial bank")])


@pytest.fixture
def doc_with_quarter_inch_floor():
    ats = dict(_ATS)
    ats["layout"] = {**_ATS["layout"], "min_margin_in": 0.25}
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)], ats=ats)


def test_two_line_modified_bullet_passes(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_bullet_line_counts(two_line_doc, pages, frozenset({"b_modified"})) == []


def test_three_line_modified_bullet_violates(three_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_three_line.pdf")
    violations = check_bullet_line_counts(three_line_doc, pages, frozenset({"b_modified"}))
    assert len(violations) == 1
    assert "3 rendered lines" in violations[0]


def test_three_line_unmodified_bullet_is_exempt(three_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_three_line.pdf")
    assert check_bullet_line_counts(three_line_doc, pages, frozenset()) == []


def test_missing_bullet_reports_survival_not_a_line_count(two_line_doc_with_absent_bullet):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    violations = check_bullet_line_counts(two_line_doc_with_absent_bullet, pages,
                                          frozenset({"b_absent"}))
    assert "did not survive" in violations[0]


def test_metrics_survive_passes_on_good_fixture(two_line_doc):
    assert check_metrics_survive(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_metric_loss_is_detected(doc_claiming_extra_metric):
    violations = check_metrics_survive(doc_claiming_extra_metric,
                                       parse_pdf(FIXTURES / "tailored_two_line.pdf"))
    assert violations and "99%" in violations[0]


def test_emphasis_rendered_passes_when_bold_present(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_emphasis_rendered(two_line_doc, pages) == []


def test_emphasis_missing_from_pdf_is_detected(doc_claiming_unrendered_emphasis):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_emphasis_rendered(doc_claiming_unrendered_emphasis, pages)


def test_vertical_bleed_is_detected(two_line_doc):
    assert check_within_page_vertical(two_line_doc, parse_pdf(FIXTURES / "tailored_bleed.pdf"))


def test_good_fixture_has_no_vertical_bleed(two_line_doc):
    assert check_within_page_vertical(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_invisible_text_check_passes_on_visible_fixture(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_no_invisible_text(two_line_doc, pages) == []


def test_printable_margin_is_silent_when_unconfigured(two_line_doc):
    assert check_printable_margin(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_printable_margin_flags_when_configured(doc_with_quarter_inch_floor):
    violations = check_printable_margin(doc_with_quarter_inch_floor,
                                        parse_pdf(FIXTURES / "tailored_two_line.pdf"))
    assert violations   # the 0.20in template is inside a 0.25in floor, by design


def test_run_l7_tailored_includes_every_base_l7_check(two_line_doc, monkeypatch):
    """The tailored aggregate must not silently drop an inherited check."""
    import src.render.l7 as l7
    called = []
    for name in ("check_identity_survives", "check_bullets_survive", "check_skills_survive",
                 "check_charset", "check_file_size", "check_page_count",
                 "check_single_column", "check_contact_in_body", "check_section_headings",
                 "check_no_overlap", "check_within_page"):
        original = getattr(l7, name)
        monkeypatch.setattr(l7, name,
                            lambda d, p, _n=name, _o=original: (called.append(_n), _o(d, p))[1])
    run_l7_tailored(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf"),
                    parse_rendered_lines(FIXTURES / "tailored_two_line.pdf"), frozenset())
    assert len(called) == 11
