import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts import calibration_packet
from src import db
from src.calibration import parse_interest_worksheet, sha256_file


def _source_batch(tmp_path, count: int = 14):
    objects = [
        {
            "id": i,
            "row_ids": [i],
            "company": f"Company {i}",
            "title": f"Software Engineer {i}",
            "locations": ["Remote US"],
            "flags": [],
            "jd_quality": "ats",
            "jd_text": f"Full JD hidden from interest worksheet {i}",
        }
        for i in range(1, count + 1)
    ]
    path = tmp_path / "source.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def test_start_round_creates_default_12_packet_with_expected_names_and_hash(tmp_path):
    source = _source_batch(tmp_path, 14)
    out_dir = tmp_path / "calibration"

    batch_path, interest_path = calibration_packet.start_round(
        source,
        out_dir=out_dir,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )

    assert batch_path == out_dir / "2026-07-16.batch.json"
    assert interest_path == out_dir / "2026-07-16.interest.md"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    assert [obj["id"] for obj in batch] == list(range(1, 13))
    worksheet = parse_interest_worksheet(interest_path, require_complete=False)
    assert worksheet.metadata.batch_sha256 == sha256_file(batch_path)
    assert len(worksheet.labels) == 12
    assert "Full JD hidden" not in interest_path.read_text(encoding="utf-8")


def test_start_round_supports_explicit_limit_round_and_prints_summary(tmp_path, capsys):
    source = _source_batch(tmp_path, 4)
    exit_code = calibration_packet.main(
        ["start", str(source), "--out-dir", str(tmp_path / "out"), "--round", "custom", "--limit", "2"]
    )

    assert exit_code == 0
    assert (tmp_path / "out" / "custom.batch.json").exists()
    assert (tmp_path / "out" / "custom.interest.md").exists()
    output = capsys.readouterr().out
    assert "Wrote calibration batch:" in output
    assert "Wrote interest worksheet:" in output
    assert "Canonical jobs: 2" in output


def test_start_round_rejects_invalid_batch_without_traceback(tmp_path, capsys):
    bad_source = tmp_path / "bad.json"
    bad_source.write_text("{}", encoding="utf-8")

    exit_code = calibration_packet.main(["start", str(bad_source), "--out-dir", str(tmp_path / "out")])

    assert exit_code == 2
    assert "Calibration packet rejected:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_start_round_rejects_insufficient_jobs_without_outputs(tmp_path, capsys):
    source = _source_batch(tmp_path, 1)

    exit_code = calibration_packet.main(["start", str(source), "--out-dir", str(tmp_path / "out"), "--limit", "2"])

    assert exit_code == 2
    assert "Calibration packet rejected:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("existing_name", ["fixed.batch.json", "fixed.interest.md"])
def test_start_round_refuses_overwrite_and_leaves_directory_unchanged(tmp_path, existing_name):
    source = _source_batch(tmp_path, 4)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / existing_name
    existing.write_text("pre-existing", encoding="utf-8")
    before = sorted(path.name for path in out_dir.iterdir())

    with pytest.raises(FileExistsError):
        calibration_packet.start_round(source, out_dir=out_dir, round_name="fixed", limit=2)

    assert existing.read_text(encoding="utf-8") == "pre-existing"
    assert sorted(path.name for path in out_dir.iterdir()) == before


def test_start_round_rolls_back_batch_if_interest_write_fails(tmp_path, monkeypatch):
    source = _source_batch(tmp_path, 4)
    out_dir = tmp_path / "out"
    calls = []
    real_atomic_write_text = calibration_packet.calibration.atomic_write_text

    def flaky_atomic_write(path, text):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("boom")
        real_atomic_write_text(path, text)

    monkeypatch.setattr(calibration_packet.calibration, "atomic_write_text", flaky_atomic_write)

    with pytest.raises(OSError, match="boom"):
        calibration_packet.start_round(source, out_dir=out_dir, round_name="fixed", limit=2)

    assert not (out_dir / "fixed.batch.json").exists()
    assert not (out_dir / "fixed.interest.md").exists()


def _complete_interest_calls(path):
    text = path.read_text(encoding="utf-8")
    text = text.replace("| ats |  |  |", "| ats | APPLY | note |", 1)
    text = text.replace("| ats |  |  |", "| ats | MAYBE | note |", 1)
    path.write_text(text, encoding="utf-8")


def _temp_jobs_db(tmp_path, rows):
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    for row in rows:
        conn.execute(
            """
            INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, jd_text)
            VALUES (?, ?, ?, ?, 'Remote', ?, 'tracker_vansh', '2026-07-16T00:00:00+00:00', 'RESOLVED', ?)
            """,
            (row["id"], f"k{row['id']}", row["company"], row["title"], f"https://example.com/{row['id']}", row["jd_text"]),
        )
    conn.commit()
    conn.close()
    return db_path


def test_reveal_fit_reads_complete_jds_readonly_and_refuses_partial_outputs(tmp_path):
    source = _source_batch(tmp_path, 2)
    batch_path, interest_path = calibration_packet.start_round(source, out_dir=tmp_path / "out", round_name="round", limit=2)
    _complete_interest_calls(interest_path)
    before_batch = batch_path.read_bytes()
    rows = json.loads(batch_path.read_text(encoding="utf-8"))
    long_jd = "Complete long JD " + ("x" * 10_000)
    db_path = _temp_jobs_db(
        tmp_path,
        [
            {"id": rows[0]["id"], "company": rows[0]["company"], "title": rows[0]["title"], "jd_text": long_jd},
            {"id": rows[1]["id"], "company": rows[1]["company"], "title": rows[1]["title"], "jd_text": "Second complete JD"},
        ],
    )
    before_db = db_path.read_bytes()

    fit_path = calibration_packet.reveal_fit(interest_path, db_path=db_path)

    assert fit_path == interest_path.with_name("round.fit.md")
    assert "x" * 10_000 in fit_path.read_text(encoding="utf-8")
    assert db_path.read_bytes() == before_db
    assert batch_path.read_bytes() == before_batch


def test_reveal_fit_rejects_incomplete_interest_and_missing_db_without_creating_output(tmp_path):
    source = _source_batch(tmp_path, 2)
    _, interest_path = calibration_packet.start_round(source, out_dir=tmp_path / "out", round_name="round", limit=2)
    missing_db = tmp_path / "missing.db"

    with pytest.raises(Exception, match="interest_call"):
        calibration_packet.reveal_fit(interest_path, db_path=missing_db)

    assert not missing_db.exists()
    assert not interest_path.with_name("round.fit.md").exists()


def test_reveal_cli_reports_concise_errors(tmp_path, capsys):
    source = _source_batch(tmp_path, 2)
    _, interest_path = calibration_packet.start_round(source, out_dir=tmp_path / "out", round_name="round", limit=2)

    exit_code = calibration_packet.main(["reveal", str(interest_path), "--db", str(tmp_path / "missing.db")])

    assert exit_code == 2
    assert "Calibration packet rejected:" in capsys.readouterr().err
