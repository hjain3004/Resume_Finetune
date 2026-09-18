"""Unit tests for Tailor2 rendering and L7 validation."""

import pytest
from pathlib import Path

from src.profile import load_profile
from src.tailor2.models import DraftBullet, DraftResponse, AtomicRequirement
from src.tailor2.render import compile_draft_to_pdf, render_draft_to_latex, render_doc_from_draft_response


@pytest.fixture
def profile():
    return load_profile("config/master_profile.yaml")


@pytest.fixture
def sample_draft():
    bullets = [
        # Amdocs (7 bullets)
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
        # Projects (5 bullets)
        DraftBullet("b11", ["pc_b01_event_sourcing"], ["r1"], "Projects", "peerchat_peer_discovery", "Developed an event-sourced peer discovery module handling node presence updates."),
        DraftBullet("b12", ["pc_b04_transport_consolidation"], ["r1"], "Projects", "peerchat_peer_discovery", "Unified transport communication layers to minimize latency overhead across network peers."),
        DraftBullet("b13", ["frd_b1"], ["r1"], "Projects", "fake_review_detection", "Implemented feature extraction pipelines to analyze textual patterns across review corpora."),
        DraftBullet("b14", ["frd_b2"], ["r1"], "Projects", "fake_review_detection", "Trained classification models detecting fraudulent submissions with high precision."),
        DraftBullet("b15", ["cm_b1"], ["r1"], "Projects", "campus_marketplace", "Engineered a relational database schema supporting concurrent item listings and order fulfillment."),
    ]
    return DraftResponse(
        atomic_requirements=[
            AtomicRequirement("r1", "distributed systems", "distributed systems", "must_have")
        ],
        selected_evidence_ids=[b.evidence_ids[0] for b in bullets],
        amdocs_omission_ledger=[],
        section_order=["Experience", "Projects", "Technical Skills"],
        bullets=bullets,
    )


def test_render_doc_from_draft_response(profile, sample_draft):
    doc = render_doc_from_draft_response(sample_draft, profile)
    assert doc.identity["name"] == profile.identity["name"]
    assert len(doc.education) == len(profile.education)
    assert len(doc.experience) == 2  # Amdocs & MalyTech
    assert len(doc.projects) == 3    # PeerChat, FRD, Campus Marketplace
    all_bullets = doc.all_bullets()
    assert len(all_bullets) == 15
    assert all_bullets[0].text.startswith("Engineered order processing services")


def test_render_draft_to_latex(profile, sample_draft):
    tex_code = render_draft_to_latex(sample_draft, profile, Path("profile/template.tex"))
    assert r"\documentclass" in tex_code
    assert "Himanshu Jain" in tex_code
    assert "Amdocs" in tex_code
    assert "MalyTech" in tex_code
    assert "Kubernetes" not in tex_code


def test_compile_draft_to_pdf(tmp_path, profile, sample_draft):
    from src.render.lines import parse_rendered_lines
    tex_path, pdf_path, doc = compile_draft_to_pdf(sample_draft, profile, tmp_path)
    assert tex_path.exists()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    pages = parse_rendered_lines(pdf_path)
    assert len(pages) == 1
