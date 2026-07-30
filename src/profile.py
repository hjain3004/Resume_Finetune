"""Master-profile loader for Phase 3 tailoring (M8 item 2).

Parses and validates config/master_profile.yaml per
docs/superpowers/specs/2026-07-30-m8-profile-schema-reconciliation-design.md.
Pure: no SQLite, no network, no logging, and no I/O beyond reading the
requested YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ProfileValidationError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of last-wins."""


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise ProfileValidationError(
                f"line {key_node.start_mark.line + 1}: duplicate key: {key!r}"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def _read_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.load(text, _StrictLoader)
    except ProfileValidationError:
        raise
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"{path}: malformed YAML: {exc}") from exc


_ASCII_EXEMPT_PATHS = ("ats.forbidden_chars", "ats.substitutions")


def _is_ascii_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _ASCII_EXEMPT_PATHS)


def _check_ascii(value: str, path: str) -> None:
    if _is_ascii_exempt(path):
        return
    if not value.isascii():
        offenders = sorted({ch for ch in value if not ch.isascii()})
        rendered = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in offenders)
        raise ProfileValidationError(f"{path}: non-ASCII character(s): {rendered}")


def _require_mapping(value: Any, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ProfileValidationError(
            f"{path}: expected mapping, got {type(value).__name__}"
        )
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileValidationError(
            f"{path}: expected list, got {type(value).__name__}"
        )
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError(
            f"{path}: expected string, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise ProfileValidationError(f"{path}: expected nonempty string")
    _check_ascii(stripped, path)
    return stripped


def _string_list(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _require_list(value, path)
    if not allow_empty and not items:
        raise ProfileValidationError(f"{path}: expected nonempty string list")
    return tuple(
        _require_string(item, f"{path}.{index}") for index, item in enumerate(items)
    )


def _require_positive_int(value: Any, path: str) -> int:
    # bool must be rejected explicitly: isinstance(True, int) is True in Python,
    # so `priority: true` would otherwise validate as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileValidationError(
            f"{path}: expected integer, got {type(value).__name__}"
        )
    if value < 1:
        raise ProfileValidationError(f"{path}: expected positive integer, got {value}")
    return value


def _required_field(raw: dict[Any, Any], field: str, path: str) -> str:
    field_path = f"{path}.{field}"
    if field not in raw:
        raise ProfileValidationError(f"{field_path}: missing required key")
    return _require_string(raw[field], field_path)


class ClaimType(str, Enum):
    VERIFIED = "verified"
    SCOPED = "scoped"
    ESTIMATED = "estimated"
    OBSERVED = "observed"
    OWNERSHIP_UNRESOLVED = "ownership_unresolved"
    NEEDS_INPUT = "needs_input"


#: claim_types whose bullets must never reach a rendered resume.
BLOCKED_CLAIM_TYPES = frozenset(
    {ClaimType.OWNERSHIP_UNRESOLVED, ClaimType.NEEDS_INPUT}
)


@dataclass(frozen=True)
class Phrasings:
    short: str
    medium: str | None = None
    long: str | None = None

    def best_within(self, limit: int) -> str:
        """Longest phrasing that fits `limit` characters, else `short`."""
        for candidate in (self.long, self.medium, self.short):
            if candidate is not None and len(candidate) <= limit:
                return candidate
        return self.short


@dataclass(frozen=True)
class Bullet:
    id: str
    claim_type: ClaimType
    priority: int
    phrasings: Phrasings
    evidence: tuple[str, ...]
    keywords_hit: tuple[str, ...]
    defense: str
    interview_risk: str

    @property
    def is_blocked(self) -> bool:
        return self.claim_type in BLOCKED_CLAIM_TYPES


def _build_enum(enum_cls, raw_value: str, path: str):
    try:
        return enum_cls(raw_value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_cls)
        raise ProfileValidationError(
            f"{path}: expected one of {allowed}, got {raw_value!r}"
        ) from None


def _build_phrasings(value: Any, path: str) -> Phrasings:
    raw = _require_mapping(value, path)
    unknown = set(map(str, raw)) - {"short", "medium", "long"}
    if unknown:
        raise ProfileValidationError(
            f"{path}: unknown phrasing tier(s): {', '.join(sorted(unknown))}"
        )
    if "short" not in raw:
        raise ProfileValidationError(f"{path}.short: missing required key")
    return Phrasings(
        short=_require_string(raw["short"], f"{path}.short"),
        medium=(
            _require_string(raw["medium"], f"{path}.medium")
            if "medium" in raw
            else None
        ),
        long=_require_string(raw["long"], f"{path}.long") if "long" in raw else None,
    )


def _build_bullet(value: Any, path: str) -> Bullet:
    raw = _require_mapping(value, path)
    claim_type = _build_enum(
        ClaimType, _required_field(raw, "claim_type", path), f"{path}.claim_type"
    )

    for required in ("phrasings", "evidence", "priority"):
        if required not in raw:
            raise ProfileValidationError(f"{path}.{required}: missing required key")

    defense = (raw.get("defense") or "").strip()
    if claim_type is not ClaimType.VERIFIED and not defense:
        raise ProfileValidationError(
            f"{path}.defense: required when claim_type is {claim_type.value!r} "
            f"(contract C3)"
        )
    if defense:
        _check_ascii(defense, f"{path}.defense")

    interview_risk = (raw.get("interview_risk") or "").strip()
    if interview_risk:
        _check_ascii(interview_risk, f"{path}.interview_risk")

    return Bullet(
        id=_required_field(raw, "id", path),
        claim_type=claim_type,
        priority=_require_positive_int(raw["priority"], f"{path}.priority"),
        phrasings=_build_phrasings(raw["phrasings"], f"{path}.phrasings"),
        evidence=_string_list(raw["evidence"], f"{path}.evidence", allow_empty=False),
        keywords_hit=_string_list(raw.get("keywords_hit", ()), f"{path}.keywords_hit"),
        defense=defense,
        interview_risk=interview_risk,
    )


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    display_title: str
    tech_line: str
    ownership_boundary: str
    bullets: tuple[Bullet, ...]
    keywords_exact: tuple[str, ...]
    keywords_topical: tuple[str, ...]
    metric_ledger: dict[str, "MetricEntry"]
    metric_scope: dict[str, str]
    known_gaps: tuple["KnownGap", ...]


@dataclass(frozen=True)
class Experience:
    id: str
    employer: str
    title: str
    scope_line: str
    display_date: str
    ownership_boundary: str
    bullets: tuple[Bullet, ...]
    keywords_exact: tuple[str, ...]
    keywords_topical: tuple[str, ...]
    metric_ledger: dict[str, "MetricEntry"]
    metric_scope: dict[str, str]
    known_gaps: tuple["KnownGap", ...]


def _build_bullets(raw: dict[Any, Any], path: str) -> tuple[Bullet, ...]:
    if "bullets" not in raw:
        raise ProfileValidationError(f"{path}.bullets: missing required key")
    entries = _require_list(raw["bullets"], f"{path}.bullets")
    if not entries:
        raise ProfileValidationError(f"{path}.bullets: expected nonempty list")
    return tuple(
        _build_bullet(entry, f"{path}.bullets.{index}")
        for index, entry in enumerate(entries)
    )


def _build_keywords(
    raw: dict[Any, Any], path: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    keywords = _require_mapping(raw.get("keywords", {}), f"{path}.keywords")
    return (
        _string_list(keywords.get("exact", ()), f"{path}.keywords.exact"),
        _string_list(keywords.get("topical", ()), f"{path}.keywords.topical"),
    )


def _build_project(value: Any, path: str) -> Project:
    raw = _require_mapping(value, path)
    exact, topical = _build_keywords(raw, path)
    tech = _require_mapping(raw.get("tech", {}), f"{path}.tech")
    return Project(
        id=_required_field(raw, "id", path),
        name=_required_field(raw, "name", path),
        display_title=_required_field(raw, "display_title", path),
        tech_line=_required_field(tech, "tech_line", f"{path}.tech"),
        ownership_boundary=_required_field(raw, "ownership_boundary", path),
        bullets=_build_bullets(raw, path),
        keywords_exact=exact,
        keywords_topical=topical,
        metric_ledger=_build_metric_ledger(raw, path),
        metric_scope=_build_metric_scope(raw, path),
        known_gaps=_build_known_gaps(raw, path),
    )


def _build_experience(value: Any, path: str) -> Experience:
    raw = _require_mapping(value, path)
    exact, topical = _build_keywords(raw, path)
    return Experience(
        id=_required_field(raw, "id", path),
        employer=_required_field(raw, "employer", path),
        title=_required_field(raw, "title", path),
        scope_line=_required_field(raw, "scope_line", path),
        display_date=_required_field(raw, "display_date", path),
        ownership_boundary=_required_field(raw, "ownership_boundary", path),
        bullets=_build_bullets(raw, path),
        keywords_exact=exact,
        keywords_topical=topical,
        metric_ledger=_build_metric_ledger(raw, path),
        metric_scope=_build_metric_scope(raw, path),
        known_gaps=_build_known_gaps(raw, path),
    )


def _build_projects(value: Any) -> tuple[Project, ...]:
    seen: set[str] = set()
    projects: list[Project] = []
    for index, entry in enumerate(_require_list(value, "projects")):
        project = _build_project(entry, f"projects.{index}")
        if project.id in seen:
            raise ProfileValidationError(
                f"projects.{index}.id: duplicate project id: {project.id}"
            )
        seen.add(project.id)
        projects.append(project)
    return tuple(projects)


def _build_experience_list(value: Any) -> tuple[Experience, ...]:
    seen: set[str] = set()
    entries: list[Experience] = []
    for index, entry in enumerate(_require_list(value, "experience")):
        item = _build_experience(entry, f"experience.{index}")
        if item.id in seen:
            raise ProfileValidationError(
                f"experience.{index}.id: duplicate experience id: {item.id}"
            )
        seen.add(item.id)
        entries.append(item)
    return tuple(entries)


def _check_unique_bullet_ids(
    experience: tuple[Experience, ...], projects: tuple[Project, ...]
) -> None:
    seen: set[str] = set()
    for source in (*projects, *experience):
        for bullet in source.bullets:
            if bullet.id in seen:
                raise ProfileValidationError(f"duplicate bullet id: {bullet.id}")
            seen.add(bullet.id)


class Provenance(str, Enum):
    COUNTED = "counted"
    DOC_BACKED = "doc_backed"
    CONFIGURED = "configured"
    ESTIMATED = "estimated"
    UNSOURCED = "unsourced"
    CONTRADICTED = "contradicted"
    NONE = "none"


#: A number from one of these sources may never be printed.
NON_RENDERABLE_PROVENANCES = frozenset(
    {Provenance.UNSOURCED, Provenance.CONTRADICTED, Provenance.NONE}
)

_METRIC_KEYS = {"value", "provenance", "renderable", "render_as", "note"}


@dataclass(frozen=True)
class MetricEntry:
    value: Any
    provenance: Provenance
    renderable: bool
    render_as: str | None
    note: str


def _build_metric_entry(value: Any, path: str) -> MetricEntry:
    raw = _require_mapping(value, path)
    unknown = set(map(str, raw)) - _METRIC_KEYS
    if unknown:
        raise ProfileValidationError(
            f"{path}: unknown key(s): {', '.join(sorted(unknown))}"
        )
    for required in ("value", "provenance", "renderable"):
        if required not in raw:
            raise ProfileValidationError(f"{path}.{required}: missing required key")

    provenance = _build_enum(
        Provenance,
        _require_string(raw["provenance"], f"{path}.provenance"),
        f"{path}.provenance",
    )

    renderable = raw["renderable"]
    if not isinstance(renderable, bool):
        raise ProfileValidationError(
            f"{path}.renderable: expected boolean, got {type(renderable).__name__}"
        )
    if renderable and provenance in NON_RENDERABLE_PROVENANCES:
        raise ProfileValidationError(
            f"{path}: renderable must be false when provenance is {provenance.value!r}"
        )

    note = (raw.get("note") or "").strip()
    if note:
        _check_ascii(note, f"{path}.note")
    return MetricEntry(
        value=raw["value"],
        provenance=provenance,
        renderable=renderable,
        render_as=(
            _require_string(raw["render_as"], f"{path}.render_as")
            if "render_as" in raw
            else None
        ),
        note=note,
    )


def _build_metric_ledger(raw: dict[Any, Any], path: str) -> dict[str, MetricEntry]:
    ledger_path = f"{path}.metric_ledger"
    ledger = _require_mapping(raw.get("metric_ledger", {}), ledger_path)
    result: dict[str, MetricEntry] = {}
    for key, value in ledger.items():
        name = _require_string(key, ledger_path)
        result[name] = _build_metric_entry(value, f"{ledger_path}.{name}")
    return result


def _build_metric_scope(raw: dict[Any, Any], path: str) -> dict[str, str]:
    scope_path = f"{path}.metric_scope"
    scope = _require_mapping(raw.get("metric_scope", {}), scope_path)
    result: dict[str, str] = {}
    for key, value in scope.items():
        name = _require_string(key, scope_path)
        result[name] = _require_string(value, f"{scope_path}.{name}")
    return result


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GapStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class KnownGap:
    id: str
    severity: Severity
    status: GapStatus
    detail: str
    fix: str


def _build_known_gaps(raw: dict[Any, Any], path: str) -> tuple[KnownGap, ...]:
    gaps_path = f"{path}.known_gaps"
    gaps: list[KnownGap] = []
    for index, entry in enumerate(_require_list(raw.get("known_gaps", []), gaps_path)):
        entry_path = f"{gaps_path}.{index}"
        raw_gap = _require_mapping(entry, entry_path)
        gaps.append(
            KnownGap(
                id=_required_field(raw_gap, "id", entry_path),
                severity=_build_enum(
                    Severity,
                    _required_field(raw_gap, "severity", entry_path),
                    f"{entry_path}.severity",
                ),
                status=_build_enum(
                    GapStatus,
                    (raw_gap.get("status") or "open"),
                    f"{entry_path}.status",
                ),
                detail=_required_field(raw_gap, "detail", entry_path),
                fix=_required_field(raw_gap, "fix", entry_path),
            )
        )
    return tuple(gaps)


def load_profile(path: str | Path) -> "MasterProfile":
    raw = _read_yaml(Path(path))
    root = _require_mapping(raw, "master_profile.yaml")
    raise NotImplementedError("built up across Tasks 2-9")
