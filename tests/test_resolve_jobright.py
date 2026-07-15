import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.resolve import jobright

FIXTURES = Path(__file__).parent / "fixtures"


def _jobright_html() -> str:
    return (FIXTURES / "jobright_amazon_page.body").read_text()


class _RaisingBrowserClient:
    """M6.10 regression aid: proves a code path never touches the browser --
    any call to crawl()/start() fails the test loudly instead of silently
    returning something plausible."""

    def crawl(self, url):
        raise AssertionError(f"browser client should not be used, but crawl({url!r}) was called")

    def start(self):
        raise AssertionError("browser client should not be used, but start() was called")


# --- find_ats_link -----------------------------------------------------------


def test_find_ats_link_returns_none_for_jobright_and_relative_hrefs():
    html = """
    <a href="/jobs/software-engineer">internal</a>
    <a href="https://jobright.ai/company/amazon">Amazon on Jobright</a>
    """
    assert jobright.find_ats_link(html) is None


def test_find_ats_link_finds_known_ats_host():
    html = '<a href="https://boards.greenhouse.io/acme/jobs/123">View posting</a>'
    assert jobright.find_ats_link(html) == "https://boards.greenhouse.io/acme/jobs/123"


def test_find_ats_link_finds_apply_text_link_to_unknown_host():
    html = '<a href="https://careers.acme.com/job/123">Apply Now</a>'
    assert jobright.find_ats_link(html) == "https://careers.acme.com/job/123"


def test_find_ats_link_ignores_unrelated_outbound_links():
    html = """
    <a href="https://www.glassdoor.com/Overview/Working-at-Acme">Glassdoor Overview</a>
    <a href="https://x.com/acme">Follow us</a>
    <a href="https://acme.com">Company site</a>
    """
    assert jobright.find_ats_link(html) is None


def test_find_ats_link_returns_none_for_real_fixture():
    # Confirmed live: this jobright page's apply flow is client-rendered, so no
    # outbound ATS/apply link is present in the static HTML.
    assert jobright.find_ats_link(_jobright_html()) is None


# --- resolve: __NEXT_DATA__ aggregator fallback ------------------------------


def test_resolve_uses_next_data_when_no_ats_link():
    session = MagicMock()
    result = jobright.resolve(
        "https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd",
        _jobright_html(),
        session,
    )

    assert result is not None
    assert result.jd_quality == "aggregator"
    assert result.resolver == "jobright"
    assert result.raw_title == "Software Development Engineer, PXT"
    assert result.raw_location == "Bellevue, WA"
    assert "sponsor_likely" in result.flags
    assert "Amazon is seeking a Software Development Engineer" in result.jd_text
    assert "Lead the architectural design" in result.jd_text
    assert "1+ years of non-internship" in result.jd_text
    assert "jobright.ai/jobs/info/6a0f128480bf0430c76309fd" in result.notes
    session.get.assert_not_called()


def test_resolve_returns_none_when_no_next_data_and_no_ats_link():
    session = MagicMock()
    result = jobright.resolve("https://jobright.ai/jobs/info/x", "<html>nothing here</html>", session)
    assert result is None


def test_resolve_prefers_ats_link_path_over_next_data():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)
    html = (
        '<a href="https://boards.greenhouse.io/acme/jobs/999">Apply</a>'
        + _jobright_html()
    )

    result = jobright.resolve("https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd", html, session)

    # greenhouse resolve fails (404) since it's not a real endpoint in this test,
    # so resolve() should return None rather than silently falling through to
    # the aggregator path once an ATS link was found.
    assert result is None


# --- M6.10: static-first ordering (NEXT_DATA before browser rendering) -------


def test_resolve_uses_next_data_without_touching_browser_even_when_enabled():
    # Regression for M6.10: previously, resolve() attempted browser rendering
    # BEFORE accepting a valid static __NEXT_DATA__ payload, spending a browser
    # launch on every jobright row that had no static ATS link -- even though
    # the aggregator-quality payload was already sufficient. A valid static
    # __NEXT_DATA__ must now win outright; the browser client must never be
    # touched, proven here with a fake that raises if called at all.
    session = MagicMock()
    result = jobright.resolve(
        "https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd",
        _jobright_html(),
        session,
        browser_resolver=True,
        browser_client=_RaisingBrowserClient(),
    )

    assert result is not None
    assert result.jd_quality == "aggregator"
    assert result.resolver == "jobright"


def test_resolve_does_not_render_when_browser_resolver_disabled():
    session = MagicMock()
    with patch("src.resolve.browser.fetch_html") as mock_fetch_html:
        result = jobright.resolve(
            "https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd",
            _jobright_html(),
            session,
        )

    mock_fetch_html.assert_not_called()
    assert result is not None
    assert result.jd_quality == "aggregator"


def test_resolve_falls_back_to_rendered_dom_when_neither_static_path_succeeds():
    # Both static paths (ATS link, __NEXT_DATA__) fail, browser_resolver is on,
    # and a browser_client is supplied: the rendered-DOM fallback must still run.
    session = MagicMock()
    rendered_html = '<a href="https://boards.greenhouse.io/acme/jobs/999">Apply</a>'
    fake_result = MagicMock(jd_text="real jd", resolver="greenhouse", raw_title="SWE", raw_location="Remote")
    browser_client = object()  # opaque sentinel; fetch_html itself is mocked below

    with patch("src.resolve.browser.fetch_html", return_value=rendered_html) as mock_fetch_html, \
         patch("src.resolve.greenhouse.resolve", return_value=fake_result) as mock_greenhouse_resolve:
        result = jobright.resolve(
            "https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd",
            "<html>nothing here, no ats link and no NEXT_DATA</html>",
            session,
            browser_resolver=True,
            browser_client=browser_client,
        )

    mock_fetch_html.assert_called_once_with(
        "https://jobright.ai/jobs/info/6a0f128480bf0430c76309fd", session, browser_client
    )
    mock_greenhouse_resolve.assert_called_once_with(
        "https://boards.greenhouse.io/acme/jobs/999", session
    )
    assert result is not None
    assert result.jd_text == "real jd"
    assert result.resolver == "greenhouse"
    assert result.jd_quality == "ats"
    assert result.ats_url == "https://boards.greenhouse.io/acme/jobs/999"


def test_resolve_returns_none_when_rendered_dom_also_has_no_link():
    session = MagicMock()
    with patch("src.resolve.browser.fetch_html", return_value="<html>still nothing</html>"):
        result = jobright.resolve(
            "https://jobright.ai/jobs/info/x",
            "<html>nothing here, no ats link and no NEXT_DATA</html>",
            session,
            browser_resolver=True,
            browser_client=object(),
        )

    assert result is None


def test_resolve_does_not_attempt_browser_when_no_client_is_supplied():
    # browser_resolver=True but browser_client=None (e.g. a caller that hasn't
    # wired the run-scoped client) must not call browser.fetch_html at all.
    session = MagicMock()
    with patch("src.resolve.browser.fetch_html") as mock_fetch_html:
        result = jobright.resolve(
            "https://jobright.ai/jobs/info/x",
            "<html>nothing here, no ats link and no NEXT_DATA</html>",
            session,
            browser_resolver=True,
            browser_client=None,
        )

    mock_fetch_html.assert_not_called()
    assert result is None
