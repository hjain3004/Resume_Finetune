"""Tests for the safe, tool-disabled S1 model invocation wrapper (M8P-1).

Mirrors scripts/score_batch.py's safe-invocation test style: subprocess.run
is patched/faked, never actually exec'd. No network, no real model call.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.tailor.invoke import (
    DEFAULT_S1_CLAUDE_CMD,
    InvocationError,
    InvocationResult,
    invoke_s1_model,
)


def test_default_command_shape_has_tools_disabled_and_no_session_persistence():
    assert DEFAULT_S1_CLAUDE_CMD == ("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")


def test_invoke_passes_prompt_as_final_positional_argv_element():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
    ) as mock_run:
        invoke_s1_model("PROMPT TEXT", claude_cmd=("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--"))

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[-1] == "PROMPT TEXT"
    assert cmd[:-1] == ["claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--"]
    # No shell invocation.
    assert kwargs.get("shell", False) is False


def test_invoke_never_uses_shell_true():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="{}", stderr="")
    ) as mock_run:
        invoke_s1_model("prompt")
    _, kwargs = mock_run.call_args
    assert "shell" not in kwargs or kwargs["shell"] is False


def test_invoke_success_returns_raw_stdout_and_model():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout='{"must_have": []}', stderr="")
    ):
        result = invoke_s1_model("prompt", claude_cmd=("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--"))
    assert isinstance(result, InvocationResult)
    assert result.raw_stdout == '{"must_have": []}'
    assert result.model == "claude"


def test_invoke_nonzero_exit_is_invocation_failure():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="boom")
    ):
        with pytest.raises(InvocationError):
            invoke_s1_model("prompt")


def test_invoke_nonzero_exit_carries_raw_stdout_when_present():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout="partial output", stderr="boom")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_s1_model("prompt")
    assert exc_info.value.raw_stdout == "partial output"


def test_invoke_empty_stdout_is_invocation_failure():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="   ", stderr="")
    ):
        with pytest.raises(InvocationError):
            invoke_s1_model("prompt")


def test_invoke_empty_stdout_failure_carries_no_raw_output():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="", stderr="")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_s1_model("prompt")
    assert exc_info.value.raw_stdout == ""


def test_invoke_timeout_is_invocation_failure():
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
        with pytest.raises(InvocationError):
            invoke_s1_model("prompt", timeout=5)


def test_invoke_timeout_carries_no_raw_output():
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
        with pytest.raises(InvocationError) as exc_info:
            invoke_s1_model("prompt", timeout=5)
    assert exc_info.value.raw_stdout == ""


def test_invoke_error_message_bounds_long_stdout_and_stderr():
    huge = "x" * 5000
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout=huge, stderr=huge)
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_s1_model("prompt")
    assert len(str(exc_info.value)) < len(huge)


def test_invoke_never_leaks_secret_env_values_in_diagnostics(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-super-secret-value")
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="failed")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_s1_model("prompt")
    assert "sk-super-secret-value" not in str(exc_info.value)


def test_invoke_claude_cmd_is_injectable():
    fake_cmd = ("python3", "-c", "print('hi')")
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="{}", stderr="")
    ) as mock_run:
        result = invoke_s1_model("prompt", claude_cmd=fake_cmd)
    assert result.model == "python3"
    args, _ = mock_run.call_args
    assert args[0][: len(fake_cmd)] == list(fake_cmd)


def test_invoke_timeout_is_explicit_and_passed_through():
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="{}", stderr="")
    ) as mock_run:
        invoke_s1_model("prompt", timeout=42)
    _, kwargs = mock_run.call_args
    assert kwargs.get("timeout") == 42
