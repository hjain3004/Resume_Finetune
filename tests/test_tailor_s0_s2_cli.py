import json
import sqlite3
import subprocess
from unittest.mock import patch

from scripts import tailor_s0_s2
from src import db
from src.models import Status
from src.tailor.s0 import parse_s0_request


def _db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("""INSERT INTO jobs
        (dedup_key, company, title, location, url, source, discovered_at,
         status, jd_text, jd_quality, base_variant)
        VALUES ('key', 'Example', 'Engineer', 'Remote', 'https://example.test/job',
         'inbox', '2026-08-01T00:00:00+00:00', ?, 'Python', 'ats', 'backend')""", (Status.SHORTLISTED,))
    conn.commit(); conn.close()


def _s1():
    return {"must_have": [{"term": "Python", "quote": "Python"}], "nice_to_have": [], "responsibilities_summary": [], "seniority_signals": [], "disqualifiers": [], "company_context": None, "suspected_injection": []}


def _prepared(tmp_path):
    database = tmp_path / "jobs.db"; _db(database)
    source = tmp_path / "s1"; source.mkdir()
    (source / "s1_request.json").write_text(json.dumps({"job_id": 1, "company": "Example", "title": "Engineer", "jd_quality": "ats", "jd_text": "Python"}))
    (source / "s1.json").write_text(json.dumps(_s1()))
    output = tmp_path / "prepared"
    assert tailor_s0_s2.main(["prepare", "--job-id", "1", "--db", str(database), "--s1-request", str(source / "s1_request.json"), "--s1", str(source / "s1.json"), "--profile", "config/master_profile.yaml", "--output", str(output)]) == 0
    return database, output


def test_prepare_s2_rejects_tampered_catalog_and_keeps_output_absent(tmp_path):
    database, prepared = _prepared(tmp_path)
    request = parse_s0_request(json.loads((prepared / "s0_request.json").read_text()))
    s0 = {"context_mode": "jd_only", "points": [
        {"sentence": "a", "profile_ids": [request.positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
        {"sentence": "b", "profile_ids": [request.positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
    ]}
    (prepared / "s0.json").write_text(json.dumps(s0))
    catalog = json.loads((prepared / "s2_catalog.json").read_text())
    catalog["bullets"][0]["keywords_hit"] = ["fabricated"]
    (prepared / "s2_catalog.json").write_text(json.dumps(catalog))
    rc = tailor_s0_s2.main(["prepare-s2", "--s1-request", str(tmp_path / "s1" / "s1_request.json"), "--s1", str(tmp_path / "s1" / "s1.json"), "--s0", str(prepared / "s0.json"), "--s0-request", str(prepared / "s0_request.json"), "--catalog", str(prepared / "s2_catalog.json"), "--db", str(database), "--profile", "config/master_profile.yaml", "--output", str(prepared)])
    assert rc != 0 and not (prepared / "s2_request.json").exists()


def test_invoke_s0_dry_run_does_not_call_or_publish(tmp_path):
    _, prepared = _prepared(tmp_path)
    with patch.object(subprocess, "run") as run:
        rc = tailor_s0_s2.main(["invoke-s0", "--request", str(prepared / "s0_request.json"), "--output", str(prepared), "--dry-run"])
    assert rc == 0 and not run.called and not (prepared / "s0.json").exists()


def test_prepare_rejects_injection_blocked_s1(tmp_path):
    database = tmp_path / "jobs.db"; _db(database)
    source = tmp_path / "source"; source.mkdir()
    (source / "s1_request.json").write_text(json.dumps({"job_id": 1, "company": "Example", "title": "Engineer", "jd_quality": "ats", "jd_text": "Python"}))
    response = _s1(); response["suspected_injection"] = [{"quote": "Python", "reason": "instruction-like"}]
    (source / "s1.json").write_text(json.dumps(response))
    assert tailor_s0_s2.main(["prepare", "--job-id", "1", "--db", str(database), "--s1-request", str(source / "s1_request.json"), "--s1", str(source / "s1.json"), "--profile", "config/master_profile.yaml", "--output", str(tmp_path / "out")]) != 0
