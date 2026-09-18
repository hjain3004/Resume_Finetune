"""Focused offline tests for Tailor2 render-fill optimization."""

from __future__ import annotations

from dataclasses import replace

from src.profile import load_profile
from src.render.lines import RenderedLine, RenderedPage
from src.render.parse import ParsedPdf, TextBox
from src.tailor2.models import AmdocsOmission, AtomicRequirement, DraftBullet, DraftResponse
from src.tailor2.render_fill import (
    LayoutState,
    OptimizationCandidate,
    RenderAttempt,
    RenderFillConfig,
    RenderMeasurement,
    build_compression_candidates,
    build_expansion_candidates,
    build_removal_candidates,
    build_richer_variant_candidates,
    build_shorter_variant_candidates,
    candidate_fingerprint,
    classify_layout,
    measure_rendered_layout,
    optimize_render_fill,
)
from src.tailor2.severity import RunStatus
from src.tailor2.validators import extract_numeric_tokens


def _profile():
    return load_profile("config/master_profile.yaml")


def _draft(profile, evidence_ids: list[str], *, texts: dict[str, str] | None = None):
    entries = {
        bullet.id: (entry, bullet)
        for entry in (*profile.experience, *profile.projects)
        for bullet in entry.bullets
    }
    bullets = []
    for index, evidence_id in enumerate(evidence_ids):
        entry, source = entries[evidence_id]
        bullets.append(
            DraftBullet(
                bullet_id=f"draft-{index}",
                evidence_ids=[evidence_id],
                supported_requirement_ids=["req-1"],
                section="Experience" if entry in profile.experience else "Projects",
                entry_id=entry.id,
                text=(texts or {}).get(evidence_id, source.phrasings.medium or source.phrasings.short),
            )
        )
    return DraftResponse(
        atomic_requirements=[AtomicRequirement("req-1", "Java", "Java")],
        selected_evidence_ids=list(evidence_ids),
        amdocs_omission_ledger=[],
        section_order=["Education", "Experience", "Projects", "Technical Skills"],
        bullets=bullets,
    )


def _measurement(
    *,
    remaining: float = 0.0,
    overflow: float = 0.0,
    pages: int = 1,
    font: float = 10.0,
    margin: float = 20.0,
    collisions: tuple[str, ...] = (),
    outside: tuple[str, ...] = (),
    compression: bool = False,
):
    return RenderMeasurement(
        page_count=pages,
        page_width=612.0,
        page_height=792.0,
        usable_bottom=14.4,
        usable_top=777.6,
        occupied_bottom=14.4 + remaining,
        occupied_top=777.6 - remaining,
        occupied_vertical_extent=763.2 - 2 * remaining,
        remaining_usable_space=remaining,
        overflow_pt=overflow,
        section_collisions=collisions,
        text_outside_page_bounds=outside,
        minimum_font_pt=font,
        minimum_margin_pt=margin,
        excessive_compression=compression,
        render_succeeded=True,
    )


def _attempt(candidate_id, draft, state, *, evidence=0.0, clarity=0.0, measurement=None, iteration=0, safe=True):
    return RenderAttempt(
        candidate_id=candidate_id,
        iteration=iteration,
        draft=draft,
        measurement=measurement or _measurement(remaining=0.0),
        state=state,
        factual_integrity=safe,
        evidence_value=evidence,
        clarity_score=clarity,
        candidate_fingerprint=candidate_fingerprint(draft),
        tex_path=f"{candidate_id}.tex",
        pdf_path=f"{candidate_id}.pdf",
    )


def test_expansion_selects_high_value_nonredundant_evidence_and_rejects_filler():
    profile = _profile()
    draft = _draft(profile, ["am_b00_order_management_domain"])
    candidates = build_expansion_candidates(
        draft,
        profile,
        [
            {"evidence_id": "pc_b01_event_sourcing", "strength": 0.9, "likely_section": "Projects", "requirement_ids": ["req-1"], "estimated_line_cost": 1},
            {"evidence_id": "pc_b04_transport_consolidation", "strength": 0.1, "likely_section": "Projects", "requirement_ids": [], "estimated_line_cost": 1},
            {"evidence_id": "not-in-profile", "strength": 1.0, "likely_section": "Projects"},
        ],
    )
    assert [item.evidence_ids for item in candidates] == [("pc_b01_event_sourcing",)]


def test_prohibited_and_unsupported_evidence_never_enters_expansion():
    profile = _profile()
    draft = _draft(profile, ["am_b00_order_management_domain"])
    candidates = build_expansion_candidates(
        draft,
        profile,
        [
            {"evidence_id": "unknown", "strength": 1.0, "omission_reason": "prohibited Kubernetes claim"},
            {"evidence_id": "also-unknown", "strength": 1.0, "omission_reason": "unsupported"},
        ],
    )
    assert candidates == []


def test_canonical_richer_and_shorter_variants_preserve_evidence_and_numbers():
    profile = _profile()
    evidence_id = "am_b01_dlq_consolidation"
    source = next(b for entry in profile.experience for b in entry.bullets if b.id == evidence_id)
    draft = _draft(profile, [evidence_id], texts={evidence_id: source.phrasings.short})
    richer = build_richer_variant_candidates(draft, profile)
    assert richer
    assert richer[0].draft.bullets[0].evidence_ids == [evidence_id]
    assert extract_numeric_tokens(richer[0].draft.bullets[0].text) == extract_numeric_tokens(source.phrasings.medium or source.phrasings.short)

    long_draft = _draft(profile, [evidence_id], texts={evidence_id: source.phrasings.long or source.phrasings.medium or source.phrasings.short})
    shorter = build_shorter_variant_candidates(long_draft, profile)
    assert shorter
    assert shorter[0].draft.bullets[0].evidence_ids == [evidence_id]


def test_omission_ledger_is_consumed_when_covered_evidence_is_added():
    profile = _profile()
    evidence_id = "am_b00_order_management_domain"
    draft = _draft(profile, ["pc_b01_event_sourcing"])
    draft = replace(draft, amdocs_omission_ledger=[AmdocsOmission(evidence_id, "space", "later page fill")])
    candidate = build_expansion_candidates(
        draft,
        profile,
        [{"evidence_id": evidence_id, "strength": 0.9, "likely_section": "Experience", "requirement_ids": ["req-1"]}],
    )[0]
    assert all(item.evidence_id != evidence_id for item in candidate.draft.amdocs_omission_ledger)


def test_measurement_distinguishes_clean_underfill_overflow_and_collisions():
    assert classify_layout(_measurement(remaining=50)) is LayoutState.MEANINGFUL_UNDERFILL
    assert classify_layout(_measurement(remaining=10)) is LayoutState.CLEAN_FIT
    assert classify_layout(_measurement(overflow=8)) is LayoutState.SLIGHT_OVERFLOW
    assert classify_layout(_measurement(collisions=("overlap",))) is LayoutState.COLLISION_OR_CLIPPING
    assert classify_layout(_measurement(font=7.0, compression=True)) is LayoutState.UNREADABLY_COMPRESSED
    assert classify_layout(_measurement(pages=2, overflow=300)) is LayoutState.SUBSTANTIAL_OVERFLOW


def test_real_measurement_uses_page_bounds_and_font_size():
    boxes = (TextBox("Name", 14.4, 740.0, 100.0, 752.0, 0), TextBox("bad", -2.0, 10.0, 20.0, 20.0, 0))
    parsed = ParsedPdf(boxes, 792.0, 612.0, 100, 1)
    line = RenderedLine("Name", 14.4, 740.0, 100.0, 752.0, 0, 11.0, 9.0, ())
    pages = (RenderedPage(0, 612.0, 792.0, (line,)),)
    measurement = measure_rendered_layout(None, parsed, pages)
    assert measurement.text_outside_page_bounds
    assert measurement.minimum_font_pt == 11.0


def test_overflow_tries_shorter_before_removal_and_preserves_metrics():
    profile = _profile()
    draft = _draft(profile, ["am_b01_dlq_consolidation", "pc_b01_event_sourcing"])
    compression = build_compression_candidates(draft, profile)
    assert compression[0].action == "shorten"
    assert any(item.action == "remove" for item in compression)
    assert all(item.stage == 0 for item in compression if item.action == "shorten")


def test_lowest_priority_eligible_bullet_is_removed_without_hardcoded_id():
    profile = _profile()
    draft = _draft(profile, ["int_b1", "int_b2", "pc_b01_event_sourcing"])
    removals = build_removal_candidates(draft, profile)
    assert removals
    assert removals[0].draft.bullets[0].bullet_id != removals[0].candidate_id.removeprefix("remove:")
    assert removals[0].reason.startswith("lowest-priority")


def test_worse_iteration_does_not_replace_best_and_budget_is_bounded():
    calls = []
    initial = "a"
    candidates = [
        OptimizationCandidate("expensive", "expand", "b", value_score=1.0),
        OptimizationCandidate("second", "expand", "c", value_score=0.5),
    ]

    def render(draft, iteration, candidate):
        calls.append(candidate.candidate_id if candidate else "initial")
        if candidate is None:
            return _attempt("initial", draft, LayoutState.MINOR_UNDERFILL, measurement=_measurement(remaining=20), iteration=iteration)
        return _attempt(candidate.candidate_id, draft, LayoutState.MEANINGFUL_UNDERFILL, evidence=candidate.value_score, measurement=_measurement(remaining=50), iteration=iteration)

    result = optimize_render_fill(initial, render, expansion_candidates=candidates, config=RenderFillConfig(max_render_iterations=2, max_expansion_attempts=2))
    assert calls == ["initial", "expensive"]
    assert result.best_attempt.candidate_id == "initial"
    assert result.iterations[0].accepted is False


def test_clean_fit_and_94_percent_fill_are_not_rejected():
    measurement = _measurement(remaining=10)
    assert measurement.fill_ratio > 0.94
    assert classify_layout(measurement) is LayoutState.CLEAN_FIT
    result = optimize_render_fill(
        "draft",
        lambda draft, iteration, candidate: _attempt("initial", draft, LayoutState.CLEAN_FIT, measurement=measurement),
    )
    assert result.status is RunStatus.ACCEPTED


def test_render_failure_preserves_latest_safe_artifact_and_unresolved_layout_is_review():
    safe_measurement = _measurement(remaining=50)
    candidate = OptimizationCandidate("bad", "expand", "new", value_score=1.0)

    def failing_render(draft, iteration, candidate):
        if candidate is None:
            return _attempt("initial", draft, LayoutState.MEANINGFUL_UNDERFILL, measurement=safe_measurement)
        raise RuntimeError("renderer unavailable")

    preserved = optimize_render_fill("draft", failing_render, expansion_candidates=[candidate])
    assert preserved.best_attempt.candidate_id == "initial"
    assert preserved.status is RunStatus.ACCEPTED_WITH_WARNINGS
    assert preserved.warnings

    review = optimize_render_fill(
        "draft",
        lambda draft, iteration, candidate: _attempt("initial", draft, LayoutState.SLIGHT_OVERFLOW, measurement=_measurement(overflow=5)),
    )
    assert review.status is RunStatus.NEEDS_HUMAN_REVIEW
    assert review.best_attempt is not None


def test_resume_skips_completed_candidate_and_manifest_records_decisions():
    calls = []
    candidate = OptimizationCandidate("done", "expand", "new", value_score=1.0)
    resume_best = _attempt("initial", "draft", LayoutState.CLEAN_FIT)

    def render(draft, iteration, candidate):
        calls.append(candidate.candidate_id if candidate else "initial")
        return _attempt("unexpected", draft, LayoutState.CLEAN_FIT)

    result = optimize_render_fill(
        "draft",
        render,
        expansion_candidates=[candidate],
        resume_manifest={"iterations": [{"candidate_id": "done"}]},
        resume_best=resume_best,
    )
    assert calls == []
    assert result.to_manifest_dict()["iterations"] == []


def test_provider_and_bullet_edit_budgets_are_explicit():
    assert RenderFillConfig(max_provider_rewrites=0, max_bullet_edits=8).max_token_edit_distance_ratio == 0.15
    try:
        RenderFillConfig(max_token_edit_distance_ratio=1.1)
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("invalid token budget accepted")
