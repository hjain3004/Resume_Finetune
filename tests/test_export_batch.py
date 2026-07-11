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


def test_export_batch_collapses_high_similarity_pair_with_different_titles(tmp_path):
    """M7 I3 fix, 2026-07-12: check_i3 flags same-company pairs with Jaccard
    content similarity >= 0.85 even when titles differ exactly. Live evidence:
    Cisco ids 119/164, "...Systems I (Full Time)" vs "...Systems 1", similarity
    0.884 — the same posting discovered twice, worded slightly differently,
    with a title variant that doesn't match exactly. _cluster_rows() had no
    merge path for this (M6.6 removed the Jaccard signal in favor of exact
    title match); restoring it as an additional signal closes the gap. See
    DECISIONS.md."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    jd_a = (
        "Software Engineer Data AI Intelligent Systems role building large scale "
        "distributed machine learning platforms used by millions of customers "
        "across our global cloud infrastructure and networking products full time position"
    )
    jd_b = (
        "Software Engineer Data AI Intelligent Systems role building large scale "
        "distributed machine learning platforms used by millions of customers "
        "across our global cloud infrastructure and networking products"
    )
    similarity = export_batch.jaccard_similarity(export_batch._shingles(jd_a), export_batch._shingles(jd_b))
    assert similarity >= 0.85

    conn.execute(
        "INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text) "
        "VALUES ('k1', 'Cisco', 'Software Engineer Data/AI/Intelligent Systems I (Full Time)', 'Austin, TX', "
        "'https://careers.cisco.com/global/en/job/2000073/x', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', ?)",
        (jd_a,),
    )
    conn.execute(
        "INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text) "
        "VALUES ('k2', 'Cisco', 'Software Engineer Data/AI/Intelligent Systems 1', 'Boston, MA', "
        "'https://careers.cisco.com/global/en/job/2000073', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', ?)",
        (jd_b,),
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 1
    assert sorted(data[0]["row_ids"]) == [1, 2]


def test_export_batch_does_not_merge_different_roles_at_same_company(tmp_path):
    """Negative case for the M7 I3 fix: two genuinely different roles at the
    same company, sharing a boilerplate company-description paragraph, must
    stay below the 0.85 threshold and NOT merge. Guards against the Jaccard
    signal over-merging distinct postings that happen to share a lot of
    company boilerplate text."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from src.db import init_db

    init_db(conn)
    boilerplate = (
        "Cisco powers the internet and helps customers reimagine applications "
        "secure their enterprise transform infrastructure and meet sustainability "
        "goals as part of our commitment to a more inclusive future for all."
    )
    jd_backend = (
        f"{boilerplate} We are hiring a backend software engineer to design and "
        "scale distributed microservices handling billions of API requests daily "
        "using Java, Kafka, and Kubernetes across our data center fabric."
    )
    jd_frontend = (
        f"{boilerplate} We are hiring a frontend software engineer to build "
        "accessible React and TypeScript interfaces for our network management "
        "dashboard used by enterprise customers worldwide."
    )
    similarity = export_batch.jaccard_similarity(
        export_batch._shingles(jd_backend), export_batch._shingles(jd_frontend)
    )
    assert similarity < 0.85

    conn.execute(
        "INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text) "
        "VALUES ('k1', 'Cisco', 'Backend Software Engineer', 'Remote', "
        "'https://careers.cisco.com/global/en/job/3000001', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', ?)",
        (jd_backend,),
    )
    conn.execute(
        "INSERT INTO jobs (dedup_key, company, title, location, url, source, discovered_at, status, jd_text) "
        "VALUES ('k2', 'Cisco', 'Frontend Software Engineer', 'Remote', "
        "'https://careers.cisco.com/global/en/job/3000002', 'tracker_vansh', '2026-07-05T00:00:00+00:00', 'RESOLVED', ?)",
        (jd_frontend,),
    )
    conn.commit()

    path = export_batch.export_batch(conn, base_dir=tmp_path, date_str="2026-07-05")

    data = json.loads(path.read_text())
    assert len(data) == 2
    assert sorted(d["row_ids"][0] for d in data) == [1, 2]
