import json
import sqlite3

from scripts import export_batch


def _seed(conn: sqlite3.Connection, jd_text_k1: str = "short jd text") -> None:
    conn.executescript(
        f"""
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k1', 'Acme Inc', 'Backend Engineer', 'Remote', 'https://acme.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{jd_text_k1}');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status)
        VALUES ('k2', 'Beta Corp', 'Software Engineer', 'Remote', 'https://beta.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'DISCOVERED');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, filter_reason)
        VALUES ('k3', 'Gamma LLC', 'Senior Engineer', 'Remote', 'https://gamma.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'FILTERED_OUT', 'title_exclude');
        """
    )
    conn.commit()


def test_export_batch_includes_only_resolved_rows(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    _seed(conn)

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["company"] == "Acme Inc"
    assert data[0]["title"] == "Backend Engineer"
    assert data[0]["jd_text"] == "short jd text"
    assert set(data[0].keys()) == {"id", "company", "title", "jd_text"}


def test_export_batch_truncates_jd_text_to_6000_chars(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    long_jd = "x" * 10000
    _seed(conn, jd_text_k1=long_jd)

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data[0]["jd_text"]) == 6000


def test_export_batch_writes_to_date_named_file(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    _seed(conn)

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    assert path == tmp_path / "2026-07-05.json"
    assert path.exists()
