"""Tests for db.prepare_tailoring_request (M8P-1): the read-only S1
job-preparation boundary. No status/notes/flags mutation is permitted --
every test asserts the row is untouched after the call."""

import sqlite3

import pytest

from src import db
from src.models import Status
from src.tailor.s1 import S1Request


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_db(connection)
    return connection


def _insert_job(conn, **overrides) -> int:
    defaults = dict(
        dedup_key=f"key-{overrides.get('id', 'x')}-{overrides.get('title', 'Software Engineer')}",
        company="Acme",
        title="Backend Engineer",
        location="Remote",
        url="https://example.com/job/1",
        source="tracker_vansh",
        date_posted=None,
        discovered_at="2026-08-01T00:00:00+00:00",
        status=Status.SHORTLISTED,
        jd_text="We need a Backend Engineer with 3+ years of Python experience.",
        jd_quality="ats",
        base_variant="backend",
    )
    defaults.update(overrides)
    cursor = conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, date_posted,
                           discovered_at, status, jd_text, jd_quality, base_variant)
        VALUES (:dedup_key, :company, :title, :location, :url, :source, :date_posted,
                :discovered_at, :status, :jd_text, :jd_quality, :base_variant)
        """,
        defaults,
    )
    conn.commit()
    return cursor.lastrowid


def _row(conn, job_id):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def test_prepare_tailoring_request_returns_typed_request(conn):
    job_id = _insert_job(conn, company="Cisco", title="ML Engineer")
    request = db.prepare_tailoring_request(conn, job_id)
    assert request == S1Request(
        job_id=job_id,
        company="Cisco",
        title="ML Engineer",
        jd_text="We need a Backend Engineer with 3+ years of Python experience.",
        jd_quality="ats",
    )


def test_prepare_tailoring_request_does_not_mutate_row(conn):
    job_id = _insert_job(conn)
    before = dict(_row(conn, job_id))
    db.prepare_tailoring_request(conn, job_id)
    after = dict(_row(conn, job_id))
    assert before == after


def test_prepare_tailoring_request_missing_row_rejected(conn):
    with pytest.raises(db.TailoringPrepError, match="no such row"):
        db.prepare_tailoring_request(conn, 999)


def test_prepare_tailoring_request_non_shortlisted_status_rejected(conn):
    job_id = _insert_job(conn, status=Status.SCORED)
    with pytest.raises(db.TailoringPrepError, match="status"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_aggregator_quality_rejected(conn):
    job_id = _insert_job(conn, jd_quality="aggregator")
    with pytest.raises(db.TailoringPrepError, match="jd_quality"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_empty_jd_text_rejected(conn):
    job_id = _insert_job(conn, jd_text="")
    with pytest.raises(db.TailoringPrepError, match="jd_text"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_whitespace_only_jd_text_rejected(conn):
    job_id = _insert_job(conn, jd_text="   \n  ")
    with pytest.raises(db.TailoringPrepError, match="jd_text"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_null_jd_text_rejected(conn):
    job_id = _insert_job(conn, jd_text=None)
    with pytest.raises(db.TailoringPrepError, match="jd_text"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_invalid_base_variant_rejected(conn):
    job_id = _insert_job(conn, base_variant="frontend")
    with pytest.raises(db.TailoringPrepError, match="base_variant"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_null_base_variant_rejected(conn):
    job_id = _insert_job(conn, base_variant=None)
    with pytest.raises(db.TailoringPrepError, match="base_variant"):
        db.prepare_tailoring_request(conn, job_id)


def test_prepare_tailoring_request_ml_base_variant_accepted(conn):
    job_id = _insert_job(conn, base_variant="ml")
    request = db.prepare_tailoring_request(conn, job_id)
    assert request.job_id == job_id


@pytest.mark.parametrize("prohibited_id", [229, 279])
def test_prepare_tailoring_request_prohibited_job_ids_rejected(conn, prohibited_id):
    conn.execute(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source,
                           discovered_at, status, jd_text, jd_quality, base_variant)
        VALUES (?, ?, 'Acme', 'Backend Engineer', 'Remote', 'https://example.com/job/x',
                'tracker_vansh', '2026-08-01T00:00:00+00:00', ?, 'JD text here', 'ats', 'backend')
        """,
        (prohibited_id, f"key-{prohibited_id}", Status.SHORTLISTED),
    )
    conn.commit()
    with pytest.raises(db.TailoringPrepError, match="prohibited"):
        db.prepare_tailoring_request(conn, prohibited_id)


def test_prepare_tailoring_request_prohibited_id_rejected_even_if_row_missing(conn):
    with pytest.raises(db.TailoringPrepError, match="prohibited"):
        db.prepare_tailoring_request(conn, 229)
