"""Canonical tier-2 contract: the project-owned page result, the client
protocol, and the one deterministic acceptance decision for a fetched page.

M9F-0 (docs/superpowers/specs/2026-08-06-firecrawl-ingestion-integration-design.md
sections 8 and 10). Neither the resolver nor `run_ingest.py` may depend on a
Firecrawl response dictionary or Crawl4AI's `CrawlResult`; both backends adapt
into `Tier2Page` here.

This module previously coexisted with duplicate `Tier2Page`/`Tier2Client`
definitions in `src/resolve/base.py` and `src/firecrawl/client.py`, plus a
placeholder `PoliteSession`. Structural (Protocol) typing hides that kind of
drift until a field diverges, so the definition is centralised here and the
duplicates were removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from urllib.parse import urlparse

from src.resolve import generic


@dataclass(frozen=True)
class Tier2Page:
    """One rendered page from whichever tier-2 backend is selected.

    `credits_used` is 0 for local backends (Crawl4AI) and the charged credit
    count for paid backends (Firecrawl)."""

    markdown: str
    html: str | None
    final_url: str
    status_code: int | None
    provider: str
    credits_used: int


class Tier2Client(Protocol):
    def start(self) -> None: ...
    def crawl(self, url: str) -> Tier2Page: ...
    def close(self) -> None: ...


class Tier2Deferred(RuntimeError):
    """The fetch did not happen and no content judgment was made.

    Raised for budget exhaustion, URL cooldown, and `--dry-run`. Orchestration
    maps this to a transient/deferred outcome, so it never consumes a row's
    `resolve_attempts` and never manufactures a cooldown of its own."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


class PageRejection(str, Enum):
    """Why a fetched tier-2 page was not acceptable. All of these are content
    judgments: the fetch succeeded, so the request is charged and the row's
    attempt budget is consumed."""

    BAD_FINAL_URL = "bad_final_url"
    BAD_STATUS = "bad_status"
    EMPTY_MARKDOWN = "empty_markdown"
    DEAD_POSTING = "dead_posting"
    QUALITY_GATE = "quality_gate"


class Tier2ContentRejected(RuntimeError):
    """A page was fetched successfully but is not acceptable content.

    This *is* a content judgment: the request has already been charged and put
    into cooldown by the budget-aware wrapper, so orchestration consumes the
    row's `resolve_attempts` exactly as for any other content failure."""

    def __init__(self, rejection: PageRejection) -> None:
        super().__init__(rejection.value)
        self.rejection = rejection


def page_rejection(page: Tier2Page) -> PageRejection | None:
    """The single deterministic acceptance decision for a tier-2 page.

    Returns `None` when the page is acceptable, otherwise the specific reason.
    Shared by every backend so Crawl4AI and Firecrawl content is judged
    identically, and defined over the existing `generic` gate rather than
    duplicating or weakening it."""
    parsed = urlparse(page.final_url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return PageRejection.BAD_FINAL_URL

    # `status_code` is optional: Crawl4AI does not report one.
    if page.status_code is not None and not 200 <= page.status_code < 300:
        return PageRejection.BAD_STATUS

    markdown = page.markdown or ""
    if not markdown.strip():
        return PageRejection.EMPTY_MARKDOWN

    if generic.is_dead_posting_text(markdown):
        return PageRejection.DEAD_POSTING

    if not generic.passes_quality(markdown):
        return PageRejection.QUALITY_GATE

    return None


def is_acceptable(page: Tier2Page) -> bool:
    return page_rejection(page) is None
