"""Executable verification and acceptance test scaffolding for Tailor2
render-measure-expand-compress optimizer evaluation corpus.

Validates:
1. Schema conformance of all 48 evaluation fixtures in cases.json.
2. Unique case IDs and valid categories (measurement, expansion, compression, optimization_behavior).
3. Target ID resolution across Top-10 targets.
4. Resolution of canonical evidence IDs or explicitly marked synthetic evidence.
5. Semantic geometry relationships and portable tolerance policies.
6. Preservation of protected facts and numerical metrics (~40%, ~70%, 862, AUROC 0.88).
7. Detection and rejection of invalid compression changes.
8. Exclusion of prohibited and unsupported content from expansion.
9. Rollback preservation of prior best-safe candidates.
10. Finite iteration budgets and cycle detection.
11. Multi-dimensional evaluation (fill ratio is never the sole criterion).
12. Zero PII and zero secrets across all fixtures.
13. Recorded iteration scenarios integrity across all 12 scenario files.
14. Integration acceptance scaffolding for pending production capabilities (strict xfails).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
import pytest

CASES_PATH = Path("tests/fixtures/tailor2/render_fill/cases.json")
SCENARIOS_DIR = Path("tests/fixtures/tailor2/render_fill/recorded_scenarios")
CATALOG_PATH = Path("tests/fixtures/tailor2/quality_regressions/canonical_evidence_catalog.json")
TARGETS_PATH = Path("shortlist/tailoring_targets/targets.json")

# Strict PII detection patterns
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_PATTERN = re.compile(r"(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})")
SECRET_PATTERN = re.compile(r"(sk-[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9_-]+|api[-_]?key)", re.IGNORECASE)

VALID_CATEGORIES = {
    "measurement",
    "expansion",
    "compression",
    "optimization_behavior",
}

VALID_LAYOUT_STATES = {
    "CLEAN_FIT",
    "MINOR_UNDERFILL",
    "MEANINGFUL_UNDERFILL",
    "SLIGHT_OVERFLOW",
    "SUBSTANTIAL_OVERFLOW",
    "TWO_PAGE_OVERFLOW",
    "BOUNDS_VIOLATION",
    "COLLISION_DETECTED",
    "LINE_WRAP_DEFECT",
    "FONT_SIZE_VIOLATION",
    "MARGIN_VIOLATION",
    "UNREADABLE_COMPRESSION",
    "RENDER_FAILURE",
}

VALID_RUNTIME_OUTCOMES = {
    "ACCEPTED",
    "ACCEPTED_WITH_WARNING",
    "OPTIMIZATION_EXPANDED",
    "OPTIMIZATION_COMPRESSED",
    "OPTIMIZATION_ROLLED_BACK",
    "NEEDS_HUMAN_REVIEW",
    "FATAL_RENDER_ERROR",
}


@pytest.fixture(scope="module")
def loaded_cases() -> list[dict[str, Any]]:
    assert CASES_PATH.exists(), f"Missing cases fixture: {CASES_PATH}"
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def canonical_catalog() -> dict[str, dict[str, Any]]:
    assert CATALOG_PATH.exists(), f"Missing canonical evidence catalog: {CATALOG_PATH}"
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data}


@pytest.fixture(scope="module")
def targets_data() -> list[dict[str, Any]]:
    assert TARGETS_PATH.exists(), f"Missing targets json: {TARGETS_PATH}"
    return json.loads(TARGETS_PATH.read_text(encoding="utf-8"))


# ==============================================================================
# Fixture Integrity Tests (Must Pass 100% Normally)
# ==============================================================================

def test_fixtures_count_and_categories(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that exactly 48 fixtures are present across all 4 categories."""
    assert len(loaded_cases) == 48, f"Expected 48 fixtures, got {len(loaded_cases)}"

    counts: dict[str, int] = {}
    for case in loaded_cases:
        cat = case["category"]
        counts[cat] = counts.get(cat, 0) + 1

    expected_counts = {
        "measurement": 14,
        "expansion": 11,
        "compression": 10,
        "optimization_behavior": 13,
    }

    for cat, expected in expected_counts.items():
        actual = counts.get(cat, 0)
        assert actual == expected, f"Category '{cat}': expected {expected}, got {actual}"


def test_every_fixture_conforms_to_schema(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that every fixture contains all required schema fields and valid enums."""
    required_fields = {
        "case_id",
        "category",
        "target_id",
        "input_candidate",
        "unused_evidence",
        "render_measurement",
        "protected_facts",
        "allowed_actions",
        "forbidden_actions",
        "expected_layout_state",
        "expected_runtime_outcome",
        "expected_decision_properties",
        "tolerance_policy",
        "notes",
    }

    case_ids = set()
    for case in loaded_cases:
        cid = case["case_id"]
        assert cid not in case_ids, f"Duplicate case_id: {cid}"
        case_ids.add(cid)

        missing = required_fields - set(case.keys())
        assert not missing, f"Case '{cid}' missing required fields: {missing}"

        assert case["category"] in VALID_CATEGORIES, f"Case '{cid}' invalid category: {case['category']}"
        assert case["expected_layout_state"] in VALID_LAYOUT_STATES, f"Case '{cid}' invalid layout state: {case['expected_layout_state']}"
        assert case["expected_runtime_outcome"] in VALID_RUNTIME_OUTCOMES, f"Case '{cid}' invalid outcome: {case['expected_runtime_outcome']}"

        assert isinstance(case["input_candidate"], dict), f"Case '{cid}': input_candidate must be dict"
        assert isinstance(case["unused_evidence"], list), f"Case '{cid}': unused_evidence must be list"
        assert isinstance(case["render_measurement"], dict), f"Case '{cid}': render_measurement must be dict"
        assert isinstance(case["protected_facts"], list), f"Case '{cid}': protected_facts must be list"
        assert isinstance(case["allowed_actions"], list), f"Case '{cid}': allowed_actions must be list"
        assert isinstance(case["forbidden_actions"], list), f"Case '{cid}': forbidden_actions must be list"
        assert isinstance(case["expected_decision_properties"], list), f"Case '{cid}': expected_decision_properties must be list"
        assert isinstance(case["tolerance_policy"], dict), f"Case '{cid}': tolerance_policy must be dict"


def test_case_ids_unique(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that all case IDs are globally unique."""
    ids = [c["case_id"] for c in loaded_cases]
    assert len(ids) == len(set(ids)), f"Duplicate case IDs found: {[x for x in ids if ids.count(x) > 1]}"


def test_cross_target_coverage_all_ten_represented(loaded_cases: list[dict[str, Any]], targets_data: list[dict[str, Any]]) -> None:
    """Verifies that all 10 target companies are represented and OpenAI is the deepest case."""
    target_counts: dict[str, int] = {}
    for case in loaded_cases:
        tid = case["target_id"]
        target_counts[tid] = target_counts.get(tid, 0) + 1

    expected_targets = {
        "openai_4949", "twitch_4182", "tiktok_4164", "roadrunner_5027",
        "doordash_4608", "c3ai_4894", "zoom_4766", "lexisnexis_4987",
        "commure_4839", "idme_3981"
    }

    actual_targets = set(target_counts.keys())
    assert actual_targets == expected_targets, f"Target coverage mismatch: missing {expected_targets - actual_targets}"
    assert target_counts["openai_4949"] >= 10, f"OpenAI cases ({target_counts['openai_4949']}) should be at least 10"


def test_referenced_target_ids_resolve(loaded_cases: list[dict[str, Any]], targets_data: list[dict[str, Any]]) -> None:
    """Verifies that every target_id resolves to an entry in targets.json."""
    valid_target_ids = set()
    for t in targets_data:
        company_slug = t["company"].lower().split()[0].replace(".", "").replace("-", "")
        slug_map = {
            "c3ai": "c3ai", "doordash": "doordash", "idme": "idme", "tiktok": "tiktok",
            "roadrunner": "roadrunner", "lexisnexis": "lexisnexis", "openai": "openai",
            "commure": "commure", "twitch": "twitch", "zoom": "zoom"
        }
        for k, v in slug_map.items():
            if k in company_slug:
                company_slug = v
                break
        valid_target_ids.add(f"{company_slug}_{t['job_id']}")

    for case in loaded_cases:
        tid = case["target_id"]
        assert tid in valid_target_ids, f"Case '{case['case_id']}' references unresolved target_id '{tid}'"


def test_referenced_evidence_ids_resolve_or_explicitly_synthetic(
    loaded_cases: list[dict[str, Any]],
    canonical_catalog: dict[str, dict[str, Any]]
) -> None:
    """Verifies that all unused_evidence items resolve to canonical catalog or are explicitly prefixed synth_."""
    for case in loaded_cases:
        cid = case["case_id"]
        for ev in case.get("unused_evidence", []):
            eid = ev["evidence_id"]
            if eid.startswith("synth_"):
                # Synthetic test items must explicitly flag support/prohibition status
                assert "is_supported" in ev and "is_prohibited" in ev
            else:
                assert eid in canonical_catalog, f"Case '{cid}': unused evidence '{eid}' not in canonical catalog"


def test_geometry_relationships_internally_consistent(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that measurement geometry properties are internally coherent."""
    for case in loaded_cases:
        cid = case["case_id"]
        rm = case["render_measurement"]
        # If page_count > 1, has_overflow must be True or vertical_fill_ratio > 1.0
        if rm["page_count"] > 1:
            assert rm["has_overflow"] or rm["vertical_fill_ratio"] > 1.0, (
                f"Case '{cid}': 2-page render must have overflow flagged"
            )
        # If collision flagged, collision_type must be specified
        if rm["has_collision"]:
            assert rm["collision_type"] in ("section_collision", "tech_date_collision", "page_boundary"), (
                f"Case '{cid}': collision flagged with invalid collision_type: {rm['collision_type']}"
            )
        # Fill ratio must be non-negative
        assert rm["vertical_fill_ratio"] >= 0.0, f"Case '{cid}': negative vertical_fill_ratio"


def test_tolerances_are_portable(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that tolerance policies avoid hardcoded pixel thresholds and declare portable margins."""
    for case in loaded_cases:
        cid = case["case_id"]
        tp = case["tolerance_policy"]
        assert tp["fill_ratio_tolerance"] > 0.0, f"Case '{cid}': fill_ratio_tolerance must be positive"
        assert tp["min_font_size_pt"] >= 9.0, f"Case '{cid}': min_font_size_pt below reasonable policy"
        assert tp["min_margin_in"] >= 0.40, f"Case '{cid}': min_margin_in below reasonable policy"
        assert 0.0 < tp["max_compression_tightness"] <= 1.0, f"Case '{cid}': invalid max_compression_tightness"


def test_protected_facts_survive_valid_transformations(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that cases with numerical metrics or canonical titles declare metric guards."""
    cases_with_metrics = [
        c for c in loaded_cases
        if any(char.isdigit() or "~" in fact for fact in c.get("protected_facts", []) for char in fact)
    ]
    assert len(cases_with_metrics) >= 10, f"Expected >= 10 cases with metrics, got {len(cases_with_metrics)}"

    for case in cases_with_metrics:
        cid = case["case_id"]
        # Must prohibit metric altering/deletion
        guards = [fa for fa in case["forbidden_actions"] if any(w in fa.lower() for w in ("metric", "alter", "delete", "round"))]
        props = [dp for dp in case["expected_decision_properties"] if any(w in dp.lower() for w in ("metric", "preserve", "factual"))]
        assert guards or props or "metric" in case["notes"].lower(), (
            f"Case '{cid}' has protected metrics but lacks metric protection rule"
        )


def test_invalid_compression_changes_detectable(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that cases with invalid compression proposals route to rollback or review."""
    invalid_compression_cases = [
        c for c in loaded_cases
        if c["case_id"] in (
            "rf_29_compression_deleting_achievement_rejected",
            "rf_31_spacing_adjustment_below_minimum_rejected",
            "rf_33_hardcoded_bullet_deletion_prohibited",
            "rf_34_compression_worsens_layout_rolled_back",
        )
    ]
    for case in invalid_compression_cases:
        cid = case["case_id"]
        assert case["expected_runtime_outcome"] in ("OPTIMIZATION_ROLLED_BACK", "NEEDS_HUMAN_REVIEW"), (
            f"Invalid compression case '{cid}' should roll back or route to review: got {case['expected_runtime_outcome']}"
        )


def test_prohibited_content_never_enters_expansion(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that prohibited or unsupported evidence cannot be used to fill vertical space."""
    prohibited_case = next(c for c in loaded_cases if c["case_id"] == "rf_18_prohibited_evidence_blocked")
    assert any(ev["is_prohibited"] for ev in prohibited_case["unused_evidence"])
    assert "add_prohibited_evidence_to_fill_space" in prohibited_case["forbidden_actions"]

    unsupported_case = next(c for c in loaded_cases if c["case_id"] == "rf_19_unsupported_evidence_blocked")
    assert any(not ev["is_supported"] for ev in unsupported_case["unused_evidence"])
    assert "inject_unsupported_skills_or_projects" in unsupported_case["forbidden_actions"]


def test_rollback_cases_preserve_prior_best_candidate(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that rollback cases explicitly preserve or restore the prior best safe candidate."""
    rollback_cases = [c for c in loaded_cases if c["expected_runtime_outcome"] == "OPTIMIZATION_ROLLED_BACK"]
    assert len(rollback_cases) >= 6, f"Expected >= 6 rollback cases, got {len(rollback_cases)}"

    for case in rollback_cases:
        cid = case["case_id"]
        assert any("rollback" in a.lower() or "restore" in a.lower() for a in case["allowed_actions"]), (
            f"Rollback case '{cid}' lacks rollback in allowed_actions"
        )


def test_iteration_traces_are_finite(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that budget cases enforce a bounded iteration limit (e.g. 5 iterations)."""
    budget_case = next(c for c in loaded_cases if c["case_id"] == "rf_37_iteration_budget_terminates")
    assert "terminate_loop_at_budget" in budget_case["allowed_actions"]
    assert "infinite_looping" in budget_case["forbidden_actions"]


def test_no_case_uses_fill_percentage_as_only_decision(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that fill percentage alone does not determine acceptance."""
    # rf_41 tests this explicitly
    case_41 = next(c for c in loaded_cases if c["case_id"] == "rf_41_fill_percentage_alone_does_not_determine_acceptance")
    assert case_41["render_measurement"]["vertical_fill_ratio"] == 0.98
    assert case_41["render_measurement"]["has_collision"] is True
    assert case_41["expected_runtime_outcome"] != "ACCEPTED", "Colliding layout should not be accepted merely due to 0.98 fill"


def test_no_case_requires_one_exact_resume_structure(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that the corpus evaluates behavioral properties rather than enforcing fixed bullet counts."""
    bullet_counts = {c["input_candidate"]["bullet_count"] for c in loaded_cases}
    assert len(bullet_counts) >= 5, f"Expected varied bullet counts, got {bullet_counts}"


def test_zero_pii_across_render_fill_fixtures() -> None:
    """Verifies that no emails, phone numbers, or secrets appear across render_fill fixtures."""
    fixtures_to_scan = [CASES_PATH] + list(SCENARIOS_DIR.glob("*.json"))
    for file_path in fixtures_to_scan:
        content = file_path.read_text(encoding="utf-8")
        assert not EMAIL_PATTERN.search(content), f"PII Email detected in {file_path}"
        assert not PHONE_PATTERN.search(content), f"PII Phone detected in {file_path}"
        assert not SECRET_PATTERN.search(content), f"Secret key pattern detected in {file_path}"


def test_recorded_scenarios_integrity() -> None:
    """Verifies that all 12 recorded scenario files exist, parse cleanly, and contain expected fields."""
    expected_scenarios = [
        "01_underfill_add_strong_bullet_clean_fit.json",
        "02_underfill_attempted_filler_rejected.json",
        "03_slight_overflow_shorter_variant_clean_fit.json",
        "04_overflow_safe_compression_clean_fit.json",
        "05_overflow_bad_compression_rollback.json",
        "06_collision_despite_acceptable_fill_ratio.json",
        "07_render_failure_prior_safe_fallback.json",
        "08_optimizer_cycle_detected.json",
        "09_iteration_budget_exhausted.json",
        "10_human_review_outcome_with_usable_pdf.json",
        "11_no_meaningful_expansion_evidence.json",
        "12_metric_altering_compression_candidate_rejected.json",
    ]

    for filename in expected_scenarios:
        file_path = SCENARIOS_DIR / filename
        assert file_path.exists(), f"Missing recorded scenario fixture: {file_path}"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"Scenario {filename} must be a JSON object"
        assert "scenario_id" in data and "initial_state" in data and "final_state" in data
        assert "trace_ledger" in data, f"Scenario {filename} missing trace_ledger"


# ==============================================================================
# Integration Acceptance Scaffolding (Marked strict xfail for pending features)
# ==============================================================================

@pytest.mark.xfail(
    strict=True,
    reason="pending render-fill implementation: actual measurement adapter"
)
def test_acceptance_actual_measurement_adapter() -> None:
    """Acceptance test: Render adapter must measure vertical fill ratio and page count from rendered PDF."""
    from src.tailor2 import measure_rendered_layout  # type: ignore[attr-defined]

    mock_pdf = Path("tests/fixtures/tailor2/mock_resume.pdf")
    measurement = measure_rendered_layout(mock_pdf)
    assert measurement.page_count == 1
    assert 0.85 <= measurement.vertical_fill_ratio <= 1.0


@pytest.mark.xfail(
    strict=True,
    reason="pending render-fill implementation: semantic geometry and collision detector"
)
def test_acceptance_semantic_geometry_and_collision_detector() -> None:
    """Acceptance test: Collision detector must identify heading/date overlaps and section collisions."""
    from src.tailor2 import detect_layout_collisions  # type: ignore[attr-defined]

    mock_tex = Path("tests/fixtures/tailor2/mock_collision.tex")
    collisions = detect_layout_collisions(mock_tex)
    assert len(collisions) >= 1
    assert collisions[0].collision_type in ("section_collision", "tech_date_collision")


@pytest.mark.xfail(
    strict=True,
    reason="pending render-fill implementation: safe unused evidence expansion engine"
)
def test_acceptance_safe_unused_evidence_expansion_engine() -> None:
    """Acceptance test: Expansion engine must select highest-value unused evidence without overflow."""
    from src.tailor2 import expand_layout_with_unused_evidence  # type: ignore[attr-defined]

    mock_draft = {}
    expanded = expand_layout_with_unused_evidence(mock_draft, available_vertical_space_in=1.5)
    assert expanded.new_bullet_added is True
    assert expanded.preserved_prior_safe is True


@pytest.mark.xfail(
    strict=True,
    reason="pending render-fill implementation: factual-preserving bullet and spacing compressor"
)
def test_acceptance_factual_preserving_bullet_compressor() -> None:
    """Acceptance test: Compressor must shorten overflowing bullets while preserving exact numbers."""
    from src.tailor2 import compress_layout_safely  # type: ignore[attr-defined]

    overflow_bullet = "Consolidated 862 dead-letter topics across distributed clusters into shared queues, cutting topic sprawl by ~70%."
    compressed = compress_layout_safely([overflow_bullet], target_lines_saved=1)
    assert "862" in compressed[0]
    assert "~70%" in compressed[0]


@pytest.mark.xfail(
    strict=True,
    reason="pending render-fill implementation: bounded multi-iteration optimizer with cycle detection and rollback"
)
def test_acceptance_bounded_multi_iteration_optimizer_cycle_detection() -> None:
    """Acceptance test: Optimizer must terminate within max_iterations and detect cyclic state oscillations."""
    from src.tailor2 import optimize_render_fill_loop  # type: ignore[attr-defined]

    initial_draft = {}
    result = optimize_render_fill_loop(initial_draft, max_iterations=5)
    assert result.iterations_executed <= 5
    assert result.cycle_detected is False or result.rolled_back is True
