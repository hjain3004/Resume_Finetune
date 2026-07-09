# tests/test_audit_2026_07_06_regression.py
import shutil
import sqlite3
from pathlib import Path

from src import db
from src.audit.invariants_export import check_i3, check_i4, check_i5

_AUDIT_CFG = {"i3": {"similarity_threshold": 0.85}, "i3b": {"similarity_threshold": 0.50}}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def test_archived_2026_07_06_batch_fails_i3(tmp_path):
    (tmp_path / "data" / "batch").mkdir(parents=True)
    shutil.copy(
        "tests/fixtures/audit_2026_07_06_batch.json",
        tmp_path / "data" / "batch" / "2026-07-06.json",
    )
    finding = check_i3(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "FAIL"


def test_archived_2026_07_06_batch_fails_i4(tmp_path):
    (tmp_path / "data" / "batch").mkdir(parents=True)
    shutil.copy(
        "tests/fixtures/audit_2026_07_06_batch.json",
        tmp_path / "data" / "batch" / "2026-07-06.json",
    )
    finding = check_i4(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "FAIL"


def test_archived_2026_07_06_batch_fails_i5(tmp_path):
    import shutil as sh

    (tmp_path / "data" / "batch").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    sh.copy("tests/fixtures/audit_2026_07_06_batch.json", tmp_path / "data" / "batch" / "2026-07-06.json")
    sh.copy("config/batch_schema.json", tmp_path / "config" / "batch_schema.json")
    sh.copy("config/scored_schema.json", tmp_path / "config" / "scored_schema.json")
    finding = check_i5(_conn(), _AUDIT_CFG, {}, {}, tmp_path)
    assert finding.status == "FAIL"
