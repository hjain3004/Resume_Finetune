# M8 Profile Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/profile.py`, a schema-validating loader for `profile/master_profile.yaml` (per `docs/TAILORING_SPEC.md` §1 and `docs/TAILORING_METHODOLOGY.md` §2), so Phase 3's next session (interactive profile construction) has something to validate against.

**Architecture:** One pure module, no I/O beyond reading the one YAML file it's given. Frozen dataclasses for everything with a fabrication/selection invariant riding on it (bullets, variants); loose dicts for `identity`/`education`/`skills` since the spec doesn't fix their key set. A single `load_profile(path)` entrypoint raises `ProfileValidationError` on the first problem found — same fail-fast shape as `src/eligibility.py::load_eligibility_config`.

**Tech Stack:** Python 3.11+, PyYAML (already approved), dataclasses, pytest. No new dependencies.

## Global Constraints

- Python 3.11+, type hints everywhere, dataclasses over dicts at module boundaries (per `CLAUDE.md`).
- No new dependencies — PyYAML is already approved and used by `src/eligibility.py`.
- Tests never touch the network or the filesystem beyond in-memory YAML strings (no fixture files needed — inline strings per the approved design).
- `src/profile.py` has zero SQLite/logging/network side effects — pure parsing, matching `src/eligibility.py`'s module docstring convention.
- Every validation error raises `ProfileValidationError` (a `ValueError` subclass) with a message that names the specific field/id that failed — never a bare `assert` or generic `KeyError`.

---

## File Structure

- Create: `src/profile.py` — dataclasses, `ProfileValidationError`, `load_profile()`.
- Create: `tests/test_profile.py` — one test per validation rule, plus one happy-path test.

Both files are created fresh in Task 1 and grown incrementally; no other files are touched.

## Task 1: Dataclasses, top-level key check, happy-path load

**Files:**
- Create: `src/profile.py`
- Create: `tests/test_profile.py`

**Interfaces:**
- Produces: `ProfileValidationError(ValueError)`; `Strength(str, Enum)` with members `FLAGSHIP`, `SOLID`, `FILLER`; dataclasses `Bullet`, `Experience`, `Project`, `Variant`, `MasterProfile`; `load_profile(path: str | Path) -> MasterProfile`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.profile'`

- [ ] **Step 3: Write minimal implementation**

Create `src/profile.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add master-profile dataclasses, load_profile, top-level key check"
```

---

## Task 2: Bullet required-field validation

**Files:**
- Modify: `src/profile.py` (`_build_bullet`)
- Modify: `tests/test_profile.py`

**Interfaces:**
- Consumes: `Bullet`, `Strength`, `ProfileValidationError` from Task 1.
- Produces: `_build_bullet` now raises `ProfileValidationError` instead of `KeyError`/`ValueError` on bad input; behavior visible to callers of `load_profile`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_profile.py`:

```python
def test_load_profile_rejects_bullet_missing_evidence(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        'evidence: "Profiled the endpoint, found N+1 queries, added Redis caching."\n',
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — the missing-evidence case raises a bare `KeyError`, not `ProfileValidationError`; the bad-strength case raises `ValueError` from `Strength(...)`, not `ProfileValidationError`.

- [ ] **Step 3: Write minimal implementation**

Replace `_build_bullet` in `src/profile.py`:

```python
def _build_bullet(raw: dict[str, Any]) -> Bullet:
    bullet_id = raw.get("id")
    if not bullet_id:
        raise ProfileValidationError("bullet missing required field: id")
    if not raw.get("text"):
        raise ProfileValidationError(f"bullet {bullet_id}: missing required field: text")
    if not raw.get("evidence"):
        raise ProfileValidationError(f"bullet {bullet_id}: missing required field: evidence")
    try:
        strength = Strength(raw.get("strength"))
    except ValueError:
        raise ProfileValidationError(
            f"bullet {bullet_id}: strength must be one of "
            f"{[s.value for s in Strength]}, got {raw.get('strength')!r}"
        ) from None
    return Bullet(
        id=bullet_id,
        text=raw["text"],
        tags=tuple(raw.get("tags", ())),
        metrics=tuple(raw.get("metrics", ())),
        evidence=raw["evidence"],
        strength=strength,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): validate required bullet fields with typed errors"
```

---

## Task 3: Bullet id uniqueness across experience + projects

**Files:**
- Modify: `src/profile.py` (`load_profile`)
- Modify: `tests/test_profile.py`

**Interfaces:**
- Consumes: `Experience`, `Project`, `Bullet` from Task 1; `_build_experience`/`_build_project` unchanged.
- Produces: `load_profile` raises `ProfileValidationError` on duplicate bullet ids anywhere in the profile.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_profile.py`:

```python
def test_load_profile_rejects_duplicate_bullet_id(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace("id: side-project-search", "id: acme-perf")
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="acme-perf"):
        load_profile(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — no uniqueness check exists yet, so `load_profile` returns successfully instead of raising.

- [ ] **Step 3: Write minimal implementation**

In `src/profile.py`, add a helper:

```python
def _check_unique_bullet_ids(experience: tuple[Experience, ...], projects: tuple[Project, ...]) -> None:
    seen: set[str] = set()
    for source in (*experience, *projects):
        for bullet in source.bullets:
            if bullet.id in seen:
                raise ProfileValidationError(f"duplicate bullet id: {bullet.id}")
            seen.add(bullet.id)
```

Replace the body of `load_profile` (from Task 1) to build `experience`/`projects` as named locals and call the check before constructing `MasterProfile`:

```python
def load_profile(path: str | Path) -> MasterProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    missing = [key for key in _REQUIRED_TOP_LEVEL_KEYS if key not in raw]
    if missing:
        raise ProfileValidationError(f"master_profile.yaml missing required key(s): {', '.join(missing)}")

    experience = tuple(_build_experience(e) for e in raw["experience"])
    projects = tuple(_build_project(p) for p in raw["projects"])
    _check_unique_bullet_ids(experience, projects)

    skills = {section: tuple(values) for section, values in raw["skills"].items()}
    variants = {name: _build_variant(v) for name, v in raw["variants"].items()}

    return MasterProfile(
        identity=raw["identity"],
        education=tuple(raw["education"]),
        experience=experience,
        projects=projects,
        skills=skills,
        variants=variants,
        do_not_claim=tuple(raw.get("do_not_claim", ())),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): reject duplicate bullet ids across experience and projects"
```

---

## Task 4: Variant reference validation

**Files:**
- Modify: `src/profile.py` (`load_profile`)
- Modify: `tests/test_profile.py`

**Interfaces:**
- Consumes: `experience`/`projects` locals from Task 3; `Variant` from Task 1.
- Produces: `load_profile` raises `ProfileValidationError` when a variant references an unknown project or bullet id.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_profile.py`:

```python
def test_load_profile_rejects_variant_unknown_project(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace("projects: [side-project]", "projects: [ghost-project]")
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="ghost-project"):
        load_profile(path)


def test_load_profile_rejects_variant_unknown_bullet(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        "bullet_order: [acme-perf, side-project-search]",
        "bullet_order: [acme-perf, ghost-bullet]",
    )
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="ghost-bullet"):
        load_profile(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — no variant-reference check exists yet.

- [ ] **Step 3: Write minimal implementation**

In `src/profile.py`, add:

```python
def _check_variant_references(
    variants: dict[str, Variant],
    experience: tuple[Experience, ...],
    projects: tuple[Project, ...],
) -> None:
    known_project_ids = {p.id for p in projects}
    known_bullet_ids = {b.id for source in (*experience, *projects) for b in source.bullets}
    for name, variant in variants.items():
        for project_id in variant.projects:
            if project_id not in known_project_ids:
                raise ProfileValidationError(f"variant {name}: unknown project id: {project_id}")
        for bullet_id in variant.bullet_order:
            if bullet_id not in known_bullet_ids:
                raise ProfileValidationError(f"variant {name}: unknown bullet id: {bullet_id}")
```

In `load_profile`, after building `variants` (right after the line `variants = {name: _build_variant(v) for name, v in raw["variants"].items()}`):

```python
    _check_variant_references(variants, experience, projects)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): validate variant project/bullet references"
```

---

## Task 5: do_not_claim vs skills cross-check

**Files:**
- Modify: `src/profile.py` (`load_profile`)
- Modify: `tests/test_profile.py`

**Interfaces:**
- Consumes: `skills` dict local from Task 1; `do_not_claim` tuple.
- Produces: `load_profile` raises `ProfileValidationError` when any `do_not_claim` entry also appears in `skills`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_profile.py`:

```python
def test_load_profile_rejects_do_not_claim_listed_as_skill(tmp_path: Path) -> None:
    yaml_text = VALID_PROFILE_YAML.replace(
        "frameworks: [FastAPI, PyTorch]",
        "frameworks: [FastAPI, PyTorch, Kubernetes administration]",
    )
    path = tmp_path / "master_profile.yaml"
    path.write_text(yaml_text)

    with pytest.raises(ProfileValidationError, match="Kubernetes administration"):
        load_profile(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profile.py -v`
Expected: FAIL — no do_not_claim cross-check exists yet.

- [ ] **Step 3: Write minimal implementation**

In `src/profile.py`, add:

```python
def _check_do_not_claim(do_not_claim: tuple[str, ...], skills: dict[str, tuple[str, ...]]) -> None:
    all_skills = {skill for values in skills.values() for skill in values}
    for banned in do_not_claim:
        if banned in all_skills:
            raise ProfileValidationError(f"do_not_claim entry listed as a skill: {banned}")
```

In `load_profile`, replace the final block (from `skills = ...` through the `return`) with:

```python
    skills = {section: tuple(values) for section, values in raw["skills"].items()}
    variants = {name: _build_variant(v) for name, v in raw["variants"].items()}
    _check_variant_references(variants, experience, projects)

    do_not_claim = tuple(raw.get("do_not_claim", ()))
    _check_do_not_claim(do_not_claim, skills)

    return MasterProfile(
        identity=raw["identity"],
        education=tuple(raw["education"]),
        experience=experience,
        projects=projects,
        skills=skills,
        variants=variants,
        do_not_claim=do_not_claim,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_profile.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: same pass count as before this plan, plus 8 new passes in `tests/test_profile.py` (the one pre-existing unrelated `test_insert_discovered_does_not_flag_recent_posting` date-boundary flake may still fail — that's tracked separately, not part of this plan).

- [ ] **Step 6: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): reject do_not_claim entries surfaced as skills"
```

---

## Definition of Done

- All 8 tests in `tests/test_profile.py` pass.
- `python -m pytest -q` shows no new failures beyond the pre-existing, unrelated date-boundary flake.
- `docs/ROADMAP.md`'s Phase 3 section gets a one-line status update noting item 1 (profile loader) is complete, with the date — this is a separate, final step to do by hand after Task 5's commit, not its own task (it's documentation bookkeeping, not implementation).
