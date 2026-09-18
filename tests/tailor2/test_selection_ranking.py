"""Focused contracts for Tailor2 selection and ranking."""

from __future__ import annotations

import pytest
import json

from src.profile import load_profile
from src.tailor2.prompts import build_selection_prompt
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.lane import run_tailor2_lane
from src.tailor2.selection_ranking import (
    BulletCandidate,
    EvidenceMatch,
    RequirementAnalysis,
    Requirement,
    build_skill_candidates,
    bound_candidates,
    build_unused_evidence_ledger,
    filter_candidates,
    rank_candidates,
    select_evidence_flexibly,
    select_whole_resume,
    parse_selection_bundle,
    parse_evidence_matches,
    parse_requirement_analysis,
)
from src.tailor2.validators import extract_numeric_tokens


@pytest.fixture
def profile():
    return load_profile("config/master_profile.yaml")


def test_requirement_analysis_preserves_alternative_groups_and_responsibilities():
    analysis = parse_requirement_analysis(
        {
            "requirements": [
                {
                    "id": "req_degree",
                    "term": "Bachelor's degree or equivalent experience",
                    "quote": "Bachelor's degree or equivalent experience",
                    "kind": "must_have",
                    "alternative_group_id": "degree_or_equivalent",
                },
                {
                    "id": "req_python",
                    "term": "Python",
                    "quote": "Experience with Python",
                    "kind": "preferred",
                },
                {
                    "id": "resp_api",
                    "term": "build APIs",
                    "quote": "build APIs",
                    "kind": "responsibility",
                },
            ]
        },
        "The role asks for Bachelor's degree or equivalent experience. Experience with Python and build APIs.",
    )

    assert isinstance(analysis, RequirementAnalysis)
    assert analysis.requirements[0].alternative_group_id == "degree_or_equivalent"
    assert analysis.requirements[1].kind == "preferred"
    assert analysis.requirements[2].kind == "responsibility"


def test_requirement_parser_rejects_non_exact_quote():
    with pytest.raises(ValueError, match="not an exact JD substring"):
        parse_requirement_analysis(
            {"requirements": [{"id": "r", "term": "Python", "quote": "Java", "kind": "must_have"}]},
            "Experience with Python",
        )


def test_requirement_parser_accepts_legacy_nice_to_have():
    analysis = parse_requirement_analysis(
        {"requirements": [{"id": "r", "term": "Python", "quote": "Python", "importance": "nice_to_have"}]},
        "Python",
    )
    assert analysis.requirements[0].kind == "preferred"


def test_requirement_parser_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate requirement ID"):
        parse_requirement_analysis(
            {"requirements": [
                {"id": "r", "term": "Java", "quote": "Java"},
                {"id": "r", "term": "Python", "quote": "Python"},
            ]},
            "Java Python",
        )


def test_requirement_parser_rejects_empty_analysis():
    with pytest.raises(ValueError, match="at least one requirement"):
        parse_requirement_analysis({"requirements": []}, "A JD")


def test_requirement_parser_keeps_top_level_responsibilities_separate():
    analysis = parse_requirement_analysis(
        {"requirements": [{"id": "r", "term": "Java", "quote": "Java"}], "responsibilities": [{"id": "x", "term": "operate services", "quote": "operate services"}]},
        "Java and operate services",
    )
    assert [item.kind for item in analysis.requirements] == ["must_have", "responsibility"]


def test_evidence_match_distinguishes_gap_from_adjacent(profile):
    analysis = RequirementAnalysis([Requirement("r", "React", "React", "must_have")])
    evidence = {b.id for entry in (*profile.experience, *profile.projects) for b in entry.bullets}
    matches = [
        EvidenceMatch("r", [], "gap", 1.0, 1.0, "No React evidence"),
    ]
    selected = select_evidence_flexibly(analysis, matches, profile, "backend")
    assert not any(item.selected for item in selected)


def test_evidence_match_rejects_unknown_requirement_or_evidence(profile):
    evidence = {b.id for entry in (*profile.experience, *profile.projects) for b in entry.bullets}
    with pytest.raises(ValueError, match="unknown ID"):
        parse_evidence_matches(
            [{"requirement_id": "missing", "evidence_ids": [], "classification": "gap", "confidence": 1, "strength": 1, "explanation": "gap"}],
            {"r"},
            evidence,
        )


def test_adjacent_and_transferable_matches_are_preserved(profile):
    evidence = {b.id for entry in (*profile.experience, *profile.projects) for b in entry.bullets}
    matches = parse_evidence_matches(
        [
            {"requirement_id": "r", "evidence_ids": ["am_b01_dlq_consolidation"], "classification": "adjacent", "confidence": 0.8, "strength": 0.7, "explanation": "adjacent"},
            {"requirement_id": "r", "evidence_ids": ["int_b1"], "classification": "transferable", "confidence": 0.6, "strength": 0.5, "explanation": "transferable"},
        ],
        {"r"},
        evidence,
    )
    assert [item.classification for item in matches] == ["adjacent", "transferable"]


def test_postgres_alias_can_propose_existing_skill_category(profile):
    analysis = RequirementAnalysis([Requirement("r", "Postgres", "Postgres", "must_have")])
    matches = [EvidenceMatch("r", ["int_b1"], "direct", 1.0, 1.0, "Postgres alias")]
    skills = build_skill_candidates(profile, analysis, matches, {"int_b1"})
    assert any(item.include and item.term.casefold() in {"postgres", "postgresql"} for item in skills)
    assert all(item.category in profile.skills for item in skills)


def test_skill_candidates_do_not_dump_unrelated_canonical_skills(profile):
    analysis = RequirementAnalysis([Requirement("r", "Kafka", "Kafka", "must_have")])
    matches = [EvidenceMatch("r", ["am_b01_dlq_consolidation"], "direct", 1.0, 1.0, "Kafka")]
    skills = build_skill_candidates(profile, analysis, matches, {"am_b01_dlq_consolidation"})
    assert any(item.include for item in skills)
    assert len([item for item in skills if item.include]) < sum(len(values) for values in profile.skills.values())


def test_supported_skill_without_selected_demo_is_advisory(profile):
    analysis = RequirementAnalysis([Requirement("r", "Kafka", "Kafka", "must_have")])
    matches = [EvidenceMatch("r", ["am_b01_dlq_consolidation"], "direct", 1.0, 1.0, "Kafka")]
    skills = build_skill_candidates(profile, analysis, matches, set())
    kafka = next(item for item in skills if "kafka" in item.term.casefold())
    assert kafka.include is True
    assert kafka.weak_demo_advisory is True


def test_ai_interest_is_not_inflated_into_llm_requirement(profile):
    analysis = RequirementAnalysis([Requirement("r", "interest in AI", "interest in AI", "must_have")])
    matches = [EvidenceMatch("r", [], "gap", 0.8, 0.2, "Interest is not production experience")]
    assert not any(item.selected for item in select_evidence_flexibly(analysis, matches, profile, "backend"))


def test_flexible_selection_prefers_direct_strong_evidence_and_keeps_balance(profile):
    analysis = RequirementAnalysis([
        Requirement("r1", "Kafka", "Kafka", "must_have"),
        Requirement("r2", "Python", "Python", "must_have"),
    ])
    matches = [
        EvidenceMatch("r1", ["am_b01_dlq_consolidation"], "direct", 1.0, 1.0, "Kafka"),
        EvidenceMatch("r2", ["int_b1"], "direct", 0.9, 0.9, "Python"),
    ]
    selections = select_evidence_flexibly(analysis, matches, profile, "backend", line_budget=4)
    chosen = {item.evidence_id for item in selections if item.selected}
    assert {"am_b01_dlq_consolidation", "int_b1"}.issubset(chosen)


def _candidate(profile, *, text=None, candidate_id="c1", bullet_id="am_b01_dlq_consolidation"):
    bullet = next(b for entry in (*profile.experience, *profile.projects) for b in entry.bullets if b.id == bullet_id)
    return BulletCandidate(
        candidate_id=candidate_id,
        bullet_id=bullet_id,
        evidence_ids=[bullet.id],
        supported_requirement_ids=["r1"],
        text=text or bullet.phrasings.medium or bullet.phrasings.short,
    )


def _integrity_inputs(profile):
    bullet = next(b for entry in (*profile.experience, *profile.projects) for b in entry.bullets if b.id == "am_b01_dlq_consolidation")
    return (
        {bullet.id: bullet.phrasings.medium or bullet.phrasings.short},
        {bullet.id: [bullet.id]},
        {bullet.id},
    )


def test_candidate_integrity_rejects_fabricated_metric(profile):
    text = "Consolidated 999 dead-letter topics across distributed clusters into shared queues."
    candidate = _candidate(profile, text=text)
    texts, evidence, selected = _integrity_inputs(profile)
    valid, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert not valid
    assert any(item.code == "numeric_tokens" for item in findings[0].findings)


def test_candidate_integrity_rejects_undefined_added_metric(profile):
    original = _candidate(profile)
    candidate = _candidate(profile, text=original.text.replace("862", "862 and 17%"))
    texts, evidence, selected = _integrity_inputs(profile)
    _, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert any(item.code == "numeric_tokens" for item in findings[0].findings)


def test_candidate_integrity_accepts_canonical_approximation(profile):
    candidate = _candidate(profile)
    texts, evidence, selected = _integrity_inputs(profile)
    valid, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert valid == [candidate]
    assert findings[0].valid


def test_candidate_integrity_rejects_changed_evidence_identity(profile):
    candidate = _candidate(profile, text=_candidate(profile).text)
    candidate = BulletCandidate(candidate.candidate_id, candidate.bullet_id, ["am_b00_order_management_domain"], candidate.supported_requirement_ids, candidate.text)
    texts, evidence, selected = _integrity_inputs(profile)
    _, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert any(item.code == "evidence_identity" for item in findings[0].findings)


def test_candidate_integrity_rejects_line_break(profile):
    candidate = _candidate(profile, text=_candidate(profile).text + "\nmore")
    texts, evidence, selected = _integrity_inputs(profile)
    _, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert any(item.code == "shape" for item in findings[0].findings)


def test_candidate_integrity_rejects_prohibited_claim(profile):
    original = _candidate(profile)
    candidate = _candidate(profile, text=original.text.replace("Cut", "Kubernetes cut", 1))
    texts, evidence, selected = _integrity_inputs(profile)
    _, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert any(item.code == "prohibited_claim" for item in findings[0].findings)


def test_candidate_integrity_preserves_leading_verb_and_length(profile):
    original = _candidate(profile)
    candidate = _candidate(profile, text="Built " + original.text.lower())
    texts, evidence, selected = _integrity_inputs(profile)
    _, findings = filter_candidates([candidate], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert any(item.code == "leading_verb" for item in findings[0].findings)


def test_candidate_filter_drops_only_invalid_and_retains_safe(profile):
    safe = _candidate(profile, candidate_id="safe")
    unsafe = _candidate(profile, candidate_id="unsafe", text=safe.text.replace("862", "999"))
    texts, evidence, selected = _integrity_inputs(profile)
    valid, findings = filter_candidates([unsafe, safe], canonical_text_by_bullet=texts, canonical_evidence_by_bullet=evidence, selected_evidence_ids=selected, profile=profile)
    assert [item.candidate_id for item in valid] == ["safe"]
    assert len(findings) == 2


def test_candidate_generation_is_bounded_per_bullet(profile):
    base = _candidate(profile)
    candidates = [
        base,
        BulletCandidate("c2", base.bullet_id, base.evidence_ids, base.supported_requirement_ids, base.text, "shorter"),
        BulletCandidate("c3", base.bullet_id, base.evidence_ids, base.supported_requirement_ids, base.text, "mechanism"),
    ]
    bounded, warnings = bound_candidates(candidates, 2)
    assert [item.candidate_id for item in bounded] == ["c1", "c2"]
    assert warnings


def test_ranking_falls_back_when_model_ranking_is_incomplete(profile):
    candidate = _candidate(profile)
    result = rank_candidates([candidate], model_rankings={"rankings": []})
    assert result.selected_by_bullet == {candidate.bullet_id: candidate.candidate_id}
    assert any("fallback" in warning for warning in result.warnings)


def test_valid_model_ranking_persists_component_scores(profile):
    candidate = _candidate(profile)
    result = rank_candidates([candidate], model_rankings={"rankings": [{"candidate_id": "c1", "component_scores": {"clarity": 9, "relevance": 8}, "total_score": 8.5, "rationale": "clear"}]})
    assert result.rankings[0].component_scores["clarity"] == 9
    assert result.rankings[0].selected is True


def test_malformed_model_ranking_uses_deterministic_scores(profile):
    candidate = _candidate(profile)
    result = rank_candidates([candidate], model_rankings={"rankings": [{"candidate_id": "c1", "component_scores": {"clarity": "bad"}}]})
    assert result.rankings[0].rationale == "deterministic safe-candidate ranking"
    assert any("fallback" in warning for warning in result.warnings)


def test_whole_resume_drops_redundant_candidate(profile):
    first = _candidate(profile, candidate_id="c1")
    second = BulletCandidate("c2", "am_b00_order_management_domain", ["am_b00_order_management_domain"], ["r1"], first.text)
    result = rank_candidates([first, second])
    selected, warnings = select_whole_resume([first, second], result)
    assert len(selected) == 1
    assert warnings


def test_whole_resume_respects_optional_bullet_cap(profile):
    first = _candidate(profile, candidate_id="c1")
    second = BulletCandidate("c2", "am_b00_order_management_domain", ["am_b00_order_management_domain"], ["r1"], "Engineered order services for customers.")
    selected, _ = select_whole_resume([first, second], rank_candidates([first, second]), max_bullets=1)
    assert len(selected) == 1


def test_unused_evidence_ledger_preserves_omission_reason(profile):
    selections = [
        type("Decision", (), {"evidence_id": "am_b00_order_management_domain", "requirement_ids": ["r1"], "score": 0.2, "estimated_line_cost": 1, "omission_reason": "redundant"})(),
    ]
    ledger = build_unused_evidence_ledger(selections, set(), profile)
    assert ledger[0].evidence_id == "am_b00_order_management_domain"
    assert ledger[0].omission_reason == "redundant"
    assert ledger[0].likely_section == "Experience"
    assert ledger[0].later_page_fill_suitability == "poor"


def test_selection_prompt_is_bounded_and_preserves_authority_boundary(profile):
    prompt = build_selection_prompt("Need Java APIs and Kafka.", profile, "backend", "Acme", "SWE")
    assert "Do not write résumé structure" in prompt
    assert "at most 3 candidates" in prompt
    assert "Kubernetes" in prompt


def test_selection_bundle_parses_requirements_matches_and_unused_contract(profile):
    jd = "Experience with Kafka and Python. Build APIs for distributed systems."
    bundle = parse_selection_bundle(
        {
            "requirements": [
                {"id": "r_kafka", "term": "Kafka", "quote": "Kafka", "kind": "must_have"},
                {"id": "r_python", "term": "Python", "quote": "Python", "kind": "preferred"},
            ],
            "matches": [
                {"requirement_id": "r_kafka", "evidence_ids": ["am_b01_dlq_consolidation"], "classification": "direct", "confidence": 1, "strength": 1, "explanation": "Kafka is explicit."},
                {"requirement_id": "r_python", "evidence_ids": [], "classification": "gap", "confidence": 1, "strength": 0, "explanation": "No selected Python match."},
            ],
            "evidence_selection": [
                {"evidence_id": "am_b01_dlq_consolidation", "selected": True, "score": 1, "requirement_ids": ["r_kafka"], "estimated_line_cost": 2, "rationale": "Direct Kafka evidence."},
            ],
            "candidates": [],
        },
        jd_text=jd,
        profile=profile,
        variant="backend",
        provider="openai",
        model="offline-fake",
    )
    assert bundle.requirements.requirements[0].id == "r_kafka"
    assert bundle.matches[1].classification == "gap"
    assert bundle.provider == "openai"


def test_lane_publishes_selection_artifact_before_legacy_draft(tmp_path, profile):
    jd = "We are looking for a Software Development Engineer with experience building high-throughput distributed systems and data pipelines. Experience with Java, Python, SQL, Kafka, and cloud infrastructure required."
    jd_path = tmp_path / "jd.txt"
    jd_path.write_text(jd, encoding="utf-8")
    from tests.tailor2.test_lane import _make_passing_audit_json, _make_valid_draft_json

    selection = {
        "requirements": [{"id": "r", "term": "Kafka", "quote": "Kafka", "kind": "must_have"}],
        "matches": [{"requirement_id": "r", "evidence_ids": ["am_b01_dlq_consolidation"], "classification": "direct", "confidence": 1, "strength": 1, "explanation": "Direct Kafka evidence."}],
        "evidence_selection": [{"evidence_id": "am_b01_dlq_consolidation", "selected": True, "score": 1, "requirement_ids": ["r"], "estimated_line_cost": 2, "rationale": "Direct evidence."}],
        "candidates": [],
    }
    invoker = Tailor2Invoker(
        provider="openai",
        model="offline-fake",
        fake_responses={
            "selection": json.dumps(selection),
            "draft": _make_valid_draft_json(),
            "audit": _make_passing_audit_json([f"b{i:02d}" for i in range(1, 16)]),
        },
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(jd_path, "Acme", "SWE", "backend", invoker, out_dir)
    assert result.success
    assert result.call_count == 3
    selection_artifact = json.loads((out_dir / "selection.json").read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert selection_artifact["requirements"]["requirements"][0]["id"] == "r"
    assert manifest["selection_enabled"] is True
    assert manifest["selection_artifacts"]["matches"][0]["classification"] == "direct"
