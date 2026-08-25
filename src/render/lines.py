"""Line- and character-level PDF geometry. src/render/parse.py returns
LTTextContainer-level boxes; L7's rendered line counts and bold-emphasis
checks need LTTextLine and LTChar, so this module performs its own
extract_pages() walk rather than changing the shared parser."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine


@dataclass(frozen=True)
class RenderedLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    max_font_size: float
    min_font_size: float
    bold_run_texts: tuple[str, ...]


@dataclass(frozen=True)
class RenderedPage:
    number: int
    width: float
    height: float
    lines: tuple[RenderedLine, ...]


def normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _is_bold(fontname: str) -> bool:
    return "bold" in fontname.casefold()


def _bold_runs(line: LTTextLine) -> tuple[str, ...]:
    """A maximal contiguous run of bold LTChars. Word-space between glyphs is
    an LTAnno, not an LTChar (no fontname of its own) -- it extends an
    already-open bold run so "anti corruption layer" survives as one run
    with its spaces intact, but never opens a run by itself."""
    runs: list[str] = []
    current: list[str] = []
    for element in line:
        if isinstance(element, LTChar):
            if _is_bold(element.fontname):
                current.append(element.get_text())
            else:
                if current:
                    runs.append("".join(current))
                    current = []
        elif current:
            current.append(element.get_text())
    if current:
        runs.append("".join(current))
    return tuple(run for run in runs if run.strip())


def _line_from(line: LTTextLine, page_number: int) -> RenderedLine | None:
    chars = [char for char in line if isinstance(char, LTChar)]
    if not chars:
        return None
    sizes = [char.size for char in chars]
    bold_run_texts = _bold_runs(line)
    x0, y0, x1, y1 = line.bbox
    return RenderedLine(
        text=line.get_text().rstrip("\n"),
        x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1),
        page=page_number,
        max_font_size=max(sizes),
        min_font_size=min(sizes),
        bold_run_texts=bold_run_texts,
    )


def parse_rendered_lines(path: str | Path) -> tuple[RenderedPage, ...]:
    """Walk extract_pages() ourselves so we can reach LTTextLine/LTChar."""
    pages: list[RenderedPage] = []
    for page_number, layout in enumerate(extract_pages(str(path), laparams=LAParams())):
        lines: list[RenderedLine] = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            for child in element:
                if isinstance(child, LTTextLine):
                    rendered = _line_from(child, page_number)
                    if rendered is not None and rendered.text.strip():
                        lines.append(rendered)
        pages.append(RenderedPage(
            number=page_number, width=float(layout.width), height=float(layout.height),
            lines=tuple(lines),
        ))
    return tuple(pages)


def locate_text_lines(pages: tuple[RenderedPage, ...], needle_plain: str) -> tuple[RenderedLine, ...]:
    """The shortest contiguous run of lines, in document order, whose
    whitespace-normalised concatenation contains the normalised needle.
    Returns () when no run matches."""
    needle = normalize(needle_plain)
    if not needle:
        return ()
    ordered: list[RenderedLine] = [line for page in pages for line in page.lines]

    best: tuple[RenderedLine, ...] = ()
    for start in range(len(ordered)):
        for end in range(start, len(ordered)):
            concatenated = normalize(" ".join(line.text for line in ordered[start:end + 1]))
            if needle in concatenated:
                candidate = tuple(ordered[start:end + 1])
                if not best or len(candidate) < len(best):
                    best = candidate
                break
    return best
