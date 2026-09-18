"""Integration checks between the independent corpus and production contracts."""

from __future__ import annotations

import json
from pathlib import Path

from src.profile import load_profile
from src.tailor2 import (
    evaluate_whole_resume_ranking,
    generate_and_rank_bullet_candidates,
    parse_atomic_requirements_semantically,
    select_tailored_skills,
)
from src.tailor2.selection_ranking import Requirement


FIXTURE_DIR = Path("tests/fixtures/tailor2/selection_ranking")
RESPONSES_DIR = FIXTURE_DIR / "recorded_responses"
PROFILE_PATH = Path("config/master_profile.yaml")


def _response(name: str) -> dict:
    return json.loads((RESPONSES_DIR / name).read_text(encoding="utf-8"))


def test_requirement_recording_maps_to_typed_semantic_view() -> None:
    recorded = _response("01_requirement_interpretation.json")
    first = recorded["interpreted_requirements"][0]
    requirements = parse_atomic_requirements_semantically(first["raw_quote"])

    assert recorded["status"] == "success"
    assert first["is_alternative_or_group"] is True
    assert first["alternative_branches"]
    assert requirements[0].is_alternative_or_group is True
    assert len(requirements[0].alternative_branches) >= 2
    assert isinstance(requirements[0].requirement, Requirement)
    assert first["candidate_satisfaction_status"] == "SATISFIED"


def test_semantic_matching_recording_uses_profile_backed_aliases() -> None:
    profile = load_profile(PROFILE_PATH)
    recorded = _response("02_semantic_evidence_matching.json")
    selected = select_tailored_skills(["Postgres", "React", "Vue", "Kubernetes"], profile)

    assert recorded["status"] == "success"
    assert recorded["matches"][0]["matched_evidence_id"] == "int_b2"
    assert recorded["matches"][0]["semantic_relationship"] == "canonical_synonym"
    assert "PostgreSQL" in selected.displayed_skills
    assert "React" not in selected.displayed_skills
    assert "Vue" not in selected.displayed_skills
    assert "Kubernetes" not in selected.displayed_skills


def test_candidate_generation_recording_is_bounded_to_canonical_phrasings() -> None:
    profile = load_profile(PROFILE_PATH)
    recorded = _response("03_candidate_generation.json")
    generated = generate_and_rank_bullet_candidates(recorded["evidence_id"], profile, count=3)
    bullet = next(
        bullet
        for entry in (*profile.projects, *profile.experience)
        for bullet in entry.bullets
        if bullet.id == "int_b2"
    )
    canonical_texts = {bullet.phrasings.short, bullet.phrasings.medium, bullet.phrasings.long}

    assert recorded["canonical_facts"]["technology"] == "PostgreSQL"
    assert len(recorded["variants"]) == 3
    assert len(generated) == 3
    assert all(candidate.evidence_id == "int_b2" for candidate in generated)
    assert all(candidate.text in canonical_texts for candidate in generated)
    assert generated[0].score >= generated[-1].score
    assert "exactly one downstream provider call" in generated[0].text


def test_recorded_local_and_resume_rankings_preserve_deterministic_fallbacks() -> None:
    local = _response("04_local_ranking.json")
    resume = _response("05_resume_level_ranking.json")
    evaluated = evaluate_whole_resume_ranking(
        [
            "Built order processing services using Java.",
            "Built dead-letter queue handler using Kafka.",
            "Built row-level access control using SQL.",
        ]
    )

    assert local["ranked_candidates"][0]["verdict"] == "SELECTED"
    assert local["ranked_candidates"][0]["aggregate_score"] > local["ranked_candidates"][1]["aggregate_score"]
    assert resume["whole_resume_evaluations"]["redundancy_check"]["status"] == "PASS_WITH_WARNING"
    assert resume["final_verdict"] == "ACCEPT"
    assert evaluated.status == "PASS_WITH_WARNING"
    assert evaluated.redundancy_penalty > 0


def test_recorded_recovery_and_integrity_scenarios_remain_explicit() -> None:
    malformed = _response("06_malformed_recoverable_output.json")
    invalid = _response("07_factually_invalid_high_scoring_candidate.json")
    omitted = _response("08_omitted_candidate_ranking.json")
    fewer = _response("09_fewer_candidates_than_requested.json")
    uncertain = _response("10_uncertain_comparison_fallback.json")

    assert malformed["recovered_successfully"] is True
    assert malformed["recovery_strategy"] == "strip_markdown_fences_and_trailing_commas"
    assert malformed["parsed_payload"]["outcome_score"] == 0.94
    assert invalid["verdict"] == "FATAL_INTEGRITY"
    assert invalid["pipeline_action"] == "REJECT_CANDIDATE"
    assert omitted["omission_detected"] is True
    assert omitted["omitted_candidate_ids"] == ["c2_star"]
    assert fewer["status"] == "DEGRADED_PASS"
    assert fewer["returned_candidate_count"] < fewer["requested_candidate_count"]
    assert uncertain["is_uncertain"] is True
    assert uncertain["fallback_applied"] == "CANONICAL_PROFILE_ORDER"
