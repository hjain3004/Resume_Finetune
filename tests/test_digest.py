import json
import sqlite3
from pathlib import Path

from src import digest


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

        INSERT INTO runs (id, started_at, finished_at, new_jobs, resolved, failed, filtered_out)
        VALUES (1, '2026-07-05T09:00:00+00:00', '2026-07-05T09:01:00+00:00', 5, 2, 1, 1);

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
