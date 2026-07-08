"""Fallback resolver: extract main content with trafilatura, gated by a
length + keyword heuristic to reject nav shells and JS-rendered pages."""

from __future__ import annotations

import re

import trafilatura

from src.models import ResolvedJD

RESOLVER_NAME = "generic"
MIN_LENGTH = 400
_KEYWORD_RE = re.compile(
    r"responsibilit|qualif|requirement|experience|skills", re.IGNORECASE
)


def passes_quality(text: str) -> bool:
    """Shared quality gate: also used by resolve/browser.py's tier-2 fallback
    so both tiers reject nav shells / JS-rendered pages the same way."""
    return len(text) >= MIN_LENGTH and bool(_KEYWORD_RE.search(text))


def resolve(url: str, session) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        return None

    text = trafilatura.extract(response.text) or ""
    if not passes_quality(text):
        return None

    return ResolvedJD(jd_text=text, resolver=RESOLVER_NAME)
