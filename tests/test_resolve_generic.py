from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import generic

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_response(name: str, status_code: int = 200):
    html = (FIXTURES / f"{name}.body").read_text(encoding="utf-8", errors="replace")
    return MagicMock(status_code=status_code, text=html)


def test_resolve_succeeds_on_real_careers_page():
    session = MagicMock()
    session.get.return_value = _fixture_response("generic_visa_smartrecruiters_success")

    result = generic.resolve(
        "https://jobs.smartrecruiters.com/Visa/744000119101657-software-engineer-new-college-grad-2026-austin-tx",
        session,
    )

    assert result is not None
    assert len(result.jd_text) >= 400
    assert result.resolver == "generic"


def test_resolve_returns_none_on_nav_shell_page():
    session = MagicMock()
    session.get.return_value = _fixture_response("generic_bentley_navshell_fail")

    result = generic.resolve(
        "https://jobs.bentley.com/job/Exton-Software-Engineer-PA-19341/1281097600", session
    )

    assert result is None


def test_resolve_returns_none_on_non_200():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404, text="")

    result = generic.resolve("https://example.com/gone", session)

    assert result is None


def test_resolve_returns_none_on_short_text_even_with_keyword():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200, text="<p>Requirements: experience with Python.</p>"
    )

    result = generic.resolve("https://example.com/short", session)

    assert result is None


def test_passes_quality_accepts_long_text_with_jd_keyword():
    assert generic.passes_quality("Responsibilities: " + "x" * 400) is True


def test_passes_quality_rejects_short_text():
    assert generic.passes_quality("Requirements: experience with Python.") is False


def test_passes_quality_rejects_long_text_without_jd_keyword():
    assert generic.passes_quality("lorem ipsum " * 100) is False


def test_passes_quality_rejects_closed_posting_with_job_keywords():
    text = (
        "We're sorry! This job is no longer available. "
        "Responsibilities and requirements for other openings: " + "x" * 400
    )
    assert generic.passes_quality(text) is False


def test_passes_quality_rejects_position_filled_notice():
    text = "Sorry, this position has been filled. " + "Experience required. " * 30
    assert generic.passes_quality(text) is False


def test_resolve_returns_none_on_closed_posting_page():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        text="<p>We're sorry! This job is no longer available. "
        + "Requirements: experience with Python. " * 20
        + "</p>",
    )

    result = generic.resolve("https://example.com/closed", session)

    assert result is None
