from __future__ import annotations

from pathlib import Path

import pytest

from src.profile import (
    Bullet,
    Experience,
    MasterProfile,
    ProfileValidationError,
    Project,
    Strength,
    Variant,
    load_profile,
)


VALID_PROFILE_YAML = """
identity:
  name: Jane Doe
  email: jane@example.com
  location: San Jose, CA
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


def _write_profile(tmp_path: Path, yaml_text: str = VALID_PROFILE_YAML) -> Path:
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def _rejects(tmp_path: Path, yaml_text: str, match: str) -> None:
    with pytest.raises(ProfileValidationError, match=match):
        load_profile(_write_profile(tmp_path, yaml_text))


def test_load_profile_happy_path_returns_immutable_dataclass_shapes(tmp_path: Path) -> None:
    profile = load_profile(_write_profile(tmp_path))

    assert isinstance(profile, MasterProfile)
    assert profile.identity == {"name": "Jane Doe", "email": "jane@example.com", "location": "San Jose, CA"}
    assert profile.education == ({"school": "State University", "degree": "BS Computer Science", "dates": "2020 - 2024"},)
    assert isinstance(profile.experience[0], Experience)
    assert profile.experience[0].org == "Acme Corp"
    assert isinstance(profile.experience[0].bullets[0], Bullet)
    assert profile.experience[0].bullets[0].strength == Strength.FLAGSHIP
    assert isinstance(profile.projects[0], Project)
    assert profile.projects[0].id == "side-project"
    assert profile.projects[0].tags == ("ml",)
    assert profile.projects[0].bullets[0].strength == Strength.SOLID
    assert profile.skills == {"languages": ("Python", "Go"), "frameworks": ("FastAPI", "PyTorch")}
    assert isinstance(profile.variants["backend"], Variant)
    assert profile.variants["backend"].projects == ("side-project",)
    assert profile.variants["backend"].bullet_order == ("acme-perf", "side-project-search")
    assert profile.do_not_claim == ("Kubernetes administration",)


def test_load_profile_rejects_malformed_yaml(tmp_path: Path) -> None:
    _rejects(tmp_path, "identity: [unterminated\n", "master_profile.yaml")


def test_load_profile_rejects_non_mapping_root(tmp_path: Path) -> None:
    _rejects(tmp_path, "- not\n- a\n- mapping\n", "master_profile.yaml")


@pytest.mark.parametrize(
    "missing_key",
    ["identity", "education", "experience", "projects", "skills", "variants"],
)
def test_load_profile_rejects_each_missing_top_level_key(tmp_path: Path, missing_key: str) -> None:
    lines = VALID_PROFILE_YAML.splitlines()
    start = lines.index(f"{missing_key}:")
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")), len(lines))
    yaml_text = "\n".join(lines[:start] + lines[end:])

    _rejects(tmp_path, yaml_text, missing_key)


@pytest.mark.parametrize(
    ("yaml_text", "match"),
    [
        (VALID_PROFILE_YAML.replace("identity:\n  name: Jane Doe\n  email: jane@example.com\n  location: San Jose, CA", "identity:\n  - Jane Doe"), "identity"),
        (VALID_PROFILE_YAML.replace("identity:\n  name: Jane Doe\n  email: jane@example.com\n  location: San Jose, CA", "identity: false"), "identity"),
        (VALID_PROFILE_YAML.replace("education:\n  - school:", "education:\n    school:"), "education"),
        (VALID_PROFILE_YAML.replace("experience:\n  - org:", "experience:\n    org:"), "experience"),
        (VALID_PROFILE_YAML.replace("projects:\n  - id:", "projects:\n    id:"), "projects"),
        (VALID_PROFILE_YAML.replace("skills:\n  languages:", "skills:\n  languages: Python\n  frameworks:"), "skills.languages"),
        (VALID_PROFILE_YAML.replace("variants:\n  backend:", "variants:\n  - backend:"), "variants"),
    ],
)
def test_load_profile_rejects_wrong_container_types(tmp_path: Path, yaml_text: str, match: str) -> None:
    _rejects(tmp_path, yaml_text, match)


@pytest.mark.parametrize(
    ("yaml_text", "match"),
    [
        (VALID_PROFILE_YAML.replace("name: Jane Doe", "name: ''"), "identity.name"),
        (VALID_PROFILE_YAML.replace("degree: BS Computer Science", "degree: ''"), "education.0.degree"),
        (VALID_PROFILE_YAML.replace("org: Acme Corp", "org: '  '"), "experience.0.org"),
        (VALID_PROFILE_YAML.replace("title: Software Engineer", "title: ''"), "experience.0.title"),
        (VALID_PROFILE_YAML.replace('dates: "Jul 2024 - Present"', "dates: ''"), "experience.0.dates"),
        (VALID_PROFILE_YAML.replace("  - id: side-project\n", "  - id: ''\n"), "projects.0.id"),
        (VALID_PROFILE_YAML.replace("name: Recipe Finder", "name: ''"), "projects.0.name"),
        (VALID_PROFILE_YAML.replace('stack: "Python, FastAPI"', "stack: ''"), "projects.0.stack"),
        (VALID_PROFILE_YAML.replace('dates: "Jan 2025 - Mar 2025"', "dates: ''"), "projects.0.dates"),
        (VALID_PROFILE_YAML.replace("id: acme-perf", "id: ''"), "experience.0.bullets.0.id"),
        (VALID_PROFILE_YAML.replace("text: \"Cut API latency 40% by adding a read-through cache.\"", "text: ''"), "experience.0.bullets.0.text"),
        (VALID_PROFILE_YAML.replace("evidence: \"Profiled the endpoint, found N+1 queries, added Redis caching.\"", "evidence: ''"), "experience.0.bullets.0.evidence"),
    ],
)
def test_load_profile_rejects_blank_required_strings(tmp_path: Path, yaml_text: str, match: str) -> None:
    _rejects(tmp_path, yaml_text, match)


def test_load_profile_rejects_invalid_strength(tmp_path: Path) -> None:
    _rejects(tmp_path, VALID_PROFILE_YAML.replace("strength: flagship", "strength: legendary"), "experience.0.bullets.0.strength")


def test_load_profile_rejects_duplicate_bullet_id_across_experience_and_project(tmp_path: Path) -> None:
    _rejects(tmp_path, VALID_PROFILE_YAML.replace("id: side-project-search", "id: acme-perf"), "duplicate bullet id")


def test_load_profile_rejects_duplicate_project_id(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        "projects:\n  - id: side-project",
        "projects:\n  - id: side-project\n    name: Clone\n    stack: Python\n    dates: Soon\n    tags: []\n    bullets: []\n  - id: side-project",
    )
    _rejects(tmp_path, yaml_text, "duplicate project id")


def test_load_profile_rejects_unknown_variant_project(tmp_path: Path) -> None:
    _rejects(tmp_path, VALID_PROFILE_YAML.replace("projects: [side-project]", "projects: [ghost-project]"), "variants.backend.projects.0")


def test_load_profile_rejects_unknown_variant_bullet(tmp_path: Path) -> None:
    _rejects(
        tmp_path,
        VALID_PROFILE_YAML.replace("bullet_order: [acme-perf, side-project-search]", "bullet_order: [acme-perf, ghost-bullet]"),
        "variants.backend.bullet_order.1",
    )


@pytest.mark.parametrize(
    ("yaml_text", "match"),
    [
        (VALID_PROFILE_YAML.replace("projects: [side-project]", "projects: [side-project, side-project]"), "variants.backend.projects.1"),
        (VALID_PROFILE_YAML.replace("bullet_order: [acme-perf, side-project-search]", "bullet_order: [acme-perf, acme-perf]"), "variants.backend.bullet_order.1"),
    ],
)
def test_load_profile_rejects_duplicate_variant_references(tmp_path: Path, yaml_text: str, match: str) -> None:
    _rejects(tmp_path, yaml_text, match)


@pytest.mark.parametrize(
    ("yaml_text", "match"),
    [
        (VALID_PROFILE_YAML.replace("languages: [Python, Go]", "languages: []"), "skills.languages"),
        (VALID_PROFILE_YAML.replace("languages: [Python, Go]", "languages: [Python, 7]"), "skills.languages.1"),
        (VALID_PROFILE_YAML.replace("languages: [Python, Go]", "7: [Python, Go]"), "skills"),
    ],
)
def test_load_profile_rejects_malformed_skills_values(tmp_path: Path, yaml_text: str, match: str) -> None:
    _rejects(tmp_path, yaml_text, match)


def test_load_profile_rejects_duplicate_do_not_claim_case_insensitively(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        "do_not_claim:\n  - Kubernetes administration",
        "do_not_claim:\n  - Kubernetes administration\n  - kubernetes administration",
    )
    _rejects(tmp_path, yaml_text, "do_not_claim.1")


def test_load_profile_rejects_direct_normalized_skill_do_not_claim_collision(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace("frameworks: [FastAPI, PyTorch]", "frameworks: [FastAPI, kubernetes ADMINISTRATION]")
    _rejects(tmp_path, yaml_text, "skills.frameworks.1")


def test_load_profile_defaults_omitted_do_not_claim_to_empty_tuple(tmp_path: Path) -> None:
    profile = load_profile(_write_profile(tmp_path, VALID_PROFILE_YAML.split("do_not_claim:", 1)[0]))

    assert profile.do_not_claim == ()


def test_load_profile_missing_file_raises_oserror() -> None:
    with pytest.raises(OSError):
        load_profile(Path("/definitely/not/a/real/master_profile.yaml"))
