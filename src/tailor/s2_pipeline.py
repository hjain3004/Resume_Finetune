"""S2 invocation, tracing, and deterministic validation outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from src.llm_trace import write_trace
from src.tailor.invoke import DEFAULT_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_text_model
from src.tailor.providers import ModelCommand, trace_model_label
from src.tailor.s2 import S2Request, S2Response, S2ParseError, S2SemanticError, S2ValidationError, build_s2_prompt, parse_s2_response

TRACE_INVOCATION_TYPE = "tailoring_s2"
class S2OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"; PARSE_FAILURE = "parse_failure"; SEMANTIC_FAILURE = "semantic_failure"; VALIDATION_FAILURE = "validation_failure"; VALID = "valid"
@dataclass(frozen=True)
class S2Outcome:
    kind: S2OutcomeKind
    response: S2Response | None
    error: str | None
    trace_path: Path | None

def run_s2_invocation(
    request: S2Request,
    *,
    prompt_template_path: Path,
    request_path: Path,
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
) -> S2Outcome:
    effective_cmd = model_command if model_command is not None else command
    template = Path(prompt_template_path).read_text(); prompt = build_s2_prompt(template, request)
    try:
        if effective_cmd is not None:
            result = invoke_text_model(prompt, command=effective_cmd, timeout=timeout)
        else:
            result = invoke_text_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        trace_model = exc.model or (trace_model_label(effective_cmd) if effective_cmd else (claude_cmd[0] if claude_cmd else ""))
        trace = write_trace(invocation_type=TRACE_INVOCATION_TYPE, input_paths=[Path(request_path)], raw_output=exc.raw_stdout, prompt_path=Path(prompt_template_path), model=trace_model, trace_dir=trace_dir) if exc.raw_stdout.strip() else None
        return S2Outcome(S2OutcomeKind.INVOCATION_FAILURE, None, str(exc), trace)
    trace = write_trace(invocation_type=TRACE_INVOCATION_TYPE, input_paths=[Path(request_path)], raw_output=result.raw_stdout, prompt_path=Path(prompt_template_path), model=result.model, trace_dir=trace_dir)
    try: response = parse_s2_response(result.raw_stdout, request)
    except S2ParseError as exc: return S2Outcome(S2OutcomeKind.PARSE_FAILURE, None, str(exc), trace)
    except S2SemanticError as exc: return S2Outcome(S2OutcomeKind.SEMANTIC_FAILURE, None, str(exc), trace)
    except S2ValidationError as exc: return S2Outcome(S2OutcomeKind.VALIDATION_FAILURE, None, str(exc), trace)
    return S2Outcome(S2OutcomeKind.VALID, response, None, trace)
