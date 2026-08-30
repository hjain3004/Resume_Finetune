from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from src.resume_evidence.model import OutcomeTier, ResumeRepresentation, RoleFamily
from src.resume_evidence.serde import EvidenceValidationError
from src.resume_evidence.store import EvidenceBank, load_evidence_bank, lookup_outcomes


def test_missing_bank_returns_empty_bank(tmp_path):
    assert load_evidence_bank(tmp_path / "bank") == EvidenceBank.empty()


def test_lookup_filters_are_advisory_and_stably_sorted(valid_outcome_record):
    other = dataclasses.replace(
        valid_outcome_record,
        reference_id="aaa_other",
        role_family=RoleFamily.ML_DATA,
        professional_experience_months=30,
        outcome_tier=OutcomeTier.OFFER,
        resume_representation=ResumeRepresentation.COMPOSITE,
    )
    bank = EvidenceBank(
        outcomes=(valid_outcome_record, other),
        doctrine=(),
        patterns=(),
        corpus_version="0.1.0",
        approved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        approval_report_sha256="a" * 64,
    )
    assert [item.reference_id for item in lookup_outcomes(bank)] == [
        "aaa_other",
        valid_outcome_record.reference_id,
    ]
    assert lookup_outcomes(bank, role_family=RoleFamily.ML_DATA) == (other,)
    assert lookup_outcomes(bank, max_months=10) == (valid_outcome_record,)
    assert lookup_outcomes(bank, outcome_tier=OutcomeTier.OFFER) == (other,)
    assert lookup_outcomes(
        bank, representation=ResumeRepresentation.COMPOSITE
    ) == (other,)


@pytest.mark.parametrize("value", [-1, 37, True])
def test_lookup_rejects_invalid_month_limit(valid_outcome_record, value):
    bank = dataclasses.replace(EvidenceBank.empty(), outcomes=(valid_outcome_record,))
    with pytest.raises(EvidenceValidationError):
        lookup_outcomes(bank, max_months=value)

