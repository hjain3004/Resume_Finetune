from __future__ import annotations

from pathlib import Path

import pytest

from src.profile import (
    MasterProfile,
    ProfileValidationError,
    Strength,
    load_profile,
)

VALID_PROFILE_YAML = """
identity:
  name: Jane Doe
  email: jane@example.com
education:
  - school: State University
    degree: BS Computer Science
    dates: "2020 - 2024"
experience:
  - org: Acme Corp
    title: Software Engineer
    dates: "Jul 2024 - Present"
    bullets:
      - id: acme-perf
        text: "Cut API latency 40% by adding a read-through cache."
        tags: [backend, performance]
        metrics: ["40%"]
        evidence: "Profiled the endpoint, found N+1 queries, added Redis caching."
        strength: flagship
projects:
  - id: side-project
    name: Recipe Finder
    stack: "Python, FastAPI"
    dates: "Jan 2025 - Mar 2025"
    tags: [ml]
    bullets:
      - id: side-project-search
        text: "Built a semantic search endpoint over 10k recipes."
        tags: [ml, search]
        metrics: []
        evidence: "Used sentence-transformers to embed recipe text, indexed with FAISS."
        strength: solid
skills:
  languages: [Python, Go]
  frameworks: [FastAPI, PyTorch]
variants:
  backend:
    projects: [side-project]
    bullet_order: [acme-perf, side-project-search]
do_not_claim:
  - Kubernetes administration
"""


def test_load_profile_happy_path(tmp_path: Path) -> None:
    path = tmp_path / "master_profile.yaml"
    path.write_text(VALID_PROFILE_YAML)

    profile = load_profile(path)

    assert isinstance(profile, MasterProfile)
    assert profile.identity["name"] == "Jane Doe"
    assert profile.education[0]["degree"] == "BS Computer Science"
    assert profile.experience[0].org == "Acme Corp"
    assert profile.experience[0].bullets[0].id == "acme-perf"
    assert profile.experience[0].bullets[0].strength == Strength.FLAGSHIP
    assert profile.projects[0].id == "side-project"
    assert profile.projects[0].bullets[0].strength == Strength.SOLID
    assert profile.skills["languages"] == ("Python", "Go")
    assert profile.variants["backend"].projects == ("side-project",)
    assert profile.variants["backend"].bullet_order == ("acme-perf", "side-project-search")
    assert profile.do_not_claim == ("Kubernetes administration",)


def test_load_profile_rejects_missing_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "master_profile.yaml"
    path.write_text("identity:\n  name: Jane Doe\n")

    with pytest.raises(ProfileValidationError, match="education"):
        load_profile(path)


def test_load_profile_rejects_bullet_missing_evidence(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        '        evidence: "Profiled the endpoint, found N+1 queries, added Redis caching."\n',
        "",
    )
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="acme-perf"):
        load_profile(path)


def test_load_profile_rejects_bullet_invalid_strength(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace("strength: flagship", "strength: legendary")
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="acme-perf"):
        load_profile(path)


def test_load_profile_rejects_duplicate_bullet_id(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace("id: side-project-search", "id: acme-perf")
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="acme-perf"):
        load_profile(path)
