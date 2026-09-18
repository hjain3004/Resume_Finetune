"""Shared test fixtures for tests/tailor2/."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


@pytest.fixture
def sample_jd_text() -> str:
    return (
        "We are looking for a Software Development Engineer with experience building "
        "high-throughput distributed systems and data pipelines. Experience with Java, "
        "Python, SQL, Kafka, and cloud infrastructure required."
    )


@pytest.fixture
def fake_draft_response_backend() -> dict:
    return {
        "atomic_requirements": [
            {
                "id": "req_1",
                "term": "distributed systems",
                "quote": "building high-throughput distributed systems",
                "importance": "must_have",
            }
        ],
        "selected_evidence_ids": [
            "am_b00_order_management_domain",
            "am_b01_dlq_consolidation",
            "am_b02_row_level_entitlement",
            "am_b03_audit_trail",
            "am_b04_data_retention",
            "am_b05_test_automation",
            "am_b07_code_quality_gates",
            "int_b1", "int_b2", "int_b3",
            "pc_b01_event_sourcing", "pc_b04_transport_consolidation",
            "frd_b1", "frd_b2", "cm_b1"
        ],
        "amdocs_omission_ledger": [],
        "section_order": ["Experience", "Projects", "Technical Skills"],
        "bullets": [
            {"bullet_id": "b01", "evidence_ids": ["am_b00_order_management_domain"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Engineered order processing services in Java handling high-volume transactions."},
            {"bullet_id": "b02", "evidence_ids": ["am_b01_dlq_consolidation"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Consolidated 862 dead-letter topics across distributed clusters into shared queues, cutting topic sprawl by 70%."},
            {"bullet_id": "b03", "evidence_ids": ["am_b02_row_level_entitlement"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Built row-level access control filters enforcing security boundaries across datasets."},
            {"bullet_id": "b04", "evidence_ids": ["am_b03_audit_trail"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Implemented asynchronous audit logging capturing system state transitions."},
            {"bullet_id": "b05", "evidence_ids": ["am_b04_data_retention"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Structured partitioned SQL tables to automate data retention, reducing storage footprint by ~40%."},
            {"bullet_id": "b06", "evidence_ids": ["am_b05_test_automation"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Automated integration test suites covering ~500 regression cases across deployment environments."},
            {"bullet_id": "b07", "evidence_ids": ["am_b07_code_quality_gates"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "amdocs_software_developer", "text": "Configured static analysis code quality gates reducing defect leakage before deployment."},
            {"bullet_id": "b08", "evidence_ids": ["int_b1"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "bank_integration_internship", "text": "Architected an anti-corruption layer with FastAPI and SQLAlchemy 2.0 integrating core banking systems with modern payment rails, returning 202 Accepted responses out of band."},
            {"bullet_id": "b09", "evidence_ids": ["int_b2"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "bank_integration_internship", "text": "Built an idempotent fund transfer engine ensuring safe payment processing under network faults."},
            {"bullet_id": "b10", "evidence_ids": ["int_b3"], "supported_requirement_ids": ["req_1"], "section": "Experience", "entry_id": "bank_integration_internship", "text": "Designed a fail-closed anti-money laundering gateway screening transactions in real time."},
            {"bullet_id": "b11", "evidence_ids": ["pc_b01_event_sourcing"], "supported_requirement_ids": ["req_1"], "section": "Projects", "entry_id": "peerchat_peer_discovery", "text": "Developed an event-sourced peer discovery module handling node presence updates."},
            {"bullet_id": "b12", "evidence_ids": ["pc_b04_transport_consolidation"], "supported_requirement_ids": ["req_1"], "section": "Projects", "entry_id": "peerchat_peer_discovery", "text": "Unified transport communication layers to minimize latency overhead across network peers."},
            {"bullet_id": "b13", "evidence_ids": ["frd_b1"], "supported_requirement_ids": ["req_1"], "section": "Projects", "entry_id": "fake_review_detection", "text": "Implemented feature extraction pipelines to analyze textual patterns across review corpora."},
            {"bullet_id": "b14", "evidence_ids": ["frd_b2"], "supported_requirement_ids": ["req_1"], "section": "Projects", "entry_id": "fake_review_detection", "text": "Trained classification models detecting fraudulent submissions with high precision."},
            {"bullet_id": "b15", "evidence_ids": ["cm_b1"], "supported_requirement_ids": ["req_1"], "section": "Projects", "entry_id": "campus_marketplace", "text": "Engineered a relational database schema supporting concurrent item listings and order fulfillment."},
        ],
    }


@pytest.fixture
def fake_audit_response_pass() -> dict:
    dims = {
        "factual_fidelity": {"score": 3, "findings": "OK"},
        "metric_fidelity": {"score": 3, "findings": "OK"},
        "technology_fidelity": {"score": 3, "findings": "OK"},
        "technical_guarantee_fidelity": {"score": 3, "findings": "OK"},
        "relevance": {"score": 3, "findings": "OK"},
        "star_xyz_coherence": {"score": 3, "findings": "OK"},
        "readability": {"score": 3, "findings": "OK"},
        "recruiter_scan_quality": {"score": 3, "findings": "OK"},
        "ai_slop_risk": {"score": 3, "findings": "OK"},
    }
    evals = [
        {"bullet_id": f"b{i:02d}", "dimensions": dims, "verdict": "ACCEPT", "rejection_reasons": []}
        for i in range(1, 16)
    ]
    return {"evaluations": evals, "overall_verdict": "PASS"}
