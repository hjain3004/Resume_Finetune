"""Whole-corpus validation and (in later tasks) atomic promotion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from src.resume_evidence import serde
from src.resume_evidence.duplicates import DuplicatePair, find_duplicates
from src.resume_evidence.model import (
    SCHEMA_VERSION,
    DoctrineCandidate,
    OutcomeCandidate,
    PatternCard,
)
from src.resume_evidence.policy import (
    AdmissionDecision,
    AdmissionStatus,
    evaluate_admission,
    validate_doctrine_bundle,
    validate_outcome_bundle,
    validate_pattern_card,
)
from src.resume_evidence.serde import EvidenceValidationError

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "corpus_version",
        "promote_outcome_ids",
        "excluded_outcomes",
        "expected_doctrine_ids",
        "expected_pattern_ids",
    }
)


@dataclass(frozen=True)
class ExcludedOutcome:
    reference_id: str
    reason: str


@dataclass(frozen=True)
class CorpusManifest:
    schema_version: str
    corpus_version: str
    promote_outcome_ids: tuple[str, ...]
    excluded_outcomes: tuple[ExcludedOutcome, ...]
    expected_doctrine_ids: tuple[str, ...]
    expected_pattern_ids: tuple[str, ...]


@dataclass(frozen=True)
class OutcomeDecision:
    reference_id: str
    admission: AdmissionDecision
    disposition: str
    exclusion_reason: str | None


@dataclass(frozen=True)
class ValidatedCorpus:
    corpus_version: str
    outcomes: tuple[OutcomeCandidate, ...]
    doctrine: tuple[DoctrineCandidate, ...]
    patterns: tuple[PatternCard, ...]
    decisions: tuple[OutcomeDecision, ...]
    duplicates: tuple[DuplicatePair, ...]

    @property
    def promoted_outcome_ids(self) -> tuple[str, ...]:
        return tuple(
            item.reference_id for item in self.decisions if item.disposition == "promote"
        )


def _strict_mapping(path: Path, field: str) -> dict[str, object]:
    try:
        return serde._load_mapping(path, field)  # one strict YAML implementation
    except FileNotFoundError:
        raise


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"{field}: expected nonempty string")
    return value


def _unique_text_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise EvidenceValidationError(f"{field}: expected list")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        text = _required_text(item, f"{field}[{index}]")
        key = text.casefold()
        if key in seen:
            raise EvidenceValidationError(f"{field}: duplicate id {text!r}")
        seen.add(key)
        result.append(text)
    return tuple(result)


def _parse_manifest(path: Path) -> CorpusManifest:
    raw = _strict_mapping(path, "manifest")
    missing = _MANIFEST_KEYS - raw.keys()
    extra = raw.keys() - _MANIFEST_KEYS
    if missing:
        raise EvidenceValidationError(f"manifest: missing keys: {sorted(missing)}")
    if extra:
        raise EvidenceValidationError(f"manifest: unexpected keys: {sorted(extra)}")
    schema_version = _required_text(raw["schema_version"], "manifest.schema_version")
    if schema_version != SCHEMA_VERSION:
        raise EvidenceValidationError(
            f"manifest.schema_version: unsupported value {schema_version!r}"
        )
    excluded_raw = raw["excluded_outcomes"]
    if not isinstance(excluded_raw, list):
        raise EvidenceValidationError("manifest.excluded_outcomes: expected list")
    excluded: list[ExcludedOutcome] = []
    excluded_seen: set[str] = set()
    for index, item in enumerate(excluded_raw):
        if not isinstance(item, dict) or set(item) != {"reference_id", "reason"}:
            raise EvidenceValidationError(
                f"manifest.excluded_outcomes[{index}]: expected reference_id and reason"
            )
        reference_id = _required_text(
            item["reference_id"], f"manifest.excluded_outcomes[{index}].reference_id"
        )
        reason = _required_text(item["reason"], f"manifest.excluded_outcomes[{index}].reason")
        key = reference_id.casefold()
        if key in excluded_seen:
            raise EvidenceValidationError(
                f"manifest.excluded_outcomes: duplicate id {reference_id!r}"
            )
        excluded_seen.add(key)
        excluded.append(ExcludedOutcome(reference_id, reason))
    promote = _unique_text_list(raw["promote_outcome_ids"], "manifest.promote_outcome_ids")
    overlap = {item.casefold() for item in promote} & excluded_seen
    if overlap:
        raise EvidenceValidationError(
            f"manifest: outcome appears in promote and exclude lists: {sorted(overlap)}"
        )
    return CorpusManifest(
        schema_version=schema_version,
        corpus_version=_required_text(raw["corpus_version"], "manifest.corpus_version"),
        promote_outcome_ids=promote,
        excluded_outcomes=tuple(excluded),
        expected_doctrine_ids=_unique_text_list(
            raw["expected_doctrine_ids"], "manifest.expected_doctrine_ids"
        ),
        expected_pattern_ids=_unique_text_list(
            raw["expected_pattern_ids"], "manifest.expected_pattern_ids"
        ),
    )


def _visible_children(path: Path) -> tuple[Path, ...]:
    if not path.is_dir():
        raise EvidenceValidationError(f"required directory is missing: {path.name!r}")
    return tuple(sorted((item for item in path.iterdir() if not item.name.startswith("."))))


def _directory_ids(path: Path, field: str) -> tuple[str, ...]:
    children = _visible_children(path)
    bad = [item.name for item in children if not item.is_dir()]
    if bad:
        raise EvidenceValidationError(f"{field}: unexpected files: {bad}")
    ids = tuple(item.name for item in children)
    if len({item.casefold() for item in ids}) != len(ids):
        raise EvidenceValidationError(f"{field}: duplicate case-insensitive ids")
    return ids


def _check_exact_ids(actual: tuple[str, ...], expected: tuple[str, ...], field: str) -> None:
    if {item.casefold() for item in actual} != {item.casefold() for item in expected}:
        raise EvidenceValidationError(
            f"{field}: actual IDs {sorted(actual)} do not match expected IDs {sorted(expected)}"
        )


def _check_schema(value: str, field: str) -> None:
    if value != SCHEMA_VERSION:
        raise EvidenceValidationError(f"{field}.schema_version: unsupported value {value!r}")


def _check_layout(candidate: OutcomeCandidate, bundle_dir: Path) -> set[Path]:
    if (candidate.layout_file is None) != (candidate.layout_sha256 is None):
        raise EvidenceValidationError(
            f"{candidate.reference_id}: layout_file and layout_sha256 must appear together"
        )
    if candidate.layout_file is None:
        return set()
    target = (bundle_dir / candidate.layout_file).resolve()
    if not target.is_relative_to(bundle_dir.resolve()) or not target.is_file():
        raise EvidenceValidationError(
            f"{candidate.reference_id}: invalid layout_file {candidate.layout_file!r}"
        )
    digest = candidate.layout_sha256 or ""
    if len(digest) != 64 or digest != digest.lower() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise EvidenceValidationError(f"{candidate.reference_id}: layout hash mismatch")
    return {target}


def _check_bundle_files(bundle_dir: Path, allowed: set[Path], field: str) -> None:
    actual = {
        path.resolve()
        for path in bundle_dir.rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(bundle_dir).parts)
    }
    unexpected = sorted(str(path.relative_to(bundle_dir.resolve())) for path in actual - allowed)
    if unexpected:
        raise EvidenceValidationError(f"{field}: unexpected files: {unexpected}")


def _resume_text(candidate: OutcomeCandidate, bundle_dir: Path) -> str:
    source = next(
        item for item in candidate.sources if item.source_id == candidate.resume_source_id
    )
    return (bundle_dir / source.snapshot_file).read_text(encoding="utf-8")


def validate_corpus(inbox_root: Path, manifest_path: Path) -> ValidatedCorpus:
    """Validate the complete private corpus without writing any state."""
    root = Path(inbox_root)
    manifest = _parse_manifest(Path(manifest_path))
    allowed_root = {"outcomes", "doctrine", "patterns"}
    if Path(manifest_path).parent.resolve() == root.resolve():
        allowed_root.add(Path(manifest_path).name)
    unexpected_root = [
        item.name
        for item in _visible_children(root)
        if item.name not in allowed_root
    ]
    if unexpected_root:
        raise EvidenceValidationError(f"inbox: unexpected entries: {unexpected_root}")

    outcome_ids = _directory_ids(root / "outcomes", "outcomes")
    doctrine_ids = _directory_ids(root / "doctrine", "doctrine")
    pattern_ids = _directory_ids(root / "patterns", "patterns")
    disposition_ids = manifest.promote_outcome_ids + tuple(
        item.reference_id for item in manifest.excluded_outcomes
    )
    _check_exact_ids(outcome_ids, disposition_ids, "outcomes")
    _check_exact_ids(doctrine_ids, manifest.expected_doctrine_ids, "doctrine")
    _check_exact_ids(pattern_ids, manifest.expected_pattern_ids, "patterns")

    outcomes: list[OutcomeCandidate] = []
    resume_text_by_id: dict[str, str] = {}
    for reference_id in outcome_ids:
        bundle_dir = root / "outcomes" / reference_id
        candidate = serde.parse_outcome_candidate(bundle_dir / "bundle.yaml")
        if candidate.reference_id != reference_id:
            raise EvidenceValidationError(
                f"outcome directory {reference_id!r} disagrees with record id {candidate.reference_id!r}"
            )
        _check_schema(candidate.schema_version, f"outcome {reference_id}")
        validate_outcome_bundle(candidate, bundle_dir)
        allowed = {bundle_dir.resolve() / "bundle.yaml"}
        allowed.update((bundle_dir / source.snapshot_file).resolve() for source in candidate.sources)
        allowed.update(_check_layout(candidate, bundle_dir))
        _check_bundle_files(bundle_dir, allowed, f"outcome {reference_id}")
        outcomes.append(candidate)
        resume_text_by_id[reference_id] = _resume_text(candidate, bundle_dir)

    doctrine: list[DoctrineCandidate] = []
    for doctrine_id in doctrine_ids:
        bundle_dir = root / "doctrine" / doctrine_id
        candidate = serde.parse_doctrine_candidate(bundle_dir / "record.yaml")
        if candidate.doctrine_id != doctrine_id:
            raise EvidenceValidationError(
                f"doctrine directory {doctrine_id!r} disagrees with record id {candidate.doctrine_id!r}"
            )
        _check_schema(candidate.schema_version, f"doctrine {doctrine_id}")
        validate_doctrine_bundle(candidate, bundle_dir)
        allowed = {
            bundle_dir.resolve() / "record.yaml",
            (bundle_dir / candidate.source.snapshot_file).resolve(),
        }
        _check_bundle_files(bundle_dir, allowed, f"doctrine {doctrine_id}")
        doctrine.append(candidate)

    promote_ids = set(manifest.promote_outcome_ids)
    patterns: list[PatternCard] = []
    for pattern_id in pattern_ids:
        bundle_dir = root / "patterns" / pattern_id
        card = serde.parse_pattern_card(bundle_dir / "record.yaml")
        if card.pattern_id != pattern_id:
            raise EvidenceValidationError(
                f"pattern directory {pattern_id!r} disagrees with record id {card.pattern_id!r}"
            )
        _check_schema(card.schema_version, f"pattern {pattern_id}")
        validate_pattern_card(card, promote_ids, set(doctrine_ids))
        _check_bundle_files(
            bundle_dir, {bundle_dir.resolve() / "record.yaml"}, f"pattern {pattern_id}"
        )
        patterns.append(card)

    exclusions = {item.reference_id: item.reason for item in manifest.excluded_outcomes}
    decisions = tuple(
        OutcomeDecision(
            candidate.reference_id,
            evaluate_admission(candidate),
            "promote" if candidate.reference_id in promote_ids else "exclude",
            exclusions.get(candidate.reference_id),
        )
        for candidate in sorted(outcomes, key=lambda item: item.reference_id)
    )
    for decision in decisions:
        if decision.disposition == "promote" and decision.admission.status is not AdmissionStatus.ACCEPTED:
            raise EvidenceValidationError(
                f"promoted outcome {decision.reference_id!r} must have accepted admission status"
            )

    duplicates = find_duplicates(tuple(outcomes), resume_text_by_id)
    unresolved = [
        pair
        for pair in duplicates
        if pair.left_id in promote_ids and pair.right_id in promote_ids
    ]
    if unresolved:
        first = unresolved[0]
        raise EvidenceValidationError(
            f"unresolved duplicate promoted outcomes: {first.left_id!r}, {first.right_id!r}"
        )

    return ValidatedCorpus(
        corpus_version=manifest.corpus_version,
        outcomes=tuple(sorted(outcomes, key=lambda item: item.reference_id)),
        doctrine=tuple(sorted(doctrine, key=lambda item: item.doctrine_id)),
        patterns=tuple(sorted(patterns, key=lambda item: item.pattern_id)),
        decisions=decisions,
        duplicates=duplicates,
    )


def import_corpus(
    inbox_root: Path,
    manifest_path: Path,
    bank_root: Path,
    *,
    approved_report_sha256: str,
    approved_at: datetime,
) -> ValidatedCorpus:
    """Validate approval binding; Task 7 adds canonical atomic publication."""
    del bank_root, approved_at
    validated = validate_corpus(inbox_root, manifest_path)
    from src.resume_evidence.report import build_report, report_sha256

    expected = report_sha256(build_report(validated))
    if approved_report_sha256 != expected:
        raise EvidenceValidationError(
            "approval report SHA-256 does not match the current validated corpus"
        )
    return validated
