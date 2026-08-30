"""Strict YAML serde for the offline resume-evidence bank.

Parsing is intentionally unforgiving: every parser rejects missing required keys,
unknown keys, duplicate mapping keys, booleans where integers are required,
non-string enum values, and any timestamp that is not the exact whole-second UTC
string ``YYYY-MM-DDTHH:MM:SSZ``. Lists become immutable tuples; duplicate ids and
case-insensitive duplicate strings are rejected during parsing.

Dumpers emit keys in dataclass field order via ``yaml.safe_dump(sort_keys=False)``
and serialize datetimes back to whole-second ``Z`` strings.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from src.resume_evidence.model import (
    AuthorityKind,
    CanonicalCorpus,
    CanonicalSourceRecord,
    ConfidenceLevel,
    DoctrineCandidate,
    DoctrineRecord,
    DoctrineUse,
    EditorialDimension,
    EditorialRating,
    EmploymentInterval,
    EvidenceConfidence,
    ExperienceConfidence,
    OutcomeCandidate,
    OutcomeRecord,
    OutcomeTier,
    PatternCard,
    ResumeRepresentation,
    ResumeVersionAttribution,
    RoleFamily,
    SourceKind,
    SourceRecord,
)

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class EvidenceValidationError(ValueError):
    """Raised when a resume-evidence document violates its strict contract."""


# --------------------------------------------------------------------------- #
# strict YAML loading
# --------------------------------------------------------------------------- #
class _StrictLoader(yaml.SafeLoader):
    pass


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise EvidenceValidationError(f"duplicate mapping key: {key}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def _load_mapping(path: Path, field: str = "root") -> dict[str, object]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.load(text, _StrictLoader)
    except EvidenceValidationError:
        raise
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise EvidenceValidationError(f"{field}: malformed YAML: {exc}") from exc
    return _expect_mapping(data, field)


# --------------------------------------------------------------------------- #
# primitive expectations
# --------------------------------------------------------------------------- #
def _expect_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{field}: expected mapping")
    return value


def _expect_keys(
    obj: dict[str, object],
    required: frozenset[str],
    optional: frozenset[str],
    field: str,
) -> None:
    missing = sorted(required - obj.keys())
    if missing:
        raise EvidenceValidationError(f"{field}: missing keys: {missing}")
    extra = sorted(obj.keys() - (required | optional))
    if extra:
        raise EvidenceValidationError(f"{field}: unexpected keys: {extra}")


def _expect_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field}: expected string")
    return value


def _expect_opt_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _expect_str(value, field)


def _expect_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceValidationError(f"{field}: expected integer")
    return value


def _expect_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceValidationError(f"{field}: expected boolean")
    return value


def _expect_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise EvidenceValidationError(f"{field}: expected list")
    return value


def _parse_utc(value: object, field: str) -> datetime:
    """Accept only ``YYYY-MM-DDTHH:MM:SSZ`` and return an aware UTC datetime.

    YAML's implicitly parsed ``datetime``/``date`` objects are rejected so that
    serialization stays explicit and lossless.
    """
    if not isinstance(value, str):
        raise EvidenceValidationError(
            f"{field}: expected UTC timestamp string YYYY-MM-DDTHH:MM:SSZ"
        )
    if not _UTC_RE.match(value):
        raise EvidenceValidationError(
            f"{field}: expected exact YYYY-MM-DDTHH:MM:SSZ format"
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise EvidenceValidationError(f"{field}: invalid timestamp: {exc}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expect_enum(enum_cls: type, value: object, field: str):
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field}: expected string enum value")
    try:
        return enum_cls(value)
    except ValueError:
        raise EvidenceValidationError(
            f"{field}: invalid value {value!r}"
        ) from None


# --------------------------------------------------------------------------- #
# collection expectations (dedup during parsing, before a set could hide dupes)
# --------------------------------------------------------------------------- #
def _expect_str_tuple(value: object, field: str) -> tuple[str, ...]:
    items = _expect_list(value, field)
    seen: set[str] = set()
    out: list[str] = []
    for index, item in enumerate(items):
        text = _expect_str(item, f"{field}[{index}]")
        key = text.casefold()
        if key in seen:
            raise EvidenceValidationError(
                f"{field}[{index}]: case-insensitive duplicate string {text!r}"
            )
        seen.add(key)
        out.append(text)
    return tuple(out)


def _expect_enum_tuple(enum_cls: type, value: object, field: str) -> tuple:
    items = _expect_list(value, field)
    seen: set = set()
    out: list = []
    for index, item in enumerate(items):
        member = _expect_enum(enum_cls, item, f"{field}[{index}]")
        if member in seen:
            raise EvidenceValidationError(
                f"{field}[{index}]: duplicate enum value {member.value!r}"
            )
        seen.add(member)
        out.append(member)
    return tuple(out)


def _parse_tuple(
    value: object, field: str, item_parser: Callable[[object, str], Any]
) -> tuple:
    items = _expect_list(value, field)
    return tuple(
        item_parser(item, f"{field}[{index}]") for index, item in enumerate(items)
    )


# --------------------------------------------------------------------------- #
# nested record parsers
# --------------------------------------------------------------------------- #
_STAGED_SOURCE_KEYS = frozenset(
    {"source_id", "url", "title", "retrieved_at", "content_sha256", "snapshot_file"}
)
_CANONICAL_SOURCE_KEYS = frozenset(
    {"source_id", "url", "title", "retrieved_at", "content_sha256"}
)


def _parse_source(value: object, field: str, *, staged: bool):
    obj = _expect_mapping(value, field)
    _expect_keys(
        obj,
        _STAGED_SOURCE_KEYS if staged else _CANONICAL_SOURCE_KEYS,
        frozenset(),
        field,
    )
    common = dict(
        source_id=_expect_str(obj["source_id"], f"{field}.source_id"),
        url=_expect_str(obj["url"], f"{field}.url"),
        title=_expect_str(obj["title"], f"{field}.title"),
        retrieved_at=_parse_utc(obj["retrieved_at"], f"{field}.retrieved_at"),
        content_sha256=_expect_str(obj["content_sha256"], f"{field}.content_sha256"),
    )
    if staged:
        return SourceRecord(
            **common,
            snapshot_file=_expect_str(obj["snapshot_file"], f"{field}.snapshot_file"),
        )
    return CanonicalSourceRecord(**common)


def _parse_sources(value: object, field: str, *, staged: bool) -> tuple:
    items = _expect_list(value, field)
    seen: set[str] = set()
    out: list = []
    for index, item in enumerate(items):
        record = _parse_source(item, f"{field}[{index}]", staged=staged)
        key = record.source_id.casefold()
        if key in seen:
            raise EvidenceValidationError(
                f"{field}[{index}]: duplicate source_id {record.source_id!r}"
            )
        seen.add(key)
        out.append(record)
    return tuple(out)


def _parse_interval(value: object, field: str) -> EmploymentInterval:
    obj = _expect_mapping(value, field)
    _expect_keys(obj, frozenset({"start_month", "end_month"}), frozenset(), field)
    return EmploymentInterval(
        start_month=_expect_str(obj["start_month"], f"{field}.start_month"),
        end_month=_expect_str(obj["end_month"], f"{field}.end_month"),
    )


def _parse_rating(value: object, field: str) -> EditorialRating:
    obj = _expect_mapping(value, field)
    _expect_keys(
        obj, frozenset({"dimension", "score", "explanation"}), frozenset(), field
    )
    return EditorialRating(
        dimension=_expect_enum(EditorialDimension, obj["dimension"], f"{field}.dimension"),
        score=_expect_int(obj["score"], f"{field}.score"),
        explanation=_expect_str(obj["explanation"], f"{field}.explanation"),
    )


def _parse_ratings(value: object, field: str) -> tuple[EditorialRating, ...]:
    items = _expect_list(value, field)
    seen: set = set()
    out: list[EditorialRating] = []
    for index, item in enumerate(items):
        rating = _parse_rating(item, f"{field}[{index}]")
        if rating.dimension in seen:
            raise EvidenceValidationError(
                f"{field}[{index}]: duplicate dimension {rating.dimension.value!r}"
            )
        seen.add(rating.dimension)
        out.append(rating)
    return tuple(out)


# --------------------------------------------------------------------------- #
# outcome (staged candidate + canonical record)
# --------------------------------------------------------------------------- #
_OUTCOME_SHARED_KEYS = {
    "schema_version",
    "reference_id",
    "source_kind",
    "sources",
    "resume_source_id",
    "outcome_source_id",
    "layout_sha256",
    "role_family",
    "target_role",
    "target_level",
    "graduation_month",
    "professional_intervals",
    "internship_intervals",
    "professional_experience_months",
    "experience_confidence",
    "outcome_tier",
    "outcome_evidence_quote",
    "outcome_evidence_confidence",
    "resume_representation",
    "resume_version_attribution",
    "section_order",
    "feature_tags",
    "editorial_ratings",
    "limitations",
}


def _build_outcome(obj: dict[str, object], field: str, *, staged: bool):
    required = set(_OUTCOME_SHARED_KEYS)
    if staged:
        required.add("layout_file")
    _expect_keys(obj, frozenset(required), frozenset(), field)

    shared = dict(
        schema_version=_expect_str(obj["schema_version"], f"{field}.schema_version"),
        reference_id=_expect_str(obj["reference_id"], f"{field}.reference_id"),
        source_kind=_expect_enum(SourceKind, obj["source_kind"], f"{field}.source_kind"),
        sources=_parse_sources(obj["sources"], f"{field}.sources", staged=staged),
        resume_source_id=_expect_str(
            obj["resume_source_id"], f"{field}.resume_source_id"
        ),
        outcome_source_id=_expect_str(
            obj["outcome_source_id"], f"{field}.outcome_source_id"
        ),
        layout_sha256=_expect_opt_str(obj["layout_sha256"], f"{field}.layout_sha256"),
        role_family=_expect_enum(RoleFamily, obj["role_family"], f"{field}.role_family"),
        target_role=_expect_str(obj["target_role"], f"{field}.target_role"),
        target_level=_expect_str(obj["target_level"], f"{field}.target_level"),
        graduation_month=_expect_opt_str(
            obj["graduation_month"], f"{field}.graduation_month"
        ),
        professional_intervals=_parse_tuple(
            obj["professional_intervals"],
            f"{field}.professional_intervals",
            _parse_interval,
        ),
        internship_intervals=_parse_tuple(
            obj["internship_intervals"],
            f"{field}.internship_intervals",
            _parse_interval,
        ),
        professional_experience_months=_expect_int(
            obj["professional_experience_months"],
            f"{field}.professional_experience_months",
        ),
        experience_confidence=_expect_enum(
            ExperienceConfidence,
            obj["experience_confidence"],
            f"{field}.experience_confidence",
        ),
        outcome_tier=_expect_enum(
            OutcomeTier, obj["outcome_tier"], f"{field}.outcome_tier"
        ),
        outcome_evidence_quote=_expect_str(
            obj["outcome_evidence_quote"], f"{field}.outcome_evidence_quote"
        ),
        outcome_evidence_confidence=_expect_enum(
            EvidenceConfidence,
            obj["outcome_evidence_confidence"],
            f"{field}.outcome_evidence_confidence",
        ),
        resume_representation=_expect_enum(
            ResumeRepresentation,
            obj["resume_representation"],
            f"{field}.resume_representation",
        ),
        resume_version_attribution=_expect_enum(
            ResumeVersionAttribution,
            obj["resume_version_attribution"],
            f"{field}.resume_version_attribution",
        ),
        section_order=_expect_str_tuple(obj["section_order"], f"{field}.section_order"),
        feature_tags=_expect_str_tuple(obj["feature_tags"], f"{field}.feature_tags"),
        editorial_ratings=_parse_ratings(
            obj["editorial_ratings"], f"{field}.editorial_ratings"
        ),
        limitations=_expect_str_tuple(obj["limitations"], f"{field}.limitations"),
    )

    if staged:
        return OutcomeCandidate(
            layout_file=_expect_opt_str(obj["layout_file"], f"{field}.layout_file"),
            **shared,
        )
    return OutcomeRecord(**shared)


def parse_outcome_candidate(path: Path) -> OutcomeCandidate:
    return _build_outcome(_load_mapping(Path(path), "outcome_candidate"), "outcome_candidate", staged=True)


def parse_outcome_record(path: Path) -> OutcomeRecord:
    return _build_outcome(_load_mapping(Path(path), "outcome_record"), "outcome_record", staged=False)


# --------------------------------------------------------------------------- #
# doctrine (staged candidate + canonical record)
# --------------------------------------------------------------------------- #
_DOCTRINE_KEYS = frozenset(
    {
        "schema_version",
        "doctrine_id",
        "source",
        "authority_kind",
        "principle",
        "early_career_applicability",
        "affected_dimensions",
        "supporting_quote",
        "conflicts_or_qualifications",
        "confidence",
        "permitted_uses",
    }
)


def _build_doctrine(obj: dict[str, object], field: str, *, staged: bool):
    _expect_keys(obj, _DOCTRINE_KEYS, frozenset(), field)
    shared = dict(
        schema_version=_expect_str(obj["schema_version"], f"{field}.schema_version"),
        doctrine_id=_expect_str(obj["doctrine_id"], f"{field}.doctrine_id"),
        source=_parse_source(obj["source"], f"{field}.source", staged=staged),
        authority_kind=_expect_enum(
            AuthorityKind, obj["authority_kind"], f"{field}.authority_kind"
        ),
        principle=_expect_str(obj["principle"], f"{field}.principle"),
        early_career_applicability=_expect_str(
            obj["early_career_applicability"], f"{field}.early_career_applicability"
        ),
        affected_dimensions=_expect_enum_tuple(
            EditorialDimension,
            obj["affected_dimensions"],
            f"{field}.affected_dimensions",
        ),
        supporting_quote=_expect_str(
            obj["supporting_quote"], f"{field}.supporting_quote"
        ),
        conflicts_or_qualifications=_expect_str_tuple(
            obj["conflicts_or_qualifications"],
            f"{field}.conflicts_or_qualifications",
        ),
        confidence=_expect_enum(
            ConfidenceLevel, obj["confidence"], f"{field}.confidence"
        ),
        permitted_uses=_expect_enum_tuple(
            DoctrineUse, obj["permitted_uses"], f"{field}.permitted_uses"
        ),
    )
    if staged:
        return DoctrineCandidate(**shared)
    return DoctrineRecord(**shared)


def parse_doctrine_candidate(path: Path) -> DoctrineCandidate:
    return _build_doctrine(_load_mapping(Path(path), "doctrine_candidate"), "doctrine_candidate", staged=True)


def parse_doctrine_record(path: Path) -> DoctrineRecord:
    return _build_doctrine(_load_mapping(Path(path), "doctrine_record"), "doctrine_record", staged=False)


# --------------------------------------------------------------------------- #
# pattern card
# --------------------------------------------------------------------------- #
_PATTERN_KEYS = frozenset(
    {
        "schema_version",
        "pattern_id",
        "text",
        "anti_pattern",
        "role_families",
        "outcome_record_ids",
        "doctrine_record_ids",
        "limitations",
        "confidence",
        "prohibited_uses",
        "candidate_dimensions",
    }
)


def _build_pattern(obj: dict[str, object], field: str) -> PatternCard:
    _expect_keys(obj, _PATTERN_KEYS, frozenset(), field)
    return PatternCard(
        schema_version=_expect_str(obj["schema_version"], f"{field}.schema_version"),
        pattern_id=_expect_str(obj["pattern_id"], f"{field}.pattern_id"),
        text=_expect_str(obj["text"], f"{field}.text"),
        anti_pattern=_expect_bool(obj["anti_pattern"], f"{field}.anti_pattern"),
        role_families=_expect_enum_tuple(
            RoleFamily, obj["role_families"], f"{field}.role_families"
        ),
        outcome_record_ids=_expect_str_tuple(
            obj["outcome_record_ids"], f"{field}.outcome_record_ids"
        ),
        doctrine_record_ids=_expect_str_tuple(
            obj["doctrine_record_ids"], f"{field}.doctrine_record_ids"
        ),
        limitations=_expect_str_tuple(obj["limitations"], f"{field}.limitations"),
        confidence=_expect_enum(
            ConfidenceLevel, obj["confidence"], f"{field}.confidence"
        ),
        prohibited_uses=_expect_str_tuple(
            obj["prohibited_uses"], f"{field}.prohibited_uses"
        ),
        candidate_dimensions=_expect_enum_tuple(
            EditorialDimension,
            obj["candidate_dimensions"],
            f"{field}.candidate_dimensions",
        ),
    )


def parse_pattern_card(path: Path) -> PatternCard:
    return _build_pattern(_load_mapping(Path(path), "pattern_card"), "pattern_card")


# --------------------------------------------------------------------------- #
# canonical corpus
# --------------------------------------------------------------------------- #
_CORPUS_KEYS = frozenset(
    {
        "schema_version",
        "corpus_version",
        "approved_at",
        "approval_report_sha256",
        "outcomes",
        "doctrine",
        "patterns",
    }
)


def _parse_unique_id_tuple(
    value: object,
    field: str,
    item_parser: Callable[[object, str], Any],
    id_attr: str,
) -> tuple:
    items = _expect_list(value, field)
    seen: set[str] = set()
    out: list = []
    for index, item in enumerate(items):
        record = item_parser(item, f"{field}[{index}]")
        key = getattr(record, id_attr).casefold()
        if key in seen:
            raise EvidenceValidationError(
                f"{field}[{index}]: duplicate {id_attr} {getattr(record, id_attr)!r}"
            )
        seen.add(key)
        out.append(record)
    return tuple(out)


def parse_canonical_corpus(root: Path) -> CanonicalCorpus:
    root = Path(root)
    path = root / "corpus.yaml" if root.is_dir() else root
    obj = _load_mapping(path, "corpus")
    _expect_keys(obj, _CORPUS_KEYS, frozenset(), "corpus")
    return CanonicalCorpus(
        schema_version=_expect_str(obj["schema_version"], "corpus.schema_version"),
        corpus_version=_expect_str(obj["corpus_version"], "corpus.corpus_version"),
        approved_at=_parse_utc(obj["approved_at"], "corpus.approved_at"),
        approval_report_sha256=_expect_str(
            obj["approval_report_sha256"], "corpus.approval_report_sha256"
        ),
        outcomes=_parse_unique_id_tuple(
            obj["outcomes"],
            "corpus.outcomes",
            lambda v, f: _build_outcome(_expect_mapping(v, f), f, staged=False),
            "reference_id",
        ),
        doctrine=_parse_unique_id_tuple(
            obj["doctrine"],
            "corpus.doctrine",
            lambda v, f: _build_doctrine(_expect_mapping(v, f), f, staged=False),
            "doctrine_id",
        ),
        patterns=_parse_unique_id_tuple(
            obj["patterns"],
            "corpus.patterns",
            lambda v, f: _build_pattern(_expect_mapping(v, f), f),
            "pattern_id",
        ),
    )


# --------------------------------------------------------------------------- #
# dumpers (stable order == dataclass field order)
# --------------------------------------------------------------------------- #
def _dump(payload: dict) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _source_payload(source, *, staged: bool) -> dict:
    payload = {
        "source_id": source.source_id,
        "url": source.url,
        "title": source.title,
        "retrieved_at": _format_utc(source.retrieved_at),
        "content_sha256": source.content_sha256,
    }
    if staged:
        payload["snapshot_file"] = source.snapshot_file
    return payload


def _interval_payload(interval: EmploymentInterval) -> dict:
    return {"start_month": interval.start_month, "end_month": interval.end_month}


def _rating_payload(rating: EditorialRating) -> dict:
    return {
        "dimension": rating.dimension.value,
        "score": rating.score,
        "explanation": rating.explanation,
    }


def _outcome_payload(outcome, *, staged: bool) -> dict:
    payload: dict = {
        "schema_version": outcome.schema_version,
        "reference_id": outcome.reference_id,
        "source_kind": outcome.source_kind.value,
        "sources": [_source_payload(s, staged=staged) for s in outcome.sources],
        "resume_source_id": outcome.resume_source_id,
        "outcome_source_id": outcome.outcome_source_id,
    }
    if staged:
        payload["layout_file"] = outcome.layout_file
    payload.update(
        {
            "layout_sha256": outcome.layout_sha256,
            "role_family": outcome.role_family.value,
            "target_role": outcome.target_role,
            "target_level": outcome.target_level,
            "graduation_month": outcome.graduation_month,
            "professional_intervals": [
                _interval_payload(i) for i in outcome.professional_intervals
            ],
            "internship_intervals": [
                _interval_payload(i) for i in outcome.internship_intervals
            ],
            "professional_experience_months": outcome.professional_experience_months,
            "experience_confidence": outcome.experience_confidence.value,
            "outcome_tier": outcome.outcome_tier.value,
            "outcome_evidence_quote": outcome.outcome_evidence_quote,
            "outcome_evidence_confidence": outcome.outcome_evidence_confidence.value,
            "resume_representation": outcome.resume_representation.value,
            "resume_version_attribution": outcome.resume_version_attribution.value,
            "section_order": list(outcome.section_order),
            "feature_tags": list(outcome.feature_tags),
            "editorial_ratings": [
                _rating_payload(r) for r in outcome.editorial_ratings
            ],
            "limitations": list(outcome.limitations),
        }
    )
    return payload


def _doctrine_payload(doctrine, *, staged: bool) -> dict:
    return {
        "schema_version": doctrine.schema_version,
        "doctrine_id": doctrine.doctrine_id,
        "source": _source_payload(doctrine.source, staged=staged),
        "authority_kind": doctrine.authority_kind.value,
        "principle": doctrine.principle,
        "early_career_applicability": doctrine.early_career_applicability,
        "affected_dimensions": [d.value for d in doctrine.affected_dimensions],
        "supporting_quote": doctrine.supporting_quote,
        "conflicts_or_qualifications": list(doctrine.conflicts_or_qualifications),
        "confidence": doctrine.confidence.value,
        "permitted_uses": [u.value for u in doctrine.permitted_uses],
    }


def _pattern_payload(pattern: PatternCard) -> dict:
    return {
        "schema_version": pattern.schema_version,
        "pattern_id": pattern.pattern_id,
        "text": pattern.text,
        "anti_pattern": pattern.anti_pattern,
        "role_families": [r.value for r in pattern.role_families],
        "outcome_record_ids": list(pattern.outcome_record_ids),
        "doctrine_record_ids": list(pattern.doctrine_record_ids),
        "limitations": list(pattern.limitations),
        "confidence": pattern.confidence.value,
        "prohibited_uses": list(pattern.prohibited_uses),
        "candidate_dimensions": [d.value for d in pattern.candidate_dimensions],
    }


def dump_outcome_candidate(value: OutcomeCandidate) -> str:
    return _dump(_outcome_payload(value, staged=True))


def dump_outcome_record(value: OutcomeRecord) -> str:
    return _dump(_outcome_payload(value, staged=False))


def dump_doctrine_candidate(value: DoctrineCandidate) -> str:
    return _dump(_doctrine_payload(value, staged=True))


def dump_doctrine_record(value: DoctrineRecord) -> str:
    return _dump(_doctrine_payload(value, staged=False))


def dump_pattern_card(value: PatternCard) -> str:
    return _dump(_pattern_payload(value))


def dump_canonical_corpus(value: CanonicalCorpus) -> str:
    payload = {
        "schema_version": value.schema_version,
        "corpus_version": value.corpus_version,
        "approved_at": _format_utc(value.approved_at),
        "approval_report_sha256": value.approval_report_sha256,
        "outcomes": [_outcome_payload(o, staged=False) for o in value.outcomes],
        "doctrine": [_doctrine_payload(d, staged=False) for d in value.doctrine],
        "patterns": [_pattern_payload(p) for p in value.patterns],
    }
    return _dump(payload)
