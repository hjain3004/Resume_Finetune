from src import db
from src.discover import inbox_manual
from src.models import Status


def _make_inbox(tmp_path):
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    return inbox_dir


def test_ingest_url_and_paste_file(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    (inbox_dir / "urls.txt").write_text(
        "# a comment\nhttps://example.com/careers/123\n"
    )
    (inbox_dir / "job1.md").write_text(
        "https://foo.com/jobs/42\n"
        "Foo Inc — Backend Engineer — Remote\n"
        "\n"
        "We are looking for a backend engineer with distributed systems experience.\n"
    )

    conn = db.get_connection(":memory:")
    result = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert result.new_urls == 1
    assert result.new_pastes == 1

    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 2

    paste_row = db.get_by_url(conn, "https://foo.com/jobs/42")
    assert paste_row["status"] == Status.RESOLVED
    assert paste_row["resolver"] == "manual"
    assert paste_row["company"] == "Foo Inc"
    assert paste_row["title"] == "Backend Engineer"
    assert paste_row["location"] == "Remote"
    assert "distributed systems" in paste_row["jd_text"]

    url_row = db.get_by_url(conn, "https://example.com/careers/123")
    assert url_row["status"] == Status.DISCOVERED
    assert url_row["company"] == "unknown"
    assert url_row["title"] == "example.com"

    assert not (inbox_dir / "job1.md").exists()
    assert (inbox_dir / "processed" / "job1.md").exists()
    assert (inbox_dir / "urls.txt").read_text().strip() == ""


def test_second_run_ingests_nothing_new(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    (inbox_dir / "urls.txt").write_text("https://example.com/careers/123\n")
    (inbox_dir / "job1.md").write_text(
        "https://foo.com/jobs/42\nFoo Inc — Backend Engineer — Remote\n\nJD text here.\n"
    )

    conn = db.get_connection(":memory:")
    inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    result = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})
    assert result.new_urls == 0
    assert result.new_pastes == 0
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 2


def test_malformed_paste_file_is_skipped_not_moved(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    (inbox_dir / "broken.md").write_text("just one line\n")

    conn = db.get_connection(":memory:")
    result = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert result.new_pastes == 0
    assert (inbox_dir / "broken.md").exists()
    assert not (inbox_dir / "processed").exists()


def test_dry_run_does_not_write_or_move_files(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    (inbox_dir / "urls.txt").write_text("https://example.com/careers/123\n")
    (inbox_dir / "job1.md").write_text(
        "https://foo.com/jobs/42\nFoo Inc — Backend Engineer — Remote\n\nJD text here.\n"
    )

    conn = db.get_connection(":memory:")
    result = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir), "dry_run": True})

    assert result.new_urls == 1
    assert result.new_pastes == 1
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 0
    assert (inbox_dir / "job1.md").exists()
    assert (inbox_dir / "urls.txt").read_text().strip() != ""


# --- M6.14 Safe Manual Inbox Tests ---

import pytest


def test_inbox_distinct_urls_on_same_hostname_create_distinct_rows(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    urls = [
        "https://www.revolut.com/en-US/careers/position/swe-1-3b79c804-b7e0-4b1a-9ef6-2fd69723dc7a/",
        "https://www.revolut.com/en-US/careers/position/swe-2-4c80d915-c8f1-5c2b-0fa7-3fe70834ed8b/",
    ]
    (inbox_dir / "urls.txt").write_text("\n".join(urls) + "\n")

    conn = db.get_connection(":memory:")
    res = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert res.new_urls == 2
    assert len(res.url_job_ids) == 2
    rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["id"] == res.url_job_ids[0]
    assert rows[1]["id"] == res.url_job_ids[1]
    assert rows[0]["dedup_key"] != rows[1]["dedup_key"]


def test_inbox_greenhouse_distinct_urls_create_distinct_rows(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    urls = [
        "https://job-boards.greenhouse.io/twitch/jobs/8623578002",
        "https://job-boards.greenhouse.io/twitch/jobs/8623578003",
        "https://job-boards.greenhouse.io/roblox/jobs/8623578004",
    ]
    (inbox_dir / "urls.txt").write_text("\n".join(urls) + "\n")

    conn = db.get_connection(":memory:")
    res = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert res.new_urls == 3
    assert len(res.url_job_ids) == 3
    rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
    assert len(rows) == 3


def test_inbox_duplicate_canonical_url_variants_create_one_row(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    urls = [
        "https://example.com/jobs/123?utm_source=linkedin",
        "https://example.com/jobs/123/",
    ]
    (inbox_dir / "urls.txt").write_text("\n".join(urls) + "\n")

    conn = db.get_connection(":memory:")
    res = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert res.new_urls == 1
    assert len(res.url_job_ids) == 1
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 1


def test_inbox_url_fragments_survive_and_comments_ignored(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    content = (
        "# Full line comment\n"
        "   # Indented comment\n"
        "https://careers.example.com/search#job/9999\n"
    )
    (inbox_dir / "urls.txt").write_text(content)

    conn = db.get_connection(":memory:")
    res = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert res.new_urls == 1
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["url"] == "https://careers.example.com/search#job/9999"


def test_inbox_sensitive_parameter_aborts_all_inserts_and_preserves_file(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    orig_content = (
        "https://example.com/job/valid1\n"
        "https://example.com/job/valid2?token=SUPER_SECRET_123\n"
    )
    (inbox_dir / "urls.txt").write_text(orig_content)

    conn = db.get_connection(":memory:")
    with pytest.raises(inbox_manual.InboxInputError) as excinfo:
        inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    # Secret is not leaked
    assert "SUPER_SECRET_123" not in str(excinfo.value)
    # Zero insertions
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    # File is preserved byte-identical
    assert (inbox_dir / "urls.txt").read_text() == orig_content


def test_inbox_sensitive_fragment_parameter_aborts(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    orig_content = "https://example.com/job#route?jwt=SECRET_TOKEN\n"
    (inbox_dir / "urls.txt").write_text(orig_content)

    conn = db.get_connection(":memory:")
    with pytest.raises(inbox_manual.InboxInputError) as excinfo:
        inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert "SECRET_TOKEN" not in str(excinfo.value)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert (inbox_dir / "urls.txt").read_text() == orig_content


def test_inbox_second_ingestion_is_idempotent_and_returns_job_ids(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    (inbox_dir / "urls.txt").write_text("https://example.com/careers/1\nhttps://example.com/careers/2\n")

    conn = db.get_connection(":memory:")
    res1 = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})
    assert res1.new_urls == 2
    assert res1.url_job_ids == (1, 2)

    # Re-write the same URLs to inbox
    (inbox_dir / "urls.txt").write_text("https://example.com/careers/1\nhttps://example.com/careers/2\n")
    res2 = inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})
    assert res2.new_urls == 0
    assert res2.url_job_ids == (1, 2)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_inbox_malformed_port_aborts_all_inserts_and_redacts_secret(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    secret = "PORT_SECRET_VAL_123"
    orig_content = f"https://example.com/valid/1\nhttps://example.com:{secret}/bad\nhttps://example.com/valid/2\n"
    (inbox_dir / "urls.txt").write_text(orig_content)

    conn = db.get_connection(":memory:")
    with pytest.raises(inbox_manual.InboxInputError) as excinfo:
        inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert secret not in str(excinfo.value)
    assert secret not in repr(excinfo.value)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert (inbox_dir / "urls.txt").read_text() == orig_content


def test_inbox_broken_ipv6_aborts_all_inserts(tmp_path):
    inbox_dir = _make_inbox(tmp_path)
    orig_content = "https://[broken-ipv6/job\n"
    (inbox_dir / "urls.txt").write_text(orig_content)

    conn = db.get_connection(":memory:")
    with pytest.raises(inbox_manual.InboxInputError):
        inbox_manual.ingest(conn, {"inbox_dir": str(inbox_dir)})

    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert (inbox_dir / "urls.txt").read_text() == orig_content
