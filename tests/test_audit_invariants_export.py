# tests/test_audit_invariants_export.py
import json
import sqlite3
from pathlib import Path

from src import db
from src.audit.invariants_export import check_i3, check_i3b, check_i4, check_i5

_AUDIT_CFG = {"i3": {"similarity_threshold": 0.85}, "i3b": {"similarity_threshold": 0.50}}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def _write_batch(tmp_path, objects, name="2026-07-06.json"):
    (tmp_path / "data" / "batch").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "data" / "batch" / name
    path.write_text(json.dumps(objects))
    return path


def test_i3_fail_when_two_objects_are_near_duplicates(tmp_path):
    base_jd = (
        "We are looking for a driven software engineer to design build and scale "
        "distributed backend systems handling millions of requests daily across "
        "our microservices platform"
    )
    _write_batch(
        tmp_path,
        [
            {"id": 1, "row_ids": [1], "company": "Acme", "title": "Engineer A", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": base_jd},
            {"id": 2, "row_ids": [2], "company": "Acme", "title": "Engineer B", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": base_jd + " Location: Austin, TX."},
        ],
    )
    finding = check_i3(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "FAIL"
    assert {1, 2} <= {i for e in finding.evidence for i in e["ids"]}


def test_i3_pass_for_unrelated_objects(tmp_path):
    _write_batch(
        tmp_path,
        [
            {"id": 1, "row_ids": [1], "company": "Acme", "title": "A", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": "Backend engineer building distributed systems in Java and Kafka."},
            {"id": 2, "row_ids": [2], "company": "Beta", "title": "B", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": "Warehouse associate needed for logistics operations in Seattle."},
        ],
    )
    finding = check_i3(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "PASS"


def test_i3b_warn_when_merged_cluster_members_are_dissimilar(tmp_path):
    conn = _conn()
    conn.executescript(
        """
        INSERT INTO jobs (id, dedup_key, company, title, url, source, discovered_at, status, jd_text)
        VALUES (1, 'k1', 'Amazon', 'Software Engineer', 'https://amazon.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 'Build cloud storage systems used by millions of customers worldwide daily.');
        INSERT INTO jobs (id, dedup_key, company, title, url, source, discovered_at, status, jd_text)
        VALUES (2, 'k2', 'Amazon', 'Software Engineer', 'https://amazon.example/2', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 'Design checkout and payments infrastructure for the retail marketplace platform.');
        """
    )
    conn.commit()
    _write_batch(
        tmp_path,
        [
            {"id": 1, "row_ids": [1, 2], "company": "Amazon", "title": "Software Engineer", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": "Build cloud storage systems used by millions of customers worldwide daily."},
        ],
    )
    finding = check_i3b(conn, _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "WARN"
    assert finding.evidence[0]["row_ids"] == [1, 2]


def test_i4_fail_lists_ids_carrying_chrome_patterns(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "chrome_patterns.txt").write_text("H1B Sponsor Likely\n")
    _write_batch(
        tmp_path,
        [
            {"id": 1, "row_ids": [1], "company": "Acme", "title": "A", "locations": [], "flags": [], "jd_quality": "aggregator", "jd_text": "Great backend role. H1B Sponsor Likely. Apply now."},
        ],
    )
    finding = check_i4(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "FAIL"
    assert finding.evidence[0]["id"] == 1


def test_i4_pass_when_clean(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "chrome_patterns.txt").write_text("H1B Sponsor Likely\n")
    _write_batch(
        tmp_path,
        [
            {"id": 1, "row_ids": [1], "company": "Acme", "title": "A", "locations": [], "flags": [], "jd_quality": "ats", "jd_text": "Great backend role building distributed systems."},
        ],
    )
    finding = check_i4(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "PASS"


def test_i5_fail_on_schema_violation(tmp_path):
    (tmp_path / "config").mkdir()
    Path("config/batch_schema.json").resolve()
    import shutil

    shutil.copy("config/batch_schema.json", tmp_path / "config" / "batch_schema.json")
    shutil.copy("config/scored_schema.json", tmp_path / "config" / "scored_schema.json")
    _write_batch(
        tmp_path,
        [{"id": 1, "row_ids": [1], "company": "Acme", "title": "A", "jd_quality": "ats", "jd_text": "x"}],
    )  # missing "locations" and "flags"

    finding = check_i5(_conn(), _AUDIT_CFG, {}, {}, tmp_path)

    assert finding.status == "FAIL"


def test_i5_pass_for_valid_batch(tmp_path):
    import shutil

    (tmp_path / "config").mkdir()
    shutil.copy("config/batch_schema.json", tmp_path / "config" / "batch_schema.json")
    shutil.copy("config/scored_schema.json", tmp_path / "config" / "scored_schema.json")
    _write_batch(
        tmp_path,
        [
            {
                "id": 1, "row_ids": [1], "company": "Acme", "title": "A",
                "locations": [], "flags": [], "jd_quality": "ats", "jd_text": "x",
            }
        ],
    )

    finding = check_i5(_conn(), _AUDIT_CFG, {}, {}, tmp_path)

    assert finding.status == "PASS"
