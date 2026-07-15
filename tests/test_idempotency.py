"""The idempotency test: running the full default pipeline twice back-to-back
must not mutate the jobs table a second time (ARCHITECTURE §9's requirement),
other than the `runs` row itself, legitimate resolve retries, and M6.8's
last_seen_at/repost_count — those are DESIGNED to change on every rediscovery
of a still-active posting (docs/PHASE2_KICKOFF.md M6.8 item 2: "on dedup-key
conflict: update last_seen_at, increment repost_count"), so a second run
discovering the same still-open postings is expected to touch them."""

from unittest.mock import patch

from src import db, run_ingest
from src.eligibility import load_eligibility_config
from src.discover.base import DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD
from src import prefilter

FIXED_JOBS = [
    DiscoveredJob(
        "Acme", "Software Engineer New Grad", "Remote",
        "https://boards.greenhouse.io/acme/jobs/1", "tracker_vansh", None,
    ),
    DiscoveredJob(
        "Beta", "Senior Software Engineer", "Remote",
        "https://jobs.lever.co/beta/2", "tracker_simplify", None,
    ),
]


def _resolve_side_effect(url, session, **kwargs):
    return ResolvedJD(jd_text="5 years is a plus, not required.", resolver="fixture")


def _run_pipeline(db_path: str, digest_dir: str, audit_dir: str) -> int:
    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult(tuple(FIXED_JOBS), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest.resolve, "resolve", side_effect=_resolve_side_effect),
    ):
        return run_ingest.main(
            ["--db", db_path, "--digest-dir", digest_dir, "--audit-dir", audit_dir]
        )


def test_full_pipeline_run_twice_is_idempotent(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    digest_dir = str(tmp_path / "digests")
    audit_dir = str(tmp_path / "audit")

    assert _run_pipeline(db_path, digest_dir, audit_dir) == 0
    conn = db.get_connection(db_path)
    first_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert first_run["new_jobs"] == 2
    rows_after_first = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()]
    conn.close()

    assert _run_pipeline(db_path, digest_dir, audit_dir) == 0
    conn = db.get_connection(db_path)
    second_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert second_run["new_jobs"] == 0
    rows_after_second = [dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()]
    conn.close()

    permitted_drift = {"last_seen_at", "repost_count"}
    strip_permitted = lambda rows: [
        {k: v for k, v in row.items() if k not in permitted_drift} for row in rows
    ]
    assert strip_permitted(rows_after_second) == strip_permitted(rows_after_first)
    # but the drift itself must be exactly the M6.8-documented kind: every
    # still-active row seen again bumps repost_count by 1 and refreshes
    # last_seen_at, nothing more.
    for before, after in zip(rows_after_first, rows_after_second):
        assert after["repost_count"] == before["repost_count"] + 1
        assert after["last_seen_at"] > before["last_seen_at"]


def test_eligibility_gate_flow_twice_is_idempotent():
    conn = db.get_connection(":memory:")
    jobs = [
        DiscoveredJob("CA Co", "Software Engineer", "Remote - Canada", "https://example.com/ca", "tracker_vansh", None),
        DiscoveredJob("Unknown Co", "Software Engineer", "Remote", "https://example.com/unknown", "tracker_vansh", None),
        DiscoveredJob("FT Co", "Software Engineer", "New York, NY", "https://example.com/ft", "tracker_vansh", None),
        DiscoveredJob("Intern Co", "Software Engineering Intern", "New York, NY", "https://example.com/intern", "tracker_vansh", None),
        DiscoveredJob("Sponsor Co", "Software Engineer", "New York, NY", "https://example.com/sponsor", "tracker_vansh", None),
        DiscoveredJob("No Start Co", "Software Engineer", "Austin, Texas", "https://example.com/no-start", "tracker_vansh", None),
    ]
    db.insert_discovered(conn, jobs)
    for url, jd in {
        "https://example.com/unknown": "Starts in 2027.",
        "https://example.com/ft": "New Grad 2027.",
        "https://example.com/intern": "Spring 2027 internship.",
        "https://example.com/sponsor": "Starts in 2027. Unable to sponsor visas.",
        "https://example.com/no-start": "Build backend systems.",
    }.items():
        row = db.get_by_url(conn, url)
        db.mark_resolved(conn, row["id"], ResolvedJD(jd, "fixture"))

    config = load_eligibility_config()
    prefilter.run_pre_resolution_gate(conn, config)
    prefilter.run_post_resolution_gate(conn, config)
    first = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]

    prefilter.run_pre_resolution_gate(conn, config)
    prefilter.run_post_resolution_gate(conn, config)
    second = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]

    assert second == first
