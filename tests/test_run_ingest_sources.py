"""Per-source observability (PHASE2_KICKOFF.md M6.0(3)): a source that
contributes zero rows must still show up as a visible zero in run_sources,
not silently vanish — this is the exact shape of the tracker_simplify bug."""

import json
from unittest.mock import patch

from src import db, run_ingest
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD


def _run(db_path, jobs, *, resolve_result=None, digest_dir=None, audit_dir=None):
    with (
        patch.object(run_ingest, "discover_all", return_value=list(jobs)),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(
            run_ingest.resolve, "resolve", return_value=resolve_result or ResolvedJD("jd", "fixture")
        ),
    ):
        args = ["--db", db_path]
        if digest_dir is not None:
            args += ["--digest-dir", digest_dir]
        if audit_dir is not None:
            args += ["--audit-dir", audit_dir]
        run_ingest.main(args)


def test_zero_discovery_source_is_recorded_not_silently_absent(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    jobs = [
        DiscoveredJob(
            "Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1",
            "tracker_vansh", None,
        )
    ]
    with patch(
        "src.run_ingest.load_sources_config",
        return_value={
            "tracker_vansh": {"enabled": True},
            "tracker_simplify": {"enabled": True},
        },
    ):
        _run(db_path, jobs, digest_dir=str(tmp_path / "digests"), audit_dir=str(tmp_path / "audit"))

    conn = db.get_connection(db_path)
    run_id = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    rows = {row["source"]: dict(row) for row in db.run_sources_for_run(conn, run_id)}

    assert rows["tracker_vansh"]["discovered"] == 1
    assert rows["tracker_vansh"]["resolved"] == 1
    assert "tracker_simplify" in rows
    assert rows["tracker_simplify"]["discovered"] == 0
    assert rows["tracker_simplify"]["inserted"] == 0


def test_full_run_writes_audit_json(tmp_path):
    """docs/SELF_HEALING.md §1: the audit runs automatically at the end of
    every pipeline run and writes data/audit/YYYY-MM-DD.json. Uses a
    tmp_path-scoped --audit-dir so the test never touches the real
    data/audit/ directory."""
    from datetime import datetime, timezone

    db_path = str(tmp_path / "jobs.db")
    audit_dir = tmp_path / "audit"
    jobs = [
        DiscoveredJob(
            "Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1",
            "tracker_vansh", None,
        )
    ]
    with patch(
        "src.run_ingest.load_sources_config",
        return_value={"tracker_vansh": {"enabled": True}},
    ):
        _run(
            db_path, jobs,
            digest_dir=str(tmp_path / "digests"),
            audit_dir=str(audit_dir),
        )

    today = datetime.now(timezone.utc).date().isoformat()
    audit_path = audit_dir / f"{today}.json"
    assert audit_path.exists()
    payload = json.loads(audit_path.read_text())
    assert set(payload.keys()) >= {"date", "overall", "findings"}
    assert payload["date"] == today
    assert payload["overall"] in {"PASS", "WARN", "FAIL"}
    assert isinstance(payload["findings"], list)
