"""S1 orchestration (M8P-1): build prompt -> invoke (tool-disabled) ->
trace (I11) -> strictly parse + semantically validate. Owns the only
filesystem I/O in the S1 path other than the CLI's request/artifact reads
and writes -- the parser in src/tailor/s1.py stays pure.

Every attempt is classified into exactly one S1OutcomeKind so the caller
(scripts/tailor_s1.py) can decide what -- if anything -- to publish. This
module never publishes s1.json; that atomic-write decision belongs to the
CLI, which only does it for S1OutcomeKind.VALID.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.llm_trace import write_trace
from src.tailor.invoke import DEFAULT_S1_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_s1_model
from src.tailor.providers import ModelCommand, trace_model_label
from src.tailor.s1 import (
    S1ParseError,
    S1Request,
    S1Response,
    S1SemanticError,
    build_s1_prompt,
    parse_s1_response,
)

TRACE_INVOCATION_TYPE = "tailoring_s1"


class S1OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"
    PARSE_FAILURE = "parse_failure"
    SEMANTIC_FAILURE = "semantic_failure"
    INJECTION_BLOCKED = "injection_blocked"
    VALID = "valid"


@dataclass(frozen=True)
class S1Outcome:
    kind: S1OutcomeKind
    response: S1Response | None
    error: str | None
    trace_path: Path | None


def run_s1_invocation(
    request: S1Request,
    *,
    prompt_template_path: Path,
    request_path: Path,
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] = DEFAULT_S1_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
) -> S1Outcome:
    """Run exactly one S1 attempt end to end. Never raises for a modeled
    failure -- every invocation, parse, or semantic failure is reported as
    a typed S1Outcome instead, so a caller cannot accidentally skip
    tracing or publish on a partial success."""
    effective_cmd = model_command if model_command is not None else command
    prompt_template_path = Path(prompt_template_path)
    request_path = Path(request_path)
    template_text = prompt_template_path.read_text()
    prompt = build_s1_prompt(template_text, request)

    try:
        if effective_cmd is not None:
            result = invoke_s1_model(prompt, command=effective_cmd, timeout=timeout)
        else:
            result = invoke_s1_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        trace_path = None
        if exc.raw_stdout.strip():
            trace_model = exc.model or (trace_model_label(effective_cmd) if effective_cmd else (claude_cmd[0] if claude_cmd else ""))
            trace_path = write_trace(
                invocation_type=TRACE_INVOCATION_TYPE,
                input_paths=[request_path],
                raw_output=exc.raw_stdout,
                prompt_path=prompt_template_path,
                model=trace_model,
                trace_dir=trace_dir,
            )
        return S1Outcome(kind=S1OutcomeKind.INVOCATION_FAILURE, response=None, error=str(exc), trace_path=trace_path)

    trace_path = write_trace(
        invocation_type=TRACE_INVOCATION_TYPE,
        input_paths=[request_path],
        raw_output=result.raw_stdout,
        prompt_path=prompt_template_path,
        model=result.model,
        trace_dir=trace_dir,
    )

    try:
        response = parse_s1_response(result.raw_stdout, request.jd_text)
    except S1ParseError as exc:
        return S1Outcome(kind=S1OutcomeKind.PARSE_FAILURE, response=None, error=str(exc), trace_path=trace_path)
    except S1SemanticError as exc:
        return S1Outcome(kind=S1OutcomeKind.SEMANTIC_FAILURE, response=None, error=str(exc), trace_path=trace_path)

    if response.suspected_injection:
        return S1Outcome(kind=S1OutcomeKind.INJECTION_BLOCKED, response=response, error=None, trace_path=trace_path)

    return S1Outcome(kind=S1OutcomeKind.VALID, response=response, error=None, trace_path=trace_path)
