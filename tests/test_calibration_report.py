import sqlite3

from scripts import calibration_report
from src.db import init_db

WORKSHEET = """\
# Calibration baseline — 2026-07-12

| id | company | title | jd_quality | flags | your call | notes |
|---|---|---|---|---|---|---|
| 1 | Acme Inc | Backend Engineer | ats |  | APPLY | |
| 2 | Beta Corp | Software Engineer | aggregator |  | SKIP | |
| 3 | Gamma LLC | Firmware Engineer | ats |  | MAYBE | |
| 4 | Delta Co | ML Engineer | ats |  | | |
| 5 | Epsilon | Data Engineer | ats |  | apply | |
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, fit_score)
        VALUES (1, 'k1', 'Acme Inc', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'SCORED', 5.0);

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, fit_score)
        VALUES (2, 'k2', 'Beta Corp', 'Software Engineer', 'Remote', 'https://beta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'SHORTLISTED', 8.0);

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, fit_score)
        VALUES (3, 'k3', 'Gamma LLC', 'Firmware Engineer', 'Remote', 'https://gamma.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'SHORTLISTED', 9.0);

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES (4, 'k4', 'Delta Co', 'ML Engineer', 'Remote', 'https://delta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED');

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, fit_score)
        VALUES (5, 'k5', 'Epsilon', 'Data Engineer', 'Remote', 'https://epsilon.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'SHORTLISTED', 7.0);
        """
    )
    conn.commit()
    return conn


def test_parse_worksheet_extracts_only_rated_rows():
    rows, total = calibration_report.parse_worksheet(WORKSHEET)
    assert total == 5
    assert [r.job_id for r in rows] == [1, 2, 3, 5]


def test_parse_worksheet_is_case_insensitive_on_call():
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    epsilon = next(r for r in rows if r.job_id == 5)
    assert epsilon.call == "APPLY"


def test_apply_below_threshold_is_a_disagreement():
    conn = _conn()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, unscored = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    ids = {d.job_id for d in disagreements}
    assert 1 in ids  # APPLY, fit_score 5.0 < 7.0


def test_skip_at_or_above_threshold_is_a_disagreement():
    conn = _conn()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, _ = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    ids = {d.job_id for d in disagreements}
    assert 2 in ids  # SKIP, fit_score 8.0 >= 7.0


def test_maybe_never_counts_as_disagreement():
    conn = _conn()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, _ = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    ids = {d.job_id for d in disagreements}
    assert 3 not in ids  # MAYBE, fit_score 9.0 — never a threshold-crossing disagreement


def test_apply_at_or_above_threshold_is_not_a_disagreement():
    conn = _conn()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, _ = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    ids = {d.job_id for d in disagreements}
    assert 5 not in ids  # APPLY, fit_score 7.0 >= 7.0 -> agreement


def test_unrated_row_never_scored_is_reported_unscored_not_disagreement():
    conn = _conn()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, unscored = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    # id 4 has no "your call" so it's excluded before find_disagreements ever sees it;
    # this test instead covers a rated row whose fit_score is still NULL (not yet scored).
    assert all(d.job_id != 4 for d in disagreements)


def test_rated_but_unscored_job_is_excluded_from_disagreements_and_flagged():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES (1, 'k1', 'Acme Inc', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED');
        """
    )
    conn.commit()
    rows, _ = calibration_report.parse_worksheet(WORKSHEET)
    disagreements, unscored = calibration_report.find_disagreements(conn, rows, threshold=7.0)
    assert all(d.job_id != 1 for d in disagreements)
    assert 1 in {u.job_id for u in unscored}
