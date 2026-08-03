"""Inline emphasis markup. Pure: no I/O, no rendering.

`**text**` marks a span to emphasize. The parser returns the plain text (what
the PDF will contain, and therefore what L7 asserts against) plus offsets into
that plain text. Offsets rather than substrings so repeated text is unambiguous.
"""

import re

_MARKER = "**"

class EmphasisError(ValueError):
    """Raised when emphasis markup is unbalanced, empty, or nested."""

def parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Split `**marked**` text into (plain_text, span offsets into plain_text)."""
    plain_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    
    cursor = 0
    plain_len = 0
    open_at = None
    open_plain_start = None
    
    while True:
        pos = raw.find(_MARKER, cursor)
        if pos == -1:
            break
            
        can_open = pos + 2 < len(raw) and not raw[pos + 2].isspace()
        can_close = pos > 0 and not raw[pos - 1].isspace()
        
        if open_at is None:
            if not can_open:
                raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")
            
            before = raw[cursor:pos]
            plain_parts.append(before)
            plain_len += len(before)
            
            open_at = pos
            open_plain_start = plain_len
            cursor = pos + 2
        else:
            body = raw[open_at + 2:pos]
            if not body:
                raise EmphasisError(f"empty emphasis span in {raw!r}")
                
            if can_close:
                plain_parts.append(body)
                plain_len += len(body)
                spans.append((open_plain_start, plain_len))
                open_at = None
                open_plain_start = None
                cursor = pos + 2
            elif can_open:
                raise EmphasisError(f"nested emphasis span in {raw!r}")
            else:
                raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")
                
    if open_at is not None:
        raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")
        
    plain_parts.append(raw[cursor:])
    return "".join(plain_parts), tuple(spans)
