import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import greenhouse

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def test_resolve_returns_jd_with_expected_substring():
    session = MagicMock()
    session.get.return_value = _fixture_response("greenhouse_thinkingmachines_5164607008")

    result = greenhouse.resolve(
        "https://job-boards.greenhouse.io/thinkingmachines/jobs/5164607008", session
    )

    assert result is not None
    assert "Thinking Machines Lab" in result.jd_text
    assert result.resolver == "greenhouse"
    assert result.raw_title == "Compensation Partner"


def test_resolve_calls_the_boards_api_with_parsed_board_and_id():
    session = MagicMock()
    session.get.return_value = _fixture_response("greenhouse_thinkingmachines_5164607008")

    greenhouse.resolve("https://boards.greenhouse.io/thinkingmachines/jobs/5164607008", session)

    called_url = session.get.call_args[0][0]
    assert called_url == "https://boards-api.greenhouse.io/v1/boards/thinkingmachines/jobs/5164607008"


def test_resolve_returns_none_for_unmatched_url():
    session = MagicMock()
    result = greenhouse.resolve("https://example.com/not-a-greenhouse-url", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_returns_none_on_404():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)

    result = greenhouse.resolve(
        "https://boards.greenhouse.io/thinkingmachines/jobs/999999999", session
    )

    assert result is None


def test_resolve_returns_none_on_malformed_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response

    result = greenhouse.resolve(
        "https://boards.greenhouse.io/thinkingmachines/jobs/5164607008", session
    )

    assert result is None


def test_resolve_returns_none_on_missing_fields():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"title": "Missing content field"}
    session.get.return_value = response

    result = greenhouse.resolve(
        "https://boards.greenhouse.io/thinkingmachines/jobs/5164607008", session
    )

    assert result is None
