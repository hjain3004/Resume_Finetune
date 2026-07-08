from unittest.mock import MagicMock, patch

from src import resolve
from src.resolve import amazon_jobs, ashby, browser, generic, greenhouse, jobright, lever, workday, wrapper


def test_route_amazon_jobs():
    assert resolve.route("https://www.amazon.jobs/en/jobs/123/some-role") is amazon_jobs


def test_route_jobright_com():
    assert resolve.route("https://jobright.com/jobs/info/abc") is jobright


def test_route_jobright_ai():
    assert resolve.route("https://jobright.ai/jobs/info/abc") is jobright


def test_route_greenhouse_boards_subdomain():
    assert resolve.route("https://boards.greenhouse.io/acme/jobs/123") is greenhouse


def test_route_greenhouse_job_boards_subdomain():
    assert resolve.route("https://job-boards.greenhouse.io/acme/jobs/123") is greenhouse


def test_route_lever():
    assert resolve.route("https://jobs.lever.co/acme/abc-123") is lever


def test_route_ashby():
    assert resolve.route("https://jobs.ashbyhq.com/acme/abc-123") is ashby


def test_route_workday():
    assert resolve.route("https://acme.wd1.myworkdayjobs.com/en-US/site/job/foo_R1") is workday


def test_route_falls_back_to_generic_for_anything_else():
    assert resolve.route("https://example.com/careers/123") is generic


def test_route_falls_back_to_generic_for_shortener_before_following_redirect():
    assert resolve.route("https://simplify.jobs/p/some-id") is generic


def test_resolve_routes_on_final_url_after_redirect_not_original():
    session = MagicMock()
    redirect_response = MagicMock(status_code=200)
    redirect_response.url = "https://boards.greenhouse.io/acme/jobs/123"
    session.get.return_value = redirect_response

    with patch.object(greenhouse, "resolve", return_value="RESOLVED") as mock_gh_resolve:
        result = resolve.resolve("https://simplify.jobs/p/some-id", session)

    mock_gh_resolve.assert_called_once_with(
        "https://boards.greenhouse.io/acme/jobs/123", session
    )
    assert result == "RESOLVED"


def test_resolve_returns_none_when_initial_fetch_fails():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=500)

    result = resolve.resolve("https://simplify.jobs/p/some-id", session)

    assert result is None


def test_resolve_does_not_try_browser_on_initial_fetch_failure_when_toggle_disabled():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=410)

    with patch.object(browser, "resolve") as mock_browser:
        result = resolve.resolve("https://careers.example.com/job/1", session)

    mock_browser.assert_not_called()
    assert result is None


def test_resolve_falls_back_to_browser_when_a_generic_hostname_blocks_the_plain_fetch():
    # Real M6.5 case: qualtrics.com returns 410 to a plain `requests` GET (bot
    # detection) but renders fine for crawl4ai's headless browser.
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=410)

    with patch.object(browser, "resolve", return_value="BROWSER_RESOLVED") as mock_browser:
        result = resolve.resolve("https://careers.example.com/job/1", session, browser_resolver=True)

    mock_browser.assert_called_once_with("https://careers.example.com/job/1", session)
    assert result == "BROWSER_RESOLVED"


def test_resolve_does_not_try_browser_on_initial_fetch_failure_for_a_known_ats_host():
    # tier-2 is a generic-only rescue; a blocked tier-1 host (e.g. Tesla-style
    # Akamai block) should stay tier-3, not get a browser retry.
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=403)

    with patch.object(browser, "resolve") as mock_browser:
        result = resolve.resolve(
            "https://boards.greenhouse.io/acme/jobs/123", session, browser_resolver=True
        )

    mock_browser.assert_not_called()
    assert result is None


def test_resolve_tries_wrapper_map_before_generic_on_a_wrapper_hostname():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://careers.roblox.com/jobs/7142298"
    response.text = "<html>no gh_jid here</html>"
    session.get.return_value = response

    with (
        patch.object(wrapper, "resolve_wrapper_map", return_value="WRAPPED") as mock_map,
        patch.object(generic, "resolve") as mock_generic,
    ):
        result = resolve.resolve("https://careers.roblox.com/jobs/7142298", session)

    mock_map.assert_called_once_with("https://careers.roblox.com/jobs/7142298", session)
    mock_generic.assert_not_called()
    assert result == "WRAPPED"


def test_resolve_tries_gh_jid_unwrap_when_wrapper_map_misses():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://amperity.com/careers/8040043?gh_jid=8040043"
    response.text = "<html>wrapper page</html>"
    session.get.return_value = response

    with (
        patch.object(wrapper, "resolve_wrapper_map", return_value=None),
        patch.object(wrapper, "resolve_gh_jid", return_value="UNWRAPPED") as mock_gh_jid,
        patch.object(generic, "resolve") as mock_generic,
    ):
        result = resolve.resolve("https://amperity.com/careers/8040043?gh_jid=8040043", session)

    mock_gh_jid.assert_called_once_with(
        "https://amperity.com/careers/8040043?gh_jid=8040043", "<html>wrapper page</html>", session
    )
    mock_generic.assert_not_called()
    assert result == "UNWRAPPED"


def test_resolve_dispatches_jobright_with_fetched_html():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://jobright.ai/jobs/info/abc"
    response.text = "<html>jobright page</html>"
    session.get.return_value = response

    with patch.object(jobright, "resolve", return_value="JOBRIGHT_RESOLVED") as mock_jobright:
        result = resolve.resolve("https://jobright.ai/jobs/info/abc", session)

    mock_jobright.assert_called_once_with(
        "https://jobright.ai/jobs/info/abc", "<html>jobright page</html>", session, browser_resolver=False
    )
    assert result == "JOBRIGHT_RESOLVED"


def test_resolve_falls_back_to_generic_when_no_wrapper_matches():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://example.com/careers/123"
    response.text = "<html>plain careers page</html>"
    session.get.return_value = response

    with (
        patch.object(wrapper, "resolve_wrapper_map", return_value=None),
        patch.object(wrapper, "resolve_gh_jid", return_value=None),
        patch.object(generic, "resolve", return_value="GENERIC") as mock_generic,
    ):
        result = resolve.resolve("https://example.com/careers/123", session)

    mock_generic.assert_called_once_with("https://example.com/careers/123", session)
    assert result == "GENERIC"


# --- M6.5 tier-2 browser fallback --------------------------------------------


def test_resolve_does_not_try_browser_when_toggle_disabled_by_default():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://example.com/careers/123"
    response.text = "<html>plain careers page</html>"
    session.get.return_value = response

    with (
        patch.object(wrapper, "resolve_wrapper_map", return_value=None),
        patch.object(wrapper, "resolve_gh_jid", return_value=None),
        patch.object(generic, "resolve", return_value=None),
        patch.object(browser, "resolve") as mock_browser,
    ):
        result = resolve.resolve("https://example.com/careers/123", session)

    mock_browser.assert_not_called()
    assert result is None


def test_resolve_falls_back_to_browser_when_generic_fails_and_toggle_enabled():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://example.com/careers/123"
    response.text = "<html>plain careers page</html>"
    session.get.return_value = response

    with (
        patch.object(wrapper, "resolve_wrapper_map", return_value=None),
        patch.object(wrapper, "resolve_gh_jid", return_value=None),
        patch.object(generic, "resolve", return_value=None),
        patch.object(browser, "resolve", return_value="BROWSER_RESOLVED") as mock_browser,
    ):
        result = resolve.resolve("https://example.com/careers/123", session, browser_resolver=True)

    mock_browser.assert_called_once_with("https://example.com/careers/123", session)
    assert result == "BROWSER_RESOLVED"


def test_resolve_does_not_try_browser_when_a_specific_resolver_fails():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://boards.greenhouse.io/acme/jobs/123"
    session.get.return_value = response

    with (
        patch.object(greenhouse, "resolve", return_value=None),
        patch.object(browser, "resolve") as mock_browser,
    ):
        result = resolve.resolve(
            "https://boards.greenhouse.io/acme/jobs/123", session, browser_resolver=True
        )

    mock_browser.assert_not_called()
    assert result is None


def test_resolve_passes_browser_resolver_toggle_through_to_jobright():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.url = "https://jobright.ai/jobs/info/abc"
    response.text = "<html>jobright page</html>"
    session.get.return_value = response

    with patch.object(jobright, "resolve", return_value="JOBRIGHT_RESOLVED") as mock_jobright:
        result = resolve.resolve("https://jobright.ai/jobs/info/abc", session, browser_resolver=True)

    mock_jobright.assert_called_once_with(
        "https://jobright.ai/jobs/info/abc", "<html>jobright page</html>", session, browser_resolver=True
    )
    assert result == "JOBRIGHT_RESOLVED"
