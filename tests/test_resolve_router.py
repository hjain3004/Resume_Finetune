from unittest.mock import MagicMock, patch

from src import resolve
from src.resolve import amazon_jobs, ashby, generic, greenhouse, lever, workday, wrapper


def test_route_amazon_jobs():
    assert resolve.route("https://www.amazon.jobs/en/jobs/123/some-role") is amazon_jobs


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
