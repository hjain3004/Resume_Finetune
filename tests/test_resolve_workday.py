import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import workday

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def test_resolve_returns_jd_with_expected_substring_no_lang_segment():
    session = MagicMock()
    session.get.return_value = _fixture_response("workday_cadence_R54895")

    result = workday.resolve(
        "https://cadence.wd1.myworkdayjobs.com/University_Talent/job/"
        "Software-Engineer-II--New-College-Grad-2026-_R54895-1",
        session,
    )

    assert result is not None
    assert "Allegro software development team" in result.jd_text
    assert result.resolver == "workday"
    assert result.raw_title == "Software Engineer II (New College Grad 2026)"


def test_resolve_drops_language_segment_when_calling_json_endpoint():
    session = MagicMock()
    session.get.return_value = _fixture_response("workday_cadence_R54895")

    workday.resolve(
        "https://cadence.wd1.myworkdayjobs.com/en-US/University_Talent/job/"
        "Software-Engineer-II--New-College-Grad-2026-_R54895-1",
        session,
    )

    called_url = session.get.call_args[0][0]
    assert called_url == (
        "https://cadence.wd1.myworkdayjobs.com/wday/cxs/cadence/University_Talent/job/"
        "Software-Engineer-II--New-College-Grad-2026-_R54895-1"
    )


def test_resolve_returns_none_for_unmatched_url():
    session = MagicMock()
    result = workday.resolve("https://example.com/not-workday", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_returns_none_on_403():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=403)

    result = workday.resolve(
        "https://cadence.wd1.myworkdayjobs.com/University_Talent/job/foo_R1", session
    )

    assert result is None


def test_resolve_returns_none_on_malformed_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response

    result = workday.resolve(
        "https://cadence.wd1.myworkdayjobs.com/University_Talent/job/foo_R1", session
    )

    assert result is None


def test_resolve_returns_none_on_schema_surprise():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = {"unexpectedShape": True}
    session.get.return_value = response

    result = workday.resolve(
        "https://cadence.wd1.myworkdayjobs.com/University_Talent/job/foo_R1", session
    )

    assert result is None
