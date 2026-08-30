"""Typed, bounded outcomes for the research acquisition transports."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum


class ResearchOutcome(str, Enum):
    SUCCESS = "success"
    RETRIEVAL_FAILURE = "retrieval_failure"
    INCOMPLETE_EXTRACTION = "incomplete_extraction"
    TIMEOUT = "timeout"
    CAPTCHA = "captcha"
    LOGIN_REQUIRED = "login_required"
    PAYWALL = "paywall"
    ROBOTS_DENIED = "robots_denied"
    AUTH_FAILURE = "auth_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RATE_LIMITED = "rate_limited"
    POLICY_REJECTION = "policy_rejection"
    PROVIDER_FAILURE = "provider_failure"
    MALFORMED_OUTPUT = "malformed_output"


@dataclass(frozen=True)
class TransportResult:
    outcome: ResearchOutcome
    diagnostic: str


MAX_DIAGNOSTIC_LENGTH = 2000


def _safe_diagnostic(stdout: str = "", stderr: str = "") -> str:
    text = "\n".join(value for value in (stderr, stdout) if value).strip()
    text = re.sub(r"(?i)(authorization\s*:\s*(?:bearer\s+)?)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access_token|token|secret|password|passwd|cookie|session(?:id)?|authorization)\s*[=:]\s*)[^\s&]+", r"\1[REDACTED]", text)
    return text[:MAX_DIAGNOSTIC_LENGTH]


def classify_firecrawl_result(
    process: subprocess.CompletedProcess[str] | None,
    *,
    output_exists: bool,
    output_valid: bool = True,
    timed_out: bool = False,
    stdout: str = "",
    stderr: str = "",
) -> TransportResult:
    process_stdout = process.stdout if process is not None and isinstance(process.stdout, str) else ""
    process_stderr = process.stderr if process is not None and isinstance(process.stderr, str) else ""
    diagnostic = _safe_diagnostic(stderr or process_stderr, stdout or process_stdout)
    if timed_out:
        return TransportResult(ResearchOutcome.TIMEOUT, diagnostic or "Firecrawl timed out")
    if process is None:
        return TransportResult(ResearchOutcome.PROVIDER_FAILURE, diagnostic or "Firecrawl produced no process result")
    if process.returncode == 0:
        if not output_exists or not output_valid:
            return TransportResult(ResearchOutcome.MALFORMED_OUTPUT, diagnostic or "Firecrawl output missing, empty, or malformed")
        return TransportResult(ResearchOutcome.SUCCESS, diagnostic)
    lowered = f"{process_stdout}\n{process_stderr}".casefold()
    if "all scraping engines failed to retrieve content" in lowered or "retrieval failure" in lowered:
        outcome = ResearchOutcome.RETRIEVAL_FAILURE
    elif "captcha" in lowered:
        outcome = ResearchOutcome.CAPTCHA
    elif "login required" in lowered or "authentication required" in lowered:
        outcome = ResearchOutcome.LOGIN_REQUIRED
    elif "paywall" in lowered:
        outcome = ResearchOutcome.PAYWALL
    elif "robots" in lowered or "robots.txt" in lowered:
        outcome = ResearchOutcome.ROBOTS_DENIED
    elif "invalid api key" in lowered or "unauthorized" in lowered or "authentication failed" in lowered:
        outcome = ResearchOutcome.AUTH_FAILURE
    elif "budget" in lowered or "credits exhausted" in lowered:
        outcome = ResearchOutcome.BUDGET_EXHAUSTED
    elif "rate limit" in lowered or "too many requests" in lowered:
        outcome = ResearchOutcome.RATE_LIMITED
    elif "policy" in lowered or "disallowed" in lowered or "refused" in lowered:
        outcome = ResearchOutcome.POLICY_REJECTION
    elif "incomplete" in lowered or "missing markdown" in lowered:
        outcome = ResearchOutcome.INCOMPLETE_EXTRACTION
    else:
        outcome = ResearchOutcome.PROVIDER_FAILURE
    return TransportResult(outcome, diagnostic or outcome.value)
