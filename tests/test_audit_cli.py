import json
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from scripts import audit as audit_cli
from src import db

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated_repo_root(tmp_path):
    """Build a repo-root-like directory containing only the config/docs the
    audit's static checks (I4, I5, I12) need, WITHOUT the real repo's
    data/batch/ directory. This keeps I3/I4/I5 (which read data/batch/*.json)
    vacuously PASSing (no batch file present) instead of scanning the real,
    intentionally-archived data/batch/2026-07-06.json fixture.
    """
    isolated_root = tmp_path / "isolated_repo"
    shutil.copytree(_REPO_ROOT / "config", isolated_root / "config")
    docs_dir = isolated_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(_REPO_ROOT / "docs" / "scoring_prompt.md", docs_dir / "scoring_prompt.md")
    return isolated_root


def test_main_writes_audit_json_and_returns_zero_on_pass(tmp_path, isolated_repo_root):
    db_path = tmp_path / "jobs.db"
    conn = db.get_connection(str(db_path))
    conn.close()
    out_dir = tmp_path / "audit"

    code = audit_cli.main(
        ["--db", str(db_path), "--out-dir", str(out_dir), "--repo-root", str(isolated_repo_root)]
    )

    assert code == 0
    out_files = list(out_dir.glob("*.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text())
    assert payload["overall"] == "PASS"
    assert len(payload["findings"]) == 15


def test_diff_permitted_drift_cli_mode(tmp_path):
    before_path = tmp_path / "before.db"
    after_path = tmp_path / "after.db"
    conn_before = db.get_connection(str(before_path))
    from src.models import DiscoveredJob

    db.insert_discovered(
        conn_before,
        [DiscoveredJob("Acme", "Backend Engineer", "Remote", "https://acme.example/1", "tracker_vansh", None)],
    )
    conn_before.close()

    import shutil
    shutil.copy(before_path, after_path)

    code = audit_cli.main(["--db-before", str(before_path), "--db-after", str(after_path)])

    assert code == 0


def test_diff_permitted_drift_cli_mode_fails_on_unpermitted_change(tmp_path):
    before_path = tmp_path / "before.db"
    after_path = tmp_path / "after.db"
    conn_before = db.get_connection(str(before_path))
    from src.models import DiscoveredJob

    db.insert_discovered(
        conn_before,
        [DiscoveredJob("Acme", "Backend Engineer", "Remote", "https://acme.example/1", "tracker_vansh", None)],
    )
    conn_before.close()

    import shutil
    shutil.copy(before_path, after_path)
    conn_after = sqlite3.connect(str(after_path))
    conn_after.execute("UPDATE jobs SET status = 'FILTERED_OUT'")
    conn_after.commit()
    conn_after.close()

    code = audit_cli.main(["--db-before", str(before_path), "--db-after", str(after_path)])

    assert code == 1


def test_audit_runs_under_10s_on_10k_rows(tmp_path, isolated_repo_root):
    db_path = tmp_path / "jobs.db"
    conn = db.get_connection(str(db_path))
    rows = [
        f"('k{i}', 'CompanyX{i}', 'Software Engineer X{i}', 'Remote', 'https://example{i}.com/job', "
        f"'tracker_vansh', '2026-07-01T00:00:00+00:00', 'RESOLVED', 'Backend engineering building distributed systems in Java and Kafka.')"
        for i in range(10_000)
    ]
    conn.executescript(
        "INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text) VALUES "
        + ",".join(rows) + ";"
    )
    conn.commit()
    conn.close()

    start = time.monotonic()
    code = audit_cli.main(
        ["--db", str(db_path), "--out-dir", str(tmp_path / "audit"), "--repo-root", str(isolated_repo_root)]
    )
    elapsed = time.monotonic() - start

    assert code == 0
    assert elapsed < 10.0
