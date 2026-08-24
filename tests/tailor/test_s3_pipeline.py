import json
from dataclasses import replace

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.invoke import InvocationError, InvocationResult
from src.tailor.s2 import parse_s2_response
from src.tailor.s3 import build_s3_request
from src.tailor.s3_pipeline import S3Bundle, S3OutcomeKind, run_s3_invocation
from tests.tailor.test_s2 import _request, _valid


def test_s3_pipeline_contract_exists():
    assert S3Bundle is not None
    assert S3OutcomeKind.VALID.value == "valid"
    assert callable(run_s3_invocation)


def _fixture(tmp_path):
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, replace(alignment, do_not_claim=()))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Return JSON.\n{{S3_REQUEST_JSON}}", encoding="utf-8")
    request_path = tmp_path / "s3_request.json"
    request_path.write_text("{}", encoding="utf-8")
    return request, prompt, request_path


def test_s3_prompt_requires_one_marker(tmp_path):
    from src.tailor.s3 import build_s3_prompt
    request, _, _ = _fixture(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        build_s3_prompt("no marker", request)
    assert "Example" in build_s3_prompt("{{S3_REQUEST_JSON}}", request)


def test_s3_pipeline_valid_traces_once(monkeypatch, tmp_path):
    request, prompt, request_path = _fixture(tmp_path)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *args, **kwargs: InvocationResult('{"bullet_edits": [], "skill_additions": []}', "stderr: <empty>", "fake"))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")
    assert outcome.kind is S3OutcomeKind.VALID
    assert outcome.bundle is not None
    assert outcome.trace_path is not None
    assert json.loads(outcome.trace_path.read_text())["model"] == "fake"


def test_s3_pipeline_parse_failure_keeps_trace(monkeypatch, tmp_path):
    request, prompt, request_path = _fixture(tmp_path)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *args, **kwargs: InvocationResult("not json", "stderr: <empty>", "fake"))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")
    assert outcome.kind is S3OutcomeKind.PARSE_FAILURE
    assert outcome.bundle is None and outcome.trace_path is not None


def test_s3_pipeline_semantic_and_g1_failures_have_no_bundle(monkeypatch, tmp_path):
    request, prompt, request_path = _fixture(tmp_path)
    semantic = '{"bullet_edits": [{"bullet_id": "unknown", "after": "x", "motivating_terms": ["Python"], "rule": "terminology_mirroring"}], "skill_additions": []}'
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *args, **kwargs: InvocationResult(semantic, "stderr: <empty>", "fake"))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")
    assert outcome.kind is S3OutcomeKind.SEMANTIC_FAILURE
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *args, **kwargs: InvocationResult('{"bullet_edits": [], "skill_additions": []}', "stderr: <empty>", "fake"))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=("Python",), trace_dir=tmp_path / "traces2")
    assert outcome.kind is S3OutcomeKind.G1_FAILURE
    assert outcome.bundle is None and outcome.g1_report is not None


def test_s3_pipeline_invocation_failure_traces_partial_stdout(monkeypatch, tmp_path):
    request, prompt, request_path = _fixture(tmp_path)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *args, **kwargs: (_ for _ in ()).throw(InvocationError("failed", raw_stdout="partial", model="fake")))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")
    assert outcome.kind is S3OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_path is not None


def test_s3_pipeline_unexpected_exception_during_parse_propagates(monkeypatch, tmp_path):
    """Defect 4: only S3ParseError/S3SemanticError may become modeled outcomes;
    an unrelated programmer error (e.g. a bug in parse_s3_response) must propagate."""
    request, prompt, request_path = _fixture(tmp_path)
    monkeypatch.setattr(
        "src.tailor.s3_pipeline.invoke_text_model",
        lambda *args, **kwargs: InvocationResult('{"bullet_edits": [], "skill_additions": []}', "stderr: <empty>", "fake"),
    )
    monkeypatch.setattr(
        "src.tailor.s3_pipeline.parse_s3_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom: unrelated bug")),
    )
    import pytest

    with pytest.raises(RuntimeError, match="boom"):
        run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")


def test_s3_bundle_to_dict_produces_json_serializable_primitives_for_nontrivial_bundle(monkeypatch, tmp_path):
    """Defect 1 regression: a valid bundle with an edited bullet (with emphasis),
    a skill addition, and a non-empty G1 report must serialize with json.dumps
    without any dataclass object surviving in the dict."""
    import json as _json
    from dataclasses import replace as _replace

    from src.tailor.s3 import build_s3_request
    from src.tailor.s3_pipeline import s3_bundle_to_dict
    from tests.tailor.test_s2 import _request, _valid as _valid_s2
    from src.profile import load_profile

    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(_json.dumps(_valid_s2(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, _replace(alignment, do_not_claim=()))

    after = (
        "Built the **anti-corruption layer** between a commercial bank's core systems and "
        "four external providers as **four asynchronous Python microservices "
        "(FastAPI, SQLAlchemy 2.0, PostgreSQL)**."
    )
    edit_raw = _json.dumps({
        "bullet_edits": [{"bullet_id": "int_b1", "after": after, "motivating_terms": ["Python"], "rule": "terminology_mirroring"}],
        "skill_additions": [],
    })

    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{S3_REQUEST_JSON}}", encoding="utf-8")
    request_path = tmp_path / "s3_request.json"
    request_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *a, **k: InvocationResult(edit_raw, "stderr: <empty>", "fake"))
    outcome = run_s3_invocation(request, prompt_template_path=prompt, request_path=request_path, banned_terms=(), trace_dir=tmp_path / "traces")
    assert outcome.kind is S3OutcomeKind.VALID
    assert outcome.bundle is not None
    assert outcome.bundle.change_log

    payload = s3_bundle_to_dict(outcome.bundle)
    serialized = _json.dumps(payload)  # must not raise TypeError
    reparsed = _json.loads(serialized)
    assert reparsed["draft"]["bullets"][0]["bullet_id"] == "int_b1"
    assert isinstance(reparsed["draft"]["bullets"][0]["emphasis"], list)
    assert isinstance(reparsed["change_log"], list) and reparsed["change_log"]
    assert isinstance(reparsed["edit_budget"]["ratio"], float)
    assert isinstance(reparsed["g1"]["violations"], list)
