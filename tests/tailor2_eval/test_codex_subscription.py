from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from src.tailor2.codex_subscription import (
    CodexPilotBudget,
    CodexSubscriptionInvoker,
    CodexPilotInterrupted,
    stage_output_schema,
)


def _fake_codex(tmp_path: Path, response: dict, *, invalid_first: bool = False, rate_limit: bool = False) -> Path:
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps(response), encoding="utf-8")
    script = tmp_path / "fake-codex"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "log = Path(os.environ['FAKE_CODEX_LOG'])\n"
        "log.write_text(log.read_text() + json.dumps({'argv': args, 'prompt': sys.stdin.read()}) + '\\n' if log.exists() else json.dumps({'argv': args, 'prompt': sys.stdin.read()}) + '\\n')\n"
        "output_path = Path(args[args.index('--output-last-message') + 1])\n"
        "response_path = Path(os.environ['FAKE_CODEX_RESPONSE'])\n"
        "if os.environ.get('FAKE_CODEX_RATE_LIMIT'):\n"
        "    print('rate limit', file=sys.stderr)\n"
        "    raise SystemExit(429)\n"
        "if os.environ.get('FAKE_CODEX_INVALID_FIRST') and not Path(os.environ['FAKE_CODEX_STATE']).exists():\n"
        "    Path(os.environ['FAKE_CODEX_STATE']).write_text('used')\n"
        "    output_path.write_text('{\\\"invalid\\\":true}')\n"
        "else:\n"
        "    output_path.write_text(response_path.read_text())\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'thread-fake'}))\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 11, 'cached_input_tokens': 3, 'output_tokens': 7, 'reasoning_output_tokens': 2}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _invoker(tmp_path: Path, script: Path, *, budget: CodexPilotBudget | None = None) -> CodexSubscriptionInvoker:
    return CodexSubscriptionInvoker(
        role="draft",
        codex_executable=str(script),
        trace_dir=tmp_path / "traces",
        budget=budget,
        codex_version="codex-cli 0.145.0",
        extra_environment={
            "FAKE_CODEX_LOG": str(tmp_path / "calls.jsonl"),
            "FAKE_CODEX_RESPONSE": str(tmp_path / "response.json"),
        },
    )


def test_codex_subscription_identity_and_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "atomic_requirements": [],
        "selected_evidence_ids": [],
        "amdocs_omission_ledger": [],
        "section_order": [],
        "bullets": [],
    }
    script = _fake_codex(tmp_path, response)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-be-read")

    invoker = _invoker(tmp_path, script)
    assert invoker.provider == "codex_subscription"
    assert invoker.model == "gpt-5.6-luna"
    assert invoker.invoke("self-contained prompt", "draft") == json.dumps(response)

    call = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "gpt-5.6-luna"
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in argv
    assert "--output-schema" in argv
    assert call["prompt"] == "self-contained prompt"
    assert invoker.metadata["authentication_mode"] == "ChatGPT-managed"
    assert invoker.metadata["cost_status"] == "not_applicable_subscription"
    assert invoker.metadata["usage"][0]["thread_id"] == "thread-fake"


def test_stage_schema_is_written_and_raw_events_are_not_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = {"repaired_bullets": []}
    script = _fake_codex(tmp_path, response)
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_CODEX_RESPONSE", str(tmp_path / "response.json"))
    invoker = CodexSubscriptionInvoker(
        role="repair",
        codex_executable=str(script),
        trace_dir=tmp_path / "traces",
        codex_version="codex-cli 0.145.0",
        extra_environment={
            "FAKE_CODEX_LOG": str(tmp_path / "calls.jsonl"),
            "FAKE_CODEX_RESPONSE": str(tmp_path / "response.json"),
        },
    )
    assert invoker.invoke("repair prompt", "repair") == json.dumps(response)
    call = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    schema_path = Path(call["argv"][call["argv"].index("--output-schema") + 1])
    assert schema_path.exists() is False
    assert stage_output_schema("repair")["required"] == ["repaired_bullets"]
    assert stage_output_schema("missing_evidence")["required"] == ["recovered_bullets"]
    assert not list(tmp_path.rglob("*.jsonl"))[1:]


def test_invalid_structured_output_has_one_bounded_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = {"repaired_bullets": []}
    script = _fake_codex(tmp_path, response, invalid_first=True)
    monkeypatch.setenv("FAKE_CODEX_INVALID_FIRST", "1")
    monkeypatch.setenv("FAKE_CODEX_STATE", str(tmp_path / "state"))
    invoker = CodexSubscriptionInvoker(
        role="repair", codex_executable=str(script), trace_dir=tmp_path / "traces", max_retries=1,
        extra_environment={
            "FAKE_CODEX_LOG": str(tmp_path / "calls.jsonl"),
            "FAKE_CODEX_RESPONSE": str(tmp_path / "response.json"),
            "FAKE_CODEX_INVALID_FIRST": "1",
            "FAKE_CODEX_STATE": str(tmp_path / "state"),
        },
    )
    assert json.loads(invoker.invoke("repair prompt", "repair")) == response
    assert len((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert invoker.metadata["retry_count"] == 1


def test_budget_exhaustion_is_resumable_and_counts_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = {"repaired_bullets": []}
    script = _fake_codex(tmp_path, response)
    budget = CodexPilotBudget(max_invocations=1)
    invoker = _invoker(tmp_path, script, budget=budget)
    invoker.invoke("prompt", "repair")
    with pytest.raises(CodexPilotInterrupted):
        invoker.invoke("prompt", "repair")
    assert budget.used_invocations == 1
    assert invoker.metadata["usage"][0]["input_count"] == 11


def test_safe_environment_does_not_pass_api_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = {"repaired_bullets": []}
    script = _fake_codex(tmp_path, response)
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("CODEX_API_KEY", "secret")
    invoker = _invoker(tmp_path, script)
    invoker.invoke("prompt", "repair")
    assert "secret" not in (tmp_path / "calls.jsonl").read_text(encoding="utf-8")


def test_independent_roles_use_separate_processes_and_no_repo_cwd(tmp_path: Path) -> None:
    response = {"repaired_bullets": []}
    script = _fake_codex(tmp_path, response)
    shared = {
        "FAKE_CODEX_LOG": str(tmp_path / "calls.jsonl"),
        "FAKE_CODEX_RESPONSE": str(tmp_path / "response.json"),
    }
    draft = CodexSubscriptionInvoker(
        role="draft", codex_executable=str(script), trace_dir=tmp_path / "traces", extra_environment=shared
    )
    audit = CodexSubscriptionInvoker(
        role="audit", codex_executable=str(script), trace_dir=tmp_path / "traces", extra_environment=shared
    )
    draft.invoke("draft", "repair")
    audit.invoke("audit", "repair")
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 2
    assert all(Path(c["argv"][c["argv"].index("-C") + 1]) != Path.cwd() for c in calls)
    assert draft.metadata["role"] != audit.metadata["role"]


def test_rate_limit_is_resumable_not_fatal(tmp_path: Path) -> None:
    script = _fake_codex(tmp_path, {"repaired_bullets": []})
    invoker = CodexSubscriptionInvoker(
        role="audit",
        codex_executable=str(script),
        extra_environment={
            "FAKE_CODEX_LOG": str(tmp_path / "calls.jsonl"),
            "FAKE_CODEX_RESPONSE": str(tmp_path / "response.json"),
            "FAKE_CODEX_RATE_LIMIT": "1",
        },
    )
    with pytest.raises(CodexPilotInterrupted, match="subscription interruption"):
        invoker.invoke("audit", "repair")
    assert invoker.metadata["usage"][0]["outcome"] == "process_error"
