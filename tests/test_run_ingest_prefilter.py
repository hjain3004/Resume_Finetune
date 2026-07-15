from unittest.mock import MagicMock, patch

from src import db, run_ingest
from src.discover.base import DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD, Status

# M7/I6a regression retained for M6.11: a --resolve-only run must still run the
# post-resolution eligibility gate, or newly resolved ineligible rows can sit as
# RESOLVED until a later full run.


def test_resolve_only_run_still_filters_newly_resolved_rows(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    conn = db.get_connection(db_path)
    db.insert_discovered(
        conn,
        [
            DiscoveredJob(
                "Cubic", "Software Integration Engineer", "San Diego, CA",
                "https://cubic.wd1.myworkdayjobs.com/cubic_USA_careers/job/San-Diego-California/Software-Integration-Engineer_REQ_49405",
                "tracker_vansh", None,
            )
        ],
    )
    conn.close()

    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult((), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "PoliteSession", return_value=MagicMock()),
        patch.object(
            run_ingest.resolve,
            "resolve",
            return_value=ResolvedJD("Starts in 2027. We are unable to sponsor visas.", "workday"),
        ),
    ):
        assert run_ingest.main([
            "--db", db_path,
            "--resolve-only",
            "--digest-dir", str(tmp_path / "digests"),
            "--audit-dir", str(tmp_path / "audit"),
        ]) == 0

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT * FROM jobs WHERE company = 'Cubic' AND title = 'Software Integration Engineer'"
    ).fetchone()
    assert row["status"] == Status.FILTERED_OUT
    assert row["filter_reason"] == "eligibility:work_authorization"
