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
    assert data[0]["row_ids"] == [data[0]["id"]]
    assert data[0]["locations"] == ["Remote"]
    assert data[0]["flags"] == []
    assert data[0]["jd_quality"] == "ats"
    assert set(data[0].keys()) == {"id", "row_ids", "company", "title", "jd_text", "locations", "flags", "jd_quality"}


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


def test_normalize_jd_strips_ago_line_and_collapses_whitespace():
    text = "Relativity · 3 hours ago\nWe build software.\n\n\nApply now."
    normalized = export_batch.normalize_jd(text)
    assert "hours ago" not in normalized
    assert "relativity" not in normalized
    assert normalized == "we build software. apply now."


def test_content_hash_equal_for_texts_differing_only_in_ago_line():
    text_a = "Relativity · 3 hours ago\nSame job description body."
    text_b = "Relativity · 9 hours ago\nSame job description body."
    assert export_batch.content_hash(text_a) == export_batch.content_hash(text_b)


def test_jaccard_similarity_high_for_near_identical_texts_low_for_unrelated():
    base = (
        "We are looking for a driven software engineer to design build and scale "
        "distributed backend systems handling millions of requests daily across "
        "our microservices platform"
    )
    near_dup = base + " Location: Austin, TX."
    unrelated = "Warehouse associate needed for logistics operations in Seattle warehouse fulfillment center shifts"

    a = export_batch._shingles(base)
    b = export_batch._shingles(near_dup)
    c = export_batch._shingles(unrelated)

    assert export_batch.jaccard_similarity(a, b) >= 0.85
    assert export_batch.jaccard_similarity(a, c) < 0.85


def test_export_batch_collapses_exact_content_duplicates(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k1', 'Relativity', 'Software Engineer', 'Chicago, IL', 'https://relativity.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Relativity · 3 hours ago\nBuild the future of legal tech.');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k2', 'Relativity', 'Software Engineer', 'Remote', 'https://relativity.example/2', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Relativity · 9 hours ago\nBuild the future of legal tech.');
        """
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 1
    assert sorted(data[0]["row_ids"]) == [1, 2]
    assert data[0]["id"] == 1


def test_export_batch_collapses_near_duplicate_by_title_similarity(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    base_jd = (
        "We are looking for a driven software engineer to design build and scale "
        "distributed backend systems handling millions of requests daily across "
        "our microservices platform"
    )
    conn.executescript(
        f"""
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k1', 'Neuralink', 'Software Engineer', 'Fremont, CA', 'https://neuralink.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{base_jd}');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k2', 'Neuralink', 'Software Engineer', 'Austin, TX', 'https://neuralink.example/2', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{base_jd} Location: Austin, TX.');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k3', 'Amazon', 'Warehouse Associate', 'Seattle, WA', 'https://amazon.example/1', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Warehouse associate needed for logistics operations in Seattle.');
        """
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 2
    neuralink_entry = next(d for d in data if d["company"] == "Neuralink")
    amazon_entry = next(d for d in data if d["company"] == "Amazon")
    assert sorted(neuralink_entry["row_ids"]) == [1, 2]
    assert amazon_entry["row_ids"] == [3]


def test_export_batch_locations_distinct_across_group_in_id_order(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    base_jd = (
        "We are looking for a driven software engineer to design build and scale "
        "distributed backend systems handling millions of requests daily across "
        "our microservices platform"
    )
    conn.executescript(
        f"""
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k1', 'Neuralink', 'Software Engineer', 'Fremont, CA', 'https://neuralink.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{base_jd}');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k2', 'Neuralink', 'Software Engineer', 'Austin, TX', 'https://neuralink.example/2', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{base_jd} Location: Austin, TX.');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k3', 'Neuralink', 'Software Engineer', 'Fremont, CA', 'https://neuralink.example/3', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', '{base_jd} Location: Fremont, CA.');
        """
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["locations"] == ["Fremont, CA", "Austin, TX"]


def test_export_batch_flags_and_jd_quality_come_from_representative_row(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text, flags, jd_quality)
        VALUES ('k1', 'Relativity', 'Software Engineer', 'Chicago, IL', 'https://relativity.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Relativity · 3 hours ago\nBuild the future of legal tech.', '["sponsor_likely"]', 'aggregator');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k2', 'Relativity', 'Software Engineer', 'Remote', 'https://relativity.example/2', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Relativity · 9 hours ago\nBuild the future of legal tech.');
        """
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["id"] == 1
    assert data[0]["flags"] == ["sponsor_likely"]
    assert data[0]["jd_quality"] == "aggregator"


def test_export_batch_collapses_same_title_even_below_similarity_threshold(tmp_path):
    """M6.6 regression: jobright generates a differently-worded AI summary per
    location for the same posting, so same-company+same-title rows can score
    well below the old 0.85 Jaccard gate. An exact title match within a
    company must still collapse them (see DECISIONS.md)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    conn.executescript(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k1', 'Neuralink', 'Software Engineer, BCI Applications', 'Fremont, CA', 'https://neuralink.example/1', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Neuralink is creating devices that enable a bi-directional interface with the brain to restore movement.');

        INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
        VALUES ('k2', 'Neuralink', 'Software Engineer, BCI Applications', 'Austin, TX', 'https://neuralink.example/2', 'tracker_jobright', '2026-07-05T00:00:00+00:00', 'RESOLVED', 'Join our team building implants that let paralyzed patients regain control over digital devices.');
        """
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert export_batch.jaccard_similarity(
        export_batch._shingles(
            "Neuralink is creating devices that enable a bi-directional interface with the brain to restore movement."
        ),
        export_batch._shingles(
            "Join our team building implants that let paralyzed patients regain control over digital devices."
        ),
    ) < 0.85
    assert len(data) == 1
    assert sorted(data[0]["row_ids"]) == [1, 2]
