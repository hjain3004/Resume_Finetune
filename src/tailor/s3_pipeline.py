"""Traced, single-attempt S3 invocation and deterministic publication data."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.llm_trace import write_trace
from src.tailor.g1 import G1Report, run_static_g1
from src.tailor.invoke import DEFAULT_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_text_model
from src.tailor.s3 import (
    ChangeEntry,
    EditBudget,
    S3HydrationError,
    S3Request,
    S3Response,
    TailoredDraft,
    build_s3_prompt,
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
    parse_s3_response,
    s3_response_to_dict,
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
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
) -> S3Outcome:
    template = Path(prompt_template_path).read_text(encoding="utf-8")
    prompt = build_s3_prompt(template, request)
    try:
        result = invoke_text_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        return S3Outcome(S3OutcomeKind.INVOCATION_FAILURE, None, None, str(exc), _trace(Path(request_path), Path(prompt_template_path), exc.raw_stdout, exc.model or (claude_cmd[0] if claude_cmd else ""), trace_dir))
    trace_path = _trace(Path(request_path), Path(prompt_template_path), result.raw_stdout, result.model, trace_dir)
    try:
        response = parse_s3_response(result.raw_stdout, request)
    except Exception as exc:
        from src.tailor.s3 import S3ParseError, S3SemanticError
        kind = S3OutcomeKind.PARSE_FAILURE if isinstance(exc, S3ParseError) else S3OutcomeKind.SEMANTIC_FAILURE if isinstance(exc, S3SemanticError) else S3OutcomeKind.PARSE_FAILURE
        return S3Outcome(kind, None, None, str(exc), trace_path)
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


def s3_bundle_to_dict(bundle: S3Bundle) -> dict[str, object]:
    return {
        "schema_version": bundle.schema_version,
        "job_id": bundle.job_id,
        "company": bundle.company,
        "title": bundle.title,
        "alignment_fingerprint": bundle.alignment_fingerprint,
        "response": s3_response_to_dict(bundle.response),
        "draft": bundle.draft.__dict__,
        "change_log": [entry.__dict__ for entry in bundle.change_log],
        "unified_diff": bundle.unified_diff,
        "edit_budget": bundle.edit_budget.__dict__,
        "g1": {
            "status": bundle.g1.status.value,
            "violations": [item.__dict__ for item in bundle.g1.violations],
            "edit_budget": bundle.g1.edit_budget.__dict__,
            "render_line_check": bundle.g1.render_line_check,
        },
    }
