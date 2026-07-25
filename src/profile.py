"""Master-profile loader for Phase 3 tailoring (M8 item 1).

Parses and validates profile/master_profile.yaml per docs/TAILORING_SPEC.md
§1 and docs/TAILORING_METHODOLOGY.md §2. Pure: no SQLite, no network, no
logging side effects, and no I/O beyond reading the requested YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

_REQUIRED_TOP_LEVEL_KEYS = (
    "identity",
    "education",
    "experience",
    "projects",
    "skills",
    "variants",
)


class ProfileValidationError(ValueError):
    pass


class Strength(str, Enum):
    FLAGSHIP = "flagship"
    SOLID = "solid"
    FILLER = "filler"


@dataclass(frozen=True)
class Bullet:
    id: str
    text: str
    tags: tuple[str, ...]
    metrics: tuple[str, ...]
    evidence: str
    strength: Strength


@dataclass(frozen=True)
class Experience:
    org: str
    title: str
    dates: str
    bullets: tuple[Bullet, ...]


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    stack: str
    dates: str
    bullets: tuple[Bullet, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Variant:
    projects: tuple[str, ...]
    bullet_order: tuple[str, ...]


@dataclass(frozen=True)
class MasterProfile:
    identity: dict[str, str]
    education: tuple[dict[str, str], ...]
    experience: tuple[Experience, ...]
    projects: tuple[Project, ...]
    skills: dict[str, tuple[str, ...]]
    variants: dict[str, Variant]
    do_not_claim: tuple[str, ...]


def load_profile(path: str | Path) -> MasterProfile:
    profile_path = Path(path)
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileValidationError(f"{profile_path}: malformed YAML: {exc}") from exc

    root = _require_mapping(raw, "master_profile.yaml")
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in root:
            raise ProfileValidationError(f"master_profile.yaml.{key}: missing required key")

    identity = _build_identity(root["identity"])
    education = _build_education(root["education"])
    experience = _build_experience_list(root["experience"])
    projects = _build_projects(root["projects"])
    skills = _build_skills(root["skills"])
    variants = _build_variants(root["variants"])
    do_not_claim = _build_do_not_claim(root.get("do_not_claim", []))

    _check_unique_bullet_ids(experience, projects)
    _check_variant_references(variants, experience, projects)
    _check_do_not_claim_against_skills(do_not_claim, skills)

    return MasterProfile(
        identity=identity,
        education=education,
        experience=experience,
        projects=projects,
        skills=skills,
        variants=variants,
        do_not_claim=do_not_claim,
    )


def _require_mapping(value: Any, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ProfileValidationError(f"{path}: expected mapping, got {type(value).__name__}")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProfileValidationError(f"{path}: expected list, got {type(value).__name__}")
    return value


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ProfileValidationError(f"{path}: expected string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ProfileValidationError(f"{path}: expected nonempty string")
    return stripped


def _string_list(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    raw_items = _require_list(value, path)
    if not allow_empty and not raw_items:
        raise ProfileValidationError(f"{path}: expected nonempty string list")
    return tuple(_require_string(item, f"{path}.{index}") for index, item in enumerate(raw_items))


def _build_identity(value: Any) -> dict[str, str]:
    raw = _require_mapping(value, "identity")
    identity: dict[str, str] = {}
    for key, raw_value in raw.items():
        key_path = "identity"
        key_text = _require_string(key, key_path)
        identity[key_text] = _require_string(raw_value, f"identity.{key_text}")
    return identity


def _build_education(value: Any) -> tuple[dict[str, str], ...]:
    entries = _require_list(value, "education")
    education: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        raw_entry = _require_mapping(entry, f"education.{index}")
        parsed: dict[str, str] = {}
        for key, raw_value in raw_entry.items():
            key_text = _require_string(key, f"education.{index}")
            parsed[key_text] = _require_string(raw_value, f"education.{index}.{key_text}")
        education.append(parsed)
    return tuple(education)


def _build_experience_list(value: Any) -> tuple[Experience, ...]:
    return tuple(_build_experience(entry, f"experience.{index}") for index, entry in enumerate(_require_list(value, "experience")))


def _build_experience(value: Any, path: str) -> Experience:
    raw = _require_mapping(value, path)
    bullets_path = f"{path}.bullets"
    if "bullets" not in raw:
        raise ProfileValidationError(f"{bullets_path}: missing required key")
    return Experience(
        org=_required_field(raw, "org", path),
        title=_required_field(raw, "title", path),
        dates=_required_field(raw, "dates", path),
        bullets=tuple(_build_bullet(bullet, f"{bullets_path}.{index}") for index, bullet in enumerate(_require_list(raw["bullets"], bullets_path))),
    )


def _build_projects(value: Any) -> tuple[Project, ...]:
    raw_projects = _require_list(value, "projects")
    projects: list[Project] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_projects):
        project = _build_project(entry, f"projects.{index}")
        if project.id in seen:
            raise ProfileValidationError(f"projects.{index}.id: duplicate project id: {project.id}")
        seen.add(project.id)
        projects.append(project)
    return tuple(projects)


def _build_project(value: Any, path: str) -> Project:
    raw = _require_mapping(value, path)
    bullets_path = f"{path}.bullets"
    tags_path = f"{path}.tags"
    if "bullets" not in raw:
        raise ProfileValidationError(f"{bullets_path}: missing required key")
    if "tags" not in raw:
        raise ProfileValidationError(f"{tags_path}: missing required key")
    return Project(
        id=_required_field(raw, "id", path),
        name=_required_field(raw, "name", path),
        stack=_required_field(raw, "stack", path),
        dates=_required_field(raw, "dates", path),
        bullets=tuple(_build_bullet(bullet, f"{bullets_path}.{index}") for index, bullet in enumerate(_require_list(raw["bullets"], bullets_path))),
        tags=_string_list(raw["tags"], tags_path),
    )


def _build_bullet(value: Any, path: str) -> Bullet:
    raw = _require_mapping(value, path)
    strength_value = _required_field(raw, "strength", path)
    try:
        strength = Strength(strength_value)
    except ValueError:
        allowed = ", ".join(s.value for s in Strength)
        raise ProfileValidationError(f"{path}.strength: expected one of {allowed}, got {strength_value!r}") from None
    return Bullet(
        id=_required_field(raw, "id", path),
        text=_required_field(raw, "text", path),
        tags=_string_list(raw.get("tags", ()), f"{path}.tags"),
        metrics=_string_list(raw.get("metrics", ()), f"{path}.metrics"),
        evidence=_required_field(raw, "evidence", path),
        strength=strength,
    )


def _build_skills(value: Any) -> dict[str, tuple[str, ...]]:
    raw = _require_mapping(value, "skills")
    skills: dict[str, tuple[str, ...]] = {}
    for key, raw_values in raw.items():
        category = _require_string(key, "skills")
        skills[category] = _string_list(raw_values, f"skills.{category}", allow_empty=False)
    return skills


def _build_variants(value: Any) -> dict[str, Variant]:
    raw = _require_mapping(value, "variants")
    variants: dict[str, Variant] = {}
    for raw_name, raw_variant in raw.items():
        name = _require_string(raw_name, "variants")
        variant_path = f"variants.{name}"
        variant_mapping = _require_mapping(raw_variant, variant_path)
        variants[name] = Variant(
            projects=_string_list(variant_mapping.get("projects", ()), f"{variant_path}.projects"),
            bullet_order=_string_list(variant_mapping.get("bullet_order", ()), f"{variant_path}.bullet_order"),
        )
    return variants


def _build_do_not_claim(value: Any) -> tuple[str, ...]:
    entries = _string_list(value, "do_not_claim")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        normalized = _normalize_term(entry)
        if normalized in seen:
            raise ProfileValidationError(f"do_not_claim.{index}: duplicate entry: {entry}")
        seen.add(normalized)
    return entries


def _required_field(raw: dict[Any, Any], field: str, path: str) -> str:
    field_path = f"{path}.{field}"
    if field not in raw:
        raise ProfileValidationError(f"{field_path}: missing required key")
    return _require_string(raw[field], field_path)


def _check_unique_bullet_ids(experience: tuple[Experience, ...], projects: tuple[Project, ...]) -> None:
    seen: set[str] = set()
    for source in (*experience, *projects):
        for bullet in source.bullets:
            if bullet.id in seen:
                raise ProfileValidationError(f"duplicate bullet id: {bullet.id}")
            seen.add(bullet.id)


def _check_variant_references(
    variants: dict[str, Variant],
    experience: tuple[Experience, ...],
    projects: tuple[Project, ...],
) -> None:
    known_project_ids = {project.id for project in projects}
    known_bullet_ids = {bullet.id for source in (*experience, *projects) for bullet in source.bullets}
    for variant_name, variant in variants.items():
        _check_references_unique(variant.projects, f"variants.{variant_name}.projects")
        _check_references_unique(variant.bullet_order, f"variants.{variant_name}.bullet_order")
        for index, project_id in enumerate(variant.projects):
            if project_id not in known_project_ids:
                raise ProfileValidationError(f"variants.{variant_name}.projects.{index}: unknown project id: {project_id}")
        for index, bullet_id in enumerate(variant.bullet_order):
            if bullet_id not in known_bullet_ids:
                raise ProfileValidationError(f"variants.{variant_name}.bullet_order.{index}: unknown bullet id: {bullet_id}")


def _check_references_unique(references: tuple[str, ...], path: str) -> None:
    seen: set[str] = set()
    for index, reference in enumerate(references):
        if reference in seen:
            raise ProfileValidationError(f"{path}.{index}: duplicate reference: {reference}")
        seen.add(reference)


def _check_do_not_claim_against_skills(do_not_claim: tuple[str, ...], skills: dict[str, tuple[str, ...]]) -> None:
    banned = {_normalize_term(entry) for entry in do_not_claim}
    if not banned:
        return
    for category, values in skills.items():
        for index, skill in enumerate(values):
            if _normalize_term(skill) in banned:
                raise ProfileValidationError(f"skills.{category}.{index}: do_not_claim term listed as skill: {skill}")


def _normalize_term(value: str) -> str:
    return " ".join(value.casefold().split())
