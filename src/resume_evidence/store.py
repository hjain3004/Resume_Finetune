"""Strict canonical resume-evidence loader and read-only advisory lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.resume_evidence import serde
from src.resume_evidence.experience import professional_experience_months
from src.resume_evidence.model import (
    SCHEMA_VERSION,
    DoctrineRecord,
    EditorialDimension,
    OutcomeRecord,
    OutcomeTier,
    PatternCard,
    ResumeRepresentation,
    RoleFamily,
)
from src.resume_evidence.policy import _check_url_safety, validate_pattern_card
from src.resume_evidence.serde import EvidenceValidationError

_CORPUS_KEYS = frozenset(
    {
        "schema_version",
        "corpus_version",
        "approved_at",
        "approval_report_sha256",
        "outcome_ids",
        "doctrine_ids",
        "pattern_ids",
    }
)


@dataclass(frozen=True)
class EvidenceBank:
    outcomes: tuple[OutcomeRecord, ...]
    doctrine: tuple[DoctrineRecord, ...]
    patterns: tuple[PatternCard, ...]
    corpus_version: str | None
    approved_at: datetime | None
    approval_report_sha256: str | None

    @classmethod
    def empty(cls) -> "EvidenceBank":
        return cls((), (), (), None, None, None)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field}: expected nonempty string")
    return value


def _id_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EvidenceValidationError(f"{field}: expected list")
    result = tuple(_required_text(item, f"{field}[{index}]") for index, item in enumerate(value))
    if len({item.casefold() for item in result}) != len(result):
        raise EvidenceValidationError(f"{field}: duplicate IDs")
    if result != tuple(sorted(result)):
        raise EvidenceValidationError(f"{field}: IDs must be sorted")
    return result


def _validate_source(source, field: str) -> None:
    _check_url_safety(source.url)
    digest = source.content_sha256
    if len(digest) != 64 or digest != digest.lower() or any(ch not in "0123456789abcdef" for ch in digest):
        raise EvidenceValidationError(f"{field}.content_sha256: invalid SHA-256")


def _validate_outcome(record: OutcomeRecord) -> None:
    if record.schema_version != SCHEMA_VERSION:
        raise EvidenceValidationError(f"outcome {record.reference_id!r}: unsupported schema")
    source_ids = [source.source_id for source in record.sources]
    if len(set(source_ids)) != len(source_ids):
        raise EvidenceValidationError(f"outcome {record.reference_id!r}: duplicate source IDs")
    if record.resume_source_id not in source_ids or record.outcome_source_id not in source_ids:
        raise EvidenceValidationError(f"outcome {record.reference_id!r}: unresolved source ID")
    for source in record.sources:
        _validate_source(source, f"outcome {record.reference_id}.{source.source_id}")
    dimensions = [rating.dimension for rating in record.editorial_ratings]
    if len(dimensions) != len(EditorialDimension) or set(dimensions) != set(EditorialDimension):
        raise EvidenceValidationError(f"outcome {record.reference_id!r}: incomplete ratings")
    if not record.limitations:
        raise EvidenceValidationError(f"outcome {record.reference_id!r}: missing limitations")
    if record.graduation_month is not None:
        computed = professional_experience_months(
            record.professional_intervals, record.graduation_month
        )
        if computed != record.professional_experience_months:
            raise EvidenceValidationError(
                f"outcome {record.reference_id!r}: experience recomputation mismatch"
            )


def _validate_doctrine(record: DoctrineRecord) -> None:
    if record.schema_version != SCHEMA_VERSION:
        raise EvidenceValidationError(f"doctrine {record.doctrine_id!r}: unsupported schema")
    _validate_source(record.source, f"doctrine {record.doctrine_id}")
    if not record.early_career_applicability.strip() or not record.affected_dimensions or not record.permitted_uses:
        raise EvidenceValidationError(f"doctrine {record.doctrine_id!r}: incomplete semantics")


def _load_records(directory: Path, ids: tuple[str, ...], kind: str):
    if not directory.is_dir():
        raise EvidenceValidationError(f"canonical {kind} directory is missing")
    actual = sorted(directory.iterdir())
    expected_names = [f"{item}.yaml" for item in ids]
    if [item.name for item in actual] != expected_names or any(not item.is_file() for item in actual):
        raise EvidenceValidationError(
            f"canonical {kind}: files do not match manifest IDs"
        )
    records = []
    for item_id, path in zip(ids, actual):
        if kind == "outcomes":
            record = serde.parse_outcome_record(path)
            if record.reference_id != item_id:
                raise EvidenceValidationError("canonical outcome filename/id disagreement")
            _validate_outcome(record)
        elif kind == "doctrine":
            record = serde.parse_doctrine_record(path)
            if record.doctrine_id != item_id:
                raise EvidenceValidationError("canonical doctrine filename/id disagreement")
            _validate_doctrine(record)
        else:
            record = serde.parse_pattern_card(path)
            if record.pattern_id != item_id or record.schema_version != SCHEMA_VERSION:
                raise EvidenceValidationError("canonical pattern filename/id disagreement")
        records.append(record)
    return tuple(records)


def load_evidence_bank(bank_root: Path) -> EvidenceBank:
    """Load ``<bank_root>/current`` strictly; a missing bank is an empty advisory bank."""
    current = Path(bank_root) / "current"
    if not current.exists():
        return EvidenceBank.empty()
    if not current.is_dir():
        raise EvidenceValidationError("canonical current path is not a directory")
    actual_root = sorted(item.name for item in current.iterdir())
    expected_root = ["corpus.yaml", "doctrine", "outcomes", "patterns"]
    if actual_root != expected_root:
        raise EvidenceValidationError(
            f"canonical bank has unexpected or missing entries: {actual_root}"
        )
    raw = serde._load_mapping(current / "corpus.yaml", "canonical corpus manifest")
    if set(raw) != _CORPUS_KEYS:
        raise EvidenceValidationError("canonical corpus manifest keys do not match contract")
    schema = _required_text(raw["schema_version"], "corpus.schema_version")
    if schema != SCHEMA_VERSION:
        raise EvidenceValidationError("canonical corpus has unsupported schema_version")
    outcome_ids = _id_list(raw["outcome_ids"], "corpus.outcome_ids")
    doctrine_ids = _id_list(raw["doctrine_ids"], "corpus.doctrine_ids")
    pattern_ids = _id_list(raw["pattern_ids"], "corpus.pattern_ids")
    outcomes = _load_records(current / "outcomes", outcome_ids, "outcomes")
    doctrine = _load_records(current / "doctrine", doctrine_ids, "doctrine")
    patterns = _load_records(current / "patterns", pattern_ids, "patterns")
    validate_outcomes = {record.reference_id for record in outcomes}
    validate_doctrine = {record.doctrine_id for record in doctrine}
    for card in patterns:
        validate_pattern_card(card, validate_outcomes, validate_doctrine)
    approval_hash = _required_text(
        raw["approval_report_sha256"], "corpus.approval_report_sha256"
    )
    if len(approval_hash) != 64 or approval_hash != approval_hash.lower() or any(
        char not in "0123456789abcdef" for char in approval_hash
    ):
        raise EvidenceValidationError("corpus.approval_report_sha256 is invalid")
    approved_at = serde._parse_utc(raw["approved_at"], "corpus.approved_at")
    return EvidenceBank(
        outcomes=outcomes,
        doctrine=doctrine,
        patterns=patterns,
        corpus_version=_required_text(raw["corpus_version"], "corpus.corpus_version"),
        approved_at=approved_at,
        approval_report_sha256=approval_hash,
    )


def lookup_outcomes(
    bank: EvidenceBank,
    *,
    role_family: RoleFamily | None = None,
    max_months: int | None = None,
    outcome_tier: OutcomeTier | None = None,
    representation: ResumeRepresentation | None = None,
) -> tuple[OutcomeRecord, ...]:
    if max_months is not None and (
        isinstance(max_months, bool) or not isinstance(max_months, int) or not 0 <= max_months <= 36
    ):
        raise EvidenceValidationError("max_months must be an integer from 0 through 36")
    selected = []
    for record in bank.outcomes:
        if role_family is not None and record.role_family is not role_family:
            continue
        if max_months is not None and record.professional_experience_months > max_months:
            continue
        if outcome_tier is not None and record.outcome_tier is not outcome_tier:
            continue
        if representation is not None and record.resume_representation is not representation:
            continue
        selected.append(record)
    return tuple(sorted(selected, key=lambda item: item.reference_id))
