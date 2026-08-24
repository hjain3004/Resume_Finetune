import json
import subprocess
from unittest.mock import MagicMock, patch

from src.tailor.s0_pipeline import S0OutcomeKind, run_s0_invocation
from tests.tailor.test_s0 import s0_request_fixture


def test_s0_pipeline_traces_valid_output(tmp_path):
    request = s0_request_fixture.__wrapped__()
    template = tmp_path / "prompt.md"; template.write_text("{{S0_REQUEST_JSON}}")
    request_path = tmp_path / "s0_request.json"; request_path.write_text("{}")
    output = json.dumps({"context_mode": "jd_only", "points": [
        {"sentence": "a", "profile_ids": [request.positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
        {"sentence": "b", "profile_ids": [request.positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
    ]})
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=output, stderr="")):
        outcome = run_s0_invocation(request, prompt_template_path=template, request_path=request_path, trace_dir=tmp_path / "traces")
    assert outcome.kind is S0OutcomeKind.VALID
    trace = json.loads(outcome.trace_path.read_text())
    assert trace["invocation_type"] == "tailoring_s0" and trace["raw_output"] == output


def test_s0_pipeline_classifies_timeout_without_fake_trace(tmp_path):
    request = s0_request_fixture.__wrapped__()
    template = tmp_path / "prompt.md"; template.write_text("{{S0_REQUEST_JSON}}")
    request_path = tmp_path / "s0_request.json"; request_path.write_text("{}")
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 1)):
        outcome = run_s0_invocation(request, prompt_template_path=template, request_path=request_path, trace_dir=tmp_path / "traces")
    assert outcome.kind is S0OutcomeKind.INVOCATION_FAILURE and outcome.trace_path is None


def test_s0_pipeline_traces_nonzero_stdout_and_classifies_parse_failure(tmp_path):
    request = s0_request_fixture.__wrapped__()
    template = tmp_path / "prompt.md"; template.write_text("{{S0_REQUEST_JSON}}")
    request_path = tmp_path / "s0_request.json"; request_path.write_text("{}")
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="partial", stderr="failed")):
        outcome = run_s0_invocation(request, prompt_template_path=template, request_path=request_path, trace_dir=tmp_path / "traces")
    assert outcome.kind is S0OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_path is not None and json.loads(outcome.trace_path.read_text())["raw_output"] == "partial"
