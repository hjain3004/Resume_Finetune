"""Apply-Now lane composer (M8N-0). No model, no network, no DB. Stage
runners are faked at the src.tailor.pilot seam exactly as the pilot tests
do; the lane's own logic (JD normalization, job id, manifest, preflight
gate, model command, rejected output) is what is under test."""
import json
from pathlib import Path

import pytest

from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    JD_MAX_CHARS,
    JD_MIN_CHARS,
    LANE_MANIFEST_SCHEMA,
    LaneError,
    build_claude_cmd,
    check_gemini_credentials,
    check_openai_credentials,
    lane_directory,
    lane_job_id,
    lane_manifest_to_dict,
    normalize_jd,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import Stage, StageState
from src.tailor.preflight import PreflightFinding, PreflightReport
from src.tailor.publish import RenderOutcome, RenderOutcomeKind
from tests.tailor.test_pilot import PILOT_JOB_ID, _build_valid_chain

PROFILE = Path("config/master_profile.yaml")
JD_TEXT = "Python " * 60  # 420 chars, above JD_MIN_CHARS


@pytest.fixture
def jd_file(tmp_path):
    path = tmp_path / "jd.txt"
    path.write_text(JD_TEXT, encoding="utf-8")
    from src.tailor.provenance import JD_PROVENANCE_SCHEMA, compute_jd_sha256
    sidecar = tmp_path / "jd.txt.provenance.json"
    sidecar.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.example.com/123",
        "source_type": "ats",
        "jd_quality": "ats",
        "jd_sha256": compute_jd_sha256(path.read_bytes()),
        "job_id": None,
        "ats_url": "https://jobs.example.com/123",
        "attestation": None,
    }), encoding="utf-8")
    return path


@pytest.fixture
def passing_preflight(monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight",
                        lambda *a, **k: PreflightReport(findings=(), passed=True))
    monkeypatch.setattr("src.tailor.lane.check_gemini_credentials", lambda *a, **k: None)
    monkeypatch.setattr("src.tailor.lane.check_openai_credentials", lambda *a, **k: None)


@pytest.fixture
def pinned_job_id(monkeypatch):
    """The fake chain below carries job_id 225; pin the lane's id to it so
    completeness checks bind."""
    monkeypatch.setattr("src.tailor.lane.lane_job_id", lambda jd_text: PILOT_JOB_ID)


class _Spy:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []


@pytest.fixture
def fake_chain(monkeypatch):
    from src.tailor.g2_pipeline import G2Outcome, G2OutcomeKind
    from src.tailor.g3 import G3Outcome, G3OutcomeKind, packet_to_dict
    from src.tailor.publish import render_result_to_dict
    from src.tailor.s0_pipeline import S0Outcome, S0OutcomeKind
    from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind
    from src.tailor.s2_pipeline import S2Outcome, S2OutcomeKind
    from src.tailor.s3_pipeline import S3Outcome, S3OutcomeKind

    chain = _build_valid_chain()
    spy = _Spy()

    def fake_s1(request, **kwargs):
        spy.calls.append(("s1", kwargs.get("claude_cmd")))
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        spy.calls.append(("s0", kwargs.get("claude_cmd")))
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        spy.calls.append(("s2", kwargs.get("claude_cmd")))
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        spy.calls.append(("s3", kwargs.get("claude_cmd")))
        return S3Outcome(kind=S3OutcomeKind.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        spy.calls.append(("g2", kwargs.get("claude_cmd")))
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


# --- pure helpers -----------------------------------------------------------

def test_normalize_jd_strips_bom_and_crlf_only():
    raw = "﻿Line one\r\nLine two  \r\n" + "x" * JD_MIN_CHARS
    out = normalize_jd(raw)
    assert out.startswith("Line one\nLine two  \n")
    assert "\r" not in out and "﻿" not in out


def test_normalize_jd_rejects_short_and_long():
    with pytest.raises(LaneError, match="at least"):
        normalize_jd("x" * (JD_MIN_CHARS - 1))
    with pytest.raises(LaneError, match="at most"):
        normalize_jd("x" * (JD_MAX_CHARS + 1))


def test_lane_job_id_is_negative_deterministic_and_content_bound():
    a = lane_job_id("hello world " * 30)
    assert a < 0 and a == lane_job_id("hello world " * 30)
    assert a != lane_job_id("hello world " * 30 + "!")


def test_build_claude_cmd_default_and_model():
    assert build_claude_cmd(None) == DEFAULT_CLAUDE_CMD
    assert build_claude_cmd("sonnet") == ("claude", "-p", "--model", "sonnet", "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--")


def test_build_claude_cmd_rejects_flag_like_model():
    with pytest.raises(LaneError):
        build_claude_cmd("--dangerously-skip-permissions")


def test_lane_directory_with_and_without_suffix(tmp_path):
    assert lane_directory(tmp_path, "Twitch", "Software Engineer", None).name == "twitch-software_engineer"
    assert lane_directory(tmp_path, "Twitch", "Software Engineer", "Req 2").name == "twitch-software_engineer-req_2"


def test_lane_manifest_round_trips_strictly():
    raw = {
        "schema_version": LANE_MANIFEST_SCHEMA, "job_id": -5, "jd_sha256": "a" * 64, "jd_path": "inbox/jd/x.txt",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": None,
        "claude_cmd": list(DEFAULT_CLAUDE_CMD), "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00",
        "provider": "claude",
    }
    manifest = parse_lane_manifest(raw)
    assert lane_manifest_to_dict(manifest) == raw
    with pytest.raises(LaneError):
        parse_lane_manifest({**raw, "extra": 1})
    with pytest.raises(LaneError):
        parse_lane_manifest({k: v for k, v in raw.items() if k != "variant"})


def test_old_manifest_without_provider_defaults_to_claude():
    old_raw = {
        "schema_version": LANE_MANIFEST_SCHEMA, "job_id": -5, "jd_sha256": "a" * 64, "jd_path": "inbox/jd/x.txt",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": None,
        "claude_cmd": list(DEFAULT_CLAUDE_CMD), "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00",
    }
    manifest = parse_lane_manifest(old_raw)
    assert manifest.provider == "claude"


def test_check_gemini_credentials():
    # Missing key fails
    err = check_gemini_credentials(env={})
    assert err is not None
    assert "GEMINI_API_KEY" in err
    # Present key passes
    assert check_gemini_credentials(env={"GEMINI_API_KEY": "AIzaSy..."}) is None


def test_check_openai_credentials():
    # Missing key fails
    err = check_openai_credentials(env={})
    assert err is not None
    assert "OPENAI_API_KEY" in err
    # Present key passes
    assert check_openai_credentials(env={"OPENAI_API_KEY": "sk-proj-..."}) is None


def test_gemini_preflight_credential_check_fails_run_before_model_call(tmp_path, jd_file, monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    monkeypatch.setattr(
        "src.tailor.lane.check_gemini_credentials",
        lambda *a, **k: "GEMINI_API_KEY environment variable is not set.",
    )
    outcome = run_manual_application(
        jd_file, company="Example", title="Engineer", variant="backend",
        provider="gemini", root=tmp_path / "apps", profile_path=PROFILE,
    )
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "preflight_failure"
    assert "GEMINI_API_KEY" in outcome.manifest.stages[0].error


def test_openai_preflight_credential_check_fails_run_before_model_call(tmp_path, jd_file, monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    monkeypatch.setattr(
        "src.tailor.lane.check_openai_credentials",
        lambda *a, **k: "OPENAI_API_KEY environment variable is not set.",
    )
    outcome = run_manual_application(
        jd_file, company="Example", title="Engineer", variant="backend",
        provider="openai", root=tmp_path / "apps", profile_path=PROFILE,
    )
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "preflight_failure"
    assert "OPENAI_API_KEY" in outcome.manifest.stages[0].error


# --- composer ---------------------------------------------------------------

def test_unknown_variant_is_refused_before_any_write(tmp_path, jd_file, passing_preflight):
    with pytest.raises(LaneError, match="variant"):
        run_manual_application(jd_file, company="Example", title="Engineer", variant="nope",
                               root=tmp_path / "apps", profile_path=PROFILE)
    assert not (tmp_path / "apps").exists()


def test_preflight_failure_stops_before_any_model_call(tmp_path, jd_file, fake_chain, monkeypatch):
    monkeypatch.setattr("src.tailor.lane.run_preflight", lambda *a, **k: PreflightReport(
        findings=(PreflightFinding("prompt_invariants", "tailoring_s1.md", "bad"),), passed=False))
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "preflight_failure"
    assert "tailoring_s1.md" in outcome.manifest.stages[0].error
    assert fake_chain.calls == []
    assert not (tmp_path / "apps").exists()


def test_full_run_writes_jd_snapshot_manifest_and_reaches_g3(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE, model="sonnet")
    assert outcome.failed_stage is None
    directory = tmp_path / "apps" / "example-engineer"
    assert (directory / "jd.txt").read_text(encoding="utf-8") == normalize_jd(JD_TEXT)
    manifest = parse_lane_manifest(json.loads((directory / "lane_manifest.json").read_text(encoding="utf-8")))
    assert manifest.model == "sonnet" and manifest.claude_cmd == build_claude_cmd("sonnet")
    assert manifest.jd_quality == "ats" and manifest.variant == "ml"
    assert (directory / "s1_request.json").exists() and (directory / "packet.json").exists()
    assert (directory / "run_manifest.json").exists()
    assert outcome.manifest.db_mutations == 0 and outcome.manifest.submissions == 0
    model_calls = [cmd for name, cmd in fake_chain.calls if name in {"s1", "s0", "s2", "s3", "g2"}]
    assert model_calls and all(cmd == build_claude_cmd("sonnet") for cmd in model_calls)
    render_args = next(args for name, args in fake_chain.calls if name == "render")
    assert render_args == (directory, directory / "rejected")


def test_second_identical_run_makes_zero_model_calls(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    fake_chain.calls.clear()
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is None
    assert outcome.manifest.total_model_calls == 0
    assert [name for name, _ in fake_chain.calls] == []


def test_mismatched_jd_for_same_directory_is_refused(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    other = tmp_path / "jd2.txt"
    other.write_text(JD_TEXT + " Go", encoding="utf-8")
    from src.tailor.provenance import JD_PROVENANCE_SCHEMA, compute_jd_sha256
    (tmp_path / "jd2.txt.provenance.json").write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.example.com/123",
        "source_type": "ats",
        "jd_quality": "ats",
        "jd_sha256": compute_jd_sha256(other.read_bytes()),
        "job_id": None,
        "ats_url": "https://jobs.example.com/123",
        "attestation": None,
    }), encoding="utf-8")
    fake_chain.calls.clear()
    outcome = run_manual_application(other, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "lane_manifest_mismatch"
    assert "--suffix" in outcome.manifest.stages[0].error
    assert fake_chain.calls == []


def test_mismatched_variant_for_same_directory_is_refused(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE)
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="backend",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.PREPARE
    assert outcome.manifest.stages[0].outcome_kind == "lane_manifest_mismatch"


def test_suffix_separates_two_postings(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id):
    run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                           root=tmp_path / "apps", profile_path=PROFILE, suffix="req-a")
    assert (tmp_path / "apps" / "example-engineer-req_a" / "lane_manifest.json").exists()


def test_dry_run_writes_nothing_and_calls_nothing(tmp_path, jd_file, fake_chain, passing_preflight):
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE, dry_run=True)
    assert outcome.failed_stage is None
    assert fake_chain.calls == []
    assert not (tmp_path / "apps").exists()


def test_l7_failure_surfaces_rejected_path_in_error(tmp_path, jd_file, fake_chain, passing_preflight, pinned_job_id, monkeypatch):
    def failing_render(profile, draft, *, root, directory=None, reject_dir=None, **kwargs):
        Path(reject_dir).mkdir(parents=True, exist_ok=True)
        (Path(reject_dir) / "l7_report.json").write_text('["L7 bullet: x did not survive"]', encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.L7_FAILURE, result=None,
                             violations=("L7 bullet: x did not survive",), error=None)

    monkeypatch.setattr("src.tailor.pilot.render_and_publish", failing_render)
    outcome = run_manual_application(jd_file, company="Example", title="Engineer", variant="ml",
                                     root=tmp_path / "apps", profile_path=PROFILE)
    assert outcome.failed_stage is Stage.RENDER
    assert (tmp_path / "apps" / "example-engineer" / "rejected" / "l7_report.json").exists()
    assert outcome.retry_command.startswith("python -m scripts.tailor_now run --jd ")
    assert outcome.retry_command.endswith("--only render")


def test_real_preflight_passes_on_the_repo(tmp_path):
    """The lane's PREPARE gate against the real prompts and profile, no render."""
    from src.tailor.lane import _preflight_findings
    assert _preflight_findings(PROFILE, Path("profile/template.tex"), Path("docs/prompts")) == ()
