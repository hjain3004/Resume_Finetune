"""Unit tests for Tailor2 data models and contracts."""

import json
import pytest

from src.tailor2.models import (
    AmdocsOmission,
    AtomicRequirement,
    AuditResponse,
    BulletAuditEvaluation,
    DimensionScore,
    DraftBullet,
    DraftResponse,
    ModelContractError,
    RepairResponse,
    RepairedBullet,
    parse_audit_response,
    parse_draft_response,
    parse_repair_response,
)


def test_parse_draft_response_valid():
    raw_json = json.dumps({
        "atomic_requirements": [
            {
                "id": "req_1",
                "term": "Distributed Systems",
                "quote": "experience with distributed systems",
                "importance": "must_have",
            }
        ],
        "selected_evidence_ids": ["int_b1", "am_b01_dlq_consolidation"],
        "amdocs_omission_ledger": [
            {
                "evidence_id": "am_b00_order_management_domain",
                "category": "space",
                "reason": "Omitted to fit one-page constraint.",
            }
        ],
        "section_order": ["Experience", "Projects", "Technical Skills"],
        "bullets": [
            {
                "bullet_id": "b01",
                "evidence_ids": ["int_b1"],
                "supported_requirement_ids": ["req_1"],
                "section": "Experience",
                "entry_id": "bank_integration_internship",
                "text": "Engineered an anti-corruption layer integrating legacy core systems with 15,000 daily transactions.",
            }
        ],
    })

    draft = parse_draft_response(raw_json)
    assert len(draft.atomic_requirements) == 1
    assert draft.atomic_requirements[0].id == "req_1"
    assert draft.selected_evidence_ids == ["int_b1", "am_b01_dlq_consolidation"]
    assert len(draft.amdocs_omission_ledger) == 1
    assert draft.amdocs_omission_ledger[0].evidence_id == "am_b00_order_management_domain"
    assert len(draft.bullets) == 1
    assert draft.bullets[0].bullet_id == "b01"


def test_parse_draft_response_strips_markdown_fences():
    raw_text = """```json
    {
      "atomic_requirements": [],
      "selected_evidence_ids": [],
      "amdocs_omission_ledger": [],
      "section_order": ["Experience"],
      "bullets": []
    }
    ```"""
    draft = parse_draft_response(raw_text)
    assert draft.section_order == ["Experience"]


def test_parse_draft_response_missing_keys_raises():
    raw_text = json.dumps({"atomic_requirements": []})
    with pytest.raises(ModelContractError, match="missing required key"):
        parse_draft_response(raw_text)


def test_parse_audit_response_valid():
    dimensions = {
        "factual_fidelity": {"score": 3, "findings": "Accurate."},
        "metric_fidelity": {"score": 3, "findings": "Matches 15,000."},
        "technology_fidelity": {"score": 3, "findings": "Accurate."},
        "technical_guarantee_fidelity": {"score": 3, "findings": "Accurate."},
        "relevance": {"score": 3, "findings": "High."},
        "star_xyz_coherence": {"score": 3, "findings": "Clean XYZ."},
        "readability": {"score": 3, "findings": "Clear."},
        "recruiter_scan_quality": {"score": 3, "findings": "Strong."},
        "ai_slop_risk": {"score": 3, "findings": "Zero slop."},
    }
    raw_json = json.dumps({
        "evaluations": [
            {
                "bullet_id": "b01",
                "dimensions": dimensions,
                "verdict": "ACCEPT",
                "rejection_reasons": [],
            }
        ],
        "overall_verdict": "PASS",
    })
    audit = parse_audit_response(raw_json)
    assert audit.overall_verdict == "PASS"
    assert len(audit.evaluations) == 1
    assert audit.evaluations[0].bullet_id == "b01"
    assert audit.evaluations[0].verdict == "ACCEPT"
    assert audit.evaluations[0].dimensions["factual_fidelity"].score == 3


def test_parse_audit_response_missing_dimension_raises():
    raw_json = json.dumps({
        "evaluations": [
            {
                "bullet_id": "b01",
                "dimensions": {
                    "factual_fidelity": {"score": 3, "findings": "Accurate."}
                },
                "verdict": "ACCEPT",
                "rejection_reasons": [],
            }
        ],
        "overall_verdict": "PASS",
    })
    with pytest.raises(ModelContractError, match="missing dimension"):
        parse_audit_response(raw_json)


def test_parse_repair_response_valid():
    raw_json = json.dumps({
        "repaired_bullets": [
            {
                "bullet_id": "b05",
                "text": "Automated data retention pipelines with partitioned SQL tables, reducing storage footprint by ~40%.",
            }
        ]
    })
    repair = parse_repair_response(raw_json)
    assert len(repair.repaired_bullets) == 1
    assert repair.repaired_bullets[0].bullet_id == "b05"
