import json
import sqlite3

import pytest

from scripts import export_batch, import_scores
from src.db import init_db
from src.models import Status


def _seed(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES (1, 'k1', 'Acme Inc', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Backend role requiring Python and SQL.');

        INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES (2, 'k2', 'Beta Corp', 'Frontend Engineer', 'Remote', 'https://beta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Frontend role requiring React.');
        """
    )
    conn.commit()


def test_export_then_hand_written_scored_file_imports_correctly(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    _seed(conn)

    batch_path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")
    batch = json.loads(batch_path.read_text())
    assert {row["id"] for row in batch} == {1, 2}

    scored_path = tmp_path / "2026-07-05.scored.json"
    scored_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "row_ids": [1],
                    "fit_score": 8.0,
                    "base_variant": "backend",
                    "missing_keywords": [],
                    "rationale": "Direct match on backend stack.",
                },
                {
                    "id": 2,
                    "row_ids": [2],
                    "fit_score": 3.0,
                    "base_variant": "frontend",
                    "missing_keywords": ["typescript"],
                    "rationale": "Some overlap but frontend-focused.",
                },
            ]
        )
    )

    result = import_scores.import_scores(conn, json.loads(scored_path.read_text()), threshold=7.0)

    assert result.updated == 2
    assert result.shortlisted == 1
    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    row2 = conn.execute("SELECT * FROM jobs WHERE id = 2").fetchone()
    assert row1["status"] == Status.SHORTLISTED
    assert row2["status"] == Status.SCORED


def test_invalid_scored_file_rejected_leaves_db_unchanged(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    _seed(conn)

    export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    bad_scored = [
        {
            "id": 1,
            "row_ids": [1],
            "fit_score": 8.0,
            "base_variant": "backend",
            "missing_keywords": [],
            "rationale": "Direct match on backend stack.",
        },
        {
            "id": 2,
            "row_ids": [2],
            "fit_score": 15,
            "base_variant": "frontend",
            "missing_keywords": ["typescript"],
            "rationale": "Some overlap but frontend-focused.",
        },
    ]

    with pytest.raises(ValueError):
        import_scores.import_scores(conn, bad_scored, threshold=7.0)

    row1 = conn.execute("SELECT * FROM jobs WHERE id = 1").fetchone()
    row2 = conn.execute("SELECT * FROM jobs WHERE id = 2").fetchone()
    assert row1["status"] == Status.RESOLVED
    assert row2["status"] == Status.RESOLVED
