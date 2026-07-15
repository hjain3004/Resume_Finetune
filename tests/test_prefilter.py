from __future__ import annotations

import json

from src import db, prefilter
from src.eligibility import load_eligibility_config
from src.models import DiscoveredJob, ResolvedJD, Status


def _conn():
    return db.get_connection(":memory:")


def _job(title: str, location: str | None, url: str, *, jd_text: str | None = None) -> DiscoveredJob:
    return DiscoveredJob("Acme", title, location, url, "tracker_vansh", None)


def _insert_discovered(conn, title: str, location: str | None, url: str):
    db.insert_discovered(conn, [_job(title, location, url)])
    return db.get_by_url(conn, url)["id"]


def _insert_resolved(conn, title: str, location: str | None, jd_text: str, url: str):
    row_id = _insert_discovered(conn, title, location, url)
    db.mark_resolved(conn, row_id, ResolvedJD(jd_text, "greenhouse"))
    return row_id


def test_pre_resolution_gate_filters_explicit_non_us_before_resolution() -> None:
    conn = _conn()
    row_id = _insert_discovered(conn, "Software Engineer", "Remote - Canada", "https://example.com/ca")

    summary = prefilter.run_pre_resolution_gate(conn, load_eligibility_config())

    row = conn.execute("SELECT status, filter_reason FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert summary.evaluated == 1
    assert summary.filtered == 1
    assert summary.by_reason == (("eligibility:country", 1),)
    assert row["status"] == Status.FILTERED_OUT
    assert row["filter_reason"] == "eligibility:country"


def test_pre_resolution_gate_filters_disabled_type_and_out_of_window_internship() -> None:
    conn = _conn()
    coop_id = _insert_discovered(conn, "Software Engineer Co-op", "New York, NY", "https://example.com/coop")
    summer_id = _insert_discovered(conn, "Software Engineering Intern", "New York, NY", "https://example.com/summer")
    conn.execute("UPDATE jobs SET title = ? WHERE id = ?", ("Software Engineering Intern Summer 2027", summer_id))
    conn.commit()

    summary = prefilter.run_pre_resolution_gate(conn, load_eligibility_config())

    rows = {
        row["id"]: row
        for row in conn.execute("SELECT id, status, filter_reason FROM jobs ORDER BY id").fetchall()
    }
    assert summary.filtered == 2
    assert rows[coop_id]["filter_reason"] == "eligibility:opportunity_type"
    assert rows[summer_id]["filter_reason"] == "eligibility:start_window"


def test_pre_resolution_gate_defers_unknown_evidence() -> None:
    conn = _conn()
    row_id = _insert_discovered(conn, "Software Engineer", "Remote", "https://example.com/remote")

    summary = prefilter.run_pre_resolution_gate(conn, load_eligibility_config())

    row = conn.execute("SELECT status, filter_reason FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert summary.deferred == 1
    assert row["status"] == Status.DISCOVERED
    assert row["filter_reason"] is None


def test_post_resolution_gate_filters_and_flags_authoritative_decisions() -> None:
    conn = _conn()
    no_sponsor = _insert_resolved(
        conn,
        "Software Engineer",
        "New York, NY",
        "Starts in 2027. We are unable to sponsor visas.",
        "https://example.com/no-sponsor",
    )
    ambiguous = _insert_resolved(
        conn,
        "Software Engineer",
        "Remote",
        "Starts in 2027. Must be authorized to work in the US.",
        "https://example.com/ambiguous",
    )

    summary = prefilter.run_post_resolution_gate(conn, load_eligibility_config())

    filtered = conn.execute("SELECT status, filter_reason FROM jobs WHERE id = ?", (no_sponsor,)).fetchone()
    flagged = conn.execute("SELECT status, flags FROM jobs WHERE id = ?", (ambiguous,)).fetchone()
    assert summary.filtered == 1
    assert summary.passed == 1
    assert filtered["status"] == Status.FILTERED_OUT
    assert filtered["filter_reason"] == "eligibility:work_authorization"
    assert set(json.loads(flagged["flags"])) == {
        "authorization_ambiguous",
        "country_unknown",
        "opportunity_type_inferred",
    }


def test_gates_are_idempotent_on_second_identical_run() -> None:
    conn = _conn()
    row_id = _insert_resolved(
        conn,
        "Software Engineer",
        "Remote",
        "Must be authorized to work in the US.",
        "https://example.com/flagged",
    )

    first = prefilter.run_post_resolution_gate(conn, load_eligibility_config())
    before = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (row_id,)).fetchone())
    second = prefilter.run_post_resolution_gate(conn, load_eligibility_config())
    after = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (row_id,)).fetchone())

    assert first.passed == 1
    assert second.filtered == 0
    assert second.by_flag == ()
    assert before == after
