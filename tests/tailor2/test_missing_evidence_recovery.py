from __future__ import annotations

import json
from collections import deque

from src.tailor2.lane import run_tailor2_lane
from src.tailor2.models import parse_draft_response
from tests.tailor2.test_lane import _make_passing_audit_json, _make_valid_draft_json


class ScriptedInvoker:
    provider = "fake"
    model = "fake-model"

    def __init__(self, responses: dict[str, list[str] | str]) -> None:
        self.fake_responses = responses
        self.calls: list[str] = []
        self._responses = {
            key: deque(value if isinstance(value, list) else [value])
            for key, value in responses.items()
        }

    def invoke(self, prompt: str, invocation_type: str, input_paths=None) -> str:
        del prompt, input_paths
        self.calls.append(invocation_type)
        values = self._responses[invocation_type]
        return values.popleft() if len(values) > 1 else values[0]


def _selection_response() -> str:
    return json.dumps(
        {
            "requirements": [
                {"id": "req_logging", "term": "logging", "quote": "data pipelines", "kind": "must_have"}
            ],
            "matches": [
                {
                    "requirement_id": "req_logging",
                    "evidence_ids": ["am_b03_audit_trail"],
                    "classification": "direct",
                    "confidence": 1,
                    "strength": 1,
                    "explanation": "Direct audit evidence.",
                }
            ],
            "evidence_selection": [
                {
                    "evidence_id": "am_b03_audit_trail",
                    "selected": True,
                    "score": 1,
                    "requirement_ids": ["req_logging"],
                    "estimated_line_cost": 2,
                    "rationale": "Direct evidence.",
                }
            ],
            "candidates": [],
        }
    )


def _draft_without_am_b03() -> str:
    response = json.loads(_make_valid_draft_json())
    response["bullets"] = [
        bullet for bullet in response["bullets"] if bullet["evidence_ids"] != ["am_b03_audit_trail"]
    ]
    response["selected_evidence_ids"].append("am_b03_audit_trail")
    response["amdocs_omission_ledger"] = []
    return json.dumps(response)


def test_selected_evidence_omission_is_targeted_not_fatal(tmp_path, sample_jd_text):
    valid_jd_file = tmp_path / "jd.txt"
    valid_jd_file.write_text(sample_jd_text, encoding="utf-8")
    draft = _draft_without_am_b03()
    audited_bullet_ids = [f"b{i:02d}" for i in range(1, 16) if i != 4]
    invoker = ScriptedInvoker(
        {
            "selection": _selection_response(),
            "draft": [draft, draft],
            "audit": _make_passing_audit_json(audited_bullet_ids),
            "missing_evidence": json.dumps(
                {
                    "recovered_bullets": [
                        {
                            "evidence_id": "am_b03_audit_trail",
                            "bullet_id": "recovered_am_b03_audit_trail",
                            "supported_requirement_ids": ["req_logging"],
                            "text": "Implemented asynchronous audit logging capturing system state transitions.",
                        }
                    ]
                }
            ),
        }
    )

    result = run_tailor2_lane(
        valid_jd_file,
        "Acme Corp",
        "Software Engineer",
        "backend",
        invoker,
        tmp_path / "out",
    )

    assert result.status != "REJECTED_FATAL"
    assert "missing_evidence" not in invoker.calls
    assert invoker.calls.count("selection") == 1
    assert invoker.calls.count("draft") == 1


def test_second_targeted_omission_preserves_safe_partial_for_human_review(tmp_path, sample_jd_text):
    valid_jd_file = tmp_path / "jd.txt"
    valid_jd_file.write_text(sample_jd_text, encoding="utf-8")
    draft = _draft_without_am_b03()
    bullet_ids = [f"b{i:02d}" for i in range(1, 16) if i != 4]
    invoker = ScriptedInvoker(
        {
            "missing_evidence": [json.dumps({"recovered_bullets": []}), json.dumps({"recovered_bullets": []})],
            "audit": _make_passing_audit_json(bullet_ids),
        }
    )

    result = run_tailor2_lane(
        valid_jd_file,
        "Acme Corp",
        "Software Engineer",
        "backend",
        invoker,
        tmp_path / "out",
        selection_enabled=False,
        initial_draft=parse_draft_response(draft),
        resume_metadata={"reused_stages": ["selection", "draft", "draft_retry"]},
    )

    assert result.status != "REJECTED_FATAL"
    assert invoker.calls == ["audit"]
    assert (tmp_path / "out" / "resume.pdf").exists()
    manifest = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["safe_candidate_constructed"] is True
    draft_json = json.loads((tmp_path / "out" / "draft.json").read_text(encoding="utf-8"))
    assert any(item["evidence_id"] == "am_b03_audit_trail" for item in draft_json["amdocs_omission_ledger"])


def test_fabricated_metric_does_not_trigger_targeted_recovery(tmp_path, sample_jd_text):
    valid_jd_file = tmp_path / "jd.txt"
    valid_jd_file.write_text(sample_jd_text, encoding="utf-8")
    draft = _draft_without_am_b03()
    invoker = ScriptedInvoker(
        {
            "missing_evidence": json.dumps(
                {
                    "recovered_bullets": [
                        {
                            "evidence_id": "am_b03_audit_trail",
                            "bullet_id": "recovered_am_b03_audit_trail",
                            "supported_requirement_ids": ["req_logging"],
                            "text": "Improved audit logging by 999% across production systems.",
                        }
                    ]
                }
            )
        }
    )

    result = run_tailor2_lane(
        valid_jd_file,
        "Acme Corp",
        "Software Engineer",
        "backend",
        invoker,
        tmp_path / "out",
        selection_enabled=False,
        initial_draft=parse_draft_response(draft),
    )

    assert result.status != "REJECTED_FATAL"
    assert invoker.calls == ["audit"]
    assert (tmp_path / "out" / "resume.pdf").exists()


def test_resume_reuses_completed_draft_without_selection_or_draft_calls(tmp_path, sample_jd_text):
    valid_jd_file = tmp_path / "jd.txt"
    valid_jd_file.write_text(sample_jd_text, encoding="utf-8")
    draft = _draft_without_am_b03()
    audited_bullet_ids = [f"b{i:02d}" for i in range(1, 16) if i != 4]
    invoker = ScriptedInvoker(
        {
            "missing_evidence": json.dumps(
                {
                    "recovered_bullets": [
                        {
                            "evidence_id": "am_b03_audit_trail",
                            "bullet_id": "recovered_am_b03_audit_trail",
                            "supported_requirement_ids": [],
                            "text": "Implemented asynchronous audit logging capturing system state transitions.",
                        }
                    ]
                }
            ),
            "audit": _make_passing_audit_json(audited_bullet_ids),
        }
    )

    result = run_tailor2_lane(
        valid_jd_file,
        "Acme Corp",
        "Software Engineer",
        "backend",
        invoker,
        tmp_path / "out",
        selection_enabled=False,
        initial_draft=parse_draft_response(draft),
        resume_metadata={"reused_stages": ["selection", "draft", "draft_retry"]},
    )

    assert result.status != "REJECTED_FATAL"
    assert "selection" not in invoker.calls
    assert "draft" not in invoker.calls
    assert invoker.calls == ["audit"]
