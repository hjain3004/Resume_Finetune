"""Tier-2 browser resolver (M6.5, PHASE2_KICKOFF.md): renders a page with
crawl4ai when no tier-1 resolver applies and generic.py's trafilatura pass
fails its quality heuristic. Deterministic rendering/markdown only — no
crawl4ai LLM-extraction strategies, no stealth/anti-bot-evasion. A site that
blocks a plain headless browser (e.g. tesla.com) is expected to stay tier-3.

M6.10 (docs/superpowers/specs/2026-07-15-resolution-runtime-hardening-design.md):
production resolution previously launched a fresh `AsyncWebCrawler`/Chromium
per URL, which was slow and made hundreds of browser-required rows do
hundreds of browser startups. `fetch_markdown`/`fetch_html`/`resolve` now
take an injected `BrowserClient` (`Crawl4AIBrowserClient` in production, a
fake in tests) that `run_ingest.py` starts once per run and closes once at
the end. `CircuitBreakingBrowserClient` wraps it so the first lifecycle
failure trips a run-local breaker: later browser-required rows fail fast
with `BrowserUnavailableError` instead of re-attempting a launch that's
already known to be broken.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig

from src.models import ResolvedJD
from src.resolve import generic
from src.resolve.base import Tier2Page, Tier2Client

RESOLVER_NAME = "browser"


class BrowserUnavailableError(RuntimeError):
    """The browser client could not start or operate. Always transient from
    orchestration's point of view -- never a content judgment about a page."""




class Crawl4AIBrowserClient:
    """One dedicated event loop and `AsyncWebCrawler` for the whole
    resolution run. `start()`/`close()` are idempotent; once unavailable,
    `start()` fails fast without retrying construction."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._crawler: AsyncWebCrawler | None = None
        self._started = False
        self._unavailable_reason: str | None = None

    def start(self) -> None:
        if self._started:
            return
        if self._unavailable_reason is not None:
            raise BrowserUnavailableError(self._unavailable_reason)
        try:
            self._crawler = AsyncWebCrawler()
            self._loop.run_until_complete(self._crawler.start())
            self._started = True
        except Exception as exc:
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            raise BrowserUnavailableError(self._unavailable_reason) from exc

    def crawl(self, url: str) -> Tier2Page:
        self.start()
        assert self._crawler is not None
        try:
            result = self._loop.run_until_complete(
                self._crawler.arun(url=url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))
            )
            return Tier2Page(
                markdown=result.markdown,
                html=result.html,
                final_url=url,
                status_code=None,
                provider="crawl4ai",
                credits_used=0
            )
        except Exception as exc:
            self._unavailable_reason = f"{type(exc).__name__}: {exc}"
            raise BrowserUnavailableError(self._unavailable_reason) from exc

    def close(self) -> None:
        try:
            if self._crawler is not None and self._started:
                self._loop.run_until_complete(self._crawler.close())
        finally:
            self._loop.close()
            self._started = False


class CircuitBreakingBrowserClient:
    """Wraps a Tier2Client so the first BrowserUnavailableError permanently
    trips the breaker for the rest of this run: later calls fail fast with
    the same error, without ever calling the underlying client's start()/
    crawl() again."""

    def __init__(self, client: Tier2Client) -> None:
        self._client = client
        self._tripped_reason: str | None = None

    def start(self) -> None:
        if self._tripped_reason is not None:
            raise BrowserUnavailableError(self._tripped_reason)
        try:
            self._client.start()
        except BrowserUnavailableError as exc:
            self._tripped_reason = str(exc)
            raise

    def crawl(self, url: str) -> Tier2Page:
        if self._tripped_reason is not None:
            raise BrowserUnavailableError(self._tripped_reason)
        try:
            return self._client.crawl(url)
        except BrowserUnavailableError as exc:
            self._tripped_reason = str(exc)
            raise

    def close(self) -> None:
        self._client.close()


def fetch_markdown(url: str, session, browser_client: Tier2Client) -> str | None:
    session.throttle(url)
    result = browser_client.crawl(url)
    if not result.markdown:
        return None
    return str(result.markdown)


def fetch_html(url: str, session, browser_client: Tier2Client) -> str | None:
    session.throttle(url)
    result = browser_client.crawl(url)
    if not result.html:
        return None
    return str(result.html)


def resolve(url: str, session, browser_client: Tier2Client, provider_name: str = RESOLVER_NAME) -> ResolvedJD | None:
    text = fetch_markdown(url, session, browser_client)
    if text is None or not generic.passes_quality(text):
        return None
    return ResolvedJD(jd_text=text, resolver=provider_name, jd_quality="ats")
