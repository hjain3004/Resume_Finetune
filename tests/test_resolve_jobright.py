import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import jobright

FIXTURES = Path(__file__).parent / "fixtures"


def _jobright_html() -> str:
    return (FIXTURES / "jobright_amazon_page.body").read_text()


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
