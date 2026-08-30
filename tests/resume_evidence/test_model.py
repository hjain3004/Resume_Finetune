from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from src.resume_evidence.model import (
    AuthorityKind, CanonicalSourceRecord, ConfidenceLevel, DoctrineCandidate,
    EditorialDimension, EditorialRating, EmploymentInterval, EvidenceConfidence,
    ExperienceConfidence, OutcomeCandidate, OutcomeRecord, OutcomeTier,
    ResumeRepresentation, ResumeVersionAttribution, RoleFamily, SourceKind, SourceRecord,
)


@pytest.fixture
def valid_candidate() -> OutcomeCandidate:
    """Fixture: fully-populated OutcomeCandidate with synthetic data."""
    source = SourceRecord(
        source_id="src_001",
        url="https://example.com/resume1",
        title="Resume Example",
        retrieved_at=datetime(2026, 1, 15, 10, 30, 0),
        content_sha256="abc123def456",
        snapshot_file="snapshots/resume_001.html",
    )

    employment = EmploymentInterval(
        start_month="2022-01",
        end_month="2024-06",
    )

    internship = EmploymentInterval(
        start_month="2021-05",
        end_month="2021-08",
    )

    rating1 = EditorialRating(
        dimension=EditorialDimension.TECHNICAL_SPECIFICITY,
        score=8,
        explanation="Clear technical skills listed",
    )

    rating2 = EditorialRating(
        dimension=EditorialDimension.EARLY_CAREER_PRIORITIZATION,
        score=7,
        explanation="Good emphasis on relevant projects",
    )

    candidate = OutcomeCandidate(
        schema_version="m8q.resume_evidence.v1",
        reference_id="ref_001",
        source_kind=SourceKind.INDIVIDUAL_PUBLIC_STORY,
        sources=(source,),
        resume_source_id="src_001",
        outcome_source_id="outcome_001",
        layout_file="layouts/layout_001.json",
        layout_sha256="xyz789abc",
        role_family=RoleFamily.GENERAL_SWE,
        target_role="Senior Backend Engineer",
        target_level="Senior",
        graduation_month="2020-05",
        professional_intervals=(employment,),
        internship_intervals=(internship,),
        professional_experience_months=30,
        experience_confidence=ExperienceConfidence.EXACT,
        outcome_tier=OutcomeTier.FINAL_INTERVIEW,
        outcome_evidence_quote="Led development of core platform",
        outcome_evidence_confidence=EvidenceConfidence.PLATFORM_LOGGED,
        resume_representation=ResumeRepresentation.INDIVIDUAL,
        resume_version_attribution=ResumeVersionAttribution.EXACT,
        section_order=("experience", "education", "skills"),
        feature_tags=("python", "distributed_systems"),
        editorial_ratings=(rating1, rating2),
        limitations=("Resume may be outdated",),
    )

    return candidate


def test_outcome_candidate_is_frozen(valid_candidate: OutcomeCandidate) -> None:
    """Test that OutcomeCandidate is frozen and rejects mutations."""
    with pytest.raises(FrozenInstanceError):
        valid_candidate.target_role = "changed"  # type: ignore


def test_closed_enums_reject_unknown_values() -> None:
    """Test that enums reject unknown string values."""
    with pytest.raises(ValueError):
        OutcomeTier("oa")
