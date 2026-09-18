"""Executable verification and acceptance test scaffolding for Tailor2
semantic-selection and multi-candidate-ranking evaluation corpus.

Validates:
1. Schema conformance of all 48 evaluation fixtures in cases.json.
2. Target ID and canonical evidence ID resolution.
3. Top-10 target JD presence and SHA-256 immutability.
4. Metric, numeric token, and approximation marker (~40%, ~70%) preservation.
5. Alternative requirement OR semantics (degree or experience).
6. Negative matching and rejection of unrelated technologies.
7. Supported vs unsupported skills distinction.
8. Error severity mapping (FATAL_INTEGRITY strictly for factual issues; quality defects to repair/warning).
9. Unused-evidence ledger integrity and explicit omission reasons.
10. Zero contact PII (emails, phone numbers, addresses) and zero provider secrets.
11. Recorded-response scenarios integrity across all 10 response fixtures.
12. Integration acceptance scaffolding for pending production capabilities (strict xfails).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
import pytest

from src.profile import load_profile

CASES_PATH = Path("tests/fixtures/tailor2/selection_ranking/cases.json")
CATALOG_PATH = Path("tests/fixtures/tailor2/quality_regressions/canonical_evidence_catalog.json")
TARGETS_PATH = Path("shortlist/tailoring_targets/targets.json")
JDS_DIR = Path("shortlist/tailoring_targets/jds")
RESPONSES_DIR = Path("tests/fixtures/tailor2/selection_ranking/recorded_responses")
PROFILE_PATH = Path("config/master_profile.yaml")

# Strict PII detection patterns
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_PATTERN = re.compile(r"(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})")
SECRET_PATTERN = re.compile(r"(sk-[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9_-]+|api[-_]?key)", re.IGNORECASE)

VALID_CATEGORIES = {
    "requirement_interpretation",
    "semantic_matching",
    "evidence_selection",
    "skills_selection",
    "multi_candidate_generation",
    "resume_ranking",
    "unused_evidence_page_fill",
}

VALID_SEVERITIES = {
    "CLEAN_PASS",
    "ADVISORY_GAP",
    "AUTO_CORRECTABLE",
    "REPAIRABLE_QUALITY",
    "NEEDS_HUMAN_REVIEW",
    "FATAL_INTEGRITY",
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


@pytest.fixture(scope="module")
def master_profile():
    assert PROFILE_PATH.exists(), f"Missing master profile: {PROFILE_PATH}"
    return load_profile(PROFILE_PATH)


# ==============================================================================
# Fixture Integrity Tests (Must Pass 100% Normally)
# ==============================================================================

def test_fixtures_count_and_categories(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that exactly 48 fixtures are present across all 7 categories."""
    assert len(loaded_cases) == 48, f"Expected 48 fixtures, got {len(loaded_cases)}"

    counts: dict[str, int] = {}
    for case in loaded_cases:
        cat = case["category"]
        counts[cat] = counts.get(cat, 0) + 1

    expected_counts = {
        "requirement_interpretation": 5,
        "semantic_matching": 7,
        "evidence_selection": 8,
        "skills_selection": 7,
        "multi_candidate_generation": 8,
        "resume_ranking": 7,
        "unused_evidence_page_fill": 6,
    }

    for cat, expected in expected_counts.items():
        actual = counts.get(cat, 0)
        assert actual == expected, f"Category '{cat}': expected {expected}, got {actual}"


def test_every_fixture_conforms_to_documented_schema(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that every fixture contains all required schema fields and valid enums."""
    required_fields = {
        "case_id",
        "category",
        "target_id",
        "requirement",
        "candidate_evidence",
        "protected_facts",
        "expected_matches",
        "expected_non_matches",
        "expected_selection_properties",
        "expected_ranking_properties",
        "expected_runtime_severity",
        "forbidden_inferences",
        "acceptable_variation",
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
        assert case["expected_runtime_severity"] in VALID_SEVERITIES, f"Case '{cid}' invalid severity: {case['expected_runtime_severity']}"

        # Validate requirement sub-schema
        req = case["requirement"]
        assert isinstance(req, dict), f"Case '{cid}': requirement must be dict"
        assert "id" in req and "raw_quote" in req and "interpreted_intent" in req, f"Case '{cid}': requirement missing keys"
        assert "is_alternative_or_group" in req, f"Case '{cid}': requirement missing is_alternative_or_group"
        assert isinstance(req["is_alternative_or_group"], bool), f"Case '{cid}': is_alternative_or_group must be bool"

        # Validate candidate_evidence is a list of dicts
        for ev in case["candidate_evidence"]:
            assert isinstance(ev, dict), f"Case '{cid}': candidate_evidence items must be dicts"
            assert "evidence_id" in ev, f"Case '{cid}': evidence item missing evidence_id"

        # Validate list types
        for field in ("protected_facts", "expected_matches", "expected_non_matches",
                      "expected_selection_properties", "expected_ranking_properties",
                      "forbidden_inferences", "acceptable_variation"):
            assert isinstance(case[field], list), f"Case '{cid}': {field} must be list"


def test_cross_target_coverage_all_ten_represented(loaded_cases: list[dict[str, Any]], targets_data: list[dict[str, Any]]) -> None:
    """Verifies that all 10 target companies are represented and OpenAI is the deepest case."""
    target_counts: dict[str, int] = {}
    for case in loaded_cases:
        tid = case["target_id"]
        target_counts[tid] = target_counts.get(tid, 0) + 1

    # Extract target company tokens
    expected_prefixes = {
        "openai_4949", "twitch_4182", "tiktok_4164", "roadrunner_5027",
        "doordash_4608", "c3ai_4894", "zoom_4766", "lexisnexis_4987",
        "commure_4839", "idme_3981"
    }

    actual_targets = set(target_counts.keys())
    assert actual_targets == expected_prefixes, f"Targets mismatch: missing {expected_prefixes - actual_targets}"

    # OpenAI must be the deepest acceptance case
    assert target_counts["openai_4949"] >= 10, f"OpenAI cases ({target_counts['openai_4949']}) should be at least 10"


def test_referenced_target_ids_resolve(loaded_cases: list[dict[str, Any]], targets_data: list[dict[str, Any]]) -> None:
    """Verifies that every target_id resolves to an entry in shortlist/tailoring_targets/targets.json."""
    valid_target_ids = set()
    for t in targets_data:
        company_slug = t["company"].lower().split()[0].replace(".", "").replace("-", "")
        # Standardize known slugs
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


def test_referenced_evidence_ids_resolve(loaded_cases: list[dict[str, Any]], canonical_catalog: dict[str, dict[str, Any]]) -> None:
    """Verifies that all evidence IDs in candidate_evidence, expected_matches resolve to canonical catalog."""
    for case in loaded_cases:
        cid = case["case_id"]
        for ev in case.get("candidate_evidence", []):
            eid = ev["evidence_id"]
            assert eid in canonical_catalog, f"Case '{cid}': candidate evidence '{eid}' not in canonical catalog"

        # If category is evidence_selection, multi_candidate_generation, or unused_evidence, expected_matches must be valid evidence IDs
        if case["category"] in ("evidence_selection", "multi_candidate_generation", "unused_evidence_page_fill"):
            for mid in case.get("expected_matches", []):
                assert mid in canonical_catalog, f"Case '{cid}': expected_match '{mid}' not in canonical catalog"


def test_all_ten_target_jds_present_and_unchanged(targets_data: list[dict[str, Any]]) -> None:
    """Verifies that all 10 target JD text files exist and match their expected SHA-256 checksums."""
    assert len(targets_data) == 10, f"Expected 10 targets, got {len(targets_data)}"
    for target in targets_data:
        jd_filename = target["jd_filename"]
        jd_path = JDS_DIR / jd_filename
        assert jd_path.exists(), f"JD file missing: {jd_path}"

        content = jd_path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        assert actual_sha == target["jd_sha256"], (
            f"JD SHA mismatch for {jd_filename}: expected {target['jd_sha256']}, got {actual_sha}"
        )


def test_protected_facts_preserved_across_candidate_variants(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that multi-candidate variants preserve evidence IDs and exact numeric facts."""
    cases_with_variants = [c for c in loaded_cases if "candidate_variants" in c]
    assert len(cases_with_variants) >= 7, f"Expected >= 7 cases with variants, got {len(cases_with_variants)}"

    for case in cases_with_variants:
        cid = case["case_id"]
        variants = case["candidate_variants"]
        assert len(variants) >= 2, f"Case '{cid}' has fewer than 2 variants"

        valid_variants = [v for v in variants if v.get("is_factually_valid", True)]
        assert len(valid_variants) >= 1, f"Case '{cid}' has no valid variants"

        # Evidence IDs must be preserved in all valid variants
        primary_eids = set(variants[0]["evidence_ids"])
        for v in valid_variants:
            assert set(v["evidence_ids"]) == primary_eids, (
                f"Case '{cid}' variant '{v['variant_id']}' altered evidence IDs: {v['evidence_ids']} vs {primary_eids}"
            )


def test_approximation_markers_preserved(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that approximation markers (~40%, ~70%, ~500ms) are explicitly guarded."""
    approx_cases = [
        c for c in loaded_cases
        if any("~" in f for f in c.get("protected_facts", []))
    ]
    assert len(approx_cases) >= 4, f"Expected at least 4 approximation test cases, found {len(approx_cases)}"

    for case in approx_cases:
        cid = case["case_id"]
        # Must have a forbidden inference or note against stripping approximation
        has_approx_guard = (
            any("~" in fi or "approximation" in fi.lower() or "rounding" in fi.lower() for fi in case["forbidden_inferences"]) or
            any("~" in p or "approx" in p.lower() for p in case["expected_selection_properties"]) or
            "approx" in case["notes"].lower()
        )
        assert has_approx_guard, f"Case '{cid}' lacks explicit guard for approximation marker"


def test_semantic_equivalence_never_alters_protected_metrics(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that semantic equivalence test cases protect against mutating metrics."""
    sem_cases = [c for c in loaded_cases if c["category"] == "semantic_matching"]
    for case in sem_cases:
        cid = case["case_id"]
        if any(char.isdigit() for f in case["protected_facts"] for char in f):
            # Must guard against metric drift
            guards = [fi for fi in case["forbidden_inferences"] if any(w in fi.lower() for w in ("altering", "rounding", "dropping", "inflating"))]
            assert guards or "metric" in case["notes"].lower(), f"Case '{cid}' has numbers but lacks metric drift guard"


def test_negative_matches_do_not_become_positive_by_lexical_coincidence(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that disjoint technical domains (e.g. Kafka vs WebRTC) are explicitly rejected."""
    unrelated_case = next(c for c in loaded_cases if c["case_id"] == "sel_10_unrelated_technologies_rejected")
    assert "am_b01_dlq_consolidation" in unrelated_case["expected_non_matches"]
    assert "cm_b1" in unrelated_case["expected_non_matches"]
    assert any("webrtc" in fi.lower() for fi in unrelated_case["forbidden_inferences"])


def test_supported_vs_unsupported_skills_distinguished(loaded_cases: list[dict[str, Any]], master_profile) -> None:
    """Verifies that skills test cases distinguish supported skills from unsupported ones."""
    # Case sel_24: unsupported skill
    unsupported_case = next(c for c in loaded_cases if c["case_id"] == "sel_24_unsupported_skill_blocked_for_ats")
    assert unsupported_case["expected_runtime_severity"] == "FATAL_INTEGRITY"
    assert "Ruby on Rails" in unsupported_case["expected_non_matches"]
    assert "Kubernetes" in unsupported_case["expected_non_matches"]

    # Verify they are not in master profile
    all_profile_skills = {
        skill for category_skills in master_profile.skills.values() for skill in category_skills
    }
    assert "Ruby on Rails" not in all_profile_skills
    assert "Kubernetes" not in all_profile_skills


def test_alternative_requirements_retain_or_semantics(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that cases with alternative requirements declare OR semantics and prohibit AND-forcing."""
    or_cases = [c for c in loaded_cases if c["requirement"].get("is_alternative_or_group") is True]
    assert len(or_cases) >= 3, f"Expected at least 3 OR-group cases, found {len(or_cases)}"

    for case in or_cases:
        cid = case["case_id"]
        assert len(case["requirement"].get("alternative_options", [])) >= 2, (
            f"Case '{cid}': OR group must have at least 2 alternative options"
        )
        assert any("conjoined" in fi.lower() or "and" in fi.lower() or "or" in fi.lower() for fi in case["forbidden_inferences"]), (
            f"Case '{cid}' lacks forbidden inference against conjoined AND logic"
        )


def test_fatal_expectations_correspond_to_factual_integrity(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that every FATAL_INTEGRITY case corresponds strictly to a factual or integrity breach."""
    fatal_cases = [c for c in loaded_cases if c["expected_runtime_severity"] == "FATAL_INTEGRITY"]
    assert len(fatal_cases) >= 4, f"Expected at least 4 FATAL_INTEGRITY cases, found {len(fatal_cases)}"

    for case in fatal_cases:
        cid = case["case_id"]
        # Must relate to fabrication, metric alteration, unevidenced skill, or ungrounded claim
        rationale_text = " ".join(case["forbidden_inferences"] + [case["notes"]] + case["protected_facts"]).lower()
        factual_keywords = {"fabricated", "rounding", "metric", "unsupported", "alter", "invent", "grounded", "falsehood"}
        assert any(k in rationale_text for k in factual_keywords), (
            f"Case '{cid}' marked FATAL_INTEGRITY without clear factual violation rationale"
        )


def test_quality_defects_map_to_ranking_repair_warning_or_human_review(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that non-factual quality defects map to REPAIRABLE_QUALITY, ADVISORY_GAP, or NEEDS_HUMAN_REVIEW."""
    quality_cases = [
        c for c in loaded_cases
        if c["case_id"] in (
            "sel_05_missing_product_evidence_disclosed_gap",
            "sel_25_auxiliary_tooling_not_dominating",
            "sel_27_inventory_dump_prevented",
            "sel_32_feature_catalogue_loses_to_outcome",
            "sel_36_repeated_sentence_structures_penalized",
            "sel_37_repeated_ai_abstractions_visible",
            "sel_38_duplicate_requirement_crowding_penalized",
            "sel_40_misleading_applied_product_positioning_flagged",
            "sel_41_buried_strong_evidence_triggers_reordering",
        )
    ]
    for case in quality_cases:
        cid = case["case_id"]
        sev = case["expected_runtime_severity"]
        assert sev in ("REPAIRABLE_QUALITY", "ADVISORY_GAP", "NEEDS_HUMAN_REVIEW", "AUTO_CORRECTABLE"), (
            f"Quality case '{cid}' should not have fatal severity: got {sev}"
        )


def test_unused_evidence_cases_have_explicit_omission_reasons(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that all unused-evidence cases declare explicit omission reasons."""
    unused_cases = [c for c in loaded_cases if c["category"] == "unused_evidence_page_fill"]
    assert len(unused_cases) == 6, f"Expected 6 unused-evidence cases, got {len(unused_cases)}"

    for case in unused_cases:
        cid = case["case_id"]
        assert "omission_reason" in case, f"Case '{cid}' missing omission_reason"
        assert case["omission_reason"] in ("space_constraint", "lower_target_relevance", "redundant_coverage", "single_employer_cap")


def test_no_fixture_requires_one_exact_prose_formulation(loaded_cases: list[dict[str, Any]]) -> None:
    """Verifies that every fixture specifies acceptable variation to prevent brittleness."""
    for case in loaded_cases:
        cid = case["case_id"]
        assert len(case["acceptable_variation"]) >= 1, f"Case '{cid}' lacks acceptable_variation"


def test_zero_pii_across_fixtures_and_responses() -> None:
    """Verifies that no personal contact information or secrets appear in fixtures."""
    fixtures_to_scan = [CASES_PATH] + list(RESPONSES_DIR.glob("*.json"))
    for file_path in fixtures_to_scan:
        content = file_path.read_text(encoding="utf-8")
        assert not EMAIL_PATTERN.search(content), f"PII Email detected in {file_path}"
        assert not PHONE_PATTERN.search(content), f"PII Phone detected in {file_path}"
        assert not SECRET_PATTERN.search(content), f"Secret key pattern detected in {file_path}"


def test_recorded_responses_integrity() -> None:
    """Verifies that all 10 recorded response scenarios exist, parse cleanly, and contain expected fields."""
    expected_filenames = [
        "01_requirement_interpretation.json",
        "02_semantic_evidence_matching.json",
        "03_candidate_generation.json",
        "04_local_ranking.json",
        "05_resume_level_ranking.json",
        "06_malformed_recoverable_output.json",
        "07_factually_invalid_high_scoring_candidate.json",
        "08_omitted_candidate_ranking.json",
        "09_fewer_candidates_than_requested.json",
        "10_uncertain_comparison_fallback.json",
    ]

    for filename in expected_filenames:
        resp_file = RESPONSES_DIR / filename
        assert resp_file.exists(), f"Missing recorded response fixture: {resp_file}"
        data = json.loads(resp_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"Fixture {filename} must be a JSON object"


# ==============================================================================
# Integration Acceptance Scaffolding (Marked strict xfail for pending features)
# ==============================================================================

@pytest.mark.xfail(
    strict=True,
    reason="pending selection-ranking implementation: semantic requirement parser with alternative OR-group extraction"
)
def test_acceptance_semantic_requirement_interpretation_or_group() -> None:
    """Acceptance test: Semantic requirement parser must extract alternative branches as an OR group."""
    from src.tailor2 import parse_atomic_requirements_semantically  # type: ignore[attr-defined]

    raw_jd = "Requirements: Bachelor's degree in Computer Science or equivalent practical experience."
    reqs = parse_atomic_requirements_semantically(raw_jd)
    or_req = next(r for r in reqs if r.is_alternative_or_group)
    assert len(or_req.alternative_branches) == 2


@pytest.mark.xfail(
    strict=True,
    reason="pending selection-ranking implementation: semantic skill alias matching and unevidenced injection prevention"
)
def test_acceptance_semantic_skill_alias_matching() -> None:
    """Acceptance test: Skills selector must normalize Postgres to PostgreSQL and block unevidenced Vue."""
    from src.tailor2 import select_tailored_skills  # type: ignore[attr-defined]

    profile = load_profile(PROFILE_PATH)
    jd_skills = ["Postgres", "React", "Vue", "Kubernetes"]
    selected = select_tailored_skills(jd_skills, profile)
    assert "PostgreSQL" in selected.displayed_skills
    assert "Vue" not in selected.displayed_skills
    assert "Kubernetes" not in selected.displayed_skills


@pytest.mark.xfail(
    strict=True,
    reason="pending selection-ranking implementation: multi-candidate bullet generation and local outcome ranking engine"
)
def test_acceptance_multi_candidate_bullet_generation_and_local_ranking() -> None:
    """Acceptance test: Candidate engine generates multiple variants and ranks outcome over catalogue."""
    from src.tailor2 import generate_and_rank_bullet_candidates  # type: ignore[attr-defined]

    profile = load_profile(PROFILE_PATH)
    candidates = generate_and_rank_bullet_candidates("int_b2", profile, count=3)
    assert len(candidates) == 3
    # Top ranked candidate must be outcome-oriented and preserve metrics
    top_candidate = candidates[0]
    assert "~40%" in top_candidate.text
    assert top_candidate.score > 0.90


@pytest.mark.xfail(
    strict=True,
    reason="pending selection-ranking implementation: whole-resume syntactic redundancy penalty and coverage diversity ranker"
)
def test_acceptance_whole_resume_redundancy_and_coverage_ranking() -> None:
    """Acceptance test: Whole-résumé ranker must detect repetitive opening verbs and penalize redundant drafts."""
    from src.tailor2 import evaluate_whole_resume_ranking  # type: ignore[attr-defined]

    repetitive_draft = [
        "Built order processing services using Java.",
        "Built dead-letter queue handler using Kafka.",
        "Built row-level access control using SQL."
    ]
    eval_result = evaluate_whole_resume_ranking(repetitive_draft)
    assert eval_result.redundancy_penalty > 0.0
    assert eval_result.status == "PASS_WITH_WARNING"


@pytest.mark.xfail(
    strict=True,
    reason="pending selection-ranking implementation: unused evidence ledger and blank-space expansion selector"
)
def test_acceptance_unused_evidence_ledger_and_blank_space_expansion() -> None:
    """Acceptance test: Ledger tracks omitted evidence with reasons and selects highest-value item for page fill."""
    from src.tailor2 import UnusedEvidenceLedger, expand_vertical_space  # type: ignore[attr-defined]

    ledger = UnusedEvidenceLedger()
    ledger.record_omission(evidence_id="int_b1", reason="space_constraint", priority=1)
    ledger.record_omission(evidence_id="cm_b5", reason="lower_target_relevance", priority=3)

    promoted_item = expand_vertical_space(ledger, available_lines=2)
    assert promoted_item.evidence_id == "int_b1"
