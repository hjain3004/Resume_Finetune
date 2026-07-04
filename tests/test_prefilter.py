import sqlite3

import pytest

from src import db, prefilter
from src.models import DiscoveredJob, ResolvedJD, Status

CONFIG = {
    "title_include": [
        "software|swe|backend|back.end|full.?stack|platform|infrastructure|distributed",
        "new.?grad|early.?career|university|entry.?level|graduate|2026|2027",
    ],
    "title_exclude": [
        "senior|staff|principal|lead|manager|director|intern(ship)?\\b",
        r"\b(7|8|9|10)\+?\s*years",
    ],
    "location_allow": [
        "united states|usa|remote|san jose|san francisco|bay area|seattle|austin|new york",
    ],
    "jd_flags": {
        "sponsorship_risk": [
            "unable to sponsor|not.{0,20}sponsor|no visa|citizens? only|clearance required|US citizenship",
        ],
    },
    "years_cap": 3,
}


@pytest.mark.parametrize(
    "title,location,jd_text,expect_filtered,expect_reason_contains",
    [
        ("Software Engineer I", "Remote", "", False, None),
        ("Senior Software Engineer", "Remote", "", True, "title_exclude"),
        ("Software Engineering Intern", "Remote", "", True, "title_exclude"),
        ("Staff Engineer, New Grad", "Remote", "", True, "title_exclude"),
        ("Software Engineer, New Grad 2026", "Remote", "", False, None),
        ("Senior New Grad Program", "Remote", "", True, "title_exclude"),
        ("Product Manager", "Remote", "", True, "title_include"),
        ("Software Engineer New Grad", "Toronto, Canada", "", True, "location"),
        ("Software Engineer New Grad", "", "", True, "location"),
        ("Software Engineer New Grad", "Remote", "minimum 5 years of experience required", True, "yoe:5"),
        ("Software Engineer New Grad", "Remote", "5 years is a plus", False, None),
        ("Software Engineer New Grad", "Remote", "7+ years required", True, "yoe:7"),
    ],
)
def test_evaluate_title_location_years_cases(
    title, location, jd_text, expect_filtered, expect_reason_contains
):
    result = prefilter.evaluate(title, location, jd_text, CONFIG)
    assert result.filtered is expect_filtered
    if expect_reason_contains:
        assert expect_reason_contains in result.reason
    else:
        assert result.reason is None


def test_evaluate_sponsorship_flag_does_not_filter():
    result = prefilter.evaluate(
        "Software Engineer New Grad",
        "Remote",
        "We are unable to sponsor visas at this time.",
        CONFIG,
    )
    assert result.filtered is False
    assert result.reason is None
    assert "sponsorship_risk" in result.flags


def test_evaluate_no_flags_when_no_jd_flag_phrases_present():
    result = prefilter.evaluate("Software Engineer New Grad", "Remote", "great team culture", CONFIG)
    assert result.flags == []


def _conn():
    return db.get_connection(":memory:")


def _insert_resolved(conn, title, location, jd_text, url="https://boards.greenhouse.io/acme/jobs/1"):
    db.insert_discovered(conn, [DiscoveredJob("Acme", title, location, url, "tracker_vansh", None)])
    row_id = db.get_by_url(conn, url)["id"]
    db.mark_resolved(conn, row_id, ResolvedJD(jd_text, "greenhouse"))
    return row_id


def test_run_prefilter_marks_filtered_out_rows():
    conn = _conn()
    row_id = _insert_resolved(conn, "Senior Software Engineer", "Remote", "")

    filtered_count = prefilter.run_prefilter(conn, CONFIG)

    assert filtered_count == 1
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == Status.FILTERED_OUT
    assert "title_exclude" in row["filter_reason"]
    assert row["jd_text"] == ""


def test_run_prefilter_sets_flags_and_keeps_resolved():
    conn = _conn()
    row_id = _insert_resolved(
        conn, "Software Engineer New Grad", "Remote", "unable to sponsor visas"
    )

    filtered_count = prefilter.run_prefilter(conn, CONFIG)

    assert filtered_count == 0
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == Status.RESOLVED
    assert "sponsorship_risk" in row["flags"]


def test_run_prefilter_skips_rows_with_existing_filter_reason():
    conn = _conn()
    row_id = _insert_resolved(conn, "Software Engineer New Grad", "Remote", "")
    conn.execute(
        "UPDATE jobs SET status = ?, filter_reason = ? WHERE id = ?",
        (Status.FILTERED_OUT, "manual_reason", row_id),
    )
    conn.commit()

    filtered_count = prefilter.run_prefilter(conn, CONFIG)

    assert filtered_count == 0
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert row["filter_reason"] == "manual_reason"


def test_run_prefilter_only_processes_resolved_rows():
    conn = _conn()
    db.insert_discovered(
        conn,
        [DiscoveredJob("Acme", "Software Engineer New Grad", "Remote", "https://example.com/1", "tracker_vansh", None)],
    )

    filtered_count = prefilter.run_prefilter(conn, CONFIG)

    assert filtered_count == 0
    row = db.get_by_url(conn, "https://example.com/1")
    assert row["status"] == Status.DISCOVERED
