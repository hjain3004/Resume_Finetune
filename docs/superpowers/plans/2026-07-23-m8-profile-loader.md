# M8 item 1 — Master Profile Loader Implementation Plan

Status: implemented in one scoped M8 item-1 pass.

Goal: build a pure, schema-validating loader for `profile/master_profile.yaml` so the next
Phase 3 session can construct the real master profile interactively with the user.

This plan is intentionally limited to M8 item 1. It does not authorize tailoring prompts,
critics, resume rendering, a CLI, database integration, SkillOpt integration, live
tailoring, eligibility fixes, scoring changes, or creation of the user's real
`profile/master_profile.yaml`.

## Constraints

- Use `superpowers:test-driven-development` and `superpowers:verification-before-completion`.
- Write failing tests before production code.
- Use no new dependencies; use the already-approved PyYAML dependency.
- Tests do not touch the network.
- `src/profile.py` performs no I/O except reading the requested YAML path.
- No SQLite reads/writes, no score import, no scorer invocation, and no real profile file.
- Keep parsing helpers small and pure; raise `ProfileValidationError`, not bare `assert`,
  `KeyError`, or unhandled `ValueError`, for validation failures.
- Keep `do_not_claim` as literal strings in this milestone. Direct normalized
  case-insensitive collisions with skills are rejected. Alias handling such as `K8s` versus
  `Kubernetes` is deferred to a future structured representation; the loader does not use
  fuzzy matching.

## Files

- Create `src/profile.py`.
- Create `tests/test_profile.py`.
- Correct `docs/superpowers/specs/2026-07-23-m8-profile-loader-design.md`.
- Add this plan file.
- Update `docs/ROADMAP.md` after verification to mark M8 item 1 complete.

## Public interface

Implement:

```python
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
    ...
```

## TDD checklist

Write `tests/test_profile.py` before `src/profile.py` and cover:

- happy-path load and returned dataclass shapes;
- malformed YAML;
- non-mapping root;
- each missing top-level key;
- wrong container types;
- blank required strings;
- invalid strength;
- duplicate bullet ID across experience and project;
- duplicate project ID;
- unknown variant project;
- unknown variant bullet;
- duplicate variant references;
- malformed skills values;
- duplicate `do_not_claim`;
- direct normalized skill/`do_not_claim` collision;
- omitted `do_not_claim` default;
- file-not-found behavior.

Verify the red state first: focused profile tests fail because `src.profile` does not
exist. Then implement the loader and rerun the focused suite to green.

## Verification

Run exactly:

```bash
.venv/bin/python -m pytest tests/test_profile.py -v
.venv/bin/python -m pytest -q
git diff --check
```

Then verify:

- no database changes;
- no scoring/import invocation;
- no eligibility changes;
- no real profile created;
- no M8 item 2 work;
- no SkillOpt dependency or integration;
- unrelated dirty files remain untouched.

Commit only the scoped M8 item-1 files with:

```bash
git commit -m "feat(m8): add validated master profile loader"
```
