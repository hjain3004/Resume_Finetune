"""Bundle integrity and admission policy for the offline resume evidence bank.

This module is the deterministic gate between a *staged* candidate bundle (local
snapshots + full provenance) and a *canonical* record that may enter the approved
corpus. Nothing here touches the network, SQLite, or YAML; callers hand in parsed
domain objects (``src.resume_evidence.serde``) plus a ``bundle_dir`` on disk.

Design decisions worth stating explicitly:

* **Resume section detection.** A resume snapshot is "recognizable" when at least
  ``MIN_RESUME_SECTIONS`` distinct headings from ``RESUME_SECTION_HEADINGS`` appear,
  each on its own line. Markdown ``#`` prefixes, a trailing ``:`` and surrounding
  ``*`` emphasis are tolerated; matching is case-insensitive. This is a structural
  smoke test ("is this actually a resume?"), not a quality judgement.

* **Role-family relevance.** ``RELEVANT_ROLE_FAMILIES`` is every current member of
  ``RoleFamily``; the enum is curated to hold only relevant technical families
  (``OTHER_RELEVANT`` included by name) and has no "irrelevant" member. Rule 3's
  role-family branch is therefore unreachable today. It is kept as an explicit
  gate: a future non-technical ``RoleFamily`` member is treated as irrelevant
  unless it is added to this set deliberately.

* **Weak outcomes are unrepresentable.** ``OutcomeTier`` only encodes
  recruiter-screen-or-stronger tiers; automatic-OA, resume-view, and
  "got responses" outcomes cannot be parsed, so admission rule 4 always accepts
  once rules 1-3 pass.

* **Privacy.** ``to_outcome_record`` / ``to_doctrine_record`` drop every private
  path (``snapshot_file`` on each source, ``layout_file``) structurally by
  building ``CanonicalSourceRecord`` objects and omitting the fields; only public
  URLs, hashes, bounded evidence, and annotations survive into canonical form.
"""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from src.resume_evidence.experience import professional_experience_months
from src.resume_evidence.model import (
    CanonicalSourceRecord,
    SCHEMA_VERSION,
    DoctrineCandidate,
    DoctrineRecord,
    EditorialDimension,
    ExperienceConfidence,
    OutcomeCandidate,
    OutcomeRecord,
    PatternCard,
    ResumeVersionAttribution,
    RoleFamily,
    SourceRecord,
)
from src.resume_evidence.serde import EvidenceValidationError

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "auth",
        "authorization",
        "password",
        "passwd",
        "secret",
        "session",
        "cookie",
    }
)

# Bounded evidence excerpts: long enough to actually support a claim, short enough
# to stay inside the copyright ceiling (design §12). Matches company_bank policy.
MIN_QUOTE_WORDS = 4
MAX_QUOTE_WORDS = 25

# Post-graduation professional experience ceiling for early-career admission (§7).
MAX_PROFESSIONAL_MONTHS = 36

_HEX = frozenset("0123456789abcdef")

RESUME_SECTION_HEADINGS = frozenset(
    {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "education",
        "projects",
        "personal projects",
        "academic projects",
        "skills",
        "technical skills",
        "summary",
        "professional summary",
        "objective",
        "certifications",
        "awards",
        "publications",
        "leadership",
        "activities",
        "coursework",
        "relevant coursework",
        "achievements",
    }
)
MIN_RESUME_SECTIONS = 2

# Every curated RoleFamily member is a relevant technical family (see module docstring).
RELEVANT_ROLE_FAMILIES = frozenset(RoleFamily)


class AdmissionStatus(str, Enum):
    """Staging outcome for an admission evaluation."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of :func:`evaluate_admission`.

    ``NEEDS_REVIEW`` and ``REJECTED`` are permitted in the staging report but
    forbidden from canonical promotion (that gate is enforced downstream).
    """

    status: AdmissionStatus
    reasons: tuple[str, ...]
    computed_experience_months: int


# machine-stable reason codes
REASON_AMBIGUOUS_EXPERIENCE = "ambiguous_experience"
REASON_AMBIGUOUS_RESUME_ATTRIBUTION = "ambiguous_resume_attribution"
REASON_EXPERIENCE_OVER_CAP = "experience_over_36_months"
REASON_IRRELEVANT_ROLE_FAMILY = "irrelevant_role_family"
REASON_RECRUITER_SCREEN_WITHIN_CAP = "recruiter_screen_or_stronger_within_cap"
REASON_UNCLASSIFIED = "unclassified_outcome"


# --------------------------------------------------------------------------- #
# URL safety
# --------------------------------------------------------------------------- #
def _check_url_safety(url: str) -> None:
    """Reject non-HTTPS, userinfo, IP-literal hosts, and credential-bearing keys."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EvidenceValidationError(f"source URL must use https: {url!r}")
    if parts.username or parts.password or "@" in parts.netloc:
        raise EvidenceValidationError(f"source URL must not carry userinfo: {url!r}")

    host = parts.hostname
    if not host:
        raise EvidenceValidationError(f"source URL has no host: {url!r}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise EvidenceValidationError(f"source URL host must not be an IP literal: {url!r}")

    for key, _ in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in SENSITIVE_QUERY_KEYS:
            raise EvidenceValidationError(
                f"source URL has sensitive query key {key!r}: {url!r}"
            )
    for key, _ in parse_qsl(parts.fragment, keep_blank_values=True):
        if key.casefold() in SENSITIVE_QUERY_KEYS:
            raise EvidenceValidationError(
                f"source URL fragment carries credentials: {url!r}"
            )


# --------------------------------------------------------------------------- #
# snapshot integrity
# --------------------------------------------------------------------------- #
def _load_snapshot(bundle_dir: Path, source: SourceRecord) -> str:
    """Return the UTF-8 text of ``source``'s snapshot after verifying its hash.

    Enforces: 64 lowercase-hex ``content_sha256``; the resolved snapshot path
    lies strictly beneath ``<bundle_dir>/sources/`` (no ``..``, absolute, or
    symlink escape); the file decodes as UTF-8; SHA-256 of the exact bytes on
    disk equals ``content_sha256``.
    """
    sha = source.content_sha256
    if len(sha) != 64 or any(ch not in _HEX for ch in sha):
        raise EvidenceValidationError(
            f"content_sha256 must be 64 lowercase hex chars: {source.source_id!r}"
        )

    sources_root = (Path(bundle_dir) / "sources").resolve()
    snap_path = (Path(bundle_dir) / source.snapshot_file).resolve()
    if snap_path == sources_root or not snap_path.is_relative_to(sources_root):
        raise EvidenceValidationError(
            f"snapshot path escapes sources/: {source.snapshot_file!r}"
        )
    if not snap_path.is_file():
        raise EvidenceValidationError(
            f"snapshot file is missing: {source.snapshot_file!r}"
        )

    raw = snap_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceValidationError(
            f"snapshot is not valid UTF-8: {source.snapshot_file!r}"
        ) from exc

    if hashlib.sha256(raw).hexdigest() != sha:
        raise EvidenceValidationError(
            f"snapshot hash mismatch for source {source.source_id!r}"
        )
    return text


# --------------------------------------------------------------------------- #
# evidence anchoring
# --------------------------------------------------------------------------- #
def _check_quote_anchored(quote: str, snapshot_text: str, label: str) -> None:
    words = quote.split()
    if not MIN_QUOTE_WORDS <= len(words) <= MAX_QUOTE_WORDS:
        raise EvidenceValidationError(
            f"{label} must be {MIN_QUOTE_WORDS}-{MAX_QUOTE_WORDS} words "
            f"(got {len(words)})"
        )
    if quote not in snapshot_text:
        raise EvidenceValidationError(
            f"{label} is not a literal substring of its declared snapshot"
        )


def _recognized_resume_sections(text: str) -> set[str]:
    found: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("#").strip().strip("*").strip()
        line = line.rstrip(":").strip()
        folded = line.casefold()
        if folded in RESUME_SECTION_HEADINGS:
            found.add(folded)
    return found


def _check_schema_version(value: str, field: str) -> None:
    if value != SCHEMA_VERSION:
        raise EvidenceValidationError(
            f"{field}.schema_version: unsupported value {value!r}"
        )


def _check_optional_layout(candidate: OutcomeCandidate, bundle_dir: Path) -> None:
    if (candidate.layout_file is None) != (candidate.layout_sha256 is None):
        raise EvidenceValidationError(
            "layout_file and layout_sha256 must appear together"
        )
    if candidate.layout_file is None:
        return
    root = Path(bundle_dir).resolve()
    layout = (Path(bundle_dir) / candidate.layout_file).resolve()
    if layout == root or not layout.is_relative_to(root) or not layout.is_file():
        raise EvidenceValidationError(
            f"layout path escapes the bundle or is missing: {candidate.layout_file!r}"
        )
    digest = candidate.layout_sha256 or ""
    if (
        len(digest) != 64
        or any(character not in _HEX for character in digest)
        or hashlib.sha256(layout.read_bytes()).hexdigest() != digest
    ):
        raise EvidenceValidationError("layout hash mismatch")


# --------------------------------------------------------------------------- #
# outcome bundle validation
# --------------------------------------------------------------------------- #
def _check_editorial_complete(candidate: OutcomeCandidate) -> None:
    dims = [rating.dimension for rating in candidate.editorial_ratings]
    if len(dims) != len(EditorialDimension) or set(dims) != set(EditorialDimension):
        raise EvidenceValidationError(
            "editorial_ratings must cover each of the 8 editorial dimensions exactly once"
        )
    for rating in candidate.editorial_ratings:
        if rating.score not in (1, 2, 3):
            raise EvidenceValidationError(
                f"editorial rating score for {rating.dimension.value!r} must be 1-3 "
                f"(got {rating.score})"
            )


def _recompute_months(candidate: OutcomeCandidate) -> int:
    if candidate.graduation_month is None:
        return candidate.professional_experience_months
    return professional_experience_months(
        candidate.professional_intervals, candidate.graduation_month
    )


def validate_outcome_bundle(candidate: OutcomeCandidate, bundle_dir: Path) -> None:
    """Raise :class:`EvidenceValidationError` on any structural/evidence failure.

    Checks, in order: source-id resolution; per-source URL safety and snapshot
    hash/path/UTF-8 integrity; editorial completeness; recorded limitations;
    stored-vs-recomputed experience equality; outcome-quote anchoring; resume
    section structure.
    """
    bundle_dir = Path(bundle_dir)
    _check_schema_version(candidate.schema_version, "outcome")

    by_id: dict[str, SourceRecord] = {}
    for source in candidate.sources:
        if source.source_id in by_id:
            raise EvidenceValidationError(
                f"duplicate source_id in candidate.sources: {source.source_id!r}"
            )
        by_id[source.source_id] = source
    for field, ref in (
        ("resume_source_id", candidate.resume_source_id),
        ("outcome_source_id", candidate.outcome_source_id),
    ):
        if ref not in by_id:
            raise EvidenceValidationError(
                f"{field} does not resolve within candidate.sources: {ref!r}"
            )

    snapshot_text: dict[str, str] = {}
    for source in candidate.sources:
        _check_url_safety(source.url)
        snapshot_text[source.source_id] = _load_snapshot(bundle_dir, source)
    _check_optional_layout(candidate, bundle_dir)

    _check_editorial_complete(candidate)

    if not candidate.limitations:
        raise EvidenceValidationError("source limitations must be recorded (§8)")

    if candidate.graduation_month is None:
        if candidate.experience_confidence is not ExperienceConfidence.AMBIGUOUS:
            raise EvidenceValidationError(
                "graduation_month is required unless experience_confidence is ambiguous"
            )
    else:
        recomputed = professional_experience_months(
            candidate.professional_intervals, candidate.graduation_month
        )
        if recomputed != candidate.professional_experience_months:
            raise EvidenceValidationError(
                f"professional_experience_months "
                f"{candidate.professional_experience_months} != deterministic "
                f"recomputation {recomputed}"
            )

    _check_quote_anchored(
        candidate.outcome_evidence_quote,
        snapshot_text[candidate.outcome_source_id],
        "outcome_evidence_quote",
    )

    sections = _recognized_resume_sections(snapshot_text[candidate.resume_source_id])
    if len(sections) < MIN_RESUME_SECTIONS:
        raise EvidenceValidationError(
            "resume snapshot lacks recognizable resume section structure "
            f"(found {sorted(sections)})"
        )


# --------------------------------------------------------------------------- #
# admission
# --------------------------------------------------------------------------- #
def evaluate_admission(candidate: OutcomeCandidate) -> AdmissionDecision:
    """Deterministic staging verdict; assumes ``validate_outcome_bundle`` passed."""
    months = _recompute_months(candidate)

    ambiguity: list[str] = []
    if candidate.experience_confidence is ExperienceConfidence.AMBIGUOUS:
        ambiguity.append(REASON_AMBIGUOUS_EXPERIENCE)
    if candidate.resume_version_attribution is ResumeVersionAttribution.AMBIGUOUS:
        ambiguity.append(REASON_AMBIGUOUS_RESUME_ATTRIBUTION)
    if ambiguity:
        return AdmissionDecision(AdmissionStatus.NEEDS_REVIEW, tuple(ambiguity), months)

    if months > MAX_PROFESSIONAL_MONTHS:
        return AdmissionDecision(
            AdmissionStatus.REJECTED, (REASON_EXPERIENCE_OVER_CAP,), months
        )

    if candidate.role_family not in RELEVANT_ROLE_FAMILIES:
        return AdmissionDecision(
            AdmissionStatus.REJECTED, (REASON_IRRELEVANT_ROLE_FAMILY,), months
        )

    if 0 <= months <= MAX_PROFESSIONAL_MONTHS:
        # OutcomeTier only encodes recruiter-screen-or-stronger tiers.
        return AdmissionDecision(
            AdmissionStatus.ACCEPTED, (REASON_RECRUITER_SCREEN_WITHIN_CAP,), months
        )

    return AdmissionDecision(
        AdmissionStatus.NEEDS_REVIEW, (REASON_UNCLASSIFIED,), months
    )


# --------------------------------------------------------------------------- #
# doctrine bundle validation
# --------------------------------------------------------------------------- #
def validate_doctrine_bundle(record: DoctrineCandidate, bundle_dir: Path) -> None:
    """Raise :class:`EvidenceValidationError` on any doctrine integrity failure."""
    _check_schema_version(record.schema_version, "doctrine")
    if not record.early_career_applicability.strip():
        raise EvidenceValidationError(
            "doctrine early_career_applicability must be non-empty"
        )
    if len(record.affected_dimensions) < 1:
        raise EvidenceValidationError(
            "doctrine must name at least one affected dimension"
        )
    if len(record.permitted_uses) < 1:
        raise EvidenceValidationError("doctrine must name at least one permitted use")

    _check_url_safety(record.source.url)
    snapshot_text = _load_snapshot(Path(bundle_dir), record.source)
    _check_quote_anchored(
        record.supporting_quote, snapshot_text, "doctrine supporting_quote"
    )


# --------------------------------------------------------------------------- #
# pattern cards
# --------------------------------------------------------------------------- #
def validate_pattern_card(
    card: PatternCard, outcome_ids: set[str], doctrine_ids: set[str]
) -> None:
    """Require a sufficient, resolvable evidentiary basis for a pattern card."""
    _check_schema_version(card.schema_version, "pattern")
    distinct_outcomes = set(card.outcome_record_ids)
    if len(distinct_outcomes) < 2 and len(card.doctrine_record_ids) < 1:
        raise EvidenceValidationError(
            "pattern card needs >=2 distinct outcome_record_ids or >=1 doctrine_record_ids"
        )

    unknown_outcomes = distinct_outcomes - set(outcome_ids)
    if unknown_outcomes:
        raise EvidenceValidationError(
            f"pattern card references unknown outcome ids: {sorted(unknown_outcomes)}"
        )
    unknown_doctrine = set(card.doctrine_record_ids) - set(doctrine_ids)
    if unknown_doctrine:
        raise EvidenceValidationError(
            f"pattern card references unknown doctrine ids: {sorted(unknown_doctrine)}"
        )


# --------------------------------------------------------------------------- #
# staged -> canonical conversion (drops every private path)
# --------------------------------------------------------------------------- #
def _to_canonical_source(source: SourceRecord) -> CanonicalSourceRecord:
    return CanonicalSourceRecord(
        source_id=source.source_id,
        url=source.url,
        title=source.title,
        retrieved_at=source.retrieved_at,
        content_sha256=source.content_sha256,
    )


def to_outcome_record(candidate: OutcomeCandidate) -> OutcomeRecord:
    """Project a staged candidate onto its canonical form.

    Structural privacy guarantee: each source loses ``snapshot_file`` and the
    outcome loses ``layout_file``; ``layout_sha256`` and all public provenance,
    classification, editorial, and evidence fields are preserved verbatim.
    """
    return OutcomeRecord(
        schema_version=candidate.schema_version,
        reference_id=candidate.reference_id,
        source_kind=candidate.source_kind,
        sources=tuple(_to_canonical_source(s) for s in candidate.sources),
        resume_source_id=candidate.resume_source_id,
        outcome_source_id=candidate.outcome_source_id,
        layout_sha256=candidate.layout_sha256,
        role_family=candidate.role_family,
        target_role=candidate.target_role,
        target_level=candidate.target_level,
        graduation_month=candidate.graduation_month,
        professional_intervals=candidate.professional_intervals,
        internship_intervals=candidate.internship_intervals,
        professional_experience_months=candidate.professional_experience_months,
        experience_confidence=candidate.experience_confidence,
        outcome_tier=candidate.outcome_tier,
        outcome_evidence_quote=candidate.outcome_evidence_quote,
        outcome_evidence_confidence=candidate.outcome_evidence_confidence,
        resume_representation=candidate.resume_representation,
        resume_version_attribution=candidate.resume_version_attribution,
        section_order=candidate.section_order,
        feature_tags=candidate.feature_tags,
        editorial_ratings=candidate.editorial_ratings,
        limitations=candidate.limitations,
    )


def to_doctrine_record(candidate: DoctrineCandidate) -> DoctrineRecord:
    """Project a staged doctrine candidate onto its canonical form (drops snapshot_file)."""
    return DoctrineRecord(
        schema_version=candidate.schema_version,
        doctrine_id=candidate.doctrine_id,
        source=_to_canonical_source(candidate.source),
        authority_kind=candidate.authority_kind,
        principle=candidate.principle,
        early_career_applicability=candidate.early_career_applicability,
        affected_dimensions=candidate.affected_dimensions,
        supporting_quote=candidate.supporting_quote,
        conflicts_or_qualifications=candidate.conflicts_or_qualifications,
        confidence=candidate.confidence,
        permitted_uses=candidate.permitted_uses,
    )
