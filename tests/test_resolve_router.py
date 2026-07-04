from unittest.mock import MagicMock, patch

from src import resolve
from src.resolve import ashby, generic, greenhouse, lever, workday


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
