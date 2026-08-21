"""Tests for the S1 orchestration layer (M8P-1): ties prompt-building,
the safe invocation wrapper, I11 tracing, and strict/semantic parsing
together into one typed S1Outcome per attempt. No network, no real model
call -- subprocess.run is patched throughout."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.tailor.s1 import S1Request
from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind, run_s1_invocation

JD_TEXT = "We need a Backend Engineer with 3+ years of Python experience."

VALID_RESPONSE_JSON = json.dumps(
    {
        "must_have": [{"term": "Python", "quote": "3+ years of Python experience"}],
        "nice_to_have": [],
        "responsibilities_summary": [],
        "seniority_signals": [],
        "disqualifiers": [],
        "company_context": None,
        "suspected_injection": [],
    }
)

INJECTION_RESPONSE_JSON = json.dumps(
    {
        "must_have": [],
        "nice_to_have": [],
        "responsibilities_summary": [],
        "seniority_signals": [],
        "disqualifiers": [],
        "company_context": None,
        "suspected_injection": [
            {"quote": "3+ years of Python experience", "reason": "looks like an embedded directive"}
        ],
    }
)


@pytest.fixture
def request_obj() -> S1Request:
    return S1Request(job_id=119, company="Cisco", title="ML Engineer", jd_text=JD_TEXT, jd_quality="ats")


@pytest.fixture
def prompt_template_path(tmp_path):
    path = tmp_path / "tailoring_s1.md"
    path.write_text("Analyze:\n{{S1_REQUEST_JSON}}\nReturn JSON only.")
    return path


@pytest.fixture
def request_path(tmp_path, request_obj):
    from src.tailor.s1 import s1_request_to_dict

    path = tmp_path / "s1_request.json"
    path.write_text(json.dumps(s1_request_to_dict(request_obj), indent=2))
    return path


def test_valid_response_produces_valid_outcome_and_trace(tmp_path, request_obj, prompt_template_path, request_path):
    trace_dir = tmp_path / "traces"
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=VALID_RESPONSE_JSON, stderr="")
    ):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=trace_dir,
        )

    assert isinstance(outcome, S1Outcome)
    assert outcome.kind == S1OutcomeKind.VALID
    assert outcome.response is not None
    assert outcome.response.must_have[0].term == "Python"
    assert outcome.trace_path is not None
    assert outcome.trace_path.exists()
    trace_data = json.loads(outcome.trace_path.read_text())
    assert trace_data["invocation_type"] == "tailoring_s1"
    assert trace_data["raw_output"] == VALID_RESPONSE_JSON


def test_injection_suspected_blocks_downstream(tmp_path, request_obj, prompt_template_path, request_path):
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=INJECTION_RESPONSE_JSON, stderr="")
    ):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.INJECTION_BLOCKED
    assert outcome.response is not None
    assert outcome.response.suspected_injection


def test_malformed_json_is_parse_failure_but_still_traced(tmp_path, request_obj, prompt_template_path, request_path):
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="not json at all", stderr="")
    ):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.PARSE_FAILURE
    assert outcome.response is None
    assert outcome.trace_path is not None
    assert outcome.trace_path.exists()


def test_semantically_invalid_response_is_semantic_failure_but_still_traced(
    tmp_path, request_obj, prompt_template_path, request_path
):
    bad = json.dumps(
        {
            "must_have": [{"term": "Rust", "quote": "5+ years of Rust experience"}],
            "nice_to_have": [],
            "responsibilities_summary": [],
            "seniority_signals": [],
            "disqualifiers": [],
            "company_context": None,
            "suspected_injection": [],
        }
    )
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=bad, stderr="")):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.SEMANTIC_FAILURE
    assert outcome.trace_path is not None


def test_invocation_failure_with_no_stdout_produces_no_trace(tmp_path, request_obj, prompt_template_path, request_path):
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.INVOCATION_FAILURE
    assert outcome.response is None
    assert outcome.trace_path is None
    assert not (tmp_path / "traces").exists()


def test_invocation_failure_with_raw_stdout_is_still_traced(tmp_path, request_obj, prompt_template_path, request_path):
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout="garbled partial output", stderr="boom")
    ):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_path is not None
    trace_data = json.loads(outcome.trace_path.read_text())
    assert trace_data["raw_output"] == "garbled partial output"


def test_invocation_timeout_produces_no_trace(tmp_path, request_obj, prompt_template_path, request_path):
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1)):
        outcome = run_s1_invocation(
            request_obj,
            prompt_template_path=prompt_template_path,
            request_path=request_path,
            timeout=1,
            trace_dir=tmp_path / "traces",
        )
    assert outcome.kind == S1OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_path is None


def test_every_outcome_kind_is_an_immutable_new_trace_per_attempt(tmp_path, request_obj, prompt_template_path, request_path):
    trace_dir = tmp_path / "traces"
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=VALID_RESPONSE_JSON, stderr="")
    ):
        outcome_1 = run_s1_invocation(
            request_obj, prompt_template_path=prompt_template_path, request_path=request_path, trace_dir=trace_dir
        )
        outcome_2 = run_s1_invocation(
            request_obj, prompt_template_path=prompt_template_path, request_path=request_path, trace_dir=trace_dir
        )
    assert outcome_1.trace_path != outcome_2.trace_path
    assert outcome_1.trace_path.exists() and outcome_2.trace_path.exists()
