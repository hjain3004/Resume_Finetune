"""Pilot operator (M8P-7 Task 1): stage table, run manifest, and
skip/conflict logic. No model, no network, no DB, no filesystem I/O beyond
what the test itself sets up under tmp_path."""
import pytest

from src.tailor.pilot import (
    MANIFEST_SCHEMA,
    STAGE_ORDER,
    Stage,
    StageState,
    artifact_path,
    manifest_to_dict,
    manifest_from_dict,
    rebuild_manifest,
    stage_is_complete,
)
from tests.fixtures.tailor.m8p7_chain import write_chain

def test_stage_order_matches_the_documented_chain():
    assert [s.value for s in STAGE_ORDER] == [
        "prepare", "s1", "s0", "s2", "s3", "g2", "render", "g3"]

def test_complete_stage_with_matching_identity_is_detected(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")

def test_stage_with_mismatched_fingerprint_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp2")

def test_stage_with_mismatched_job_id_is_not_complete(tmp_path):
    write_chain(tmp_path, job_id=225, fingerprint="fp1", through="s3")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=999, alignment_fingerprint="fp1")

def test_absent_artifact_is_not_complete(tmp_path):
    write_chain(tmp_path, through="s1")
    assert not stage_is_complete(tmp_path, Stage.S3, job_id=225, alignment_fingerprint="fp1")

def test_manifest_is_rebuilt_from_artifacts_not_from_a_stale_manifest(tmp_path):
    write_chain(tmp_path, through="s2")
    (tmp_path / "run_manifest.json").write_text('{"schema_version": "lies"}', encoding="utf-8")
    manifest = rebuild_manifest(tmp_path, job_id=225, company="Notion", title="SWE")
    assert manifest.schema_version == MANIFEST_SCHEMA
    by_stage = {r.stage: r.state for r in manifest.stages}
    assert by_stage[Stage.S2] is StageState.SKIPPED_COMPLETE
    assert by_stage[Stage.S3] is StageState.PENDING

def test_manifest_always_asserts_zero_mutations_and_submissions(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s1"), job_id=225,
                                company="Notion", title="SWE")
    assert manifest.db_mutations == 0 and manifest.submissions == 0

def test_manifest_round_trips_strictly(tmp_path):
    manifest = rebuild_manifest(write_chain(tmp_path, through="s3"), job_id=225,
                                company="Notion", title="SWE")
    assert manifest_from_dict(manifest_to_dict(manifest)) == manifest

def test_artifact_path_is_deterministic(tmp_path):
    assert artifact_path(tmp_path, Stage.S3).name == "s3_bundle.json"

# ---------------------------------------------------------------------------
# Task 2: chain driver with cost accounting and fail-closed diagnostics
# ---------------------------------------------------------------------------

import json
import sqlite3

from pathlib import Path
from types import SimpleNamespace

from src import db as db_module
from src.models import Status
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import run_static_g1
from src.tailor.g2 import G2Dimension, G2Response, G2Verdict
from src.tailor.g2_pipeline import G2Bundle, G2Outcome, G2OutcomeKind, G2Round
from src.tailor.g3 import G3Outcome, G3OutcomeKind
from src.tailor.publish import RenderOutcome, RenderOutcomeKind, RenderResult

from src.tailor.s0_pipeline import S0Outcome, S0OutcomeKind
from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind
from src.tailor.s2 import build_s2_request, parse_s2_response
from src.tailor.s2_pipeline import S2Outcome, S2OutcomeKind
from src.tailor.s3 import (
    build_s3_request,
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
    parse_s3_response,
)
from src.tailor.s3_pipeline import S3Bundle, S3Outcome, S3OutcomeKind as S3OK
from src.tailor.pilot import run_application
from tests.tailor.test_m8p2_contracts import _fixtures

PILOT_JOB_ID = 225

def _build_valid_chain():
    """A genuinely consistent, real-profile chain (S1/S0/S2/S3Bundle/
    G2Bundle/RenderResult), all bound to the same alignment_fingerprint,
    with the profile's real, UNSTRIPPED do_not_claim intact -- run_application
    itself computes the alignment fingerprint from the real profile with no
    stripping, so a canned bundle built against a stripped alignment would
    never match. The "ml" base variant is used instead of "backend" because
    the real profile's "backend" variant canonical ct_b1 bullet mentions
    "Kubernetes" while "Kubernetes" is the sole do_not_claim entry -- a
    pre-existing, out-of-scope profile condition (same workaround used in
    earlier M8P milestones' adversarial tests); "ml"'s canonical bullets
    never reference it."""
    profile, _backend_catalog, s1, s0 = _fixtures()
    catalog = profile.for_selection("ml")
    s2_request = build_s2_request(PILOT_JOB_ID, "Example", "Engineer", s1, s0, catalog)
    variant = next(item for item in s2_request.catalog.variants if item.name == "ml")
    raw_s2 = {
        "base_variant": "ml",
        "projects": [{"project_id": p, "reason": "selected", "s0_point_indexes": [0]} for p in variant.projects],
        "bullet_order": list(variant.bullet_order),
        "coverage": [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}],
    }
    s2 = parse_s2_response(json.dumps(raw_s2), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2)
    s3_request = build_s3_request(PILOT_JOB_ID, "Example", "Engineer", s1, s0, s2, alignment)
    response = parse_s3_response(json.dumps({"bullet_edits": [], "skill_additions": []}), s3_request)
    draft = hydrate_s3(s3_request, response)
    report = run_static_g1(s3_request, response, draft, ())
    assert report.status.value == "static_pass", report.violations
    s3_bundle = S3Bundle(
        "m8p3.s3_bundle.v1", PILOT_JOB_ID, "Example", "Engineer", alignment.fingerprint,
        response, draft, derive_change_log(s3_request, response, draft),
        derive_unified_diff(s3_request, draft), calculate_edit_budget(s3_request, draft), report,
    )
    g2_response = G2Response(
        scores=((G2Dimension.C1, 3), (G2Dimension.C2, 3), (G2Dimension.C3, 3),
               (G2Dimension.C4, 3), (G2Dimension.C5, 3)),
        findings=(),
    )
    g2_round = G2Round(round_index=1, response=g2_response, verdict=G2Verdict.PASS, trace_path=None)
    g2_bundle = G2Bundle(
        "m8p4.g2_bundle.v1", PILOT_JOB_ID, "Example", "Engineer", alignment.fingerprint,
        s3_bundle, (g2_round,), G2Verdict.PASS, (), 1, 1,
    )
    render_result = RenderResult(
        "m8p5.render_result.v1", PILOT_JOB_ID, "Example", "Engineer", alignment.fingerprint,
        s3_bundle.schema_version, "applications/example-engineer/resume.tex",
        "applications/example-engineer/Himanshu_Jain_Resume.pdf", "0" * 64, 1, 12345,
        (), (), (), "pass",
    )
    return SimpleNamespace(
        profile=profile, s2_request=s2_request, s3_request=s3_request, alignment=alignment,
        s1=s1, s0=s0, s2=s2, s3_bundle=s3_bundle, g2_bundle=g2_bundle, render_result=render_result,
    )

def _seed_db(db_path, *, job_id=PILOT_JOB_ID, status=Status.SHORTLISTED,
            company="Example", title="Engineer", jd_text="Python", base_variant="backend"):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db_module.init_db(conn)
    conn.execute(
        """INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                             status, jd_text, jd_quality, base_variant)
           VALUES (?, ?, ?, ?, 'Remote', 'https://example.test/job', 'inbox',
                   '2026-08-01T00:00:00+00:00', ?, ?, 'ats', ?)""",
        (job_id, f"key-{job_id}", company, title, status, jd_text, base_variant),
    )
    conn.commit()
    conn.close()

@pytest.fixture
def tmp_repo(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=PILOT_JOB_ID, base_variant="ml")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                             status, jd_text, jd_quality, base_variant)
           VALUES (279, 'key-279', 'Blocked', 'SWE', 'Remote', 'https://example.test/job2', 'inbox',
                   '2026-08-01T00:00:00+00:00', 'SHORTLISTED', 'text', 'ats', 'backend')"""
    )
    conn.commit()
    conn.close()
    return SimpleNamespace(
        root=tmp_path, db=db_path, profile=Path("config/master_profile.yaml"),
        applications=tmp_path / "applications", feedback=tmp_path / "feedback",
    )

@pytest.fixture
def db_checksum(tmp_repo):
    import hashlib

    def _checksum():
        return hashlib.sha256(tmp_repo.db.read_bytes()).hexdigest()
    return _checksum

class _SpyInvocations:
    def __init__(self):
        self.calls: list[str] = []

    def reset(self):
        self.calls = []

    @property
    def call_count(self):
        return len(self.calls)

    def calls_for(self, name):
        return self.calls.count(name)

    def record(self, name):
        self.calls.append(name)

@pytest.fixture
def spy_invocations():
    return _SpyInvocations()

@pytest.fixture
def mock_all_stages_pass(monkeypatch, spy_invocations):
    chain = _build_valid_chain()

    def fake_s1(request, **kwargs):
        spy_invocations.record("s1")
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        spy_invocations.record("s0")
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        spy_invocations.record("s2")
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        spy_invocations.record("s3")
        return S3Outcome(kind=S3OK.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        spy_invocations.record("g2")
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    def fake_render(profile, draft, *, root, **kwargs):
        spy_invocations.record("render")
        from src.tailor.publish import application_dir, render_result_to_dict
        directory = application_dir(root, chain.render_result.company, chain.render_result.title)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render_result.json").write_text(
            json.dumps(render_result_to_dict(chain.render_result)), encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.VALID, result=chain.render_result, violations=(), error=None)

    def fake_g3(packet, changed_bullet_ids, directory):
        spy_invocations.record("g3")
        from src.tailor.g3 import packet_to_dict
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
    return chain

def test_dry_run_makes_no_model_call_and_writes_no_artifact(tmp_repo, spy_invocations):
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications, dry_run=True)
    assert spy_invocations.call_count == 0
    assert outcome.manifest.total_model_calls == 0
    assert not list(tmp_repo.applications.rglob("s1_response.json"))

def test_full_run_reports_five_to_seven_model_calls(tmp_repo, mock_all_stages_pass):
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications)
    assert 5 <= outcome.manifest.total_model_calls <= 7
    assert all(r.state in (StageState.COMPLETE, StageState.SKIPPED_COMPLETE)
              for r in outcome.manifest.stages)

def test_rerun_of_a_complete_application_costs_zero_calls(tmp_repo, mock_all_stages_pass, spy_invocations):
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    spy_invocations.reset()
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications)
    assert spy_invocations.call_count == 0
    assert outcome.manifest.total_model_calls == 0

def test_rerun_produces_byte_identical_artifacts(tmp_repo, mock_all_stages_pass):
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    before = {p: p.read_bytes() for p in tmp_repo.applications.rglob("*.json") if p.name != "run_manifest.json"}
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    after = {p: p.read_bytes() for p in tmp_repo.applications.rglob("*.json") if p.name != "run_manifest.json"}
    assert after == before

def test_tampered_upstream_artifact_produces_conflict_and_changes_nothing(tmp_repo, mock_all_stages_pass):
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    bundle = next(tmp_repo.applications.rglob("s3_bundle.json"))
    raw = json.loads(bundle.read_text())
    raw["alignment_fingerprint"] = "0" * 64
    bundle.write_text(json.dumps(raw), encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_repo.applications.rglob("*.json") if p != bundle and p.name != "run_manifest.json"}
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications)
    assert outcome.failed_stage is Stage.S3
    after = {p: p.read_bytes() for p in tmp_repo.applications.rglob("*.json") if p != bundle and p.name != "run_manifest.json"}
    assert after == before

@pytest.fixture
def mock_g2_fails_then_passes(monkeypatch, spy_invocations):
    chain = _build_valid_chain()
    calls = {"g2": 0}

    def fake_s1(request, **kwargs):
        spy_invocations.record("s1")
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        spy_invocations.record("s0")
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        spy_invocations.record("s2")
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        spy_invocations.record("s3")
        return S3Outcome(kind=S3OK.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        spy_invocations.record("g2")
        calls["g2"] += 1
        if calls["g2"] == 1:
            return G2Outcome(kind=G2OutcomeKind.INVOCATION_FAILURE, bundle=None, error="boom", trace_paths=())
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    def fake_render(profile, draft, *, root, **kwargs):
        spy_invocations.record("render")
        from src.tailor.publish import application_dir, render_result_to_dict
        directory = application_dir(root, chain.render_result.company, chain.render_result.title)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render_result.json").write_text(
            json.dumps(render_result_to_dict(chain.render_result)), encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.VALID, result=chain.render_result, violations=(), error=None)

    def fake_g3(packet, changed_bullet_ids, directory):
        spy_invocations.record("g3")
        from src.tailor.g3 import packet_to_dict
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
    return chain

def test_mid_chain_failure_resumes_at_the_failed_stage(tmp_repo, mock_g2_fails_then_passes, spy_invocations):
    first = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                            root=tmp_repo.applications)
    assert first.failed_stage is Stage.G2
    spy_invocations.reset()
    second = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                             root=tmp_repo.applications)
    assert second.failed_stage is None
    assert spy_invocations.call_count <= 3      # only G2 (and downstream) re-ran

def test_failure_reports_a_retry_command_and_a_trace_path(tmp_repo, monkeypatch):
    def fake_s1_fail(request, **kwargs):
        return S1Outcome(kind=S1OutcomeKind.INVOCATION_FAILURE, response=None, error="boom",
                         trace_path=Path("data/traces/fake.json"))
    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1_fail)
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications)
    assert outcome.retry_command and "--only s1" in outcome.retry_command
    record = next(r for r in outcome.manifest.stages if r.stage is Stage.S1)
    assert record.trace_paths

def test_no_automatic_retry_on_failure(tmp_repo, monkeypatch, spy_invocations):
    def fake_s1_fail(request, **kwargs):
        spy_invocations.record("s1")
        return S1Outcome(kind=S1OutcomeKind.INVOCATION_FAILURE, response=None, error="boom", trace_path=None)
    monkeypatch.setattr("src.tailor.pilot.run_s1_invocation", fake_s1_fail)
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    assert spy_invocations.calls_for("s1") == 1

def test_prohibited_job_is_refused(tmp_repo, mock_all_stages_pass):
    outcome = run_application(279, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    assert outcome.failed_stage is Stage.PREPARE
    assert "no such row" in (outcome.manifest.stages[0].error or "") or \
           "prohibited" in (outcome.manifest.stages[0].error or "")

def test_rerun_after_feedback_is_refused_by_default(tmp_repo, mock_all_stages_pass):
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications,
                   feedback_dir=tmp_repo.feedback)
    tmp_repo.feedback.mkdir(parents=True, exist_ok=True)
    (tmp_repo.feedback / "index.jsonl").write_text(
        json.dumps({"job_id": PILOT_JOB_ID, "alignment_fingerprint": "fp", "revision": 1}) + "\n",
        encoding="utf-8",
    )
    outcome = run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile,
                              root=tmp_repo.applications, feedback_dir=tmp_repo.feedback)
    assert outcome.failed_stage is Stage.PREPARE
    assert "feedback" in (outcome.manifest.stages[0].error or "")

def test_rerun_after_feedback_with_flag_writes_to_a_rerun_subdirectory(tmp_repo, mock_all_stages_pass):
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications,
                   feedback_dir=tmp_repo.feedback)
    tmp_repo.feedback.mkdir(parents=True, exist_ok=True)
    (tmp_repo.feedback / "index.jsonl").write_text(
        json.dumps({"job_id": PILOT_JOB_ID, "alignment_fingerprint": "fp", "revision": 1}) + "\n",
        encoding="utf-8",
    )
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications,
                   feedback_dir=tmp_repo.feedback, allow_rerun_after_feedback=True)
    assert list(tmp_repo.applications.rglob("rerun-1/s3_bundle.json"))

def test_operator_defines_no_parsing_or_validation_of_its_own():
    source = Path("src/tailor/pilot.py").read_text(encoding="utf-8")
    for forbidden in ("def parse_", "def validate_", "def hydrate_", "def build_prompt"):
        assert forbidden not in source

def test_operator_cannot_submit_an_application():
    source = Path("src/tailor/pilot.py").read_text(encoding="utf-8")
    for forbidden in ("requests", "urllib", "smtplib", "webbrowser",
                      "playwright", "crawl4ai", "firecrawl"):
        assert forbidden not in source

def test_no_sqlite_write_occurs(tmp_repo, mock_all_stages_pass, db_checksum):
    before = db_checksum()
    run_application(PILOT_JOB_ID, db_path=tmp_repo.db, profile_path=tmp_repo.profile, root=tmp_repo.applications)
    assert db_checksum() == before


# ---------------------------------------------------------------------------
# Task 3: read-only pilot-job selection
# ---------------------------------------------------------------------------

from src.tailor.pilot import PilotCandidate, eligible_candidates, select_pilot_jobs


@pytest.fixture
def seeded_conn(tmp_path):
    db_path = tmp_path / "select.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db_module.init_db(conn)
    rows = [
        # id, company, title, status, jd_text, jd_quality, base_variant
        (119, "Cisco", "Software Engineer Data/AI/Intelligent Systems", Status.SHORTLISTED,
         "x" * 13445 + " kubernetes docker", "ats", "ml"),
        (213, "Citadel Securities", "Graduate Software Engineer", Status.SHORTLISTED,
         "y" * 2352, "ats", "backend"),
        (225, "Notion", "Software Engineer", Status.SHORTLISTED, "z" * 7493, "ats", "backend"),
        (229, "Blocked", "SWE", Status.SHORTLISTED, "a" * 1000, "ats", "backend"),
        (279, "Blocked2", "SWE", Status.SHORTLISTED, "b" * 1000, "ats", "ml"),
        (900, "NotATS", "SWE", Status.SHORTLISTED, "c" * 1000, "resume", "backend"),
        (901, "NotShortlisted", "SWE", Status.SCORED, "d" * 1000, "ats", "backend"),
    ]
    for job_id, company, title, status, jd_text, jd_quality, base_variant in rows:
        conn.execute(
            """INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                                 status, jd_text, jd_quality, base_variant)
               VALUES (?, ?, ?, ?, 'Remote', ?, 'inbox', '2026-08-01T00:00:00+00:00', ?, ?, ?, ?)""",
            (job_id, f"key-{job_id}", company, title, f"https://example.test/{job_id}",
             status, jd_text, jd_quality, base_variant),
        )
    conn.commit()
    return conn


@pytest.fixture
def db_checksum_for_conn(seeded_conn, tmp_path):
    import hashlib
    path = tmp_path / "select.db"

    def _checksum():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return _checksum


def _candidate(job_id, *, base_variant="backend", jd_length=5000, content_group="g1"):
    return PilotCandidate(job_id=job_id, company="C", title="T", base_variant=base_variant,
                          jd_length=jd_length, content_group=content_group, reasons=())


@pytest.fixture
def candidates_with_duplicates():
    return (
        _candidate(1, content_group="dup"), _candidate(2, content_group="dup"),
        _candidate(3, content_group="dup"), _candidate(4, base_variant="ml", jd_length=13000, content_group="g2"),
        _candidate(5, jd_length=2000, content_group="g3"), _candidate(6, jd_length=7000, content_group="g4"),
    )


@pytest.fixture
def candidates_mixed():
    return (
        _candidate(119, base_variant="ml", jd_length=13445, content_group="cisco"),
        _candidate(213, base_variant="backend", jd_length=2352, content_group="citadelsec"),
        _candidate(225, base_variant="backend", jd_length=7493, content_group="notion"),
        _candidate(233, base_variant="backend", jd_length=2822, content_group="atos"),
        _candidate(266, base_variant="backend", jd_length=6058, content_group="newsbreak"),
        _candidate(283, base_variant="backend", jd_length=6210, content_group="bytedance"),
    )


@pytest.fixture
def candidates_all_backend():
    return (
        _candidate(1, base_variant="backend", jd_length=2000, content_group="g1"),
        _candidate(2, base_variant="backend", jd_length=6000, content_group="g2"),
        _candidate(3, base_variant="backend", jd_length=13000, content_group="g3"),
    )


def test_eligible_candidates_excludes_prohibited_and_non_ats(seeded_conn):
    ids = {c.job_id for c in eligible_candidates(seeded_conn)}
    assert 279 not in ids and 229 not in ids
    assert 900 not in ids and 901 not in ids
    assert {119, 213, 225} <= ids
    assert all(c.jd_length > 0 for c in eligible_candidates(seeded_conn))


def test_selection_never_returns_two_rows_from_one_content_group(candidates_with_duplicates):
    picked = select_pilot_jobs(candidates_with_duplicates, count=3)
    assert len({c.content_group for c in picked}) == 3


def test_selection_covers_both_base_variants(candidates_mixed):
    picked = select_pilot_jobs(candidates_mixed, count=3)
    assert {c.base_variant for c in picked} >= {"backend", "ml"}


def test_selection_spreads_jd_length(candidates_mixed):
    lengths = sorted(c.jd_length for c in select_pilot_jobs(candidates_mixed, count=3))
    assert lengths[0] < 3000 and lengths[-1] > 12000


def test_every_pick_carries_a_reason(candidates_mixed):
    assert all(c.reasons for c in select_pilot_jobs(candidates_mixed, count=3))


def test_selection_is_deterministic(candidates_mixed):
    assert select_pilot_jobs(candidates_mixed, 3) == select_pilot_jobs(candidates_mixed, 3)


def test_selection_raises_when_criteria_cannot_be_met(candidates_all_backend):
    with pytest.raises(ValueError, match="base variant"):
        select_pilot_jobs(candidates_all_backend, count=3)


def test_selection_is_read_only(seeded_conn, db_checksum_for_conn):
    before = db_checksum_for_conn()
    eligible_candidates(seeded_conn)
    assert db_checksum_for_conn() == before


# ---------------------------------------------------------------------------
# Task 4: cost accounting and the acceptance gate
# ---------------------------------------------------------------------------
from src.tailor.pilot import (  # noqa: E402
    CostReport,
    GateCondition,
    GateReport,
    StageRecord,
    RunManifest,
    acceptance_gate,
    cost_report,
)
from src.tailor.feedback import parse_feedback_form, store_feedback  # noqa: E402
from src.tailor.publish import application_dir, render_result_to_dict  # noqa: E402
from tests.fixtures.tailor.m8p6_forms import form  # noqa: E402


def _cost_stage_record(stage, model_calls, complete=True):
    return StageRecord(
        stage=stage, state=StageState.COMPLETE if complete else StageState.PENDING,
        outcome_kind="complete" if complete else "pending",
        artifact_path=None, model_calls=model_calls if complete else 0,
        trace_paths=(), started_at="t0", ended_at="t1", error=None,
    )


def _write_run(directory: Path, *, job_id, company, title, fingerprint,
                g2_rounds=1, g3_reached=True, l7_violations=()):
    directory.mkdir(parents=True, exist_ok=True)
    calls = {Stage.PREPARE: 0, Stage.S1: 1, Stage.S0: 1, Stage.S2: 1,
             Stage.S3: 1, Stage.G2: g2_rounds, Stage.RENDER: 0, Stage.G3: 0}
    stages = tuple(
        _cost_stage_record(stage, calls[stage], complete=(stage != Stage.G3 or g3_reached))
        for stage in STAGE_ORDER
    )
    manifest = RunManifest(
        schema_version=MANIFEST_SCHEMA, job_id=job_id, company=company, title=title,
        alignment_fingerprint=fingerprint, stages=stages,
        total_model_calls=sum(record.model_calls for record in stages),
        db_mutations=0, submissions=0,
    )
    (directory / "run_manifest.json").write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")

    render_result = RenderResult(
        schema_version="m8p5.render_result.v1", job_id=job_id, company=company, title=title,
        alignment_fingerprint=fingerprint, s3_bundle_schema_version="m8p3r.s3_bundle.v1",
        source_path=f"{directory}/resume.tex", pdf_path=f"{directory}/resume.pdf",
        pdf_sha256="a" * 64, page_count=1, size_bytes=1000,
        modified_bullet_ids=("b1",), modified_bullet_line_counts=(("b1", 2),),
        l7_violations=tuple(l7_violations), render_line_check="pass",
    )
    (directory / "render_result.json").write_text(json.dumps(render_result_to_dict(render_result)), encoding="utf-8")
    return manifest


_PILOT_SPECS = (
    dict(job_id=119, company="Cisco", title="Engineer", fingerprint="fp119"),
    dict(job_id=213, company="Citadel Securities", title="Engineer", fingerprint="fp213"),
    dict(job_id=225, company="Notion", title="Engineer", fingerprint="fp225"),
)


def _build_pilot_root(tmp_path, overrides=None):
    overrides = overrides or {}
    root = tmp_path / "applications"
    for index, spec in enumerate(_PILOT_SPECS):
        spec = {**spec, **overrides.get(index, {})}
        directory = application_dir(root, spec["company"], spec["title"])
        _write_run(directory, **spec)
    return root


@pytest.fixture
def three_completed_applications(tmp_path):
    return _build_pilot_root(tmp_path)


@pytest.fixture
def pilot_root(tmp_path):
    return _build_pilot_root(tmp_path)


@pytest.fixture
def pilot_root_incomplete(tmp_path):
    return _build_pilot_root(tmp_path, overrides={2: {"g3_reached": False}})


@pytest.fixture
def pilot_root_with_l7_failure(tmp_path):
    return _build_pilot_root(tmp_path, overrides={0: {"l7_violations": ("line 12 exceeds the L7 bound",)}})


_UNSUPPORTED_BULLET_TEXT = "Cut p99 latency 40% by sharding the write path"


def _write_feedback_record(feedback_dir, *, job_id, fingerprint, would_submit="yes",
                            needs_another_revision="no", company_alignment=3, visual_quality=3,
                            unsupported_claims=()):
    record = parse_feedback_form(
        form(job_id=job_id, alignment_fingerprint=fingerprint, would_submit=would_submit,
             needs_another_revision=needs_another_revision, company_alignment=company_alignment,
             visual_quality=visual_quality, unsupported_claims=list(unsupported_claims)),
        job_id=job_id, alignment_fingerprint=fingerprint,
        changed_bullet_ids=frozenset({"b1"}), bullet_plain_text_by_id={"b1": _UNSUPPORTED_BULLET_TEXT},
    )
    store_feedback(record, feedback_dir=feedback_dir)


@pytest.fixture
def good_feedback(tmp_path):
    feedback_dir = tmp_path / "feedback"
    _write_feedback_record(feedback_dir, job_id=119, fingerprint="fp119", would_submit="yes")
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213", would_submit="yes")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225", would_submit="no")
    return feedback_dir


@pytest.fixture
def feedback_with_one_unsupported_claim(tmp_path):
    feedback_dir = tmp_path / "feedback"
    _write_feedback_record(
        feedback_dir, job_id=119, fingerprint="fp119",
        unsupported_claims=[{"bullet_id": "b1", "quoted_text": "p99 latency", "why": "never measured"}],
    )
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225")
    return feedback_dir


@pytest.fixture
def feedback_one_yes(tmp_path):
    feedback_dir = tmp_path / "feedback"
    _write_feedback_record(feedback_dir, job_id=119, fingerprint="fp119", would_submit="yes")
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213", would_submit="no")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225", would_submit="not_as_is")
    return feedback_dir


@pytest.fixture
def feedback_two_revisions(tmp_path):
    feedback_dir = tmp_path / "feedback"
    _write_feedback_record(feedback_dir, job_id=119, fingerprint="fp119", needs_another_revision="yes")
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213", needs_another_revision="yes")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225", needs_another_revision="no")
    return feedback_dir


def test_cost_report_aggregates_manifests(three_completed_applications):
    report = cost_report(three_completed_applications)
    assert report.applications == 3
    assert report.total_model_calls == sum(n for _, n in report.calls_by_stage)
    assert 5.0 <= report.mean_calls_per_application <= 7.0


def test_gate_fails_on_any_unsupported_claim(pilot_root, feedback_with_one_unsupported_claim):
    report = acceptance_gate(pilot_root, feedback_with_one_unsupported_claim)
    condition = next(c for c in report.conditions if c.name == "unsupported_claims")
    assert not condition.passed and not report.passed


def test_gate_fails_when_fewer_than_two_would_submit(pilot_root, feedback_one_yes):
    assert not acceptance_gate(pilot_root, feedback_one_yes).passed


def test_gate_fails_on_any_l7_failure(pilot_root_with_l7_failure, good_feedback):
    assert not acceptance_gate(pilot_root_with_l7_failure, good_feedback).passed


def test_gate_fails_when_more_than_one_needs_revision(pilot_root, feedback_two_revisions):
    assert not acceptance_gate(pilot_root, feedback_two_revisions).passed


def test_gate_fails_when_a_run_did_not_reach_a_packet(pilot_root_incomplete, good_feedback):
    assert not acceptance_gate(pilot_root_incomplete, good_feedback).passed


def test_gate_passes_only_when_every_condition_passes(pilot_root, good_feedback):
    report = acceptance_gate(pilot_root, good_feedback)
    assert report.passed and all(c.passed for c in report.conditions)


def test_gate_reports_observed_values_for_every_condition(pilot_root, good_feedback):
    assert all(c.observed for c in acceptance_gate(pilot_root, good_feedback).conditions)


def test_gate_and_cost_are_read_only(pilot_root, good_feedback):
    before = sorted(str(p) for p in pilot_root.rglob("*"))
    acceptance_gate(pilot_root, good_feedback)
    cost_report(pilot_root)
    assert sorted(str(p) for p in pilot_root.rglob("*")) == before
