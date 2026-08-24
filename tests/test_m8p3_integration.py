import json
from pathlib import Path

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.s2 import parse_s2_response
from src.tailor.s3 import build_s3_request, parse_s3_request, s3_request_to_dict
from tests.tailor.test_s2 import _request, _valid


def test_m8p3_real_profile_alignment_round_trip_without_model_or_db():
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, alignment)
    assert parse_s3_request(s3_request_to_dict(request)) == request
    assert tuple(item.bullet_id for item in alignment.bullets) == s2_response.bullet_order


def test_m8p3_cli_dry_run_creates_no_bundle_or_trace(tmp_path, monkeypatch):
    from scripts.tailor_s3 import cmd_invoke
    from src.tailor.s3 import s3_request_to_dict
    from tests.tailor.test_s3 import _request_fixture

    request = _request_fixture()
    request_path = tmp_path / "s3_request.json"
    request_path.write_text(json.dumps(s3_request_to_dict(request)), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("{{S3_REQUEST_JSON}}", encoding="utf-8")
    banned = tmp_path / "banned.txt"
    banned.write_text("# no terms\n", encoding="utf-8")
    output = tmp_path / "out"
    args = type("Args", (), {"request": str(request_path), "banned_words": str(banned), "output": str(output), "prompt_template": str(prompt), "trace_dir": str(tmp_path / "traces"), "timeout": 1, "dry_run": True})()
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    assert cmd_invoke(args) == 0
    assert not output.exists()
    assert not (tmp_path / "traces").exists()
