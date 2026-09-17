"""Multi-provider model command boundary for the tailoring lane.

Pure, deterministic command construction, argument validation, and output extraction
for Claude, Gemini, and Codex. Zero I/O in this module (CLAUDE.md prime directive 1).

Safety invariants:
- Zero tool authority and zero filesystem permissions for all providers.
- No auto-approval, yolo, or sandbox-bypass flags.
- Prompt delivered via positional argv or piped stdin as designed per CLI.
- Response extracted strictly from model output, stripping progress/diagnostics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Literal

FORBIDDEN_FLAG_PATTERNS: tuple[str, ...] = (
    "--yolo",
    "yolo",
    "auto_edit",
    "--dangerously-bypass-approvals-and-sandbox",
    "--full-auto",
)


class Provider(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"


@dataclass(frozen=True)
class ModelCommand:
    provider: Provider
    model: str | None
    argv: tuple[str, ...]
    prompt_via: Literal["argv", "stdin"]
    output_file: bool


def validate_model_name(model: str | None) -> str | None:
    """Validate model identifier: non-empty, no leading dash, no whitespace."""
    if model is None:
        return None
    if not model.strip() or model.startswith("-") or any(ch.isspace() for ch in model):
        raise ValueError(f"model must be a bare model name, got {model!r}")
    return model.strip()


def build_model_command(provider: Provider | str, model: str | None = None) -> ModelCommand:
    """Build a tool-disabled, safe ModelCommand for the requested provider.

    Reproduces DEFAULT_CLAUDE_CMD and lane.build_claude_cmd byte-for-byte for Claude.
    """
    if isinstance(provider, str):
        try:
            provider = Provider(provider.lower())
        except ValueError:
            raise ValueError(f"unknown provider {provider!r}; expected one of {[p.value for p in Provider]}")

    clean_model = validate_model_name(model)

    if provider is Provider.CLAUDE:
        if clean_model is None:
            argv = ("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")
        else:
            argv = ("claude", "-p", "--model", clean_model, "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")
        cmd = ModelCommand(
            provider=provider,
            model=clean_model,
            argv=argv,
            prompt_via="argv",
            output_file=False,
        )
    elif provider is Provider.GEMINI:
        if clean_model is None:
            argv = ("gemini", "--approval-mode", "default", "--output-format", "json")
        else:
            argv = ("gemini", "--approval-mode", "default", "--output-format", "json", "-m", clean_model)
        cmd = ModelCommand(
            provider=provider,
            model=clean_model,
            argv=argv,
            prompt_via="argv",
            output_file=False,
        )
    elif provider is Provider.CODEX:
        if clean_model is None:
            argv = (
                "codex", "exec", "--sandbox", "read-only", "--ephemeral",
                "--skip-git-repo-check", "--color", "never", "-",
            )
        else:
            argv = (
                "codex", "exec", "--sandbox", "read-only", "--ephemeral",
                "--skip-git-repo-check", "--color", "never", "-m", clean_model, "-",
            )
        cmd = ModelCommand(
            provider=provider,
            model=clean_model,
            argv=argv,
            prompt_via="stdin",
            output_file=True,
        )
    else:
        raise ValueError(f"unsupported provider: {provider}")

    # Safety invariant: assert no forbidden flags can ever be built
    joined = " ".join(cmd.argv)
    for forbidden in FORBIDDEN_FLAG_PATTERNS:
        if forbidden in cmd.argv or forbidden in joined:
            raise ValueError(f"Refusing to build command containing forbidden token {forbidden!r}")

    return cmd


def extract_model_text(command: ModelCommand, stdout: str, output_file_text: str = "") -> str:
    """Extract model response text, stripping CLI wrappers, progress, and logs."""
    if command.provider is Provider.CLAUDE:
        return stdout

    if command.provider is Provider.GEMINI:
        stripped = stdout.strip()
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                if "response" in data:
                    res = data["response"]
                    return res if isinstance(res, str) else json.dumps(res)
                if "error" in data:
                    return ""
        except (ValueError, TypeError):
            pass
        return stdout

    if command.provider is Provider.CODEX:
        return output_file_text

    raise ValueError(f"unknown provider: {command.provider}")


def trace_model_label(command: ModelCommand) -> str:
    """Format model label for I11 traces, e.g. 'gemini:gemini-2.5-pro' or 'codex:default'."""
    model_str = command.model if command.model is not None else "default"
    return f"{command.provider.value}:{model_str}"
