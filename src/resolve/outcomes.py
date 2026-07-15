"""Typed resolution outcomes (M6.10, docs/superpowers/specs/2026-07-15-resolution-runtime-hardening-design.md).

Orchestration (`run_ingest.run_resolution()`) previously converted every
resolver failure -- a genuine content mismatch, a transient network/browser
error, or an unexpected exception -- into the same `None`, which spent a
row's three-attempt content-failure budget regardless of cause. This module
gives orchestration a typed outcome so only `CONTENT_FAILURE` consumes that
budget; `TRANSIENT_FAILURE` and `INTERNAL_ERROR` leave a row untouched and
eligible for the next run.

No DB or browser behavior lives here -- this is the contract only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.models import ResolvedJD

_MAX_MESSAGE_LENGTH = 500


def _truncate(message: str | None) -> str | None:
    if message is None:
        return None
    return message[:_MAX_MESSAGE_LENGTH]


class ResolutionOutcomeKind(str, Enum):
    RESOLVED = "resolved"
    CONTENT_FAILURE = "content_failure"
    TRANSIENT_FAILURE = "transient_failure"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ResolutionOutcome:
    kind: ResolutionOutcomeKind
    result: ResolvedJD | None = None
    reason_code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.kind == ResolutionOutcomeKind.RESOLVED and self.result is None:
            raise ValueError("a RESOLVED outcome requires a result")
        if self.kind != ResolutionOutcomeKind.RESOLVED and self.result is not None:
            raise ValueError(f"a {self.kind.value} outcome must not carry a result")
        object.__setattr__(self, "message", _truncate(self.message))

    @classmethod
    def resolved(cls, result: ResolvedJD) -> ResolutionOutcome:
        return cls(ResolutionOutcomeKind.RESOLVED, result=result)

    @classmethod
    def content_failure(cls, reason_code: str, message: str | None = None) -> ResolutionOutcome:
        return cls(ResolutionOutcomeKind.CONTENT_FAILURE, reason_code=reason_code, message=message)

    @classmethod
    def transient(cls, reason_code: str, exc: BaseException) -> ResolutionOutcome:
        return cls(ResolutionOutcomeKind.TRANSIENT_FAILURE, reason_code=reason_code, message=str(exc))

    @classmethod
    def internal(cls, reason_code: str, exc: BaseException) -> ResolutionOutcome:
        return cls(ResolutionOutcomeKind.INTERNAL_ERROR, reason_code=reason_code, message=str(exc))


@dataclass(frozen=True)
class ResolutionIssue:
    job_id: int
    url: str
    kind: ResolutionOutcomeKind
    reason_code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", _truncate(self.message) or "")


@dataclass
class ResolutionSummary:
    """Mutable, run-scoped resolution counters and diagnostics.

    Owned by `run_ingest.main()` so it survives an interrupted
    `run_resolution()` call for partial-run finalization (Task 6).
    """

    resolved: int = 0
    content_failed: int = 0
    transient: int = 0
    internal: int = 0
    tier1: int = 0
    tier2: int = 0
    manual: int = 0
    per_source: dict[str, dict[str, int]] = field(default_factory=dict)
    issues: list[ResolutionIssue] = field(default_factory=list)

    def _per_source_counts(self, source: str) -> dict[str, int]:
        return self.per_source.setdefault(source, {"resolved": 0, "failed": 0})

    def record(self, row, outcome: ResolutionOutcome) -> None:
        if outcome.kind == ResolutionOutcomeKind.RESOLVED:
            self.resolved += 1
            self._per_source_counts(row["source"])["resolved"] += 1
            assert outcome.result is not None
            if outcome.result.resolver == "browser":
                self.tier2 += 1
            else:
                self.tier1 += 1
            return

        if outcome.kind == ResolutionOutcomeKind.CONTENT_FAILURE:
            self.content_failed += 1
            self._per_source_counts(row["source"])["failed"] += 1
        elif outcome.kind == ResolutionOutcomeKind.TRANSIENT_FAILURE:
            self.transient += 1
        elif outcome.kind == ResolutionOutcomeKind.INTERNAL_ERROR:
            self.internal += 1

        self.issues.append(
            ResolutionIssue(
                job_id=row["id"],
                url=row["url"],
                kind=outcome.kind,
                reason_code=outcome.reason_code or "",
                message=outcome.message or "",
            )
        )
