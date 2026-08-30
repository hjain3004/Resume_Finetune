"""Resume evidence domain model: frozen contracts for outcomes, doctrine, and patterns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

SCHEMA_VERSION = "m8q.resume_evidence.v1"


class SourceKind(str, Enum):
    """Source categorization for evidence."""

    HUNTR = "huntr"
    INDIVIDUAL_PUBLIC_STORY = "individual_public_story"
    OTHER_APPROVED = "other_approved"


class OutcomeTier(str, Enum):
    """Interview/hiring progress level."""

    RECRUITER_SCREEN = "recruiter_screen"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER = "offer"


class EvidenceConfidence(str, Enum):
    """How an outcome was established."""

    PLATFORM_LOGGED = "platform_logged"
    PUBLISHER_ASSERTED = "publisher_asserted"
    SELF_REPORTED = "self_reported"


class ConfidenceLevel(str, Enum):
    """General confidence/quality assessment."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResumeRepresentation(str, Enum):
    """How the resume was sourced/presented."""

    INDIVIDUAL = "individual"
    ANONYMIZED = "anonymized"
    RECONSTRUCTED = "reconstructed"
    COMPOSITE = "composite"


class ResumeVersionAttribution(str, Enum):
    """Provenance of the resume version."""

    EXACT = "exact"
    PUBLISHER_LINKED = "publisher_linked"
    AMBIGUOUS = "ambiguous"


class ExperienceConfidence(str, Enum):
    """How the employment history was established."""

    EXACT = "exact"
    DERIVED = "derived"
    AMBIGUOUS = "ambiguous"


class RoleFamily(str, Enum):
    """Role category for targeting."""

    GENERAL_SWE = "general_swe"
    BACKEND_PLATFORM = "backend_platform"
    ML_DATA = "ml_data"
    JAVA_ENTERPRISE = "java_enterprise"
    OTHER_RELEVANT = "other_relevant"


class AuthorityKind(str, Enum):
    """Source of principle/doctrine authority."""

    AUTHOR_FIRST_PARTY = "author_first_party"
    PRACTITIONER_FIRST_PARTY = "practitioner_first_party"
    INSTITUTIONAL = "institutional"
    SECONDARY = "secondary"


class DoctrineUse(str, Enum):
    """Permitted use cases for a doctrine/principle."""

    RUBRIC_CANDIDATE = "rubric_candidate"
    PATTERN_CONTEXT = "pattern_context"
    ADVISORY_ONLY = "advisory_only"


class EditorialDimension(str, Enum):
    """Resume quality evaluation criteria."""

    EARLY_CAREER_PRIORITIZATION = "early_career_prioritization"
    TECHNICAL_SPECIFICITY = "technical_specificity"
    OWNERSHIP_CLARITY = "ownership_clarity"
    CLAIM_CREDIBILITY = "claim_credibility"
    PROJECT_SELECTION = "project_selection"
    ROLE_ALIGNMENT = "role_alignment"
    SCANABILITY = "scanability"
    PROFESSIONAL_VOICE = "professional_voice"


@dataclass(frozen=True)
class SourceRecord:
    """Tracked source with local snapshot reference."""

    source_id: str
    url: str
    title: str
    retrieved_at: datetime
    content_sha256: str
    snapshot_file: str


@dataclass(frozen=True)
class CanonicalSourceRecord:
    """Source reference without local snapshot (for approved corpus)."""

    source_id: str
    url: str
    title: str
    retrieved_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class EmploymentInterval:
    """Continuous employment or internship period."""

    start_month: str
    end_month: str


@dataclass(frozen=True)
class EditorialRating:
    """Editorial score on one dimension."""

    dimension: EditorialDimension
    score: int
    explanation: str


@dataclass(frozen=True)
class OutcomeCandidate:
    """Proposed outcome record before approval (with full local state)."""

    schema_version: str
    reference_id: str
    source_kind: SourceKind
    sources: tuple[SourceRecord, ...]
    resume_source_id: str
    outcome_source_id: str
    layout_file: str | None
    layout_sha256: str | None
    role_family: RoleFamily
    target_role: str
    target_level: str
    graduation_month: str | None
    professional_intervals: tuple[EmploymentInterval, ...]
    internship_intervals: tuple[EmploymentInterval, ...]
    professional_experience_months: int
    experience_confidence: ExperienceConfidence
    outcome_tier: OutcomeTier
    outcome_evidence_quote: str
    outcome_evidence_confidence: EvidenceConfidence
    resume_representation: ResumeRepresentation
    resume_version_attribution: ResumeVersionAttribution
    section_order: tuple[str, ...]
    feature_tags: tuple[str, ...]
    editorial_ratings: tuple[EditorialRating, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class OutcomeRecord:
    """Approved outcome record (normalized to canonical sources)."""

    schema_version: str
    reference_id: str
    source_kind: SourceKind
    sources: tuple[CanonicalSourceRecord, ...]
    resume_source_id: str
    outcome_source_id: str
    layout_sha256: str | None
    role_family: RoleFamily
    target_role: str
    target_level: str
    graduation_month: str | None
    professional_intervals: tuple[EmploymentInterval, ...]
    internship_intervals: tuple[EmploymentInterval, ...]
    professional_experience_months: int
    experience_confidence: ExperienceConfidence
    outcome_tier: OutcomeTier
    outcome_evidence_quote: str
    outcome_evidence_confidence: EvidenceConfidence
    resume_representation: ResumeRepresentation
    resume_version_attribution: ResumeVersionAttribution
    section_order: tuple[str, ...]
    feature_tags: tuple[str, ...]
    editorial_ratings: tuple[EditorialRating, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class DoctrineCandidate:
    """Proposed doctrine/principle before approval (with full local state)."""

    schema_version: str
    doctrine_id: str
    source: SourceRecord
    authority_kind: AuthorityKind
    principle: str
    early_career_applicability: str
    affected_dimensions: tuple[EditorialDimension, ...]
    supporting_quote: str
    conflicts_or_qualifications: tuple[str, ...]
    confidence: ConfidenceLevel
    permitted_uses: tuple[DoctrineUse, ...]


@dataclass(frozen=True)
class DoctrineRecord:
    """Approved doctrine/principle record (normalized to canonical source)."""

    schema_version: str
    doctrine_id: str
    source: CanonicalSourceRecord
    authority_kind: AuthorityKind
    principle: str
    early_career_applicability: str
    affected_dimensions: tuple[EditorialDimension, ...]
    supporting_quote: str
    conflicts_or_qualifications: tuple[str, ...]
    confidence: ConfidenceLevel
    permitted_uses: tuple[DoctrineUse, ...]


@dataclass(frozen=True)
class PatternCard:
    """Reusable pattern or anti-pattern extracted from outcomes and doctrine."""

    schema_version: str
    pattern_id: str
    text: str
    anti_pattern: bool
    role_families: tuple[RoleFamily, ...]
    outcome_record_ids: tuple[str, ...]
    doctrine_record_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence: ConfidenceLevel
    prohibited_uses: tuple[str, ...]
    candidate_dimensions: tuple[EditorialDimension, ...]


@dataclass(frozen=True)
class CanonicalCorpus:
    """Complete approved corpus: outcomes, doctrine, and extracted patterns."""

    schema_version: str
    corpus_version: str
    approved_at: datetime
    approval_report_sha256: str
    outcomes: tuple[OutcomeRecord, ...]
    doctrine: tuple[DoctrineRecord, ...]
    patterns: tuple[PatternCard, ...]
