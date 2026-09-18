"""Required tests 1, 2, 10, 14: plan schema validation, checksum validation,
credential redaction, and human-review response schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tailor2_eval.plan import PlanValidationError, load_plan, validate_plan_file
from src.tailor2_eval.redact import redact_mapping, redact_text
from src.tailor2_eval.schemas import EvalSchemaError, human_review_from_dict, validate_human_review_dict

from .conftest import INVALID_PLAN_MISSING_FIELD_PATH, INVALID_PLAN_WITH_CREDENTIAL_PATH, VALID_PLAN_PATH


def test_valid_plan_loads_and_validates() -> None:
    plan = validate_plan_file(VALID_PLAN_PATH)
    assert plan.plan_id == "eval-plan-001"
    assert plan.target_ids == ("zoom_4766", "doordash_4608")


def test_invalid_plan_missing_field_rejected() -> None:
    with pytest.raises(EvalSchemaError):
        load_plan(INVALID_PLAN_MISSING_FIELD_PATH)


def test_invalid_plan_with_credential_rejected() -> None:
    with pytest.raises(EvalSchemaError, match="credential"):
        load_plan(INVALID_PLAN_WITH_CREDENTIAL_PATH)


def test_plan_checksum_mismatch_rejected(tmp_path: Path) -> None:
    data = json.loads(VALID_PLAN_PATH.read_text(encoding="utf-8"))
    data["profile_checksum"] = "0" * 64
    tampered = tmp_path / "tampered_plan.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanValidationError, match="profile_checksum"):
        validate_plan_file(tampered)


def test_plan_jd_checksum_mismatch_rejected(tmp_path: Path) -> None:
    data = json.loads(VALID_PLAN_PATH.read_text(encoding="utf-8"))
    data["target_jd_checksums"]["zoom_4766"] = "1" * 64
    tampered = tmp_path / "tampered_jd_plan.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanValidationError, match="target_jd_checksums"):
        validate_plan_file(tampered)


def test_plan_unknown_target_rejected(tmp_path: Path) -> None:
    data = json.loads(VALID_PLAN_PATH.read_text(encoding="utf-8"))
    data["target_ids"].append("nonexistent_9999")
    data["target_jd_checksums"]["nonexistent_9999"] = "2" * 64
    tampered = tmp_path / "unknown_target_plan.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PlanValidationError, match="unknown target_id"):
        validate_plan_file(tampered)


def test_redact_text_masks_api_key_shapes() -> None:
    assert "sk-" not in redact_text("here is my key sk-abcdefghijklmnopqrstuvwxyz")
    assert redact_text("nothing secret here") == "nothing secret here"


def test_redact_mapping_masks_credential_named_fields() -> None:
    redacted = redact_mapping({"api_key": "sk-real-secret-value-000000", "company": "Zoom"})
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["company"] == "Zoom"


def test_human_review_schema_valid(human_review_factory) -> None:
    review = human_review_factory("ab_preference_new_pipeline")
    assert review.overall_preference == "A"
    assert 0.0 <= review.reviewer_confidence <= 1.0


def test_human_review_schema_rejects_bad_preference(scenarios) -> None:
    bad = dict(scenarios["human_reviews"]["ab_tie"])
    bad["overall_preference"] = "MAYBE"
    with pytest.raises(EvalSchemaError):
        validate_human_review_dict(bad)


def test_human_review_schema_rejects_bad_confidence(scenarios) -> None:
    bad = dict(scenarios["human_reviews"]["ab_tie"])
    bad["reviewer_confidence"] = 1.5
    with pytest.raises(EvalSchemaError):
        validate_human_review_dict(bad)
