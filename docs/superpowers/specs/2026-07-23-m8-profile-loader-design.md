SUPERSEDED (2026-07-30) by 2026-07-30-m8-profile-schema-reconciliation-design.md. The schema below is not current.

# M8 item 1 — Master Profile Loader (design)

Status: implemented (M8 item 1)
Phase: 3 (M8 Tailoring), item 1 — **Phase 3 is UNLOCKED by explicit user-approved deviation (2026-07-25)**
Depends on: `docs/TAILORING_SPEC.md` §1 (schema), `docs/TAILORING_METHODOLOGY.md` §2 (evidence/strength/do_not_claim additions)

## Context

**CORRECTION (2026-07-25, M6.13R): Phase 3 was not unlocked at that time, and this section was wrong.**
Unlocking requires *both* halves of the gate in `docs/ROADMAP.md`. Only the ATS half was
checked. The Phase 2 exit criteria were not met: the 2026-07-19 closure has since been
retracted (of 36 claimed fit labels, 26 remain valid across one clean round, not three).
The ATS half is genuinely met — 12 `SHORTLISTED` rows carry `jd_quality='ats'`, still true
after the M6.13R DB repair — but Phase 3 stays LOCKED until one more clean calibration round
completes. This spec remains a design document only; nothing in it is cleared to build.

**UPDATE (2026-07-25): Phase 3 is now unlocked by explicit user-approved deviation.** The
user accepted the remaining calibration uncertainty, waived the additional held-out round,
locked threshold 6.0 for the start of Phase 3, and kept Phase 3 fully human-reviewed with
no auto-submit path. The historical correction above is preserved because it accurately
documents the prior mistaken unlock claim. The current session is cleared to build M8 item
1 only: the pure master-profile loader.

The original (incorrect) text follows for the record:

> Phase 3 unlocked 2026-07-22 (12 SHORTLISTED rows now carry `jd_quality='ats'`, past the
> ≥5 gate). Per `docs/ROADMAP.md`, the first Phase 3 session builds the master-profile
> *loader* only; the interactive session where the user actually decomposes their 5-6 resume
> variants into `profile/master_profile.yaml` happens after this exists. No such YAML file
> exists yet — `profile/` currently holds only PDF resume variants.

This session's scope is therefore: a loader module that can parse and validate a
`master_profile.yaml` conforming to the spec, plus tests against small hand-written
fixture YAML. It does not write a real profile, does not add a CLI entrypoint (nothing
downstream consumes this yet — S1-S3 tailoring steps are unbuilt), and does not touch
`src/db.py` or any pipeline stage.

## Data model

`src/profile.py`, new module. Follows the fail-fast validation convention already used by
`src/eligibility.py::load_eligibility_config` (single error type, raised immediately with a
path-labeled message on the first problem found) rather than a collect-all-errors result
object, for consistency with the codebase's one existing config loader.

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
```

`identity`, `education`, and `skills` entries keep flexible key sets (mirroring
`TAILORING_SPEC.md`'s "mirror the sections used in the current resumes" — the exact key set
isn't fixed by the spec and shouldn't be hard-coded here), but the loader validates their
runtime shape: identity values are strings, education entries are string-key/string-value
mappings, and skills values are nonempty string lists. Everything with a fabrication or
selection invariant riding on it (bullets, variants) gets a real dataclass.

## `load_profile(path: str | Path) -> MasterProfile`

Reads and validates YAML (PyYAML, already an approved dependency). Raises
`ProfileValidationError` on the first violation found, each one tracing directly to an
explicit rule already written in the two spec docs (nothing new invented here):

1. YAML root is a mapping.
2. Top-level keys `identity`, `education`, `experience`, `projects`, `skills`, `variants`
   must be present; `do_not_claim` is optional and defaults to `()`.
3. Expected mappings/lists/strings have the correct runtime type; booleans and scalar
   values are rejected where containers are expected.
4. Required textual fields are nonempty after trimming.
5. Identity values are strings; education entries are string-key/string-value mappings.
6. Skills is a mapping of category names to nonempty string lists.
7. Every experience contains nonempty `org`, `title`, `dates`, and a bullet list.
8. Every project contains a globally unique, nonempty `id` plus nonempty `name`, `stack`,
   `dates`, `tags`, and a bullet list.
9. Every bullet has globally unique nonempty `id`, nonempty `text`, list-of-string `tags`,
   list-of-string `metrics`, nonempty `evidence`, and `strength` in
   `flagship`/`solid`/`filler` — `TAILORING_METHODOLOGY.md` §2 marks `evidence` and
   `strength` "required per bullet."
10. Bullet `id`s are globally unique across `experience` + `projects` bullets. This is the
   structural fabrication guard `TAILORING_SPEC.md` §1 calls out directly: "every bullet in
   any generated resume must carry the `id` of a master-profile entry."
11. Variant names are nonempty. Every `variants.*.projects` entry resolves to a real
   `projects[].id`, and every
   `variants.*.bullet_order` entry resolves to a real bullet id (from either
   `experience[].bullets` or `projects[].bullets`).
12. Duplicate references inside a single variant are rejected.
13. `do_not_claim` entries are nonempty strings and unique case-insensitively.
14. No `do_not_claim` entry appears anywhere in `skills` values under direct normalized
   case-insensitive comparison — enforcement of §2: "the tailor may NEVER surface these as
   skills regardless of JD demand."
15. YAML lists are converted to immutable tuples in the returned dataclasses.

`do_not_claim` remains a list of literal strings in M8 item 1. Aliases such as `K8s` versus
`Kubernetes` require a future structured representation; the loader deliberately does not
invent an unreliable fuzzy matcher.

## Testing

`tests/test_profile.py`, hand-written fixture YAML as inline strings (no fixture files —
these are small enough that inline is clearer than a `tests/fixtures/profile/*.yaml` for a
reader to see the fixture and its assertion in one place). Tests cover the happy path,
malformed YAML, missing keys, wrong container types, blank strings, invalid strength,
duplicate IDs/references, malformed skills, `do_not_claim`, omitted `do_not_claim`, and
file-not-found behavior.

## Explicitly out of scope this session

- Writing a real `profile/master_profile.yaml` (next session, interactive, with the user).
- A CLI validator entrypoint (`scripts/validate_profile.py`) — add it when something
  actually calls `load_profile` (the tailoring pipeline, or the user wanting to hand-check
  a draft file).
- Any change to `src/db.py`, `run_ingest.py`, or scoring/eligibility code — this is a pure,
  standalone parsing module with no I/O beyond reading the one YAML file.
