"""Line- and character-level PDF geometry (M8P-5 Task 2). No pdflatex here --
every test runs against committed PDF fixtures."""
from pathlib import Path

from src.render.lines import locate_text_lines, normalize, parse_rendered_lines

FIXTURES = Path("tests/fixtures/render")

TWO_LINE_BULLET_PLAIN = (
    "Built the anti corruption layer between commercial bank core systems and "
    "four external providers as four asynchronous Python microservices, "
    "cutting deployment defects by 40%."
)
THREE_LINE_BULLET_PLAIN = (
    "Built the anti corruption layer between commercial bank core systems and "
    "four external providers as four asynchronous Python microservices, "
    "cutting deployment defects by 40%, and improving reliability across three "
    "downstream services while doubling automated test coverage for the "
    "adapter boundary."
)
EMPHASISED_FRAGMENT = "anti corruption layer"


def test_two_line_bullet_occupies_two_rendered_lines():
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    run = locate_text_lines(pages, TWO_LINE_BULLET_PLAIN)
    assert len(run) == 2


def test_three_line_bullet_occupies_three_rendered_lines():
    pages = parse_rendered_lines(FIXTURES / "tailored_three_line.pdf")
    assert len(locate_text_lines(pages, THREE_LINE_BULLET_PLAIN)) == 3


def test_locate_returns_empty_when_text_absent():
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert locate_text_lines(pages, "text that was never rendered") == ()


def test_bold_runs_are_captured():
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    bold = {normalize(t) for page in pages for line in page.lines for t in line.bold_run_texts}
    assert any(normalize(EMPHASISED_FRAGMENT) in t for t in bold)


def test_page_dimensions_are_reported():
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert pages[0].width > 0 and pages[0].height > 0


def test_font_sizes_are_positive_for_visible_text():
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert all(line.min_font_size > 0.5 for page in pages for line in page.lines if line.text.strip())
