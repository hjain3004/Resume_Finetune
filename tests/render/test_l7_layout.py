from pathlib import Path
import pytest
from src.render.l7 import (
    check_single_column, check_contact_in_body, check_section_headings, check_page_count, run_l7,
)
from src.render.model import RenderDoc
from src.render.parse import ParsedPdf, TextBox, parse_pdf

FIXTURES = Path("tests/fixtures/render")


def _doc(**kw) -> RenderDoc:
    base = dict(
        identity={"name": "Test User"},
        education=(), experience=(), projects=(),
        skills={},
        section_order=("Education", "Experience"),
        ats={"forbidden_chars": [], "max_file_size_mb": 2.5,
             "layout": {"columns": 1, "contact_in_body": True},
             "headings_whitelist": ["Education", "Experience", "Projects", "Skills"]},
    )
    base.update(kw)
    return RenderDoc(**base)


def _pdf(boxes, page_count=1) -> ParsedPdf:
    return ParsedPdf(boxes=tuple(boxes), page_height=792.0,
                     page_width=612.0, size_bytes=1000, page_count=page_count)


def test_single_column_layout_passes():
    boxes = [TextBox(text=f"line {i}", x0=50, y0=700 - i * 20,
                     x1=550, y1=715 - i * 20, page=0) for i in range(10)]
    assert check_single_column(_doc(), _pdf(boxes)) == []


def test_two_column_layout_is_reported():
    left = [TextBox(text=f"L{i}", x0=50, y0=700 - i * 20,
                    x1=280, y1=715 - i * 20, page=0) for i in range(6)]
    right = [TextBox(text=f"R{i}", x0=330, y0=700 - i * 20,
                     x1=560, y1=715 - i * 20, page=0) for i in range(6)]
    violations = check_single_column(_doc(), _pdf(left + right))
    assert len(violations) == 1
    assert "column" in violations[0].lower()


def test_single_indented_block_does_not_trip_column_check():
    body = [TextBox(text=f"line {i}", x0=50, y0=700 - i * 20,
                    x1=550, y1=715 - i * 20, page=0) for i in range(12)]
    indented = [TextBox(text="note", x0=330, y0=400, x1=560, y1=415, page=0)]
    assert check_single_column(_doc(), _pdf(body + indented)) == []


def test_column_check_is_skipped_when_policy_allows_columns():
    doc = _doc(ats={"layout": {"columns": 2}, "headings_whitelist": []})
    left = [TextBox(text=f"L{i}", x0=50, y0=700 - i * 20,
                    x1=280, y1=715 - i * 20, page=0) for i in range(6)]
    right = [TextBox(text=f"R{i}", x0=330, y0=700 - i * 20,
                     x1=560, y1=715 - i * 20, page=0) for i in range(6)]
    assert check_single_column(doc, _pdf(left + right)) == []


def test_contact_in_header_band_is_reported():
    boxes = [TextBox(text="Test User", x0=50, y0=780, x1=550, y1=790, page=0)]
    assert len(check_contact_in_body(_doc(), _pdf(boxes))) == 1


def test_contact_inside_body_passes():
    boxes = [TextBox(text="Test User", x0=50, y0=700, x1=550, y1=715, page=0)]
    assert check_contact_in_body(_doc(), _pdf(boxes)) == []


def test_out_of_order_headings_are_reported():
    boxes = [
        TextBox(text="Experience", x0=50, y0=700, x1=200, y1=715, page=0),
        TextBox(text="Education", x0=50, y0=600, x1=200, y1=615, page=0),
    ]
    assert len(check_section_headings(_doc(), _pdf(boxes))) == 1


def test_headings_in_order_pass():
    boxes = [
        TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0),
        TextBox(text="Experience", x0=50, y0=600, x1=200, y1=615, page=0),
    ]
    assert check_section_headings(_doc(), _pdf(boxes)) == []


def test_missing_heading_is_reported():
    boxes = [TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0)]
    violations = check_section_headings(_doc(), _pdf(boxes))
    assert any("Experience" in v for v in violations)


def test_run_l7_aggregates_all_checks():
    boxes = [TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0)]
    violations = run_l7(_doc(), _pdf(boxes))
    assert any("identity" in v for v in violations)
    assert any("Experience" in v for v in violations)


def test_valid_one_page_output_passes():
    doc = _doc(ats={"max_pages": 1})
    assert check_page_count(doc, _pdf([], page_count=1)) == []


def test_too_many_pages_fails():
    doc = _doc(ats={"max_pages": 1})
    violations = check_page_count(doc, _pdf([], page_count=2))
    assert len(violations) == 1
    assert "exceeds ats.max_pages" in violations[0]


def test_absent_max_pages_is_noop():
    doc = _doc(ats={})  # no max_pages
    assert check_page_count(doc, _pdf([], page_count=5)) == []


@pytest.mark.skipif(not (FIXTURES / "bad_two_column.pdf").exists(),
                    reason="fixture not recorded yet (Task 4)")
def test_two_column_fixture_fails_on_the_column_check_specifically():
    parsed = parse_pdf(FIXTURES / "bad_two_column.pdf")
    assert check_single_column(_doc(), parsed), (
        "the deliberately two-column fixture must trip the column check"
    )
