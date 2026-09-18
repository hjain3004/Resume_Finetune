"""Baseline/reference registry: maps a Top-10 target_id to the genuinely
distinct artifacts it may be compared against.

This is the fix for the self-pairing defect in the original
`build-blind-pairs`: instead of pairing a candidate result against itself,
`pairing.py` resolves a real baseline through this registry. A target with
no entries at all (or no entry of a requested kind) yields `None` -- this
module never invents or substitutes a fabricated artifact.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

BaselineKind = Literal["old_pipeline", "manual", "accepted_historical", "alternate_config"]

VALID_BASELINE_KINDS: tuple[BaselineKind, ...] = (
    "old_pipeline",
    "manual",
    "accepted_historical",
    "alternate_config",
)

# Default preference order when the caller doesn't ask for a specific kind:
# prefer a like-for-like pipeline comparison first, then a previously
# accepted output, then an alternate configuration, and only then a manual
# reference (manual artifacts are hand-authored and may differ in scope from
# what the pipeline itself would produce). This is a default, not a rule --
# callers may pass their own `preferred_kinds` order.
DEFAULT_PREFERRED_KINDS: tuple[BaselineKind, ...] = (
    "old_pipeline",
    "accepted_historical",
    "alternate_config",
    "manual",
)


class BaselineRegistryError(ValueError):
    """Raised when a baseline registry file is structurally invalid."""


@dataclass(frozen=True)
class BaselineEntry:
    kind: BaselineKind
    artifact_id: str
    pipeline_id: str
    resume_checksum: str
    resume_text_path: str
    model_identities: dict[str, Any] = field(default_factory=dict)
    provenance: str = ""


@dataclass(frozen=True)
class BaselineRegistry:
    entries: dict[str, dict[BaselineKind, BaselineEntry]]

    def available_kinds(self, target_id: str) -> tuple[BaselineKind, ...]:
        return tuple(self.entries.get(target_id, {}).keys())

    def get(self, target_id: str, kind: BaselineKind) -> BaselineEntry | None:
        return self.entries.get(target_id, {}).get(kind)

    def resolve(
        self,
        target_id: str,
        preferred_kinds: tuple[BaselineKind, ...] = DEFAULT_PREFERRED_KINDS,
    ) -> BaselineEntry | None:
        """First available baseline for `target_id` in `preferred_kinds`
        order, or None if the target has no baseline of any requested kind.
        A missing 'manual' entry (or any other single kind) never raises --
        the caller simply gets the next available kind, or None."""
        by_kind = self.entries.get(target_id, {})
        for kind in preferred_kinds:
            if kind in by_kind:
                return by_kind[kind]
        return None


def _entry_from_dict(kind: str, data: dict[str, Any]) -> BaselineEntry:
    required = ("artifact_id", "pipeline_id", "resume_checksum", "resume_text_path")
    missing = [f for f in required if f not in data]
    if missing:
        raise BaselineRegistryError(f"baseline entry (kind={kind!r}) missing required fields: {missing}")
    return BaselineEntry(
        kind=kind,  # type: ignore[arg-type]
        artifact_id=str(data["artifact_id"]),
        pipeline_id=str(data["pipeline_id"]),
        resume_checksum=str(data["resume_checksum"]),
        resume_text_path=str(data["resume_text_path"]),
        model_identities=dict(data.get("model_identities", {})),
        provenance=str(data.get("provenance", "")),
    )


def load_baseline_registry(path: Path) -> BaselineRegistry:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BaselineRegistryError(f"baseline registry must be a JSON object: {path}")

    entries: dict[str, dict[BaselineKind, BaselineEntry]] = {}
    for target_id, kinds in raw.items():
        if not isinstance(kinds, dict):
            raise BaselineRegistryError(f"baseline registry entry for {target_id!r} must be an object")
        by_kind: dict[BaselineKind, BaselineEntry] = {}
        for kind, entry_data in kinds.items():
            if kind not in VALID_BASELINE_KINDS:
                raise BaselineRegistryError(
                    f"unknown baseline kind {kind!r} for target {target_id!r}; expected one of {VALID_BASELINE_KINDS}"
                )
            by_kind[kind] = _entry_from_dict(kind, entry_data)
        entries[target_id] = by_kind
    return BaselineRegistry(entries=entries)


def empty_registry() -> BaselineRegistry:
    """A registry with no entries for any target -- every resolve() call
    returns None. Used as the safe default when no --baseline-registry is
    given, so absence of a registry excludes targets rather than falling
    back to self-pairing."""
    return BaselineRegistry(entries={})
