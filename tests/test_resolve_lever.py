import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import lever

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def test_resolve_returns_jd_with_expected_substring():
    session = MagicMock()
    session.get.return_value = _fixture_response("lever_palantir_e500bcf3")

    result = lever.resolve(
        "https://jobs.lever.co/palantir/e500bcf3-19d8-4d3c-b340-4d76e4a55b40", session
    )

    assert result is not None
    assert "Palantir builds the world" in result.jd_text
    assert "What We Value" in result.jd_text
    assert result.resolver == "lever"
    assert result.raw_title == "Forward Deployed Software Engineer, New Grad - Commercial"
    assert result.raw_location == "Chicago, IL"


def test_resolve_calls_the_postings_api_with_parsed_company_and_id():
    session = MagicMock()
    session.get.return_value = _fixture_response("lever_palantir_e500bcf3")

    lever.resolve("https://jobs.lever.co/palantir/e500bcf3-19d8-4d3c-b340-4d76e4a55b40", session)

    called_url = session.get.call_args[0][0]
    assert called_url == "https://api.lever.co/v0/postings/palantir/e500bcf3-19d8-4d3c-b340-4d76e4a55b40"


def test_resolve_returns_none_for_unmatched_url():
    session = MagicMock()
    result = lever.resolve("https://example.com/not-a-lever-url", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_returns_none_on_404():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)

    result = lever.resolve("https://jobs.lever.co/palantir/does-not-exist", session)

    assert result is None


def test_resolve_returns_none_on_malformed_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response

    result = lever.resolve("https://jobs.lever.co/palantir/e500bcf3-19d8-4d3c-b340-4d76e4a55b40", session)

    assert result is None


def test_resolve_returns_none_on_missing_fields():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"description": "<p>hi</p>"}
    session.get.return_value = response

    result = lever.resolve("https://jobs.lever.co/palantir/e500bcf3-19d8-4d3c-b340-4d76e4a55b40", session)

    assert result is None
