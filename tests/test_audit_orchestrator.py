import sqlite3

from src import audit
from src.db import init_db


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_finding_defaults():
    f = audit.Finding(invariant="I1", status="PASS")
    assert f.evidence == []
    assert f.detail == ""


def test_run_all_returns_pass_overall_when_all_checks_pass(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(
        audit, "_CHECKS", [lambda c, ac, fc, frc, rr: audit.Finding(invariant="I0", status="PASS")]
    )
    result = audit.run_all(conn, audit_config={}, filters_config={}, freshness_config={})
    assert result.overall == "PASS"
    assert len(result.findings) == 1


def test_run_all_overall_is_fail_if_any_finding_fails(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(
        audit,
        "_CHECKS",
        [
            lambda c, ac, fc, frc, rr: audit.Finding(invariant="I0", status="PASS"),
            lambda c, ac, fc, frc, rr: audit.Finding(invariant="I1", status="FAIL"),
        ],
    )
    result = audit.run_all(conn, audit_config={}, filters_config={}, freshness_config={})
    assert result.overall == "FAIL"


def test_run_all_overall_is_warn_if_warn_but_no_fail(monkeypatch):
    conn = _conn()
    monkeypatch.setattr(
        audit,
        "_CHECKS",
        [
            lambda c, ac, fc, frc, rr: audit.Finding(invariant="I0", status="PASS"),
            lambda c, ac, fc, frc, rr: audit.Finding(invariant="I1", status="WARN"),
        ],
    )
    result = audit.run_all(conn, audit_config={}, filters_config={}, freshness_config={})
    assert result.overall == "WARN"


def test_to_json_dict_shape():
    conn = _conn()
    result = audit.AuditResult(
        findings=[audit.Finding(invariant="I1", status="PASS", evidence=[{"id": 1}])],
        overall="PASS",
    )
    payload = audit.to_json_dict(result, date_str="2026-07-09")
    assert payload == {
        "date": "2026-07-09",
        "overall": "PASS",
        "findings": [{"invariant": "I1", "status": "PASS", "evidence": [{"id": 1}], "detail": ""}],
    }
