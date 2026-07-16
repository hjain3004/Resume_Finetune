import json
from pathlib import Path

import pytest

from src.calibration import (
    BatchJob,
    CalibrationContractError,
    CalibrationStage,
    RoundMetadata,
    atomic_write_text,
    batch_jobs_to_json,
    load_batch,
    parse_interest_worksheet,
    render_interest_worksheet,
    select_round_jobs,
    sha256_bytes,
    sha256_file,
)


def _batch_obj(job_id: int, *, row_ids: list[int] | None = None, **overrides: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "id": job_id,
        "row_ids": row_ids if row_ids is not None else [job_id],
        "company": f"Company {job_id}",
        "title": f"Software Engineer {job_id}",
        "locations": ["New York, NY", "Remote US"],
        "flags": ["authorization_ambiguous"] if job_id % 2 == 0 else [],
        "jd_quality": "ats",
        "jd_text": f"Complete JD text for job {job_id}",
    }
    obj.update(overrides)
    return obj


def _write_batch(tmp_path, objects: list[dict[str, object]]):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def _valid_jobs(count: int = 14) -> tuple[BatchJob, ...]:
    return tuple(
        BatchJob(
            job_id=i,
            row_ids=(i,),
            company=f"Company {i}",
            title=f"Software Engineer {i}",
            locations=("New York, NY", "Remote US"),
            flags=("authorization_ambiguous",) if i % 2 == 0 else (),
            jd_quality="ats",
            jd_text=f"Complete JD text for job {i}",
        )
        for i in range(1, count + 1)
    )


def test_select_round_jobs_defaults_to_first_12_and_supports_explicit_limit():
    jobs = _valid_jobs(14)

    assert [job.job_id for job in select_round_jobs(jobs)] == list(range(1, 13))
    assert [job.job_id for job in select_round_jobs(jobs, limit=2)] == [1, 2]


@pytest.mark.parametrize("limit", [0, -1, 1.5, "2"])
def test_select_round_jobs_rejects_invalid_limits(limit):
    with pytest.raises(CalibrationContractError, match="limit"):
        select_round_jobs(_valid_jobs(14), limit=limit)  # type: ignore[arg-type]


def test_select_round_jobs_rejects_limit_greater_than_available():
    with pytest.raises(CalibrationContractError, match="available.*2"):
        select_round_jobs(_valid_jobs(2), limit=3)


def test_load_batch_preserves_source_order_and_types(tmp_path):
    path = _write_batch(tmp_path, [_batch_obj(3), _batch_obj(1), _batch_obj(2)])

    jobs = load_batch(path)

    assert [job.job_id for job in jobs] == [3, 1, 2]
    assert jobs[0] == BatchJob(
        job_id=3,
        row_ids=(3,),
        company="Company 3",
        title="Software Engineer 3",
        locations=("New York, NY", "Remote US"),
        flags=(),
        jd_quality="ats",
        jd_text="Complete JD text for job 3",
    )


@pytest.mark.parametrize(
    ("objects", "message"),
    [
        ({"id": 1}, "JSON root"),
        ([_batch_obj(1) | {"unexpected": True}], "extra"),
        ([{k: v for k, v in _batch_obj(1).items() if k != "title"}], "missing"),
        ([_batch_obj(1, id="1")], "id"),
        ([_batch_obj(1, row_ids=[])], "row_ids"),
        ([_batch_obj(1, row_ids=[1, 1])], "duplicate"),
        ([_batch_obj(1, row_ids=[2])], "contain canonical"),
        ([_batch_obj(1), _batch_obj(1)], "duplicate canonical"),
        ([_batch_obj(1, row_ids=[1, 2]), _batch_obj(3, row_ids=[2, 3])], "overlap"),
        ([_batch_obj(1, company="")], "company"),
        ([_batch_obj(1, locations=["Remote", 7])], "locations"),
        ([_batch_obj(1, flags=["ok", 7])], "flags"),
        ([_batch_obj(1, jd_quality="summary")], "jd_quality"),
        ([_batch_obj(1, jd_text=7)], "jd_text"),
    ],
)
def test_load_batch_rejects_invalid_shapes(tmp_path, objects, message):
    path = _write_batch(tmp_path, objects if isinstance(objects, list) else objects)

    with pytest.raises(CalibrationContractError, match=message):
        load_batch(path)


def test_batch_jobs_to_json_is_stable_and_hashable():
    jobs = _valid_jobs(2)

    serialized = batch_jobs_to_json(jobs)

    assert serialized.endswith("\n")
    assert json.loads(serialized) == [
        {
            "id": 1,
            "row_ids": [1],
            "company": "Company 1",
            "title": "Software Engineer 1",
            "locations": ["New York, NY", "Remote US"],
            "flags": [],
            "jd_quality": "ats",
            "jd_text": "Complete JD text for job 1",
        },
        {
            "id": 2,
            "row_ids": [2],
            "company": "Company 2",
            "title": "Software Engineer 2",
            "locations": ["New York, NY", "Remote US"],
            "flags": ["authorization_ambiguous"],
            "jd_quality": "ats",
            "jd_text": "Complete JD text for job 2",
        },
    ]
    assert sha256_bytes(serialized.encode("utf-8")) == sha256_bytes(batch_jobs_to_json(jobs).encode("utf-8"))


def test_atomic_write_text_refuses_existing_destination_and_keeps_bytes(tmp_path):
    path = tmp_path / "artifact.md"
    path.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        atomic_write_text(path, "replacement")

    assert path.read_text(encoding="utf-8") == "original"


def test_atomic_write_text_creates_new_file(tmp_path):
    path = tmp_path / "artifact.md"

    atomic_write_text(path, "new text")

    assert path.read_text(encoding="utf-8") == "new text"


def _metadata(batch_path: Path, *, count: int = 2, **overrides: object) -> RoundMetadata:
    data = {
        "contract_version": 2,
        "stage": CalibrationStage.INTEREST,
        "round_name": "2026-07-16",
        "batch_path": batch_path,
        "batch_sha256": sha256_file(batch_path),
        "canonical_job_count": count,
        "created_at": "2026-07-16T00:00:00+00:00",
    }
    data.update(overrides)
    return RoundMetadata(**data)


def _write_valid_round_batch(tmp_path, jobs: tuple[BatchJob, ...] | None = None) -> tuple[Path, tuple[BatchJob, ...]]:
    jobs = jobs or _valid_jobs(2)
    path = tmp_path / "round.batch.json"
    path.write_text(batch_jobs_to_json(jobs), encoding="utf-8")
    return path, jobs


def _write_interest(tmp_path, text: str) -> Path:
    path = tmp_path / "round.interest.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_render_interest_worksheet_metadata_header_and_blindness(tmp_path):
    batch_path, jobs = _write_valid_round_batch(tmp_path)

    text = render_interest_worksheet(_metadata(batch_path), jobs)

    assert text.startswith("---\n")
    assert "contract_version: 2\n" in text
    assert "stage: interest\n" in text
    assert 'round: "2026-07-16"\n' in text
    assert f'batch_sha256: "{sha256_file(batch_path)}"\n' in text
    assert "canonical_job_count: 2\n" in text
    assert "| id | row_ids | company | title | locations | flags | jd_quality | interest_call | notes |\n" in text
    assert "Complete JD text" not in text
    assert "fit_score" not in text
    assert "fit_call" not in text


def test_interest_worksheet_round_trips_escaped_cells_and_normalizes_calls(tmp_path):
    jobs = (
        BatchJob(
            job_id=1,
            row_ids=(1, 11),
            company="A&B | Labs",
            title="Backend\nEngineer",
            locations=("New York | Remote",),
            flags=("needs&review",),
            jd_quality="ats",
            jd_text="JD hidden",
        ),
        BatchJob(
            job_id=2,
            row_ids=(2,),
            company="Beta",
            title="ML Engineer",
            locations=(),
            flags=(),
            jd_quality="aggregator",
            jd_text="JD hidden 2",
        ),
        BatchJob(
            job_id=3,
            row_ids=(3,),
            company="Gamma",
            title="Data Engineer",
            locations=("Remote",),
            flags=(),
            jd_quality="ats",
            jd_text="JD hidden 3",
        ),
    )
    batch_path, jobs = _write_valid_round_batch(tmp_path, jobs)
    text = render_interest_worksheet(_metadata(batch_path, count=3), jobs)
    text = text.replace("| 1,11 | A&amp;B &#124; Labs | Backend<br>Engineer |", "| 1,11 | A&amp;B &#124; Labs | Backend<br>Engineer |")
    text = text.replace("| ats |  |  |", "| ats | apply | note with &#124; pipe &amp; amp<br>next |", 1)
    text = text.replace("| aggregator |  |  |", "| aggregator |  MAYBE  |  |", 1)
    text = text.replace("| ats |  |  |", "| ats | skip |  |", 1)
    path = _write_interest(tmp_path, text)

    worksheet = parse_interest_worksheet(path, require_complete=True)

    assert [label.interest_call for label in worksheet.labels] == ["APPLY", "MAYBE", "SKIP"]
    assert worksheet.labels[0].job.company == "A&B | Labs"
    assert worksheet.labels[0].job.title == "Backend\nEngineer"
    assert worksheet.labels[0].notes == "note with | pipe & amp\nnext"


def test_parse_interest_accepts_blank_calls_only_when_not_required(tmp_path):
    batch_path, jobs = _write_valid_round_batch(tmp_path)
    path = _write_interest(tmp_path, render_interest_worksheet(_metadata(batch_path), jobs))

    worksheet = parse_interest_worksheet(path, require_complete=False)
    assert [label.interest_call for label in worksheet.labels] == [None, None]

    with pytest.raises(CalibrationContractError, match="job 1.*interest_call"):
        parse_interest_worksheet(path, require_complete=True)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda text: text.replace("batch_sha256:", "batch_hash:"), "metadata"),
        (lambda text: text.replace("contract_version: 2", "contract_version: 1"), "contract_version"),
        (lambda text: text.replace("stage: interest", "stage: fit"), "stage"),
        (lambda text: text.replace("canonical_job_count: 2", "canonical_job_count: 3"), "count"),
        (lambda text: text.replace("| 1 |", "| 2 |", 1), "order"),
        (lambda text: text.replace("| 1 | 1 |", "| 1 | 1,9 |", 1), "row_ids"),
        (lambda text: text.replace("Company 1", "Other Co", 1), "company"),
        (lambda text: text.replace("| interest_call |", "| decision |", 1), "columns"),
        (lambda text: text + "| 99 | 99 | X | Y |  |  | ats | APPLY |  |\n", "count"),
        (lambda text: text.replace("| ats |  |", "| ats | LATER |", 1), "interest_call"),
        (lambda text: text.replace("---\ncontract_version", "--\ncontract_version", 1), "front matter"),
    ],
)
def test_parse_interest_rejects_tampering(tmp_path, mutate, message):
    batch_path, jobs = _write_valid_round_batch(tmp_path)
    text = render_interest_worksheet(_metadata(batch_path), jobs)
    path = _write_interest(tmp_path, mutate(text))

    with pytest.raises(CalibrationContractError, match=message):
        parse_interest_worksheet(path, require_complete=False)


def test_parse_interest_rejects_batch_hash_drift(tmp_path):
    batch_path, jobs = _write_valid_round_batch(tmp_path)
    path = _write_interest(tmp_path, render_interest_worksheet(_metadata(batch_path), jobs))
    batch_path.write_text(batch_jobs_to_json(_valid_jobs(3)), encoding="utf-8")

    with pytest.raises(CalibrationContractError, match="batch.*sha256"):
        parse_interest_worksheet(path, require_complete=False)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"batch_sha256": "ABC"}, "batch_sha256"),
        ({"created_at": "2026-07-16T00:00:00"}, "created_at"),
    ],
)
def test_render_interest_rejects_invalid_metadata(tmp_path, override, message):
    batch_path, jobs = _write_valid_round_batch(tmp_path)

    with pytest.raises(CalibrationContractError, match=message):
        render_interest_worksheet(_metadata(batch_path, **override), jobs)
