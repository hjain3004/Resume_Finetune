from unittest.mock import MagicMock, patch

from src import db, run_ingest
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, Status


def test_main_runs_liveness_recheck_and_closes_dead_shortlisted_row(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    conn = db.get_connection(db_path)
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, last_seen_at)
        VALUES ('k1', 'Acme', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh',
                '2026-07-05T00:00:00+00:00', 'SHORTLISTED', '2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    conn.close()

    mock_session = MagicMock()
    mock_session.get.return_value = MagicMock(status_code=404)

    with (
        patch.object(run_ingest, "discover_all", return_value=[]),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "PoliteSession", return_value=mock_session),
    ):
        assert run_ingest.main(["--db", db_path, "--digest-dir", str(tmp_path / "digests")]) == 0

    conn = db.get_connection(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE dedup_key = 'k1'").fetchone()
    assert row["status"] == Status.CLOSED
    assert "404" in row["notes"]


def test_main_threads_freshness_config_stale_days_into_insert_discovered(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    old_job = DiscoveredJob("Acme", "Backend Engineer", "Remote", "https://acme.example/1", "tracker_vansh", "2026-01-01")

    with (
        patch.object(run_ingest, "discover_all", return_value=[old_job]),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "PoliteSession", return_value=MagicMock()),
        patch.object(run_ingest.resolve, "resolve", return_value=None),
    ):
        assert run_ingest.main(["--db", db_path, "--discover-only"]) == 0

    conn = db.get_connection(db_path)
    row = conn.execute("SELECT * FROM jobs WHERE dedup_key IS NOT NULL").fetchone()
    import json

    assert json.loads(row["flags"]) == ["stale_listing"]
