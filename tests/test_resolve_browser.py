"""M6.10: browser.py owns one run-scoped BrowserClient lifecycle instead of
launching a fresh Chromium per URL. These tests never start a real browser --
`Crawl4AIBrowserClient` tests patch `browser.AsyncWebCrawler` itself, and the
`fetch_*`/`resolve` tests use a plain in-memory fake client.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.resolve import browser


def _fake_result(success=True, markdown="", html=""):
    return SimpleNamespace(success=success, markdown=markdown, html=html)


class FakeBrowserClient:
    """A BrowserClient test double: records call counts, returns a
    pre-set CrawlResult (or raises), never touches asyncio/Playwright."""

    def __init__(self, result=None, raise_on_crawl=None):
        self.start_calls = 0
        self.crawl_calls = []
        self.close_calls = 0
        self._result = result if result is not None else _fake_result()
        self._raise_on_crawl = raise_on_crawl

    def start(self) -> None:
        self.start_calls += 1

    def crawl(self, url: str):
        self.crawl_calls.append(url)
        if self._raise_on_crawl is not None:
            raise self._raise_on_crawl
        return self._result

    def close(self) -> None:
        self.close_calls += 1


# --- fetch_markdown / fetch_html / resolve use an injected client -----------


def test_fetch_markdown_returns_markdown_on_success():
    client = FakeBrowserClient(result=_fake_result(markdown="# Job\n\nResponsibilities..."))
    session = MagicMock()

    result = browser.fetch_markdown("https://careers.acme.com/job/1", session, client)

    assert result == "# Job\n\nResponsibilities..."


def test_fetch_markdown_returns_none_on_crawl_failure():
    client = FakeBrowserClient(result=_fake_result(success=False))
    session = MagicMock()

    result = browser.fetch_markdown("https://careers.acme.com/job/1", session, client)

    assert result is None


def test_fetch_markdown_throttles_before_crawling():
    client = FakeBrowserClient(result=_fake_result(markdown="x"))
    session = MagicMock()

    browser.fetch_markdown("https://careers.acme.com/job/1", session, client)

    session.throttle.assert_called_once_with("https://careers.acme.com/job/1")


def test_fetch_html_returns_html_on_success():
    client = FakeBrowserClient(result=_fake_result(html="<html>rendered</html>"))
    session = MagicMock()

    result = browser.fetch_html("https://careers.acme.com/job/1", session, client)

    assert result == "<html>rendered</html>"


def test_fetch_html_returns_none_on_crawl_failure():
    client = FakeBrowserClient(result=_fake_result(success=False))
    session = MagicMock()

    result = browser.fetch_html("https://careers.acme.com/job/1", session, client)

    assert result is None


def test_resolve_returns_resolved_jd_when_quality_passes():
    markdown = "Responsibilities: " + "build distributed systems. " * 30
    client = FakeBrowserClient(result=_fake_result(markdown=markdown))
    session = MagicMock()

    result = browser.resolve("https://careers.acme.com/job/1", session, client)

    assert result is not None
    assert result.jd_text == markdown
    assert result.resolver == "browser"
    assert result.jd_quality == "ats"


def test_resolve_returns_none_when_quality_heuristic_fails():
    client = FakeBrowserClient(result=_fake_result(markdown="too short"))
    session = MagicMock()

    result = browser.resolve("https://careers.acme.com/job/1", session, client)

    assert result is None


def test_resolve_returns_none_when_render_fails():
    client = FakeBrowserClient(result=_fake_result(success=False))
    session = MagicMock()

    result = browser.resolve("https://careers.acme.com/job/1", session, client)

    assert result is None


def test_two_fetches_share_one_client_and_each_call_crawls_once():
    # The run-scoped client itself owns lifecycle reuse (proven separately
    # against Crawl4AIBrowserClient below); at the fetch_* boundary the
    # contract is simply "use the client I was given, don't construct a new one."
    client = FakeBrowserClient(result=_fake_result(markdown="x"))
    session = MagicMock()

    browser.fetch_markdown("https://careers.acme.com/job/1", session, client)
    browser.fetch_markdown("https://careers.acme.com/job/2", session, client)

    assert client.crawl_calls == [
        "https://careers.acme.com/job/1",
        "https://careers.acme.com/job/2",
    ]
    assert client.start_calls == 0  # fetch_* never calls start() directly


def test_resolve_propagates_browser_unavailable_error():
    client = FakeBrowserClient(raise_on_crawl=browser.BrowserUnavailableError("browser_unavailable"))
    session = MagicMock()

    with pytest.raises(browser.BrowserUnavailableError):
        browser.resolve("https://careers.acme.com/job/1", session, client)


# --- Crawl4AIBrowserClient: real lifecycle, fake AsyncWebCrawler ------------


def _mock_async_web_crawler():
    instance = MagicMock()
    instance.start = AsyncMock()
    instance.close = AsyncMock()
    instance.arun = AsyncMock(return_value=_fake_result(markdown="rendered"))
    factory = MagicMock(return_value=instance)
    return factory, instance


def test_crawl4ai_client_shares_one_start_across_two_crawls():
    factory, instance = _mock_async_web_crawler()
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        client.crawl("https://a.example/1")
        client.crawl("https://a.example/2")
        client.close()

    factory.assert_called_once()
    instance.start.assert_awaited_once()
    assert instance.arun.await_count == 2


def test_crawl4ai_client_start_failure_raises_browser_unavailable_error():
    factory = MagicMock(side_effect=RuntimeError("no chromium"))
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        with pytest.raises(browser.BrowserUnavailableError):
            client.start()


def test_crawl4ai_client_crawl_failure_raises_browser_unavailable_error():
    factory, instance = _mock_async_web_crawler()
    instance.arun = AsyncMock(side_effect=RuntimeError("navigation timeout"))
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        with pytest.raises(browser.BrowserUnavailableError):
            client.crawl("https://a.example/1")


def test_crawl4ai_client_start_is_idempotent_after_success():
    factory, instance = _mock_async_web_crawler()
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        client.start()
        client.start()
        client.close()

    factory.assert_called_once()
    instance.start.assert_awaited_once()


def test_crawl4ai_client_start_raises_permanently_once_unavailable():
    factory = MagicMock(side_effect=RuntimeError("no chromium"))
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        with pytest.raises(browser.BrowserUnavailableError):
            client.start()
        # a second attempt does not retry construction; it fails fast
        with pytest.raises(browser.BrowserUnavailableError):
            client.start()

    assert factory.call_count == 1


def test_crawl4ai_client_close_is_idempotent():
    factory, instance = _mock_async_web_crawler()
    with patch.object(browser, "AsyncWebCrawler", factory):
        client = browser.Crawl4AIBrowserClient()
        client.start()
        client.close()
        client.close()  # must not raise


# --- Circuit breaker ---------------------------------------------------------


def test_circuit_breaker_passes_through_successful_calls():
    client = FakeBrowserClient(result=_fake_result(markdown="x"))
    breaker = browser.CircuitBreakingBrowserClient(client)

    breaker.crawl("https://a.example/1")
    breaker.crawl("https://a.example/2")

    assert client.crawl_calls == ["https://a.example/1", "https://a.example/2"]


def test_circuit_breaker_trips_after_first_unavailable_error_and_skips_later_calls():
    client = FakeBrowserClient(raise_on_crawl=browser.BrowserUnavailableError("boom"))
    breaker = browser.CircuitBreakingBrowserClient(client)

    with pytest.raises(browser.BrowserUnavailableError):
        breaker.crawl("https://a.example/1")
    assert client.crawl_calls == ["https://a.example/1"]

    with pytest.raises(browser.BrowserUnavailableError):
        breaker.crawl("https://a.example/2")

    # the underlying client was never asked to crawl again once tripped
    assert client.crawl_calls == ["https://a.example/1"]


def test_circuit_breaker_start_also_trips_and_short_circuits():
    client = FakeBrowserClient()

    def _raise():
        raise browser.BrowserUnavailableError("no chromium")

    client.start = _raise
    breaker = browser.CircuitBreakingBrowserClient(client)

    with pytest.raises(browser.BrowserUnavailableError):
        breaker.start()
    with pytest.raises(browser.BrowserUnavailableError):
        breaker.start()
