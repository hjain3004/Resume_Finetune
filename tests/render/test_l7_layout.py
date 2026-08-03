from pathlib import Path
import pytest
from src.render.l7 import (
    check_single_column, check_contact_in_body, check_section_headings, check_page_count,
    check_no_overlap, check_within_page, run_l7,
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


def _line(text, y0, y1, x0=50.0, x1=550.0, page=0) -> TextBox:
    return TextBox(text=text, x0=x0, y0=y0, x1=x1, y1=y1, page=page)


def test_normally_spaced_lines_do_not_report_overlap():
    boxes = [_line("alpha", 700, 712), _line("bravo", 686, 698)]
    assert check_no_overlap(_doc(), _pdf(boxes)) == []


def test_touching_lines_within_tolerance_are_not_reported():
    # pdfminer containers include leading; a 2pt shared extent is normal.
    boxes = [_line("alpha", 700, 712), _line("bravo", 690, 702)]
    assert check_no_overlap(_doc(), _pdf(boxes)) == []


def test_heading_printed_through_a_bullet_is_reported():
    boxes = [_line("Amdocs Ltd.", 700, 712), _line("Built the layer", 694, 706)]
    violations = check_no_overlap(_doc(), _pdf(boxes))
    assert len(violations) == 1
    assert "collision" in violations[0]
    assert "Amdocs Ltd." in violations[0]


def test_vertically_overlapping_but_side_by_side_text_is_not_a_collision():
    boxes = [_line("left", 700, 712, x0=50, x1=200),
             _line("right", 700, 712, x0=400, x1=550)]
    assert check_no_overlap(_doc(), _pdf(boxes)) == []


def test_collisions_are_not_reported_across_pages():
    boxes = [_line("alpha", 700, 712, page=0), _line("bravo", 700, 712, page=1)]
    assert check_no_overlap(_doc(), _pdf(boxes, page_count=2)) == []


def test_text_inside_the_page_passes_the_bleed_check():
    assert check_within_page(_doc(), _pdf([_line("fits", 700, 712)])) == []


def test_text_running_off_the_right_edge_is_reported():
    boxes = [_line("Campus Marketplace - Peer-to-Peer Backend", 700, 712,
                   x0=25.0, x1=905.0)]
    violations = check_within_page(_doc(), _pdf(boxes))
    assert len(violations) == 1
    assert "past the right page edge" in violations[0]
    assert "293.0pt" in violations[0]


def test_text_starting_left_of_the_page_is_reported():
    boxes = [_line("clipped", 700, 712, x0=-9.0, x1=200.0)]
    violations = check_within_page(_doc(), _pdf(boxes))
    assert len(violations) == 1
    assert "left of the page" in violations[0]


def test_run_l7_includes_the_overlap_and_bleed_checks():
    boxes = [_line("Amdocs Ltd.", 700, 712), _line("Built the layer", 694, 706, x1=905.0)]
    violations = run_l7(_doc(), _pdf(boxes))
    assert any("collision" in v for v in violations)
    assert any("past the right page edge" in v for v in violations)


@pytest.mark.skipif(not (FIXTURES / "bad_two_column.pdf").exists(),
                    reason="fixture not recorded yet (Task 4)")
def test_two_column_fixture_fails_on_the_column_check_specifically():
    parsed = parse_pdf(FIXTURES / "bad_two_column.pdf")
    assert check_single_column(_doc(), parsed), (
        "the deliberately two-column fixture must trip the column check"
    )
