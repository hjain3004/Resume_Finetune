"""Tests for the quality_core severity model, dual model identity, the
whole-résumé audit projection, and the repair-first/fail-closed policy.

All model responses are recorded/fake -- no live provider calls (per the
task's "Use recorded/fake responses" requirement).
"""

from __future__ import annotations

import json

import pytest

from src.profile import load_profile
from src.tailor2.audit_projection import build_resume_projection, unsupported_skill_terms
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.lane import run_tailor2_lane
from src.tailor2.models import DraftResponse, parse_draft_response
from src.tailor2.prompts import build_audit_prompt, build_re_audit_prompt
from src.tailor2.severity import RunStatus, Severity, dimension_severity, has_fatal_dimension
from src.tailor2.title_policy import resolve_displayed_title
from src.tailor2.validators import (
    apply_deterministic_auto_corrections,
    check_skills_evidence_integrity,
)

BULLET_DIMS = (
    "factual_fidelity",
    "metric_fidelity",
    "technology_fidelity",
    "technical_guarantee_fidelity",
    "relevance",
    "star_xyz_coherence",
    "readability",
    "recruiter_scan_quality",
    "ai_slop_risk",
)

WHOLE_RESUME_DIMS = (
    "metric_interpretability",
    "interview_defensibility",
    "whole_resume_positioning",
    "skills_evidence_integrity",
    "title_identity_fidelity",
    "mechanism_outcome_balance",
    "cross_bullet_repetition",
    "misleading_implication",
)


def _bullet_dims_pass() -> dict:
    return {d: {"score": 3, "findings": "OK"} for d in BULLET_DIMS}


def _whole_resume_pass() -> dict:
    return {"dimensions": {d: {"score": 3, "findings": "OK"} for d in WHOLE_RESUME_DIMS}, "verdict": "ACCEPT", "rejection_reasons": []}


def _passing_audit_json(bullet_ids: list[str], whole_resume: dict | None = None) -> str:
    evals = [{"bullet_id": bid, "dimensions": _bullet_dims_pass(), "verdict": "ACCEPT", "rejection_reasons": []} for bid in bullet_ids]
    payload = {"evaluations": evals, "overall_verdict": "PASS", "whole_resume": whole_resume or _whole_resume_pass()}
    return json.dumps(payload)


@pytest.fixture
def profile():
    return load_profile("config/master_profile.yaml")


@pytest.fixture
def valid_jd_file(tmp_path):
    content = (
        "We are looking for a Software Development Engineer with experience building "
        "high-throughput distributed systems and data pipelines. Experience with Java, "
        "Python, SQL, Kafka, and cloud infrastructure required."
    )
    p = tmp_path / "sample_jd.txt"
    p.write_text(content, encoding="utf-8")
    return p


def _draft_from_fixture(fake_draft_response_backend: dict) -> DraftResponse:
    return parse_draft_response(json.dumps(fake_draft_response_backend))


# ---------------------------------------------------------------------------
# 1. Title mismatch is corrected from canonical data, processing continues
#    (AUTO_CORRECTABLE per the architectural override -- not a rejection).
# ---------------------------------------------------------------------------


def test_quality_core_title_mismatch_is_auto_corrected_not_rejected(profile):
    exp = next(e for e in profile.experience if e.id == "amdocs_software_developer")
    resolution = resolve_displayed_title(exp.id, "Senior Staff Principal Engineer", exp.title)
    assert resolution.was_auto_corrected is True
    assert resolution.final_title == exp.title  # corrected back to canonical, not rejected


def test_quality_core_approved_title_variant_passes_without_correction():
    resolution = resolve_displayed_title("amdocs_software_developer", "Software Engineer", "Software Developer")
    assert resolution.was_auto_corrected is False
    assert resolution.final_title == "Software Engineer"


def test_quality_core_title_mismatch_end_to_end_continues_the_run(tmp_path, valid_jd_file, fake_draft_response_backend):
    """A drafter that proposes a non-canonical, non-approved title for an
    entry does not halt the lane -- render.py uses the corrected title and
    the run completes."""
    draft = dict(fake_draft_response_backend)
    draft["entry_title_overrides"] = {"amdocs_software_developer": "Chief Technology Officer"}
    bullet_ids = [b["bullet_id"] for b in draft["bullets"]]

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(draft), "audit": _passing_audit_json(bullet_ids)},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True
    assert result.out_pdf is not None and result.out_pdf.exists()
    manifest = json.loads(result.manifest_path.read_text())
    assert any("Chief Technology Officer" in c for c in manifest["auto_corrections"])
    assert manifest["status"] in ("ACCEPTED", "ACCEPTED_WITH_WARNINGS")


# ---------------------------------------------------------------------------
# 2/3. Undefined metric interpretability and stability-vs-accuracy findings
#    are recorded and block ACCEPT at the whole-résumé level (repair-tier,
#    not fatal).
# ---------------------------------------------------------------------------


def test_quality_core_undefined_metric_movement_blocks_whole_resume_accept():
    wr = _whole_resume_pass()
    wr["dimensions"]["metric_interpretability"] = {
        "score": 1,
        "findings": "'mean LLM scoring movement' has no defined denominator or baseline.",
    }
    wr["verdict"] = "REJECT"
    wr["rejection_reasons"] = ["undefined metric"]

    from src.tailor2.models import DimensionScore, WholeResumeEvaluation

    evaluation = WholeResumeEvaluation(
        dimensions={k: DimensionScore(**v) for k, v in wr["dimensions"].items()},
        verdict=wr["verdict"],
        rejection_reasons=wr["rejection_reasons"],
    )
    from src.tailor2.validators import classify_whole_resume_severity

    assert classify_whole_resume_severity(evaluation) == Severity.REPAIRABLE_QUALITY
    assert dimension_severity("metric_interpretability") == Severity.REPAIRABLE_QUALITY


def test_quality_core_stability_labeled_accuracy_is_a_repairable_finding():
    """Stability presented as accuracy without evidence is exactly the
    'misleading despite literally-true phrases' pattern -- classified
    REPAIRABLE_QUALITY (interview_defensibility / misleading_implication),
    never fatal, per the architectural override."""
    assert dimension_severity("interview_defensibility") == Severity.REPAIRABLE_QUALITY
    assert dimension_severity("misleading_implication") == Severity.REPAIRABLE_QUALITY
    assert not has_fatal_dimension(["interview_defensibility", "misleading_implication"])


# ---------------------------------------------------------------------------
# 4. Unsupported Skills term is removed/repaired WITHOUT rejecting the run
#    (AUTO_CORRECTABLE).
# ---------------------------------------------------------------------------


def test_quality_core_unsupported_skills_term_deterministically_removed(profile, fake_draft_response_backend):
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    unsupported = unsupported_skill_terms(projection)
    assert len(unsupported) > 0  # this fixture's evidence selection doesn't cover every profile skill

    corrected, corrections = apply_deterministic_auto_corrections(projection)
    assert len(corrections) == len(unsupported)
    # Every remaining skill in the corrected projection is supported.
    assert unsupported_skill_terms(corrected) == []


def test_quality_core_unsupported_skills_end_to_end_does_not_reject(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={
            "draft": json.dumps(fake_draft_response_backend),
            "audit": _passing_audit_json(bullet_ids),
        },
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True
    manifest = json.loads(result.manifest_path.read_text())
    assert len(manifest["auto_corrections"]) > 0
    assert manifest["status"] == "ACCEPTED_WITH_WARNINGS"


# ---------------------------------------------------------------------------
# 5. Cross-bullet repetition: the whole-résumé auditor must actually SEE
#    every bullet (not just one in isolation) to judge repetition.
# ---------------------------------------------------------------------------


def test_quality_core_whole_resume_projection_exposes_every_bullet_to_auditor(profile, fake_draft_response_backend):
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    prompt = build_audit_prompt("JD text", draft.bullets, {}, projection)
    # Every bullet's text -- not just the "current" one -- appears in the
    # prompt, so the auditor can compare wording across the whole résumé.
    for b in draft.bullets:
        assert b.text in prompt
    assert "cross_bullet_repetition" in prompt


# ---------------------------------------------------------------------------
# 6/7. Same-model draft/audit is disclosed+warned and continues; separate
#    model identities are persisted in the manifest.
# ---------------------------------------------------------------------------


def test_quality_core_same_model_disclosed_and_continues(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(fake_draft_response_backend), "audit": _passing_audit_json(bullet_ids)},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True  # same-model disclosure never halts the run
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["same_model_draft_and_audit"] is True
    assert any("NOT an independent cross-model review" in w for w in manifest["warnings"])


def test_quality_core_separate_model_identities_persisted(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    fake_responses = {"draft": json.dumps(fake_draft_response_backend), "audit": _passing_audit_json(bullet_ids)}
    drafter = Tailor2Invoker(provider="openai", model="drafter-model", fake_responses=fake_responses, trace_dir=tmp_path / "t1")
    auditor = Tailor2Invoker(provider="gemini", model="auditor-model", fake_responses=fake_responses, trace_dir=tmp_path / "t2")

    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file,
        company="Acme",
        title="SE",
        variant="backend",
        invoker=drafter,
        auditor_invoker=auditor,
        out_dir=out_dir,
    )
    assert result.success is True
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["drafter_provider"] == "openai" and manifest["drafter_model"] == "drafter-model"
    assert manifest["auditor_provider"] == "gemini" and manifest["auditor_model"] == "auditor-model"
    assert manifest["repair_provider"] == "gemini" and manifest["repair_model"] == "auditor-model"
    assert manifest["re_audit_provider"] == "gemini" and manifest["re_audit_model"] == "auditor-model"
    assert manifest["same_model_draft_and_audit"] is False
    assert not any("NOT an independent cross-model review" in w for w in manifest["warnings"])


# ---------------------------------------------------------------------------
# 8/9. Repair preserves evidence IDs and metrics; re-audit receives the
#    complete repaired résumé, not just the fragments.
# ---------------------------------------------------------------------------


def test_quality_core_repair_preserves_evidence_and_metrics_end_to_end(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    dims_fail = _bullet_dims_pass()
    dims_fail["ai_slop_risk"] = {"score": 1, "findings": "Buzzword-heavy."}
    evals = [
        {"bullet_id": bid, "dimensions": dims_fail if bid == "b02" else _bullet_dims_pass(), "verdict": "REJECT" if bid == "b02" else "ACCEPT", "rejection_reasons": ["slop"] if bid == "b02" else []}
        for bid in bullet_ids
    ]
    audit_json = json.dumps({"evaluations": evals, "overall_verdict": "REPAIR_REQUIRED", "whole_resume": _whole_resume_pass()})
    # b02's evidence is am_b01_dlq_consolidation citing "70%" -- a valid repair keeps that number.
    repair_json = json.dumps(
        {"repaired_bullets": [{"bullet_id": "b02", "text": "Consolidated 862 dead-letter topics into shared queues across distributed clusters, cutting sprawl by 70%."}]}
    )
    re_audit_json = _passing_audit_json(["b02"])

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={
            "draft": json.dumps(fake_draft_response_backend),
            "audit": audit_json,
            "repair": repair_json,
            "re_audit": re_audit_json,
        },
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True
    assert result.repair_performed is True
    repaired = json.loads((out_dir / "draft_repaired.json").read_text())
    b02 = next(b for b in repaired["bullets"] if b["bullet_id"] == "b02")
    assert b02["evidence_ids"] == ["am_b01_dlq_consolidation"]  # evidence id preserved through the splice
    assert "70%" in b02["text"]  # metric preserved


def test_quality_core_re_audit_prompt_carries_full_projection_not_just_fragment(profile, fake_draft_response_backend):
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    # Simulate: only b02 was repaired, but the re-audit prompt must still
    # show every OTHER bullet (the complete résumé), not just b02.
    prompt = build_re_audit_prompt("JD text", [], {}, {}, projection)
    other_bullet_ids = [b.bullet_id for b in draft.bullets if b.bullet_id != "b02"]
    assert other_bullet_ids  # sanity: fixture has more than one bullet
    for bid in other_bullet_ids:
        assert bid in prompt


# ---------------------------------------------------------------------------
# 10. A factually grounded but misleading implication forces a non-blind-
#    accept outcome (NEEDS_HUMAN_REVIEW under the severity override, since
#    misleading_implication is REPAIRABLE_QUALITY, not fatal) when it has
#    no single-bullet repair target.
# ---------------------------------------------------------------------------


def test_quality_core_misleading_implication_forces_human_review_not_blind_accept(
    tmp_path, valid_jd_file, fake_draft_response_backend
):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    wr = _whole_resume_pass()
    wr["dimensions"]["misleading_implication"] = {
        "score": 1,
        "findings": "Every literal claim is true, but the combined résumé implies senior technical leadership the candidate never held.",
    }
    wr["verdict"] = "REJECT"
    wr["rejection_reasons"] = ["misleading overall impression of seniority"]
    audit_json = json.dumps({"evaluations": [{"bullet_id": bid, "dimensions": _bullet_dims_pass(), "verdict": "ACCEPT", "rejection_reasons": []} for bid in bullet_ids], "overall_verdict": "PASS", "whole_resume": wr})

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(fake_draft_response_backend), "audit": audit_json},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    # NOT a blind accept, and NOT a fatal rejection: forced to human review,
    # with the rendered artifact still preserved.
    assert result.status == RunStatus.NEEDS_HUMAN_REVIEW.value
    assert result.success is True
    assert result.out_pdf is not None and result.out_pdf.exists()


# ---------------------------------------------------------------------------
# 11/12. AI-slop score=1 triggers repair (not fatal); an unresolved
#    stylistic issue produces NEEDS_HUMAN_REVIEW with a rendered artifact.
# ---------------------------------------------------------------------------


def test_quality_core_ai_slop_score_1_triggers_repair_not_fatal_rejection(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    dims_fail = _bullet_dims_pass()
    dims_fail["ai_slop_risk"] = {"score": 1, "findings": "Cliché-heavy."}
    evals = [
        {"bullet_id": bid, "dimensions": dims_fail if bid == "b03" else _bullet_dims_pass(), "verdict": "REJECT" if bid == "b03" else "ACCEPT", "rejection_reasons": ["slop"] if bid == "b03" else []}
        for bid in bullet_ids
    ]
    audit_json = json.dumps({"evaluations": evals, "overall_verdict": "REPAIR_REQUIRED", "whole_resume": _whole_resume_pass()})
    repair_json = json.dumps({"repaired_bullets": [{"bullet_id": "b03", "text": "Built row-level access control filters enforcing security boundaries across datasets."}]})
    re_audit_json = _passing_audit_json(["b03"])

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(fake_draft_response_backend), "audit": audit_json, "repair": repair_json, "re_audit": re_audit_json},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True
    assert result.repair_performed is True
    assert result.status in ("ACCEPTED", "ACCEPTED_WITH_WARNINGS")


def test_quality_core_unresolved_stylistic_issue_after_budget_needs_human_review_with_artifact(
    tmp_path, valid_jd_file, fake_draft_response_backend
):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    dims_fail = _bullet_dims_pass()
    dims_fail["readability"] = {"score": 1, "findings": "Awkward phrasing."}
    evals = [
        {"bullet_id": bid, "dimensions": dims_fail if bid == "b04" else _bullet_dims_pass(), "verdict": "REJECT" if bid == "b04" else "ACCEPT", "rejection_reasons": ["awkward"] if bid == "b04" else []}
        for bid in bullet_ids
    ]
    audit_json = json.dumps({"evaluations": evals, "overall_verdict": "REPAIR_REQUIRED", "whole_resume": _whole_resume_pass()})
    repair_json = json.dumps({"repaired_bullets": [{"bullet_id": "b04", "text": "Implemented asynchronous audit logging capturing system state transitions."}]})
    # Re-audit STILL rejects on the same repairable dimension -- repair
    # budget (default 1) is now exhausted.
    dims_still_fail = _bullet_dims_pass()
    dims_still_fail["readability"] = {"score": 1, "findings": "Still awkward."}
    re_audit_json = json.dumps({"evaluations": [{"bullet_id": "b04", "dimensions": dims_still_fail, "verdict": "REJECT", "rejection_reasons": ["still awkward"]}], "overall_verdict": "REPAIR_REQUIRED", "whole_resume": _whole_resume_pass()})

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(fake_draft_response_backend), "audit": audit_json, "repair": repair_json, "re_audit": re_audit_json},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.status == RunStatus.NEEDS_HUMAN_REVIEW.value
    assert result.success is True  # still delivers a usable artifact
    assert result.out_pdf is not None and result.out_pdf.exists()
    assert any("unresolved after repair budget" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 13. A missing requirement (e.g. React) becomes an ADVISORY_GAP, not a
#    pipeline halt.
# ---------------------------------------------------------------------------


def test_quality_core_missing_requirement_is_advisory_gap_not_a_halt(tmp_path, valid_jd_file, fake_draft_response_backend):
    draft = dict(fake_draft_response_backend)
    draft["atomic_requirements"] = draft["atomic_requirements"] + [
        {"id": "req_react", "term": "React", "quote": "Kafka, and cloud infrastructure", "importance": "must_have"}
    ]
    bullet_ids = [b["bullet_id"] for b in draft["bullets"]]
    # No bullet supports req_react -- the profile genuinely has no React evidence.

    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(draft), "audit": _passing_audit_json(bullet_ids)},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is True  # a missing capability never halts the pipeline
    manifest = json.loads(result.manifest_path.read_text())
    assert any("req_react" in g for g in manifest["advisory_gaps"])
    assert manifest["status"] == "ACCEPTED_WITH_WARNINGS"


# ---------------------------------------------------------------------------
# 14/15. A fabricated metric and an unresolved evidence id both still fail
#    fatally -- these are the deterministic FATAL_INTEGRITY checks, which
#    this task explicitly preserves.
# ---------------------------------------------------------------------------


def test_quality_core_fabricated_metric_fails_fatally(tmp_path, valid_jd_file, fake_draft_response_backend):
    draft = dict(fake_draft_response_backend)
    draft["bullets"][1]["text"] = "Consolidated dead-letter topics, cutting sprawl by 999%."  # not in evidence
    invoker = Tailor2Invoker(
        provider="openai", model="fake-model", fake_responses={"draft": json.dumps(draft)}, trace_dir=tmp_path / "traces"
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is False
    assert result.status == RunStatus.REJECTED_FATAL.value
    assert (out_dir / "rejected" / "run_manifest.json").exists()


def test_quality_core_unresolved_evidence_id_fails_fatally(tmp_path, valid_jd_file, fake_draft_response_backend):
    draft = dict(fake_draft_response_backend)
    draft["bullets"][1]["evidence_ids"] = ["totally_made_up_evidence_id"]
    invoker = Tailor2Invoker(
        provider="openai", model="fake-model", fake_responses={"draft": json.dumps(draft)}, trace_dir=tmp_path / "traces"
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is False
    assert result.status == RunStatus.REJECTED_FATAL.value


# ---------------------------------------------------------------------------
# 16/12(call-behavior). Existing happy-path/repair-path call counts remain
#    bounded and deterministic (regression guard for the whole rewrite).
# ---------------------------------------------------------------------------


def test_quality_core_happy_path_is_exactly_two_calls(tmp_path, valid_jd_file, fake_draft_response_backend):
    bullet_ids = [b["bullet_id"] for b in fake_draft_response_backend["bullets"]]
    invoker = Tailor2Invoker(
        provider="openai",
        model="fake-model",
        fake_responses={"draft": json.dumps(fake_draft_response_backend), "audit": _passing_audit_json(bullet_ids)},
        trace_dir=tmp_path / "traces",
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.call_count == 2
    assert result.repair_performed is False
