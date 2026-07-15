"""M6.5: the browser_resolver toggle lives at the top level of
config/sources.yaml (sibling to `sources:`), and main() must thread it
through to resolve.resolve() and record the resulting tier counts."""

from unittest.mock import MagicMock, patch

from src import db, run_ingest
from src.discover.base import DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD


def test_load_browser_resolver_flag_reads_top_level_key(tmp_path):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text("browser_resolver: true\nsources:\n  tracker_vansh:\n    enabled: true\n")

    assert run_ingest.load_browser_resolver_flag(str(config_path)) is True


def test_load_browser_resolver_flag_defaults_to_false_when_absent(tmp_path):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text("sources:\n  tracker_vansh:\n    enabled: true\n")

    assert run_ingest.load_browser_resolver_flag(str(config_path)) is False


def test_main_passes_browser_resolver_toggle_to_resolve_and_records_tiers(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    jobs = [
        DiscoveredJob(
            "Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1", "tracker_vansh", None,
        )
    ]

    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult(tuple(jobs), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "load_browser_resolver_flag", return_value=True),
        patch.object(run_ingest, "Crawl4AIBrowserClient", return_value=MagicMock()),
        patch.object(run_ingest.resolve, "resolve", return_value=ResolvedJD("jd", "browser")) as mock_resolve,
    ):
        run_ingest.main([
            "--db", db_path,
            "--digest-dir", str(tmp_path / "digests"),
            "--audit-dir", str(tmp_path / "audit"),
        ])

    mock_resolve.assert_called_once_with(
        "https://boards.greenhouse.io/acme/jobs/1",
        mock_resolve.call_args.args[1],
        browser_resolver=True,
        browser_client=mock_resolve.call_args.kwargs["browser_client"],
    )
    assert mock_resolve.call_args.kwargs["browser_client"] is not None

    conn = db.get_connection(db_path)
    run_row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["tier1_resolved"] == 0
    assert run_row["tier2_resolved"] == 1
    assert run_row["manual_failed"] == 0
