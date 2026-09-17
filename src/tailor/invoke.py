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

import json
import os
import subprocess
from dataclasses import dataclass

import requests

from src.tailor.providers import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_OPENAI_MODEL,
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

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


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


def _invoke_openai_http(
    prompt: str,
    *,
    command: ModelCommand,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InvocationResult:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = trace_model_label(command)
    if not api_key:
        raise InvocationError("OPENAI_API_KEY environment variable is not set", raw_stdout="", model=model)

    model_name = command.model or DEFAULT_OPENAI_MODEL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        resp = requests.post(OPENAI_CHAT_URL, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise InvocationError(f"model invocation timed out after {timeout}s", raw_stdout="", model=model) from exc
    except requests.exceptions.RequestException as exc:
        raise InvocationError(f"model HTTP request failed: {type(exc).__name__}", raw_stdout="", model=model) from exc

    if resp.status_code != 200:
        bounded_body = _bounded_stream("body", resp.text)
        raise InvocationError(
            f"model invocation HTTP {resp.status_code}; {bounded_body}",
            raw_stdout=resp.text,
            model=model,
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise InvocationError(
            f"model response was unparseable JSON: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        ) from exc

    if not isinstance(data, dict):
        raise InvocationError(
            f"model response was not a JSON object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise InvocationError(
            f"model response contained no choices: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise InvocationError(
            f"model choice was not an object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise InvocationError(
            f"model response choice contained no message object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InvocationError(
            "model response returned empty message content",
            raw_stdout=resp.text,
            model=model,
        )

    return InvocationResult(raw_stdout=content, bounded_stderr="stderr: <empty>", model=model)


def _invoke_gemini_http(
    prompt: str,
    *,
    command: ModelCommand,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> InvocationResult:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = trace_model_label(command)
    if not api_key:
        raise InvocationError("GEMINI_API_KEY environment variable is not set", raw_stdout="", model=model)

    model_name = command.model or DEFAULT_GEMINI_MODEL
    url = GEMINI_API_URL_TEMPLATE.format(model=model_name)
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise InvocationError(f"model invocation timed out after {timeout}s", raw_stdout="", model=model) from exc
    except requests.exceptions.RequestException as exc:
        raise InvocationError(f"model HTTP request failed: {type(exc).__name__}", raw_stdout="", model=model) from exc

    if resp.status_code != 200:
        bounded_body = _bounded_stream("body", resp.text)
        raise InvocationError(
            f"model invocation HTTP {resp.status_code}; {bounded_body}",
            raw_stdout=resp.text,
            model=model,
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise InvocationError(
            f"model response was unparseable JSON: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        ) from exc

    if not isinstance(data, dict):
        raise InvocationError(
            f"model response was not a JSON object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise InvocationError(
            f"model response contained no candidates: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    first_cand = candidates[0]
    if not isinstance(first_cand, dict):
        raise InvocationError(
            f"model candidate was not an object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    content_obj = first_cand.get("content")
    if not isinstance(content_obj, dict):
        raise InvocationError(
            f"model candidate contained no content object: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    parts = content_obj.get("parts")
    if not isinstance(parts, list) or not parts:
        raise InvocationError(
            f"model response candidate content had no parts: {_bounded_stream('body', resp.text)}",
            raw_stdout=resp.text,
            model=model,
        )

    text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p]
    content = "".join(text_chunks)
    if not content.strip():
        raise InvocationError(
            "model response returned empty text",
            raw_stdout=resp.text,
            model=model,
        )

    return InvocationResult(raw_stdout=content, bounded_stderr="stderr: <empty>", model=model)


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

    if command.provider is Provider.OPENAI:
        return _invoke_openai_http(prompt, command=command, timeout=timeout)

    if command.provider is Provider.GEMINI:
        return _invoke_gemini_http(prompt, command=command, timeout=timeout)

    model = trace_model_label(command)
    exec_argv = [*command.argv, prompt]

    try:
        result = subprocess.run(
            exec_argv,
            capture_output=True,
            text=True,
            timeout=timeout,
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

    extracted = extract_model_text(command, result.stdout)
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
