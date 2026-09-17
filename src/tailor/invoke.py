"""Safe, tool-disabled model invocation (M8P-1, multi-provider).

Mirrors scripts/score_batch.py's safe command boundary (2026-07-13,
user-approved trust boundary): the model call is a pure text-in/text-out function
with ZERO filesystem authority -- no tools, no session persistence, no permission-bypass
flags, no shell.

For Gemini and Codex, the subprocess runs in an isolated empty temporary directory.
For Codex, the final model message is captured via --output-last-message inside the temp dir,
which is a deliberate, documented exception to "invoke.py never touches the filesystem".

No retries in M8P-1 (explicit decision) -- every invocation, including a manual rerun,
is one attempt and the caller creates one new immutable I11 trace per attempt.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.tailor.providers import (
    ModelCommand,
    Provider,
    extract_model_text,
    trace_model_label,
)

# Order matters -- see scripts/score_batch.py's DEFAULT_CLAUDE_CMD comment:
# `--tools` is variadic and greedily consumes following non-flag argv, so
# `--tools ""` must never be last; the trailing "--" keeps the prompt
# positional even if it starts with a dash.
DEFAULT_CLAUDE_CMD: tuple[str, ...] = ("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")
DEFAULT_S1_CLAUDE_CMD = DEFAULT_CLAUDE_CMD
DEFAULT_TIMEOUT_SECONDS = 300
_DIAGNOSTIC_MAX_CHARS = 1000


class InvocationError(RuntimeError):
    """The model invocation itself failed (timeout, nonzero exit, empty
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


def invoke_text_model(
    prompt: str,
    *,
    command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InvocationResult:
    """Run exactly one model invocation. No shell, no retries.

    Accepts a ModelCommand or a legacy claude_cmd tuple.
    Raises InvocationError on timeout, nonzero exit, or empty extracted output.
    """
    if command is None:
        cmd_tuple = claude_cmd if claude_cmd is not None else DEFAULT_CLAUDE_CMD
        model = cmd_tuple[0] if cmd_tuple else ""
        try:
            result = subprocess.run(
                [*cmd_tuple, prompt], capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise InvocationError(f"model invocation timed out after {timeout}s", raw_stdout="", model=model) from exc

        bounded_stderr = _bounded_stream("stderr", result.stderr)
        if result.returncode != 0:
            raise InvocationError(
                f"model invocation exited {result.returncode}; "
                f"{_bounded_stream('stdout', result.stdout)}; {bounded_stderr}",
                raw_stdout=result.stdout,
                model=model,
            )
        if not result.stdout.strip():
            raise InvocationError(
                f"model invocation returned empty stdout ({bounded_stderr})", raw_stdout="", model=model
            )

        return InvocationResult(raw_stdout=result.stdout, bounded_stderr=bounded_stderr, model=model)

    model = trace_model_label(command)
    with tempfile.TemporaryDirectory(prefix="tailor-invoke-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        output_file_path: Path | None = None
        output_file_text = ""

        if command.prompt_via == "stdin":
            run_input: str | None = prompt
            if command.output_file:
                output_file_path = temp_dir_path / "last_message.txt"
                if command.argv and command.argv[-1] == "-":
                    exec_argv = [*command.argv[:-1], "--output-last-message", str(output_file_path), "-"]
                else:
                    exec_argv = [*command.argv, "--output-last-message", str(output_file_path)]
            else:
                exec_argv = list(command.argv)
        else:
            run_input = None
            exec_argv = [*command.argv, prompt]

        run_cwd = temp_dir if command.provider in (Provider.GEMINI, Provider.CODEX) else None

        try:
            result = subprocess.run(
                exec_argv,
                input=run_input,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=run_cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise InvocationError(f"model invocation timed out after {timeout}s", raw_stdout="", model=model) from exc

        if output_file_path is not None and output_file_path.exists():
            output_file_text = output_file_path.read_text(encoding="utf-8")

        bounded_stderr = _bounded_stream("stderr", result.stderr)
        if result.returncode != 0:
            raise InvocationError(
                f"model invocation exited {result.returncode}; "
                f"{_bounded_stream('stdout', result.stdout)}; {bounded_stderr}",
                raw_stdout=result.stdout,
                model=model,
            )

        extracted = extract_model_text(command, result.stdout, output_file_text)
        if not extracted.strip():
            raise InvocationError(
                f"model invocation returned empty output ({bounded_stderr})",
                raw_stdout=result.stdout,
                model=model,
            )

        return InvocationResult(raw_stdout=extracted, bounded_stderr=bounded_stderr, model=model)


def invoke_s1_model(
    prompt: str,
    *,
    command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InvocationResult:
    """Compatibility wrapper retaining the M8P-1 public API."""
    return invoke_text_model(prompt, command=command, claude_cmd=claude_cmd, timeout=timeout)
