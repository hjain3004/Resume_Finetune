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
# M6.13R dead-posting detection.
#
# M6.13 matched unbounded fragments (`has been filled`, `no longer exists`,
# `no longer open`) anywhere on a page, which misclassified valid JDs carrying
# incidental policy wording — job 1246 (D2L) was flagged by the careers-FAQ
# sentence "When an opportunity has been filled, we will remove the job
# posting". A dead-page notice always names *this* posting, so evidence now
# requires an explicit subject bound to a dead predicate inside one sentence.

# Nouns a dead-page notice uses for the thing that is gone. Longest-first so
# "job post"/"job posting" win over the bare "job" alternative.
_SUBJECT_NOUN = (
    r"(?:job\s+post(?:ing)?s?|job\s+listing|job\s+description|job|position|role"
    r"|posting|listing|opportunity|vacancy|requisition|page)"
)

# Predicates asserting the posting is gone. Deliberately closed-vocabulary:
# "no longer remote" or "no longer accepting referrals" must not qualify.
_DEAD_PREDICATE = (
    r"(?:no\s+longer\s+(?:available|open|posted|active|live|exists?"
    r"|accepting\s+applications)"
    r"|has\s+been\s+(?:filled|removed|closed)"
    r"|does\s+not\s+exist"
    r"|has\s+expired"
    r"|could\s+not\s+be\s+found)"
)

# Same-sentence filler between subject and predicate ("is", "may be",
# "is either", ...). Sentence punctuation is excluded so evidence never spans
# two sentences.
_GAP = r"[^.!?\n]{0,40}?"

# Relative clauses that bind a definite noun to the posting the visitor asked
# for: "the job you are trying to apply for", "the page you are looking for".
_ASKED_FOR = (
    r"(?:that\s+)?you(?:'re|’re|\s+are|\s+were)?\s+"
    r"(?:looking\s+for|trying\s+to\s+apply\s+for|interested\s+in|clicked\s+on"
    r"|applied\s+for|selected)"
)

_DEAD_POSTING_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "This job is no longer available", "this position has been filled".
    re.compile(rf"\bthis\s+{_SUBJECT_NOUN}\b{_GAP}{_DEAD_PREDICATE}", re.IGNORECASE),
    # "The position you're looking for is no longer open".
    re.compile(
        rf"\b(?:the|this|that)\s+{_SUBJECT_NOUN}\b\s+{_ASKED_FOR}{_GAP}{_DEAD_PREDICATE}",
        re.IGNORECASE,
    ),
    # iCIMS error page: "The requested job could not be found".
    re.compile(
        rf"\bthe\s+requested\s+{_SUBJECT_NOUN}\b{_GAP}{_DEAD_PREDICATE}", re.IGNORECASE
    ),
)

# A conditional/temporal clause turns the same wording into policy rather than
# a notice: "Once this position has been filled, we will notify applicants."
_CONDITIONAL_RE = re.compile(
    r"\b(?:when|whenever|once|after|until|if|unless|should|in\s+the\s+event)\b",
    re.IGNORECASE,
)

_SENTENCE_BREAK_RE = re.compile(r"[.!?\n]")


def _sentence_prefix(text: str, index: int) -> str:
    """Text from the start of the sentence containing `index` up to `index`."""
    breaks = [m.end() for m in _SENTENCE_BREAK_RE.finditer(text, 0, index)]
    return text[breaks[-1] : index] if breaks else text[:index]


def dead_posting_evidence(text: str) -> str | None:
    """The matched dead-page notice, whitespace-collapsed, or None.

    Evidence is an explicit subject naming this posting plus a dead predicate
    in the same sentence, and is discarded when the clause is conditional.
    Returned so remediation previews can be audited transition by transition."""
    for pattern in _DEAD_POSTING_PATTERNS:
        for match in pattern.finditer(text):
            if not _CONDITIONAL_RE.search(_sentence_prefix(text, match.start())):
                return " ".join(match.group(0).split())
    return None


def is_dead_posting_text(text: str) -> bool:
    """M6.13R: true if `text` reads as a closed/expired-posting notice rather
    than real JD content. Exposed for scripts/remediate_dead_postings.py so
    stored jd_text is judged by exactly the same rule as freshly fetched text."""
    return dead_posting_evidence(text) is not None


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
