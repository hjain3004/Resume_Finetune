import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import amazon_jobs

FIXTURES = Path(__file__).parent / "fixtures"
JOB_ID = "3093439"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def test_resolve_returns_jd_with_expected_fields():
    session = MagicMock()
    session.get.return_value = _fixture_response("amazon_jobs_3093439")

    result = amazon_jobs.resolve(
        f"https://www.amazon.jobs/en/jobs/{JOB_ID}/software-engineer", session
    )

    assert result is not None
    assert result.resolver == "amazon_jobs"
    assert result.raw_title == "Software Engineer"
    assert result.raw_location == "Seattle, Washington, USA"
    assert "Basic Qualifications:" in result.jd_text
    assert "Preferred Qualifications:" in result.jd_text


def test_resolve_queries_search_json_with_base_query():
    session = MagicMock()
    session.get.return_value = _fixture_response("amazon_jobs_3093439")

    amazon_jobs.resolve(f"https://www.amazon.jobs/en/jobs/{JOB_ID}/software-engineer", session)

    session.get.assert_called_once_with(
        "https://www.amazon.jobs/en/search.json", params={"base_query": JOB_ID}
    )


def test_resolve_handles_bare_amazon_jobs_host_without_www():
    session = MagicMock()
    session.get.return_value = _fixture_response("amazon_jobs_3093439")

    result = amazon_jobs.resolve(f"https://amazon.jobs/en/jobs/{JOB_ID}/software-engineer", session)

    assert result is not None


def test_resolve_returns_none_for_unmatched_url():
    session = MagicMock()
    result = amazon_jobs.resolve("https://example.com/not-amazon", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_returns_none_when_job_id_not_in_search_results():
    session = MagicMock()
    session.get.return_value = _fixture_response("amazon_jobs_3093439")

    result = amazon_jobs.resolve("https://www.amazon.jobs/en/jobs/9999999/some-role", session)

    assert result is None


def test_resolve_returns_none_on_non_200():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=500)

    result = amazon_jobs.resolve(f"https://www.amazon.jobs/en/jobs/{JOB_ID}/software-engineer", session)

    assert result is None


def test_resolve_returns_none_on_malformed_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response

    result = amazon_jobs.resolve(f"https://www.amazon.jobs/en/jobs/{JOB_ID}/software-engineer", session)

    assert result is None
