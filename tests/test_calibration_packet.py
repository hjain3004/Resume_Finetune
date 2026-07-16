import json
from datetime import datetime, timezone

import pytest

from scripts import calibration_packet
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
