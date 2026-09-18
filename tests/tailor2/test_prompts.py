"""Unit tests for Tailor2 prompt construction and information boundaries."""

import pytest

from src.profile import load_profile
from src.tailor2.models import (
    BulletAuditEvaluation,
    DimensionScore,
    DraftBullet,
    RepairedBullet,
)
from src.tailor2.prompts import (
    build_audit_prompt,
    build_draft_prompt,
    build_re_audit_prompt,
    build_repair_prompt,
)


@pytest.fixture
def profile():
    return load_profile("config/master_profile.yaml")


@pytest.fixture
def sample_bullet():
    return DraftBullet(
        bullet_id="b01",
        evidence_ids=["int_b1"],
        supported_requirement_ids=["req_01"],
        section="Experience",
        entry_id="bank_integration_internship",
        text="Architected an anti-corruption layer integrating legacy core banking systems.",
    )


def test_build_draft_prompt_contains_all_constraints(profile):
    jd_text = "Looking for a backend engineer with Python and distributed systems experience."
    prompt = build_draft_prompt(jd_text, profile, "backend", "Acme Corp", "Backend Engineer")

    # Contains JD
    assert "Acme Corp" in prompt
    assert "Backend Engineer" in prompt
    assert "backend engineer with Python" in prompt
    # Contains writing rules
    assert "compressed STAR or Google XYZ" in prompt
    assert "Kubernetes" in prompt and "Never render" in prompt
    assert "am_b00_order_management_domain" in prompt
    assert "amdocs_omission_ledger" in prompt
    # Contains evidence catalog
    assert "bank_integration_internship" in prompt
    assert "int_b1" in prompt


def test_build_audit_prompt_enforces_information_isolation(profile, sample_bullet):
    jd_text = "Looking for a backend engineer."
    evidence_by_id = {b.id: b for exp in profile.experience for b in exp.bullets}
    prompt = build_audit_prompt(jd_text, [sample_bullet], evidence_by_id)

    # Contains JD and bullet
    assert "Looking for a backend engineer" in prompt
    assert sample_bullet.text in prompt
    assert "int_b1" in prompt
    # Contains all 9 dimensions
    for dim in (
        "factual_fidelity",
        "metric_fidelity",
        "technology_fidelity",
        "technical_guarantee_fidelity",
        "relevance",
        "star_xyz_coherence",
        "readability",
        "recruiter_scan_quality",
        "ai_slop_risk",
    ):
        assert dim in prompt

    # MUST NOT contain drafter reasoning / CoT placeholders
    assert "chain of thought" not in prompt.lower()
    assert "strategy reasoning" not in prompt.lower()


def test_build_repair_prompt_receives_only_rejected_and_findings(profile, sample_bullet):
    evidence_by_id = {b.id: b for exp in profile.experience for b in exp.bullets}
    findings = {
        "b01": [
            {"dimension": "ai_slop_risk", "score": 1, "findings": "Uses buzzwords."}
        ]
    }
    prompt = build_repair_prompt([sample_bullet], evidence_by_id, findings)

    assert sample_bullet.text in prompt
    assert "Uses buzzwords" in prompt
    assert "ai_slop_risk" in prompt


def test_build_re_audit_prompt_receives_only_repaired_and_evidence(profile):
    repaired = [RepairedBullet("b01", "Engineered clean layer without buzzwords.")]
    evidence_by_id = {b.id: b for exp in profile.experience for b in exp.bullets}
    bullet_entries = {"b01": ("Experience", "bank_integration_internship", ["int_b1"])}
    prompt = build_re_audit_prompt("Sample JD", repaired, evidence_by_id, bullet_entries)

    assert "Engineered clean layer without buzzwords" in prompt
    assert "int_b1" in prompt
    assert "factual_fidelity" in prompt
