import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import ashby

FIXTURES = Path(__file__).parent / "fixtures"
JOB_ID = "2385c5a6-7f15-483e-9a30-2b8f66eb4a90"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def test_resolve_returns_jd_with_expected_substring():
    session = MagicMock()
    session.get.return_value = _fixture_response("ashby_creditgenie_board")

    result = ashby.resolve(f"https://jobs.ashbyhq.com/creditgenie/{JOB_ID}", session)

    assert result is not None
    assert "Credit Genie is a mobile-first financial wellness platform" in result.jd_text
    assert result.resolver == "ashby"
    assert result.raw_title == "Senior Software Engineer, Trust Platform"
    assert result.raw_location == "New York, NY"


def test_resolve_calls_the_job_board_api_with_parsed_org():
    session = MagicMock()
    session.get.return_value = _fixture_response("ashby_creditgenie_board")

    ashby.resolve(f"https://jobs.ashbyhq.com/creditgenie/{JOB_ID}", session)

    called_url = session.get.call_args[0][0]
    assert called_url == "https://api.ashbyhq.com/posting-api/job-board/creditgenie"


def test_resolve_returns_none_for_unmatched_url():
    session = MagicMock()
    result = ashby.resolve("https://example.com/not-ashby", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_returns_none_when_id_not_in_board():
    session = MagicMock()
    session.get.return_value = _fixture_response("ashby_creditgenie_board")

    result = ashby.resolve("https://jobs.ashbyhq.com/creditgenie/00000000-0000-0000-0000-000000000000", session)

    assert result is None


def test_resolve_returns_none_on_404():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)

    result = ashby.resolve(f"https://jobs.ashbyhq.com/creditgenie/{JOB_ID}", session)

    assert result is None


def test_resolve_returns_none_on_malformed_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response

    result = ashby.resolve(f"https://jobs.ashbyhq.com/creditgenie/{JOB_ID}", session)

    assert result is None
