"""Traced, single-attempt S3 invocation and deterministic publication data."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.llm_trace import write_trace
from src.tailor.g1 import G1Report, G1Status, g1_report_to_dict, parse_g1_report, run_static_g1
from src.tailor.invoke import DEFAULT_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_text_model
from src.tailor.providers import ModelCommand, trace_model_label
from src.tailor.s3 import (
    ChangeEntry,
    EditBudget,
    S3HydrationError,
    S3ParseError,
    S3Request,
    S3Response,
    S3RevisionContext,
    S3SemanticError,
    TailoredDraft,
    build_s3_prompt,
    build_s3_revision_prompt,
    calculate_edit_budget,
    change_entry_to_dict,
    derive_change_log,
    derive_unified_diff,
    edit_budget_to_dict,
    hydrate_s3,
    parse_change_log,
    parse_edit_budget,
    parse_s3_response,
    parse_tailored_draft,
    s3_response_to_dict,
    tailored_draft_to_dict,
    validate_revision_scope,
)

TRACE_INVOCATION_TYPE = "tailoring_s3"


class S3OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"
    PARSE_FAILURE = "parse_failure"
    SEMANTIC_FAILURE = "semantic_failure"
    HYDRATION_FAILURE = "hydration_failure"
    G1_FAILURE = "g1_failure"
    VALID = "valid"


@dataclass(frozen=True)
class S3Bundle:
    schema_version: str
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str
    response: S3Response
    draft: TailoredDraft
    change_log: tuple[ChangeEntry, ...]
    unified_diff: str
    edit_budget: EditBudget
    g1: G1Report


@dataclass(frozen=True)
class S3Outcome:
    kind: S3OutcomeKind
    bundle: S3Bundle | None
    g1_report: G1Report | None
    error: str | None
    trace_path: Path | None


def _trace(request_path: Path, prompt_template_path: Path, raw: str, model: str, trace_dir: Path) -> Path | None:
    if not raw.strip():
        return None
    return write_trace(
        invocation_type=TRACE_INVOCATION_TYPE,
        input_paths=[request_path],
        raw_output=raw,
        prompt_path=prompt_template_path,
        model=model,
        trace_dir=trace_dir,
    )


def run_s3_invocation(
    request: S3Request,
    *,
    prompt_template_path: Path,
    request_path: Path,
    banned_terms: tuple[str, ...],
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
) -> S3Outcome:
    effective_cmd = model_command if model_command is not None else command
    template = Path(prompt_template_path).read_text(encoding="utf-8")
    prompt = build_s3_prompt(template, request)
    try:
        if effective_cmd is not None:
            result = invoke_text_model(prompt, command=effective_cmd, timeout=timeout)
        else:
            result = invoke_text_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        trace_model = exc.model or (trace_model_label(effective_cmd) if effective_cmd else (claude_cmd[0] if claude_cmd else ""))
        return S3Outcome(S3OutcomeKind.INVOCATION_FAILURE, None, None, str(exc), _trace(Path(request_path), Path(prompt_template_path), exc.raw_stdout, trace_model, trace_dir))
    trace_path = _trace(Path(request_path), Path(prompt_template_path), result.raw_stdout, result.model, trace_dir)
    try:
        response = parse_s3_response(result.raw_stdout, request)
    except S3ParseError as exc:
        return S3Outcome(S3OutcomeKind.PARSE_FAILURE, None, None, str(exc), trace_path)
    except S3SemanticError as exc:
        return S3Outcome(S3OutcomeKind.SEMANTIC_FAILURE, None, None, str(exc), trace_path)
    try:
        draft = hydrate_s3(request, response)
    except S3HydrationError as exc:
        return S3Outcome(S3OutcomeKind.HYDRATION_FAILURE, None, None, str(exc), trace_path)
    report = run_static_g1(request, response, draft, banned_terms)
    if report.status.value != "static_pass":
        return S3Outcome(S3OutcomeKind.G1_FAILURE, None, report, "static G1 failed", trace_path)
    bundle = S3Bundle(
        "m8p3.s3_bundle.v1", request.job_id, request.company, request.title,
        request.alignment.fingerprint, response, draft,
        derive_change_log(request, response, draft), derive_unified_diff(request, draft),
        calculate_edit_budget(request, draft), report,
    )
    return S3Outcome(S3OutcomeKind.VALID, bundle, report, None, trace_path)


# ---------------------------------------------------------------------------
# M8P-4 addition (post-M8P-3R integration, purely additive): the bounded S3
# revision invocation a G2 critic finding may trigger. Mirrors
# run_s3_invocation()'s trace/parse/hydrate/G1 sequence exactly, with one
# extra step (validate_revision_scope) between parsing and hydration.
# run_s3_invocation() itself is not modified.
# ---------------------------------------------------------------------------


def run_s3_revision(
    request: S3Request,
    previous: S3Response,
    *,
    context: S3RevisionContext,
    prompt_template_path: Path,
    request_path: Path,
    banned_terms: tuple[str, ...],
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
) -> S3Outcome:
    effective_cmd = model_command if model_command is not None else command
    template = Path(prompt_template_path).read_text(encoding="utf-8")
    prompt = build_s3_revision_prompt(template, request, context)
    try:
        if effective_cmd is not None:
            result = invoke_text_model(prompt, command=effective_cmd, timeout=timeout)
        else:
            result = invoke_text_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        trace_model = exc.model or (trace_model_label(effective_cmd) if effective_cmd else (claude_cmd[0] if claude_cmd else ""))
        return S3Outcome(S3OutcomeKind.INVOCATION_FAILURE, None, None, str(exc), _trace(Path(request_path), Path(prompt_template_path), exc.raw_stdout, trace_model, trace_dir))
    trace_path = _trace(Path(request_path), Path(prompt_template_path), result.raw_stdout, result.model, trace_dir)
    try:
        response = parse_s3_response(result.raw_stdout, request)
    except S3ParseError as exc:
        return S3Outcome(S3OutcomeKind.PARSE_FAILURE, None, None, str(exc), trace_path)
    except S3SemanticError as exc:
        return S3Outcome(S3OutcomeKind.SEMANTIC_FAILURE, None, None, str(exc), trace_path)
    try:
        validate_revision_scope(response, previous, context)
    except S3SemanticError as exc:
        return S3Outcome(S3OutcomeKind.SEMANTIC_FAILURE, None, None, str(exc), trace_path)
    try:
        draft = hydrate_s3(request, response)
    except S3HydrationError as exc:
        return S3Outcome(S3OutcomeKind.HYDRATION_FAILURE, None, None, str(exc), trace_path)
    report = run_static_g1(request, response, draft, banned_terms)
    if report.status.value != "static_pass":
        return S3Outcome(S3OutcomeKind.G1_FAILURE, None, report, "static G1 failed", trace_path)
    bundle = S3Bundle(
        "m8p3.s3_bundle.v1", request.job_id, request.company, request.title,
        request.alignment.fingerprint, response, draft,
        derive_change_log(request, response, draft), derive_unified_diff(request, draft),
        calculate_edit_budget(request, draft), report,
    )
    return S3Outcome(S3OutcomeKind.VALID, bundle, report, None, trace_path)


_BUNDLE_KEYS = {
    "schema_version", "job_id", "company", "title", "alignment_fingerprint",
    "response", "draft", "change_log", "unified_diff", "edit_budget", "g1",
}
_BUNDLE_SCHEMA_VERSION = "m8p3.s3_bundle.v1"


class S3BundleError(ValueError):
    """A persisted s3_bundle.json failed strict structural parsing or
    deterministic recompute-and-compare validation against the
    authoritative S3Request."""


def s3_bundle_to_dict(bundle: S3Bundle) -> dict[str, object]:
    """Recursive, explicit serialization -- JSON primitives only, no
    dataclass `.__dict__` anywhere (Defect 1)."""
    return {
        "schema_version": bundle.schema_version,
        "job_id": bundle.job_id,
        "company": bundle.company,
        "title": bundle.title,
        "alignment_fingerprint": bundle.alignment_fingerprint,
        "response": s3_response_to_dict(bundle.response),
        "draft": tailored_draft_to_dict(bundle.draft),
        "change_log": [change_entry_to_dict(entry) for entry in bundle.change_log],
        "unified_diff": bundle.unified_diff,
        "edit_budget": edit_budget_to_dict(bundle.edit_budget),
        "g1": g1_report_to_dict(bundle.g1),
    }


def parse_s3_bundle(raw: object, request: S3Request, banned_terms: tuple[str, ...]) -> S3Bundle:
    """Strict, authoritative parser for a persisted `s3_bundle.json`.

    First proves the JSON is well-typed (exact field sets, correct scalar/
    container types, no bool-as-int, valid emphasis spans, no duplicate
    bullet ids or skill categories, a known schema version and enum
    values). Then, given the authoritative `request` and `banned_terms`,
    deterministically recomputes the response validation, hydrated draft,
    change log, unified diff, edit budget, and static G1 report, and
    requires every persisted derived field to match the recomputation
    exactly. A tampered derived field -- including a fabricated bullet
    owner or an undeclared bullet mutation -- is rejected here even if it
    would otherwise slip past a narrower check.
    """
    if not isinstance(raw, dict) or set(raw) != _BUNDLE_KEYS:
        raise S3BundleError("$: unexpected or missing fields")
    if raw["schema_version"] != _BUNDLE_SCHEMA_VERSION:
        raise S3BundleError(f"$.schema_version: expected {_BUNDLE_SCHEMA_VERSION!r}")
    job_id = raw["job_id"]
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise S3BundleError("$.job_id: expected integer")
    company = raw["company"]
    title = raw["title"]
    if not isinstance(company, str) or not company.strip():
        raise S3BundleError("$.company: expected nonempty string")
    if not isinstance(title, str) or not title.strip():
        raise S3BundleError("$.title: expected nonempty string")
    fingerprint = raw["alignment_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise S3BundleError("$.alignment_fingerprint: invalid fingerprint")
    if job_id != request.job_id or company != request.company or title != request.title:
        raise S3BundleError("$: identity does not match the authoritative request")
    if fingerprint != request.alignment.fingerprint:
        raise S3BundleError("$.alignment_fingerprint: does not match the authoritative alignment")

    try:
        response = parse_s3_response(json.dumps(raw["response"], separators=(",", ":")), request)
    except (S3ParseError, S3SemanticError) as exc:
        raise S3BundleError(f"$.response: {exc}") from exc

    draft = parse_tailored_draft(raw["draft"], "$.draft")
    change_log = parse_change_log(raw["change_log"], "$.change_log")
    unified_diff = raw["unified_diff"]
    if not isinstance(unified_diff, str):
        raise S3BundleError("$.unified_diff: expected string")
    edit_budget = parse_edit_budget(raw["edit_budget"], "$.edit_budget")
    g1 = parse_g1_report(raw["g1"], "$.g1")

    try:
        recomputed_draft = hydrate_s3(request, response)
    except S3HydrationError as exc:
        raise S3BundleError(f"$.draft: cannot be reproduced from the persisted response: {exc}") from exc
    if draft != recomputed_draft:
        raise S3BundleError("$.draft: does not match deterministic recomputation from the persisted response")
    if change_log != derive_change_log(request, response, recomputed_draft):
        raise S3BundleError("$.change_log: does not match deterministic recomputation")
    if unified_diff != derive_unified_diff(request, recomputed_draft):
        raise S3BundleError("$.unified_diff: does not match deterministic recomputation")
    recomputed_budget = calculate_edit_budget(request, recomputed_draft)
    if edit_budget != recomputed_budget:
        raise S3BundleError("$.edit_budget: does not match deterministic recomputation")
    recomputed_g1 = run_static_g1(request, response, recomputed_draft, banned_terms)
    if g1 != recomputed_g1:
        raise S3BundleError("$.g1: does not match deterministic recomputation")
    if g1.status is not G1Status.STATIC_PASS:
        raise S3BundleError("$.g1: persisted bundle does not pass static G1")

    return S3Bundle(raw["schema_version"], job_id, company, title, fingerprint, response, recomputed_draft, change_log, unified_diff, edit_budget, g1)
