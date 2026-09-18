"""Automated verification suite for Tailor2 evaluation assets.

Verifies:
1. All plan files load, parse, and pass validate_plan_file.
2. Chechsums match the actual files on disk (master_profile.yaml, target JDs).
3. Zero credentials, secrets, or API keys in plans, templates, or rubrics.
4. Zero PII in checked-in evaluation assets.
5. Baseline reference registry covers all 10 targets across all 3 baselines.
6. openai_4949 manual reference is available and verified; other baselines marked unavailable.
7. Human review response template conforms to HumanReviewResponse schema.
8. Rubric dictionary defines all 14 RUBRIC_DIMENSIONS.
9. Instructions maintain blind neutrality and explain TIE vs NEITHER.
10. Dry-run execution runs offline with zero calls and zero cost.
11. Artifact and file paths are strictly portable relative paths.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from src.tailor2_eval.checksums import sha256_file
from src.tailor2_eval.orchestrator import run_evaluation_plan
from src.tailor2_eval.plan import validate_plan_file
from src.tailor2_eval.redact import find_credential_like_keys
from src.tailor2_eval.schemas import (
    RUBRIC_DIMENSIONS,
    human_review_from_dict,
    validate_human_review_dict,
)
from src.tailor2_eval.targets import load_top10_targets

PLANS_DIR = Path("evaluation/tailor2/plans")
REGISTRY_DIR = Path("evaluation/tailor2/registry")
HUMAN_REVIEW_DIR = Path("evaluation/tailor2/human_review")

OPENAI_SMOKE_RECORDED_PATH = PLANS_DIR / "openai_smoke_recorded.json"
OPENAI_SMOKE_LIVE_TEMPLATE_PATH = PLANS_DIR / "openai_smoke_live.template.json"
TOP10_RECORDED_PATH = PLANS_DIR / "top10_recorded.json"
TOP10_LIVE_TEMPLATE_PATH = PLANS_DIR / "top10_live.template.json"
REFERENCE_REGISTRY_PATH = REGISTRY_DIR / "reference_registry.json"
RUBRIC_DICTIONARY_PATH = HUMAN_REVIEW_DIR / "rubric_dictionary.json"
RESPONSE_TEMPLATE_PATH = HUMAN_REVIEW_DIR / "response_template.json"
INSTRUCTIONS_PATH = HUMAN_REVIEW_DIR / "instructions.md"
FACTUAL_ERROR_GUIDANCE_PATH = HUMAN_REVIEW_DIR / "factual_error_guidance.md"

ALL_PLAN_PATHS = [
    OPENAI_SMOKE_RECORDED_PATH,
    OPENAI_SMOKE_LIVE_TEMPLATE_PATH,
    TOP10_RECORDED_PATH,
    TOP10_LIVE_TEMPLATE_PATH,
]


def test_openai_smoke_recorded_plan_validates() -> None:
    plan = validate_plan_file(OPENAI_SMOKE_RECORDED_PATH)
    assert plan.plan_id == "openai_smoke_recorded"
    assert plan.target_ids == ("openai_4949",)
    assert plan.drafter.provider == "mock"
    assert plan.resume_policy == "skip_completed"
    assert plan.blind_comparison.enabled is True
    assert len(plan.blind_comparison.dimensions) == 14


def test_openai_smoke_live_template_validates() -> None:
    plan = validate_plan_file(OPENAI_SMOKE_LIVE_TEMPLATE_PATH)
    assert plan.plan_id == "openai_smoke_live"
    assert plan.target_ids == ("openai_4949",)
    assert plan.drafter.provider == "openai"
    assert plan.drafter.model == "gpt-4o"
    assert plan.resume_policy == "skip_completed"
    assert plan.max_cost_usd > 0
    assert plan.max_calls > 0


def test_top10_recorded_plan_validates() -> None:
    plan = validate_plan_file(TOP10_RECORDED_PATH)
    assert plan.plan_id == "top10_recorded"
    targets = load_top10_targets()
    expected_ids = tuple(t.target_id for t in targets)
    assert plan.target_ids == expected_ids
    assert len(plan.target_ids) == 10
    assert plan.drafter.provider == "mock"
    assert plan.resume_policy == "skip_completed"
    assert plan.blind_comparison.enabled is True
    assert len(plan.blind_comparison.dimensions) == 14


def test_top10_live_template_validates() -> None:
    plan = validate_plan_file(TOP10_LIVE_TEMPLATE_PATH)
    assert plan.plan_id == "top10_live"
    targets = load_top10_targets()
    expected_ids = tuple(t.target_id for t in targets)
    assert plan.target_ids == expected_ids
    assert len(plan.target_ids) == 10
    assert plan.drafter.provider == "openai"
    assert plan.drafter.model == "gpt-4o"
    assert plan.resume_policy == "skip_completed"


def test_all_plans_profile_checksum_fresh() -> None:
    profile_path = Path("config/master_profile.yaml")
    assert profile_path.exists(), "master profile yaml must exist"
    actual_profile_hash = sha256_file(profile_path)

    for plan_path in ALL_PLAN_PATHS:
        plan = validate_plan_file(plan_path)
        assert plan.profile_checksum == actual_profile_hash, (
            f"Plan {plan_path.name} profile_checksum does not match current profile file"
        )


def test_all_plans_target_jd_checksums_fresh() -> None:
    targets_by_id = {t.target_id: t for t in load_top10_targets()}

    for plan_path in ALL_PLAN_PATHS:
        plan = validate_plan_file(plan_path)
        for target_id in plan.target_ids:
            target = targets_by_id[target_id]
            actual_jd_hash = sha256_file(target.jd_path)
            assert plan.target_jd_checksums[target_id] == actual_jd_hash, (
                f"Plan {plan_path.name} target_jd_checksums[{target_id}] is stale"
            )


def test_plans_and_templates_contain_no_credentials_or_secrets() -> None:
    for json_file in Path("evaluation/tailor2").glob("**/*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            bad_keys = find_credential_like_keys(data)
            assert not bad_keys, f"Found credential-like key(s) in {json_file}: {bad_keys}"

        content = json_file.read_text(encoding="utf-8")
        assert not re.search(r"sk-[A-Za-z0-9]{20,}", content), f"Possible API key found in {json_file}"
        assert not re.search(r"AIza[A-Za-z0-9_\-]{20,}", content), f"Possible Google API key found in {json_file}"


def test_plans_and_templates_contain_no_pii() -> None:
    for json_file in Path("evaluation/tailor2").glob("**/*.json"):
        content = json_file.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", content), f"SSN-like pattern in {json_file}"
        assert not re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", content), f"Phone-like pattern in {json_file}"


def test_reference_registry_schema_and_integrity() -> None:
    assert REFERENCE_REGISTRY_PATH.exists()
    registry = json.loads(REFERENCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert registry["schema_version"] == "1.0"
    baselines = registry["baselines"]
    for required_baseline in ("manual_reference", "tailor1_legacy", "future_render_fill"):
        assert required_baseline in baselines, f"Missing baseline {required_baseline} in registry"

    top10_targets = load_top10_targets()
    expected_target_ids = {t.target_id for t in top10_targets}

    for baseline_name, baseline_data in baselines.items():
        targets_dict = baseline_data["targets"]
        assert set(targets_dict.keys()) == expected_target_ids, (
            f"Baseline {baseline_name} does not cover all 10 targets"
        )

    # openai_4949 under manual_reference is available
    manual_openai = baselines["manual_reference"]["targets"]["openai_4949"]
    assert manual_openai["is_available"] is True
    assert manual_openai["git_ref"] == "origin/resume/openai-4949-manual"
    assert manual_openai["commit_prefix"] == "a4dd50b"
    assert "tex_path" in manual_openai["artifacts"]

    # all other targets under manual_reference are unavailable
    for target_id in expected_target_ids - {"openai_4949"}:
        assert baselines["manual_reference"]["targets"][target_id]["is_available"] is False

    # all targets under tailor1_legacy and future_render_fill are currently unavailable
    for target_id in expected_target_ids:
        assert baselines["tailor1_legacy"]["targets"][target_id]["is_available"] is False
        assert baselines["future_render_fill"]["targets"][target_id]["is_available"] is False


def test_human_review_response_template_validates() -> None:
    assert RESPONSE_TEMPLATE_PATH.exists()
    raw = json.loads(RESPONSE_TEMPLATE_PATH.read_text(encoding="utf-8"))
    validate_human_review_dict(raw)
    response = human_review_from_dict(raw)
    assert response.schema_version == "1.0"
    assert response.comparison_id.startswith("cmp-")
    assert response.overall_preference in ("A", "B", "TIE", "NEITHER")
    assert 0.0 <= response.reviewer_confidence <= 1.0
    assert set(response.dimension_preferences.keys()) == set(RUBRIC_DIMENSIONS)
    for dim, pref in response.dimension_preferences.items():
        assert pref in ("A", "B", "TIE", "NEITHER"), f"Invalid preference {pref} for dimension {dim}"


def test_human_review_rubric_dictionary_covers_all_14_dimensions() -> None:
    assert RUBRIC_DICTIONARY_PATH.exists()
    raw = json.loads(RUBRIC_DICTIONARY_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.0"
    dimensions = raw["dimensions"]
    assert set(dimensions.keys()) == set(RUBRIC_DIMENSIONS)

    for dim_id, dim_data in dimensions.items():
        assert "name" in dim_data
        assert "priority" in dim_data
        assert "description" in dim_data
        assert "evaluation_focus" in dim_data
        assert isinstance(dim_data.get("positive_indicators"), list) and len(dim_data["positive_indicators"]) > 0
        assert isinstance(dim_data.get("negative_indicators"), list) and len(dim_data["negative_indicators"]) > 0


def test_human_review_instructions_blind_neutrality() -> None:
    assert INSTRUCTIONS_PATH.exists()
    content = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    assert "Candidate A" in content
    assert "Candidate B" in content
    assert "TIE" in content
    assert "NEITHER" in content

    # Should not mention specific model names to preserve blind neutrality
    lowered = content.lower()
    for forbidden in ("claude sonnet", "gpt-4", "gemini-pro", "chatgpt"):
        assert forbidden not in lowered, f"Instruction contains forbidden model name: {forbidden}"


def test_dry_run_execution_with_recorded_plans(tmp_path: Path) -> None:
    for plan_path in (OPENAI_SMOKE_RECORDED_PATH, TOP10_RECORDED_PATH):
        plan = validate_plan_file(plan_path)
        # Use isolated artifact directory under tmp_path
        tmp_plan = replace(plan, artifact_root=str(tmp_path / plan.plan_id))
        summary = run_evaluation_plan(tmp_plan, mode="dry_run")
        assert summary.mode == "dry_run"
        assert len(summary.results) == len(plan.target_ids)
        assert summary.provider_calls_made == 0
        assert summary.total_cost_usd == 0.0
        assert not summary.stopped_on_budget
        for result in summary.results:
            assert result.status == "DRY_RUN_OK"
            assert result.provider_call_count == 0
            assert result.estimated_cost_usd == 0.0


def test_artifact_paths_portable_and_relative() -> None:
    for json_file in Path("evaluation/tailor2").glob("**/*.json"):
        content = json_file.read_text(encoding="utf-8")
        assert "/Users/" not in content, f"Hardcoded absolute path found in {json_file}"
        assert "/home/" not in content, f"Hardcoded absolute path found in {json_file}"
        assert "C:\\" not in content, f"Hardcoded Windows path found in {json_file}"
