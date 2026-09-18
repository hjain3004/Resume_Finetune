"""Unit tests for Tailor2 deterministic validators."""

import dataclasses
import pytest

from src.profile import load_profile
from src.tailor2.models import (
    AmdocsOmission,
    AtomicRequirement,
    AuditResponse,
    BulletAuditEvaluation,
    DimensionScore,
    DraftBullet,
    DraftResponse,
    RepairResponse,
    RepairedBullet,
)
from src.tailor2.validators import (
    AuditValidationError,
    CANONICAL_AMDOCS_BULLETS,
    DraftValidationError,
    RepairValidationError,
    extract_numeric_tokens,
    validate_audit_response,
    validate_draft_response,
    validate_repair_response,
)


@pytest.fixture
def profile():
    return load_profile("config/master_profile.yaml")


@pytest.fixture
def valid_jd_text():
    return (
        "We are looking for a Software Development Engineer with experience building "
        "high-throughput distributed systems and data pipelines. Experience with Java, "
        "Python, SQL, Kafka, and cloud infrastructure required."
    )


def make_valid_draft(jd_text):
    # 7 canonical Amdocs: am_b01, am_b03, am_b04, am_b05, am_b02, am_b00, am_b07
    # 3 MalyTech: int_b1, int_b2, int_b3
    # 3 Projects: PeerChat (pc_b01, pc_b04), FRD (frd_b1, frd_b2), Campus (cm_b1)
    bullets = [
        # Amdocs (7 bullets - largest entry)
        DraftBullet("b01", ["am_b00_order_management_domain"], ["r1"], "Experience", "amdocs_software_developer", "Engineered order processing services in Java handling high-volume transactions."),
        DraftBullet("b02", ["am_b01_dlq_consolidation"], ["r1"], "Experience", "amdocs_software_developer", "Consolidated 862 dead-letter topics across distributed clusters into shared queues, cutting topic sprawl by 70%."),
        DraftBullet("b03", ["am_b02_row_level_entitlement"], ["r1"], "Experience", "amdocs_software_developer", "Built row-level access control filters enforcing security boundaries across datasets."),
        DraftBullet("b04", ["am_b03_audit_trail"], ["r1"], "Experience", "amdocs_software_developer", "Implemented asynchronous audit logging capturing system state transitions."),
        DraftBullet("b05", ["am_b04_data_retention"], ["r1"], "Experience", "amdocs_software_developer", "Structured partitioned SQL tables to automate data retention, reducing storage footprint by ~40%."),
        DraftBullet("b06", ["am_b05_test_automation"], ["r1"], "Experience", "amdocs_software_developer", "Automated integration test suites covering ~500 regression cases across deployment environments."),
        DraftBullet("b07", ["am_b07_code_quality_gates"], ["r1"], "Experience", "amdocs_software_developer", "Configured static analysis code quality gates reducing defect leakage before deployment."),
        # MalyTech (3 bullets)
        DraftBullet("b08", ["int_b1"], ["r1"], "Experience", "bank_integration_internship", "Architected an anti-corruption layer with FastAPI and SQLAlchemy 2.0 integrating core banking systems with modern payment rails, returning 202 Accepted responses out of band."),
        DraftBullet("b09", ["int_b2"], ["r1"], "Experience", "bank_integration_internship", "Built an idempotent fund transfer engine ensuring safe payment processing under network faults."),
        DraftBullet("b10", ["int_b3"], ["r1"], "Experience", "bank_integration_internship", "Designed a fail-closed anti-money laundering gateway screening transactions in real time."),
        # Projects (5 bullets: 2 + 2 + 1)
        DraftBullet("b11", ["pc_b01_event_sourcing"], ["r1"], "Projects", "peerchat_peer_discovery", "Developed an event-sourced peer discovery module handling node presence updates."),
        DraftBullet("b12", ["pc_b04_transport_consolidation"], ["r1"], "Projects", "peerchat_peer_discovery", "Unified transport communication layers to minimize latency overhead across network peers."),
        DraftBullet("b13", ["frd_b1"], ["r1"], "Projects", "fake_review_detection", "Implemented feature extraction pipelines to analyze textual patterns across review corpora."),
        DraftBullet("b14", ["frd_b2"], ["r1"], "Projects", "fake_review_detection", "Trained classification models detecting fraudulent submissions with high precision."),
        DraftBullet("b15", ["cm_b1"], ["r1"], "Projects", "campus_marketplace", "Engineered a relational database schema supporting concurrent item listings and order fulfillment."),
    ]
    return DraftResponse(
        atomic_requirements=[
            AtomicRequirement("r1", "distributed systems", "building high-throughput distributed systems", "must_have"),
        ],
        selected_evidence_ids=[b.evidence_ids[0] for b in bullets],
        amdocs_omission_ledger=[],
        section_order=["Experience", "Projects", "Technical Skills"],
        bullets=bullets,
    )


def test_validate_draft_response_success(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    # Should not raise
    validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_quote_not_in_jd_fails(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    bad_reqs = [AtomicRequirement("r1", "blockchain", "expert in web3 blockchain smart contracts", "must_have")]
    draft = dataclasses.replace(draft, atomic_requirements=bad_reqs)
    with pytest.raises(DraftValidationError, match="not an exact substring"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_invalid_evidence_id_fails(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    bad_bullets = list(draft.bullets)
    bad_bullets[0] = DraftBullet(
        "b01", ["non_existent_id"], ["r1"], "Experience", "amdocs_software_developer", "Some text."
    )
    draft = dataclasses.replace(draft, bullets=bad_bullets)
    with pytest.raises(DraftValidationError, match="unknown evidence_id"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_amdocs_missing_and_not_omitted_fails(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    # Drop am_b07 from bullets and leave omission ledger empty
    filtered_bullets = [b for b in draft.bullets if b.evidence_ids[0] != "am_b07_code_quality_gates"]
    draft = dataclasses.replace(draft, bullets=filtered_bullets)
    with pytest.raises(DraftValidationError, match="Canonical Amdocs bullet .* missing"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_amdocs_omitted_with_ledger_succeeds(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    filtered_bullets = [b for b in draft.bullets if b.evidence_ids[0] != "am_b07_code_quality_gates"]
    ledger = [AmdocsOmission("am_b07_code_quality_gates", "space", "Omitted to preserve space for project depth.")]
    draft = dataclasses.replace(draft, bullets=filtered_bullets, amdocs_omission_ledger=ledger)
    validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_numeric_token_invented_fails(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    bad_bullets = list(draft.bullets)
    bad_bullets[7] = DraftBullet(
        "b08", ["int_b1"], ["r1"], "Experience", "bank_integration_internship",
        "Architected an anti-corruption layer handling 999,999 daily transactions."
    )
    draft = dataclasses.replace(draft, bullets=bad_bullets)
    with pytest.raises(DraftValidationError, match="numeric token '999,999' not found in cited evidence"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_do_not_claim_kubernetes_fails(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    bad_bullets = list(draft.bullets)
    bad_bullets[0] = DraftBullet(
        "b01", ["am_b00_order_management_domain"], ["r1"], "Experience", "amdocs_software_developer",
        "Engineered order processing services using Kubernetes clusters."
    )
    draft = dataclasses.replace(draft, bullets=bad_bullets)
    with pytest.raises(DraftValidationError, match="prohibited do_not_claim term 'Kubernetes'"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_draft_malytech_capped_at_3_bullets(profile, valid_jd_text):
    draft = make_valid_draft(valid_jd_text)
    extra_b = DraftBullet("b16", ["int_b4"], ["r1"], "Experience", "bank_integration_internship", "Built automated reconciliations.")
    draft = dataclasses.replace(draft, bullets=list(draft.bullets) + [extra_b])
    with pytest.raises(DraftValidationError, match="capped at 3 bullets"):
        validate_draft_response(draft, valid_jd_text, profile, "backend")


def test_validate_audit_response_score_1_must_reject():
    dimensions = {
        "factual_fidelity": DimensionScore(1, "Hallucinated metrics."),
        "metric_fidelity": DimensionScore(3, "Accurate."),
        "technology_fidelity": DimensionScore(3, "Accurate."),
        "technical_guarantee_fidelity": DimensionScore(3, "Accurate."),
        "relevance": DimensionScore(3, "High."),
        "star_xyz_coherence": DimensionScore(3, "Clean XYZ."),
        "readability": DimensionScore(3, "Clear."),
        "recruiter_scan_quality": DimensionScore(3, "Strong."),
        "ai_slop_risk": DimensionScore(3, "Zero slop."),
    }
    # Verdict incorrectly marked ACCEPT despite score 1
    evals = [
        BulletAuditEvaluation("b01", dimensions, "ACCEPT", [])
    ]
    audit = AuditResponse(evals, "PASS")
    with pytest.raises(AuditValidationError, match="has score 1 must have verdict REJECT"):
        validate_audit_response(audit, ["b01"])


def test_validate_repair_response_invented_metric_fails(profile):
    evidence_by_id = {b.id: b for exp in profile.experience for b in exp.bullets}
    repair = RepairResponse([
        RepairedBullet("b08", "Engineered layer with 777,000 requests.")
    ])
    with pytest.raises(RepairValidationError, match="numeric token '777,000' not found"):
        validate_repair_response(repair, ["b08"], {"b08": ["int_b1"]}, evidence_by_id, profile)
