import sqlite3

import pytest

from scripts import import_scores
from src.db import init_db
from src.models import Status


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES (1, 'k1', 'Acme Inc', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED');

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES (2, 'k2', 'Beta Corp', 'Software Engineer', 'Remote', 'https://beta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED');
        """
    )
    conn.commit()
    return conn


def _valid_entry(**overrides) -> dict:
    entry = {
        "id": 1,
        "row_ids": [1],
        "fit_score": 8.5,
        "base_variant": "backend",
        "missing_keywords": ["kubernetes"],
        "rationale": "Strong backend match with relevant experience.",
    }
    entry.update(overrides)
    return entry


def test_import_valid_scores_updates_status_and_fields():
    conn = _conn()
    scored = [
        _valid_entry(id=1, row_ids=[1], fit_score=8.5),
        _valid_entry(id=2, row_ids=[2], fit_score=5.0),
    ]

    result = import_scores.import_scores(conn, scored, threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    row2 = conn.execute("SELECT * FROM jobs WHERE id = 2").fetchone()
    assert row1["status"] == Status.SHORTLISTED
    assert row1["fit_score"] == 8.5
    assert row1["base_variant"] == "backend"
    assert row1["missing_keywords"] == '["kubernetes"]'
    assert row1["fit_rationale"] == "Strong backend match with relevant experience."
    assert row2["status"] == Status.SCORED
    assert result.updated == 2
    assert result.shortlisted == 1


def test_import_rejects_missing_field_with_zero_db_changes():
    conn = _conn()
    entry = _valid_entry()
    del entry["fit_score"]

    with pytest.raises(ValueError, match="fit_score"):
        import_scores.import_scores(conn, [entry], threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    assert row1["status"] == Status.RESOLVED
    assert row1["fit_score"] is None


def test_import_rejects_score_out_of_range():
    conn = _conn()
    entry = _valid_entry(fit_score=11)

    with pytest.raises(ValueError, match="fit_score"):
        import_scores.import_scores(conn, [entry], threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    assert row1["status"] == Status.RESOLVED


def test_import_rejects_unknown_id():
    conn = _conn()
    entry = _valid_entry(id=999, row_ids=[999])

    with pytest.raises(ValueError, match="999"):
        import_scores.import_scores(conn, [entry], threshold=7.0)


def test_import_rejects_unknown_row_id():
    conn = _conn()
    entry = _valid_entry(row_ids=[1, 999])

    with pytest.raises(ValueError, match="999"):
        import_scores.import_scores(conn, [entry], threshold=7.0)


def test_import_rejects_row_ids_missing_own_id():
    conn = _conn()
    entry = _valid_entry(id=1, row_ids=[2])

    with pytest.raises(ValueError, match="row_ids"):
        import_scores.import_scores(conn, [entry], threshold=7.0)


def test_import_rejects_rationale_too_long():
    conn = _conn()
    entry = _valid_entry(rationale="x" * 161)

    with pytest.raises(ValueError, match="rationale"):
        import_scores.import_scores(conn, [entry], threshold=7.0)


def test_import_is_all_or_nothing_across_entries():
    conn = _conn()
    scored = [
        _valid_entry(id=1, row_ids=[1], fit_score=9.0),
        _valid_entry(id=2, row_ids=[2], fit_score=200),
    ]

    with pytest.raises(ValueError):
        import_scores.import_scores(conn, scored, threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    assert row1["status"] == Status.RESOLVED
    assert row1["fit_score"] is None


def test_import_applies_score_to_every_row_id_in_group():
    conn = _conn()
    entry = _valid_entry(id=1, row_ids=[1, 2], fit_score=8.0)

    result = import_scores.import_scores(conn, [entry], threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    row2 = conn.execute("SELECT * FROM jobs WHERE id = 2").fetchone()
    assert row1["status"] == Status.SHORTLISTED
    assert row2["status"] == Status.SHORTLISTED
    assert row2["fit_score"] == 8.0
    assert row2["fit_rationale"] == entry["rationale"]
    assert result.updated == 2
    assert result.shortlisted == 2


def test_import_rejects_row_id_covered_by_two_entries():
    conn = _conn()
    scored = [
        _valid_entry(id=1, row_ids=[1, 2], fit_score=8.0),
        _valid_entry(id=2, row_ids=[2], fit_score=5.0),
    ]

    with pytest.raises(ValueError, match="covered exactly once"):
        import_scores.import_scores(conn, scored, threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    assert row1["status"] == Status.RESOLVED
    assert row1["fit_score"] is None
