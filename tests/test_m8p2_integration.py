import json
import subprocess
from unittest.mock import MagicMock, patch

from scripts import tailor_s0_s2
from src.tailor.profile_views import parse_selection
from src.tailor.s0 import parse_s0_request
from tests.test_tailor_s0_s2_cli import _prepared


def test_offline_chain_uses_two_calls_and_publishes_valid_s2(tmp_path):
    database, prepared = _prepared(tmp_path)
    s0_request = parse_s0_request(json.loads((prepared / "s0_request.json").read_text()))
    s0_output = json.dumps({"context_mode": "jd_only", "points": [
        {"sentence": "Lead with backend delivery.", "profile_ids": [s0_request.positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
        {"sentence": "Support with production experience.", "profile_ids": [s0_request.positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
    ]})
    catalog = parse_selection(json.loads((prepared / "s2_catalog.json").read_text()))
    variant = catalog.variants[0]
    s2_output = json.dumps({"base_variant": "backend", "projects": [{"project_id": p, "reason": "selected", "s0_point_indexes": [0]} for p in variant.projects], "bullet_order": list(variant.bullet_order), "coverage": [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}]})
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        output = s0_output if len(calls) == 1 else s2_output
        return MagicMock(returncode=0, stdout=output, stderr="")
    with patch.object(subprocess, "run", side_effect=fake_run):
        assert tailor_s0_s2.main(["invoke-s0", "--request", str(prepared / "s0_request.json"), "--output", str(prepared), "--trace-dir", str(tmp_path / "traces")]) == 0
        assert tailor_s0_s2.main(["prepare-s2", "--s1-request", str(tmp_path / "s1" / "s1_request.json"), "--s1", str(tmp_path / "s1" / "s1.json"), "--s0", str(prepared / "s0.json"), "--s0-request", str(prepared / "s0_request.json"), "--catalog", str(prepared / "s2_catalog.json"), "--db", str(database), "--profile", "config/master_profile.yaml", "--output", str(prepared)]) == 0
        assert tailor_s0_s2.main(["invoke-s2", "--request", str(prepared / "s2_request.json"), "--output", str(prepared), "--trace-dir", str(tmp_path / "traces")]) == 0
    assert len(calls) == 2
    assert (prepared / "s2.json").exists()
    traces = sorted((tmp_path / "traces").rglob("*.json"))
    assert {json.loads(path.read_text())["invocation_type"] for path in traces} == {"tailoring_s0", "tailoring_s2"}
    for path in traces:
        prompt = json.loads(path.read_text())["inputs"][0]["content"]
        assert "phrasings" not in prompt and "evidence" not in prompt and "jd_text" not in prompt
