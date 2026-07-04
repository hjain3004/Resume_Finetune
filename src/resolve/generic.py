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


def resolve(url: str, session) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        return None

    text = trafilatura.extract(response.text) or ""
    if len(text) < MIN_LENGTH or not _KEYWORD_RE.search(text):
        return None

    return ResolvedJD(jd_text=text, resolver=RESOLVER_NAME)
