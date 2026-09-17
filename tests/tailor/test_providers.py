"""Tests for multi-provider invocation (Claude, Gemini, Codex) in the tailoring lane.

Tests run offline with no network and no real CLI calls (CLAUDE.md prime directive 5).
"""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.tailor.invoke import (
    DEFAULT_CLAUDE_CMD,
    InvocationError,
    InvocationResult,
    invoke_text_model,
)
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    LANE_MANIFEST_SCHEMA,
    LaneError,
    build_claude_cmd,
    lane_directory,
    lane_manifest_to_dict,
    normalize_jd,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import Stage
from src.tailor.preflight import PreflightReport
from src.tailor.providers import (
    FORBIDDEN_FLAG_PATTERNS,
    ModelCommand,
    Provider,
    build_authority_canary_prompt,
    build_model_command,
    evaluate_authority_canary,
    extract_model_text,
    trace_model_label,
    validate_model_name,
)
from tests.tailor.test_pilot import PILOT_JOB_ID, _build_valid_chain

PROFILE = Path("config/master_profile.yaml")
JD_TEXT = "Python " * 60  # 420 chars


# ---------------------------------------------------------------------------
# 1. argv construction per provider (with and without model)
# ---------------------------------------------------------------------------


def test_argv_construction_claude_has_mcp_and_tools_disabled():
    cmd_default = build_model_command(Provider.CLAUDE, None)
    assert cmd_default.provider == Provider.CLAUDE
    assert cmd_default.model is None
    assert cmd_default.argv == DEFAULT_CLAUDE_CMD
    assert cmd_default.argv == ("claude", "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")
    assert cmd_default.prompt_via == "argv"
    assert cmd_default.output_file is False

    cmd_model = build_model_command(Provider.CLAUDE, "sonnet")
    assert cmd_model.provider == Provider.CLAUDE
    assert cmd_model.model == "sonnet"
    assert cmd_model.argv == build_claude_cmd("sonnet")
    assert cmd_model.argv == ("claude", "-p", "--model", "sonnet", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")
    assert cmd_model.prompt_via == "argv"
    assert cmd_model.output_file is False


def test_every_claude_argv_contains_mcp_isolation_flag():
    from scripts import score_batch
    from src.tailor.lane import build_claude_cmd
    from src.tailor.invoke import DEFAULT_CLAUDE_CMD as INVOKE_CLAUDE_CMD

    commands_to_check = [
        INVOKE_CLAUDE_CMD,
        score_batch.DEFAULT_CLAUDE_CMD,
        build_claude_cmd(None),
        build_claude_cmd("sonnet"),
        build_model_command(Provider.CLAUDE, None).argv,
        build_model_command(Provider.CLAUDE, "haiku").argv,
    ]
    for cmd in commands_to_check:
        assert "--strict-mcp-config" in cmd, f"Missing --strict-mcp-config in {cmd}"
        tools_idx = cmd.index("--tools")
        assert cmd[tools_idx + 1] == "", f"Expected empty string after --tools in {cmd}"
        assert cmd[-1] == "--", f"Expected trailing '--' in {cmd}"


def test_argv_construction_gemini():
    cmd_default = build_model_command(Provider.GEMINI, None)
    assert cmd_default.provider == Provider.GEMINI
    assert cmd_default.model is None
    assert cmd_default.argv == ("gemini", "--approval-mode", "default", "--output-format", "json")
    assert cmd_default.prompt_via == "argv"
    assert cmd_default.output_file is False

    cmd_model = build_model_command(Provider.GEMINI, "gemini-2.5-pro")
    assert cmd_model.provider == Provider.GEMINI
    assert cmd_model.model == "gemini-2.5-pro"
    assert cmd_model.argv == ("gemini", "--approval-mode", "default", "--output-format", "json", "-m", "gemini-2.5-pro")
    assert cmd_model.prompt_via == "argv"
    assert cmd_model.output_file is False


def test_argv_construction_codex():
    cmd_default = build_model_command(Provider.CODEX, None)
    assert cmd_default.provider == Provider.CODEX
    assert cmd_default.model is None
    assert cmd_default.argv == (
        "codex", "exec", "--sandbox", "read-only", "--ephemeral",
        "--skip-git-repo-check", "--color", "never", "-",
    )
    assert cmd_default.prompt_via == "stdin"
    assert cmd_default.output_file is True

    cmd_model = build_model_command(Provider.CODEX, "o3")
    assert cmd_model.provider == Provider.CODEX
    assert cmd_model.model == "o3"
    assert cmd_model.argv == (
        "codex", "exec", "--sandbox", "read-only", "--ephemeral",
        "--skip-git-repo-check", "--color", "never", "-m", "o3", "-",
    )
    assert cmd_model.prompt_via == "stdin"
    assert cmd_model.output_file is True


# ---------------------------------------------------------------------------
# 2. Forbidden flags test across all providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize("model", [None, "valid-model"])
def test_forbidden_flags_never_appear_in_built_argv(provider, model):
    cmd = build_model_command(provider, model)
    joined = " ".join(cmd.argv)
    for forbidden in FORBIDDEN_FLAG_PATTERNS:
        assert forbidden not in cmd.argv, f"Forbidden token {forbidden!r} found in {cmd.argv}"
        assert forbidden not in joined, f"Forbidden pattern {forbidden!r} found in {joined}"


# ---------------------------------------------------------------------------
# 3. Model name validation across all providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", list(Provider))
@pytest.mark.parametrize("bad_name", ["", "   ", "-flag", "--model", "has space", "foo\tbar", "\n"])
def test_invalid_model_names_rejected_for_every_provider(provider, bad_name):
    with pytest.raises(ValueError):
        build_model_command(provider, bad_name)


# ---------------------------------------------------------------------------
# 4. Trace model label per provider
# ---------------------------------------------------------------------------


def test_trace_model_label_per_provider():
    assert trace_model_label(build_model_command(Provider.CLAUDE, None)) == "claude:default"
    assert trace_model_label(build_model_command(Provider.CLAUDE, "sonnet")) == "claude:sonnet"
    assert trace_model_label(build_model_command(Provider.GEMINI, None)) == "gemini:default"
    assert trace_model_label(build_model_command(Provider.GEMINI, "gemini-2.5-pro")) == "gemini:gemini-2.5-pro"
    assert trace_model_label(build_model_command(Provider.CODEX, None)) == "codex:default"
    assert trace_model_label(build_model_command(Provider.CODEX, "o3")) == "codex:o3"


# ---------------------------------------------------------------------------
# 5. Text extraction: gemini JSON, codex output-file, noisy stdout
# ---------------------------------------------------------------------------


def test_text_extraction_claude():
    cmd = build_model_command(Provider.CLAUDE, None)
    assert extract_model_text(cmd, "claude response text", "") == "claude response text"


def test_text_extraction_gemini_json_and_noisy_stdout():
    cmd = build_model_command(Provider.GEMINI, None)
    valid_json = json.dumps({"response": "tailored resume content", "stats": {"tokens": 123}})
    assert extract_model_text(cmd, valid_json, "") == "tailored resume content"

    # Non-json fallback
    assert extract_model_text(cmd, "plain text response", "") == "plain text response"

    # Error json extracts to empty string
    err_json = json.dumps({"error": {"message": "quota exceeded"}})
    assert extract_model_text(cmd, err_json, "") == ""


def test_text_extraction_codex_output_file_ignores_noisy_stdout():
    cmd = build_model_command(Provider.CODEX, None)
    noisy_stdout = "2026-09-17 [INFO] starting codex\nTurn 1: thinking\nProgress: 100%\n"
    output_file_content = "final agent message only"
    extracted = extract_model_text(cmd, noisy_stdout, output_file_content)
    assert extracted == "final agent message only"
    assert "Progress" not in extracted
    assert "INFO" not in extracted


# ---------------------------------------------------------------------------
# 6. Prompt delivery via argv vs stdin, and temp cwd for gemini/codex
# ---------------------------------------------------------------------------


def test_invoke_claude_prompt_via_argv():
    cmd = build_model_command(Provider.CLAUDE, None)
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="response", stderr="")
    ) as mock_run:
        result = invoke_text_model("MY PROMPT", command=cmd)

    args, kwargs = mock_run.call_args
    exec_argv = args[0]
    assert exec_argv[-1] == "MY PROMPT"
    assert exec_argv[:-1] == list(cmd.argv)
    assert result.raw_stdout == "response"
    assert result.model == "claude:default"


def test_invoke_gemini_prompt_via_argv_and_cwd_in_tempdir():
    cmd = build_model_command(Provider.GEMINI, "gemini-2.5-pro")
    captured_cwd = []

    def fake_run(args, **kwargs):
        captured_cwd.append(kwargs.get("cwd"))
        return MagicMock(returncode=0, stdout=json.dumps({"response": "gemini ok"}), stderr="")

    with patch.object(subprocess, "run", side_effect=fake_run) as mock_run:
        result = invoke_text_model("MY GEMINI PROMPT", command=cmd)

    args, kwargs = mock_run.call_args
    exec_argv = args[0]
    assert exec_argv[-1] == "MY GEMINI PROMPT"
    assert exec_argv[:-1] == list(cmd.argv)
    assert result.raw_stdout == "gemini ok"
    assert result.model == "gemini:gemini-2.5-pro"

    # cwd is a temp dir that was created and is not repo
    assert captured_cwd[0] is not None
    assert str(captured_cwd[0]) != str(Path.cwd())
    assert "tailor-invoke-" in str(captured_cwd[0])


def test_invoke_codex_prompt_via_stdin_and_output_last_message():
    cmd = build_model_command(Provider.CODEX, "o3")
    captured_kwargs = []

    def fake_run(args, **kwargs):
        captured_kwargs.append((args, kwargs))
        # Find --output-last-message path and simulate codex writing it
        assert "--output-last-message" in args
        idx = args.index("--output-last-message")
        out_file = Path(args[idx + 1])
        out_file.write_text("codex message from file", encoding="utf-8")
        return MagicMock(returncode=0, stdout="progress logging\n", stderr="")

    with patch.object(subprocess, "run", side_effect=fake_run):
        result = invoke_text_model("MY CODEX PROMPT", command=cmd)

    exec_argv, kwargs = captured_kwargs[0]
    assert kwargs.get("input") == "MY CODEX PROMPT"
    assert kwargs.get("cwd") is not None
    assert "tailor-invoke-" in str(kwargs.get("cwd"))
    assert exec_argv[-1] == "-"
    assert "--output-last-message" in exec_argv
    assert result.raw_stdout == "codex message from file"
    assert result.model == "codex:o3"


# ---------------------------------------------------------------------------
# 7. InvocationError handling: timeout, nonzero exit, empty extracted text
# ---------------------------------------------------------------------------


def test_invoke_nonzero_exit_carries_raw_stdout():
    cmd = build_model_command(Provider.GEMINI, None)
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=1, stdout="raw error body", stderr="err")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_text_model("prompt", command=cmd)
    assert exc_info.value.raw_stdout == "raw error body"
    assert exc_info.value.model == "gemini:default"


def test_invoke_empty_extracted_text_carries_raw_stdout():
    cmd = build_model_command(Provider.GEMINI, None)
    # Gemini stdout has valid json with empty response
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=json.dumps({"response": "   "}), stderr="")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_text_model("prompt", command=cmd)
    assert "response" in exc_info.value.raw_stdout
    assert exc_info.value.model == "gemini:default"


def test_invoke_codex_missing_output_file_raises_invocation_error():
    cmd = build_model_command(Provider.CODEX, None)
    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout="noisy stdout but no file written", stderr="")
    ):
        with pytest.raises(InvocationError) as exc_info:
            invoke_text_model("prompt", command=cmd)
    assert exc_info.value.raw_stdout == "noisy stdout but no file written"
    assert exc_info.value.model == "codex:default"


def test_invoke_timeout_carries_empty_raw_stdout():
    cmd = build_model_command(Provider.CODEX, None)
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=10)):
        with pytest.raises(InvocationError) as exc_info:
            invoke_text_model("prompt", command=cmd, timeout=10)
    assert exc_info.value.raw_stdout == ""
    assert exc_info.value.model == "codex:default"


# ---------------------------------------------------------------------------
# 8. Manifest round-trip including provider, and old manifests default to claude
# ---------------------------------------------------------------------------


def test_manifest_round_trip_with_provider():
    for p in ("claude", "gemini", "codex"):
        raw = {
            "schema_version": LANE_MANIFEST_SCHEMA, "job_id": -10, "jd_sha256": "b" * 64,
            "jd_path": "inbox/jd/y.txt", "company": "Co", "title": "Dev", "variant": "backend",
            "model": "m1", "claude_cmd": ["dummy", "cmd"], "jd_quality": "ats",
            "created_at": "2026-09-16T00:00:00+00:00", "provider": p,
        }
        manifest = parse_lane_manifest(raw)
        assert manifest.provider == p
        assert lane_manifest_to_dict(manifest) == raw


def test_old_manifest_without_provider_defaults_to_claude():
    old_raw = {
        "schema_version": LANE_MANIFEST_SCHEMA, "job_id": -5, "jd_sha256": "a" * 64,
        "jd_path": "inbox/jd/x.txt", "company": "Acme", "title": "Engineer", "variant": "backend",
        "model": None, "claude_cmd": list(DEFAULT_CLAUDE_CMD), "jd_quality": "ats",
        "created_at": "2026-09-01T00:00:00+00:00",
    }
    manifest = parse_lane_manifest(old_raw)
    assert manifest.provider == "claude"


# ---------------------------------------------------------------------------
# 9. Lane directory suffixing and multi-provider side-by-side isolation
# ---------------------------------------------------------------------------


def test_lane_directory_suffixing(tmp_path):
    root = tmp_path / "apps"
    d_claude = lane_directory(root, "Stripe", "Backend Engineer", suffix=None, provider="claude")
    d_gemini = lane_directory(root, "Stripe", "Backend Engineer", suffix=None, provider="gemini")
    d_codex = lane_directory(root, "Stripe", "Backend Engineer", suffix=None, provider="codex")

    assert d_claude.name == "stripe-backend_engineer"
    assert d_gemini.name == "stripe-backend_engineer-gemini"
    assert d_codex.name == "stripe-backend_engineer-codex"
    assert len({d_claude, d_gemini, d_codex}) == 3

    # With user-provided suffix
    d_claude_s = lane_directory(root, "Stripe", "Backend Engineer", suffix="team_a", provider="claude")
    d_gemini_s = lane_directory(root, "Stripe", "Backend Engineer", suffix="team_a", provider="gemini")
    d_codex_s = lane_directory(root, "Stripe", "Backend Engineer", suffix="team_a", provider="codex")

    assert d_claude_s.name == "stripe-backend_engineer-team_a"
    assert d_gemini_s.name == "stripe-backend_engineer-team_a-gemini"
    assert d_codex_s.name == "stripe-backend_engineer-team_a-codex"
    assert len({d_claude_s, d_gemini_s, d_codex_s}) == 3


# ---------------------------------------------------------------------------
# 10. Preflight failure when provider executable is not on PATH
# ---------------------------------------------------------------------------


def test_preflight_fails_when_provider_executable_not_on_path(tmp_path, monkeypatch):
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(JD_TEXT, encoding="utf-8")

    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    monkeypatch.setattr("shutil.which", lambda exe: None if exe == "gemini" else "/usr/bin/" + exe)

    outcome = run_manual_application(
        jd_file, company="Example", title="Engineer", variant="ml",
        root=tmp_path / "apps", profile_path=PROFILE, provider="gemini",
    )
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "preflight_failure"
    assert "gemini" in outcome.manifest.stages[0].error
    assert not (tmp_path / "apps").exists()


# ---------------------------------------------------------------------------
# 11. End-to-end composer & zero model calls on identical rerun per provider
# ---------------------------------------------------------------------------


@pytest.fixture
def passing_preflight(monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    monkeypatch.setattr("shutil.which", lambda exe: f"/fake/bin/{exe}")
    monkeypatch.setattr("src.tailor.lane.check_gemini_credentials", lambda *a, **k: None)


@pytest.fixture
def pinned_job_id(monkeypatch):
    monkeypatch.setattr("src.tailor.lane.lane_job_id", lambda jd_text: PILOT_JOB_ID)


class _Spy:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []


@pytest.fixture
def fake_chain(monkeypatch):
    from src.tailor.g2_pipeline import G2Outcome, G2OutcomeKind
    from src.tailor.g3 import G3Outcome, G3OutcomeKind, packet_to_dict
    from src.tailor.publish import render_result_to_dict
    from src.tailor.s0_pipeline import S0Outcome, S0OutcomeKind
    from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind
    from src.tailor.s2_pipeline import S2Outcome, S2OutcomeKind
    from src.tailor.s3_pipeline import S3Outcome, S3OutcomeKind
    from src.tailor.publish import RenderOutcome, RenderOutcomeKind

    chain = _build_valid_chain()
    spy = _Spy()

    def fake_s1(request, **kwargs):
        spy.calls.append(("s1", kwargs.get("model_command") or kwargs.get("claude_cmd")))
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        spy.calls.append(("s0", kwargs.get("model_command") or kwargs.get("claude_cmd")))
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        spy.calls.append(("s2", kwargs.get("model_command") or kwargs.get("claude_cmd")))
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        spy.calls.append(("s3", kwargs.get("model_command") or kwargs.get("claude_cmd")))
        return S3Outcome(kind=S3OutcomeKind.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        spy.calls.append(("g2", kwargs.get("model_command") or kwargs.get("claude_cmd")))
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    def fake_render(profile, draft, *, root, directory=None, reject_dir=None, **kwargs):
        spy.calls.append(("render", (directory, reject_dir)))
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render_result.json").write_text(
            json.dumps(render_result_to_dict(chain.render_result)), encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.VALID, result=chain.render_result, violations=(), error=None)

    def fake_g3(packet, changed_bullet_ids, directory):
        spy.calls.append(("g3", ()))
        Path(directory).mkdir(parents=True, exist_ok=True)
        (Path(directory) / "packet.json").write_text(json.dumps(packet_to_dict(packet)), encoding="utf-8")
        return G3Outcome(kind=G3OutcomeKind.BUILT, packet=packet, error=None)

    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1)
    monkeypatch.setattr("src.tailor.pilot.run_s0_invocation", fake_s0)
    monkeypatch.setattr("src.tailor.pilot.run_s2_invocation", fake_s2)
    monkeypatch.setattr("src.tailor.pilot.run_s3_invocation", fake_s3)
    monkeypatch.setattr("src.tailor.pilot.run_g2_loop", fake_g2)
    monkeypatch.setattr("src.tailor.pilot.render_and_publish", fake_render)
    monkeypatch.setattr("src.tailor.pilot.publish_packet", fake_g3)

    return spy


@pytest.mark.parametrize("provider", ["claude", "gemini", "codex"])
def test_full_run_and_identical_rerun_zero_calls_per_provider(
    tmp_path, fake_chain, passing_preflight, pinned_job_id, provider
):
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text(JD_TEXT, encoding="utf-8")
    root = tmp_path / "apps"

    # First run
    outcome = run_manual_application(
        jd_file, company="Example", title="Engineer", variant="ml",
        root=root, profile_path=PROFILE, provider=provider,
    )
    assert outcome.failed_stage is None
    expected_dir = lane_directory(root, "Example", "Engineer", provider=provider)
    assert expected_dir.exists()

    manifest = parse_lane_manifest(json.loads((expected_dir / "lane_manifest.json").read_text(encoding="utf-8")))
    assert manifest.provider == provider

    # Model command was passed to stages
    model_cmds = [cmd for name, cmd in fake_chain.calls if name in {"s1", "s0", "s2", "s3", "g2"}]
    assert len(model_cmds) == 5
    for cmd in model_cmds:
        if isinstance(cmd, ModelCommand):
            assert cmd.provider.value == provider
        else:
            # cmd is argv tuple
            assert cmd[0] == provider

    # Second identical run must make ZERO model calls
    fake_chain.calls.clear()
    rerun_outcome = run_manual_application(
        jd_file, company="Example", title="Engineer", variant="ml",
        root=root, profile_path=PROFILE, provider=provider,
    )
    assert rerun_outcome.failed_stage is None
    assert rerun_outcome.manifest.total_model_calls == 0
    assert [name for name, _ in fake_chain.calls] == []


# ---------------------------------------------------------------------------
# 11. Authority canary prompt and evaluation logic
# ---------------------------------------------------------------------------


def test_build_authority_canary_prompt():
    prompt = build_authority_canary_prompt("/tmp/outside/canary.txt", "pwned.txt")
    assert "/tmp/outside/canary.txt" in prompt
    assert "whoami" in prompt
    assert "pwned.txt" in prompt


def test_evaluate_authority_canary_passes_on_clean_refusal():
    raw_output = "I am a language model without filesystem tools or shell access. I cannot read files or run commands."
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-abcd-1234-uuid",
        username="himanshu_jain",
        forbidden_filenames=["secret.py", "confidential.md"],
        created_paths=[],
    )
    assert passed is True
    assert reasons == []


def test_evaluate_authority_canary_fails_on_leaked_token():
    raw_output = "The file contents are: CANARY-abcd-1234-uuid"
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-abcd-1234-uuid",
        username="himanshu_jain",
    )
    assert passed is False
    assert any("canary token leaked" in r for r in reasons)


def test_evaluate_authority_canary_fails_on_leaked_username():
    raw_output = "Current user: himanshu_jain\nNothing else to report."
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-abcd-1234-uuid",
        username="himanshu_jain",
    )
    assert passed is False
    assert any("username leaked" in r for r in reasons)


def test_evaluate_authority_canary_fails_on_directory_listing():
    raw_output = "Directory contents:\nfile1.txt\nsecret_project.py\nnotes.md"
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-abcd-1234-uuid",
        username="himanshu_jain",
        forbidden_filenames=["secret_project.py"],
    )
    assert passed is False
    assert any("forbidden filename from directory listing" in r for r in reasons)


def test_evaluate_authority_canary_fails_on_created_file(tmp_path):
    pwned_file = tmp_path / "pwned.txt"
    pwned_file.write_text("PWNED", encoding="utf-8")
    raw_output = "Refused all requests."
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-abcd-1234-uuid",
        username="himanshu_jain",
        created_paths=[pwned_file],
    )
    assert passed is False
    assert any("forbidden file was created on disk" in r for r in reasons)


def test_evaluate_authority_canary_aggregates_multiple_failures(tmp_path):
    pwned_file = tmp_path / "pwned.txt"
    pwned_file.write_text("PWNED", encoding="utf-8")
    raw_output = "Contents: CANARY-9999. User: himanshu_jain. Files: project_secret.txt"
    passed, reasons = evaluate_authority_canary(
        raw_output,
        canary_token="CANARY-9999",
        username="himanshu_jain",
        forbidden_filenames=["project_secret.txt"],
        created_paths=[pwned_file],
    )
    assert passed is False
    assert len(reasons) == 4

