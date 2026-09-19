from __future__ import annotations

import dataclasses
import json

from src.profile import load_profile
from src.tailor2.models import DraftResponse, parse_draft_response
from src.tailor2.sanitize import build_safe_fallback, sanitize_draft


def _draft(payload: dict) -> DraftResponse:
    return parse_draft_response(json.dumps(payload))


def test_selected_evidence_missing_from_draft_is_added_to_omission_ledger(
    fake_draft_response_backend,
):
    draft = dict(fake_draft_response_backend)
    draft["bullets"] = [
        bullet for bullet in draft["bullets"] if bullet["evidence_ids"] != ["am_b03_audit_trail"]
    ]
    draft["amdocs_omission_ledger"] = []

    result = sanitize_draft(
        _draft(draft),
        load_profile("config/master_profile.yaml"),
        "backend",
        selected_evidence_ids={"am_b03_audit_trail"},
    )

    assert [item.evidence_id for item in result.draft.amdocs_omission_ledger if item.evidence_id == "am_b03_audit_trail"]
    assert result.quarantine_ledger == []
    assert result.model_calls_required is False


def test_soft_section_overflow_is_retained_for_later_render_fill(fake_draft_response_backend):
    draft = dict(fake_draft_response_backend)
    draft["bullets"].append(
        {
            "bullet_id": "b16",
            "evidence_ids": ["int_b4"],
            "supported_requirement_ids": ["req_1"],
            "section": "Experience",
            "entry_id": "bank_integration_internship",
            "text": "Built reconciliation workflows for provider settlement records.",
        }
    )

    result = sanitize_draft(_draft(draft), load_profile("config/master_profile.yaml"), "backend")

    assert len([b for b in result.draft.bullets if b.entry_id == "bank_integration_internship"]) == 4
    assert any("overflow" in warning for warning in result.warnings)


def test_unsupported_outcome_is_quarantined_and_canonical_wording_restored(
    fake_draft_response_backend,
):
    draft = dict(fake_draft_response_backend)
    draft["bullets"][10]["text"] = (
        "Implemented WebSocket-based peer discovery for resilient distributed membership."
    )

    result = sanitize_draft(
        _draft(draft),
        load_profile("config/master_profile.yaml"),
        "backend",
        audit_findings={"b11": ["unsupported outcome phrase: resilient distributed membership"]},
    )

    repaired = next(b for b in result.draft.bullets if b.bullet_id == "b11")
    assert "resilient distributed membership" not in repaired.text
    assert any(item.location == "bullets[b11]" for item in result.quarantine_ledger)


def test_altered_metric_is_replaced_without_discarding_other_bullets(fake_draft_response_backend):
    draft = dict(fake_draft_response_backend)
    draft["bullets"][1]["text"] = "Consolidated 999 dead-letter topics and cut topic sprawl by 999%."

    result = sanitize_draft(_draft(draft), load_profile("config/master_profile.yaml"), "backend")

    repaired = next(b for b in result.draft.bullets if b.bullet_id == "b02")
    assert "999" not in repaired.text
    assert len(result.draft.bullets) == len(draft["bullets"])
    assert any(item.location == "bullets[b02]" for item in result.quarantine_ledger)


def test_unusable_draft_gets_minimum_safe_fallback():
    profile = load_profile("config/master_profile.yaml")
    empty = DraftResponse([], [], [], ["Experience", "Projects", "Technical Skills"], [])

    result = sanitize_draft(empty, profile, "backend")
    fallback = build_safe_fallback(profile, "backend")

    assert result.safe_fallback_used is True
    assert result.draft.bullets
    assert result.draft.bullets == fallback.bullets
    assert all(b.evidence_ids for b in result.draft.bullets)


def test_sanitization_preserves_order_and_does_not_deduplicate(fake_draft_response_backend):
    draft = _draft(fake_draft_response_backend)
    result = sanitize_draft(draft, load_profile("config/master_profile.yaml"), "backend")

    assert [b.bullet_id for b in result.draft.bullets] == [b.bullet_id for b in draft.bullets]
    assert result.draft.selected_evidence_ids == draft.selected_evidence_ids


def test_sanitization_result_is_immutable_at_the_boundary(fake_draft_response_backend):
    draft = _draft(fake_draft_response_backend)
    result = sanitize_draft(draft, load_profile("config/master_profile.yaml"), "backend")

    assert dataclasses.is_dataclass(result)
    assert isinstance(result.draft, DraftResponse)
