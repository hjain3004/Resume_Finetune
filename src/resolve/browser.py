"""Tier-2 browser resolver (M6.5, PHASE2_KICKOFF.md): renders a page with
crawl4ai when no tier-1 resolver applies and generic.py's trafilatura pass
fails its quality heuristic. Deterministic rendering/markdown only — no
crawl4ai LLM-extraction strategies, no stealth/anti-bot-evasion. A site that
blocks a plain headless browser (e.g. tesla.com) is expected to stay tier-3.

crawl4ai is async; `_crawl_async` is the sole seam mocked in tests (no real
browser in pytest). Everything else in the pipeline stays synchronous by
wrapping it in `asyncio.run()`.
"""

from __future__ import annotations

import asyncio

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, CrawlResult

from src.models import ResolvedJD
from src.resolve import generic

RESOLVER_NAME = "browser"


async def _crawl_async(url: str) -> CrawlResult:
    async with AsyncWebCrawler() as crawler:
        return await crawler.arun(url=url, config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS))


def _crawl(url: str) -> CrawlResult:
    return asyncio.run(_crawl_async(url))


def fetch_markdown(url: str, session) -> str | None:
    session.throttle(url)
    result = _crawl(url)
    if not result.success:
        return None
    return str(result.markdown)


def fetch_html(url: str, session) -> str | None:
    session.throttle(url)
    result = _crawl(url)
    if not result.success:
        return None
    return str(result.html)


def resolve(url: str, session) -> ResolvedJD | None:
    text = fetch_markdown(url, session)
    if text is None or not generic.passes_quality(text):
        return None
    return ResolvedJD(jd_text=text, resolver=RESOLVER_NAME, jd_quality="ats")
