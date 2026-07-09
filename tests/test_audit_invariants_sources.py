import sqlite3

from src import db
from src.audit.invariants_sources import check_i1, check_i2


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


_AUDIT_CFG = {
    "i1": {"warn_consecutive_zero_runs": 3, "fail_consecutive_zero_runs": 7, "trailing_runs_considered": 7},
    "i2": {"fail_resolve_rate_below": 0.5, "trailing_runs_considered": 3, "warn_domain_failure_count": 3},
}
_FILTERS_CFG = {
    "title_include": ["software|swe|backend"],
    "title_exclude": ["senior|staff"],
}


def _seed_runs_with_zero_discoveries(conn, source, n):
    for _ in range(n):
        run_id = db.start_run(conn)
        db.record_run_source(conn, run_id, source, discovered=0, inserted=0)
        db.finish_run(conn, run_id)


def test_i1_pass_when_source_has_recent_discoveries():
    conn = _conn()
    run_id = db.start_run(conn)
    db.record_run_source(conn, run_id, "tracker_vansh", discovered=5, inserted=2)
    db.finish_run(conn, run_id)

    finding = check_i1(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status == "PASS"


def test_i1_warn_after_three_consecutive_zero_runs():
    conn = _conn()
    _seed_runs_with_zero_discoveries(conn, "tracker_vansh", 3)

    finding = check_i1(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status == "WARN"
    assert any(e["source"] == "tracker_vansh" for e in finding.evidence)


def test_i1_fail_after_seven_consecutive_zero_runs():
    conn = _conn()
    _seed_runs_with_zero_discoveries(conn, "tracker_vansh", 7)

    finding = check_i1(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status == "FAIL"


def test_i2_fail_when_trailing_resolve_rate_below_50_percent():
    conn = _conn()
    for resolved, failed in [(1, 9), (2, 8), (0, 10)]:
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, resolved=resolved, failed=failed)

    finding = check_i2(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status == "FAIL"


def test_i2_pass_when_trailing_resolve_rate_healthy():
    conn = _conn()
    for resolved, failed in [(9, 1), (8, 2), (10, 0)]:
        run_id = db.start_run(conn)
        db.finish_run(conn, run_id, resolved=resolved, failed=failed)

    finding = check_i2(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status != "FAIL"


def test_i2_warn_domain_with_three_failures_on_role_matching_titles():
    conn = _conn()
    conn.executescript(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://gated.example.com/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVE_FAILED', 3);
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k2', 'Beta', 'Software Engineer', 'https://gated.example.com/2', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVE_FAILED', 3);
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k3', 'Gamma', 'Software Engineer', 'https://gated.example.com/3', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVE_FAILED', 3);
        """
    )
    conn.commit()

    finding = check_i2(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)

    assert finding.status == "WARN"
    assert any(e.get("domain") == "gated.example.com" for e in finding.evidence)
