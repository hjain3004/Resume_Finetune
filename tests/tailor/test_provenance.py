"""Deterministic, network-free tests for JD provenance boundary (M8N-0 / M9D target).

Verifies:
- an aggregator JD cannot enter tailoring;
- an arbitrary text file cannot be silently labeled ATS;
- missing provenance fails before any model call;
- a mismatched JD hash fails before any model call;
- company/title mismatch fails;
- a valid database-backed ATS JD passes;
- a valid user-attested official copy passes;
- changing an attested JD invalidates its attestation;
- review-only exports remain visibly non-tailoring;
- tailoring-ready exports contain zero aggregator jobs;
- export publication is atomic and deterministic;
- no raw shortlist SQL remains outside src/db.py;
- dry-run performs no model call and no output write;
- attestation refuses aggregator URLs;
- database metadata disagreement fails.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

import pytest

from scripts.export_shortlist import ExportMode, export_shortlist
import scripts.tailor_now as cli
from src import db
from src.tailor.lane import LaneError, run_manual_application
from src.tailor.pilot import Stage
from src.tailor.preflight import PreflightReport
from src.tailor.provenance import (
    JD_PROVENANCE_SCHEMA,
    JDQuality,
    JDProvenance,
    ProvenanceError,
    compute_jd_sha256,
    create_user_attestation,
    find_provenance_sidecar,
    is_aggregator_url,
    parse_provenance_dict,
    validate_provenance_for_tailoring,
)
from tests.tailor.test_pilot import PILOT_JOB_ID, _build_valid_chain, _seed_db

PROFILE = Path("config/master_profile.yaml")
JD_TEXT = "Python " * 60  # 420 chars, above JD_MIN_CHARS


@pytest.fixture
def fake_chain(monkeypatch):
    from src.tailor.g2_pipeline import G2Outcome, G2OutcomeKind
    from src.tailor.g3 import G3Outcome, G3OutcomeKind, packet_to_dict
    from src.tailor.publish import RenderOutcome, RenderOutcomeKind, render_result_to_dict
    from src.tailor.s0_pipeline import S0Outcome, S0OutcomeKind
    from src.tailor.s1_pipeline import S1Outcome, S1OutcomeKind
    from src.tailor.s2_pipeline import S2Outcome, S2OutcomeKind
    from src.tailor.s3_pipeline import S3Outcome, S3OutcomeKind

    chain = _build_valid_chain()
    calls: list[tuple[str, tuple]] = []

    def fake_s1(request, **kwargs):
        calls.append(("s1", (request.job_id, request.jd_quality)))
        return S1Outcome(kind=S1OutcomeKind.VALID, response=chain.s1, error=None, trace_path=None)

    def fake_s0(request, **kwargs):
        calls.append(("s0", ()))
        return S0Outcome(kind=S0OutcomeKind.VALID, response=chain.s0, error=None, trace_path=None)

    def fake_s2(request, **kwargs):
        calls.append(("s2", ()))
        return S2Outcome(kind=S2OutcomeKind.VALID, response=chain.s2, error=None, trace_path=None)

    def fake_s3(request, **kwargs):
        calls.append(("s3", ()))
        return S3Outcome(kind=S3OutcomeKind.VALID, bundle=chain.s3_bundle, g1_report=chain.s3_bundle.g1, error=None, trace_path=None)

    def fake_g2(s3_request, s3_bundle, **kwargs):
        calls.append(("g2", ()))
        return G2Outcome(kind=G2OutcomeKind.PASSED_ROUND_1, bundle=chain.g2_bundle, error=None, trace_paths=())

    def fake_render(profile, draft, *, root, directory=None, reject_dir=None, **kwargs):
        calls.append(("render", ()))
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render_result.json").write_text(
            json.dumps(render_result_to_dict(chain.render_result)), encoding="utf-8")
        return RenderOutcome(kind=RenderOutcomeKind.VALID, result=chain.render_result, violations=(), error=None)

    def fake_g3(packet, changed_bullet_ids, directory):
        calls.append(("g3", ()))
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
    return calls


@pytest.fixture
def passing_preflight(monkeypatch):
    monkeypatch.setattr(
        "src.tailor.lane.run_preflight",
        lambda *a, **k: PreflightReport(findings=(), passed=True),
    )
    monkeypatch.setattr("shutil.which", lambda exe: f"/fake/bin/{exe}")
    monkeypatch.setattr("src.tailor.lane.check_gemini_credentials", lambda *a, **k: None)
    monkeypatch.setattr("src.tailor.lane.check_openai_credentials", lambda *a, **k: None)


@pytest.fixture
def pinned_job_id(monkeypatch):
    monkeypatch.setattr("src.tailor.lane.lane_job_id", lambda jd_text: PILOT_JOB_ID)


def _create_jd_file(tmp_path: Path, filename: str = "jd.txt", content: str = JD_TEXT) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


def _create_user_attested_sidecar(
    jd_path: Path,
    *,
    company: str = "Example",
    title: str = "Engineer",
    source_url: str = "https://jobs.example.com/1",
    notes: str | None = None,
    tamper_hash: str | None = None,
) -> Path:
    jd_bytes = jd_path.read_bytes()
    sha = tamper_hash or compute_jd_sha256(jd_bytes)
    sidecar_p = jd_path.parent / f"{jd_path.name}.provenance.json"
    data = {
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": company,
        "title": title,
        "source_url": source_url,
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": source_url,
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": source_url,
            "notes": notes,
        },
    }
    sidecar_p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sidecar_p


def _create_ats_sidecar(
    jd_path: Path,
    *,
    job_id: int,
    company: str = "Example",
    title: str = "Engineer",
    source_url: str = "https://jobs.lever.co/example/1",
    source_type: str = "lever",
    ats_url: str | None = None,
    tamper_hash: str | None = None,
) -> Path:
    jd_bytes = jd_path.read_bytes()
    sha = tamper_hash or compute_jd_sha256(jd_bytes)
    sidecar_p = jd_path.parent / f"{jd_path.name}.provenance.json"
    data = {
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": company,
        "title": title,
        "source_url": source_url,
        "source_type": source_type,
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": job_id,
        "ats_url": ats_url or source_url,
        "attestation": None,
    }
    sidecar_p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sidecar_p


def _create_aggregator_sidecar(
    jd_path: Path,
    *,
    company: str = "Example",
    title: str = "Engineer",
    source_url: str = "https://jobright.ai/jobs/1",
    tamper_hash: str | None = None,
) -> Path:
    jd_bytes = jd_path.read_bytes()
    sha = tamper_hash or compute_jd_sha256(jd_bytes)
    sidecar_p = jd_path.parent / f"{jd_path.name}.provenance.json"
    data = {
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": company,
        "title": title,
        "source_url": source_url,
        "source_type": "aggregator",
        "jd_quality": "aggregator",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": None,
        "attestation": None,
    }
    sidecar_p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return sidecar_p


# ---------------------------------------------------------------------------
# 1. Aggregator JD cannot enter tailoring
# ---------------------------------------------------------------------------

def test_aggregator_jd_cannot_enter_tailoring(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    _create_aggregator_sidecar(jd_p)

    with pytest.raises(LaneError, match="cannot tailor aggregator-quality JD"):
        run_manual_application(
            jd_p, company="Example", title="Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    # Zero model calls were made
    assert fake_chain == []
    # Zero application output created
    assert not (tmp_path / "apps").exists()


# ---------------------------------------------------------------------------
# 2. Arbitrary text file cannot be silently labeled ATS
# ---------------------------------------------------------------------------

def test_arbitrary_text_file_cannot_be_silently_labeled_ats(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path, "arbitrary.txt")
    # No sidecar created

    with pytest.raises(LaneError, match="missing provenance sidecar"):
        run_manual_application(
            jd_p, company="Example", title="Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    # S1Request with jd_quality="ats" was never constructed or passed to S1
    assert fake_chain == []
    assert not (tmp_path / "apps").exists()


# ---------------------------------------------------------------------------
# 3. Missing provenance fails before any model call
# ---------------------------------------------------------------------------

def test_missing_provenance_fails_before_any_model_call(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    # Ensure no sidecar exists
    assert find_provenance_sidecar(jd_p) is None

    with pytest.raises(LaneError, match="missing provenance sidecar"):
        run_manual_application(
            jd_p, company="Example", title="Engineer", variant="backend",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    assert fake_chain == []


# ---------------------------------------------------------------------------
# 4. Mismatched JD hash fails before any model call
# ---------------------------------------------------------------------------

def test_mismatched_jd_hash_fails_before_any_model_call(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    wrong_hash = "0" * 64
    _create_user_attested_sidecar(jd_p, tamper_hash=wrong_hash)

    with pytest.raises(LaneError, match="jd hash mismatch"):
        run_manual_application(
            jd_p, company="Example", title="Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    assert fake_chain == []


# ---------------------------------------------------------------------------
# 5. Company / title mismatch fails
# ---------------------------------------------------------------------------

def test_company_title_mismatch_fails(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    _create_user_attested_sidecar(jd_p, company="Acme Corp", title="Backend Engineer")

    # Mismatched company
    with pytest.raises(LaneError, match="provenance company/title mismatch"):
        run_manual_application(
            jd_p, company="Other Corp", title="Backend Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    # Mismatched title
    with pytest.raises(LaneError, match="provenance company/title mismatch"):
        run_manual_application(
            jd_p, company="Acme Corp", title="Frontend Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    assert fake_chain == []


# ---------------------------------------------------------------------------
# 6. Valid database-backed ATS JD passes
# ---------------------------------------------------------------------------

def _seed_job_with_quality(
    db_path: Path,
    *,
    job_id: int,
    company: str,
    title: str,
    jd_text: str = JD_TEXT,
    base_variant: str = "backend",
    jd_quality: str = "ats",
    status: str = "SHORTLISTED",
    url: str = "https://example.test/job",
    ats_url: str | None = None,
    resolver: str | None = None,
    source: str = "inbox",
) -> None:
    conn = db.get_connection(db_path)
    conn.execute(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                          status, jd_text, jd_quality, base_variant, ats_url, resolver)
        VALUES (?, ?, ?, ?, 'Remote', ?, ?,
                '2026-08-01T00:00:00+00:00', ?, ?, ?, ?, ?, ?)
        """,
        (job_id, f"key-{job_id}", company, title, url, source, status, jd_text, jd_quality, base_variant, ats_url, resolver),
    )
    conn.commit()
    conn.close()


def test_valid_database_backed_ats_jd_passes(tmp_path, fake_chain, passing_preflight, pinned_job_id):
    db_path = tmp_path / "jobs.db"
    _seed_job_with_quality(
        db_path,
        job_id=225,
        company="Notion",
        title="Software Engineer",
        jd_text=JD_TEXT,
        base_variant="backend",
        jd_quality="ats",
        url="https://jobs.lever.co/notion/225",
        ats_url="https://jobs.lever.co/notion/225",
        resolver="lever",
    )

    jd_p = _create_jd_file(tmp_path)
    _create_ats_sidecar(
        jd_p,
        company="Notion",
        title="Software Engineer",
        source_url="https://jobs.lever.co/notion/225",
        source_type="lever",
        job_id=225,
    )

    outcome = run_manual_application(
        jd_p, company="Notion", title="Software Engineer", variant="backend",
        root=tmp_path / "apps", profile_path=PROFILE, db_path=db_path,
    )

    assert outcome.failed_stage is None
    s1_calls = [args for name, args in fake_chain if name == "s1"]
    assert len(s1_calls) == 1
    assert s1_calls[0] == (PILOT_JOB_ID, "ats")

    app_dir = tmp_path / "apps" / "notion-software_engineer"
    manifest = json.loads((app_dir / "lane_manifest.json").read_text(encoding="utf-8"))
    assert manifest["jd_quality"] == "ats"
    assert (app_dir / "jd.provenance.json").exists()


def test_database_metadata_disagreement_fails_before_any_model_call(tmp_path, fake_chain, passing_preflight):
    # DB has job 225 with jd_quality='aggregator'
    db_path = tmp_path / "jobs.db"
    _seed_job_with_quality(
        db_path,
        job_id=225,
        company="TikTok",
        title="Software Engineer",
        jd_text=JD_TEXT,
        base_variant="backend",
        jd_quality="aggregator",
        url="https://jobs.lever.co/tiktok/225",
        ats_url="https://jobs.lever.co/tiktok/225",
        resolver="lever",
    )

    # But sidecar fraudulently claims jd_quality='ats'
    jd_p = _create_jd_file(tmp_path)
    _create_ats_sidecar(
        jd_p,
        company="TikTok",
        title="Software Engineer",
        source_url="https://jobs.lever.co/tiktok/225",
        source_type="lever",
        job_id=225,
    )

    with pytest.raises(LaneError, match="database metadata disagreement"):
        run_manual_application(
            jd_p, company="TikTok", title="Software Engineer", variant="backend",
            root=tmp_path / "apps", profile_path=PROFILE, db_path=db_path,
        )

    assert fake_chain == []


# ---------------------------------------------------------------------------
# 7. Valid user-attested official copy passes
# ---------------------------------------------------------------------------

def test_valid_user_attested_official_copy_passes(tmp_path, fake_chain, passing_preflight, pinned_job_id):
    jd_p = _create_jd_file(tmp_path)
    sidecar_path = create_user_attestation(
        jd_p,
        company="Example Co",
        title="Staff Engineer",
        source_url="https://boards.greenhouse.io/example/jobs/999",
        notes="Copied directly from official Greenhouse board",
    )
    assert sidecar_path.is_file()

    outcome = run_manual_application(
        jd_p, company="Example Co", title="Staff Engineer", variant="ml",
        root=tmp_path / "apps", profile_path=PROFILE,
    )

    assert outcome.failed_stage is None
    s1_calls = [args for name, args in fake_chain if name == "s1"]
    assert len(s1_calls) == 1
    # Note: Passed with 'user_attested' quality, never falsely relabeled 'ats'!
    assert s1_calls[0] == (PILOT_JOB_ID, "user_attested")

    app_dir = tmp_path / "apps" / "example_co-staff_engineer"
    manifest = json.loads((app_dir / "lane_manifest.json").read_text(encoding="utf-8"))
    assert manifest["jd_quality"] == "user_attested"
    assert (app_dir / "jd.provenance.json").exists()


# ---------------------------------------------------------------------------
# 8. Changing an attested JD invalidates its attestation
# ---------------------------------------------------------------------------

def test_changing_attested_jd_invalidates_attestation(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    create_user_attestation(
        jd_p,
        company="Example",
        title="Engineer",
        source_url="https://careers.example.com/posting/1",
    )

    # Modify JD text after attestation
    jd_p.write_text(JD_TEXT + " Modified extra content", encoding="utf-8")

    with pytest.raises(LaneError, match="jd hash mismatch"):
        run_manual_application(
            jd_p, company="Example", title="Engineer", variant="ml",
            root=tmp_path / "apps", profile_path=PROFILE,
        )

    assert fake_chain == []

    # Re-attesting restores validity
    create_user_attestation(
        jd_p,
        company="Example",
        title="Engineer",
        source_url="https://careers.example.com/posting/1",
    )
    outcome = run_manual_application(
        jd_p, company="Example", title="Engineer", variant="ml",
        root=tmp_path / "apps", profile_path=PROFILE, dry_run=True,
    )
    assert outcome.failed_stage is None


# ---------------------------------------------------------------------------
# 9. Review-only exports remain visibly non-tailoring
# ---------------------------------------------------------------------------

def _seed_shortlist_db(db_path: Path) -> None:
    conn = db.get_connection(db_path)
    now = "2026-09-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, new_jobs, resolved, failed, filtered_out) VALUES (?, ?, ?, ?, ?, ?)",
        (now, now, 4, 4, 0, 0),
    )
    run_id = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO run_sources (run_id, source, discovered, inserted, resolved, failed) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, "tracker_vansh", 4, 4, 4, 0),
    )

    jobs = [
        # 2 ATS jobs
        ("k1", "Stripe", "Backend SWE", "https://stripe.com/jobs/1", "tracker_vansh", now, "SHORTLISTED", JD_TEXT, "greenhouse", "ats", "https://boards.greenhouse.io/stripe/1", 9.0, "backend"),
        ("k2", "Databricks", "ML SWE", "https://databricks.com/jobs/2", "tracker_vansh", now, "SHORTLISTED", JD_TEXT, "lever", "ats", "https://jobs.lever.co/databricks/2", 8.5, "ml"),
        # 2 Aggregator jobs
        ("k3", "TikTok", "Backend SWE", "https://jobright.ai/jobs/3", "tracker_jobright", now, "SHORTLISTED", JD_TEXT, "jobright", "aggregator", None, 8.0, "backend"),
        ("k4", "TikTok", "Infra SWE", "https://jobright.ai/jobs/4", "tracker_jobright", now, "SHORTLISTED", JD_TEXT, "jobright", "aggregator", None, 7.5, "backend"),
    ]
    for j in jobs:
        conn.execute(
            """
            INSERT INTO jobs (
                dedup_key, company, title, url, source, discovered_at, status, jd_text,
                resolver, jd_quality, ats_url, fit_score, base_variant
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            j,
        )
    conn.commit()
    conn.close()


def test_review_only_exports_remain_visibly_non_tailoring(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_shortlist_db(db_path)
    out_dir = tmp_path / "review_shortlist"

    export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=10, mode=ExportMode.REVIEW_ONLY)

    # 1. README clearly states REVIEW ONLY and warns against direct tailoring
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "REVIEW ONLY - NOT TAILORING READY" in readme
    assert "Aggregator summaries lack literal employer wording and cannot be tailored directly" in readme
    assert "Review-Only (Aggregator)" in readme

    # 2. JSON clearly marked review_only
    json_data = json.loads((out_dir / "jobs_top10.json").read_text(encoding="utf-8"))
    assert json_data["mode"] == "review_only"
    assert json_data["total_evaluated"] == 4
    assert json_data["included_count"] == 4

    # 3. Provenance sidecars for aggregator rows record jd_quality="aggregator"
    tiktok_sidecars = [p for p in out_dir.glob("jds/*.provenance.json") if "tiktok" in p.name.lower()]
    assert len(tiktok_sidecars) == 2
    for sc_path in tiktok_sidecars:
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        assert sc["jd_quality"] == "aggregator"

    # 4. Attempting to feed an aggregator JD from this export to tailor_now fails immediately
    tiktok_jd = out_dir / "jds" / tiktok_sidecars[0].name.replace(".provenance.json", "")
    sc_0 = json.loads(tiktok_sidecars[0].read_text(encoding="utf-8"))
    with pytest.raises(LaneError, match="cannot tailor aggregator-quality JD"):
        run_manual_application(
            tiktok_jd, company=sc_0["company"], title=sc_0["title"], variant="backend",
            root=tmp_path / "apps", profile_path=PROFILE,
        )


# ---------------------------------------------------------------------------
# 10. Tailoring-ready exports contain zero aggregator jobs
# ---------------------------------------------------------------------------

def test_tailoring_ready_exports_contain_zero_aggregator_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_shortlist_db(db_path)
    out_dir = tmp_path / "tailoring_shortlist"

    export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=10, mode=ExportMode.TAILORING_READY)

    # 1. Exactly 2 ATS jobs exported, 2 aggregator jobs excluded
    json_data = json.loads((out_dir / "jobs_top10.json").read_text(encoding="utf-8"))
    assert json_data["mode"] == "tailoring_ready"
    assert json_data["total_evaluated"] == 4
    assert json_data["included_count"] == 2
    assert json_data["excluded_count"] == 2
    for ex in json_data["excluded"]:
        assert ex["company"] == "TikTok"
        assert "aggregator summary" in ex["reason"]

    # 2. In jds/: only 2 txt files and 2 provenance files exist
    jd_txt_files = sorted(out_dir.glob("jds/*.txt"))
    assert len(jd_txt_files) == 2
    assert not any("tiktok" in f.name.lower() for f in jd_txt_files)

    sidecars = sorted(out_dir.glob("jds/*.provenance.json"))
    assert len(sidecars) == 2
    for sc_path in sidecars:
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        assert sc["jd_quality"] == "ats"

    # 3. Exported DB contains only the 2 tailoring-ready jobs
    exp_conn = sqlite3.connect(out_dir / "jobs_top10.db")
    rows = exp_conn.execute("SELECT id, company, jd_quality FROM jobs").fetchall()
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"Stripe", "Databricks"}
    assert {r[2] for r in rows} == {"ats"}
    exp_conn.close()

    # 4. README reports exclusions clearly
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "Excluded Shortlisted Jobs (2)" in readme
    assert "TikTok" in readme


# ---------------------------------------------------------------------------
# 11. Export publication is atomic and deterministic
# ---------------------------------------------------------------------------

def test_export_publication_is_atomic_and_deterministic(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_shortlist_db(db_path)
    out_dir = tmp_path / "shortlist_export"

    # First export with limit 10 (exports 2 ATS jobs)
    export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=10, mode=ExportMode.TAILORING_READY)
    files_1 = {p.name: p.read_bytes() for p in out_dir.glob("jds/*")}
    assert len(files_1) == 4  # 2 txt + 2 provenance

    # Second export with limit 1 (exports only 1 ATS job: Stripe)
    export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=1, mode=ExportMode.TAILORING_READY)
    files_2 = {p.name: p.read_bytes() for p in out_dir.glob("jds/*")}

    # Exactly 1 job (2 files) remains; the stale Databricks file was purged!
    assert len(files_2) == 2
    assert any("stripe" in name.lower() for name in files_2)
    assert not any("databricks" in name.lower() for name in files_2)

    # Identical export produces deterministic byte hashes
    out_dir_b = tmp_path / "shortlist_export_b"
    export_shortlist(db_path=str(db_path), out_dir=str(out_dir_b), limit=1, mode=ExportMode.TAILORING_READY)
    files_b = {p.name: p.read_bytes() for p in out_dir_b.glob("jds/*")}
    for name in files_2:
        assert files_2[name] == files_b[name]


# ---------------------------------------------------------------------------
# 12. No raw shortlist SQL outside src/db.py
# ---------------------------------------------------------------------------

def test_no_raw_shortlist_sql_outside_src_db():
    script_path = Path("scripts/export_shortlist.py")
    content = script_path.read_text(encoding="utf-8")

    # Ensure no raw SQL statements appear as string literals in export_shortlist.py
    sql_patterns = [
        re.compile(r'["\']\s*SELECT\b', re.IGNORECASE),
        re.compile(r'["\']\s*INSERT\s+INTO\b', re.IGNORECASE),
        re.compile(r'["\']\s*CREATE\s+TABLE\b', re.IGNORECASE),
        re.compile(r'["\']\s*PRAGMA\b', re.IGNORECASE),
        re.compile(r'["\']\s*DELETE\s+FROM\b', re.IGNORECASE),
        re.compile(r'["\']\s*UPDATE\b', re.IGNORECASE),
    ]

    for pattern in sql_patterns:
        match = pattern.search(content)
        assert match is None, f"Found raw SQL literal in scripts/export_shortlist.py: {match.group(0)!r}"


# ---------------------------------------------------------------------------
# 13. Dry run performs no model call and no output write
# ---------------------------------------------------------------------------

def test_dry_run_performs_no_model_call_and_no_output_write(tmp_path, fake_chain, passing_preflight):
    jd_p = _create_jd_file(tmp_path)
    _create_user_attested_sidecar(jd_p, company="Example", title="Engineer")

    outcome = run_manual_application(
        jd_p, company="Example", title="Engineer", variant="ml",
        root=tmp_path / "apps", profile_path=PROFILE, dry_run=True,
    )

    assert outcome.failed_stage is None
    assert fake_chain == []
    assert not (tmp_path / "apps").exists()


# ---------------------------------------------------------------------------
# 14. Attestation refuses aggregator URLs
# ---------------------------------------------------------------------------

def test_attestation_refuses_aggregator_urls(tmp_path):
    jd_p = _create_jd_file(tmp_path)

    for agg_url in [
        "https://www.linkedin.com/jobs/view/12345",
        "https://jobright.ai/jobs/recommend/6789",
        "https://simplify.jobs/p/abcdef",
        "https://www.indeed.com/viewjob?jk=12345",
        "https://www.glassdoor.com/job-listing/12345",
    ]:
        with pytest.raises(ProvenanceError, match="cannot attest an aggregator URL"):
            create_user_attestation(
                jd_p,
                company="Example",
                title="Engineer",
                source_url=agg_url,
            )

    # Valid employer / ATS URL passes
    sidecar = create_user_attestation(
        jd_p,
        company="Example",
        title="Engineer",
        source_url="https://jobs.lever.co/example/12345",
    )
    assert sidecar.is_file()


# ---------------------------------------------------------------------------
# 15. CLI attest and run commands integration
# ---------------------------------------------------------------------------

def test_cli_attest_command_integration(tmp_path, capsys):
    jd_p = _create_jd_file(tmp_path)
    rc = cli.main([
        "attest",
        "--jd", str(jd_p),
        "--company", "Acme",
        "--title", "Software Engineer",
        "--source-url", "https://boards.greenhouse.io/acme/jobs/123",
        "--notes", "Pasted from official careers site",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote provenance sidecar" in out
    assert "user_attested" in out

    sidecar = find_provenance_sidecar(jd_p)
    assert sidecar is not None
    prov = parse_provenance_dict(json.loads(sidecar.read_text(encoding="utf-8")))
    assert prov.company == "Acme"
    assert prov.title == "Software Engineer"
    assert prov.jd_quality == "user_attested"
    assert prov.attestation is not None
    assert prov.attestation.attester == "user"


# ---------------------------------------------------------------------------
# 16. Adversarial Rejection Tests (Strict Provenance State Machine Verification)
# ---------------------------------------------------------------------------

def test_adversarial_1_ats_with_job_id_null_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/1",
        "source_type": "ats",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://jobs.lever.co/example/1",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="ATS provenance sidecar requires a valid integer job_id"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_2_ats_without_database_connection_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/1",
        "source_type": "ats",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": 225,
        "ats_url": "https://jobs.lever.co/example/1",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="requires an active database connection"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer", db_conn=None)


def test_adversarial_3_ats_referencing_nonexistent_database_row_is_rejected(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = db.get_connection(db_path)

    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/1",
        "source_type": "ats",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": 999,
        "ats_url": "https://jobs.lever.co/example/1",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="nonexistent database row"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer", db_conn=conn)
    conn.close()


def test_adversarial_4_ats_whose_file_text_differs_from_db_jd_text_is_rejected(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_job_with_quality(
        db_path,
        job_id=225,
        company="Example",
        title="Engineer",
        jd_text="Original DB text that differs from file",
        url="https://jobs.lever.co/example/1",
        ats_url="https://jobs.lever.co/example/1",
        resolver="lever",
    )
    conn = db.get_readonly_connection(db_path)

    jd_p = _create_jd_file(tmp_path, content="Different file text on disk " * 20)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/1",
        "source_type": "lever",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": 225,
        "ats_url": "https://jobs.lever.co/example/1",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="database JD text mismatch"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer", db_conn=conn)
    conn.close()


def test_adversarial_5_ats_whose_source_url_disagrees_with_db_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    db_path = tmp_path / "jobs.db"
    _seed_job_with_quality(
        db_path,
        job_id=225,
        company="Example",
        title="Engineer",
        jd_text=JD_TEXT,
        url="https://jobs.lever.co/example/original",
        ats_url="https://jobs.lever.co/example/original",
        resolver="lever",
    )
    conn = db.get_readonly_connection(db_path)

    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/forged_different",
        "source_type": "lever",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": 225,
        "ats_url": "https://jobs.lever.co/example/forged_different",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="database URL disagreement"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer", db_conn=conn)
    conn.close()


def test_adversarial_6_ats_carrying_an_attestation_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    db_path = tmp_path / "jobs.db"
    _seed_job_with_quality(
        db_path,
        job_id=225,
        company="Example",
        title="Engineer",
        jd_text=JD_TEXT,
        url="https://jobs.lever.co/example/1",
        ats_url="https://jobs.lever.co/example/1",
        resolver="lever",
    )
    conn = db.get_readonly_connection(db_path)

    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://jobs.lever.co/example/1",
        "source_type": "lever",
        "jd_quality": "ats",
        "jd_sha256": sha,
        "job_id": 225,
        "ats_url": "https://jobs.lever.co/example/1",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://jobs.lever.co/example/1",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="ATS provenance sidecar must not carry an attestation"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer", db_conn=conn)
    conn.close()


def test_adversarial_7_user_attested_with_attestation_null_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="user_attested quality requires an attestation"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_8_user_attested_with_non_null_job_id_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": 225,
        "ats_url": "https://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://example.com/job",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="user_attested copy must not have a database job_id"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_9_user_attested_with_mismatched_top_level_and_attestation_urls_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job-a",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job-a",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://example.com/job-b",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="does not match sidecar source_url"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_10_user_attested_with_http_rather_than_https_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "http://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "http://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "http://example.com/job",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="must use HTTPS"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_11_user_attested_with_known_aggregator_url_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://www.linkedin.com/jobs/view/9999",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://www.linkedin.com/jobs/view/9999",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://www.linkedin.com/jobs/view/9999",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="cannot attest an aggregator URL"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_12_user_attested_with_invalid_or_timezone_naive_attested_at_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    # Test naive timestamp
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T12:00:00",  # naive, missing timezone!
            "attester": "user",
            "source_url": "https://example.com/job",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="timezone-aware UTC ISO-8601"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_13_user_attested_with_empty_attester_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "   ",  # empty
            "source_url": "https://example.com/job",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="attester must be a nonempty string"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_14_user_attested_with_unknown_attestation_fields_is_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "user_attested",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://example.com/job",
            "unauthorized_field": "injected",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="unrecognized keys in attestation"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_adversarial_15_unknown_quality_source_type_combinations_are_rejected(tmp_path):
    jd_p = _create_jd_file(tmp_path)
    sha = compute_jd_sha256(jd_p.read_bytes())
    sidecar_p = jd_p.parent / f"{jd_p.name}.provenance.json"

    # unknown quality
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "partner",
        "jd_quality": "partner",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": None,
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="cannot tailor unverified JD"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")

    # Inconsistent combination: user_attested quality but source_type='ats'
    sidecar_p.write_text(json.dumps({
        "schema_version": JD_PROVENANCE_SCHEMA,
        "company": "Example",
        "title": "Engineer",
        "source_url": "https://example.com/job",
        "source_type": "ats",
        "jd_quality": "user_attested",
        "jd_sha256": sha,
        "job_id": None,
        "ats_url": "https://example.com/job",
        "attestation": {
            "attested_at": "2026-09-17T00:00:00+00:00",
            "attester": "user",
            "source_url": "https://example.com/job",
        },
    }), encoding="utf-8")

    with pytest.raises(ProvenanceError, match="requires source_type='user_attested'"):
        validate_provenance_for_tailoring(jd_p, company="Example", title="Engineer")


def test_export_shortlist_failure_injection_preserves_previous_export(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _seed_shortlist_db(db_path)
    out_dir = tmp_path / "shortlist_export"

    # 1. Complete successful initial export
    export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=10, mode=ExportMode.TAILORING_READY)
    current_json = out_dir / "current.json"
    assert current_json.exists()
    initial_current_data = json.loads(current_json.read_text(encoding="utf-8"))
    initial_gen_id = initial_current_data["generation_id"]
    initial_files = {p.name: p.read_bytes() for p in out_dir.glob("jds/*")}
    initial_readme = (out_dir / "README.md").read_text(encoding="utf-8")
    initial_db_bytes = (out_dir / "jobs_top10.db").read_bytes()

    # 2. Inject failure during the next export's artifact creation
    original_dump = json.dump

    def failing_dump(obj, fp, **kwargs):
        if isinstance(obj, dict) and obj.get("mode") == "tailoring_ready":
            raise OSError("Disk full simulation during export")
        return original_dump(obj, fp, **kwargs)

    monkeypatch.setattr("json.dump", failing_dump)

    with pytest.raises(OSError, match="Disk full simulation"):
        export_shortlist(db_path=str(db_path), out_dir=str(out_dir), limit=1, mode=ExportMode.TAILORING_READY)

    # 3. Verify previous export is completely unchanged and readable
    assert current_json.exists()
    post_failure_current_data = json.loads(current_json.read_text(encoding="utf-8"))
    assert post_failure_current_data["generation_id"] == initial_gen_id

    post_failure_files = {p.name: p.read_bytes() for p in out_dir.glob("jds/*")}
    assert post_failure_files == initial_files
    assert (out_dir / "README.md").read_text(encoding="utf-8") == initial_readme
    assert (out_dir / "jobs_top10.db").read_bytes() == initial_db_bytes
