"""Safe, structured invocations through the user's ChatGPT Codex session.

This provider deliberately does not share the platform-API adapters.  Each
stage is a fresh ``codex exec`` process with a read-only sandbox, ephemeral
session, and a stage-specific JSON Schema.  Only the final structured message
and bounded usage metadata leave the temporary invocation directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.llm_trace import write_trace

CODEX_MODEL = "gpt-5.6-luna"
CODEX_PROVIDER = "codex_subscription"
DEFAULT_MAX_RETRIES = 1
_API_KEY_NAMES = {
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
}


class CodexInvocationError(RuntimeError):
    """A non-resumable Codex subprocess or structured-output failure."""


class CodexPilotInterrupted(RuntimeError):
    """A budget, rate-limit, or timeout interruption safe to resume later."""


@dataclass
class CodexPilotBudget:
    max_invocations: int = 120
    deadline_monotonic: float | None = None
    target_deadline_monotonic: float | None = None
    used_invocations: int = 0

    def reserve(self) -> None:
        if self.used_invocations >= self.max_invocations:
            raise CodexPilotInterrupted("Codex invocation budget exhausted; completed targets are resumable")
        deadlines = [deadline for deadline in (self.deadline_monotonic, self.target_deadline_monotonic) if deadline is not None]
        if deadlines and time.monotonic() >= min(deadlines):
            raise CodexPilotInterrupted("Codex pilot wall-clock budget exhausted; completed targets are resumable")
        self.used_invocations += 1


@dataclass(frozen=True)
class CodexUsage:
    thread_id: str | None
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    latency_seconds: float
    outcome: str


def _dimension_schema(dimensions: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {
                "type": "object",
                "properties": {"score": {"type": "integer", "enum": [1, 2, 3]}, "findings": {"type": "string"}},
                "required": ["score", "findings"],
                "additionalProperties": False,
            }
            for name in dimensions
        },
        "required": list(dimensions),
        "additionalProperties": False,
    }


def stage_output_schema(stage: str) -> dict[str, Any]:
    """Return the strict final-output schema for one Tailor2 stage."""
    def object_schema(properties: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
        del required
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    string_array = {"type": "array", "items": {"type": "string"}}
    if stage == "selection":
        requirement = object_schema(
            {
                "id": {"type": "string"},
                "term": {"type": "string"},
                "quote": {"type": "string"},
                "kind": {"type": "string", "enum": ["must_have", "preferred", "nice_to_have", "responsibility"]},
                "alternative_group_id": {"type": ["string", "null"]},
                "domain_context": {"type": "string"},
                "ambiguity": {"type": "string"},
                "evidence_gap": {"type": "boolean"},
            },
            ("id", "term", "quote", "kind"),
        )
        match = object_schema(
            {
                "requirement_id": {"type": "string"},
                "evidence_ids": string_array,
                "classification": {"type": "string", "enum": ["direct", "adjacent", "transferable", "gap"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "strength": {"type": "number", "minimum": 0, "maximum": 1},
                "explanation": {"type": "string"},
                "limitation": {"type": "string"},
            },
            ("requirement_id", "evidence_ids", "classification", "confidence", "strength", "explanation"),
        )
        evidence_selection = object_schema(
            {
                "evidence_id": {"type": "string"},
                "selected": {"type": "boolean"},
                "score": {"type": "number"},
                "requirement_ids": string_array,
                "estimated_line_cost": {"type": "integer"},
                "rationale": {"type": "string"},
                "omission_reason": {"type": ["string", "null"]},
            },
            ("evidence_id", "selected", "score", "requirement_ids", "estimated_line_cost", "rationale"),
        )
        skill = object_schema(
            {
                "category": {"type": "string"},
                "term": {"type": "string"},
                "include": {"type": "boolean"},
                "canonical_support": {"type": "boolean"},
                "selected_demonstration": {"type": "boolean"},
                "evidence_ids": string_array,
                "reason": {"type": "string"},
                "weak_demo_advisory": {"type": "boolean"},
            },
            ("category", "term", "include", "canonical_support", "selected_demonstration", "evidence_ids", "reason"),
        )
        candidate = object_schema(
            {
                "candidate_id": {"type": "string"},
                "bullet_id": {"type": "string"},
                "evidence_ids": string_array,
                "supported_requirement_ids": string_array,
                "text": {"type": "string"},
                "variation": {"type": "string"},
            },
            ("candidate_id", "bullet_id", "evidence_ids", "supported_requirement_ids", "text"),
        )
        component_scores = object_schema(
            {
                name: {"type": "number"}
                for name in (
                    "clarity", "relevance", "achievement", "metric_interpretability",
                    "defensibility", "mechanism_outcome_balance", "redundancy", "ai_abstraction",
                    "recruiter_scan", "line_cost",
                )
            },
            (),
        )
        ranking = object_schema(
            {
                "candidate_id": {"type": "string"},
                "component_scores": component_scores,
                "total_score": {"type": "number"},
                "rationale": {"type": "string"},
                "selected": {"type": "boolean"},
                "fallback": {"type": "boolean"},
            },
            ("candidate_id", "component_scores", "total_score", "rationale"),
        )
        unused = object_schema(
            {
                "evidence_id": {"type": "string"},
                "requirement_ids": string_array,
                "strength": {"type": "number"},
                "likely_section": {"type": "string"},
                "estimated_line_cost": {"type": "integer"},
                "omission_reason": {"type": "string"},
                "redundancy": {"type": "string"},
                "weaker_selected_replacement": {"type": ["string", "null"]},
                "later_page_fill_suitability": {"type": "string"},
            },
            ("evidence_id", "requirement_ids", "strength", "likely_section", "estimated_line_cost", "omission_reason"),
        )
        return {
            "type": "object",
            "properties": {
                "requirements": {"type": "array", "items": requirement},
                "matches": {"type": "array", "items": match},
                "evidence_selection": {"type": "array", "items": evidence_selection},
                "skills": {"type": "array", "items": skill},
                "candidates": {"type": "array", "items": candidate},
                "rankings": {"type": "array", "items": ranking},
                "unused_evidence": {"type": "array", "items": unused},
            },
            "required": ["requirements", "matches", "evidence_selection", "skills", "candidates", "rankings", "unused_evidence"],
            "additionalProperties": False,
        }
    if stage == "draft":
        atomic_requirement = object_schema(
            {"id": {"type": "string"}, "term": {"type": "string"}, "quote": {"type": "string"}, "importance": {"type": "string", "enum": ["must_have", "nice_to_have"]}},
            ("id", "term", "quote"),
        )
        omission = object_schema(
            {"evidence_id": {"type": "string"}, "category": {"type": "string", "enum": ["relevance", "space"]}, "reason": {"type": "string"}},
            ("evidence_id", "category", "reason"),
        )
        bullet = object_schema(
            {"bullet_id": {"type": "string"}, "evidence_ids": string_array, "supported_requirement_ids": string_array, "section": {"type": "string", "enum": ["Experience", "Projects"]}, "entry_id": {"type": "string"}, "text": {"type": "string"}},
            ("bullet_id", "evidence_ids", "supported_requirement_ids", "section", "entry_id", "text"),
        )
        return {
            "type": "object",
            "properties": {
                "atomic_requirements": {"type": "array", "items": atomic_requirement},
                "selected_evidence_ids": string_array,
                "amdocs_omission_ledger": {"type": "array", "items": omission},
                "section_order": string_array,
                "bullets": {"type": "array", "items": bullet},
            },
            "required": [
                "atomic_requirements",
                "selected_evidence_ids",
                "amdocs_omission_ledger",
                "section_order",
                "bullets",
            ],
            "additionalProperties": False,
        }
    if stage in {"audit", "re_audit"}:
        dimensions = (
            "factual_fidelity",
            "metric_fidelity",
            "technology_fidelity",
            "technical_guarantee_fidelity",
            "relevance",
            "star_xyz_coherence",
            "readability",
            "recruiter_scan_quality",
            "ai_slop_risk",
        )
        whole_dimensions = (
            "metric_interpretability",
            "interview_defensibility",
            "whole_resume_positioning",
            "skills_evidence_integrity",
            "title_identity_fidelity",
            "mechanism_outcome_balance",
            "cross_bullet_repetition",
            "misleading_implication",
        )
        evaluation = {
            "type": "object",
            "properties": {
                "bullet_id": {"type": "string"},
                "dimensions": _dimension_schema(dimensions),
                "verdict": {"type": "string", "enum": ["ACCEPT", "REJECT"]},
                "rejection_reasons": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["bullet_id", "dimensions", "verdict", "rejection_reasons"],
            "additionalProperties": False,
        }
        whole_resume = {
            "type": "object",
            "properties": {
                "dimensions": _dimension_schema(whole_dimensions),
                "verdict": {"type": "string", "enum": ["ACCEPT", "REJECT"]},
                "rejection_reasons": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dimensions", "verdict", "rejection_reasons"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "evaluations": {"type": "array", "items": evaluation},
                "overall_verdict": {"type": "string", "enum": ["PASS", "REPAIR_REQUIRED"]},
                "whole_resume": whole_resume,
            },
            "required": ["evaluations", "overall_verdict", "whole_resume"],
            "additionalProperties": False,
        }
    if stage == "repair":
        return {
            "type": "object",
            "properties": {
                "repaired_bullets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"bullet_id": {"type": "string"}, "text": {"type": "string"}},
                        "required": ["bullet_id", "text"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["repaired_bullets"],
            "additionalProperties": False,
        }
    if stage == "missing_evidence":
        recovered_bullet = {
            "type": "object",
            "properties": {
                "evidence_id": {"type": "string"},
                "bullet_id": {"type": "string"},
                "supported_requirement_ids": string_array,
                "text": {"type": "string"},
            },
            "required": ["evidence_id", "bullet_id", "supported_requirement_ids", "text"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {"recovered_bullets": {"type": "array", "items": recovered_bullet}},
            "required": ["recovered_bullets"],
            "additionalProperties": False,
        }
    raise ValueError(f"unknown Tailor2 Codex stage: {stage!r}")


def _stage_keys(stage: str) -> tuple[str, ...]:
    return tuple(stage_output_schema(stage)["required"])


def _bounded(text: str, limit: int = 1000) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _safe_environment() -> dict[str, str]:
    allowed = {"PATH", "HOME", "CODEX_HOME", "LANG", "LC_ALL", "TMPDIR", "TERM"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    for key in list(environment):
        if key in _API_KEY_NAMES or key.endswith("_TOKEN"):
            environment.pop(key, None)
    return environment


def _parse_events(stdout: str) -> tuple[str | None, dict[str, int]]:
    thread_id: str | None = None
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        if event.get("type") != "turn.completed":
            continue
        raw_usage = event.get("usage")
        if not isinstance(raw_usage, dict):
            continue
        for key in usage:
            value = raw_usage.get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
    return thread_id, usage


def _codex_version(executable: str) -> str:
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, env=_safe_environment())
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    value = result.stdout.strip().splitlines()
    return _bounded(value[0], 120) if result.returncode == 0 and value else "unknown"


@dataclass
class CodexSubscriptionInvoker:
    role: str
    model: str = CODEX_MODEL
    reasoning_effort: str = "high"
    timeout_seconds: int = 600
    trace_dir: Path = Path("data/traces")
    codex_executable: str = "codex"
    codex_version: str | None = None
    budget: CodexPilotBudget | None = None
    max_retries: int = DEFAULT_MAX_RETRIES
    extra_environment: dict[str, str] = field(default_factory=dict, repr=False)
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
    invocation_count: int = 0
    _usage: list[dict[str, Any]] = field(default_factory=list)
    _retry_count: int = 0
    contract_retry_count: int = 0
    fake_responses: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.model != CODEX_MODEL:
            raise ValueError(f"Codex subscription pilot requires exact model {CODEX_MODEL!r}")
        self.trace_dir = Path(self.trace_dir)
        if self.codex_version is None:
            self.codex_version = _codex_version(self.codex_executable)

    @property
    def provider(self) -> str:
        return CODEX_PROVIDER

    @property
    def metadata(self) -> dict[str, Any]:
        token_totals = {
            key: sum(int(item.get(key, 0)) for item in self._usage)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
        }
        safe_totals = {
            "input_count": token_totals["input_tokens"],
            "cached_input_count": token_totals["cached_input_tokens"],
            "output_count": token_totals["output_tokens"],
            "reasoning_output_count": token_totals["reasoning_output_tokens"],
        }
        safe_usage = [
            {
                "thread_id": item.get("thread_id"),
                "stage": item.get("stage"),
                "input_count": item.get("input_tokens", 0),
                "cached_input_count": item.get("cached_input_tokens", 0),
                "output_count": item.get("output_tokens", 0),
                "reasoning_output_count": item.get("reasoning_output_tokens", 0),
                "latency_seconds": item.get("latency_seconds", 0.0),
                "outcome": item.get("outcome", ""),
            }
            for item in self._usage
        ]
        return {
            "provider": CODEX_PROVIDER,
            "execution_surface": "Codex CLI",
            "authentication_mode": "ChatGPT-managed",
            "model": self.model,
            "role": self.role,
            "reasoning_effort": self.reasoning_effort,
            "codex_version": self.codex_version,
            "invocation_count": self.invocation_count,
            "retry_count": self._retry_count,
            "contract_retry_count": self.contract_retry_count,
            "cost_status": "not_applicable_subscription",
            "usage_totals": safe_totals,
            "usage": safe_usage,
        }

    def _environment(self) -> dict[str, str]:
        environment = _safe_environment()
        for key, value in self.extra_environment.items():
            if key in _API_KEY_NAMES or key.endswith("_TOKEN"):
                raise ValueError(f"refusing credential-like test environment key: {key}")
            environment[key] = value
        return environment

    def _run_once(self, prompt: str, stage: str) -> tuple[str, CodexUsage]:
        if self.budget is not None:
            self.budget.reserve()
        self.invocation_count += 1
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="tailor2-codex-") as temp_dir:
            temp_root = Path(temp_dir)
            schema_path = temp_root / "output-schema.json"
            last_message_path = temp_root / "last-message.json"
            schema_path.write_text(json.dumps(stage_output_schema(stage), sort_keys=True), encoding="utf-8")
            argv = [
                self.codex_executable,
                "exec",
                "--model",
                self.model,
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--ignore-rules",
                "--config",
                "mcp_servers={}",
                "--config",
                'model_reasoning_effort="high"',
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(last_message_path),
                "--json",
                "-C",
                str(temp_root),
                "-",
            ]
            try:
                result = self.runner(
                    argv,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=self._environment(),
                )
            except subprocess.TimeoutExpired as exc:
                raise CodexPilotInterrupted(f"Codex {self.role} stage timed out after {self.timeout_seconds}s") from exc
            except OSError as exc:
                raise CodexInvocationError(f"Codex CLI could not start: {type(exc).__name__}") from exc

            thread_id, usage = _parse_events(result.stdout)
            latency = time.monotonic() - started
            outcome = "success" if result.returncode == 0 else "process_error"
            record = {
                "thread_id": thread_id,
                "stage": stage,
                **usage,
                "latency_seconds": round(latency, 3),
                "outcome": outcome,
            }
            self._usage.append(record)
            if result.returncode != 0:
                diagnostic = _bounded(result.stderr)
                event_errors: list[str] = []
                for line in result.stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "error" and isinstance(event.get("message"), str):
                        event_errors.append(event["message"])
                if event_errors:
                    diagnostic = _bounded("; ".join(event_errors)) + (f"; {diagnostic}" if diagnostic else "")
                lowered = diagnostic.lower()
                if result.returncode in {408, 429} or "rate limit" in lowered or "usage limit" in lowered:
                    raise CodexPilotInterrupted(f"Codex subscription interruption: {diagnostic or 'rate limit'}")
                raise CodexInvocationError(f"Codex CLI exited {result.returncode}: {diagnostic or 'no stderr'}")
            if not last_message_path.exists():
                raise CodexInvocationError("Codex CLI completed without a final structured output")
            return last_message_path.read_text(encoding="utf-8"), CodexUsage(
                thread_id=thread_id,
                latency_seconds=latency,
                outcome=outcome,
                **usage,
            )

    def invoke(self, prompt: str, invocation_type: str, input_paths: list[Path] | None = None) -> str:
        stage = "re_audit" if invocation_type == "re_audit" else invocation_type
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            raw_output, _ = self._run_once(prompt, stage)
            try:
                parsed = json.loads(raw_output)
                if not isinstance(parsed, dict) or any(key not in parsed for key in _stage_keys(stage)):
                    raise ValueError(f"structured output missing required {stage} keys")
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise CodexInvocationError(f"Codex {stage} output failed bounded validation: {exc}") from exc
                self._retry_count += 1
                continue
            break
        else:  # pragma: no cover - loop always returns or raises
            raise CodexInvocationError(f"Codex {stage} output failed: {last_error}")

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as prompt_file:
            prompt_file.write(prompt)
            prompt_path = Path(prompt_file.name)
        try:
            write_trace(
                invocation_type=f"tailor2_{invocation_type}",
                input_paths=input_paths or [],
                raw_output=raw_output,
                prompt_path=prompt_path,
                model=f"{CODEX_PROVIDER}:{self.model}",
                trace_dir=self.trace_dir,
            )
        finally:
            prompt_path.unlink(missing_ok=True)
        return raw_output
