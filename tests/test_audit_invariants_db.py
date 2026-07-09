import json
import sqlite3

from src import db
from src.audit.invariants_db import check_i6a, check_i6b, check_i8, check_i9, check_i10
from src.models import Status

_FILTERS_CFG = {
    "title_include": ["software|swe|backend"],
    "title_exclude": ["senior|staff"],
}
_AUDIT_CFG = {"i6": {"warn_filtered_pct_above": 0.90, "warn_filtered_pct_below": 0.20}, "i9": {"stale_flag": "stale_logic_version"}}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def test_i6a_fail_when_a_scored_row_title_would_be_excluded():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status)
        VALUES ('k1', 'Acme', 'Senior Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'SCORED')
        """
    )
    conn.commit()
    finding = check_i6a(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "FAIL"


def test_i6a_pass_when_titles_all_pass_prefilter():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'SCORED')
        """
    )
    conn.commit()
    finding = check_i6a(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "PASS"


def test_i6b_warn_when_run_filters_over_90_percent():
    conn = _conn()
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, resolved=1, filtered_out=10)
    finding = check_i6b(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "WARN"


def test_i6b_pass_for_normal_filter_rate():
    conn = _conn()
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, resolved=10, filtered_out=5)
    finding = check_i6b(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "PASS"


def test_i8_fail_on_discovered_row_at_resolve_limit():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'DISCOVERED', 3)
        """
    )
    conn.commit()
    finding = check_i8(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "FAIL"


def test_i8_fail_on_scored_row_missing_fit_score():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'SCORED')
        """
    )
    conn.commit()
    finding = check_i8(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "FAIL"


def test_i8_pass_for_legal_state_machine():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, fit_score)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'SCORED', 6.0)
        """
    )
    conn.commit()
    finding = check_i8(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "PASS"


def test_i9_warn_first_time_flags_stale_active_row():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolved_logic_version)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 1)
        """
    )
    conn.commit()
    audit_cfg = {**_AUDIT_CFG, "current_logic_version": 2}

    finding = check_i9(conn, audit_cfg, _FILTERS_CFG, {}, None)

    assert finding.status == "WARN"
    row = conn.execute("SELECT flags FROM jobs WHERE dedup_key='k1'").fetchone()
    assert "stale_logic_version" in json.loads(row["flags"])


def test_i9_fail_when_already_flagged_row_is_still_stale():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolved_logic_version, flags)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 1, '["stale_logic_version"]')
        """
    )
    conn.commit()
    audit_cfg = {**_AUDIT_CFG, "current_logic_version": 2}

    finding = check_i9(conn, audit_cfg, _FILTERS_CFG, {}, None)

    assert finding.status == "FAIL"


def test_i9_pass_when_row_is_current():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at, status, resolved_logic_version)
        VALUES ('k1', 'Acme', 'Software Engineer', 'https://acme.example/1', 'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 2)
        """
    )
    conn.commit()
    audit_cfg = {**_AUDIT_CFG, "current_logic_version": 2}

    finding = check_i9(conn, audit_cfg, _FILTERS_CFG, {}, None)

    assert finding.status == "PASS"


def test_i10_fail_on_orphaned_run_sources_row():
    conn = _conn()
    conn.execute(
        "INSERT INTO run_sources (run_id, source, discovered) VALUES (999, 'tracker_vansh', 1)"
    )
    conn.commit()
    finding = check_i10(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "FAIL"


def test_i10_pass_for_clean_db():
    conn = _conn()
    run_id = db.start_run(conn)
    db.record_run_source(conn, run_id, "tracker_vansh", discovered=1)
    finding = check_i10(conn, _AUDIT_CFG, _FILTERS_CFG, {}, None)
    assert finding.status == "PASS"
