from __future__ import annotations

import subprocess

import pytest

from src.resume_evidence.transport import ResearchOutcome, classify_firecrawl_result


def completed(returncode=1, stdout="", stderr=""):
    return subprocess.CompletedProcess(("firecrawl",), returncode, stdout, stderr)


def test_observed_retrieval_error_is_typed_retrieval_failure():
    result = classify_firecrawl_result(completed(stderr="All scraping engines failed to retrieve content from this URL."), output_exists=False)
    assert result.outcome is ResearchOutcome.RETRIEVAL_FAILURE


@pytest.mark.parametrize(("text", "expected"), [
    ("invalid api key", ResearchOutcome.AUTH_FAILURE),
    ("captcha required", ResearchOutcome.CAPTCHA),
    ("login required", ResearchOutcome.LOGIN_REQUIRED),
    ("paywall", ResearchOutcome.PAYWALL),
    ("robots denied", ResearchOutcome.ROBOTS_DENIED),
    ("budget exhausted", ResearchOutcome.BUDGET_EXHAUSTED),
    ("rate limit exceeded", ResearchOutcome.RATE_LIMITED),
])
def test_terminal_firecrawl_failures_are_not_retrieval_fallbacks(text, expected):
    result = classify_firecrawl_result(completed(stderr=text), output_exists=False)
    assert result.outcome is expected


def test_timeout_is_explicit_and_terminal():
    result = classify_firecrawl_result(None, output_exists=False, timed_out=True, stderr="timed out")
    assert result.outcome is ResearchOutcome.TIMEOUT


def test_unknown_nonzero_is_provider_failure():
    result = classify_firecrawl_result(completed(stderr="unexpected upstream failure"), output_exists=False)
    assert result.outcome is ResearchOutcome.PROVIDER_FAILURE


@pytest.mark.parametrize("output_exists", [False, True])
def test_success_without_valid_output_is_malformed(output_exists):
    result = classify_firecrawl_result(completed(returncode=0), output_exists=output_exists, output_valid=False)
    assert result.outcome is ResearchOutcome.MALFORMED_OUTPUT


def test_diagnostics_are_bounded_and_secret_free():
    result = classify_firecrawl_result(completed(stderr="Authorization: Bearer super-secret-token " * 100 + "?api_key=secret"), output_exists=False)
    assert len(result.diagnostic) <= 2000
    assert "super-secret-token" not in result.diagnostic
    assert "secret" not in result.diagnostic
