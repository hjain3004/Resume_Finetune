"""Tests for the quality_core severity model, dual model identity, the
whole-résumé audit projection, and the repair-first/fail-closed policy.

All model responses are recorded/fake -- no live provider calls (per the
task's "Use recorded/fake responses" requirement).
"""

from __future__ import annotations

import json
from pathlib import Path

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
    # Canonical title passes without correction
    res_canonical = resolve_displayed_title("amdocs_software_developer", "Software Developer", "Software Developer")
    assert res_canonical.was_auto_corrected is False
    assert res_canonical.resolution_status == "canonical"
    assert res_canonical.final_title == "Software Developer"

    # Documented approved variant passes without correction
    res_approved = resolve_displayed_title(
        "bank_integration_internship", "Software Engineering Intern", "Software Engineering Intern"
    )
    assert res_approved.was_auto_corrected is False
    assert res_approved.final_title == "Software Engineering Intern"


def test_quality_core_title_mismatch_end_to_end_continues_the_run(tmp_path, valid_jd_file, fake_draft_response_backend):
    """A drafter that proposes a non-canonical, non-approved title for an
    entry does not halt the lane -- render.py uses the corrected title and
    the run completes with NEEDS_HUMAN_REVIEW (preserving the artifact)."""
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
    assert manifest["status"] == "NEEDS_HUMAN_REVIEW"


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
    # Canonically supported profile skills are not removed; weakly demonstrated skills generate advisories
    from src.tailor2.audit_projection import SkillTermProjection, check_skills_advisories, weakly_demonstrated_skill_terms
    import dataclasses as _dc

    weakly = weakly_demonstrated_skill_terms(projection)
    assert len(weakly) > 0  # some profile skills are not cited in this draft's bullets
    advisories = check_skills_advisories(projection)
    assert len(advisories) == len(weakly)

    # Now inject an unsupported term (e.g. Kubernetes / ungrounded skill)
    injected_skills = dict(projection.skills)
    injected_skills["developer_tools"] = list(injected_skills.get("developer_tools", [])) + [
        SkillTermProjection(term="Kubernetes", canonical_support=False, selected_demonstration=False, supported=False)
    ]
    proj_with_unsupported = _dc.replace(projection, skills=injected_skills)

    unsupported = unsupported_skill_terms(proj_with_unsupported)
    assert len(unsupported) == 1
    assert unsupported[0][1] == "Kubernetes"

    corrected, corrections = apply_deterministic_auto_corrections(proj_with_unsupported)
    assert any("Kubernetes" in c for c in corrections)
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
    assert any("Skills advisory" in w for w in manifest["warnings"])
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


# ===========================================================================
# Skills Integration Tests (Correction 1: 4-Tier Skills Model & Semantic Aliases)
# ===========================================================================


def test_skills_canonically_supported_evidence_not_selected_for_bullet(profile, fake_draft_response_backend):
    """1. A Skill supported anywhere in canonical evidence remains eligible and is NOT
    removed solely because its supporting project or bullet was not selected."""
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    lang_terms = {s.term: s for s in projection.skills.get("languages", [])}
    assert "Java" in lang_terms
    assert lang_terms["Java"].canonical_support is True
    assert lang_terms["Java"].display_decision is True

    corrected, corrections = apply_deterministic_auto_corrections(projection)
    corrected_langs = [s.term for s in corrected.skills.get("languages", [])]
    assert "Java" in corrected_langs
    assert not any("Java" in c and "removed" in c for c in corrections)


def test_skills_support_through_selected_evidence(profile, fake_draft_response_backend):
    """2. Support through selected evidence: selected_demonstration is True when
    a selected bullet visibly cites the skill."""
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    db_terms = {s.term: s for s in projection.skills.get("databases", [])}
    assert "PostgreSQL" in db_terms
    assert db_terms["PostgreSQL"].canonical_support is True
    assert db_terms["PostgreSQL"].selected_demonstration is True
    assert "int_b2" in db_terms["PostgreSQL"].evidence_ids


def test_skills_supported_but_weakly_demonstrated_produces_only_advisory(profile, fake_draft_response_backend):
    """3. Supported but weakly demonstrated Skills produce only an advisory warning,
    never automatic removal or fatal rejection."""
    draft = _draft_from_fixture(fake_draft_response_backend)
    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    from src.tailor2.audit_projection import check_skills_advisories, weakly_demonstrated_skill_terms
    weakly = weakly_demonstrated_skill_terms(projection)
    assert len(weakly) > 0
    advisories = check_skills_advisories(projection)
    assert len(advisories) == len(weakly)
    assert all("Skills advisory" in a for a in advisories)

    from src.tailor2.validators import check_skills_evidence_integrity
    removals = check_skills_evidence_integrity(projection)
    assert len(removals) == 0


def test_skills_completely_unsupported_removed_or_repaired(profile, fake_draft_response_backend):
    """4. Completely unsupported Skills (e.g. Kubernetes, ungrounded terms) are
    detected as integrity defects and removed deterministically."""
    draft = _draft_from_fixture(fake_draft_response_backend)
    from src.tailor2.audit_projection import SkillTermProjection
    import dataclasses as _dc

    projection = build_resume_projection(
        draft, profile, "Acme", "SE", "backend", {"drafter": {}, "auditor": {}, "repair": {}, "re_audit": {}}
    )
    custom_skills = dict(projection.skills)
    custom_skills["developer_tools"] = list(custom_skills.get("developer_tools", [])) + [
        SkillTermProjection(term="Kubernetes", canonical_support=False, selected_demonstration=False, supported=False),
        SkillTermProjection(term="GraphQL", canonical_support=False, selected_demonstration=False, supported=False),
    ]
    proj_with_unsupported = _dc.replace(projection, skills=custom_skills)

    unsupported = unsupported_skill_terms(proj_with_unsupported)
    unsupported_terms = [term for _, term in unsupported]
    assert "Kubernetes" in unsupported_terms
    assert "GraphQL" in unsupported_terms

    corrected, corrections = apply_deterministic_auto_corrections(proj_with_unsupported)
    corrected_terms = [s.term for terms in corrected.skills.values() for s in terms]
    assert "Kubernetes" not in corrected_terms
    assert "GraphQL" not in corrected_terms
    assert any("Kubernetes" in c for c in corrections)
    assert any("GraphQL" in c for c in corrections)


def test_skills_postgres_postgresql_semantic_equivalence(profile):
    """5. Explicit semantic aliases such as Postgres and PostgreSQL resolve to the same supported concept."""
    from src.tailor2.audit_projection import _resolve_skills, get_skill_aliases
    aliases = get_skill_aliases("Postgres")
    assert "postgresql" in aliases
    assert "postgres" in aliases

    evidence_by_id = {}
    for exp in profile.experience:
        for b in exp.bullets:
            evidence_by_id[b.id] = b
    for proj in profile.projects:
        for b in proj.bullets:
            evidence_by_id[b.id] = b

    custom_skills = {"databases": ["Postgres"]}
    resolved = _resolve_skills(profile, evidence_by_id, {"int_b2"}, skills_by_category=custom_skills)
    postgres_proj = resolved["databases"][0]
    assert postgres_proj.canonical_support is True
    assert postgres_proj.selected_demonstration is True
    assert "int_b2" in postgres_proj.evidence_ids


def test_skills_selection_concerns_never_rejected_fatal(tmp_path, valid_jd_file, fake_draft_response_backend):
    """6. Skills selection concerns or weakly demonstrated skills never become REJECTED_FATAL."""
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
    assert result.status != RunStatus.REJECTED_FATAL.value
    assert result.out_pdf is not None and result.out_pdf.exists()


def test_skills_existing_factual_integrity_behavior_intact(tmp_path, valid_jd_file, fake_draft_response_backend):
    """7. Existing factual-integrity behavior remains intact: fabricated numbers still fail fatally."""
    draft = dict(fake_draft_response_backend)
    draft["bullets"][0]["text"] = "Engineered custom distributed system scaling by 9999%."
    invoker = Tailor2Invoker(
        provider="openai", model="fake-model", fake_responses={"draft": json.dumps(draft)}, trace_dir=tmp_path / "traces"
    )
    out_dir = tmp_path / "out"
    result = run_tailor2_lane(
        jd_path=valid_jd_file, company="Acme", title="SE", variant="backend", invoker=invoker, out_dir=out_dir
    )
    assert result.success is False
    assert result.status == RunStatus.REJECTED_FATAL.value


# ===========================================================================
# Title Provenance Tests (Correction 2: Amdocs Title Provenance Conflict)
# ===========================================================================


def test_title_exact_canonical_title_passes():
    """1. Exact canonical title passes with resolution_status='canonical'."""
    resolution = resolve_displayed_title("amdocs_software_developer", "Software Developer", "Software Developer")
    assert resolution.displayed_title == "Software Developer"
    assert resolution.resolution_status == "canonical"
    assert resolution.was_auto_corrected is False
    assert resolution.requires_human_review is False


def test_title_approved_display_variant_passes_with_provenance():
    """2. Explicitly approved display variant with verified provenance passes."""
    resolution = resolve_displayed_title(
        "bank_integration_internship",
        "Software Engineering Intern",
        "Intern",
        approved_variants=frozenset({"Software Engineering Intern"}),
    )
    assert resolution.displayed_title == "Software Engineering Intern"
    assert resolution.resolution_status == "approved_variant"
    assert resolution.was_auto_corrected is False
    assert resolution.requires_human_review is False


def test_title_unapproved_substitution_does_not_silently_pass():
    """3. Unapproved title substitution does not silently pass; routes to human review."""
    resolution = resolve_displayed_title("amdocs_software_developer", "Software Engineer", "Software Developer")
    assert resolution.displayed_title == "Software Developer"  # preserves canonical!
    assert resolution.resolution_status == "unresolved_conflict"
    assert resolution.was_auto_corrected is True
    assert resolution.requires_human_review is True
    assert "differs from canonical title" in resolution.authority_note


def test_title_recruiter_preference_not_rewriting_canonical_history():
    """4. Recruiter or drafter preference does not rewrite canonical history."""
    resolution = resolve_displayed_title(
        "amdocs_software_developer", "Senior Software Engineer", "Software Developer"
    )
    assert resolution.displayed_title == "Software Developer"
    assert resolution.resolution_status == "unresolved_conflict"
    assert resolution.was_auto_corrected is True


def test_title_conflicting_sources_produce_needs_human_review_not_fatal(tmp_path, valid_jd_file, fake_draft_response_backend):
    """5. Conflicting title sources produce NEEDS_HUMAN_REVIEW, not REJECTED_FATAL."""
    draft = dict(fake_draft_response_backend)
    draft["entry_title_overrides"] = {"amdocs_software_developer": "Software Engineer"}
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
    assert result.status == RunStatus.NEEDS_HUMAN_REVIEW.value
    assert result.status != RunStatus.REJECTED_FATAL.value


def test_title_artifact_preservation_during_title_review(tmp_path, valid_jd_file, fake_draft_response_backend):
    """6. Title review preserves the usable rendered résumé artifact."""
    draft = dict(fake_draft_response_backend)
    draft["entry_title_overrides"] = {"amdocs_software_developer": "Software Engineer"}
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
    assert manifest["status"] == "NEEDS_HUMAN_REVIEW"
    assert len(manifest["title_resolutions"]) > 0
    amdocs_res = next(r for r in manifest["title_resolutions"] if r["entry_id"] == "amdocs_software_developer")
    assert amdocs_res["displayed_title"] == "Software Developer"
    assert amdocs_res["resolution_status"] == "unresolved_conflict"


def test_title_no_amdocs_specific_production_rule():
    """7. No Amdocs-specific production rule: APPROVED_TITLE_VARIANTS has no Amdocs entry,
    and resolve_displayed_title has no branching on 'amdocs'."""
    from src.tailor2.title_policy import APPROVED_TITLE_VARIANTS
    assert "amdocs_software_developer" not in APPROVED_TITLE_VARIANTS
    import inspect
    from src.tailor2 import title_policy
    source = inspect.getsource(title_policy.resolve_displayed_title)
    assert "amdocs" not in source.lower()


def test_title_openai_fixtures_do_not_assert_unverified_title_as_fact():
    """8. OpenAI fixtures do not assert an unverified title as unquestionable fact."""
    cases_path = Path("tests/fixtures/tailor2/quality_regressions/cases.json")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    reg15_neg = next(c for c in cases if c["case_id"] == "reg_15_employer_title_tampering_neg")
    reg15_pos = next(c for c in cases if c["case_id"] == "reg_15_employer_title_tampering_pos")
    assert "Software Developer displayed when canonical or explicitly approved title is Software Engineer" not in reg15_neg["description"]
    assert "Software Developer displayed when canonical or explicitly approved title is Software Engineer" not in reg15_pos["description"]

    manifest_path = Path("tests/fixtures/tailor2/quality_regressions/openai_acceptance_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["employer_title_fidelity"]["amdocs"]["canonical_title"] == "Software Developer"
    assert "Software Engineer" in manifest["employer_title_fidelity"]["amdocs"]["prohibited_substitutions"]



def test_title_existing_approved_variant_backward_compatible():
    """9. TitleResolution maintains backward-compatible final_title property."""
    resolution = resolve_displayed_title("bank_integration_internship", "Software Engineering Intern", "Software Engineering Intern")
    assert resolution.final_title == resolution.displayed_title
    assert hasattr(resolution, "was_auto_corrected")
