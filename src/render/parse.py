"""PDF text + geometry extraction. Pure over a file path; no rendering."""

import logging
from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int


@dataclass(frozen=True)
class ParsedPdf:
    boxes: tuple[TextBox, ...]
    page_height: float
    page_width: float
    size_bytes: int
    page_count: int

    @property
    def text(self) -> str:
        return "\n".join(box.text for box in self.boxes)

    @property
    def normalized_text(self) -> str:
        return " ".join(self.text.split()).casefold()


def parse_pdf(path: str | Path) -> ParsedPdf:
    """Extract text containers with bounding boxes, in document order."""
    path = Path(path)
    boxes: list[TextBox] = []
    page_height = 0.0
    page_width = 0.0
    page_count = 0

    for page_number, layout in enumerate(extract_pages(str(path), laparams=LAParams())):
        page_count = page_number + 1
        page_width = max(page_width, float(layout.width))
        page_height = max(page_height, float(layout.height))
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            text = element.get_text().strip()
            if not text:
                continue
            x0, y0, x1, y1 = element.bbox
            boxes.append(
                TextBox(
                    text=text,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    page=page_number,
                )
            )

    logger.info("parsed %s: %d text boxes", path.name, len(boxes))
    return ParsedPdf(
        boxes=tuple(boxes),
        page_height=page_height,
        page_width=page_width,
        size_bytes=path.stat().st_size,
        page_count=page_count,
    )
