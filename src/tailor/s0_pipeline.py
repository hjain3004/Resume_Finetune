"""S0 invocation, tracing, and outcome classification."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from src.llm_trace import write_trace
from src.tailor.invoke import DEFAULT_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_text_model
from src.tailor.s0 import S0Request, S0Response, S0ParseError, S0SemanticError, build_s0_prompt, parse_s0_response

TRACE_INVOCATION_TYPE = "tailoring_s0"
class S0OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"
    PARSE_FAILURE = "parse_failure"
    SEMANTIC_FAILURE = "semantic_failure"
    VALID = "valid"
@dataclass(frozen=True)
class S0Outcome:
    kind: S0OutcomeKind
    response: S0Response | None
    error: str | None
    trace_path: Path | None

def run_s0_invocation(request: S0Request, *, prompt_template_path: Path, request_path: Path, claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD, timeout: float = DEFAULT_TIMEOUT_SECONDS, trace_dir: Path = Path("data/traces")) -> S0Outcome:
    template = Path(prompt_template_path).read_text()
    prompt = build_s0_prompt(template, request)
    try: result = invoke_text_model(prompt, claude_cmd=claude_cmd, timeout=timeout)
    except InvocationError as exc:
        trace = write_trace(invocation_type=TRACE_INVOCATION_TYPE, input_paths=[Path(request_path)], raw_output=exc.raw_stdout, prompt_path=Path(prompt_template_path), model=exc.model or (claude_cmd[0] if claude_cmd else ""), trace_dir=trace_dir) if exc.raw_stdout.strip() else None
        return S0Outcome(S0OutcomeKind.INVOCATION_FAILURE, None, str(exc), trace)
    trace = write_trace(invocation_type=TRACE_INVOCATION_TYPE, input_paths=[Path(request_path)], raw_output=result.raw_stdout, prompt_path=Path(prompt_template_path), model=result.model, trace_dir=trace_dir)
    try: response = parse_s0_response(result.raw_stdout, request)
    except S0ParseError as exc: return S0Outcome(S0OutcomeKind.PARSE_FAILURE, None, str(exc), trace)
    except S0SemanticError as exc: return S0Outcome(S0OutcomeKind.SEMANTIC_FAILURE, None, str(exc), trace)
    return S0Outcome(S0OutcomeKind.VALID, response, None, trace)
