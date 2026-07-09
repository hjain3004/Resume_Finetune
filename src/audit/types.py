"""Shared dataclasses for the M7 audit suite. Split out from src/audit/__init__.py
to avoid a circular import: __init__.py imports the invariant modules, and each
invariant module needs Finding, so both sides import from this module instead."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    invariant: str
    status: str
    evidence: list[dict] = field(default_factory=list)
    detail: str = ""


@dataclass
class AuditResult:
    findings: list[Finding]
    overall: str
