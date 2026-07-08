from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.resolve import browser


def _fake_result(success=True, markdown="", html=""):
    return SimpleNamespace(success=success, markdown=markdown, html=html)


def test_fetch_markdown_returns_markdown_on_success():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(markdown="# Job\n\nResponsibilities..."))):
        result = browser.fetch_markdown("https://careers.acme.com/job/1", session)

    assert result == "# Job\n\nResponsibilities..."


def test_fetch_markdown_returns_none_on_crawl_failure():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(success=False))):
        result = browser.fetch_markdown("https://careers.acme.com/job/1", session)

    assert result is None


def test_fetch_markdown_throttles_before_crawling():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(markdown="x"))):
        browser.fetch_markdown("https://careers.acme.com/job/1", session)

    session.throttle.assert_called_once_with("https://careers.acme.com/job/1")


def test_fetch_html_returns_html_on_success():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(html="<html>rendered</html>"))):
        result = browser.fetch_html("https://careers.acme.com/job/1", session)

    assert result == "<html>rendered</html>"


def test_fetch_html_returns_none_on_crawl_failure():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(success=False))):
        result = browser.fetch_html("https://careers.acme.com/job/1", session)

    assert result is None


def test_resolve_returns_resolved_jd_when_quality_passes():
    session = MagicMock()
    markdown = "Responsibilities: " + "build distributed systems. " * 30
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(markdown=markdown))):
        result = browser.resolve("https://careers.acme.com/job/1", session)

    assert result is not None
    assert result.jd_text == markdown
    assert result.resolver == "browser"
    assert result.jd_quality == "ats"


def test_resolve_returns_none_when_quality_heuristic_fails():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(markdown="too short"))):
        result = browser.resolve("https://careers.acme.com/job/1", session)

    assert result is None


def test_resolve_returns_none_when_render_fails():
    session = MagicMock()
    with patch.object(browser, "_crawl_async", AsyncMock(return_value=_fake_result(success=False))):
        result = browser.resolve("https://careers.acme.com/job/1", session)

    assert result is None
