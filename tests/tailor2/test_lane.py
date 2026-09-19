"""End-to-end orchestration unit tests for Tailor2 lane."""

import json
import pytest
from pathlib import Path

from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.lane import run_tailor2_lane


@pytest.fixture
def valid_jd_file(tmp_path):
    jd_content = (
        "We are looking for a Software Development Engineer with experience building "
        "high-throughput distributed systems and data pipelines. Experience with Java, "
        "Python, SQL, Kafka, and cloud infrastructure required."
    )
    p = tmp_path / "sample_jd.txt"
    p.write_text(jd_content, encoding="utf-8")
    return p


def _make_valid_draft_json():
    # Valid draft response JSON string
    return json.dumps({
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
        ]
    })


def _make_passing_audit_json(bullet_ids):
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
    evals = [{"bullet_id": bid, "dimensions": dims, "verdict": "ACCEPT", "rejection_reasons": []} for bid in bullet_ids]
    return json.dumps({"evaluations": evals, "overall_verdict": "PASS"})


def test_lane_happy_path_exactly_two_calls(tmp_path, valid_jd_file):
    bullet_ids = [f"b{i:02d}" for i in range(1, 16)]
    fake_responses = {
        "draft": _make_valid_draft_json(),
        "audit": _make_passing_audit_json(bullet_ids),
    }

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses=fake_responses,
        trace_dir=tmp_path / "traces",
    )

    out_dir = tmp_path / "app_out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file,
        company="Acme Corp",
        title="Software Engineer",
        variant="backend",
        invoker=invoker,
        out_dir=out_dir,
    )

    assert result.success is True
    assert result.call_count == 2
    assert result.repair_performed is False
    assert (out_dir / "resume.pdf").exists()
    assert (out_dir / "draft.json").exists()
    assert (out_dir / "audit.json").exists()
    assert not (out_dir / "repair.json").exists()


def test_lane_repair_path_exactly_four_calls(tmp_path, valid_jd_file):
    bullet_ids = [f"b{i:02d}" for i in range(1, 16)]
    # First audit rejects b05
    dims_pass = {
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
    dims_fail = dict(dims_pass)
    dims_fail["ai_slop_risk"] = {"score": 1, "findings": "Cliché found."}

    evals = []
    for bid in bullet_ids:
        if bid == "b05":
            evals.append({"bullet_id": bid, "dimensions": dims_fail, "verdict": "REJECT", "rejection_reasons": ["Cliché"]})
        else:
            evals.append({"bullet_id": bid, "dimensions": dims_pass, "verdict": "ACCEPT", "rejection_reasons": []})

    audit_reject_json = json.dumps({"evaluations": evals, "overall_verdict": "REPAIR_REQUIRED"})

    repair_json = json.dumps({
        "repaired_bullets": [
            {
                "bullet_id": "b05",
                "text": "Structured partitioned SQL tables to automate data retention, reducing storage footprint by ~40% across production systems.",
            }
        ]
    })

    re_audit_pass_json = json.dumps({
        "evaluations": [
            {"bullet_id": "b05", "dimensions": dims_pass, "verdict": "ACCEPT", "rejection_reasons": []}
        ],
        "overall_verdict": "PASS",
    })

    fake_responses = {
        "draft": _make_valid_draft_json(),
        "audit": audit_reject_json,
        "repair": repair_json,
        "re_audit": re_audit_pass_json,
    }

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses=fake_responses,
        trace_dir=tmp_path / "traces",
    )

    out_dir = tmp_path / "app_out_repair"
    result = run_tailor2_lane(
        jd_path=valid_jd_file,
        company="Acme Corp",
        title="Software Engineer",
        variant="backend",
        invoker=invoker,
        out_dir=out_dir,
    )

    assert result.success is True
    assert result.call_count == 4
    assert result.repair_performed is True
    assert (out_dir / "resume.pdf").exists()
    assert (out_dir / "repair.json").exists()
    assert (out_dir / "re_audit.json").exists()


# Renamed from test_lane_fails_closed_if_re_audit_rejects: under the
# quality_core severity model (see src/tailor2/severity.py), a
# factual_fidelity=1 finding is FATAL_INTEGRITY, which can never be
# repaired without inventing evidence -- so the lane now fails closed at
# the FIRST audit (before repair is even attempted), not after a wasted
# repair+re-audit round trip. This is the intended behavior change from
# the "IMPORTANT ARCHITECTURAL CORRECTION" policy override: only
# AUTO_CORRECTABLE and REPAIRABLE_QUALITY findings ever reach repair.
def test_lane_fails_closed_on_fatal_factual_finding_before_repair(tmp_path, valid_jd_file):
    bullet_ids = [f"b{i:02d}" for i in range(1, 16)]
    dims_pass = {
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
    dims_fail = dict(dims_pass)
    dims_fail["factual_fidelity"] = {"score": 1, "findings": "Still inaccurate."}

    evals = []
    for bid in bullet_ids:
        if bid == "b05":
            evals.append({"bullet_id": bid, "dimensions": dims_fail, "verdict": "REJECT", "rejection_reasons": ["Inaccurate"]})
        else:
            evals.append({"bullet_id": bid, "dimensions": dims_pass, "verdict": "ACCEPT", "rejection_reasons": []})

    audit_reject_json = json.dumps({"evaluations": evals, "overall_verdict": "REPAIR_REQUIRED"})

    repair_json = json.dumps({
        "repaired_bullets": [
            {
                "bullet_id": "b05",
                "text": "Structured partitioned SQL tables to automate data retention, reducing storage footprint by ~40% across production systems.",
            }
        ]
    })

    re_audit_fail_json = json.dumps({
        "evaluations": [
            {"bullet_id": "b05", "dimensions": dims_fail, "verdict": "REJECT", "rejection_reasons": ["Still inaccurate"]}
        ],
        "overall_verdict": "REPAIR_REQUIRED",
    })

    fake_responses = {
        "draft": _make_valid_draft_json(),
        "audit": audit_reject_json,
        "repair": repair_json,
        "re_audit": re_audit_fail_json,
    }

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses=fake_responses,
        trace_dir=tmp_path / "traces",
    )

    out_dir = tmp_path / "app_out_failed_reaudit"
    result = run_tailor2_lane(
        jd_path=valid_jd_file,
        company="Acme Corp",
        title="Software Engineer",
        variant="backend",
        invoker=invoker,
        out_dir=out_dir,
    )

    assert result.success is True
    assert result.status == "NEEDS_HUMAN_REVIEW"
    # The last safe candidate survives the audit finding; no repair call is
    # needed after canonical wording restores the cited evidence.
    assert result.call_count == 2
    assert (out_dir / "resume.pdf").exists()
    assert (out_dir / "run_manifest.json").exists()
