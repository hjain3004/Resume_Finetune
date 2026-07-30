# M8 item 2 — Master Profile Schema Reconciliation, Part A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `src/profile.py` to validate the real authored profile at `config/master_profile.yaml`, migrate that file to schema v0.3.0, and author its missing deterministic sections, so the file loads green and exposes token-bounded projections for later tailoring work.

**Architecture:** One pure module, `src/profile.py`, containing a duplicate-key-rejecting YAML read, fail-fast validation raising a single `ProfileValidationError` with path-labeled messages, frozen dataclasses, and three projections over one source of truth. No SQLite, no network, no logging, no I/O beyond reading the one YAML file. Mirrors the existing convention in `src/eligibility.py::load_eligibility_config`.

**Tech Stack:** Python 3.11+, PyYAML, pytest. No new dependencies.

**Authoritative spec:** `docs/superpowers/specs/2026-07-30-m8-profile-schema-reconciliation-design.md`. Read it before starting. Where this plan and the spec disagree, the spec wins — stop and report the discrepancy.

## Global Constraints

- Python 3.11+, type hints everywhere, dataclasses over dicts at module boundaries.
- **No new dependencies.** Approved list: requests, trafilatura, PyYAML, pytest, crawl4ai. Do not add BeautifulSoup, pydantic, jsonschema, or anything else. If you believe you need one, stop and ask.
- **Never `print` inside `src/`.** `src/profile.py` does no logging and no printing at all. `scripts/validate_profile.py` may print — it is a CLI.
- **No SQL outside `src/db.py`.** This work touches no database.
- **Tests never touch the network.** All fixtures are inline YAML strings.
- Interpreter is the project venv: **`.venv/bin/python`** and **`.venv/bin/pytest`**. Bare `python` does not exist on this machine and bare `python3` lacks PyYAML.
- Commits use `feat(m8): ...`, `fix(m8): ...`, `refactor(m8): ...`, or `docs(m8): ...`.
- Run the **entire** suite (`.venv/bin/pytest -q`) before every commit, not just the new test. The pre-existing baseline is 713 tests passing.
- Idempotency is sacred: no change may make a second identical run mutate state.

## Required inputs you must obtain from the user before Task 12

Do **not** invent any of these. If the user is unavailable, complete Tasks 1–11 and 13, then stop and report which inputs are outstanding.

1. **`identity.linkedin`** and **`identity.github`** — full URLs. The resume PDF renders these as the link text "Linkedin" and "GitHub"; the underlying URLs are not recoverable from it.
2. **`do_not_claim`** — the list of technologies the user has touched but cannot defend in an interview (`docs/TAILORING_METHODOLOGY.md` §2). Only the user can supply this. An empty list is a valid answer, but it must be an explicit answer.
3. **Skills conflict resolution.** The current resume lists **Kubernetes** under Developer Tools, and `TAILORING_METHODOLOGY.md` §2 uses Kubernetes as its worked example of a `do_not_claim` term ("deployed to it, never administered it"). Loader rule 15 makes it an error for a term to appear in both. Ask the user which side Kubernetes belongs on. Do not decide this yourself.

## Out of scope for this plan — do not attempt

**Authoring the `campus_marketplace` and `clinical_trial_platform` project entries is NOT part of this plan**, despite being spec §2 decision 4. Those entries require `evidence` (artifact paths into the user's own repositories), `defense`, `interview_risk`, and `known_gaps` — all of which `TAILORING_METHODOLOGY.md` §2 requires be written by the user from real artifacts and "never model-authored". Generating them without repository access would fabricate exactly what this design exists to prevent.

They are deferred to a separate interactive plan, **Part B**. Consequence to accept and report: after this plan, `base_variants.backend` contains only `peerchat_peer_discovery`, and the `backend` variant is not yet renderable. That is the honest state.

Also out of scope: the tailor prompt, critic prompt, renderer, `config/banned_words.txt`, `config/taste.md`, replacing the `CHANGEME` PeerChat URL at `config/master_profile.yaml:98`, and any change to `src/db.py`, `run_ingest.py`, scoring, or eligibility.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/profile.py` (rewrite) | The whole loader: YAML read, validation, dataclasses, projections. Currently 322 lines; expect ~550. Single module, matching `src/eligibility.py`'s one-loader-per-config-file pattern. |
| `tests/test_profile.py` (rewrite) | Inline-YAML unit tests, one per numbered rule, plus projection tests and a real-file integration test. |
| `scripts/validate_profile.py` (create) | CLI wrapper over `load_profile` for checking the file while authoring. |
| `config/master_profile.yaml` (modify) | Migrated to v0.3.0 and extended with `identity`, `education`, `skills`, `base_variants`, `do_not_claim`. |
| `docs/TAILORING_SPEC.md` (modify §1) | Schema section replaced to match reality. |
| `docs/ROADMAP.md`, `docs/DECISIONS.md` (modify) | Status and approved-deviation record. |
| `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md` (modify) | Superseded-by pointer. |

---

## Task 0: Commit the authored profile as a baseline

`config/master_profile.yaml` is currently **untracked**. Without a baseline commit there is no diff to review and no way to roll back a bad migration. This task has no test — it is a safety prerequisite.

**Files:**
- Commit: `config/master_profile.yaml`

- [ ] **Step 1: Confirm the file is untracked**

```bash
git status --short config/master_profile.yaml
```
Expected: `?? config/master_profile.yaml`

- [ ] **Step 2: Confirm it parses as YAML before committing**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('config/master_profile.yaml')); print('parses')"
```
Expected: `parses`

- [ ] **Step 3: Commit it alone, unmodified**

```bash
git add config/master_profile.yaml
git commit -m "feat(m8): add authored master profile (schema v0.2.0, pre-migration baseline)

User-authored 2026-07-30. 38 bullets across 3 projects and 2 experience
entries. Committed unmodified as the rollback point for the v0.3.0 migration
in docs/superpowers/plans/2026-07-30-m8-profile-schema-reconciliation.md.

Known defects at this commit, fixed by the migration: duplicate date_note key
at :1150/:1157 causing silent data loss, and a CHANGEME placeholder URL at :98."
```

---

## Task 1: Duplicate-key-rejecting YAML read (rule 1)

PyYAML silently keeps the **last** of duplicated mapping keys. The authored file has a real instance at `config/master_profile.yaml:1150`/`:1157`, where a `CONFIRMED` internship date note is silently discarded in favour of a stale one. For a file whose purpose is preventing fabrication, silent last-wins is unacceptable.

**Files:**
- Modify: `src/profile.py` (replace the module; start with just this piece)
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `ProfileValidationError(ValueError)`; `_read_yaml(path: Path) -> Any` raising on duplicate keys and malformed YAML.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_profile.py` entirely with:

```python
import pytest

from src.profile import ProfileValidationError, load_profile


def _write(tmp_path, text: str):
    path = tmp_path / "master_profile.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_duplicate_mapping_key_is_rejected(tmp_path):
    path = _write(tmp_path, "identity:\n  name: A\n  name: B\n")
    with pytest.raises(ProfileValidationError, match="duplicate key"):
        load_profile(path)


def test_malformed_yaml_is_rejected(tmp_path):
    path = _write(tmp_path, "identity: [unclosed\n")
    with pytest.raises(ProfileValidationError, match="malformed YAML"):
        load_profile(path)


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_profile(tmp_path / "nope.yaml")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: FAIL — the current loader accepts duplicate keys.

- [ ] **Step 3: Implement the duplicate-rejecting read**

Replace the top of `src/profile.py`:

```python
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


def load_profile(path: str | Path) -> "MasterProfile":
    raw = _read_yaml(Path(path))
    root = _require_mapping(raw, "master_profile.yaml")
    raise NotImplementedError("built up across Tasks 2-9")
```

The `except ProfileValidationError: raise` clause must come **before** the `yaml.YAMLError` clause — PyYAML wraps constructor exceptions, and without it the duplicate-key message is swallowed and misreported as malformed YAML.

- [ ] **Step 4: Run to verify these three pass**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): reject duplicate YAML keys in profile loader"
```

---

## Task 2: Scalar and container helpers, plus the ASCII rule (rules 7, 13)

Rule 7 is ASCII-only for **every** string in the document, with exactly one exemption: the `ats.forbidden_chars` list and the **keys** of `ats.substitutions`. Those decode from `\uXXXX` escapes into real non-ASCII characters and exist precisely to declare what is banned — without the exemption the loader rejects the file for containing its own policy. There are exactly 8 such characters today.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `_require_mapping(value, path) -> dict`, `_require_list(value, path) -> list`, `_require_string(value, path) -> str`, `_string_list(value, path, *, allow_empty=True) -> tuple[str, ...]`, `_require_positive_int(value, path) -> int`, `_check_ascii(value, path) -> None`, `_required_field(raw, field, path) -> str`.

- [ ] **Step 1: Write the tests**

Append to `tests/test_profile.py`. These reference `_MINIMAL_PROFILE`, the shared happy-path fixture defined in **Task 7 Step 1**; until that lands they error with `NameError`, which is expected and called out in Step 2.

```python
def test_non_ascii_in_phrasing_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "short: Built a thing", "short: Built a thing — with an em dash"))
    with pytest.raises(ProfileValidationError, match="non-ASCII"):
        load_profile(path)


def test_ats_forbidden_chars_may_be_non_ascii(tmp_path):
    # The exemption: declaring a banned character is not using it.
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    assert "—" in profile.ats["forbidden_chars"]


def test_blank_string_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "name: Himanshu Jain", 'name: "   "'))
    with pytest.raises(ProfileValidationError, match="nonempty"):
        load_profile(path)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "ascii or blank"`
Expected: FAIL with `NameError: _MINIMAL_PROFILE`. These become real assertions once Task 7 defines the fixture.

- [ ] **Step 3: Implement the helpers**

```python
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
```

- [ ] **Step 4: Run**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: Task 1's three still pass; the new three still error on the missing fixture. Nothing else breaks.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add profile validation helpers and ASCII rule"
```

---

## Task 3: Bullet dataclass (rules 3, 4, 5, 6, 12)

Reality the loader must accept: of the 38 authored bullets, 22 carry `long`+`medium`+`short`, 12 carry `medium`+`short`, 4 carry `short` only. So `short` is required and the other two tiers are optional.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `ClaimType(str, Enum)`; `BLOCKED_CLAIM_TYPES: frozenset[ClaimType]`; `Phrasings` frozen dataclass with `short: str`, `medium: str | None`, `long: str | None` and method `best_within(limit: int) -> str`; `Bullet` frozen dataclass with `id: str`, `claim_type: ClaimType`, `priority: int`, `phrasings: Phrasings`, `evidence: tuple[str, ...]`, `keywords_hit: tuple[str, ...]`, `defense: str`, `interview_risk: str`, and property `is_blocked: bool`; `_build_bullet(value, path) -> Bullet`.

- [ ] **Step 1: Write the tests**

```python
from src.profile import ClaimType


def test_bullet_requires_short_phrasing(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "short: Built a thing", "tiny: Built a thing"))
    with pytest.raises(ProfileValidationError, match=r"phrasings"):
        load_profile(path)


def test_unknown_claim_type_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "claim_type: verified", "claim_type: probably_true", 1))
    with pytest.raises(ProfileValidationError, match="claim_type"):
        load_profile(path)


def test_non_verified_claim_requires_defense(tmp_path):
    # Contract C3: any claim_type other than `verified` must carry a defense.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "claim_type: verified", "claim_type: estimated", 1))
    with pytest.raises(ProfileValidationError, match="defense"):
        load_profile(path)


def test_empty_evidence_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        '        evidence:\n          - "src/thing.py: does the thing"\n',
        "        evidence: []\n"))
    with pytest.raises(ProfileValidationError, match="nonempty string list"):
        load_profile(path)


def test_null_evidence_is_rejected(tmp_path):
    # Deleting the only list item leaves `evidence:` parsing as None, which is
    # a different failure path than an explicitly empty list.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        '          - "src/thing.py: does the thing"\n', ""))
    with pytest.raises(ProfileValidationError, match="expected list, got NoneType"):
        load_profile(path)


def test_priority_must_be_positive_int(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("priority: 1", "priority: 0", 1))
    with pytest.raises(ProfileValidationError, match="positive integer"):
        load_profile(path)


def test_priority_rejects_boolean(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("priority: 1", "priority: true", 1))
    with pytest.raises(ProfileValidationError, match="expected integer"):
        load_profile(path)


def test_verified_bullet_is_not_blocked(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    bullet = profile.projects[0].bullets[0]
    assert bullet.claim_type is ClaimType.VERIFIED
    assert bullet.is_blocked is False


def test_best_within_falls_back_to_short(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    phrasings = profile.projects[0].bullets[0].phrasings
    assert phrasings.best_within(5) == "Built a thing"
    assert phrasings.best_within(500) == "Built a thing"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "phrasing or claim_type or defense or evidence or priority or blocked or best_within"`
Expected: FAIL — `ClaimType` does not exist.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: Task 1's tests pass; fixture-dependent tests still error on `_MINIMAL_PROFILE` only.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add Bullet, Phrasings, and ClaimType to profile loader"
```

---

## Task 4: Project and Experience dataclasses (rule 2)

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `Project` frozen dataclass with `id, name, display_title, tech_line, ownership_boundary, bullets, keywords_exact, keywords_topical, metric_ledger, metric_scope, known_gaps`; `Experience` frozen dataclass with `id, employer, title, scope_line, display_date, ownership_boundary, bullets, keywords_exact, keywords_topical, metric_ledger, metric_scope, known_gaps`; `_build_projects(value) -> tuple[Project, ...]`; `_build_experience_list(value) -> tuple[Experience, ...]`; `_check_unique_bullet_ids(experience, projects) -> None`.
- Consumes: `_build_metric_ledger`, `_build_metric_scope` (Task 5), `_build_known_gaps` (Task 6). Those three do not exist yet, so this task's code will `NameError` until Tasks 5 and 6 land. Implement Tasks 4, 5, and 6 back to back and run the tests only after Task 6.

- [ ] **Step 1: Write the tests**

```python
def test_duplicate_bullet_id_across_entries_is_rejected(tmp_path):
    # Contract C1: bullet ids are the fabrication anchor, globally unique.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("id: exp_b1", "id: proj_b1"))
    with pytest.raises(ProfileValidationError, match="duplicate bullet id: proj_b1"):
        load_profile(path)


def test_duplicate_project_id_is_rejected(tmp_path):
    doubled = _MINIMAL_PROFILE.replace(
        "projects:\n", "projects:\n" + _DUPLICATE_PROJECT_BLOCK, 1
    )
    with pytest.raises(ProfileValidationError, match="duplicate project id"):
        load_profile(_write(tmp_path, doubled))
```

`_DUPLICATE_PROJECT_BLOCK` is defined alongside `_MINIMAL_PROFILE` in Task 7 Step 1: a copy of the fixture's project with the same `id` but distinct bullet ids, so this test isolates project-id collision from bullet-id collision.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "duplicate_bullet or duplicate_project"`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Do not run yet — proceed to Task 5**

`_build_metric_ledger`, `_build_metric_scope`, and `_build_known_gaps` are undefined until Tasks 5 and 6. Running now yields `NameError`. Continue.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add Project and Experience with unique-id checks"
```

---

## Task 5: `metric_ledger` and `metric_scope` (rules 10, 11)

The authored file uses ten ad-hoc `status` values conflating provenance with printability. Replace with two orthogonal fields so a prohibited number becomes structurally unprintable.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `Provenance(str, Enum)` = `COUNTED, DOC_BACKED, CONFIGURED, ESTIMATED, UNSOURCED, CONTRADICTED, NONE`; `NON_RENDERABLE_PROVENANCES: frozenset[Provenance]`; `MetricEntry` frozen dataclass with `value: Any`, `provenance: Provenance`, `renderable: bool`, `render_as: str | None`, `note: str`; `_build_metric_ledger(raw, path) -> dict[str, MetricEntry]`; `_build_metric_scope(raw, path) -> dict[str, str]`.

- [ ] **Step 1: Write the tests**

```python
from src.profile import Provenance


def test_prohibited_provenance_cannot_be_renderable(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "provenance: counted", "provenance: contradicted"))
    with pytest.raises(ProfileValidationError, match="renderable"):
        load_profile(path)


def test_metric_ledger_entry_must_be_mapping(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "      tests:\n"
        "        value: 12\n"
        "        provenance: counted\n"
        "        renderable: true\n",
        "      tests: just-a-string\n"))
    with pytest.raises(ProfileValidationError, match="expected mapping"):
        load_profile(path)


def test_metric_ledger_rejects_unknown_key(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "        renderable: true\n", "        renderable: true\n        bogus: 1\n"))
    with pytest.raises(ProfileValidationError, match="unknown key"):
        load_profile(path)


def test_metric_ledger_renderable_must_be_boolean(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "renderable: true", 'renderable: "yes"'))
    with pytest.raises(ProfileValidationError, match="expected boolean"):
        load_profile(path)


def test_metric_ledger_happy_path(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    entry = profile.projects[0].metric_ledger["tests"]
    assert entry.value == 12
    assert entry.provenance is Provenance.COUNTED
    assert entry.renderable is True
    assert profile.projects[0].metric_scope["test_scope"] == "unit tests only"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k metric`
Expected: FAIL — `Provenance` does not exist.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Do not run yet — proceed to Task 6**

`_build_known_gaps` is still undefined. Continue.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): normalize metric_ledger to provenance and renderable"
```

---

## Task 6: `known_gaps` severity/status split

The authored file puts `resolved` (a state, 5 uses) in the same field as `high`/`medium`/`low` (severities). Split them.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `Severity(str, Enum)` = `HIGH, MEDIUM, LOW`; `GapStatus(str, Enum)` = `OPEN, RESOLVED`; `KnownGap` frozen dataclass with `id, severity, status, detail, fix`; `_build_known_gaps(raw, path) -> tuple[KnownGap, ...]`.

- [ ] **Step 1: Write the tests**

```python
from src.profile import GapStatus, Severity


def test_resolved_is_not_a_severity(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "severity: medium", "severity: resolved"))
    with pytest.raises(ProfileValidationError, match="severity"):
        load_profile(path)


def test_known_gap_defaults_to_open(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    gap = profile.projects[0].known_gaps[0]
    assert gap.severity is Severity.MEDIUM
    assert gap.status is GapStatus.OPEN
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "severity or known_gap"`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: Task 1's three pass; everything else still errors on the missing `_MINIMAL_PROFILE` fixture. No `NameError` for `_build_metric_ledger` / `_build_known_gaps` any more.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): split known_gaps severity from status"
```

---

## Task 7: Top level — identity, education, skills, do_not_claim, and the shared fixture (rules 13, 14, 15)

This task defines `_MINIMAL_PROFILE`, which every earlier task's tests reference. After Tasks 7 and 8 land, all previously-written tests must pass.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `MasterProfile` frozen dataclass with `schema_version: str`, `last_updated: str`, `ats: dict[str, Any]`, `identity: dict[str, str]`, `education: tuple[dict[str, str], ...]`, `skills: dict[str, tuple[str, ...]]`, `projects: tuple[Project, ...]`, `experience: tuple[Experience, ...]`, `base_variants: dict[str, BaseVariant]`, `do_not_claim: tuple[str, ...]`; a working `load_profile`.
- Consumes: `_build_base_variants` (Task 8). Implement Tasks 7 and 8 back to back.

- [ ] **Step 1: Add the shared fixtures**

Insert immediately after the imports in `tests/test_profile.py`:

```python
_MINIMAL_PROFILE = """
schema_version: "0.3.0"
last_updated: "2026-07-30"
ats:
  charset_policy: ascii_strict
  forbidden_chars: ["\\u2014"]
  substitutions:
    "\\u2014": "-"
identity:
  name: Himanshu Jain
  email: himanshu.jain@sjsu.edu
education:
  - institution: San Jose State University
    degree: Master of Science in Software Engineering
    display_date: "Aug. 2025 - May 2027"
skills:
  languages: ["Python", "Java"]
projects:
  - id: proj_one
    name: Project One
    display_title: Project One - A Thing
    ownership_boundary: "SAFE TO CLAIM: all of it."
    tech:
      tech_line: "Python, pytest"
    keywords:
      exact: ["Python"]
      topical: ["backend"]
    metric_ledger:
      tests:
        value: 12
        provenance: counted
        renderable: true
    metric_scope:
      test_scope: "unit tests only"
    known_gaps:
      - id: gap_one
        severity: medium
        detail: "A gap."
        fix: "Close it."
    bullets:
      - id: proj_b1
        claim_type: verified
        priority: 1
        phrasings:
          short: Built a thing
        evidence:
          - "src/thing.py: does the thing"
        keywords_hit: ["Python"]
experience:
  - id: exp_one
    employer: Amdocs
    title: Software Developer
    scope_line: "Did backend work."
    display_date: "July 2023 - June 2025"
    ownership_boundary: "SAFE TO CLAIM: my slice."
    bullets:
      - id: exp_b1
        claim_type: verified
        priority: 1
        phrasings:
          short: Shipped a service
        evidence:
          - "prep doc: service description"
base_variants:
  backend:
    projects: [proj_one]
    bullet_order: [exp_b1, proj_b1]
do_not_claim:
  - Kubernetes
"""

_DUPLICATE_PROJECT_BLOCK = """  - id: proj_one
    name: Project One Again
    display_title: Project One Again
    ownership_boundary: "SAFE TO CLAIM: all of it."
    tech:
      tech_line: "Python"
    bullets:
      - id: proj_b_dup
        claim_type: verified
        priority: 1
        phrasings:
          short: Built another thing
        evidence:
          - "src/other.py: does another thing"
"""
```

- [ ] **Step 2: Add the top-level tests**

```python
def test_happy_path_loads_every_section(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    assert profile.schema_version == "0.3.0"
    assert profile.identity["name"] == "Himanshu Jain"
    assert profile.education[0]["institution"] == "San Jose State University"
    assert profile.skills["languages"] == ("Python", "Java")
    assert len(profile.projects) == 1
    assert len(profile.experience) == 1
    assert profile.do_not_claim == ("Kubernetes",)


def test_missing_required_top_level_key_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace("identity:", "identity_typo:", 1))
    with pytest.raises(ProfileValidationError, match="identity: missing required key"):
        load_profile(path)


def test_do_not_claim_defaults_to_empty(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "do_not_claim:\n  - Kubernetes\n", ""))
    assert load_profile(path).do_not_claim == ()


def test_duplicate_do_not_claim_entry_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "  - Kubernetes\n", "  - Kubernetes\n  - kubernetes\n"))
    with pytest.raises(ProfileValidationError, match="duplicate entry"):
        load_profile(path)


def test_do_not_claim_term_may_not_appear_in_skills(tmp_path):
    # TAILORING_METHODOLOGY.md §2: never surface these as skills.
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        'languages: ["Python", "Java"]', 'languages: ["Python", "kubernetes"]'))
    with pytest.raises(
        ProfileValidationError, match="do_not_claim term listed as skill"
    ):
        load_profile(path)


def test_skills_category_may_not_be_empty(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        'languages: ["Python", "Java"]', "languages: []"))
    with pytest.raises(ProfileValidationError, match="nonempty string list"):
        load_profile(path)
```

- [ ] **Step 3: Implement the top level**

```python
_REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "last_updated",
    "ats",
    "identity",
    "education",
    "skills",
    "projects",
    "experience",
    "base_variants",
)


@dataclass(frozen=True)
class MasterProfile:
    schema_version: str
    last_updated: str
    ats: dict[str, Any]
    identity: dict[str, str]
    education: tuple[dict[str, str], ...]
    skills: dict[str, tuple[str, ...]]
    projects: tuple[Project, ...]
    experience: tuple[Experience, ...]
    base_variants: dict[str, "BaseVariant"]
    do_not_claim: tuple[str, ...]


def _normalize_term(value: str) -> str:
    return " ".join(value.casefold().split())


def _build_str_mapping(value: Any, path: str) -> dict[str, str]:
    raw = _require_mapping(value, path)
    result: dict[str, str] = {}
    for key, item in raw.items():
        name = _require_string(key, path)
        result[name] = _require_string(item, f"{path}.{name}")
    return result


def _build_education(value: Any) -> tuple[dict[str, str], ...]:
    return tuple(
        _build_str_mapping(entry, f"education.{index}")
        for index, entry in enumerate(_require_list(value, "education"))
    )


def _build_skills(value: Any) -> dict[str, tuple[str, ...]]:
    raw = _require_mapping(value, "skills")
    result: dict[str, tuple[str, ...]] = {}
    for key, item in raw.items():
        category = _require_string(key, "skills")
        result[category] = _string_list(
            item, f"skills.{category}", allow_empty=False
        )
    return result


def _build_do_not_claim(value: Any) -> tuple[str, ...]:
    entries = _string_list(value, "do_not_claim")
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        normalized = _normalize_term(entry)
        if normalized in seen:
            raise ProfileValidationError(
                f"do_not_claim.{index}: duplicate entry: {entry}"
            )
        seen.add(normalized)
    return entries


def _check_do_not_claim_against_skills(
    do_not_claim: tuple[str, ...], skills: dict[str, tuple[str, ...]]
) -> None:
    banned = {_normalize_term(entry) for entry in do_not_claim}
    if not banned:
        return
    for category, values in skills.items():
        for index, skill in enumerate(values):
            if _normalize_term(skill) in banned:
                raise ProfileValidationError(
                    f"skills.{category}.{index}: do_not_claim term listed as "
                    f"skill: {skill}"
                )


def load_profile(path: str | Path) -> MasterProfile:
    raw = _read_yaml(Path(path))
    root = _require_mapping(raw, "master_profile.yaml")
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in root:
            raise ProfileValidationError(
                f"master_profile.yaml.{key}: missing required key"
            )

    projects = _build_projects(root["projects"])
    experience = _build_experience_list(root["experience"])
    skills = _build_skills(root["skills"])
    do_not_claim = _build_do_not_claim(root.get("do_not_claim", []))

    _check_unique_bullet_ids(experience, projects)
    _check_do_not_claim_against_skills(do_not_claim, skills)

    base_variants = _build_base_variants(root["base_variants"], projects, experience)

    return MasterProfile(
        schema_version=_require_string(root["schema_version"], "schema_version"),
        last_updated=_require_string(root["last_updated"], "last_updated"),
        ats=_require_mapping(root["ats"], "ats"),
        identity=_build_str_mapping(root["identity"], "identity"),
        education=_build_education(root["education"]),
        skills=skills,
        projects=projects,
        experience=experience,
        base_variants=base_variants,
        do_not_claim=do_not_claim,
    )
```

Delete the `raise NotImplementedError` stub from Task 1.

- [ ] **Step 4: Do not run yet — proceed to Task 8**

`_build_base_variants` is undefined. Continue.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add top-level profile sections and do_not_claim guard"
```

---

## Task 8: `base_variants` (rules 8, 9, 16)

Rule 9 is the load-bearing guarantee: a bullet whose `claim_type` is `ownership_unresolved` or `needs_input` cannot be referenced by a base variant, making "blocked claims never render" a load-time failure rather than a render-time hope. The authored file has four such bullets.

Rule 16 gives gate L6's flagship-ordering rule a mechanical meaning: within one `bullet_order`, no bullet may precede one of strictly lower `priority` **drawn from the same project or experience entry**. Cross-entry ordering is unconstrained — interleaving entries is legitimate.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `BaseVariant` frozen dataclass with `projects: tuple[str, ...]`, `bullet_order: tuple[str, ...]`; `_build_base_variants(value, projects, experience) -> dict[str, BaseVariant]`.

- [ ] **Step 1: Write the tests**

```python
def test_unknown_project_reference_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "projects: [proj_one]", "projects: [does_not_exist]"))
    with pytest.raises(ProfileValidationError, match="unknown project id"):
        load_profile(path)


def test_unknown_bullet_reference_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "bullet_order: [exp_b1, proj_b1]", "bullet_order: [nope]"))
    with pytest.raises(ProfileValidationError, match="unknown bullet id"):
        load_profile(path)


def test_duplicate_reference_within_variant_is_rejected(tmp_path):
    path = _write(tmp_path, _MINIMAL_PROFILE.replace(
        "bullet_order: [exp_b1, proj_b1]", "bullet_order: [proj_b1, proj_b1]"))
    with pytest.raises(ProfileValidationError, match="duplicate reference"):
        load_profile(path)


def test_blocked_bullet_cannot_be_referenced(tmp_path):
    # Rule 9: ownership_unresolved must not render, enforced at load time.
    blocked = _MINIMAL_PROFILE.replace(
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
        "      - id: proj_b1\n        claim_type: ownership_unresolved\n"
        "        priority: 1\n        defense: Attribution unconfirmed.\n",
    )
    with pytest.raises(ProfileValidationError, match="blocked"):
        load_profile(_write(tmp_path, blocked))


def test_priority_ordering_within_an_entry_is_enforced(tmp_path):
    # Rule 16: a priority-2 bullet may not precede a priority-1 bullet
    # from the same entry.
    reordered = _MINIMAL_PROFILE.replace(
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
        "      - id: proj_b0\n        claim_type: verified\n        priority: 2\n"
        "        phrasings:\n          short: Lower priority thing\n"
        "        evidence:\n"
        '          - "src/other.py: other"\n'
        "      - id: proj_b1\n        claim_type: verified\n        priority: 1\n",
    ).replace("bullet_order: [exp_b1, proj_b1]", "bullet_order: [proj_b0, proj_b1]")
    with pytest.raises(ProfileValidationError, match="priority"):
        load_profile(_write(tmp_path, reordered))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "reference or blocked or ordering"`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
@dataclass(frozen=True)
class BaseVariant:
    projects: tuple[str, ...]
    bullet_order: tuple[str, ...]


def _check_references_unique(references: tuple[str, ...], path: str) -> None:
    seen: set[str] = set()
    for index, reference in enumerate(references):
        if reference in seen:
            raise ProfileValidationError(
                f"{path}.{index}: duplicate reference: {reference}"
            )
        seen.add(reference)


def _build_base_variants(
    value: Any,
    projects: tuple[Project, ...],
    experience: tuple[Experience, ...],
) -> dict[str, BaseVariant]:
    raw = _require_mapping(value, "base_variants")
    known_project_ids = {project.id for project in projects}
    # bullet id -> (owning entry id, bullet)
    bullet_index: dict[str, tuple[str, Bullet]] = {
        bullet.id: (source.id, bullet)
        for source in (*projects, *experience)
        for bullet in source.bullets
    }

    variants: dict[str, BaseVariant] = {}
    for raw_name, raw_variant in raw.items():
        name = _require_string(raw_name, "base_variants")
        variant_path = f"base_variants.{name}"
        mapping = _require_mapping(raw_variant, variant_path)
        variant = BaseVariant(
            projects=_string_list(
                mapping.get("projects", ()), f"{variant_path}.projects"
            ),
            bullet_order=_string_list(
                mapping.get("bullet_order", ()), f"{variant_path}.bullet_order"
            ),
        )
        _check_references_unique(variant.projects, f"{variant_path}.projects")
        _check_references_unique(variant.bullet_order, f"{variant_path}.bullet_order")

        for index, project_id in enumerate(variant.projects):
            if project_id not in known_project_ids:
                raise ProfileValidationError(
                    f"{variant_path}.projects.{index}: unknown project id: {project_id}"
                )

        # Rule 8, then rule 9, then rule 16, in reference order.
        last_priority: dict[str, int] = {}
        for index, bullet_id in enumerate(variant.bullet_order):
            entry_path = f"{variant_path}.bullet_order.{index}"
            if bullet_id not in bullet_index:
                raise ProfileValidationError(
                    f"{entry_path}: unknown bullet id: {bullet_id}"
                )
            owner_id, bullet = bullet_index[bullet_id]
            if bullet.is_blocked:
                raise ProfileValidationError(
                    f"{entry_path}: references blocked bullet {bullet_id} "
                    f"(claim_type={bullet.claim_type.value})"
                )
            previous = last_priority.get(owner_id)
            if previous is not None and bullet.priority < previous:
                raise ProfileValidationError(
                    f"{entry_path}: bullet {bullet_id} has priority "
                    f"{bullet.priority} but follows priority {previous} from the "
                    f"same entry {owner_id}"
                )
            last_priority[owner_id] = bullet.priority

        variants[name] = variant
    return variants
```

- [ ] **Step 4: Run the whole file — every test from Tasks 1-8 must now pass**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: all pass, no errors, no `NameError`.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: all pass. `tests/test_profile.py` is rewritten so the total count changes from 713; no test file other than `tests/test_profile.py` may fail.

- [ ] **Step 6: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add base_variants with blocked-bullet and priority-order gates"
```

---

## Task 9: Projection API

`interview_risk` and `known_gaps` are written for a human preparing for an interview and must never enter a tailoring prompt. Feeding the whole ~1,900-line file into every tailoring call is the expensive mistake this design prevents.

**Files:**
- Modify: `src/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces: `TailoringBullet` frozen dataclass with `id, phrasings, keywords_hit, claim_type, priority`; `CriticBullet` adding `evidence, defense, ownership_boundary`; `TailoringView` with `identity, education, skills, do_not_claim, bullets`; `CriticView` with `identity, skills, do_not_claim, bullets`; methods `MasterProfile.for_tailoring(base_variant: str) -> TailoringView` and `MasterProfile.for_critic(base_variant: str) -> CriticView`, each raising `ProfileValidationError` on an unknown variant name.

- [ ] **Step 1: Write the tests**

```python
def test_for_tailoring_omits_human_only_fields(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_tailoring("backend")
    bullet = view.bullets[0]
    assert not hasattr(bullet, "evidence")
    assert not hasattr(bullet, "interview_risk")
    assert not hasattr(bullet, "defense")
    assert bullet.id == "exp_b1"


def test_for_tailoring_carries_identity_skills_and_do_not_claim(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_tailoring("backend")
    assert view.identity["name"] == "Himanshu Jain"
    assert view.skills["languages"] == ("Python", "Java")
    assert view.do_not_claim == ("Kubernetes",)


def test_for_tailoring_follows_bullet_order(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_tailoring("backend")
    assert [bullet.id for bullet in view.bullets] == ["exp_b1", "proj_b1"]


def test_for_critic_includes_evidence_and_defense(tmp_path):
    view = load_profile(_write(tmp_path, _MINIMAL_PROFILE)).for_critic("backend")
    bullet = view.bullets[0]
    assert bullet.evidence
    assert hasattr(bullet, "defense")
    assert bullet.ownership_boundary
    assert not hasattr(bullet, "interview_risk")


def test_unknown_base_variant_is_rejected(tmp_path):
    profile = load_profile(_write(tmp_path, _MINIMAL_PROFILE))
    with pytest.raises(ProfileValidationError, match="unknown base_variant"):
        profile.for_tailoring("quantum")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_profile.py -q -k "for_tailoring or for_critic or unknown_base"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add above `MasterProfile`:

```python
@dataclass(frozen=True)
class TailoringBullet:
    id: str
    phrasings: Phrasings
    keywords_hit: tuple[str, ...]
    claim_type: ClaimType
    priority: int


@dataclass(frozen=True)
class CriticBullet:
    id: str
    phrasings: Phrasings
    keywords_hit: tuple[str, ...]
    claim_type: ClaimType
    priority: int
    evidence: tuple[str, ...]
    defense: str
    ownership_boundary: str


@dataclass(frozen=True)
class TailoringView:
    identity: dict[str, str]
    education: tuple[dict[str, str], ...]
    skills: dict[str, tuple[str, ...]]
    do_not_claim: tuple[str, ...]
    bullets: tuple[TailoringBullet, ...]


@dataclass(frozen=True)
class CriticView:
    identity: dict[str, str]
    skills: dict[str, tuple[str, ...]]
    do_not_claim: tuple[str, ...]
    bullets: tuple[CriticBullet, ...]
```

Add these methods inside `MasterProfile`:

```python
    def _ordered_bullets(self, base_variant: str) -> tuple[tuple[str, Bullet], ...]:
        """(owning entry's ownership_boundary, bullet) in bullet_order order.

        Blocked bullets cannot appear here: rule 9 rejects any base_variant
        referencing one at load time.
        """
        if base_variant not in self.base_variants:
            known = ", ".join(sorted(self.base_variants)) or "(none)"
            raise ProfileValidationError(
                f"unknown base_variant: {base_variant!r}; known: {known}"
            )
        index: dict[str, tuple[str, Bullet]] = {
            bullet.id: (source.ownership_boundary, bullet)
            for source in (*self.projects, *self.experience)
            for bullet in source.bullets
        }
        return tuple(
            index[bullet_id]
            for bullet_id in self.base_variants[base_variant].bullet_order
        )

    def for_tailoring(self, base_variant: str) -> TailoringView:
        return TailoringView(
            identity=self.identity,
            education=self.education,
            skills=self.skills,
            do_not_claim=self.do_not_claim,
            bullets=tuple(
                TailoringBullet(
                    id=bullet.id,
                    phrasings=bullet.phrasings,
                    keywords_hit=bullet.keywords_hit,
                    claim_type=bullet.claim_type,
                    priority=bullet.priority,
                )
                for _, bullet in self._ordered_bullets(base_variant)
            ),
        )

    def for_critic(self, base_variant: str) -> CriticView:
        return CriticView(
            identity=self.identity,
            skills=self.skills,
            do_not_claim=self.do_not_claim,
            bullets=tuple(
                CriticBullet(
                    id=bullet.id,
                    phrasings=bullet.phrasings,
                    keywords_hit=bullet.keywords_hit,
                    claim_type=bullet.claim_type,
                    priority=bullet.priority,
                    evidence=bullet.evidence,
                    defense=bullet.defense,
                    ownership_boundary=boundary,
                )
                for boundary, bullet in self._ordered_bullets(base_variant)
            ),
        )
```

- [ ] **Step 4: Run**

Run: `.venv/bin/pytest tests/test_profile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/profile.py tests/test_profile.py
git commit -m "feat(m8): add tailoring and critic projections over the profile"
```

---

## Task 10: `scripts/validate_profile.py`

**Files:**
- Create: `scripts/validate_profile.py`
- Test: `tests/test_validate_profile.py`

**Interfaces:**
- Consumes: `load_profile`, `ProfileValidationError` from `src.profile`; `_MINIMAL_PROFILE` from `tests.test_profile`.
- Produces: `main(argv: list[str] | None = None) -> int` returning `0` valid, `1` validation failure, `2` unreadable file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_validate_profile.py`:

```python
from scripts.validate_profile import main
from tests.test_profile import _MINIMAL_PROFILE


def test_valid_profile_returns_zero(tmp_path, capsys):
    path = tmp_path / "p.yaml"
    path.write_text(_MINIMAL_PROFILE, encoding="utf-8")
    assert main([str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_invalid_profile_returns_one_and_reports_path(tmp_path, capsys):
    path = tmp_path / "p.yaml"
    path.write_text(
        _MINIMAL_PROFILE.replace("identity:", "identity_typo:", 1), encoding="utf-8"
    )
    assert main([str(path)]) == 1
    assert "identity: missing required key" in capsys.readouterr().err


def test_unreadable_file_returns_two(tmp_path, capsys):
    assert main([str(tmp_path / "nope.yaml")]) == 2
    assert "UNREADABLE" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_validate_profile.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```python
"""Validate config/master_profile.yaml against the M8 loader.

Usage: python -m scripts.validate_profile [PATH]
Exit codes: 0 valid, 1 validation error, 2 file unreadable.
"""

from __future__ import annotations

import argparse
import sys

from src.profile import ProfileValidationError, load_profile

_DEFAULT_PATH = "config/master_profile.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the master profile.")
    parser.add_argument("path", nargs="?", default=_DEFAULT_PATH)
    args = parser.parse_args(argv)

    try:
        profile = load_profile(args.path)
    except ProfileValidationError as exc:
        print(f"INVALID {args.path}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"UNREADABLE {args.path}: {exc}", file=sys.stderr)
        return 2

    sources = (*profile.projects, *profile.experience)
    bullets = sum(len(source.bullets) for source in sources)
    blocked = sum(
        1 for source in sources for bullet in source.bullets if bullet.is_blocked
    )
    print(
        f"OK {args.path}: schema {profile.schema_version}, "
        f"{len(profile.projects)} project(s), {len(profile.experience)} experience "
        f"entry(ies), {bullets} bullet(s) ({blocked} blocked), "
        f"base_variants: {', '.join(sorted(profile.base_variants)) or '(none)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run**

Run: `.venv/bin/pytest tests/test_validate_profile.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate_profile.py tests/test_validate_profile.py
git commit -m "feat(m8): add validate_profile CLI"
```

---

## Task 11: Migrate `config/master_profile.yaml` to v0.3.0

Mechanical edits to the real file. Every step is verified by a command, not by eye. If any assertion fails, **stop** — the file is not what this plan assumes.

**Files:**
- Modify: `config/master_profile.yaml`

- [ ] **Step 1: Rename bullet-level `variants:` to `phrasings:`**

All 38 occurrences are at bullet level; the key has no other use.

```bash
.venv/bin/python - <<'PY'
import re, pathlib
p = pathlib.Path("config/master_profile.yaml")
new, count = re.subn(r"(?m)^(\s*)variants:$", r"\1phrasings:", p.read_text(encoding="utf-8"))
assert count == 38, f"expected 38 renames, made {count}"
p.write_text(new, encoding="utf-8")
print(f"renamed {count}")
PY
```
Expected: `renamed 38`

- [ ] **Step 2: Delete the stale duplicate `date_note`**

`bank_integration_internship` declares `date_note` twice. Keep the block beginning `CONFIRMED 2026-07-30: 06/2026 - 08/2026`; delete the later block beginning `Not recoverable from the repo.`, including its `date_note:` key line and every continuation line. Edit by hand — which one survives is a semantic choice, not a regex.

```bash
grep -c "date_note:" config/master_profile.yaml
```
Expected: `1`

- [ ] **Step 3: Delete every `theme:` line**

```bash
.venv/bin/python - <<'PY'
import re, pathlib
p = pathlib.Path("config/master_profile.yaml")
new, count = re.subn(r"(?m)^\s*theme:.*\n", "", p.read_text(encoding="utf-8"))
assert count == 38, f"expected 38 theme lines, removed {count}"
p.write_text(new, encoding="utf-8")
print(f"removed {count}")
PY
```
Expected: `removed 38`

- [ ] **Step 4: Normalize `metric_ledger` by hand**

For every entry, replace `status: X` with a `provenance:` / `renderable:` pair per this table. Do not script it — several entries also carry a `note` that must survive.

| old `status` | `provenance` | `renderable` |
|---|---|---|
| `counted` | `counted` | `true` |
| `doc_backed` | `doc_backed` | `true` |
| `configured` | `configured` | `false` |
| `estimated` | `estimated` | `false` |
| `unsourced_do_not_use` | `unsourced` | `false` |
| `contradicted_do_not_use` | `contradicted` | `false` |
| `unverified_do_not_use` | `unsourced` | `false` |
| `confirmed_none` | `none` | `false` |
| `none_exist_by_design` | `none` | `false` |

Then move the two bare-string entries out of `metric_ledger` into a new sibling `metric_scope:` mapping on the same entry: `sepsis_early_warning.metric_ledger.split_scope` → `sepsis_early_warning.metric_scope.split_scope`, and `fake_review_detection.metric_ledger.ablation_scope` → `fake_review_detection.metric_scope.ablation_scope`.

```bash
.venv/bin/python - <<'PY'
import yaml
d = yaml.safe_load(open("config/master_profile.yaml"))
bad = []
for item in d["projects"] + d["experience"]:
    for key, entry in (item.get("metric_ledger") or {}).items():
        if not isinstance(entry, dict):
            bad.append(f"{item['id']}.{key}: not a mapping")
        elif "status" in entry or "provenance" not in entry or "renderable" not in entry:
            bad.append(f"{item['id']}.{key}: {sorted(entry)}")
print("\n".join(bad) if bad else "metric_ledger normalized")
PY
```
Expected: `metric_ledger normalized`

- [ ] **Step 5: Split `known_gaps.severity`**

Five gaps use `severity: resolved`. For each, set `severity:` to the real severity its `detail` text implies and add `status: resolved`. Leave every other gap without a `status` key — the loader defaults them to `open`.

```bash
grep -c "severity: resolved" config/master_profile.yaml
```
Expected: `0`

- [ ] **Step 6: Bump the version**

Set `schema_version: "0.3.0"` and `last_updated: "2026-07-30"`.

- [ ] **Step 7: Confirm it parses with no duplicate keys**

```bash
.venv/bin/python -c "
from pathlib import Path
from src.profile import _read_yaml
_read_yaml(Path('config/master_profile.yaml'))
print('parses, no duplicate keys')"
```
Expected: `parses, no duplicate keys`

- [ ] **Step 8: Commit**

```bash
git add config/master_profile.yaml
git commit -m "refactor(m8): migrate master profile to schema v0.3.0

Renames bullet-level variants to phrasings (38), deletes theme (38),
normalizes metric_ledger to provenance + renderable, extracts metric_scope,
splits known_gaps severity from status, and removes the duplicate date_note
that was silently discarding the CONFIRMED internship dates."
```

---

## Task 12: Author the remaining sections

Requires the three user inputs listed at the top of this plan. Do not proceed without them.

**Files:**
- Modify: `config/master_profile.yaml`
- Test: `tests/test_profile.py`

- [ ] **Step 1: Add `identity`**

Facts below come from `profile/Himanshu_Resume_New.pdf`. `linkedin` and `github` are user-supplied — do not invent them.

```yaml
identity:
  name: "Himanshu Jain"
  phone: "408-390-0164"
  email: "himanshu.jain@sjsu.edu"
  linkedin: "<user-supplied URL>"
  github: "<user-supplied URL>"
  location: "San Jose, CA"
```

- [ ] **Step 2: Add `education`**

```yaml
education:
  - institution: "San Jose State University"
    degree: "Master of Science in Software Engineering"
    location: "San Jose, CA"
    start: "2025-08"
    end: "2027-05"
    display_date: "Aug. 2025 - May 2027"
  - institution: "National Institute of Technology, Warangal"
    degree: "Bachelor of Technology in Computer Science and Engineering"
    location: "Warangal, India"
    start: "2019-08"
    end: "2023-05"
    display_date: "Aug. 2019 - May 2023"
```

- [ ] **Step 3: Add `skills`**

Union of `profile/Himanshu_Resume_New.pdf` and `config/profile_summary.md` §Skills. Whether `Kubernetes` belongs here depends on the user's answer to required input 3 — if it goes into `do_not_claim`, it must not appear below or loader rule 15 fails the file.

```yaml
skills:
  languages: ["Java", "Python", "C++", "SQL"]
  frameworks: ["Spring Boot", "Spring MVC (REST)", "FastAPI", "JUnit", "Mockito"]
  libraries: ["Apache Kafka", "Elasticsearch", "PyTorch", "scikit-learn", "XGBoost", "PySpark"]
  apis_and_standards: ["REST", "JSON", "OpenAPI/Swagger", "OAuth2/JWT", "HTTP"]
  developer_tools: ["Jenkins", "Maven", "Docker", "Git/GitHub", "Bitbucket", "Postman", "OpenShift (OCP)", "SonarQube", "IntelliJ"]
  databases: ["PostgreSQL", "Couchbase (SDK, N1QL)", "SQL (RDBMS)"]
```

- [ ] **Step 4: Add `do_not_claim`**

Exactly the list the user supplied. If their answer is "none", write `do_not_claim: []`.

- [ ] **Step 5: Add `base_variants`**

`ml` uses the two fully-authored ML projects. `backend` gets only `peerchat_peer_discovery` — Campus Marketplace and the Clinical Trial Platform are deferred to Part B. Choose `bullet_order` from **non-blocked** bullets only, in non-decreasing `priority` order within each entry (rule 16). The four `ownership_unresolved` bullets are ineligible.

```yaml
base_variants:
  backend:
    projects: [peerchat_peer_discovery]
    bullet_order: [<internship bullet ids>, <amdocs bullet ids>, <peerchat bullet ids>]
  ml:
    projects: [sepsis_early_warning, fake_review_detection]
    bullet_order: [<internship bullet ids>, <amdocs bullet ids>, <sepsis ids>, <frd ids>]
```

- [ ] **Step 6: Validate with the CLI**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: `OK config/master_profile.yaml: schema 0.3.0, 3 project(s), 2 experience entry(ies), 38 bullet(s) (4 blocked), base_variants: backend, ml`

Fix reported errors and re-run until it passes.

- [ ] **Step 7: Add the real-file integration test**

```python
def test_real_profile_loads():
    """The shipped profile and the loader must not drift apart again."""
    profile = load_profile("config/master_profile.yaml")
    assert profile.schema_version == "0.3.0"
    assert {"backend", "ml"} <= set(profile.base_variants)
    all_bullets = [
        bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    ]
    assert len(all_bullets) == 38
    # Blocked claims exist in the corpus but must never be selectable.
    assert any(bullet.is_blocked for bullet in all_bullets)
    for name in profile.base_variants:
        assert all(
            not bullet.is_blocked for bullet in profile.for_tailoring(name).bullets
        )
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add config/master_profile.yaml tests/test_profile.py
git commit -m "feat(m8): author identity, education, skills, base_variants, do_not_claim"
```

---

## Task 13: Documentation

**Files:**
- Modify: `docs/TAILORING_SPEC.md` (§1), `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md`

- [ ] **Step 1: Replace `TAILORING_SPEC.md` §1**

Replace the whole "## 1. Source of truth" section with the v0.3.0 schema, the nomenclature table, and the `metric_ledger` model — copied from §3, §4, §4.1, and §6 of `docs/superpowers/specs/2026-07-30-m8-profile-schema-reconciliation-design.md`. Correct the path to `config/master_profile.yaml`. Replace the stale `systems` / `aiml` variant names with `backend` / `ml`. Leave §2–§6 unchanged.

- [ ] **Step 2: Update `ROADMAP.md`**

In the Phase 3 section: mark M8 item 2 complete, correct the path from `profile/master_profile.yaml` to `config/master_profile.yaml`, and state that `base_variants.backend` holds only `peerchat_peer_discovery` until Part B authors the two backend projects.

- [ ] **Step 3: Add the `DECISIONS.md` entry**

Dated 2026-07-30, recording: the authored v0.2.0 schema supersedes `TAILORING_SPEC.md` §1; the canonical path moves from `profile/` to `config/`; `do_not_claim` and the `priority` ↔ `strength` mapping restored per `TAILORING_METHODOLOGY.md` §2; and Part B deferred because evidence for the two new projects cannot be model-authored.

- [ ] **Step 4: Mark the old spec superseded**

Add at the top of `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md`:
`SUPERSEDED (2026-07-30) by 2026-07-30-m8-profile-schema-reconciliation-design.md. The schema below is not current.`

- [ ] **Step 5: Run the full suite one final time**

Run: `.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs(m8): reconcile tailoring spec, roadmap, and decisions with v0.3.0"
```

---

## Definition of done

- `.venv/bin/pytest -q` green; no test file other than `tests/test_profile.py` changed in count.
- `.venv/bin/python -m scripts.validate_profile` prints `OK`.
- `config/master_profile.yaml` is `schema_version: "0.3.0"`, has exactly one `date_note`, zero `theme` keys, zero `severity: resolved`, and no `status` key inside any `metric_ledger`.
- Every one of the 16 loader rules in spec §5 has at least one failing-case test.
- `docs/TAILORING_SPEC.md` §1 describes the file that actually exists.
- Report to the user: what was built, that Part B remains outstanding, and that `backend` is not yet renderable.
