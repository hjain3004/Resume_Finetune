import json
import sqlite3
from pathlib import Path

import pytest

from scripts import calibration_report
from src import db
from src.calibration import (
    BatchJob,
    CalibrationContractError,
    CalibrationStage,
    ComparisonKind,
    FullJD,
    RoundMetadata,
    batch_jobs_to_json,
    compare_fit_calls,
    load_scored_file,
    parse_calibration_worksheet,
    render_fit_worksheet,
    render_interest_worksheet,
    sha256_file,
)


def _jobs() -> tuple[BatchJob, ...]:
    return (
        BatchJob(1, (1,), "Acme", "Backend Engineer", ("Remote",), (), "ats", "truncated"),
        BatchJob(2, (2,), "Beta", "ML Engineer", ("NY",), ("authorization_ambiguous",), "ats", "truncated"),
        BatchJob(3, (3,), "Gamma", "Firmware Engineer", (), (), "aggregator", "truncated"),
    )


def _write_fit_round(tmp_path, *, fit_calls=("APPLY", "MAYBE", "SKIP"), interest_calls=("APPLY", "SKIP", "MAYBE")):
    jobs = _jobs()
    batch_path = tmp_path / "round.batch.json"
    batch_path.write_text(batch_jobs_to_json(jobs), encoding="utf-8")
    interest_meta = RoundMetadata(
        2,
        CalibrationStage.INTEREST,
        "round",
        batch_path,
        sha256_file(batch_path),
        3,
        "2026-07-16T00:00:00+00:00",
    )
    interest_text = render_interest_worksheet(interest_meta, jobs)
    for job, call in zip(jobs, interest_calls, strict=True):
        interest_text = interest_text.replace(f"| {job.jd_quality} |  |  |", f"| {job.jd_quality} | {call} | interest note {job.job_id} |", 1)
    interest_path = tmp_path / "round.interest.md"
    interest_path.write_text(interest_text, encoding="utf-8")
    interest = parse_calibration_worksheet(interest_path, require_complete=False)
    fit_meta = RoundMetadata(
        2,
        CalibrationStage.FIT,
        "round",
        batch_path,
        sha256_file(batch_path),
        3,
        "2026-07-16T01:00:00+00:00",
        interest_path,
        sha256_file(interest_path),
    )
    full_jds = tuple(FullJD(job.job_id, job.company, job.title, f"Complete JD {job.job_id}") for job in jobs)
    fit_text = render_fit_worksheet(fit_meta, interest, full_jds)
    rewritten_lines = []
    fit_by_id = {job.job_id: fit_call for job, fit_call in zip(jobs, fit_calls, strict=True)}
    for line in fit_text.splitlines():
        if line.startswith("| ") and not line.startswith("| id ") and not line.startswith("|---"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            job_id = int(cells[0])
            cells[8] = fit_by_id[job_id]
            cells[9] = f"fit note {job_id}"
            line = "| " + " | ".join(cells) + " |"
        rewritten_lines.append(line)
    fit_text = "\n".join(rewritten_lines) + "\n"
    fit_path = tmp_path / "round.fit.md"
    fit_path.write_text(fit_text, encoding="utf-8")
    return fit_path, jobs


def _scored_file(tmp_path, scores):
    path = tmp_path / "round.scored.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": job_id,
                    "row_ids": [job_id],
                    "fit_score": score,
                    "base_variant": "backend",
                    "missing_keywords": [],
                    "rationale": "ok",
                }
                for job_id, score in scores
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_compare_fit_calls_treats_apply_and_maybe_positive_at_threshold(tmp_path):
    fit_path, jobs = _write_fit_round(tmp_path, fit_calls=("APPLY", "MAYBE", "SKIP"))
    worksheet = parse_calibration_worksheet(fit_path)
    scores = load_scored_file(_scored_file(tmp_path, [(1, 7.0), (2, 6.5), (3, 7.0)]), jobs)

    report = compare_fit_calls(worksheet, scores, threshold=7.0)

    assert [comparison.kind for comparison in report.comparisons] == [
        ComparisonKind.AGREEMENT,
        ComparisonKind.FALSE_NEGATIVE,
        ComparisonKind.FALSE_POSITIVE,
    ]
    assert report.complete is True


def test_compare_fit_calls_threshold_override_changes_boundary(tmp_path):
    fit_path, jobs = _write_fit_round(tmp_path, fit_calls=("MAYBE", "APPLY", "SKIP"))
    worksheet = parse_calibration_worksheet(fit_path)
    scores = load_scored_file(_scored_file(tmp_path, [(1, 7.0), (2, 7.5), (3, 7.49)]), jobs)

    report = compare_fit_calls(worksheet, scores, threshold=7.5)

    assert [comparison.kind for comparison in report.comparisons] == [
        ComparisonKind.FALSE_NEGATIVE,
        ComparisonKind.AGREEMENT,
        ComparisonKind.AGREEMENT,
    ]


def test_report_output_contains_counts_transitions_changed_rows_and_notes(tmp_path, capsys):
    fit_path, _ = _write_fit_round(tmp_path, fit_calls=("APPLY", "MAYBE", "SKIP"))
    scored_path = _scored_file(tmp_path, [(1, 7.0), (2, 6.5), (3, 7.0)])

    assert calibration_report.main([str(fit_path), "--scored-file", str(scored_path)]) == 0

    output = capsys.readouterr().out
    assert "Fit labels: APPLY=1, MAYBE=1, SKIP=1" in output
    assert "Agreements: 1/3" in output
    assert "False negatives: 1" in output
    assert "False positives: 1" in output
    assert "APPLY -> APPLY: 1" in output
    assert "SKIP -> MAYBE: 1" in output
    assert "MAYBE -> SKIP: 1" in output
    assert "Changed after JD:" in output
    assert "fit note 2" in output


def test_load_scored_file_rejects_coverage_type_and_range_mismatches(tmp_path):
    _, jobs = _write_fit_round(tmp_path)

    cases = [
        [{"id": 1, "row_ids": [1], "fit_score": 7.0}],
        [{"id": 1, "row_ids": [2], "fit_score": 7.0}, {"id": 2, "row_ids": [2], "fit_score": 7.0}, {"id": 3, "row_ids": [3], "fit_score": 7.0}],
        [{"id": 1, "row_ids": [1], "fit_score": True}, {"id": 2, "row_ids": [2], "fit_score": 7.0}, {"id": 3, "row_ids": [3], "fit_score": 7.0}],
        [{"id": 1, "row_ids": [1], "fit_score": 11.0}, {"id": 2, "row_ids": [2], "fit_score": 7.0}, {"id": 3, "row_ids": [3], "fit_score": 7.0}],
        [{"id": 1, "row_ids": [1], "fit_score": 7.0}, {"id": 2, "row_ids": [2], "fit_score": 7.0}],
        [{"id": 1, "row_ids": [1], "fit_score": 7.0}, {"id": 2, "row_ids": [2], "fit_score": 7.0}, {"id": 3, "row_ids": [3], "fit_score": 7.0}, {"id": 4, "row_ids": [4], "fit_score": 7.0}],
    ]
    for idx, payload in enumerate(cases):
        path = tmp_path / f"bad-{idx}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(CalibrationContractError):
            load_scored_file(path, jobs)


def test_db_backed_mode_lists_unscored_and_is_readonly(tmp_path, capsys):
    fit_path, _ = _write_fit_round(tmp_path)
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    for job_id, score in [(1, 7.0), (2, None), (3, 6.0)]:
        conn.execute(
            """
            INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at, status, fit_score)
            VALUES (?, ?, 'C', 'T', 'Remote', ?, 'tracker_vansh', '2026-07-16T00:00:00+00:00', 'SCORED', ?)
            """,
            (job_id, f"k{job_id}", f"https://example.com/{job_id}", score),
        )
    conn.commit()
    conn.close()
    before = db_path.read_bytes()

    assert calibration_report.main([str(fit_path), "--db", str(db_path)]) == 0

    output = capsys.readouterr().out
    assert "Unscored: 1" in output
    assert "id=2" in output
    assert db_path.read_bytes() == before


def test_legacy_worksheet_is_refused_before_db_query(tmp_path, monkeypatch, capsys):
    def fail_if_called(_):
        raise AssertionError("DB should not be opened for legacy refusal")

    monkeypatch.setattr(calibration_report.db, "get_readonly_connection", fail_if_called)

    exit_code = calibration_report.main(["data/calibration/2026-07-12.user.md", "--db", str(tmp_path / "jobs.db")])

    assert exit_code == 2
    assert "legacy interest-only worksheet cannot be used as fit ground truth" in capsys.readouterr().err
