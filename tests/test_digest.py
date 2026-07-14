import json
import sqlite3
from pathlib import Path

from src import digest
from src.audit import AuditResult, Finding


def _seed(conn: sqlite3.Connection) -> sqlite3.Row:
    conn.executescript(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, flags)
        VALUES ('k1', 'Beta Corp', 'Software Engineer New Grad', 'Remote', 'https://beta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', '["sponsorship_risk"]');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES ('k2', 'Acme Inc', 'Backend Engineer', 'San Francisco', 'https://acme.example/1', 'tracker_simplify', '2026-07-05T00:00:00+00:00', 'RESOLVED');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k3', 'Gamma LLC', 'Platform Engineer', 'Remote', 'https://gamma.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVE_FAILED', 3);

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, resolve_attempts)
        VALUES ('k4', 'Delta Co', 'Infra Engineer', 'Remote', 'https://delta.example/1', 'inbox', '2026-07-05T00:00:00+00:00', 'DISCOVERED', 1);

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, filter_reason)
        VALUES ('k5', 'Epsilon Ltd', 'Senior Software Engineer', 'Remote', 'https://epsilon.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'FILTERED_OUT', 'title_exclude');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_quality)
        VALUES ('k6', 'Zeta Inc', 'Software Engineer', 'Remote', 'https://jobright.ai/jobs/info/abc', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'SHORTLISTED', 'aggregator');

        INSERT INTO runs (id, started_at, finished_at, new_jobs, resolved, failed, filtered_out, tier1_resolved, tier2_resolved, manual_failed)
        VALUES (1, '2026-07-05T09:00:00+00:00', '2026-07-05T09:01:00+00:00', 5, 2, 1, 1, 1, 1, 1);

        INSERT INTO run_sources (run_id, source, discovered, inserted, resolved, failed)
        VALUES (1, 'inbox', 1, 1, 0, 1),
               (1, 'tracker_jobright', 1, 1, 0, 1),
               (1, 'tracker_simplify', 1, 1, 1, 0),
               (1, 'tracker_vansh', 2, 2, 1, 0);
        """
    )
    conn.commit()
    return conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()


EXPECTED = """\
# Job Digest — 2026-07-05

## Run summary
- Discovered: 5
- Resolved: 2
- Failed: 1
- Filtered out: 1
- Resolution tiers — t1: 1, t2: 1, manual: 1

### Per-source
| Source | Discovered | Inserted | Resolved | Failed |
|---|---|---|---|---|
| inbox | 1 | 1 | 0 | 1 |
| tracker_jobright | 1 | 1 | 0 | 1 |
| tracker_simplify | 1 | 1 | 1 | 0 |
| tracker_vansh | 2 | 2 | 1 | 0 |

## New & resolved
| Company | Title | Location | Flags | Source | Link |
|---|---|---|---|---|---|
| Acme Inc | Backend Engineer | San Francisco |  | tracker_simplify | [link](https://acme.example/1) |
| Beta Corp | Software Engineer New Grad | Remote | sponsorship_risk | tracker_vansh | [link](https://beta.example/1) |

## Needs your help
Paste the job description into `inbox/<name>.md` using the format in ARCHITECTURE.md §5.3 to resolve these manually.

| Company | Title | URL | Status |
|---|---|---|---|
| Delta Co | Infra Engineer | https://delta.example/1 | retrying (1/3 attempts) |
| Gamma LLC | Platform Engineer | https://gamma.example/1 | failed (3/3 attempts) |

### Needs the original posting

These shortlisted rows only have an aggregator's summary, not the employer's literal
wording. Drop the real posting URL into `inbox/urls.txt` before tailoring.

| Company | Title | Aggregator URL |
|---|---|---|
| Zeta Inc | Software Engineer | https://jobright.ai/jobs/info/abc |

## Filtered out
- Epsilon Ltd — Senior Software Engineer (title_exclude)
"""


def test_build_digest_matches_golden_markdown():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert text == EXPECTED


def test_write_digest_creates_file(tmp_path):
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)

    path = digest.write_digest(conn, run_row, base_dir=tmp_path, date_str="2026-07-05")

    assert path == tmp_path / "2026-07-05.md"
    assert path.read_text() == EXPECTED


def test_build_digest_shows_recycled_and_reopened_rows():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, flags, notes)
        VALUES ('k7', 'Theta Inc', 'Backend Engineer', 'Remote', 'https://theta.example/1', 'tracker_vansh',
                '2026-07-05T00:00:00+00:00', 'RESOLVED', '["repost"]',
                'recycled: you skipped job #5 (FILTERED_OUT) on 2026-06-01')
        """
    )
    conn.commit()

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "## Recycled & reopened" in text
    assert "Theta Inc" in text
    assert "recycled: you skipped job #5 (FILTERED_OUT) on 2026-06-01" in text


def test_build_digest_omits_recycled_section_when_no_matching_rows():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "## Recycled & reopened" not in text


def test_build_digest_shows_closed_rows():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, notes)
        VALUES ('k8', 'Iota LLC', 'Platform Engineer', 'Remote', 'https://iota.example/1', 'tracker_vansh',
                '2026-07-05T00:00:00+00:00', 'CLOSED', 'liveness recheck: 404 on https://iota.example/1')
        """
    )
    conn.commit()

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "## Closed (dead links)" in text
    assert "Iota LLC" in text
    assert "liveness recheck: 404" in text


def test_build_digest_omits_closed_section_when_no_closed_rows():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "## Closed (dead links)" not in text


def test_audit_section_lists_every_finding():
    result = AuditResult(
        findings=[
            Finding(invariant="I1", status="PASS", evidence=[]),
            Finding(invariant="I4", status="FAIL", evidence=[{"id": 1}, {"id": 2}]),
        ],
        overall="FAIL",
    )
    section = digest._audit_section(result)
    assert "I1" in section and "PASS" in section
    assert "I4" in section and "FAIL" in section and "2" in section


def test_build_digest_omits_audit_section_when_no_result_given():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "## Audit" not in text
    assert text == EXPECTED


def test_build_digest_shows_run_warnings_from_structured_notes():
    import src.db as db

    conn = db.get_connection(":memory:")
    _seed(conn)
    conn.execute(
        "UPDATE runs SET notes = ? WHERE id = 1",
        (
            json.dumps(
                {
                    "discovery_issues": [
                        {
                            "source": "tracker_simplify",
                            "stage": "fetch",
                            "error_type": "RuntimeError",
                            "message": "boom",
                        }
                    ]
                }
            ),
        ),
    )
    conn.commit()
    run_row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()

    text = digest.build_digest(conn, run_row, date_str="2026-07-05")

    assert "### Run warnings" in text
    assert "- tracker_simplify [fetch/RuntimeError]: boom" in text


def test_build_digest_shows_fail_banner_and_suppresses_new_and_resolved_when_audit_fails():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)
    audit_result = AuditResult(findings=[Finding(invariant="I4", status="FAIL", evidence=[{"id": 1}])], overall="FAIL")

    text = digest.build_digest(conn, run_row, date_str="2026-07-05", audit_result=audit_result)

    assert "AUDIT FAILURES" in text
    assert "Acme Inc" not in text.split("## New & resolved")[1].split("## Needs your help")[0]
    assert "## Audit" in text
    assert "I4" in text and "FAIL" in text


def test_build_digest_shows_new_and_resolved_when_audit_passes():
    import src.db as db

    conn = db.get_connection(":memory:")
    run_row = _seed(conn)
    audit_result = AuditResult(findings=[Finding(invariant="I1", status="PASS", evidence=[])], overall="PASS")

    text = digest.build_digest(conn, run_row, date_str="2026-07-05", audit_result=audit_result)

    assert "AUDIT FAILURES" not in text
    assert "Acme Inc" in text
    assert "## Audit" in text
