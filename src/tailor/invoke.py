"""Safe, tool-disabled S1 model invocation (M8P-1).

Mirrors scripts/score_batch.py's safe command boundary (2026-07-13,
user-approved trust boundary): the nested `claude` call is a pure
text-in/text-out function with ZERO filesystem authority -- no tools, no
session persistence, no permission-bypass flags, no shell. The caller
embeds everything the model needs directly into the prompt text and reads
only stdout; this module never touches the filesystem itself.

No retries in M8P-1 (explicit decision) -- every invocation, including a
manual rerun, is one attempt and the caller creates one new immutable I11
trace per attempt.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

# Order matters -- see scripts/score_batch.py's DEFAULT_CLAUDE_CMD comment:
# `--tools` is variadic and greedily consumes following non-flag argv, so
# `--tools ""` must never be last; the trailing "--" keeps the prompt
# positional even if it starts with a dash.
DEFAULT_S1_CLAUDE_CMD: tuple[str, ...] = ("claude", "-p", "--tools", "", "--no-session-persistence", "--")
DEFAULT_TIMEOUT_SECONDS = 300
_DIAGNOSTIC_MAX_CHARS = 1000


class InvocationError(RuntimeError):
    """The S1 model invocation itself failed (timeout, nonzero exit, empty
    stdout). Carries `raw_stdout` (possibly empty) so the caller can still
    write an I11 trace when raw output exists despite the failure."""

    def __init__(self, message: str, *, raw_stdout: str = "", model: str = ""):
        super().__init__(message)
        self.raw_stdout = raw_stdout
        self.model = model


@dataclass(frozen=True)
class InvocationResult:
    raw_stdout: str
    bounded_stderr: str
    model: str


def _bounded_stream(name: str, text: str, limit: int = _DIAGNOSTIC_MAX_CHARS) -> str:
    stripped = text.strip()
    if not stripped:
        return f"{name}: <empty>"
    if len(stripped) <= limit:
        return f"{name}: {stripped}"
    omitted = len(stripped) - limit
    return f"{name}: {stripped[:limit]}...<truncated {omitted} chars>"


def invoke_s1_model(
    prompt: str,
    *,
    claude_cmd: tuple[str, ...] = DEFAULT_S1_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InvocationResult:
    """Run exactly one S1 model invocation. No shell, no retries.

    Raises InvocationError on timeout, nonzero exit, or empty stdout.
    """
    model = claude_cmd[0] if claude_cmd else ""
    try:
        result = subprocess.run(
            [*claude_cmd, prompt], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise InvocationError(f"S1 invocation timed out after {timeout}s", raw_stdout="", model=model) from exc

    bounded_stderr = _bounded_stream("stderr", result.stderr)
    if result.returncode != 0:
        raise InvocationError(
            f"S1 invocation exited {result.returncode}; "
            f"{_bounded_stream('stdout', result.stdout)}; {bounded_stderr}",
            raw_stdout=result.stdout,
            model=model,
        )
    if not result.stdout.strip():
        raise InvocationError(
            f"S1 invocation returned empty stdout ({bounded_stderr})", raw_stdout="", model=model
        )

    return InvocationResult(raw_stdout=result.stdout, bounded_stderr=bounded_stderr, model=model)
