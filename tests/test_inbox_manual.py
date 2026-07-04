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
