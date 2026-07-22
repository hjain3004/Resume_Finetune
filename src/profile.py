"""Master-profile loader for Phase 3 tailoring (M8 item 1).

Parses and validates profile/master_profile.yaml per docs/TAILORING_SPEC.md
§1 and docs/TAILORING_METHODOLOGY.md §2. Pure: no SQLite, no network, no
logging side effects — matches src/eligibility.py's module shape.
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
    identity: dict
    education: tuple[dict, ...]
    experience: tuple[Experience, ...]
    projects: tuple[Project, ...]
    skills: dict[str, tuple[str, ...]]
    variants: dict[str, Variant]
    do_not_claim: tuple[str, ...]


def _build_bullet(raw: dict[str, Any]) -> Bullet:
    return Bullet(
        id=raw["id"],
        text=raw["text"],
        tags=tuple(raw.get("tags", ())),
        metrics=tuple(raw.get("metrics", ())),
        evidence=raw["evidence"],
        strength=Strength(raw["strength"]),
    )


def _build_experience(raw: dict[str, Any]) -> Experience:
    return Experience(
        org=raw["org"],
        title=raw["title"],
        dates=raw["dates"],
        bullets=tuple(_build_bullet(b) for b in raw.get("bullets", ())),
    )


def _build_project(raw: dict[str, Any]) -> Project:
    return Project(
        id=raw["id"],
        name=raw["name"],
        stack=raw["stack"],
        dates=raw["dates"],
        bullets=tuple(_build_bullet(b) for b in raw.get("bullets", ())),
        tags=tuple(raw.get("tags", ())),
    )


def _build_variant(raw: dict[str, Any]) -> Variant:
    return Variant(
        projects=tuple(raw.get("projects", ())),
        bullet_order=tuple(raw.get("bullet_order", ())),
    )


def load_profile(path: str | Path) -> MasterProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    missing = [key for key in _REQUIRED_TOP_LEVEL_KEYS if key not in raw]
    if missing:
        raise ProfileValidationError(f"master_profile.yaml missing required key(s): {', '.join(missing)}")

    skills = {section: tuple(values) for section, values in raw["skills"].items()}
    variants = {name: _build_variant(v) for name, v in raw["variants"].items()}

    return MasterProfile(
        identity=raw["identity"],
        education=tuple(raw["education"]),
        experience=tuple(_build_experience(e) for e in raw["experience"]),
        projects=tuple(_build_project(p) for p in raw["projects"]),
        skills=skills,
        variants=variants,
        do_not_claim=tuple(raw.get("do_not_claim", ())),
    )
