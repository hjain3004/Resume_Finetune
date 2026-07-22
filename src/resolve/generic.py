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
_DEAD_POSTING_RE = re.compile(
    r"no longer available|position has been filled|no longer accepting applications"
    r"|this position is no longer|posting has expired|no longer open|no longer exists"
    r"|has been filled|job is no longer|no longer posted",
    re.IGNORECASE,
)


def is_dead_posting_text(text: str) -> bool:
    """M6.13: true if `text` reads as a closed/expired-posting notice rather
    than real JD content. Exposed for scripts/remediate_dead_postings.py to
    reuse the same phrase list against already-stored jd_text."""
    return bool(_DEAD_POSTING_RE.search(text))


def passes_quality(text: str) -> bool:
    """Shared quality gate: also used by resolve/browser.py's tier-2 fallback
    so both tiers reject nav shells / JS-rendered pages the same way. Rejects
    closed/expired-posting notices even when they're long enough and contain
    job-adjacent keywords to otherwise pass (M6.13 dead-posting fix)."""
    if is_dead_posting_text(text):
        return False
    return len(text) >= MIN_LENGTH and bool(_KEYWORD_RE.search(text))


def resolve(url: str, session) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        return None

    text = trafilatura.extract(response.text) or ""
    if not passes_quality(text):
        return None

    return ResolvedJD(jd_text=text, resolver=RESOLVER_NAME)
