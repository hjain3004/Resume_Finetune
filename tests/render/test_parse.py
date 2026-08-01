from pathlib import Path
import pytest
from src.render.parse import parse_pdf, ParsedPdf

FIXTURES = Path("tests/fixtures/render")
GOOD = FIXTURES / "good_single_column.pdf"

pytestmark = pytest.mark.skipif(
    not GOOD.exists(), reason="fixture not recorded yet (Task 4)"
)


def test_parse_returns_boxes_with_geometry():
    parsed = parse_pdf(GOOD)
    assert isinstance(parsed, ParsedPdf)
    assert parsed.boxes, "expected at least one text box"
    first = parsed.boxes[0]
    assert first.x1 > first.x0
    assert first.y1 > first.y0
    assert parsed.page_width > 0


def test_normalized_text_collapses_whitespace_and_case():
    parsed = parse_pdf(GOOD)
    assert "  " not in parsed.normalized_text
    assert parsed.normalized_text == parsed.normalized_text.casefold()


def test_size_bytes_matches_file():
    assert parse_pdf(GOOD).size_bytes == GOOD.stat().st_size
