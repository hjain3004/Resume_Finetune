"""Discovery adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.models import DiscoveredJob


@dataclass(frozen=True)
class SnapshotState:
    keys: frozenset[str]
    pending_keys: frozenset[str]


@dataclass(frozen=True)
class PendingCheckpoint:
    source: str
    path: Path
    source_path: str
    keys: frozenset[str]
    pending_keys: frozenset[str]


@dataclass(frozen=True)
class AdapterDiscovery:
    source: str
    jobs: tuple[DiscoveredJob, ...]
    checkpoint: PendingCheckpoint | None


@dataclass(frozen=True)
class DiscoveryIssue:
    source: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    jobs: tuple[DiscoveredJob, ...]
    checkpoints: tuple[PendingCheckpoint, ...]
    succeeded_sources: tuple[str, ...]
    issues: tuple[DiscoveryIssue, ...]


class DiscoverAdapter(Protocol):
    SOURCE_NAME: str

    def discover(self, config: dict) -> AdapterDiscovery: ...
