from unittest.mock import MagicMock, patch

from src import db, run_ingest
from src.discover.base import DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD, Status

# M7 I6a regression: a --resolve-only run used to skip prefilter.run_prefilter()
# entirely (src/run_ingest.py gated the call behind `if not args.resolve_only`),
# leaving newly-resolved rows sitting as RESOLVED with no filter_reason verdict
# until someone happened to run the full pipeline. Live evidence: id 257 (Cubic,
# "Software Integration Engineer", San Diego, CA — outside location_allow) leaked
# through exactly this way during an interrupted resolve-only smoke run (run id 9,
# 2026-07-08). See DECISIONS.md 2026-07-12 for the approved fix: prefilter
# eligibility is a state condition (RESOLVED + filter_reason IS NULL), so it must
# be swept on every run that can produce such rows, not just "full" runs.


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
        patch.object(run_ingest.resolve, "resolve", return_value=ResolvedJD("jd text", "workday")),
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
    assert row["filter_reason"] == "location"
