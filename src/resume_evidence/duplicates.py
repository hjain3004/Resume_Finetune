"""Deterministic duplicate analysis for staged resume evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.resume_evidence.model import OutcomeCandidate
from src.textsim import jaccard_similarity, shingles

NEAR_DUPLICATE_THRESHOLD = 0.90

_TRACKING_KEYS = frozenset({"fbclid", "gclid", "msclkid"})
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\d ().-]{7,}\d)")
_CONTACT_URL_RE = re.compile(r"\b(?:https?://|www\.|linkedin\.com|github\.com)\S*", re.I)
_SECTION_HEADINGS = frozenset(
    {
        "summary",
        "experience",
        "work experience",
        "professional experience",
        "projects",
        "education",
        "skills",
        "technical skills",
    }
)


@dataclass(frozen=True)
class DuplicatePair:
    left_id: str
    right_id: str
    kind: str
    similarity: float


def canonical_source_url(url: str) -> str:
    """Normalize a public source URL while preserving content-affecting queries."""
    parts = urlsplit(url)
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold()
    port = parts.port
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"
    path = parts.path or "/"
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        folded = key.casefold()
        if folded.startswith("utm_") or folded in _TRACKING_KEYS:
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, host, path, query, ""))


def _resume_body(text: str) -> str:
    lines = text.splitlines()
    first_section = None
    for index, raw in enumerate(lines):
        heading = raw.strip().lstrip("#").strip().rstrip(":").casefold()
        if heading in _SECTION_HEADINGS:
            first_section = index
            break
    if first_section is not None:
        lines = lines[first_section:]
    kept = []
    for line in lines:
        if _EMAIL_RE.search(line) or _PHONE_RE.search(line) or _CONTACT_URL_RE.search(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def resume_signature(text: str) -> frozenset[str]:
    """Return five-word shingles after dropping obvious header/contact tokens."""
    return frozenset(shingles(_resume_body(text)))


def _resume_source(candidate: OutcomeCandidate):
    return next(
        source
        for source in candidate.sources
        if source.source_id == candidate.resume_source_id
    )


def find_duplicates(
    candidates: tuple[OutcomeCandidate, ...],
    snapshot_text_by_id: dict[str, str],
) -> tuple[DuplicatePair, ...]:
    """Report one strongest duplicate reason for each deterministic candidate pair."""
    ordered = sorted(candidates, key=lambda item: item.reference_id.casefold())
    pairs: list[DuplicatePair] = []
    for left_index, left in enumerate(ordered):
        left_source = _resume_source(left)
        for right in ordered[left_index + 1 :]:
            right_source = _resume_source(right)
            if canonical_source_url(left_source.url) == canonical_source_url(right_source.url):
                pairs.append(
                    DuplicatePair(left.reference_id, right.reference_id, "source_url", 1.0)
                )
                continue
            if left_source.content_sha256 == right_source.content_sha256:
                pairs.append(
                    DuplicatePair(
                        left.reference_id, right.reference_id, "content_sha256", 1.0
                    )
                )
                continue
            similarity = jaccard_similarity(
                set(resume_signature(snapshot_text_by_id[left.reference_id])),
                set(resume_signature(snapshot_text_by_id[right.reference_id])),
            )
            if similarity >= NEAR_DUPLICATE_THRESHOLD:
                pairs.append(
                    DuplicatePair(
                        left.reference_id,
                        right.reference_id,
                        "near_signature",
                        similarity,
                    )
                )
    return tuple(pairs)

