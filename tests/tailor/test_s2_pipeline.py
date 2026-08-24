import json
import subprocess
from unittest.mock import MagicMock, patch

from src.tailor.s2_pipeline import S2OutcomeKind, run_s2_invocation
from tests.tailor.test_m8p2_contracts import _fixtures
from src.tailor.s2 import build_s2_request


def test_s2_pipeline_classifies_validation_failure_and_traces(tmp_path):
    profile, catalog, s1, s0 = _fixtures()
    request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    variant = catalog.variants[0]
    output = {"base_variant": "backend", "projects": [{"project_id": p, "reason": "x", "s0_point_indexes": [0]} for p in variant.projects], "bullet_order": list(variant.bullet_order[:-1]), "coverage": [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}]}
    template = tmp_path / "prompt.md"; template.write_text("{{S2_REQUEST_JSON}}")
    request_path = tmp_path / "s2_request.json"; request_path.write_text("{}")
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=json.dumps(output), stderr="")):
        outcome = run_s2_invocation(request, prompt_template_path=template, request_path=request_path, trace_dir=tmp_path / "traces")
    assert outcome.kind is S2OutcomeKind.VALIDATION_FAILURE
    assert outcome.trace_path is not None


def test_s2_pipeline_classifies_empty_output_without_trace(tmp_path):
    _, catalog, s1, s0 = _fixtures()
    request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    template = tmp_path / "prompt.md"; template.write_text("{{S2_REQUEST_JSON}}")
    request_path = tmp_path / "s2_request.json"; request_path.write_text("{}")
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout="", stderr="")):
        outcome = run_s2_invocation(request, prompt_template_path=template, request_path=request_path, trace_dir=tmp_path / "traces")
    assert outcome.kind is S2OutcomeKind.INVOCATION_FAILURE and outcome.trace_path is None
